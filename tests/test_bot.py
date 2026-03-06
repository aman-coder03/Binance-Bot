"""
tests/test_bot.py — Unit tests for utils and bot logic.

Run with:  pytest tests/ -v
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from exceptions import ValidationError, RiskLimitError, APIError
from utils import (
    validate_symbol,
    validate_quantity,
    validate_price,
    validate_side,
    validate_leverage,
    sign_payload,
)


# ─────────────────────────────────────────────────────────────────────────────
# Validators
# ─────────────────────────────────────────────────────────────────────────────

class TestValidateSymbol:
    def test_valid(self):
        assert validate_symbol("btcusdt") == "BTCUSDT"
        assert validate_symbol("ETHUSDT") == "ETHUSDT"
        assert validate_symbol("  bnbusdt  ") == "BNBUSDT"

    def test_too_short(self):
        with pytest.raises(ValidationError):
            validate_symbol("BT")

    def test_non_string(self):
        with pytest.raises(ValidationError):
            validate_symbol(123)

    def test_special_chars(self):
        with pytest.raises(ValidationError):
            validate_symbol("BTC-USDT")


class TestValidateQuantity:
    def test_valid_float(self):
        assert validate_quantity(0.01) == 0.01
        assert validate_quantity("1.5") == 1.5

    def test_zero(self):
        with pytest.raises(ValidationError):
            validate_quantity(0)

    def test_negative(self):
        with pytest.raises(ValidationError):
            validate_quantity(-1)

    def test_non_numeric(self):
        with pytest.raises(ValidationError):
            validate_quantity("abc")


class TestValidatePrice:
    def test_valid(self):
        assert validate_price(50000.0) == 50000.0
        assert validate_price("30000") == 30000.0

    def test_zero(self):
        with pytest.raises(ValidationError):
            validate_price(0)

    def test_negative(self):
        with pytest.raises(ValidationError):
            validate_price(-100)


class TestValidateSide:
    def test_buy(self):
        assert validate_side("buy") == "BUY"
        assert validate_side("BUY") == "BUY"

    def test_sell(self):
        assert validate_side("SELL") == "SELL"

    def test_invalid(self):
        with pytest.raises(ValidationError):
            validate_side("LONG")


class TestValidateLeverage:
    def test_valid(self):
        assert validate_leverage(10) == 10
        assert validate_leverage("5") == 5

    def test_too_high(self):
        with pytest.raises(ValidationError):
            validate_leverage(200)

    def test_zero(self):
        with pytest.raises(ValidationError):
            validate_leverage(0)


# ─────────────────────────────────────────────────────────────────────────────
# HMAC signing
# ─────────────────────────────────────────────────────────────────────────────

class TestSignPayload:
    def test_signature_present(self):
        result = sign_payload({"symbol": "BTCUSDT", "quantity": "0.01"}, "mysecret")
        assert "signature=" in result

    def test_deterministic_for_same_payload_secret(self):
        payload1 = {"symbol": "BTCUSDT", "timestamp": 1234567890}
        payload2 = {"symbol": "BTCUSDT", "timestamp": 1234567890}
        r1 = sign_payload(payload1, "secret")
        r2 = sign_payload(payload2, "secret")
        assert r1 == r2

    def test_different_secrets_produce_different_sigs(self):
        payload = {"symbol": "BTCUSDT", "timestamp": 1234567890}
        r1 = sign_payload(dict(payload), "secret1")
        r2 = sign_payload(dict(payload), "secret2")
        assert r1 != r2


# ─────────────────────────────────────────────────────────────────────────────
# Bot order methods (mocked HTTP)
# ─────────────────────────────────────────────────────────────────────────────

MOCK_ORDER_RESPONSE = {
    "orderId": 99999,
    "symbol": "BTCUSDT",
    "status": "NEW",
    "side": "BUY",
    "type": "MARKET",
    "origQty": "0.01",
}


@pytest.fixture
def bot():
    """Return a BinanceFuturesBot with dummy credentials."""
    with patch("utils.Config.API_KEY", "dummy_key"), \
         patch("utils.Config.API_SECRET", "dummy_secret"):
        from bot import BinanceFuturesBot
        return BinanceFuturesBot(api_key="dummy_key", api_secret="dummy_secret", testnet=True)


class TestMarketOrder:
    def test_valid_market_buy(self, bot):
        with patch.object(bot, "_post", return_value=MOCK_ORDER_RESPONSE), \
             patch.object(bot, "get_open_orders", return_value=[]):
            res = bot.place_market_order("BTCUSDT", "BUY", 0.01)
            assert res["orderId"] == 99999

    def test_invalid_symbol_raises(self, bot):
        with pytest.raises(ValidationError):
            bot.place_market_order("!!", "BUY", 0.01)

    def test_invalid_side_raises(self, bot):
        with pytest.raises(ValidationError):
            bot.place_market_order("BTCUSDT", "LONG", 0.01)

    def test_zero_quantity_raises(self, bot):
        with pytest.raises(ValidationError):
            bot.place_market_order("BTCUSDT", "BUY", 0)


class TestLimitOrder:
    def test_valid_limit_sell(self, bot):
        with patch.object(bot, "_post", return_value=MOCK_ORDER_RESPONSE), \
             patch.object(bot, "get_open_orders", return_value=[]):
            res = bot.place_limit_order("BTCUSDT", "SELL", 0.01, 70000.0)
            assert res["orderId"] == 99999

    def test_zero_price_raises(self, bot):
        with pytest.raises(ValidationError):
            bot.place_limit_order("BTCUSDT", "BUY", 0.01, 0)


class TestRiskChecks:
    def test_too_many_open_orders(self, bot):
        from config import Config
        fake_orders = [{"orderId": i} for i in range(Config.MAX_OPEN_ORDERS)]
        with patch.object(bot, "get_open_orders", return_value=fake_orders):
            with pytest.raises(RiskLimitError):
                bot._check_open_orders("BTCUSDT")

    def test_position_size_too_large(self, bot):
        from config import Config
        qty = Config.MAX_POSITION_USDT + 1
        price = 1.0  # notional = qty * 1.0 > MAX
        with pytest.raises(RiskLimitError):
            bot._check_position_size("BTCUSDT", qty, price)


class TestCancelOrder:
    def test_cancel_returns_response(self, bot):
        mock_resp = {"orderId": 12345, "status": "CANCELED"}
        with patch.object(bot, "_delete", return_value=mock_resp):
            res = bot.cancel_order("BTCUSDT", 12345)
            assert res["status"] == "CANCELED"


class TestOCO:
    def test_oco_returns_both_legs(self, bot):
        tp_resp = {**MOCK_ORDER_RESPONSE, "orderId": 1, "type": "TAKE_PROFIT"}
        sl_resp = {**MOCK_ORDER_RESPONSE, "orderId": 2, "type": "STOP"}

        call_count = 0

        def mock_place(payload):
            nonlocal call_count
            call_count += 1
            return tp_resp if call_count == 1 else sl_resp

        with patch.object(bot, "_place_order", side_effect=mock_place):
            res = bot.place_oco("BTCUSDT", "BUY", 0.01, 72000, 62000, 61900)
            assert "take_profit" in res
            assert "stop_loss" in res
            assert res["take_profit"]["orderId"] == 1
            assert res["stop_loss"]["orderId"] == 2