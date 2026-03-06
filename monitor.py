"""
monitor.py — Background monitor loop for grid trading.

Responsibilities:
  - Poll open orders and detect fills
  - Place counter-orders on fill
  - Update database
  - Check risk limits on every cycle
  - Emit Telegram alerts on key events
  - Handle graceful shutdown on Ctrl+C or risk trip
"""

from __future__ import annotations

import signal
import time
from typing import Optional

from bot import BinanceFuturesBot
from config import Config
from database import (
    init_db,
    record_order,
    record_fill,
    start_grid_session,
    update_grid_session,
    end_grid_session,
    update_order_status,
)
from exceptions import APIError, RiskLimitError
from logger import get_logger
from risk import RiskConfig, RiskManager
from strategy.grid import GridConfig, GridStrategy, suggest_grid_range
from utils import send_telegram_alert

log = get_logger(__name__)


class GridMonitor:
    """
    Runs the full grid trading lifecycle:
      setup → place initial orders → poll → react to fills → shutdown
    """

    POLL_INTERVAL: float = 3.0      # seconds between order status checks
    RISK_CHECK_INTERVAL: float = 10.0  # seconds between risk checks

    def __init__(
        self,
        grid_config: GridConfig,
        risk_config: Optional[RiskConfig] = None,
        testnet: bool = True,
    ):
        self.grid_config = grid_config
        self.bot = BinanceFuturesBot(testnet=testnet)
        self.strategy = GridStrategy(grid_config)
        self.risk = RiskManager(risk_config or RiskConfig())
        self._running = False
        self._session_id: Optional[int] = None
        self._last_risk_check: float = 0.0

        init_db()
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)

    # ── Public entry point ────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the grid monitor. Blocks until stopped."""
        log.info(f"Starting grid monitor | {self.grid_config.symbol} | "
                 f"range ${self.grid_config.lower_price}-${self.grid_config.upper_price}")

        send_telegram_alert(
            f"Grid bot started\n"
            f"Symbol: {self.grid_config.symbol}\n"
            f"Range: ${self.grid_config.lower_price} - ${self.grid_config.upper_price}\n"
            f"Grids: {self.grid_config.num_grids}\n"
            f"Qty per grid: {self.grid_config.quantity_per_grid}"
        )

        # Set leverage
        self.bot.set_leverage(self.grid_config.symbol, self.grid_config.leverage)

        # Record session in DB
        self._session_id = start_grid_session(
            self.grid_config.symbol,
            self.grid_config.lower_price,
            self.grid_config.upper_price,
            self.grid_config.num_grids,
            self.grid_config.quantity_per_grid,
        )

        # Get current price and place initial orders
        current_price = self.bot.get_ticker_price(self.grid_config.symbol)
        log.info(f"Current price: ${current_price}")
        self._place_initial_orders(current_price)

        self.strategy.is_running = True
        self.strategy.start_time = time.time()
        self._running = True

        # Main loop
        try:
            self._loop()
        finally:
            self._shutdown()

    # ── Initial order placement ───────────────────────────────────────────────

    def _place_initial_orders(self, current_price: float) -> None:
        orders = self.strategy.get_initial_orders(current_price)
        log.info(f"Placing {len(orders)} initial grid orders...")

        for side, price in orders:
            try:
                res = self.bot.place_limit_order(
                    symbol=self.grid_config.symbol,
                    side=side,
                    quantity=self.grid_config.quantity_per_grid,
                    price=price,
                    time_in_force="GTC",
                )
                order_id = res.get("orderId")
                self.strategy.register_order(order_id, price)
                record_order(
                    order_id=order_id,
                    symbol=self.grid_config.symbol,
                    side=side,
                    order_type="LIMIT",
                    quantity=self.grid_config.quantity_per_grid,
                    price=price,
                    strategy="grid",
                )
                log.debug(f"Placed {side} @ ${price} | id={order_id}")
                time.sleep(0.1)  # small delay to avoid rate limits

            except (APIError, RiskLimitError) as exc:
                log.error(f"Failed to place {side} @ ${price}: {exc}")

    # ── Main polling loop ─────────────────────────────────────────────────────

    def _loop(self) -> None:
        log.info("Monitor loop running. Press Ctrl+C to stop.")

        while self._running:
            try:
                self._check_fills()

                # Periodic risk check
                if time.time() - self._last_risk_check >= self.RISK_CHECK_INTERVAL:
                    self._run_risk_check()
                    self._last_risk_check = time.time()

                # Update DB with latest stats
                if self._session_id:
                    update_grid_session(
                        self._session_id,
                        self.strategy.total_profit,
                        self.strategy.completed_pairs,
                    )

            except Exception as exc:
                log.error(f"Monitor loop error: {exc}", exc_info=True)

            time.sleep(self.POLL_INTERVAL)

    # ── Fill detection ────────────────────────────────────────────────────────

    def _check_fills(self) -> None:
        """Check all tracked orders and react to any fills."""
        order_ids = list(self.strategy.order_map.keys())
        if not order_ids:
            return

        for order_id in order_ids:
            level = self.strategy.order_map.get(order_id)
            if not level or level.filled:
                continue

            try:
                status = self.bot.get_order_status(self.grid_config.symbol, order_id)
                order_status = status.get("status")

                if order_status == "FILLED":
                    fill_price = float(status.get("avgPrice", status.get("price", 0)))
                    qty = float(status.get("executedQty", self.grid_config.quantity_per_grid))

                    log.info(f"Fill detected: {level.side} @ ${fill_price} | order {order_id}")

                    # Record fill in DB
                    record_fill(
                        order_id=str(order_id),
                        symbol=self.grid_config.symbol,
                        side=level.side,
                        fill_price=fill_price,
                        quantity=qty,
                        strategy="grid",
                    )
                    update_order_status(str(order_id), "FILLED")

                    # Alert
                    send_telegram_alert(
                        f"Grid fill: {level.side} {self.grid_config.symbol} "
                        f"@ ${fill_price}\nTotal profit: ${self.strategy.total_profit:.4f}"
                    )

                    # Get counter-order
                    counter = self.strategy.on_fill(order_id, fill_price)
                    if counter:
                        self._place_counter_order(counter[0], counter[1])

                elif order_status in ("CANCELED", "EXPIRED", "REJECTED"):
                    log.warning(f"Order {order_id} is {order_status} — removing from tracking")
                    update_order_status(str(order_id), order_status)
                    self.strategy.order_map.pop(order_id, None)

            except APIError as exc:
                log.error(f"Error checking order {order_id}: {exc}")

            time.sleep(0.05)  # small delay between status checks

    def _place_counter_order(self, side: str, price: float) -> None:
        """Place the counter-order after a fill."""
        try:
            res = self.bot.place_limit_order(
                symbol=self.grid_config.symbol,
                side=side,
                quantity=self.grid_config.quantity_per_grid,
                price=price,
                time_in_force="GTC",
            )
            order_id = res.get("orderId")
            self.strategy.register_order(order_id, price)
            record_order(
                order_id=order_id,
                symbol=self.grid_config.symbol,
                side=side,
                order_type="LIMIT",
                quantity=self.grid_config.quantity_per_grid,
                price=price,
                strategy="grid",
            )
            log.info(f"Counter-order placed: {side} @ ${price} | id={order_id}")

        except (APIError, RiskLimitError) as exc:
            log.error(f"Failed to place counter-order {side} @ ${price}: {exc}")

    # ── Risk check ────────────────────────────────────────────────────────────

    def _run_risk_check(self) -> None:
        try:
            balances = self.bot.get_account_balance()
            usdt_balance = next(
                (float(b["balance"]) for b in balances if b["asset"] == "USDT"), 0.0
            )
            current_price = self.bot.get_ticker_price(self.grid_config.symbol)

            safe = self.risk.check_all(
                current_balance=usdt_balance,
                current_price=current_price,
                grid_lower=self.grid_config.lower_price,
                grid_upper=self.grid_config.upper_price,
            )

            if not safe:
                log.error(f"Risk check failed: {self.risk._trip_reason}. Stopping grid.")
                send_telegram_alert(
                    f"RISK ALERT — Grid stopped\nReason: {self.risk._trip_reason}"
                )
                self._running = False

        except Exception as exc:
            log.error(f"Risk check error: {exc}")

    # ── Shutdown ──────────────────────────────────────────────────────────────

    def _shutdown(self) -> None:
        log.info("Shutting down grid monitor...")
        self._running = False
        self.strategy.is_running = False

        # Cancel all open grid orders
        try:
            self.bot.cancel_all_orders(self.grid_config.symbol)
            log.info("All grid orders cancelled.")
        except Exception as exc:
            log.error(f"Error cancelling orders on shutdown: {exc}")

        # Close DB session
        if self._session_id:
            end_grid_session(
                self._session_id,
                self.strategy.total_profit,
                self.strategy.completed_pairs,
            )

        summary = self.strategy.summary()
        log.info(f"Grid session ended | {summary}")
        send_telegram_alert(
            f"Grid bot stopped\n"
            f"Symbol: {self.grid_config.symbol}\n"
            f"Completed pairs: {self.strategy.completed_pairs}\n"
            f"Total profit: ${self.strategy.total_profit:.4f}"
        )

    def _handle_shutdown(self, signum, frame) -> None:
        log.info(f"Signal {signum} received — initiating shutdown.")
        self._running = False
