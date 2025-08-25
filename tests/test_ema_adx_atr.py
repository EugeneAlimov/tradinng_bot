# tests/test_ema_adx_atr.py
from src.domain.strategy import registry as reg


def _ohlc(n=500):
    ts = list(range(n))
    close = [1 + i * 0.001 for i in ts]
    high = [c * 1.001 for c in close]
    low = [c * 0.999 for c in close]
    open_ = [c * 0.9995 for c in close]
    return dict(ts=ts, open=open_, high=high, low=low, close=close)


def test_signals_and_status():
    o = _ohlc(600)
    defn = reg.get("ema_adx_atr")
    sig = defn.generate_signals(close=o["close"], high=o["high"], low=o["low"],
                                fast=9, slow=21, adx_len=14, on=18, off=14,
                                require_di=False, atr_len=14, atr_mult=3.0)
    assert isinstance(sig, list) and len(sig) == len(o["close"])
    assert any(x != 0 for x in sig), "ожидали хотя бы один сигнал"
    txt, state = defn.status(close=o["close"], high=o["high"], low=o["low"],
                             fast=9, slow=21, adx_len=14, on=18, off=14,
                             require_di=False, atr_len=14, atr_mult=3.0)
    assert isinstance(txt, str)
    assert state in (-1, 0, 1)
