# src/infrastructure/http/http_utils.py
from __future__ import annotations
import os
import time
import json
import logging
from typing import Any, Dict, Optional
import requests

logger = logging.getLogger(__name__)

EXMO_DEBUG = os.getenv("EXMO_DEBUG", "0") not in ("", "0", "false", "False", "no", "No")

class HttpClient:
    def __init__(self, base_url: str = "", session: Optional[requests.Session] = None, timeout: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.timeout = timeout

    def _full_url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return f"{self.base_url}/{path.lstrip('/')}"

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        auth=None,
    ) -> requests.Response:
        url = self._full_url(path)
        t0 = time.perf_counter()

        if EXMO_DEBUG:
            logger.warning("[EXMO] → %s %s params=%s json=%s", method.upper(), url, params, json_data)

        resp = self.session.request(
            method=method.upper(),
            url=url,
            params=params,
            json=json_data,
            headers=headers,
            timeout=self.timeout,
            auth=auth,
        )

        dt = (time.perf_counter() - t0) * 1000.0
        if EXMO_DEBUG:
            try:
                body_preview = resp.json()
            except Exception:
                body_preview = resp.text[:500]
            logger.warning("[EXMO] ← %s %s (%d) in %.1fms body=%s",
                           method.upper(), url, resp.status_code, dt, json.dumps(body_preview, ensure_ascii=False)[:800])

        resp.raise_for_status()
        return resp

    def get(self, path: str, **kw) -> requests.Response:
        return self.request("GET", path, **kw)

    def post(self, path: str, **kw) -> requests.Response:
        return self.request("POST", path, **kw)
