#!/usr/bin/env python3
"""
paper_trade_cmd.py — простая CLI-утилита бумажного трейда, совместимая со sweep_cli.

Вход: CSV с колонками времени и OHLCV. По умолчанию ищет колонку времени 'timestamp',
переименовывает в 'time' и ресемплит во фрейм 'resample' (например, '5min').

Стратегия (упрощённая, но рабочая):
- Вход LONG при пересечении EMA_fast выше EMA_slow, ADX >= adx_on, и (если require_di) +DI > -DI.
  Вход SHORT при обратном пересечении и (если require_di) -DI > +DI.
- Фильтр HTF (опционально): если задан htf_tf, для старшего ТФ считаем EMA(HTF) и разрешаем
  только LONG, когда EMA_fast(HTF) > EMA_slow(HTF), и только SHORT, когда <.
- Стоп: stop_atr * ATR(atr_len). Тейк (опционально): take_atr * ATR. Трейл (опционально):
  trail_atr * ATR, активируется сразу или при достижении RR >= trail_activate_rr.
- Breakeven (опционально): при достижении RR >= breakeven_rr переносим стоп в безубыток.
- min_hold_bars — минимальная выдержка позиции (стоп всё равно действует),
  cooldown_bars — пауза после выхода.
- Направление выхода внутри бара: если в том же баре задеты и стоп, и тейк/трейл, берём стоп первым
  (консервативно). Можно поменять логикой "priority" при желании.
- Сделки исполняются по следующему бару (entry_lag баров задержка) по цене открытия с проскальзыванием,
  выходы — по уровню с проскальзыванием.

Выход: печатает на stdout ЕДИНСТВЕННУЮ строку с JSON объектом:
{"trades": int, "win_rate": float, "net_pnl": float, "avg_pnl": float}
Именно это парсит sweep_cli.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from typing import Optional, List

import numpy as np
import pandas as pd


# ------------------------
# Utils & indicators
# ------------------------

def str2bool(x: str) -> bool:
    if isinstance(x, bool):
        return x
    x = x.strip().lower()
    return x in {"1", "true", "t", "y", "yes"}


def ensure_time_index(df: pd.DataFrame, time_col: str = "timestamp") -> pd.DataFrame:
    if "time" in df.columns:
        tcol = "time"
    elif time_col in df.columns:
        tcol = time_col
    else:
        # попробуем угадать
        for cand in ["timestamp", "date", "datetime", "time"]:
            if cand in df.columns:
                tcol = cand
                break
        else:
            raise ValueError("Не найдена колонка времени. Укажите --time-col")
    df = df.copy()
    df[tcol] = pd.to_datetime(df[tcol], utc=True, errors="coerce")
    df = df.dropna(subset=[tcol])
    df = df.rename(columns={tcol: "time"}).set_index("time").sort_index()
    return df


def resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    agg = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
    }
    if "volume" in df.columns:
        agg["volume"] = "sum"
    out = df.resample(rule).agg(agg).dropna()
    return out


def ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False, min_periods=span).mean()


def _tr(h: pd.Series, l: pd.Series, c: pd.Series) -> pd.Series:
    prev_c = c.shift(1)
    return pd.concat([(h - l).abs(), (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)


def atr(h: pd.Series, l: pd.Series, c: pd.Series, n: int) -> pd.Series:
    tr = _tr(h, l, c)
    return tr.rolling(n, min_periods=n).mean()


def di_adx(h: pd.Series, l: pd.Series, c: pd.Series, n: int):
    # Wilder's smoothing (приближение без talib)
    up_move = h.diff()
    down_move = -l.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr = _tr(h, l, c)

    plus_dm = pd.Series(plus_dm, index=h.index)
    minus_dm = pd.Series(minus_dm, index=h.index)

    tr_n = tr.rolling(n, min_periods=n).sum()
    plus_n = plus_dm.rolling(n, min_periods=n).sum()
    minus_n = minus_dm.rolling(n, min_periods=n).sum()

    plus_di = 100 * (plus_n / tr_n).replace([np.inf, -np.inf], np.nan)
    minus_di = 100 * (minus_n / tr_n).replace([np.inf, -np.inf], np.nan)
    dx = (100 * (plus_di - minus_di).abs() / (plus_di + minus_di)).replace([np.inf, -np.inf], np.nan)
    adx = dx.rolling(n, min_periods=n).mean()
    return plus_di, minus_di, adx


# ------------------------
# Backtester
# ------------------------

@dataclass
class Config:
    ohlcv: str
    time_col: str = "timestamp"
    resample: str = "5min"
    ema_fast: int = 12
    ema_slow: int = 21
    adx_len: int = 14
    adx_on: float = 25.0
    adx_off: float = 20.0
    require_di: bool = True
    htf_tf: Optional[str] = None
    htf_ema_fast: Optional[int] = None
    htf_ema_slow: Optional[int] = None
    atr_len: int = 14
    stop_atr: float = 2.0
    take_atr: Optional[float] = None
    trail_atr: Optional[float] = None
    breakeven_rr: Optional[float] = None
    trail_activate_rr: Optional[float] = None
    entry_lag: int = 0
    cooldown_bars: int = 0
    min_hold_bars: int = 0
    fill_mode: str = "next_open"
    fee_bps: float = 0.0
    slip_bps: float = 0.0
    qty: float = 1.0


@dataclass
class Trade:
    side: int  # +1 long, -1 short
    entry_idx: pd.Timestamp
    entry_px: float
    exit_idx: pd.Timestamp
    exit_px: float
    pnl: float


def run_backtest(cfg: Config) -> List[Trade]:
    df = pd.read_csv(cfg.ohlcv)
    # колонок может быть много: ожидаем как минимум open/high/low/close
    lower_cols = {c.lower(): c for c in df.columns}
    for need in ["open", "high", "low", "close"]:
        if need not in lower_cols:
            raise ValueError(f"В CSV нет колонки {need}")
    # нормализуем имена
    df = df.rename(columns={lower_cols["open"]: "open",
                            lower_cols["high"]: "high",
                            lower_cols["low"]: "low",
                            lower_cols["close"]: "close"})
    if "volume" in lower_cols:
        df = df.rename(columns={lower_cols["volume"]: "volume"})

    df = ensure_time_index(df, cfg.time_col)
    if cfg.resample:
        df = resample_ohlcv(df, cfg.resample)

    # индикаторы LTF
    df["ema_f"] = ema(df["close"], cfg.ema_fast)
    df["ema_s"] = ema(df["close"], cfg.ema_slow)
    plus_di, minus_di, adx = di_adx(df["high"], df["low"], df["close"], cfg.adx_len)
    df["plus_di"], df["minus_di"], df["adx"] = plus_di, minus_di, adx
    df["atr"] = atr(df["high"], df["low"], df["close"], cfg.atr_len)

    # фильтр HTF
    if cfg.htf_tf:
        htf = resample_ohlcv(df[["open", "high", "low", "close"]], cfg.htf_tf)
        efast = cfg.htf_ema_fast or cfg.ema_fast
        eslow = cfg.htf_ema_slow or cfg.ema_slow
        htf["ema_f"] = ema(htf["close"], efast)
        htf["ema_s"] = ema(htf["close"], eslow)
        # сопоставим значения к LTF по forward-fill
        htf = htf[["ema_f", "ema_s"]].reindex(df.index, method="ffill")
        df["htf_ok_long"] = (htf["ema_f"] > htf["ema_s"]).astype(float)
        df["htf_ok_short"] = (htf["ema_f"] < htf["ema_s"]).astype(float)
    else:
        df["htf_ok_long"] = 1.0
        df["htf_ok_short"] = 1.0

    # сигналы входа (кресты EMA)
    df["cross_up"] = (df["ema_f"].shift(1) <= df["ema_s"].shift(1)) & (df["ema_f"] > df["ema_s"])
    df["cross_dn"] = (df["ema_f"].shift(1) >= df["ema_s"].shift(1)) & (df["ema_f"] < df["ema_s"])

    trades: List[Trade] = []

    pos = 0  # 0/ +1 / -1
    entry_px = None
    entry_idx = None
    risk_per_unit = None
    stop_px = None
    take_px = None
    trail_active = False
    be_done = False
    hold_bars = 0
    cooldown = 0

    slip = cfg.slip_bps / 10000.0
    fee = cfg.fee_bps / 10000.0

    # пройдём по барам
    for i in range(1, len(df)):
        ts = df.index[i]
        row = df.iloc[i]
        prev = df.iloc[i - 1]

        if cooldown > 0:
            cooldown -= 1

        # обновление трейла для открытой позиции
        if pos != 0:
            hold_bars += 1
            # Активировать трейл по RR
            if not trail_active and cfg.trail_atr and cfg.trail_activate_rr is not None and risk_per_unit:
                # для длинной используем максимум бара, для короткой минимум
                if pos > 0:
                    rr_now = (row["high"] - entry_px) / risk_per_unit
                else:
                    rr_now = (entry_px - row["low"]) / risk_per_unit
                if rr_now >= cfg.trail_activate_rr:
                    trail_active = True

            # Безубыток
            if not be_done and cfg.breakeven_rr is not None and risk_per_unit:
                if pos > 0:
                    rr_now = (row["high"] - entry_px) / risk_per_unit
                    if rr_now >= cfg.breakeven_rr:
                        stop_px = max(stop_px, entry_px)
                        be_done = True
                else:
                    rr_now = (entry_px - row["low"]) / risk_per_unit
                    if rr_now >= cfg.breakeven_rr:
                        stop_px = min(stop_px, entry_px)
                        be_done = True

            # Трейлинг
            if cfg.trail_atr and (trail_active or cfg.trail_activate_rr is None):
                dist = cfg.trail_atr * row["atr"]
                if pd.notna(dist):
                    if pos > 0:
                        trail_level = row["high"] - dist
                        if stop_px is None:
                            stop_px = trail_level
                        else:
                            stop_px = max(stop_px, trail_level)
                    else:
                        trail_level = row["low"] + dist
                        if stop_px is None:
                            stop_px = trail_level
                        else:
                            stop_px = min(stop_px, trail_level)

            # Проверка выхода в текущем баре (приоритет стопа)
            if pos > 0:
                stop_hit = stop_px is not None and row["low"] <= stop_px
                take_hit = cfg.take_atr is not None and take_px is not None and row[
                    "high"] >= take_px and hold_bars >= cfg.min_hold_bars
                if stop_hit:
                    exit_px = stop_px * (1 - slip)
                elif take_hit:
                    exit_px = take_px * (1 - slip)
                else:
                    exit_px = None
                if exit_px is not None:
                    # комиссия на выход
                    pnl = (exit_px - entry_px) * cfg.qty
                    pnl -= (entry_px + exit_px) * cfg.qty * fee
                    trades.append(Trade(+1, entry_idx, entry_px, ts, exit_px, pnl))
                    # сброс состояния
                    pos = 0
                    entry_px = None
                    entry_idx = None
                    risk_per_unit = None
                    stop_px = None
                    take_px = None
                    trail_active = False
                    be_done = False
                    hold_bars = 0
                    cooldown = cfg.cooldown_bars
                    continue
            elif pos < 0:
                stop_hit = stop_px is not None and row["high"] >= stop_px
                take_hit = cfg.take_atr is not None and take_px is not None and row[
                    "low"] <= take_px and hold_bars >= cfg.min_hold_bars
                if stop_hit:
                    exit_px = stop_px * (1 + slip)
                elif take_hit:
                    exit_px = take_px * (1 + slip)
                else:
                    exit_px = None
                if exit_px is not None:
                    pnl = (entry_px - exit_px) * cfg.qty
                    pnl -= (entry_px + exit_px) * cfg.qty * fee
                    trades.append(Trade(-1, entry_idx, entry_px, ts, exit_px, pnl))
                    pos = 0
                    entry_px = None
                    entry_idx = None
                    risk_per_unit = None
                    stop_px = None
                    take_px = None
                    trail_active = False
                    be_done = False
                    hold_bars = 0
                    cooldown = cfg.cooldown_bars
                    continue

        # поиск входа (если нет позиции и нет кулдауна)
        if pos == 0 and cooldown == 0:
            adx_ok_on = row["adx"] >= cfg.adx_on if pd.notna(row["adx"]) else False
            adx_ok_off = row["adx"] <= cfg.adx_off if pd.notna(row["adx"]) else True
            # Включён ли вообще ADX фильтр на вход: требуем adx_on
            if pd.isna(row["ema_f"]) or pd.isna(row["ema_s"]) or pd.isna(row["atr"]) or not adx_ok_on:
                pass
            else:
                long_ok = bool(row["cross_up"]) and bool(row["htf_ok_long"]) and (
                        not cfg.require_di or (row["plus_di"] > row["minus_di"]))
                short_ok = bool(row["cross_dn"]) and bool(row["htf_ok_short"]) and (
                        not cfg.require_di or (row["minus_di"] > row["plus_di"]))
                if long_ok:
                    # вход по следующему бару open с проскальзыванием
                    if i + cfg.entry_lag < len(df):
                        j = i + cfg.entry_lag
                        next_open = df.iloc[j]["open"]
                        if pd.notna(next_open) and adx_ok_on:
                            entry_px = float(next_open) * (1 + slip)
                            entry_idx = df.index[j]
                            pos = +1
                            # комиссии на вход
                            entry_fee = entry_px * cfg.qty * fee
                            # риск
                            risk_per_unit = cfg.stop_atr * row["atr"]
                            if pd.isna(risk_per_unit) or risk_per_unit <= 0:
                                # если ATR нет — отменяем вход
                                pos = 0
                                entry_px = None
                                entry_idx = None
                            else:
                                stop_px = entry_px - risk_per_unit
                                take_px = None
                                if cfg.take_atr:
                                    take_px = entry_px + cfg.take_atr * row["atr"]
                                trail_active = cfg.trail_activate_rr is None  # сразу или после RR
                                be_done = False
                                hold_bars = 0
                                # учтём комиссию сразу через вычитание из PnL на выходе; здесь можно игнорировать

                elif short_ok:
                    if i + cfg.entry_lag < len(df):
                        j = i + cfg.entry_lag
                        next_open = df.iloc[j]["open"]
                        if pd.notna(next_open) and adx_ok_on:
                            entry_px = float(next_open) * (1 - slip)
                            entry_idx = df.index[j]
                            pos = -1
                            entry_fee = entry_px * cfg.qty * fee
                            risk_per_unit = cfg.stop_atr * row["atr"]
                            if pd.isna(risk_per_unit) or risk_per_unit <= 0:
                                pos = 0
                                entry_px = None
                                entry_idx = None
                            else:
                                stop_px = entry_px + risk_per_unit
                                take_px = None
                                if cfg.take_atr:
                                    take_px = entry_px - cfg.take_atr * row["atr"]
                                trail_active = cfg.trail_activate_rr is None
                                be_done = False
                                hold_bars = 0

    return trades


def summarize(trades: List[Trade]):
    if not trades:
        return {"trades": 0, "win_rate": 0.0, "net_pnl": 0.0, "avg_pnl": 0.0}
    pnl = np.array([t.pnl for t in trades], dtype=float)
    wins = (pnl > 0).sum()
    return {
        "trades": int(len(trades)),
        "win_rate": float(wins / len(trades)),
        "net_pnl": float(pnl.sum()),
        "avg_pnl": float(pnl.mean()),
    }


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="paper-trade")
    p.add_argument("--ohlcv", required=True, help="Путь к CSV OHLCV")
    p.add_argument("--time-col", default="timestamp")
    p.add_argument("--resample", required=True)
    p.add_argument("--ema-fast", type=int, required=True, dest="ema_fast")
    p.add_argument("--ema-slow", type=int, required=True, dest="ema_slow")
    p.add_argument("--adx-len", type=int, required=True, dest="adx_len")
    p.add_argument("--adx-on", type=float, required=True, dest="adx_on")
    p.add_argument("--adx-off", type=float, required=True, dest="adx_off")
    p.add_argument("--require-di", type=str2bool, required=True, dest="require_di")
    p.add_argument("--htf-tf", dest="htf_tf")
    p.add_argument("--htf-ema-fast", type=int, dest="htf_ema_fast")
    p.add_argument("--htf-ema-slow", type=int, dest="htf_ema_slow")
    p.add_argument("--atr-len", type=int, dest="atr_len", default=14)
    p.add_argument("--stop-atr", type=float, required=True, dest="stop_atr")
    p.add_argument("--take-atr", type=float, dest="take_atr")
    p.add_argument("--trail-atr", type=float, dest="trail_atr")
    p.add_argument("--breakeven-rr", type=float, dest="breakeven_rr")
    p.add_argument("--trail-activate-rr", type=float, dest="trail_activate_rr")
    p.add_argument("--entry-lag", type=int, dest="entry_lag", default=0)
    p.add_argument("--cooldown-bars", type=int, required=True, dest="cooldown_bars")
    p.add_argument("--min-hold-bars", type=int, dest="min_hold_bars", default=0)
    p.add_argument("--fill-mode", dest="fill_mode", default="next_open")
    p.add_argument("--fee-bps", type=float, required=True, dest="fee_bps")
    p.add_argument("--slip-bps", type=float, required=True, dest="slip_bps")
    p.add_argument("--qty", type=float, required=True, dest="qty")
    # совместимость: игнорируем неизвестные доп. ключи, если sweep_cli их пришлёт
    return p


def main():
    parser = build_argparser()
    args, unknown = parser.parse_known_args()
    # Не падаем из‑за неизвестных аргументов, просто игнорируем

    cfg = Config(
        ohlcv=args.ohlcv,
        time_col=args.time_col,
        resample=args.resample,
        ema_fast=args.ema_fast,
        ema_slow=args.ema_slow,
        adx_len=args.adx_len,
        adx_on=args.adx_on,
        adx_off=args.adx_off,
        require_di=args.require_di,
        htf_tf=args.htf_tf,
        htf_ema_fast=args.htf_ema_fast,
        htf_ema_slow=args.htf_ema_slow,
        atr_len=args.atr_len,
        stop_atr=args.stop_atr,
        take_atr=args.take_atr,
        trail_atr=args.trail_atr,
        breakeven_rr=args.breakeven_rr,
        trail_activate_rr=args.trail_activate_rr,
        entry_lag=args.entry_lag,
        cooldown_bars=args.cooldown_bars,
        min_hold_bars=args.min_hold_bars,
        fill_mode=args.fill_mode,
        fee_bps=args.fee_bps,
        slip_bps=args.slip_bps,
        qty=args.qty,
    )

    try:
        trades = run_backtest(cfg)
        summ = summarize(trades)
    except Exception as e:
        # В случае сбоя отдаём валидный JSON с нулевой статистикой и текстом ошибки в stderr
        raise
    else:
        # ВАЖНО: вывести РОВНО один JSON-объект одной строкой (без префиксов), это парсит sweep_cli
        print(json.dumps(summ, ensure_ascii=False))


if __name__ == "__main__":
    main()
