# src/data/exmo_client.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, Optional
import time
import json
import hashlib
import gzip

import requests
import pandas as pd


@dataclass
class ExmoClient:
    base_url: str = "https://api.exmo.com/v1.1"  # при необходимости скорректируем
    cache_dir: Path = Path("data/cache/exmo")
    timeout: int = 15
    retries: int = 3
    backoff_sec: float = 0.8
    user_agent: str = "tradinng-bot/opt"

    def _request(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"
        headers = {"User-Agent": self.user_agent}
        last_err = None
        for attempt in range(1, self.retries + 1):
            try:
                r = requests.get(url, params=params, timeout=self.timeout, headers=headers)
                if r.status_code == 200:
                    return r.json()
                last_err = RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
            except Exception as e:
                last_err = e
            time.sleep(self.backoff_sec * attempt)
        raise last_err or RuntimeError("Unknown EXMO request error")

    def _cache_path(self, key: str) -> Path:
        h = hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        return self.cache_dir / f"{h}.json.gz"

    def _cache_load(self, key: str) -> Optional[Dict[str, Any]]:
        p = self._cache_path(key)
        if not p.exists():
            return None
        try:
            with gzip.open(p, "rt", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def _cache_save(self, key: str, data: Dict[str, Any]) -> None:
        p = self._cache_path(key)
        with gzip.open(p, "wt", encoding="utf-8") as f:
            json.dump(data, f)

    # -------- candles --------
    def get_candles(self, symbol: str, resolution: str = "1m", limit: int = 2000) -> pd.DataFrame:
        """
        Заглушка под EXMO candles (с API может отличаться по пути/параметрам).
        Кэшируем сырой JSON; конвертим в DataFrame с индексом Datetime (UTC).
        Ожидаемый формат JSON: список баров со (t, o, h, l, c, v) — подкорректируем под фактический ответ.
        """
        path = "candles_history"  # возможно придётся поменять на реальный endpoint
        params = {"symbol": symbol, "resolution": resolution, "limit": int(limit)}
        key = f"{path}?{json.dumps(params, sort_keys=True)}"
        raw = self._cache_load(key)
        if raw is None:
            raw = self._request(path, params)
            self._cache_save(key, raw)

        # Пример нормализации (подгоните под реальность EXMO)
        # Ожидаем raw["candles"] = [{"t": 1690000000, "o":..., "h":..., "l":..., "c":..., "v":...}, ...]
        if isinstance(raw, dict) and "candles" in raw:
            rows = raw["candles"]
        elif isinstance(raw, list):
            rows = raw
        else:
            raise RuntimeError("Unexpected EXMO candles format")

        df = pd.DataFrame(rows)
        # возможные варианты времени: 't' (sec) или 'ts' (ms)
        if "t" in df.columns:
            ts = pd.to_datetime(df["t"].astype("int64"), unit="s", utc=True)
        elif "ts" in df.columns:
            ts = pd.to_datetime(df["ts"].astype("int64"), unit="ms", utc=True)
        else:
            raise RuntimeError("Missing time field in EXMO candles response")

        df.index = ts
        col_map = {"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"}
        for k, v in col_map.items():
            if k in df.columns:
                df[v] = pd.to_numeric(df[k], errors="coerce")
        keep = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
        return df[keep].sort_index()
