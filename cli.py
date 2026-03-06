#!/usr/bin/env python3
"""
cli.py — Command-line interface for the Binance Futures Bot.

Usage examples
──────────────
  # Market buy 0.01 BTC
  python cli.py market BTCUSDT BUY 0.01

  # Limit sell 0.01 BTC at 70000
  python cli.py limit BTCUSDT SELL 0.01 70000

  # Stop-limit buy: trigger 65000, fill at 65100
  python cli.py stop-limit BTCUSDT BUY 0.01 65000 65100

  # OCO bracket: TP=72000, SL trigger=62000, SL limit=61900
  python cli.py oco BTCUSDT BUY 0.01 72000 62000 61900

  # Full bracket (entry + TP + SL in one command)
  python cli.py bracket BTCUSDT BUY 0.01 --entry 68000 --tp 72000 --sl 65000

  # Trailing stop: 1.5% callback
  python cli.py trailing BTCUSDT SELL 0.01 1.5

  # Account balance
  python cli.py balance

  # Open positions
  python cli.py positions

  # Get ticker price
  python cli.py price BTCUSDT

  # Cancel a specific order
  python cli.py cancel BTCUSDT 123456789

  # Cancel all orders for a symbol
  python cli.py cancel-all BTCUSDT

  # Close position
  python cli.py close BTCUSDT

  # Set leverage
  python cli.py set-leverage BTCUSDT 10

Credentials are read from environment variables or a .env file:
  BINANCE_API_KEY=...
  BINANCE_API_SECRET=...
  USE_TESTNET=true   (default true)
"""

from __future__ import annotations

import argparse
import json
import sys

from bot import BinanceFuturesBot
from config import Config
from logger import get_logger

log = get_logger("cli")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python cli.py",
        description="Binance USDT-M Futures Trading Bot CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--api-key", default=None, help="Override BINANCE_API_KEY env var.")
    p.add_argument("--api-secret", default=None, help="Override BINANCE_API_SECRET env var.")
    p.add_argument(
        "--mainnet",
        action="store_true",
        help="Use mainnet (default is testnet). REAL MONEY – use with care.",
    )
    p.add_argument("--json", action="store_true", help="Output raw JSON (machine-readable).")

    sub = p.add_subparsers(dest="cmd", required=True)

    # ── market ────────────────────────────────────────────────────────────────
    m = sub.add_parser("market", help="Place a MARKET order.")
    m.add_argument("symbol")
    m.add_argument("side", choices=["BUY", "SELL"])
    m.add_argument("quantity", type=float)
    m.add_argument("--reduce-only", action="store_true")

    # ── limit ─────────────────────────────────────────────────────────────────
    lim = sub.add_parser("limit", help="Place a LIMIT order.")
    lim.add_argument("symbol")
    lim.add_argument("side", choices=["BUY", "SELL"])
    lim.add_argument("quantity", type=float)
    lim.add_argument("price", type=float)
    lim.add_argument("--tif", default="GTC", help="Time-in-force (GTC/IOC/FOK).")
    lim.add_argument("--reduce-only", action="store_true")
    lim.add_argument("--post-only", action="store_true", help="Maker-only (GTX).")

    # ── stop-limit ────────────────────────────────────────────────────────────
    sl = sub.add_parser("stop-limit", help="Place a STOP-LIMIT order (trigger → limit).")
    sl.add_argument("symbol")
    sl.add_argument("side", choices=["BUY", "SELL"])
    sl.add_argument("quantity", type=float)
    sl.add_argument("stop_price", type=float, help="Trigger price.")
    sl.add_argument("limit_price", type=float, help="Limit price after trigger.")
    sl.add_argument("--reduce-only", action="store_true")

    # ── take-profit ───────────────────────────────────────────────────────────
    tp = sub.add_parser("take-profit", help="Place a TAKE_PROFIT_MARKET order.")
    tp.add_argument("symbol")
    tp.add_argument("side", choices=["BUY", "SELL"])
    tp.add_argument("quantity", type=float)
    tp.add_argument("stop_price", type=float, help="Trigger price.")
    tp.add_argument("--no-reduce", action="store_true", help="Do NOT set reduceOnly.")

    # ── trailing ──────────────────────────────────────────────────────────────
    ts = sub.add_parser("trailing", help="Place a TRAILING_STOP_MARKET order.")
    ts.add_argument("symbol")
    ts.add_argument("side", choices=["BUY", "SELL"])
    ts.add_argument("quantity", type=float)
    ts.add_argument("callback_rate", type=float, help="Trailing % (0.1-5.0).")
    ts.add_argument("--activation-price", type=float, default=None)
    ts.add_argument("--no-reduce", action="store_true")

    # ── oco ───────────────────────────────────────────────────────────────────
    oco = sub.add_parser("oco", help="Place simulated OCO (TP limit + SL stop-limit).")
    oco.add_argument("symbol")
    oco.add_argument("side", choices=["BUY", "SELL"])
    oco.add_argument("quantity", type=float)
    oco.add_argument("tp_price", type=float, help="Take-profit price.")
    oco.add_argument("sl_stop_price", type=float, help="Stop-loss trigger price.")
    oco.add_argument("sl_limit_price", type=float, help="Stop-loss limit price.")
    oco.add_argument("--no-reduce", action="store_true")

    # ── bracket ───────────────────────────────────────────────────────────────
    br = sub.add_parser("bracket", help="Full bracket: entry limit + TP + SL.")
    br.add_argument("symbol")
    br.add_argument("side", choices=["BUY", "SELL"])
    br.add_argument("quantity", type=float)
    br.add_argument("--entry", type=float, required=True, dest="entry_price")
    br.add_argument("--tp", type=float, required=True, dest="take_profit_price")
    br.add_argument("--sl", type=float, required=True, dest="stop_loss_price")
    br.add_argument("--leverage", type=int, default=Config.DEFAULT_LEVERAGE)

    # ── balance ───────────────────────────────────────────────────────────────
    sub.add_parser("balance", help="Show account balance.")

    # ── positions ─────────────────────────────────────────────────────────────
    pos = sub.add_parser("positions", help="Show open positions.")
    pos.add_argument("--symbol", default=None)

    # ── open-orders ───────────────────────────────────────────────────────────
    oo = sub.add_parser("open-orders", help="List open orders.")
    oo.add_argument("--symbol", default=None)

    # ── order-status ──────────────────────────────────────────────────────────
    os_ = sub.add_parser("order-status", help="Query a specific order.")
    os_.add_argument("symbol")
    os_.add_argument("order_id", type=int)

    # ── price ─────────────────────────────────────────────────────────────────
    pr = sub.add_parser("price", help="Get current ticker price.")
    pr.add_argument("symbol")

    # ── klines ────────────────────────────────────────────────────────────────
    kl = sub.add_parser("klines", help="Fetch OHLCV candlestick data.")
    kl.add_argument("symbol")
    kl.add_argument("--interval", default="1m")
    kl.add_argument("--limit", type=int, default=10)

    # ── cancel ────────────────────────────────────────────────────────────────
    ca = sub.add_parser("cancel", help="Cancel a specific order.")
    ca.add_argument("symbol")
    ca.add_argument("order_id", type=int)

    # ── cancel-all ────────────────────────────────────────────────────────────
    caa = sub.add_parser("cancel-all", help="Cancel all orders for a symbol.")
    caa.add_argument("symbol")

    # ── close ─────────────────────────────────────────────────────────────────
    cl = sub.add_parser("close", help="Close position for a symbol (market order).")
    cl.add_argument("symbol")

    # ── set-leverage ──────────────────────────────────────────────────────────
    slev = sub.add_parser("set-leverage", help="Set leverage for a symbol.")
    slev.add_argument("symbol")
    slev.add_argument("leverage", type=int)

    # ── pnl ───────────────────────────────────────────────────────────────────
    sub.add_parser("pnl", help="Show unrealised PnL for all open positions.")

    return p


def _out(data, as_json: bool) -> None:
    """Pretty-print result."""
    if as_json:
        print(json.dumps(data, indent=2))
    else:
        print(json.dumps(data, indent=2))  # always JSON for now – easy to parse


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    # Initialise bot
    bot = BinanceFuturesBot(
        api_key=args.api_key,
        api_secret=args.api_secret,
        testnet=not args.mainnet,
    )

    try:
        match args.cmd:
            case "market":
                res = bot.place_market_order(
                    args.symbol, args.side, args.quantity,
                    reduce_only=args.reduce_only,
                )
            case "limit":
                res = bot.place_limit_order(
                    args.symbol, args.side, args.quantity, args.price,
                    time_in_force=args.tif,
                    reduce_only=args.reduce_only,
                    post_only=args.post_only,
                )
            case "stop-limit":
                res = bot.place_stop_limit_order(
                    args.symbol, args.side, args.quantity,
                    args.stop_price, args.limit_price,
                    reduce_only=args.reduce_only,
                )
            case "take-profit":
                res = bot.place_take_profit_market(
                    args.symbol, args.side, args.quantity, args.stop_price,
                    reduce_only=not args.no_reduce,
                )
            case "trailing":
                res = bot.place_trailing_stop_market(
                    args.symbol, args.side, args.quantity, args.callback_rate,
                    activation_price=args.activation_price,
                    reduce_only=not args.no_reduce,
                )
            case "oco":
                res = bot.place_oco(
                    args.symbol, args.side, args.quantity,
                    args.tp_price, args.sl_stop_price, args.sl_limit_price,
                    reduce_only=not args.no_reduce,
                )
            case "bracket":
                res = bot.place_bracket_order(
                    args.symbol, args.side, args.quantity,
                    entry_price=args.entry_price,
                    take_profit_price=args.take_profit_price,
                    stop_loss_price=args.stop_loss_price,
                    leverage=args.leverage,
                )
            case "balance":
                res = bot.get_account_balance()
            case "positions":
                res = bot.get_positions(args.symbol)
            case "open-orders":
                res = bot.get_open_orders(args.symbol)
            case "order-status":
                res = bot.get_order_status(args.symbol, args.order_id)
            case "price":
                res = {"symbol": args.symbol, "price": bot.get_ticker_price(args.symbol)}
            case "klines":
                res = bot.get_klines(args.symbol, args.interval, args.limit)
            case "cancel":
                res = bot.cancel_order(args.symbol, args.order_id)
            case "cancel-all":
                res = bot.cancel_all_orders(args.symbol)
            case "close":
                res = bot.close_position(args.symbol)
            case "set-leverage":
                res = bot.set_leverage(args.symbol, args.leverage)
            case "pnl":
                res = bot.get_unrealised_pnl()
            case _:
                parser.error(f"Unknown command: {args.cmd}")

        _out(res, args.json)

    except KeyboardInterrupt:
        log.info("Interrupted by user.")
        sys.exit(0)
    except Exception as exc:
        log.exception(f"Command '{args.cmd}' failed: {exc}")
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()