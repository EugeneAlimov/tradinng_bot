from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import requests

from .http_utils import with_retries


# ──────────────────────────────────────────────────────────────────────────────
# Вспомогалки
# ──────────────────────────────────────────────────────────────────────────────

def _is_debug() -> bool:
    v = os.getenv("EXMO_DEBUG", "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _dbg(msg: str) -> None:
    if _is_debug():
        print(msg)


def _ts_utc() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def _map_resolution(tf: str | int) -> int:
    """
    EXMO candles_history принимает resolution в МИНУТАХ (int).
    Поддержим строки '1m','3m','5m','15m','30m','1h','4h','1d' и т.п.
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
    # fallback: попробовать как int
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
# Модель кредов
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class ExmoCredentials:
    api_key: str = ""
    api_secret: str = ""


# ──────────────────────────────────────────────────────────────────────────────
# Клиент EXMO (v1.1)
# ──────────────────────────────────────────────────────────────────────────────
class ExmoApi:
    base_url: str = "https://api.exmo.com/v1.1"

    def __init__(self, creds: ExmoCredentials, *, allow_trading: bool = False, timeout: float = 10.0, retry_attempts: int = 3):
        self.creds = creds
        self.allow_trading = allow_trading  # пока не используем для write-методов
        self.timeout = timeout
        self.retry_attempts = retry_attempts
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "clean-crypto-bot/0.1"})

    # ── HTTP низкоуровневые ───────────────────────────────────────────────────
    def _make_url(self, path: str) -> str:
        p = path.lstrip("/")
        # защита от двойного v1.1/… (на случай если передали '/v1.1/candles_history')
        if p.startswith("v1.1/"):
            p = p[5:]
        return f"{self.base_url}/{p}"

    def _public_get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = self._make_url(path)

        def _do():
            if _is_debug():
                print(f"[EXMO] → GET {url} params= {params}")
            r = self._session.get(url, params=params, timeout=self.timeout)
            if _is_debug():
                print(f"[EXMO] ← {path} status= {r.status_code}")
            r.raise_for_status()
            data = r.json()
            # некоторые старые эндпоинты при ошибке отдают {"error": "..."}
            if isinstance(data, dict) and data.get("error"):
                if _is_debug():
                    print(f"[EXMO]   error: {data.get('error')}")
                raise RuntimeError(f"EXMO error: {data.get('error')}")
            if _is_debug():
                # не спамим полнотекстом — только первые ~800 байт
                try:
                    body_preview = json.dumps(data)[:800]
                    print(f"[EXMO]   body: {body_preview}{'...(trunc)' if len(body_preview) == 800 else ''}")
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

        body = "&".join(f"{k}={params[k]}" for k in sorted(params))
        secret = self.creds.api_secret.encode("utf-8")
        sign_bin = hmac.new(secret, body.encode("utf-8"), hashlib.sha512).digest()
        sign = base64.b64encode(sign_bin).decode("ascii")

        headers = {
            "Key": self.creds.api_key,
            "Sign": sign,
            "Content-Type": "application/x-www-form-urlencoded",
        }

        def _do():
            if _is_debug():
                red_api = _redact(self.creds.api_key)
                print(f"[EXMO] → POST {url} body= {body} headers.Key={red_api}")
            r = self._session.post(url, data=params, headers=headers, timeout=self.timeout)
            if _is_debug():
                print(f"[EXMO] ← {path} status= {r.status_code}")
            r.raise_for_status()
            data = r.json()
            # у приватных success=false|true
            if isinstance(data, dict) and not data.get("success", True):
                err = data.get("error") or "unknown error"
                if _is_debug():
                    print(f"[EXMO]   error: {err}")
                raise RuntimeError(f"EXMO error: {err}")
            return data

        def _on_retry(i, err):
            print(f"[EXMO]   retry {i+1}: {type(err).__name__}: {err}")

        return with_retries(_do, attempts=self.retry_attempts, on_retry=_on_retry)

    # ── Публичные методы ──────────────────────────────────────────────────────
    def ping(self) -> bool:
        try:
            _ = self.ticker()
            return True
        except Exception:
            return False

    def ticker(self) -> Dict[str, Any]:
        # v1 ticker
        return self._public_get("ticker")

    def ticker_pair(self, pair: str) -> Dict[str, Any]:
        tk = self.ticker()
        return tk.get(pair, {}) if isinstance(tk, dict) else {}

    def order_book(self, pair: str, *, limit: int = 20) -> Dict[str, Any]:
        return self._public_get("order_book", params={"pair": pair, "limit": limit})

    def trades(self, pair: str, *, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Публичные сделки. На EXMO v1.1 — /trades?pair=... Возвращает dict {pair: [{...}, ...]}
        """
        data = self._public_get("trades", params={"pair": pair, "limit": limit})
        rows = data.get(pair) if isinstance(data, dict) else None
        if isinstance(rows, list):
            return rows
        return []

    # ── Свечи (через candles_history) ─────────────────────────────────────────
    def _calc_from_to_by_limit(self, resolution_min: int, limit: int) -> Tuple[int, int]:
        """
        Чтобы получить N последних свечей через candles_history (который ожидает диапазон),
        считаем to=now, from=to - resolution*limit минут.
        """
        to_ts = _ts_utc()
        span_sec = resolution_min * 60 * max(1, int(limit))
        frm_ts = to_ts - span_sec
        return frm_ts, to_ts

    def candles(self, *, pair: str, timeframe: str | int, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Унифицированный возврат списка словарей:
          [{ts, open, high, low, close, volume}, ...]
        Берём данные из /candles_history.
        """
        res = _map_resolution(timeframe)
        frm, to = self._calc_from_to_by_limit(res, limit)

        params = {"symbol": pair, "resolution": res, "from": frm, "to": to}
        _dbg(f"[EXMO] probe: candles_history params= {params}")

        data = self._public_get("candles_history", params=params)
        candles = data.get("candles") if isinstance(data, dict) else None
        if not isinstance(candles, list):
            _dbg("[EXMO]   no luck: empty rows")
            return []

        out: List[Dict[str, Any]] = []
        for r in candles:
            # r: {"t": 1754815800000, "o": 0.2, "c":..., "h":..., "l":..., "v": 248.29}
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

        _dbg(f"[EXMO]   candles_history OK rows={len(out)}")
        return out

    def kline(self, *, pair: str, timeframe: str | int, limit: int = 100) -> List[Dict[str, Any]]:
        # Для совместимости оставим отдельное имя, но используем candles_history
        return self.candles(pair=pair, timeframe=timeframe, limit=limit)

    def ohlcv(self, *, pair: str, timeframe: str | int, limit: int = 100) -> List[List[Any]]:
        """
        Возврат в виде списков: [[ts, o, h, l, c, v], ...]
        На базе candles_history.
        """
        rows = self.candles(pair=pair, timeframe=timeframe, limit=limit)
        ohlcv_rows: List[List[Any]] = []
        for r in rows:
            try:
                ohlcv_rows.append([
                    int(r["ts"]),
                    str(r["open"]),
                    str(r["high"]),
                    str(r["low"]),
                    str(r["close"]),
                    str(r.get("volume", "")),
                ])
            except Exception:
                continue
        return ohlcv_rows

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
        # Формат EXMO: { "trades": [ { ... }, ... ] } ИЛИ список сразу.
        rows = data.get("trades") if isinstance(data, dict) else data
        if isinstance(rows, list):
            return rows
        return []
