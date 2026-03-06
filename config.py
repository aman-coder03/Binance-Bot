"""
config.py — Centralised configuration for Binance Futures Trading Bot.
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    API_KEY: str = os.getenv("BINANCE_API_KEY", "")
    API_SECRET: str = os.getenv("BINANCE_API_SECRET", "")

    USE_TESTNET: bool = os.getenv("USE_TESTNET", "true").lower() == "true"
    FUTURES_TESTNET_BASE: str = "https://testnet.binancefuture.com"
    FUTURES_MAINNET_BASE: str = "https://fapi.binance.com"

    @classmethod
    def base_url(cls) -> str:
        return cls.FUTURES_TESTNET_BASE if cls.USE_TESTNET else cls.FUTURES_MAINNET_BASE

    REQUEST_TIMEOUT: int = int(os.getenv("REQUEST_TIMEOUT", "10"))
    MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "3"))
    RETRY_BACKOFF: float = float(os.getenv("RETRY_BACKOFF", "1.5"))

    RATE_LIMIT_CALLS: int = int(os.getenv("RATE_LIMIT_CALLS", "10"))
    RATE_LIMIT_PERIOD: float = float(os.getenv("RATE_LIMIT_PERIOD", "1.0"))

    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "DEBUG")
    LOG_FILE: str = os.getenv("LOG_FILE", "logs/bot.log")
    LOG_MAX_BYTES: int = int(os.getenv("LOG_MAX_BYTES", str(10 * 1024 * 1024)))
    LOG_BACKUP_COUNT: int = int(os.getenv("LOG_BACKUP_COUNT", "5"))

    MAX_POSITION_USDT: float = float(os.getenv("MAX_POSITION_USDT", "10000.0"))
    DEFAULT_LEVERAGE: int = int(os.getenv("DEFAULT_LEVERAGE", "1"))
    MAX_OPEN_ORDERS: int = int(os.getenv("MAX_OPEN_ORDERS", "10"))

    DEFAULT_TIME_IN_FORCE: str = os.getenv("DEFAULT_TIME_IN_FORCE", "GTC")

    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

    @classmethod
    def validate(cls) -> None:
        if not cls.API_KEY or not cls.API_SECRET:
            raise ValueError(
                "BINANCE_API_KEY and BINANCE_API_SECRET must be set."
            )
        if cls.DEFAULT_LEVERAGE < 1 or cls.DEFAULT_LEVERAGE > 125:
            raise ValueError("DEFAULT_LEVERAGE must be between 1 and 125.")
        if cls.MAX_POSITION_USDT <= 0:
            raise ValueError("MAX_POSITION_USDT must be positive.")