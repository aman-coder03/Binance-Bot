#!/usr/bin/env python3
"""
cli.py — Command-line interface for the Binance Futures Bot.
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
    )
    p.add_argument("--api-key", default=None)
    p.add_argument("--api-secret", default=None)
    p.add_argument("--mainnet", action="store_true", help="Use mainnet. REAL MONEY.")
    p.add_argument("--json", action="store_true")

    sub = p.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("market")
    m.add_argument("symbol")
    m.add_argument("side", choices=["BUY", "SELL"])
    m.add_argument("quantity", type=float)
    m.add_argument("--reduce-only", action="store_true")

    lim = sub.add_parser("limit")
    lim.add_argument("symbol")
    lim.add_argument("side", choices=["BUY", "SELL"])
    lim.add_argument("quantity", type=float)
    lim.add_argument("price", type=float)
    lim.add_argument("--tif", default="GTC")
    lim.add_argument("--reduce-only", action="store_true")
    lim.add_argument("--post-only", action="store_true")

    sl = sub.add_parser("stop-limit")
    sl.add_argument("symbol")
    sl.add_argument("side", choices=["BUY", "SELL"])
    sl.add_argument("quantity", type=float)
    sl.add_argument("stop_price", type=float)
    sl.add_argument("limit_price", type=float)
    sl.add_argument("--reduce-only", action="store_true")

    tp = sub.add_parser("take-profit")
    tp.add_argument("symbol")
    tp.add_argument("side", choices=["BUY", "SELL"])
    tp.add_argument("quantity", type=float)
    tp.add_argument("stop_price", type=float)
    tp.add_argument("--no-reduce", action="store_true")

    ts = sub.add_parser("trailing")
    ts.add_argument("symbol")
    ts.add_argument("side", choices=["BUY", "SELL"])
    ts.add_argument("quantity", type=float)
    ts.add_argument("callback_rate", type=float)
    ts.add_argument("--activation-price", type=float, default=None)
    ts.add_argument("--no-reduce", action="store_true")

    oco = sub.add_parser("oco")
    oco.add_argument("symbol")
    oco.add_argument("side", choices=["BUY", "SELL"])
    oco.add_argument("quantity", type=float)
    oco.add_argument("tp_price", type=float)
    oco.add_argument("sl_stop_price", type=float)
    oco.add_argument("sl_limit_price", type=float)
    oco.add_argument("--no-reduce", action="store_true")

    br = sub.add_parser("bracket")
    br.add_argument("symbol")
    br.add_argument("side", choices=["BUY", "SELL"])
    br.add_argument("quantity", type=float)
    br.add_argument("--entry", type=float, required=True, dest="entry_price")
    br.add_argument("--tp", type=float, required=True, dest="take_profit_price")
    br.add_argument("--sl", type=float, required=True, dest="stop_loss_price")
    br.add_argument("--leverage", type=int, default=Config.DEFAULT_LEVERAGE)

    sub.add_parser("balance")

    pos = sub.add_parser("positions")
    pos.add_argument("--symbol", default=None)

    oo = sub.add_parser("open-orders")
    oo.add_argument("--symbol", default=None)

    os_ = sub.add_parser("order-status")
    os_.add_argument("symbol")
    os_.add_argument("order_id", type=int)

    pr = sub.add_parser("price")
    pr.add_argument("symbol")

    kl = sub.add_parser("klines")
    kl.add_argument("symbol")
    kl.add_argument("--interval", default="1m")
    kl.add_argument("--limit", type=int, default=10)

    ca = sub.add_parser("cancel")
    ca.add_argument("symbol")
    ca.add_argument("order_id", type=int)

    caa = sub.add_parser("cancel-all")
    caa.add_argument("symbol")

    cl = sub.add_parser("close")
    cl.add_argument("symbol")

    slev = sub.add_parser("set-leverage")
    slev.add_argument("symbol")
    slev.add_argument("leverage", type=int)

    sub.add_parser("pnl")

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    bot = BinanceFuturesBot(
        api_key=args.api_key,
        api_secret=args.api_secret,
        testnet=not args.mainnet,
    )

    try:
        match args.cmd:
            case "market":
                res = bot.place_market_order(args.symbol, args.side, args.quantity, reduce_only=args.reduce_only)
            case "limit":
                res = bot.place_limit_order(args.symbol, args.side, args.quantity, args.price,
                                            time_in_force=args.tif, reduce_only=args.reduce_only, post_only=args.post_only)
            case "stop-limit":
                res = bot.place_stop_limit_order(args.symbol, args.side, args.quantity,
                                                  args.stop_price, args.limit_price, reduce_only=args.reduce_only)
            case "take-profit":
                res = bot.place_take_profit_market(args.symbol, args.side, args.quantity,
                                                    args.stop_price, reduce_only=not args.no_reduce)
            case "trailing":
                res = bot.place_trailing_stop_market(args.symbol, args.side, args.quantity, args.callback_rate,
                                                      activation_price=args.activation_price, reduce_only=not args.no_reduce)
            case "oco":
                res = bot.place_oco(args.symbol, args.side, args.quantity,
                                    args.tp_price, args.sl_stop_price, args.sl_limit_price, reduce_only=not args.no_reduce)
            case "bracket":
                res = bot.place_bracket_order(args.symbol, args.side, args.quantity,
                                               entry_price=args.entry_price, take_profit_price=args.take_profit_price,
                                               stop_loss_price=args.stop_loss_price, leverage=args.leverage)
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

        print(json.dumps(res, indent=2))

    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as exc:
        log.exception(f"Command '{args.cmd}' failed: {exc}")
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()