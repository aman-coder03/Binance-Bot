"""
dashboard.py — Live terminal dashboard.

Shows real-time:
  - Current price
  - Account balance
  - Open positions and PnL
  - Grid status (if running)
  - Recent fills
  - Risk status

Run standalone:  python dashboard.py BTCUSDT
"""

from __future__ import annotations

import json
import os
import time
from typing import Optional

from bot import BinanceFuturesBot
from config import Config
from database import get_trade_history, get_total_pnl
from logger import get_logger

log = get_logger(__name__)

REFRESH_INTERVAL = 5  # seconds


def clear() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def _bar(value: float, max_value: float, width: int = 20, fill: str = "█") -> str:
    if max_value == 0:
        return "─" * width
    filled = int((value / max_value) * width)
    return fill * filled + "─" * (width - filled)


def render_dashboard(bot: BinanceFuturesBot, symbol: str) -> None:
    """Render a single frame of the dashboard."""
    clear()

    now = time.strftime("%Y-%m-%d %H:%M:%S")
    mode = "TESTNET" if Config.USE_TESTNET else "MAINNET"

    print("=" * 60)
    print(f"  Binance Futures Bot Dashboard  |  {mode}  |  {now}")
    print("=" * 60)

    # ── Price ─────────────────────────────────────────────────────────────────
    try:
        price = bot.get_ticker_price(symbol)
        print(f"\n  {symbol:<12}  ${price:,.2f}")
    except Exception as exc:
        print(f"\n  Price fetch error: {exc}")
        price = None

    # ── Balance ───────────────────────────────────────────────────────────────
    print("\n  BALANCE")
    print("  " + "─" * 40)
    try:
        balances = bot.get_account_balance()
        for b in balances:
            bal = float(b["balance"])
            avail = float(b["availableBalance"])
            print(f"  {b['asset']:<6}  Balance: {bal:>12.4f}  Available: {avail:>12.4f}")
    except Exception as exc:
        print(f"  Error: {exc}")

    # ── Positions ─────────────────────────────────────────────────────────────
    print("\n  OPEN POSITIONS")
    print("  " + "─" * 40)
    try:
        positions = bot.get_positions()
        if not positions:
            print("  No open positions.")
        for p in positions:
            pnl = float(p["unRealizedProfit"])
            pnl_str = f"+${pnl:.4f}" if pnl >= 0 else f"-${abs(pnl):.4f}"
            pnl_indicator = "▲" if pnl >= 0 else "▼"
            print(
                f"  {p['symbol']:<10}  Amt: {p['positionAmt']:>8}  "
                f"Entry: ${float(p['entryPrice']):,.2f}  "
                f"PnL: {pnl_indicator} {pnl_str}  "
                f"Lev: {p['leverage']}x"
            )
    except Exception as exc:
        print(f"  Error: {exc}")

    # ── Recent fills ──────────────────────────────────────────────────────────
    print("\n  RECENT FILLS  (from database)")
    print("  " + "─" * 40)
    try:
        fills = get_trade_history(symbol, limit=5)
        if not fills:
            print("  No fills recorded yet.")
        for f in fills:
            import datetime
            ts = datetime.datetime.fromtimestamp(f["filled_at"]).strftime("%H:%M:%S")
            pnl = f["realised_pnl"]
            pnl_str = f"+{pnl:.4f}" if pnl >= 0 else f"{pnl:.4f}"
            print(
                f"  {ts}  {f['side']:<4}  @ ${f['fill_price']:,.2f}  "
                f"qty={f['quantity']}  pnl={pnl_str}"
            )
        total = get_total_pnl(symbol)
        print(f"\n  Total realised PnL: ${total:.4f}")
    except Exception as exc:
        print(f"  Error: {exc}")

    # ── Open orders ───────────────────────────────────────────────────────────
    print("\n  OPEN ORDERS")
    print("  " + "─" * 40)
    try:
        orders = bot.get_open_orders(symbol)
        if not orders:
            print("  No open orders.")
        else:
            buy_orders = [o for o in orders if o["side"] == "BUY"]
            sell_orders = [o for o in orders if o["side"] == "SELL"]
            print(f"  BUY orders:  {len(buy_orders)}")
            print(f"  SELL orders: {len(sell_orders)}")
            print(f"  Total:       {len(orders)}")
    except Exception as exc:
        print(f"  Error: {exc}")

    print("\n" + "=" * 60)
    print(f"  Refreshing every {REFRESH_INTERVAL}s  |  Ctrl+C to exit")
    print("=" * 60)


def run_dashboard(symbol: str) -> None:
    bot = BinanceFuturesBot()
    print(f"Starting dashboard for {symbol}... (Ctrl+C to exit)")
    try:
        while True:
            render_dashboard(bot, symbol)
            time.sleep(REFRESH_INTERVAL)
    except KeyboardInterrupt:
        print("\nDashboard stopped.")


if __name__ == "__main__":
    import sys
    sym = sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT"
    run_dashboard(sym)
