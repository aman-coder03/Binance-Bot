"""
strategy/grid.py — Grid Trading Strategy.

How it works:
  1. You define a price range (low, high) and number of grid levels.
  2. The bot divides the range into equal intervals and places
     buy orders at every level below current price and sell orders
     at every level above.
  3. When a buy fills  → place a sell one grid above.
  4. When a sell fills → place a buy one grid below.
  5. Repeat forever, capturing the spread on every move.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from logger import get_logger

log = get_logger(__name__)


@dataclass
class GridLevel:
    price: float
    side: str           # 'BUY' or 'SELL'
    order_id: Optional[int] = None
    filled: bool = False
    fill_price: Optional[float] = None
    fill_time: Optional[float] = None


@dataclass
class GridConfig:
    symbol: str
    lower_price: float
    upper_price: float
    num_grids: int
    quantity_per_grid: float
    leverage: int = 1

    def __post_init__(self):
        if self.lower_price >= self.upper_price:
            raise ValueError("lower_price must be less than upper_price.")
        if self.num_grids < 2:
            raise ValueError("num_grids must be at least 2.")
        if self.quantity_per_grid <= 0:
            raise ValueError("quantity_per_grid must be positive.")

    @property
    def grid_interval(self) -> float:
        return (self.upper_price - self.lower_price) / self.num_grids

    @property
    def grid_prices(self) -> List[float]:
        prices = []
        for i in range(self.num_grids + 1):
            prices.append(round(self.lower_price + i * self.grid_interval, 2))
        return prices

    def total_investment(self) -> float:
        """Approximate USDT needed to fund all buy orders."""
        buy_levels = self.num_grids // 2
        return buy_levels * self.quantity_per_grid * self.lower_price


class GridStrategy:
    """
    Manages the state of a grid trading strategy.

    This class is pure state management — it does NOT call the exchange.
    The monitor loop calls the exchange and updates this object.
    """

    def __init__(self, config: GridConfig):
        self.config = config
        self.levels: List[GridLevel] = []
        self.order_map: Dict[int, GridLevel] = {}   # order_id -> GridLevel
        self.is_running = False
        self.start_time: Optional[float] = None
        self.total_profit: float = 0.0
        self.completed_pairs: int = 0
        self._build_levels()

    def _build_levels(self) -> None:
        """Create grid levels — no orders placed yet."""
        self.levels = []
        for price in self.config.grid_prices:
            level = GridLevel(price=price, side="BUY")  # side set at runtime
            self.levels.append(level)
        log.info(
            f"Grid built: {len(self.levels)} levels | "
            f"interval=${self.config.grid_interval:.2f} | "
            f"range=${self.config.lower_price}-${self.config.upper_price}"
        )

    def get_initial_orders(self, current_price: float) -> List[Tuple[str, float]]:
        """
        Return list of (side, price) tuples for initial order placement.
        Levels below current price → BUY
        Levels above current price → SELL
        """
        orders = []
        for level in self.levels:
            if level.price < current_price:
                orders.append(("BUY", level.price))
                level.side = "BUY"
            elif level.price > current_price:
                orders.append(("SELL", level.price))
                level.side = "SELL"
            # skip the level closest to current price
        return orders

    def register_order(self, order_id: int, price: float) -> None:
        """Called after an order is successfully placed on the exchange."""
        for level in self.levels:
            if abs(level.price - price) < 0.01:
                level.order_id = order_id
                self.order_map[order_id] = level
                return

    def on_fill(self, order_id: int, fill_price: float) -> Optional[Tuple[str, float]]:
        """
        Called when an order fills.

        Returns (side, price) of the counter-order to place,
        or None if no counter-order needed.
        """
        level = self.order_map.get(order_id)
        if not level:
            log.warning(f"Fill received for unknown order {order_id}")
            return None

        level.filled = True
        level.fill_price = fill_price
        level.fill_time = time.time()

        interval = self.config.grid_interval

        if level.side == "BUY":
            # Place sell one grid above
            counter_price = round(fill_price + interval, 2)
            if counter_price <= self.config.upper_price:
                log.info(f"BUY filled at {fill_price} → placing SELL at {counter_price}")
                return ("SELL", counter_price)

        elif level.side == "SELL":
            # Place buy one grid below
            counter_price = round(fill_price - interval, 2)
            if counter_price >= self.config.lower_price:
                # Profit on this completed pair
                profit = (fill_price - (fill_price - interval)) * self.config.quantity_per_grid
                self.total_profit += profit
                self.completed_pairs += 1
                log.info(
                    f"SELL filled at {fill_price} → placing BUY at {counter_price} | "
                    f"pair profit=${profit:.4f} | total=${self.total_profit:.4f}"
                )
                return ("BUY", counter_price)

        return None

    def is_price_in_range(self, price: float) -> bool:
        return self.config.lower_price <= price <= self.config.upper_price

    def summary(self) -> Dict:
        return {
            "symbol": self.config.symbol,
            "range": f"${self.config.lower_price} - ${self.config.upper_price}",
            "grid_interval": f"${self.config.grid_interval:.2f}",
            "num_grids": self.config.num_grids,
            "quantity_per_grid": self.config.quantity_per_grid,
            "completed_pairs": self.completed_pairs,
            "total_profit_usdt": round(self.total_profit, 4),
            "is_running": self.is_running,
            "uptime_seconds": round(time.time() - self.start_time) if self.start_time else 0,
        }


def suggest_grid_range(prices: List[float], margin: float = 0.05) -> Tuple[float, float]:
    """
    Suggest a grid range based on recent price history.

    Takes the min/max of recent prices and adds a margin buffer.
    """
    low = min(prices)
    high = max(prices)
    buffer = (high - low) * margin
    return round(low - buffer, 2), round(high + buffer, 2)
