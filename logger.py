"""
logger.py — Structured, rotating JSON logger for the trading bot.

Usage:
    from logger import get_logger
    log = get_logger(__name__)
    log.info("Order placed", extra={"order_id": 12345})
"""

import json
import logging
import os
from logging.handlers import RotatingFileHandler

from config import Config


class JsonFormatter(logging.Formatter):
    """Emit each log record as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        # Merge any extra keyword args passed via extra={}
        for key, val in record.__dict__.items():
            if key not in logging.LogRecord.__dict__ and not key.startswith("_"):
                payload[key] = val
        return json.dumps(payload, default=str)


def get_logger(name: str = "bot") -> logging.Logger:
    """Return (or create) a named logger with JSON file + plain-text console handlers."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # already configured

    level = getattr(logging, Config.LOG_LEVEL.upper(), logging.DEBUG)
    logger.setLevel(level)

    # ── File handler (rotating, JSON) ─────────────────────────────────────────
    os.makedirs(os.path.dirname(Config.LOG_FILE), exist_ok=True)
    fh = RotatingFileHandler(
        Config.LOG_FILE,
        maxBytes=Config.LOG_MAX_BYTES,
        backupCount=Config.LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    fh.setFormatter(JsonFormatter())
    fh.setLevel(logging.DEBUG)
    logger.addHandler(fh)

    # ── Console handler (human-readable) ──────────────────────────────────────
    ch = logging.StreamHandler()
    ch.setFormatter(
        logging.Formatter(
            "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    ch.setLevel(getattr(logging, Config.LOG_LEVEL.upper(), logging.INFO))
    logger.addHandler(ch)

    return logger