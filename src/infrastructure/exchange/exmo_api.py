# src/infrastructure/exchange/exmo_api.py
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import requests

# Пытаемся взять ваш ретраер из соседнего модуля; если его нет — используем простой фоллбэк
try:
    from .http_utils import with_retries  # type: ignore
except Exception:  # pragma: no cover
    def with_retries(fn, *, attempts: int = 3, on_retry=None):
        for i in range(max(1, int(attempts))):
            try:
                return fn()
            except Exception as e:
                if i < attempts - 1:
                    if on_retry:
                        try:
                            on_retry(i, e)
                        except Exception:
                            pass
                    time.sleep(0.5 * (i + 1))
                else:
                    raise

log = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Вспомогалки
# ──────────────────────────────────────────────────────────────────────────────

def _is_debug() -> bool:
    v = os.getenv("EXMO_DEBUG", "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _dbg(msg: str) -> None:
    if _is_debug():
        log.debug(msg)


def _ts_utc() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def _map_resolution(tf: str | int) -> int:
    """
    EXMO /v1.1/candles_history принимает resolution в МИНУТАХ (int).
    Поддержим строки '1m','3m','5m','15m','30m','1h','4h','1d' и т.п., либо int.
    """
    if isinstance(tf, int):
        return max(1, tf)
    s = str(tf).strip().lower()
    if s.endswith("m"):
        return max(1, int(s[:-1] or "1"))
    if s.endswith("h"):
        return max(1, int(s[:-1] or "1") * 60)
    if s.endswith("d"):
        return max(1, int(s[:-1] or "1") * 60 * 24)
    try:
        return max(1, int(s))
    except Exception:
        return 1


def _redact(s: str, keep: int = 4) -> str:
    if not s:
        return ""
    if len(s) <= keep:
        return "*" * len(s)
    return s[:keep] + "…" + "*" * (len(s) - keep)


# ──────────────────────────────────────────────────────────────────────────────
# Модель кредов (есть тут для совместимости с вашим импортом из app.py)
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class ExmoCredentials:
    api_key: str = ""
    api_secret: str = ""


# ──────────────────────────────────────────────────────────────────────────────
# Клиент EXMO v1.1 (публичные + приватные read-only)
# ──────────────────────────────────────────────────────────────────────────────
class ExmoApi:
    base_url: str = "https://api.exmo.com/v1.1"

    def __init__(
        self,
        creds_or_key: ExmoCredentials | None = None,
        *,
        api_key: str = "",
        api_secret: str = "",
        allow_trading: bool = False,
        timeout: float = 10.0,
        retry_attempts: int = 3,
    ):
        # Совместимость: можно передавать либо объект ExmoCredentials, либо пары строк.
        if isinstance(creds_or_key, ExmoCredentials):
            self.api_key = creds_or_key.api_key or api_key
            self.api_secret = creds_or_key.api_secret or api_secret
        else:
            self.api_key = api_key
            self.api_secret = api_secret

        self.allow_trading = allow_trading  # зарезервировано
        self.timeout = timeout
        self.retry_attempts = retry_attempts
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "clean-crypto-bot/0.1"})

    # ── HTTP низкоуровневые ───────────────────────────────────────────────────
    def _make_url(self, path: str) -> str:
        p = path.lstrip("/")
        if p.startswith("v1.1/"):  # защита от двойного v1.1
            p = p[5:]
        return f"{self.base_url}/{p}"

    def _public_get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = self._make_url(path)

        def _do():
            if _is_debug():
                _dbg(f"[EXMO] → GET {url} params={params}")
            r = self._session.get(url, params=params, timeout=self.timeout)
            if _is_debug():
                _dbg(f"[EXMO] ← {path} status={r.status_code}")
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict) and data.get("error"):
                # старые эндпоинты могли вернуть {"error":"..."}
                err = data.get("error")
                _dbg(f"[EXMO]   error: {err}")
                raise RuntimeError(f"EXMO error: {err}")
            if _is_debug():
                try:
                    body_preview = json.dumps(data, ensure_ascii=False)[:800]
                    _dbg(f"[EXMO]   body: {body_preview}{'...(trunc)' if len(body_preview)==800 else ''}")
                except Exception:
                    pass
            return data

        def _on_retry(i, err):
            print(f"[EXMO]   retry {i+1}: {type(err).__name__}: {err}")

        return with_retries(_do, attempts=self.retry_attempts, on_retry=_on_retry)

    def _private_post(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = self._make_url(path)
        params = dict(params or {})
        params["nonce"] = int(time.time() * 1000)

        # Form-encoded body по ключам в алфавитном порядке
        body = "&".join(f"{k}={params[k]}" for k in sorted(params))
        secret = (self.api_secret or "").encode("utf-8")
        # EXMO v1.1: Sign = hex(HMAC_SHA512(body, secret))
        sign = hmac.new(secret, body.encode("utf-8"), hashlib.sha512).hexdigest()

        headers = {
            "Key": self.api_key or "",
            "Sign": sign,
            "Content-Type": "application/x-www-form-urlencoded",
        }

        def _do():
            if _is_debug():
                _dbg(f"[EXMO] → POST {url} body={body} Key={_redact(self.api_key)}")
            r = self._session.post(url, data=params, headers=headers, timeout=self.timeout)
            if _is_debug():
                _dbg(f"[EXMO] ← {path} status={r.status_code}")
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict) and not data.get("success", True):
                err = data.get("error") or "unknown error"
                _dbg(f"[EXMO]   error: {err}")
                raise RuntimeError(f"EXMO error: {err}")
            return data

        def _on_retry(i, err):
            print(f"[EXMO]   retry {i+1}: {type(err).__name__}: {err}")

        return with_retries(_do, attempts=self.retry_attempts, on_retry=_on_retry)

    # ── Публичные ─────────────────────────────────────────────────────────────
    def ping(self) -> bool:
        try:
            _ = self.ticker()
            return True
        except Exception:
            return False

    def ticker(self) -> Dict[str, Any]:
        return self._public_get("ticker")

    def ticker_pair(self, pair: str) -> Dict[str, Any]:
        tk = self.ticker()
        return tk.get(pair, {}) if isinstance(tk, dict) else {}

    def order_book(self, pair: str, *, limit: int = 20) -> Dict[str, Any]:
        return self._public_get("order_book", params={"pair": pair, "limit": limit})

    def trades(self, pair: str, *, limit: int = 100) -> List[Dict[str, Any]]:
        data = self._public_get("trades", params={"pair": pair, "limit": limit})
        rows = data.get(pair) if isinstance(data, dict) else None
        return rows if isinstance(rows, list) else []

    # Прямой доступ к /candles_history (для совместимости со старым CLI)
    def candles_history(self, *, symbol: str, resolution: int, ts_from: int, ts_to: int) -> Dict[str, Any]:
        params = {"symbol": symbol, "resolution": int(resolution), "from": int(ts_from), "to": int(ts_to)}
        _dbg(f"[EXMO] probe: candles_history params= {params}")
        return self._public_get("candles_history", params=params)

    # ── Свечи (нормализованные) ───────────────────────────────────────────────
    def _calc_from_to_by_limit(self, resolution_min: int, limit: int) -> Tuple[int, int]:
        to_ts = _ts_utc()
        span_sec = max(1, resolution_min) * 60 * max(1, int(limit))
        frm_ts = to_ts - span_sec
        return frm_ts, to_ts

    def candles(self, *, pair: str, timeframe: str | int, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Возвращает список словарей вида:
          [{ts, open, high, low, close, volume}, ...]
        На базе /candles_history.
        """
        res = _map_resolution(timeframe)
        frm, to = self._calc_from_to_by_limit(res, limit)
        data = self.candles_history(symbol=pair, resolution=res, ts_from=frm, ts_to=to)
        raw = data.get("candles") if isinstance(data, dict) else None
        if not isinstance(raw, list):
            _dbg("[EXMO]   candles: empty rows")
            return []

        out: List[Dict[str, Any]] = []
        for r in raw:
            try:
                ts = int(int(r["t"]) // 1000)
                out.append({
                    "ts": ts,
                    "open": str(r["o"]),
                    "high": str(r["h"]),
                    "low": str(r["l"]),
                    "close": str(r["c"]),
                    "volume": str(r.get("v", "")),
                })
            except Exception:
                continue
        _dbg(f"[EXMO]   candles OK rows={len(out)}")
        return out

    def kline(self, *, pair: str, timeframe: str | int, limit: int = 100) -> List[Dict[str, Any]]:
        # Совместимое имя — те же данные, что и candles()
        return self.candles(pair=pair, timeframe=timeframe, limit=limit)

    def ohlcv(self, *, pair: str, timeframe: str | int, limit: int = 100) -> List[List[Any]]:
        rows = self.candles(pair=pair, timeframe=timeframe, limit=limit)
        out: List[List[Any]] = []
        for r in rows:
            try:
                out.append([
                    int(r["ts"]),
                    str(r["open"]),
                    str(r["high"]),
                    str(r["low"]),
                    str(r["close"]),
                    str(r.get("volume", "")),
                ])
            except Exception:
                continue
        return out

    # ── Приватные (read-only) ─────────────────────────────────────────────────
    def user_balances(self) -> Dict[str, Decimal]:
        data = self._private_post("user_info")
        balances = data.get("balances") if isinstance(data, dict) else None
        if not isinstance(balances, dict):
            return {}
        out: Dict[str, Decimal] = {}
        for k, v in balances.items():
            try:
                out[str(k)] = Decimal(str(v))
            except Exception:
                out[str(k)] = Decimal("0")
        return out

    def user_open_orders(self, pair: Optional[str] = None) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if pair:
            params["pair"] = pair
        return self._private_post("user_open_orders", params=params)

    def user_trades(self, pair: str, *, limit: int = 100) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"pair": pair, "limit": limit}
        data = self._private_post("user_trades", params=params)
        rows = data.get("trades") if isinstance(data, dict) else data
        return rows if isinstance(rows, list) else []
