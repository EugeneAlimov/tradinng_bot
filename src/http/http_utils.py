# src/infrastructure/http/http_utils.py
from __future__ import annotations

import json
import logging
import random
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import urllib3
from urllib3.util import Retry, Timeout

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HttpConfig:
    retries: int = 3
    backoff: float = 1.0  # сек, базовый backoff
    timeout_sec: float = 10.0  # общий таймаут
    pool_connections: int = 2
    pool_maxsize: int = 4
    # Доп. настройки
    jitter_frac: float = 0.25  # рандомизация backoff (0..25%)
    status_forcelist: Tuple[int, ...] = (429, 500, 502, 503, 504)
    allowed_methods: Tuple[str, ...] = ("GET", "POST", "PUT", "DELETE", "HEAD", "OPTIONS")


class HttpClient:
    """
    Единый HTTP-клиент с urllib3.PoolManager + Retry.
    """

    def __init__(self, cfg: Optional[HttpConfig] = None) -> None:
        self.cfg = cfg or HttpConfig()

        # Настраиваем Retry: экспоненциальный backoff с фактором cfg.backoff
        # respect_retry_after_header=True чтобы уважать Retry-After от API.
        self._retry = Retry(
            total=self.cfg.retries,
            connect=self.cfg.retries,
            read=self.cfg.retries,
            redirect=self.cfg.retries,
            status=self.cfg.retries,
            backoff_factor=self.cfg.backoff,
            status_forcelist=self.cfg.status_forcelist,
            allowed_methods=set(m.upper() for m in self.cfg.allowed_methods),
            raise_on_status=False,
            respect_retry_after_header=True,
        )

        # Глобальный пул
        self._pm = urllib3.PoolManager(
            num_pools=self.cfg.pool_connections,
            maxsize=self.cfg.pool_maxsize,
            retries=False,  # важн.: управляем ретраями вручную через urlopen(..., retries=self._retry)
        )

        self._timeout = Timeout(total=self.cfg.timeout_sec)

    def _sleep_with_jitter(self, base_sec: float) -> None:
        if base_sec <= 0:
            return
        jitter = base_sec * self.cfg.jitter_frac * random.random()
        time.sleep(base_sec + jitter)

    def get_text(self, url: str, *, retries: Optional[int] = None) -> Tuple[int, str]:
        """
        Возвращает (status_code, text). Не бросает исключений на сетевых ошибках:
        - статус = 0, text = '' при фатальной ошибке (после ретраев).
        """
        # Локально можем переопределить число ретраев
        retry = self._retry if retries is None else self._retry.new(total=retries)
        attempt = 0
        while True:
            attempt += 1
            try:
                r = self._pm.request(
                    "GET",
                    url,
                    retries=retry,
                    timeout=self._timeout,
                    preload_content=True,
                )
                # urllib3 при успешном ответе не кидает исключений —
                # даже если status >= 400 (мы не raise_on_status).
                data = r.data.decode("utf-8", errors="replace") if r.data is not None else ""
                return r.status or 0, data
            except Exception as e:
                # Логируем и спим по экспоненте + джиттер
                logger.warning("HTTP GET failed (attempt=%s/%s): %s", attempt, (retry.total or self.cfg.retries), e)
                if attempt > (retry.total or self.cfg.retries):
                    logger.error("HTTP GET giving up: %s", url)
                    return 0, ""
                # экспонента близка к Retry.backoff_factor, но контролируем сами
                self._sleep_with_jitter(self.cfg.backoff * (2 ** (attempt - 1)))

    def get_json(self, url: str, *, retries: Optional[int] = None) -> Tuple[int, Optional[Dict[str, Any]]]:
        st, txt = self.get_text(url, retries=retries)
        if st <= 0 or not txt:
            return st, None
        try:
            return st, json.loads(txt)
        except Exception:
            # Возвращаем raw-текст для диагностики через caller, если нужно
            logger.warning("JSON parse failed (status=%s): %s...", st, txt[:120])
            return st, None
