"""
utils.py — HTTP transport, HMAC signing, validation, rate limiting, alerting.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import time
import urllib.parse
from threading import Lock
from typing import Any, Dict, Optional

import requests

from config import Config
from exceptions import APIError, NetworkError, RateLimitError, ValidationError
from logger import get_logger

log = get_logger(__name__)

_SYMBOL_RE = re.compile(r"^[A-Z0-9]{6,20}$")


class _TokenBucket:
    def __init__(self, capacity: int, refill_period: float):
        self._capacity = capacity
        self._tokens = capacity
        self._refill_period = refill_period
        self._lock = Lock()
        self._last_refill = time.monotonic()

    def acquire(self) -> None:
        with self._lock:
            self._refill()
            if self._tokens < 1:
                sleep_for = self._refill_period - (time.monotonic() - self._last_refill)
                if sleep_for > 0:
                    time.sleep(sleep_for)
                self._refill()
            self._tokens -= 1

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        if elapsed >= self._refill_period:
            self._tokens = self._capacity
            self._last_refill = now


_rate_limiter = _TokenBucket(Config.RATE_LIMIT_CALLS, Config.RATE_LIMIT_PERIOD)


def sign_payload(payload: Dict[str, Any], api_secret: str) -> str:
    if "timestamp" not in payload:
        payload["timestamp"] = int(time.time() * 1000)
    query = urllib.parse.urlencode(payload)
    sig = hmac.new(
        api_secret.encode("utf-8"),
        query.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{query}&signature={sig}"


def send_signed_request(
    method: str,
    base: str,
    path: str,
    payload: Dict[str, Any],
    api_key: str,
    api_secret: str,
    timeout: int = Config.REQUEST_TIMEOUT,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    url = base.rstrip("/") + path
    headers = {
        "X-MBX-APIKEY": api_key,
        "Content-Type": "application/x-www-form-urlencoded",
    }
    _method = method.upper()
    if _method not in ("GET", "POST", "DELETE"):
        raise ValueError(f"Unsupported HTTP method: {method}")

    attempt = 0
    delay = Config.RETRY_BACKOFF
    last_exc: Exception = RuntimeError("No attempts made")

    while attempt < Config.MAX_RETRIES:
        attempt += 1
        _rate_limiter.acquire()

        _payload = dict(payload)
        _payload["timestamp"] = int(time.time() * 1000)
        signed_qs = sign_payload(_payload, api_secret)

        log.debug(f"-> {_method} {path} (attempt {attempt}/{Config.MAX_RETRIES})")

        try:
            if _method == "POST":
                resp = requests.post(url, data=signed_qs, headers=headers, timeout=timeout)
            elif _method == "DELETE":
                resp = requests.delete(url + "?" + signed_qs, headers=headers, timeout=timeout)
            else:
                full_qs = signed_qs
                if params:
                    full_qs += "&" + urllib.parse.urlencode(params)
                resp = requests.get(url + "?" + full_qs, headers=headers, timeout=timeout)

        except requests.exceptions.Timeout as exc:
            log.warning(f"Request timeout on attempt {attempt}: {exc}")
            last_exc = NetworkError(f"Timeout: {exc}")
            time.sleep(delay)
            delay *= Config.RETRY_BACKOFF
            continue
        except requests.exceptions.ConnectionError as exc:
            log.warning(f"Connection error on attempt {attempt}: {exc}")
            last_exc = NetworkError(f"Connection error: {exc}")
            time.sleep(delay)
            delay *= Config.RETRY_BACKOFF
            continue

        status = resp.status_code
        try:
            body = resp.json()
        except Exception:
            body = {"raw": resp.text}

        if status in (429, 418):
            retry_after = float(resp.headers.get("Retry-After", delay))
            log.warning(f"Rate limited by Binance (HTTP {status}). Sleeping {retry_after}s")
            time.sleep(retry_after)
            last_exc = RateLimitError(f"Rate limited: {body}", status_code=status)
            continue

        if status >= 400:
            bcode = body.get("code") if isinstance(body, dict) else None
            bmsg = body.get("msg", str(body)) if isinstance(body, dict) else str(body)
            err = APIError(bmsg, status_code=status, binance_code=bcode)
            log.error(f"API error: {err}")
            raise err

        log.debug(f"<- {status} {path}")
        return body

    raise last_exc


def send_public_request(
    method: str,
    base: str,
    path: str,
    params: Optional[Dict[str, Any]] = None,
    timeout: int = Config.REQUEST_TIMEOUT,
) -> Any:
    _rate_limiter.acquire()
    url = base.rstrip("/") + path
    try:
        resp = requests.request(method.upper(), url, params=params, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.Timeout as exc:
        raise NetworkError(f"Public request timeout: {exc}") from exc
    except requests.exceptions.HTTPError as exc:
        raise APIError(str(exc), status_code=exc.response.status_code) from exc


def validate_symbol(sym: Any) -> str:
    if not isinstance(sym, str):
        raise ValidationError(f"Symbol must be a string, got {type(sym).__name__}.")
    sym = sym.upper().strip()
    if not _SYMBOL_RE.match(sym):
        raise ValidationError(f"Invalid symbol '{sym}'.")
    return sym


def validate_quantity(q: Any) -> float:
    try:
        qn = float(q)
    except (TypeError, ValueError):
        raise ValidationError(f"Quantity '{q}' is not a valid number.")
    if qn <= 0:
        raise ValidationError(f"Quantity must be positive, got {qn}.")
    return qn


def validate_price(p: Any, label: str = "Price") -> float:
    try:
        pn = float(p)
    except (TypeError, ValueError):
        raise ValidationError(f"{label} '{p}' is not a valid number.")
    if pn <= 0:
        raise ValidationError(f"{label} must be positive, got {pn}.")
    return pn


def validate_side(side: Any) -> str:
    if not isinstance(side, str):
        raise ValidationError(f"Side must be a string, got {type(side).__name__}.")
    s = side.upper().strip()
    if s not in ("BUY", "SELL"):
        raise ValidationError(f"Side must be 'BUY' or 'SELL', got '{side}'.")
    return s


def validate_leverage(lev: Any) -> int:
    try:
        ln = int(lev)
    except (TypeError, ValueError):
        raise ValidationError(f"Leverage '{lev}' is not a valid integer.")
    if not 1 <= ln <= 125:
        raise ValidationError(f"Leverage must be 1-125, got {ln}.")
    return ln


def send_telegram_alert(message: str) -> None:
    token = Config.TELEGRAM_BOT_TOKEN
    chat_id = Config.TELEGRAM_CHAT_ID
    if not token or not chat_id:
        return
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(
            url,
            json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
            timeout=5,
        )
    except Exception as exc:
        log.warning(f"Failed to send Telegram alert: {exc}")