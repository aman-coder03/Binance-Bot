"""
grid_runner.py — Entry point for running the grid trading strategy.

Usage examples:
  # Basic grid on BTCUSDT
  python grid_runner.py BTCUSDT --lower 60000 --upper 70000 --grids 10 --qty 0.001

  # Auto-detect range from recent price history
  python grid_runner.py BTCUSDT --auto-range --grids 10 --qty 0.001

  # With custom risk settings
  python grid_runner.py BTCUSDT --lower 60000 --upper 70000 --grids 10 --qty 0.001
      --max-daily-loss 50 --max-drawdown 3

  # Show suggested range without starting
  python grid_runner.py BTCUSDT --suggest-range

  # View performance stats
  python grid_runner.py --stats
  python grid_runner.py --stats --symbol BTCUSDT
"""

from __future__ import annotations

import argparse
import json
import sys

from bot import BinanceFuturesBot
from database import init_db
from logger import get_logger
from monitor import GridMonitor
from risk import RiskConfig
from strategy.grid import GridConfig, suggest_grid_range
from tracker import PnLTracker

log = get_logger("grid_runner")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python grid_runner.py",
        description="Grid Trading Strategy Runner",
    )

    p.add_argument("symbol", nargs="?", default=None, help="Trading pair e.g. BTCUSDT")
    p.add_argument("--lower", type=float, help="Grid lower price boundary")
    p.add_argument("--upper", type=float, help="Grid upper price boundary")
    p.add_argument("--grids", type=int, default=10, help="Number of grid levels (default 10)")
    p.add_argument("--qty", type=float, required=False, help="Quantity per grid order")
    p.add_argument("--leverage", type=int, default=1, help="Leverage (default 1)")

    p.add_argument("--auto-range", action="store_true",
                   help="Auto-detect price range from recent klines")
    p.add_argument("--suggest-range", action="store_true",
                   help="Print suggested range and exit without trading")

    p.add_argument("--mainnet", action="store_true",
                   help="Use mainnet. REAL MONEY — use with caution.")

    # Risk settings
    p.add_argument("--max-daily-loss", type=float, default=100.0,
                   help="Max daily loss in USDT before stopping (default 100)")
    p.add_argument("--max-drawdown", type=float, default=5.0,
                   help="Max drawdown %% from session high before stopping (default 5)")
    p.add_argument("--min-balance", type=float, default=100.0,
                   help="Minimum USDT balance to keep trading (default 100)")

    # Stats / reporting
    p.add_argument("--stats", action="store_true", help="Show performance stats and exit")
    p.add_argument("--history", action="store_true", help="Show recent trade history and exit")
    p.add_argument("--sessions", action="store_true", help="Show grid sessions and exit")

    return p


def get_auto_range(bot: BinanceFuturesBot, symbol: str, grids: int) -> tuple:
    """Fetch recent klines and suggest a grid range."""
    log.info(f"Fetching recent price history for {symbol}...")
    klines = bot.get_klines(symbol, interval="1h", limit=168)  # 1 week of hourly
    closes = [float(k[4]) for k in klines]  # index 4 = close price
    lower, upper = suggest_grid_range(closes, margin=0.03)
    log.info(f"Suggested range: ${lower} - ${upper}")
    return lower, upper


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    init_db()
    bot = BinanceFuturesBot(testnet=not args.mainnet)

    # ── Stats / reporting modes ───────────────────────────────────────────────
    if args.stats:
        tracker = PnLTracker(args.symbol)
        print(json.dumps(tracker.summary(), indent=2))
        return

    if args.history:
        tracker = PnLTracker(args.symbol)
        print(json.dumps(tracker.recent_trades(limit=20), indent=2))
        return

    if args.sessions:
        tracker = PnLTracker()
        print(json.dumps(tracker.grid_sessions(limit=10), indent=2))
        return

    # ── Validate required args for trading ───────────────────────────────────
    if not args.symbol:
        parser.error("symbol is required when not using --stats/--history/--sessions")
    if not args.qty:
        parser.error("--qty is required")

    symbol = args.symbol.upper()

    # ── Suggest range mode ────────────────────────────────────────────────────
    if args.suggest_range:
        lower, upper = get_auto_range(bot, symbol, args.grids)
        interval = (upper - lower) / args.grids
        print(f"\nSuggested grid configuration for {symbol}:")
        print(f"  Lower price  : ${lower:,.2f}")
        print(f"  Upper price  : ${upper:,.2f}")
        print(f"  Grid interval: ${interval:,.2f}")
        print(f"  Grids        : {args.grids}")
        print(f"\nRun with:")
        print(f"  python grid_runner.py {symbol} --lower {lower} --upper {upper} --grids {args.grids} --qty {args.qty or 0.001}")
        return

    # ── Determine price range ─────────────────────────────────────────────────
    if args.auto_range:
        lower, upper = get_auto_range(bot, symbol, args.grids)
    else:
        if not args.lower or not args.upper:
            parser.error("--lower and --upper are required (or use --auto-range)")
        lower, upper = args.lower, args.upper

    # ── Build configs ─────────────────────────────────────────────────────────
    grid_config = GridConfig(
        symbol=symbol,
        lower_price=lower,
        upper_price=upper,
        num_grids=args.grids,
        quantity_per_grid=args.qty,
        leverage=args.leverage,
    )

    risk_config = RiskConfig(
        max_daily_loss_usdt=args.max_daily_loss,
        max_drawdown_pct=args.max_drawdown,
        min_balance_usdt=args.min_balance,
    )

    # ── Print summary before starting ─────────────────────────────────────────
    interval = (upper - lower) / args.grids
    total_investment = grid_config.total_investment()
    print(f"\nGrid Configuration")
    print(f"  Symbol         : {symbol}")
    print(f"  Range          : ${lower:,.2f} - ${upper:,.2f}")
    print(f"  Grid interval  : ${interval:,.2f}")
    print(f"  Grids          : {args.grids}")
    print(f"  Qty per grid   : {args.qty}")
    print(f"  Leverage       : {args.leverage}x")
    print(f"  Est. investment: ~${total_investment:,.2f} USDT")
    print(f"\nRisk Settings")
    print(f"  Max daily loss : ${risk_config.max_daily_loss_usdt}")
    print(f"  Max drawdown   : {risk_config.max_drawdown_pct}%")
    print(f"  Min balance    : ${risk_config.min_balance_usdt}")
    print(f"\nNetwork: {'TESTNET' if not args.mainnet else 'MAINNET *** REAL MONEY ***'}")
    print()

    confirm = input("Start grid? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("Aborted.")
        return

    # ── Start ─────────────────────────────────────────────────────────────────
    monitor = GridMonitor(
        grid_config=grid_config,
        risk_config=risk_config,
        testnet=not args.mainnet,
    )
    monitor.start()


if __name__ == "__main__":
    main()
