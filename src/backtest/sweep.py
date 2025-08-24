# src/backtest/sweep.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from itertools import product
from typing import Iterable, List, Optional, Tuple, Dict, Any

import math
import pandas as pd
import numpy as np
import time

try:
    from .vectorized_bt import _fetch_exmo_candles as _fetch_exmo_candles_inner
except Exception:
    _fetch_exmo_candles_inner = None


# ------------------------------ utils ------------------------------ #

def parse_int_list(spec: str) -> List[int]:
    spec = str(spec).strip()
    if ":" in spec and "," in spec:
        raise ValueError(f"Ambiguous list spec (both ':' and ','): {spec}")
    if ":" in spec:
        parts = [int(x) for x in spec.split(":")]
        if len(parts) not in (2, 3):
            raise ValueError(f"Bad range spec: {spec}. Expected start:stop[:step]")
        start, stop = parts[0], parts[1]
        step = parts[2] if len(parts) == 3 else 1
        if step == 0:
            raise ValueError("Step must be non-zero")
        out = list(range(start, stop + (1 if step > 0 else -1), step))
        out = [x for x in out if (start <= x <= stop) or (start >= x >= stop)]
        return out
    if "," in spec:
        return [int(x.strip()) for x in spec.split(",") if x.strip() != ""]
    if spec == "":
        return []
    return [int(spec)]


def parse_float_list(spec: str) -> List[float]:
    spec = str(spec).strip()
    if ":" in spec and "," in spec:
        raise ValueError(f"Ambiguous list spec (both ':' and ','): {spec}")
    if ":" in spec:
        start, stop, *rest = [float(x) for x in spec.split(":")]
        step = rest[0] if rest else 1.0
        if step == 0.0:
            raise ValueError("Step must be non-zero")
        out = []
        x = start
        forward = step > 0
        while (x <= stop if forward else x >= stop):
            out.append(round(float(x), 10))
            x += step
        return out
    if "," in spec:
        return [float(x.strip()) for x in spec.split(",") if x.strip() != ""]
    if spec == "":
        return []
    return [float(spec)]


def _normalize_resample_rule(rule: Optional[str]) -> Optional[str]:
    """
    Приводим '5m' (минуты) к '5T' для совместимости с новыми pandas.
    Если пользователь передал '5min' или '5T' — оставляем как есть.
    """
    if not rule:
        return None
    r = str(rule).strip()
    rl = r.lower()
    if rl.endswith("min") or rl.endswith("t"):
        return r
    if rl.endswith("m") and rl[:-1].isdigit():
        return f"{int(rl[:-1])}T"
    return r


def _bars_per_year_for_rule(rule: Optional[str]) -> float:
    if not rule:
        return 525600.0  # 1m
    rl = str(rule).strip().lower()
    if rl.endswith("t") or rl.endswith("min"):
        num = "".join(ch for ch in rl if ch.isdigit())
        minutes = int(num) if num else 1
        if minutes == 5:
            return 105192.0
        return 525600.0 / max(1, minutes)
    if rl.endswith("h"):
        num = "".join(ch for ch in rl if ch.isdigit())
        hours = int(num) if num else 1
        return (24.0 * 365.0) / max(1, hours)
    if rl.endswith("d"):
        num = "".join(ch for ch in rl if ch.isdigit())
        days = int(num) if num else 1
        return 365.0 / max(1, days)
    return 105192.0


def _resample_ohlc(df: pd.DataFrame, rule: Optional[str]) -> pd.DataFrame:
    if not rule:
        return df.copy()
    rule = _normalize_resample_rule(rule)
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    out = df.resample(rule, label="right", closed="right").agg(agg).dropna()
    return out


def _sma(a: pd.Series, n: int) -> pd.Series:
    return a.rolling(n, min_periods=n).mean()


def _safe_to_dtindex(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.index, pd.DatetimeIndex):
        return df
    if "time" in df.columns:
        return df.set_index(pd.to_datetime(df["time"], utc=True)).drop(columns=["time"])
    # как fallback — пробуем преобразовать текущий индекс
    return df.set_index(pd.to_datetime(df.index, utc=True))


def _fetch_exmo_candles_cached(pair: str, span: str, retries: int = 3, pause_s: float = 0.7,
                               cache_dir: Path = Path("data/cache")) -> pd.DataFrame:
    """
    Надёжная загрузка свечей:
    - несколько попыток из EXMO
    - при неудаче — поднимаем из локального кэша (csv.gz)
    - при успехе — обновляем кэш
    """
    if _fetch_exmo_candles_inner is None:
        raise RuntimeError("EXMO fetch function is not available in this build")

    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_name = f"exmo_{pair}_{span.replace(':','-')}.csv.gz"
    cache_path = cache_dir / cache_name
    last_err: Optional[Exception] = None

    for i in range(max(1, retries)):
        try:
            df = _fetch_exmo_candles_inner(pair, span)
            if df is None or len(df) == 0:
                raise RuntimeError(f"Empty candles from EXMO for {pair} span={span}")
            df = df.copy()
            # нормализация столбцов/индекса
            cols = {c.lower(): c for c in df.columns}
            rename_map = {}
            for want in ("open", "high", "low", "close", "volume"):
                for col in df.columns:
                    if col.lower() == want:
                        rename_map[col] = want
                        break
            df = df.rename(columns=rename_map)
            df = _safe_to_dtindex(df).sort_index()
            # обновляем кэш
            try:
                df.to_csv(cache_path, index=True, compression="gzip")
            except Exception:
                pass
            return df
        except Exception as e:
            last_err = e
            time.sleep(pause_s)

    # не удалось — пытаемся поднять из кэша
    if cache_path.exists():
        try:
            df = pd.read_csv(cache_path, compression="gzip")
            df = _safe_to_dtindex(df).sort_index()
            return df
        except Exception:
            pass

    raise RuntimeError(f"fetch_failed: {last_err}" if last_err else "fetch_failed: unknown")


def _simulate_on_df(
    ohlc: pd.DataFrame,
    *,
    fast: int,
    slow: int,
    hysteresis_bps: int,
    cooldown_bars: int,
    fee_bps: int,
    slip_bps: int,
    qty_eur: float,
    enter_on_start: bool = False,
    max_daily_loss_bps: int = 0,
    resample_rule: Optional[str] = None,
    pair_name: str = "UNK",
) -> Tuple[Dict[str, Any], pd.DataFrame, pd.DataFrame]:
    """
    SMA crossover + hysteresis + cooldown. Возвращает (metrics, trades_df, equity_df).
    """
    if ohlc.empty:
        raise RuntimeError("Empty OHLC for simulation")
    df = ohlc.copy()
    close = df["close"].astype(float)

    if fast <= 0 or slow <= 0 or fast >= slow:
        raise RuntimeError(f"Bad SMA windows: fast={fast}, slow={slow}")

    df["sma_fast"] = _sma(close, fast)
    df["sma_slow"] = _sma(close, slow)
    df = df.dropna().copy()
    if df.empty:
        raise RuntimeError("Not enough candles after SMA warmup")

    bps = 1e-4
    up_th = (1.0 + hysteresis_bps * bps)
    dn_th = (1.0 - hysteresis_bps * bps)

    in_pos = False
    cooldown = 0

    price = df["close"].values
    sf = df["sma_fast"].values
    ss = df["sma_slow"].values

    trades: List[Dict[str, Any]] = []
    cash = 1000.0
    asset = 0.0
    eq_list: List[Tuple[pd.Timestamp, float]] = []

    bars_per_year = _bars_per_year_for_rule(_normalize_resample_rule(resample_rule))

    fee = fee_bps * bps
    slip = slip_bps * bps

    for i, (ts, row) in enumerate(df.iterrows()):
        p = float(row["close"])
        eq_list.append((ts, cash + asset * p))

        if cooldown > 0:
            cooldown -= 1

        want_long = sf[i] > ss[i] * up_th
        want_flat = sf[i] < ss[i] * dn_th

        # вход
        if not in_pos and cooldown == 0:
            if enter_on_start & i == 0:
                want_long = True
            if want_long and qty_eur > 0:
                buy_p = p * (1.0 + slip)
                size = qty_eur / buy_p
                cost = size * buy_p
                fee_cost = cost * fee
                if cash >= cost + fee_cost:
                    cash -= (cost + fee_cost)
                    asset += size
                    trades.append({"time": ts, "side": "BUY", "price": buy_p, "size": size, "fee_eur": fee_cost})
                    in_pos = True

        # выход
        if in_pos and want_flat:
            sell_p = p * (1.0 - slip)
            proceeds = asset * sell_p
            fee_cost = proceeds * fee
            cash += (proceeds - fee_cost)
            trades.append({"time": ts, "side": "SELL", "price": sell_p, "size": asset, "fee_eur": fee_cost})
            asset = 0.0
            in_pos = False
            cooldown = cooldown_bars

    # финальный выход
    if in_pos and len(df) > 0:
        ts = df.index[-1]
        p = float(df["close"].iloc[-1])
        sell_p = p * (1.0 - slip)
        proceeds = asset * sell_p
        fee_cost = proceeds * fee
        cash += (proceeds - fee_cost)
        trades.append({"time": ts, "side": "SELL", "price": sell_p, "size": asset, "fee_eur": fee_cost})
        asset = 0.0
        in_pos = False

    equity = pd.DataFrame(eq_list, columns=["time", "equity"]).set_index("time")
    final_eq = float(equity["equity"].iloc[-1]) if not equity.empty else 1000.0
    ret = (final_eq / 1000.0) - 1.0

    # метрики по сделкам
    tdf = pd.DataFrame(trades)
    wins = 0.0
    losses = 0.0
    n_trades = 0
    if not tdf.empty:
        cash_tmp = 1000.0
        pnl_list = []
        for _, tr in tdf.iterrows():
            side = tr["side"]
            pr = float(tr["price"])
            sz = float(tr["size"])
            fee_eur = float(tr.get("fee_eur", 0.0))
            if side == "BUY":
                cash_tmp -= (pr * sz + fee_eur)
            else:
                cash_tmp += (pr * sz - fee_eur)
                pnl_list.append(cash_tmp - 1000.0 - sum(pnl_list))
        for p in pnl_list:
            if p >= 0:
                wins += p
            else:
                losses += -p
        n_trades = len(pnl_list)

    profit_factor = (wins / losses) if losses > 0 else (float("inf") if wins > 0 else 0.0)
    avg_trade_eur = (final_eq - 1000.0) / max(1, n_trades)
    exposure_pct = 0.0
    if not tdf.empty:
        exposure_pct = 100.0 * (tdf["side"].eq("BUY").sum() / max(1, len(df)))

    # max DD
    roll_max = equity["equity"].cummax()
    dd = (equity["equity"] / roll_max) - 1.0
    max_dd = float(dd.min()) if not dd.empty else 0.0

    # Sharpe
    er = equity["equity"].pct_change().dropna()
    sharpe = float(er.mean() / (er.std() + 1e-12) * math.sqrt(bars_per_year)) if not er.empty else 0.0

    years = max(1e-9, len(df) / bars_per_year)
    cagr = (final_eq / 1000.0) ** (1.0 / years) - 1.0
    calmar = (cagr / abs(max_dd)) if max_dd < 0 else (float("inf") if cagr > 0 else 0.0)

    metrics = {
        "pair": pair_name,
        "bars": int(len(df)),
        "trades": int(n_trades),
        "winrate_pct": float(100.0 * wins / (wins + losses) if (wins + losses) > 0 else 0.0),
        "total_return_pct": float(100.0 * ret),
        "max_drawdown_pct": float(100.0 * max_dd),
        "final_equity_eur": float(final_eq),
        "start_equity_eur": 1000.0,
        "profit_factor": float(profit_factor),
        "avg_trade_eur": float(avg_trade_eur),
        "exposure_pct": float(exposure_pct),
        "sharpe": float(sharpe),
        "cagr_pct": float(100.0 * cagr),
        "calmar": float(100.0 * calmar),
        "bars_per_year": float(bars_per_year),
    }
    return metrics, tdf, equity


@dataclass
class SweepCfg:
    pair: str
    span: str
    resample: Optional[str]
    fast_list: List[int]
    slow_list: List[int]
    hyst_list: List[int]
    cooldown_list: List[int]
    qty_list: List[float]
    fee_bps: int
    slip_bps: int
    max_daily_loss_bps: int
    out_dir: Path
    verbose: bool = False


def run_sweep(cfg: SweepCfg) -> str:
    """
    Возвращает путь к CSV со всеми комбинациями. Каждый ряд имеет колонку 'error' (пусто если успех).
    """
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    stamp = pd.Timestamp.utcnow().strftime("%Y%m%d-%H%M%S")
    out_csv = cfg.out_dir / f"sweep_{cfg.pair}_{_normalize_resample_rule(cfg.resample) or 'raw'}_{stamp}.csv"

    # 1) загрузка и ресемпл (один раз) с ретраями/кэшем
    try:
        raw = _fetch_exmo_candles_cached(cfg.pair, cfg.span, retries=3)
        if raw.empty:
            raise RuntimeError(f"Empty candles for {cfg.pair} span={cfg.span}")
        ohlc = _resample_ohlc(raw, cfg.resample)
        if ohlc.empty:
            raise RuntimeError(f"Resample produced empty OHLC for rule={cfg.resample}")
    except Exception as e:
        pd.DataFrame([{"pair": cfg.pair, "error": f"fetch_or_resample_failed: {e}"}]).to_csv(out_csv, index=False)
        return str(out_csv)

    rows: List[Dict[str, Any]] = []
    for fast, slow, hyst, cd, qty in product(
        cfg.fast_list, cfg.slow_list, cfg.hyst_list, cfg.cooldown_list, cfg.qty_list
    ):
        row: Dict[str, Any] = dict(
            pair=cfg.pair,
            fast=int(fast),
            slow=int(slow),
            hysteresis_bps=int(hyst),
            cooldown_bars=int(cd),
            qty_eur=float(qty),
            fee_bps=int(cfg.fee_bps),
            slip_bps=int(cfg.slip_bps),
            max_daily_loss_bps=int(cfg.max_daily_loss_bps),
            resample=_normalize_resample_rule(cfg.resample) or "",
            error="",
        )
        try:
            metrics, _, _ = _simulate_on_df(
                ohlc,
                fast=fast, slow=slow,
                hysteresis_bps=hyst, cooldown_bars=cd,
                fee_bps=cfg.fee_bps, slip_bps=cfg.slip_bps,
                qty_eur=qty,
                resample_rule=cfg.resample,
                pair_name=cfg.pair,
            )
            row.update(metrics)
        except Exception as e:
            row["error"] = f"{type(e).__name__}: {e}"
        rows.append(row)

        if cfg.verbose and len(rows) % 50 == 0:
            print(f"[sweep] done {len(rows)} rows ...")

    pd.DataFrame(rows).to_csv(out_csv, index=False)
    return str(out_csv)
