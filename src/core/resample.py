# -*- coding: utf-8 -*-
from typing import List, Dict


def tf_to_seconds(s: str) -> int:
    s = s.strip().lower()
    if s.endswith("m"): return int(s[:-1]) * 60
    if s.endswith("h"): return int(s[:-1]) * 3600
    if s.endswith("d"): return int(s[:-1]) * 86400
    raise ValueError(f"bad tf: {s}")


def normalize_row(r: Dict) -> Dict:
    # Вход: EXMO {"t": ms, "o","h","l","c","v"} либо {"ts": sec, ...}
    ts = int(r.get("ts") or int(r["t"]) // 1000)
    return {
        "ts": ts,
        "o": float(r["o"]),
        "h": float(r["h"]),
        "l": float(r["l"]),
        "c": float(r["c"]),
        "v": float(r.get("v", 0.0)),
    }


def resample_ohlcv(rows: List[Dict], tf_sec: int) -> List[Dict]:
    if not rows: return []
    out = {}
    for r0 in rows:
        r = normalize_row(r0)
        bucket = (r["ts"] // tf_sec) * tf_sec
        b = out.get(bucket)
        if not b:
            out[bucket] = {"ts": bucket, "o": r["o"], "h": r["h"], "l": r["l"], "c": r["c"], "v": r["v"]}
        else:
            b["h"] = max(b["h"], r["h"])
            b["l"] = min(b["l"], r["l"])
            b["c"] = r["c"]
            b["v"] += r["v"]
    return [out[k] for k in sorted(out)]
