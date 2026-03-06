"""
tracker.py — PnL tracking, trade statistics, and performance reporting.
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional

from database import get_trade_history, get_total_pnl, get_grid_sessions
from logger import get_logger

log = get_logger(__name__)


class PnLTracker:
    """Aggregates trade history and computes performance metrics."""

    def __init__(self, symbol: Optional[str] = None):
        self.symbol = symbol

    def summary(self) -> Dict:
        """Return a full performance summary."""
        trades = get_trade_history(self.symbol, limit=1000)
        if not trades:
            return {"message": "No trades recorded yet."}

        buys = [t for t in trades if t["side"] == "BUY"]
        sells = [t for t in trades if t["side"] == "SELL"]
        total_pnl = get_total_pnl(self.symbol)
        winning = [t for t in trades if t["realised_pnl"] > 0]
        losing = [t for t in trades if t["realised_pnl"] < 0]

        avg_win = sum(t["realised_pnl"] for t in winning) / len(winning) if winning else 0
        avg_loss = sum(t["realised_pnl"] for t in losing) / len(losing) if losing else 0
        win_rate = (len(winning) / len(trades) * 100) if trades else 0
        profit_factor = abs(avg_win / avg_loss) if avg_loss != 0 else float("inf")

        return {
            "symbol": self.symbol or "ALL",
            "total_trades": len(trades),
            "buy_trades": len(buys),
            "sell_trades": len(sells),
            "winning_trades": len(winning),
            "losing_trades": len(losing),
            "win_rate_pct": round(win_rate, 2),
            "total_realised_pnl_usdt": round(total_pnl, 4),
            "avg_win_usdt": round(avg_win, 4),
            "avg_loss_usdt": round(avg_loss, 4),
            "profit_factor": round(profit_factor, 2),
            "best_trade": round(max((t["realised_pnl"] for t in trades), default=0), 4),
            "worst_trade": round(min((t["realised_pnl"] for t in trades), default=0), 4),
        }

    def recent_trades(self, limit: int = 10) -> List[Dict]:
        """Return the most recent trades formatted for display."""
        trades = get_trade_history(self.symbol, limit=limit)
        result = []
        for t in trades:
            result.append({
                "time": _fmt_time(t["filled_at"]),
                "symbol": t["symbol"],
                "side": t["side"],
                "price": t["fill_price"],
                "qty": t["quantity"],
                "pnl": round(t["realised_pnl"], 4),
                "strategy": t["strategy"],
            })
        return result

    def grid_sessions(self, limit: int = 5) -> List[Dict]:
        """Return recent grid trading sessions."""
        sessions = get_grid_sessions(limit)
        result = []
        for s in sessions:
            duration = None
            if s["started_at"] and s["ended_at"]:
                duration = round((s["ended_at"] - s["started_at"]) / 3600, 2)
            elif s["started_at"]:
                duration = round((time.time() - s["started_at"]) / 3600, 2)

            result.append({
                "id": s["id"],
                "symbol": s["symbol"],
                "range": f"${s['lower_price']} - ${s['upper_price']}",
                "grids": s["num_grids"],
                "total_profit_usdt": round(s["total_profit"], 4),
                "completed_pairs": s["completed_pairs"],
                "duration_hours": duration,
                "status": s["status"],
                "started": _fmt_time(s["started_at"]),
            })
        return result


def _fmt_time(ts: Optional[float]) -> str:
    if not ts:
        return "—"
    import datetime
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
