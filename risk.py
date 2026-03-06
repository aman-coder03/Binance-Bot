"""
risk.py — Risk management, circuit breakers, and position sizing.

Protects your capital by enforcing hard limits on losses,
position sizes, and drawdown.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from logger import get_logger

log = get_logger(__name__)


@dataclass
class RiskConfig:
    max_daily_loss_usdt: float = 100.0      # Stop all trading if daily loss exceeds this
    max_drawdown_pct: float = 5.0           # Stop if account drops X% from session high
    max_position_usdt: float = 10000.0      # Max single position size
    max_open_orders: int = 20               # Hard cap on open orders
    price_deviation_pct: float = 10.0       # Stop grid if price moves X% outside range
    min_balance_usdt: float = 100.0         # Never trade if balance drops below this


class RiskManager:
    """
    Tracks session-level risk metrics and enforces circuit breakers.

    Call check_all() before every order. If it returns False, do not place the order.
    """

    def __init__(self, config: Optional[RiskConfig] = None):
        self.config = config or RiskConfig()
        self._session_start = time.time()
        self._session_high_balance: Optional[float] = None
        self._daily_loss: float = 0.0
        self._daily_reset_time: float = self._next_midnight()
        self._tripped = False
        self._trip_reason: str = ""
        self._trade_count: int = 0

    # ── Main check ────────────────────────────────────────────────────────────

    def check_all(
        self,
        current_balance: float,
        current_price: Optional[float] = None,
        grid_lower: Optional[float] = None,
        grid_upper: Optional[float] = None,
    ) -> bool:
        """
        Run all risk checks. Returns True if safe to trade, False to halt.
        """
        self._maybe_reset_daily()

        if self._tripped:
            log.warning(f"Risk circuit breaker already tripped: {self._trip_reason}")
            return False

        # Update session high watermark
        if self._session_high_balance is None or current_balance > self._session_high_balance:
            self._session_high_balance = current_balance

        # Check minimum balance
        if current_balance < self.config.min_balance_usdt:
            return self._trip(f"Balance ${current_balance:.2f} below minimum ${self.config.min_balance_usdt:.2f}")

        # Check daily loss limit
        if self._daily_loss >= self.config.max_daily_loss_usdt:
            return self._trip(f"Daily loss ${self._daily_loss:.2f} reached limit ${self.config.max_daily_loss_usdt:.2f}")

        # Check drawdown from session high
        if self._session_high_balance and self._session_high_balance > 0:
            drawdown_pct = ((self._session_high_balance - current_balance) / self._session_high_balance) * 100
            if drawdown_pct >= self.config.max_drawdown_pct:
                return self._trip(f"Drawdown {drawdown_pct:.2f}% reached limit {self.config.max_drawdown_pct:.2f}%")

        # Check price deviation from grid range
        if current_price and grid_lower and grid_upper:
            grid_range = grid_upper - grid_lower
            if current_price < grid_lower:
                deviation_pct = ((grid_lower - current_price) / grid_range) * 100
                if deviation_pct >= self.config.price_deviation_pct:
                    return self._trip(f"Price ${current_price} deviated {deviation_pct:.1f}% below grid range")
            elif current_price > grid_upper:
                deviation_pct = ((current_price - grid_upper) / grid_range) * 100
                if deviation_pct >= self.config.price_deviation_pct:
                    return self._trip(f"Price ${current_price} deviated {deviation_pct:.1f}% above grid range")

        return True

    def record_loss(self, amount: float) -> None:
        """Call this when a trade results in a loss."""
        if amount > 0:
            self._daily_loss += amount
            log.info(f"Loss recorded: ${amount:.4f} | Daily total: ${self._daily_loss:.4f}")

    def record_trade(self) -> None:
        self._trade_count += 1

    def reset(self) -> None:
        """Manually reset the circuit breaker (use with caution)."""
        self._tripped = False
        self._trip_reason = ""
        log.info("Risk circuit breaker manually reset.")

    def calculate_position_size(
        self,
        balance: float,
        price: float,
        risk_pct: float = 1.0,
        stop_distance_pct: float = 1.0,
    ) -> float:
        """
        Calculate safe position size using fixed fractional method.

        risk_pct         : % of balance to risk per trade (default 1%)
        stop_distance_pct: distance to stop loss as % of price (default 1%)
        """
        risk_amount = balance * (risk_pct / 100)
        stop_distance = price * (stop_distance_pct / 100)
        if stop_distance == 0:
            return 0.0
        position_size = risk_amount / stop_distance
        # Cap at config max
        max_qty = self.config.max_position_usdt / price
        return round(min(position_size, max_qty), 3)

    # ── Status ────────────────────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "tripped": self._tripped,
            "trip_reason": self._trip_reason,
            "daily_loss_usdt": round(self._daily_loss, 4),
            "max_daily_loss_usdt": self.config.max_daily_loss_usdt,
            "session_high_balance": self._session_high_balance,
            "trade_count": self._trade_count,
            "uptime_seconds": round(time.time() - self._session_start),
        }

    # ── Internal ──────────────────────────────────────────────────────────────

    def _trip(self, reason: str) -> bool:
        self._tripped = True
        self._trip_reason = reason
        log.error(f"RISK CIRCUIT BREAKER TRIPPED: {reason}")
        return False

    def _maybe_reset_daily(self) -> None:
        if time.time() >= self._daily_reset_time:
            log.info(f"Daily loss counter reset. Previous: ${self._daily_loss:.4f}")
            self._daily_loss = 0.0
            self._daily_reset_time = self._next_midnight()

    @staticmethod
    def _next_midnight() -> float:
        import datetime
        now = datetime.datetime.now()
        midnight = (now + datetime.timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return midnight.timestamp()
