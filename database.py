"""
database.py — SQLite trade history and audit trail.

Every order placed, filled, or cancelled is recorded here.
Gives you a full audit trail and data for PnL analysis.
"""

from __future__ import annotations

import sqlite3
import time
import os
from typing import Dict, List, Optional

from logger import get_logger

log = get_logger(__name__)

DB_PATH = os.getenv("DB_PATH", "data/trades.db")


def _get_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create tables if they do not exist."""
    with _get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS orders (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id      TEXT,
                symbol        TEXT,
                side          TEXT,
                type          TEXT,
                quantity      REAL,
                price         REAL,
                status        TEXT,
                strategy      TEXT,
                created_at    REAL,
                updated_at    REAL
            );

            CREATE TABLE IF NOT EXISTS fills (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id      TEXT,
                symbol        TEXT,
                side          TEXT,
                fill_price    REAL,
                quantity      REAL,
                commission    REAL,
                realised_pnl  REAL,
                strategy      TEXT,
                filled_at     REAL
            );

            CREATE TABLE IF NOT EXISTS grid_sessions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol          TEXT,
                lower_price     REAL,
                upper_price     REAL,
                num_grids       INTEGER,
                qty_per_grid    REAL,
                total_profit    REAL DEFAULT 0,
                completed_pairs INTEGER DEFAULT 0,
                started_at      REAL,
                ended_at        REAL,
                status          TEXT DEFAULT 'running'
            );

            CREATE TABLE IF NOT EXISTS daily_pnl (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                date        TEXT,
                symbol      TEXT,
                realised    REAL DEFAULT 0,
                unrealised  REAL DEFAULT 0,
                num_trades  INTEGER DEFAULT 0
            );
        """)
    log.info("Database initialised.")


def record_order(
    order_id: str,
    symbol: str,
    side: str,
    order_type: str,
    quantity: float,
    price: float,
    status: str = "NEW",
    strategy: str = "manual",
) -> None:
    now = time.time()
    with _get_conn() as conn:
        conn.execute(
            """INSERT INTO orders
               (order_id, symbol, side, type, quantity, price, status, strategy, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (str(order_id), symbol, side, order_type, quantity, price, status, strategy, now, now),
        )
    log.debug(f"Order recorded: {order_id} {symbol} {side} {order_type}")


def update_order_status(order_id: str, status: str) -> None:
    with _get_conn() as conn:
        conn.execute(
            "UPDATE orders SET status=?, updated_at=? WHERE order_id=?",
            (status, time.time(), str(order_id)),
        )


def record_fill(
    order_id: str,
    symbol: str,
    side: str,
    fill_price: float,
    quantity: float,
    commission: float = 0.0,
    realised_pnl: float = 0.0,
    strategy: str = "manual",
) -> None:
    with _get_conn() as conn:
        conn.execute(
            """INSERT INTO fills
               (order_id, symbol, side, fill_price, quantity, commission, realised_pnl, strategy, filled_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (str(order_id), symbol, side, fill_price, quantity, commission, realised_pnl, strategy, time.time()),
        )
    log.debug(f"Fill recorded: {order_id} {symbol} {side} @ {fill_price}")


def start_grid_session(
    symbol: str,
    lower_price: float,
    upper_price: float,
    num_grids: int,
    qty_per_grid: float,
) -> int:
    with _get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO grid_sessions
               (symbol, lower_price, upper_price, num_grids, qty_per_grid, started_at)
               VALUES (?,?,?,?,?,?)""",
            (symbol, lower_price, upper_price, num_grids, qty_per_grid, time.time()),
        )
        return cur.lastrowid


def update_grid_session(session_id: int, total_profit: float, completed_pairs: int) -> None:
    with _get_conn() as conn:
        conn.execute(
            "UPDATE grid_sessions SET total_profit=?, completed_pairs=? WHERE id=?",
            (total_profit, completed_pairs, session_id),
        )


def end_grid_session(session_id: int, total_profit: float, completed_pairs: int) -> None:
    with _get_conn() as conn:
        conn.execute(
            """UPDATE grid_sessions
               SET total_profit=?, completed_pairs=?, ended_at=?, status='stopped'
               WHERE id=?""",
            (total_profit, completed_pairs, time.time(), session_id),
        )


def get_trade_history(symbol: Optional[str] = None, limit: int = 50) -> List[Dict]:
    with _get_conn() as conn:
        if symbol:
            rows = conn.execute(
                "SELECT * FROM fills WHERE symbol=? ORDER BY filled_at DESC LIMIT ?",
                (symbol, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM fills ORDER BY filled_at DESC LIMIT ?", (limit,)
            ).fetchall()
    return [dict(r) for r in rows]


def get_total_pnl(symbol: Optional[str] = None) -> float:
    with _get_conn() as conn:
        if symbol:
            row = conn.execute(
                "SELECT SUM(realised_pnl) as total FROM fills WHERE symbol=?", (symbol,)
            ).fetchone()
        else:
            row = conn.execute("SELECT SUM(realised_pnl) as total FROM fills").fetchone()
    return row["total"] or 0.0


def get_grid_sessions(limit: int = 10) -> List[Dict]:
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM grid_sessions ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]
