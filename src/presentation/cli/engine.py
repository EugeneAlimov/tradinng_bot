import logging

import time

from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests

LOG = logging.getLogger("cli")

_PERIODS = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400}


def _parse_candles(flag: str) -> Tuple[str, int]:
    tf, n = flag.split(":", 1)
    return tf.strip(), int(n)


def _fetch_exmo_ohlc(args, pair: str, candles: str) -> pd.DataFrame:
    """
    Улучшенная версия получения OHLC данных с EXMO API
    Учитывает особенности API: обязательные from/to параметры и недоступность limit
    """
    # Проверяем что pair не пустой
    if not pair:
        LOG.error("Empty pair provided to _fetch_exmo_ohlc")
        return pd.DataFrame()

    try:
        tf, n = _parse_candles(candles)
    except Exception as e:
        LOG.error("bad --candles: %s", e)
        return pd.DataFrame()

    if tf not in _PERIODS:
        LOG.error("Unsupported timeframe '%s'", tf)
        return pd.DataFrame()

    period = _PERIODS[tf]
    resolution_minutes = period // 60

    # Вычисляем временные рамки
    current_time = int(time.time())
    from_time = current_time - (n * period)
    to_time = current_time

    # ИСПРАВЛЕНИЕ: Используем только from/to параметры (limit не поддерживается EXMO)
    url = "https://api.exmo.com/v1.1/candles_history"
    params = {
        "symbol": pair,
        "resolution": resolution_minutes,
        "from": from_time,
        "to": to_time
        # НЕ используем "limit" - EXMO возвращает ошибку 40035
    }

    try:
        LOG.debug(f"[exmo] requesting {n} {tf} candles for {pair} (from={from_time}, to={to_time})")

        response = requests.get(url, params=params, timeout=20)

        if response.status_code != 200:
            LOG.warning(f"[exmo] HTTP {response.status_code}: {response.text[:200]}")
            return pd.DataFrame()

        data = response.json()

        # Проверяем формат ответа
        if not isinstance(data, dict):
            LOG.warning(f"[exmo] unexpected response type: {type(data)}")
            return pd.DataFrame()

        # Проверяем на ошибки API
        if data.get('result') == False and 'error' in data:
            LOG.warning(f"[exmo] API error: {data['error']}")
            return pd.DataFrame()

        if data.get('s') == 'error':
            LOG.warning(f"[exmo] API error: {data.get('errmsg', 'unknown error')}")
            return pd.DataFrame()

        # Проверяем наличие данных
        if 'candles' not in data:
            LOG.warning(f"[exmo] no 'candles' field in response")
            return pd.DataFrame()

        candles_data = data['candles']
        if not candles_data:
            LOG.warning(f"[exmo] empty candles for {pair}")
            return pd.DataFrame()

        LOG.info(f"[exmo] received {len(candles_data)} candles for {pair}")

        # Обрабатываем данные
        df = pd.DataFrame(candles_data)

        # Переименовываем колонки (EXMO возвращает t,o,h,l,c,v)
        df = df.rename(columns={
            "t": "timestamp",
            "o": "open",
            "h": "high",
            "l": "low",
            "c": "close",
            "v": "volume"
        })

        # Конвертируем в числовые типы
        for col in ("open", "high", "low", "close", "volume"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # ИСПРАВЛЕНИЕ: EXMO возвращает timestamp в миллисекундах, конвертируем в секунды
        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce") / 1000.0

        # Удаляем строки с NaN
        df = df.dropna()

        if df.empty:
            LOG.warning(f"[exmo] all data was invalid for {pair}")
            return pd.DataFrame()

        # Сортируем по времени и ограничиваем количество до запрошенного
        df = df.sort_values("timestamp").reset_index(drop=True)

        # Берем последние n свечей (если получили больше чем запрашивали)
        if len(df) > n:
            df = df.tail(n).reset_index(drop=True)
            LOG.debug(f"[exmo] limited to last {n} candles for {pair}")

        return df

    except Exception as e:
        LOG.error(f"[exmo] request failed for {pair}: {e}")
        return pd.DataFrame()


def _live_params_from_args(args) -> Dict[str, Any]:
    """Извлекаем параметры стратегии из аргументов"""
    return {
        "fast": getattr(args, "ema_fast", 12),
        "slow": getattr(args, "ema_slow", 21),
        "adx_len": getattr(args, "adx_len", 14),
        "on": getattr(args, "adx_on", 23.0),
        "off": getattr(args, "adx_off", 17.0),
        "require_di": getattr(args, "require_di", False),
    }


def _evaluate_last_signal(strategy: str, df: pd.DataFrame, params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Улучшенная оценка торговых сигналов с реальными индикаторами
    """
    if df.empty:
        return {}

    try:
        close = df["close"]
        high = df.get("high", close)
        low = df.get("low", close)

        fast_len = params.get("fast", 12)
        slow_len = params.get("slow", 21)
        adx_len = params.get("adx_len", 14)

        if len(close) < max(fast_len, slow_len, adx_len):
            LOG.debug(f"Insufficient data for signals: {len(close)} < {max(fast_len, slow_len, adx_len)}")
            return {}

        # EMA расчеты
        ema_fast = close.ewm(span=fast_len).mean().iloc[-1]
        ema_slow = close.ewm(span=slow_len).mean().iloc[-1]

        # Простой расчет ADX (упрощенная версия)
        # В реальном проекте лучше использовать ta-lib или pandas-ta
        price_range = high - low
        avg_range = price_range.rolling(window=adx_len).mean().iloc[-1]
        close_change = abs(close.diff()).rolling(window=adx_len).mean().iloc[-1]

        # Простой ADX-подобный индикатор (нормализованный)
        adx_simple = min(100, (close_change / avg_range * 100)) if avg_range > 0 else 0

        LOG.debug(f"Signals: EMA_fast={ema_fast:.6f}, EMA_slow={ema_slow:.6f}, ADX_simple={adx_simple:.2f}")

        return {
            "ema_fast": float(ema_fast),
            "ema_slow": float(ema_slow),
            "adx": float(adx_simple),
            "close": float(close.iloc[-1]),
            "timestamp": df["timestamp"].iloc[-1] if "timestamp" in df.columns else time.time()
        }

    except Exception as e:
        LOG.error(f"Signal evaluation error: {e}")
        return {}


def run_trade_live(args) -> int:
    """
    Улучшенная версия run_trade_live с лучшим логированием и обработкой сигналов
    """

    # Проверяем обязательные параметры
    pair = getattr(args, 'pair', None)
    if not pair:
        LOG.error("No trading pair specified. Use --pair or --pairs argument.")
        return 1

    candles = getattr(args, 'candles', None)
    if not candles:
        LOG.error("No candles specification provided. Use --candles argument (e.g., 1m:100)")
        return 1

    LOG.info("Command: trade-live mode=%s strategy=%s pair=%s", args.mode, args.strategy, pair)

    # Первоначальная загрузка данных
    df = _fetch_exmo_ohlc(args, pair, candles)
    if df.empty:
        print("(no data)")
        return 0

    print(f"[live] {args.mode} {pair} {candles} strategy={args.strategy} rows={len(df)}")

    poll = int(getattr(args, "poll_sec", 10))
    summary = bool(getattr(args, "summary_alert", False))
    params = _live_params_from_args(args)

    LOG.info(f"Strategy parameters: {params}")

    last_print_ts: Optional[float] = None
    simulated_in_pos = False
    entry_price: Optional[float] = None
    position_start_time: Optional[float] = None

    try:
        while True:
            # Обновляем данные
            df = _fetch_exmo_ohlc(args, pair, candles)
            if df.empty:
                LOG.warning("[live] empty data on refresh")
                time.sleep(poll)
                continue

            last = df.iloc[-1]
            last_ts = float(last["timestamp"]) if "timestamp" in df.columns else time.time()
            close = float(last["close"])

            # Оцениваем сигналы
            sig = _evaluate_last_signal(args.strategy, df, params)
            fast = sig.get("ema_fast")
            slow = sig.get("ema_slow")
            adx = sig.get("adx")

            entered = exited = False
            if fast is not None and slow is not None and adx is not None:
                adx_on_threshold = float(params.get("on", 20.0))
                adx_off_threshold = float(params.get("off", 14.0))

                long_cond = (fast > slow) and (adx >= adx_on_threshold)
                off_cond = (adx <= adx_off_threshold) or (fast <= slow)

                if long_cond and not simulated_in_pos:
                    simulated_in_pos = True
                    entry_price = close
                    position_start_time = last_ts
                    entered = True
                elif simulated_in_pos and off_cond:
                    simulated_in_pos = False
                    exited = True

            # Улучшенный вывод результатов
            if summary:
                if last_print_ts != last_ts or entered or exited:
                    state = "IN" if simulated_in_pos else "OUT"
                    pnl_info = ""
                    if simulated_in_pos and entry_price:
                        pnl_pct = ((close - entry_price) / entry_price) * 100
                        pnl_info = f" PnL: {pnl_pct:+.2f}%"

                    print(f"[live] {pair} close={close:.6f} state={state}{pnl_info}")
                    last_print_ts = last_ts
            else:
                if entered:
                    print(
                        f"[live] ENTER {pair} @ {close:.6f} (EMA_fast={fast:.6f} > EMA_slow={slow:.6f}, ADX={adx:.2f})")
                elif exited:
                    pnl_info = ""
                    if entry_price:
                        pnl_pct = ((close - entry_price) / entry_price) * 100
                        duration = (last_ts - position_start_time) / 60 if position_start_time else 0
                        pnl_info = f" PnL: {pnl_pct:+.2f}% Duration: {duration:.1f}min"
                    print(f"[live] EXIT {pair} @ {close:.6f}{pnl_info}")
                    entry_price = None
                    position_start_time = None

            time.sleep(poll)

    except KeyboardInterrupt:
        LOG.info("[live] stopped by user")
        if simulated_in_pos and entry_price:
            final_pnl = ((close - entry_price) / entry_price) * 100
            print(f"[live] Final position PnL: {final_pnl:+.2f}%")
        return 0
    except Exception as e:
        LOG.error(f"[live] unexpected error: {e}")
        return 1


def run_auto(args) -> int:
    """Автоматический режим - заглушка"""
    LOG.info("Command: auto mode (not implemented)")
    return 0


def run_optimize(args) -> int:
    """Оптимизация - заглушка"""
    LOG.info("Command: optimize (not implemented)")
    return 0


def run_robustness(args) -> int:
    """Тест устойчивости - заглушка"""
    LOG.info("Command: robustness (not implemented)")
    return 0


def run_walk_forward(args) -> int:
    """Walk-forward анализ - заглушка"""
    LOG.info("Command: walk-forward (not implemented)")
    return 0
