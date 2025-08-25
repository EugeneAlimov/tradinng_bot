# src/domain/strategy/__init__.py
from .registry import StrategyDef, register, get, names

# Подтягиваем стратегии «по имени модуля». Если чего-то нет — просто пропустим.
for _m in (
        "sma", "rsi2", "donchian", "ema", "macd",
        "bbands", "roc", "supertrend", "keltner",
        "adx", "sma_atr", "ema_adx", "ema_adx_atr"
):
    try:
        __import__(f"{__name__}.{_m}")
    except Exception:
        # не ломаем пакет, если модуль отсутствует
        pass
