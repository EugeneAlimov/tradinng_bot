# src/infrastructure/exchange/http_utils.py
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

LOG = logging.getLogger("exmo.http")


def _make_session(retries: int, backoff_factor: float) -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=retries,
        backoff_factor=backoff_factor,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "POST"]),
        raise_on_status=False,
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


class HttpClient:
    """
    Мини-клиент с ретраями и опциональным трасс‑логом (EXMO_DEBUG).
    """

    def __init__(self, base_url: str, timeout_sec: float = 10.0, retries: int = 3, backoff_factor: float = 0.3,
                 debug: bool = False, user_agent: str = "tradinng-bot/StageA"):
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout = timeout_sec
        self.debug = debug
        self.session = _make_session(retries=retries, backoff_factor=backoff_factor)
        self.session.headers["User-Agent"] = user_agent

    def _log_req(self, method: str, path: str, params: Optional[Dict[str, Any]], data: Optional[Dict[str, Any]]) -> None:
        if not self.debug:
            return
        LOG.debug("[HTTP] %s %s params=%s data=%s", method, path, params, data)

    def _log_resp(self, status: int, text: str) -> None:
        if not self.debug:
            return
        preview = text if len(text) < 500 else (text[:500] + "...(truncated)")
        LOG.debug("[HTTP] <- %s %s", status, preview)

    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        url = urljoin(self.base_url, path.lstrip("/"))
        self._log_req("GET", url, params, None)
        r = self.session.get(url, params=params, timeout=self.timeout)
        self._log_resp(r.status_code, r.text)
        r.raise_for_status()
        return r.json()

    def post(self, path: str, data: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None) -> Any:
        url = urljoin(self.base_url, path.lstrip("/"))
        self._log_req("POST", url, None, data)
        r = self.session.post(url, data=data or {}, headers=headers or {}, timeout=self.timeout)
        self._log_resp(r.status_code, r.text)
        r.raise_for_status()
        ct = r.headers.get("Content-Type", "")
        return r.json() if "application/json" in ct or r.text.startswith("{") else r.text
