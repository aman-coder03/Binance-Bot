"""
exceptions.py — Custom exception hierarchy for the trading bot.
"""


class BotError(Exception):
    """Base class for all bot errors."""


class ConfigurationError(BotError):
    """Raised when configuration is invalid or incomplete."""


class ValidationError(BotError):
    """Raised when order parameters fail validation."""


class APIError(BotError):
    """Raised when the Binance REST API returns an error response."""

    def __init__(self, message: str, status_code=None, binance_code=None):
        super().__init__(message)
        self.status_code = status_code
        self.binance_code = binance_code

    def __str__(self) -> str:
        parts = [super().__str__()]
        if self.status_code:
            parts.append(f"HTTP {self.status_code}")
        if self.binance_code:
            parts.append(f"Binance code {self.binance_code}")
        return " | ".join(parts)


class RateLimitError(APIError):
    """Raised when we hit the Binance rate limit (HTTP 429 / 418)."""


class NetworkError(BotError):
    """Raised on connection timeouts or unreachable host."""


class RiskLimitError(BotError):
    """Raised when an order would exceed configured risk limits."""


class OrderError(BotError):
    """Raised when an order operation fails for business-logic reasons."""