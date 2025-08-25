# src/domain/strategy/ema_adx_atr.py
from __future__ import annotations
from typing import List, Optional, Tuple
from .registry import StrategyDef, register


def _ema(series: List[float], period: int) -> List[Optional[float]]:
    p = max(2, int(period))
    out: List[Optional[float]] = [None] * len(series)
    k = 2.0 / (p + 1.0)
    v: Optional[float] = None
    for i, x in enumerate(series):
        v = x if v is None else x * k + v * (1 - k)
        out[i] = v
    return out


def _tr(high: List[float], low: List[float], close: List[float]) -> List[float]:
    out = [0.0] * len(close)
    for i in range(len(close)):
        if i == 0:
            out[i] = high[i] - low[i]
        else:
            out[i] = max(
                high[i] - low[i],
                abs(high[i] - close[i - 1]),
                abs(low[i] - close[i - 1]),
            )
    return out


def _rma(vals: List[float], length: int) -> List[float]:
    n = max(1, int(length))
    out = [0.0] * len(vals)
    avg = None
    for i, v in enumerate(vals):
        if avg is None:
            if i < n:
                out[i] = 0.0
                avg = (avg or 0.0) + v
                if i == n - 1:
                    out[i] = avg / n
                    avg = out[i]
            else:
                out[i] = v
                avg = v
        else:
            alpha = 1.0 / n
            avg = alpha * v + (1 - alpha) * avg
            out[i] = avg
    return out


def _adx(high: List[float], low: List[float], close: List[float], length: int):
    n = max(2, int(length))
    tr = _tr(high, low, close)
    plus_dm = [0.0] * len(close)
    minus_dm = [0.0] * len(close)
    for i in range(1, len(close)):
        up = high[i] - high[i - 1]
        down = low[i - 1] - low[i]
        plus_dm[i] = up if (up > down and up > 0) else 0.0
        minus_dm[i] = down if (down > up and down > 0) else 0.0
    tr_rma = _rma(tr, n)
    plus_rma = _rma(plus_dm, n)
    minus_rma = _rma(minus_dm, n)
    plus_di = [0.0 if tr_rma[i] == 0 else 100.0 * plus_rma[i] / tr_rma[i] for i in range(len(close))]
    minus_di = [0.0 if tr_rma[i] == 0 else 100.0 * minus_rma[i] / tr_rma[i] for i in range(len(close))]
    dx = [0.0 if (plus_di[i] + minus_di[i]) == 0 else 100.0 * abs(plus_di[i] - minus_di[i]) / (plus_di[i] + minus_di[i])
          for i in range(len(close))]
    adx = _rma(dx, n)
    return plus_di, minus_di, adx


def _atr(high: List[float], low: List[float], close: List[float], length: int) -> List[float]:
    return _rma(_tr(high, low, close), max(1, int(length)))


def generate_signals(
        close: List[float],
        high: List[float],
        low: List[float],
        fast: int = 12,
        slow: int = 26,
        adx_len: int = 14,
        on: float = 22.0,
        off: float = 18.0,
        require_di: bool = True,
        atr_len: int = 14,
        atr_mult: float = 3.0,
) -> List[int]:
    """
    Вход long: EMA(fast) пересекает EMA(slow) ВВЕРХ и ADX>=on (и при require_di: +DI>-DI).
    Выход: обратный кросс ИЛИ ADX<off ИЛИ трейлинг-стоп ATR (C < trail).
    """
    fast = max(2, int(fast))
    slow = max(fast + 1, int(slow))
    adx_len = max(2, int(adx_len))
    on = float(on);
    off = float(off)
    atr_len = max(1, int(atr_len));
    atr_mult = float(atr_mult)

    ema_f = _ema(close, fast)
    ema_s = _ema(close, slow)
    pdi, mdi, adx = _adx(high, low, close, adx_len)
    atr = _atr(high, low, close, atr_len)

    in_pos = False
    trail = 0.0
    signals = [0] * len(close)
    for i in range(1, len(close)):
        ef = ema_f[i];
        es = ema_s[i]
        e_prev_f = ema_f[i - 1];
        e_prev_s = ema_s[i - 1]
        if ef is None or es is None or e_prev_f is None or e_prev_s is None:
            continue

        cross_up = (e_prev_f <= e_prev_s and ef > es)
        cross_dn = (e_prev_f >= e_prev_s and ef < es)
        allow_trend = adx[i] >= on
        allow_dir = (pdi[i] > mdi[i]) if require_di else True

        if not in_pos and cross_up and allow_trend and allow_dir:
            signals[i] = +1
            in_pos = True
            trail = close[i] - atr_mult * atr[i]
        elif in_pos:
            trail = max(trail, close[i] - atr_mult * atr[i])
            if cross_dn or (adx[i] < off) or (close[i] < trail):
                signals[i] = -1
                in_pos = False
                trail = 0.0
    return signals


def status(
        close: List[float],
        high: List[float],
        low: List[float],
        fast: int = 12,
        slow: int = 26,
        adx_len: int = 14,
        on: float = 22.0,
        off: float = 18.0,
        require_di: bool = True,
        atr_len: int = 14,
        atr_mult: float = 3.0,
) -> Tuple[str, int]:
    ema_f = _ema(close, max(2, int(fast)))
    ema_s = _ema(close, max(int(fast) + 1, int(slow)))
    pdi, mdi, adx = _adx(high, low, close, int(adx_len))
    atr = _atr(high, low, close, int(atr_len))
    i = len(close) - 1
    if i < 0 or ema_f[i] is None or ema_s[i] is None:
        return "EMA+ADX+ATR: EMAf=?, EMAs=?, ADX=?, ATR=?", 0
    f = float(ema_f[i]);
    s = float(ema_s[i]);
    a = float(adx[i]);
    p = float(pdi[i]);
    m = float(mdi[i]);
    at = float(atr[i])
    ok_trend = a >= on
    ok_dir = (p > m) if require_di else True
    state = 1 if (f > s and ok_trend and ok_dir) else (-1 if (f < s and (a >= on) and (m > p)) else 0)
    txt = f"EMAf={f:.6f} EMAs={s:.6f} ADX={a:.2f} +DI={p:.2f} -DI={m:.2f} ATR={at:.6f} on={on:.1f}/off={off:.1f} x{atr_mult:.1f}"
    if require_di:
        txt += " DI=on"
    return txt, state


register(StrategyDef(
    name="ema_adx_atr",
    generate_signals=generate_signals,
    status=status,
    defaults={"fast": 12, "slow": 26, "adx_len": 14, "on": 22.0, "off": 18.0, "require_di": True, "atr_len": 14,
              "atr_mult": 3.0},
))
