# -*- coding: utf-8 -*-
"""
EXMO Private/Public API client with:
- ThreadSafeNonceManager (file-locked, cross-process safe)
- Unique client_id generation (int32-safe) for order_create
- Connection pooling (requests.Session)
- Defensive logging (API key never leaked)
- Minimal retry for nonce/rate-limit/network

This module provides a single class: ExmoPrivate
which is intentionally self-contained so it can be used
both in live trading and utility scripts.
"""
from __future__ import annotations

import os
import time
import hmac
import hashlib
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Union

import requests

from src.infrastructure.exchange.nonce_manager import ThreadSafeNonceManager
from src.infrastructure.exchange.order_manager import OrderIDGenerator

logger = logging.getLogger(__name__)


def _mask_secret(value: Optional[str]) -> str:
    """Return masked secret for logs (no trailing part exposure)."""
    if not value:
        return "<none>"
    return f"<len={len(value)}>"


def _to_str_num(x: Union[str, float, int]) -> str:
    s = f"{float(x):.10f}".rstrip("0").rstrip(".")
    return s or "0"


class ExmoPrivate:
    """
    Minimal EXMO API client.

    Notes:
      - base_url can be overridden via env EXMO_BASE_URL
      - nonce storage via env EXMO_NONCE_FILE (default data/.exmo_nonce)
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: int = 20,
        nonce_file: Optional[str] = None,
        session: Optional[requests.Session] = None,
    ):
        self.key = (api_key or os.environ.get("EXMO_API_KEY", "")).strip()
        self._secret_raw = (api_secret or os.environ.get("EXMO_API_SECRET", "")).strip()
        if not self.key or not self._secret_raw:
            raise RuntimeError("EXMO API credentials are not set")

        self.secret = self._secret_raw.encode("utf-8")
        self.base_url = (base_url or os.environ.get("EXMO_BASE_URL", "https://api.exmo.com/v1.1")).rstrip("/")
        self.timeout = int(timeout)

        nf = nonce_file or os.environ.get("EXMO_NONCE_FILE", "data/.exmo_nonce")
        Path(nf).parent.mkdir(parents=True, exist_ok=True)
        self.nonce_manager = ThreadSafeNonceManager(nf)

        # Reuse TCP connections
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": "tradinng-bot/EXMO"})

        # client_id generator (int32 safe)
        self._cid_gen = OrderIDGenerator()

        logger.debug(
            "ExmoPrivate init base_url=%s key=%s secret=%s nonce_file=%s",
            self.base_url,
            _mask_secret(self.key),
            _mask_secret(self._secret_raw),
            nf,
        )

    # --------------- low-level HTTP ---------------

    def _signed_post(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Signed POST with automatic nonce and bounded retries for nonce / rate limit.
        """
        url = f"{self.base_url}/{method}"
        params = dict(params or {})
        max_attempts = 5

        for attempt in range(max_attempts):
            try:
                # monotonic, file-locked nonce
                params["nonce"] = self.nonce_manager.get_next_nonce()
                payload = requests.utils.requote_uri("&".join(f"{k}={params[k]}" for k in params))
                # urlencode with Session's internal encoder (more robust for unicode)
                payload_bytes = payload.encode("utf-8")
                sign = hmac.new(self.secret, payload_bytes, hashlib.sha512).hexdigest()
                headers = {
                    "Key": self.key,
                    "Sign": sign,
                    "Content-Type": "application/x-www-form-urlencoded",
                }
                resp = self.session.post(url, data=params, headers=headers, timeout=self.timeout)
                resp.raise_for_status()
                data = resp.json()

                # Business-level errors from EXMO
                if isinstance(data, dict) and data.get("error"):
                    err = str(data.get("error"))
                    low = err.lower()
                    if "nonce" in low:
                        logger.warning("EXMO nonce error on attempt %s: %s", attempt + 1, err)
                        time.sleep(0.4 * (attempt + 1))
                        continue
                    if "flood" in low or "limit" in low or "rate" in low:
                        delay = min(2 ** attempt, 15)
                        logger.warning("EXMO rate limit on attempt %s: wait %ss", attempt + 1, delay)
                        time.sleep(delay)
                        continue
                    # other business error → raise
                    raise RuntimeError(f"EXMO API error: {err}")

                return data

            except requests.exceptions.RequestException as e:
                if attempt < max_attempts - 1:
                    delay = min(2 ** attempt, 10)
                    logger.warning("Network error attempt %s: %s, retry in %ss", attempt + 1, e, delay)
                    time.sleep(delay)
                    continue
                raise
            except Exception:
                # unhandled — bubble up after last retry
                if attempt == max_attempts - 1:
                    raise
                time.sleep(0.5)

        # unreachable
        raise RuntimeError("EXMO _signed_post failed unexpectedly")

    def _public_get(self, method: str, params: Optional[Dict[str, Any]] = None) -> Any:
        url = f"{self.base_url}/{method}"
        try:
            resp = self.session.get(url, params=params or {}, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error("EXMO public GET failed: %s", e)
            raise

    # --------------- public ---------------

    def ticker(self) -> Dict[str, Any]:
        return self._public_get("ticker")

    def ticker_pair(self, pair: str) -> Dict[str, Any]:
        all_t = self.ticker()
        # EXMO returns a map; keys usually like "DOGE_EUR"
        return all_t.get(pair) or all_t.get(pair.upper(), {})

    # --------------- private ---------------

    def user_info(self) -> Dict[str, Any]:
        return self._signed_post("user_info")

    def user_open_orders(self, pair: Optional[str] = None) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if pair:
            params["pair"] = pair
        return self._signed_post("user_open_orders", params)

    def order_create(
        self,
        *,
        pair: str,
        quantity: Union[str, float, int],
        price: Union[str, float, int],
        side: str,
        client_id: Optional[object] = None,
    ) -> Dict[str, Any]:
        """
        Create order with safe client_id:
        - EXMO requires integer client_id; we generate int32-safe ID if not provided.
        - If client_id is provided, try to coerce to int string safely.
        """
        side = str(side).lower().strip()
        if side not in ("buy", "sell"):
            raise ValueError("side must be 'buy' or 'sell'")

        # Guarantee unique client_id
        cid: Optional[int] = None
        if client_id is not None:
            try:
                cid = int(str(client_id).strip())
            except Exception:
                # ignore invalid client_id
                cid = None
        if cid is None:
            cid = self._cid_gen.generate()

        params = {
            "pair": pair,
            "quantity": _to_str_num(quantity),
            "price": _to_str_num(price),
            "type": side,
            "client_id": str(cid),
        }
        return self._signed_post("order_create", params)

    def order_cancel(self, order_id: Union[str, int]) -> Dict[str, Any]:
        return self._signed_post("order_cancel", {"order_id": str(order_id)})

    def order_trades(self, order_id: Union[str, int]) -> Dict[str, Any]:
        return self._signed_post("order_trades", {"order_id": str(order_id)})

    # --------------- context ---------------

    def close(self) -> None:
        try:
            self.session.close()
        except Exception:
            pass
