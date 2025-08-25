# src/presentation/cli/app.py
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

# ---- Strategies registry ----
# основной путь
try:
    from src.domain.strategy import registry as strat_registry  # type: ignore
except Exception:
    # совместимость со старым путём (если жив)
    try:
        from src.application.research.strategies import strat_registry  # type: ignore
    except Exception as e:
        raise RuntimeError(
            "Strategy registry not found. Ensure src/domain/strategy/registry.py exists."
        ) from e

# ---- Research pipelines (optional) ----
try:
    from src.application.research import selector as sel  # type: ignore
except Exception:
    sel = None  # команды research дадут понятную ошибку


# ---- Safe converters ----
def as_int_or_none(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != value:
            return None
        return int(value)
    s = str(value).strip()
    return int(s) if s else None


def as_float_or_none(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, float):
        if value != value:
            return None
        return value
    if isinstance(value, int):
        return float(value)
    s = str(value).strip()
    return float(s) if s else None


def bps_or_none(value: Any) -> Optional[int]:
    i = as_int_or_none(value)
    return i if (i is not None and i >= 0) else None


def pct01_or_none(value: Any) -> Optional[float]:
    f = as_float_or_none(value)
    return f if (f is not None and f >= 0.0) else None


# ---- Logging ----
LOG = logging.getLogger("cli")


def _setup_logging(debug: bool) -> None:
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [cli] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    LOG.debug("Logging configured. Level=%s", "DEBUG" if debug else "INFO")


# ---- EXMO client (urllib3 + Retry) ----
import urllib3
from urllib3.util.retry import Retry

EXMO_HOST = "https://api.exmo.com"
EXMO_CANDLES_V = "/v1.1/candles_history"


def _resolution_minutes(tf: str) -> int:
    tf = tf.strip().lower()
    if tf.endswith("m"):
        return int(tf[:-1])
    if tf.endswith("h"):
        return int(tf[:-1]) * 60
    if tf.endswith("d"):
        return int(tf[:-1]) * 60 * 24
    raise ValueError(f"Unsupported timeframe: {tf}")


def _parse_pair(pair: str) -> str:
    return pair.strip().upper()


def _parse_candles_spec(spec: str) -> Tuple[str, int]:
    tf, cnt = spec.split(":")
    return tf.strip(), int(cnt)


def _build_http(retries: Optional[int], backoff: Optional[float]) -> urllib3.PoolManager:
    total = retries if retries is not None else as_int_or_none(os.getenv("HTTP_RETRIES"))
    back = backoff if backoff is not None else as_float_or_none(os.getenv("HTTP_BACKOFF"))
    total = total if total is not None else 3
    back = back if back is not None else 0.3
    retry = Retry(
        total=total,
        backoff_factor=back,
        status_forcelist=(429, 500, 502, 503, 504),
        raise_on_status=False,
        allowed_methods=False,  # ретраи и на GET
    )
    return urllib3.PoolManager(retries=retry, timeout=urllib3.Timeout(connect=5.0, read=15.0))


def _exmo_candles_history(
        http: urllib3.PoolManager,
        pair: str,
        resolution_min: int,
        epoch_from: int,
        epoch_to: int,
) -> List[Dict[str, Any]]:
    params = {
        "symbol": pair,
        "resolution": str(resolution_min),
        "from": str(epoch_from),
        "to": str(epoch_to),
    }
    url = f"{EXMO_HOST}{EXMO_CANDLES_V}"
    r = http.request("GET", url, fields=params)
    if r.status != 200:
        LOG.error("EXMO candles_history failed: %s", r.status)
        raise RuntimeError(f"EXMO HTTP {r.status}")
    data = json.loads(r.data.decode("utf-8"))
    return data.get("candles") or []


def _get_candles_arrays(
        pair: str,
        spec: str,
        retries: Optional[int],
        backoff: Optional[float],
) -> Tuple[List[int], List[float], List[float], List[float], List[float]]:
    tf, count = _parse_candles_spec(spec)
    res_min = _resolution_minutes(tf)
    now = int(time.time())
    span = res_min * 60 * count
    frm = now - span
    to = now
    http = _build_http(retries, backoff)
    raw = _exmo_candles_history(http, _parse_pair(pair), res_min, frm, to)
    raw.sort(key=lambda x: x.get("t", 0))
    ts: List[int] = []
    o: List[float] = []
    h: List[float] = []
    l: List[float] = []
    c: List[float] = []
    for k in raw:
        ts.append(int(k["t"]))
        o.append(float(k["o"]))
        h.append(float(k["h"]))
        l.append(float(k["l"]))
        c.append(float(k["c"]))
    return ts, o, h, l, c


# ---- Simple stats ----
def _sharpe_by_trades(trade_pnls: List[float]) -> float:
    if not trade_pnls:
        return 0.0
    import math
    m = sum(trade_pnls) / len(trade_pnls)
    var = sum((x - m) ** 2 for x in trade_pnls) / len(trade_pnls)
    sd = math.sqrt(var) if var > 0 else 0.0
    return (m / sd) if sd > 0 else 0.0


def _max_drawdown(equity: List[float]) -> float:
    peak = float("-inf")
    mdd = 0.0
    for v in equity:
        if v > peak:
            peak = v
        dd = v - peak
        if dd < mdd:
            mdd = dd
    return mdd


@dataclass
class Trade:
    entry_ts: int
    entry_px: float
    side: int  # +1 long, -1 short
    exit_ts: int
    exit_px: float
    pnl: float


# ---- Strategy params from CLI ----
def _build_params_from_args(strategy: str, args: argparse.Namespace) -> Dict[str, Any]:
    p: Dict[str, Any] = {}
    if getattr(args, "fast", None) is not None:
        p["fast"] = int(args.fast)
    if getattr(args, "slow", None) is not None:
        p["slow"] = int(args.slow)
    if getattr(args, "adx_len", None) is not None:
        p["adx_len"] = int(args.adx_len)
    if getattr(args, "on", None) is not None:
        p["on"] = float(args.on)
    if getattr(args, "off", None) is not None:
        p["off"] = float(args.off)
    if getattr(args, "require_di", False):
        p["require_di"] = True
    if getattr(args, "atr_len", None) is not None:
        p["atr_len"] = int(args.atr_len)
    if getattr(args, "atr_mult", None) is not None:
        p["atr_mult"] = float(args.atr_mult)
    if getattr(args, "st_len", None) is not None:
        p["atr_len"] = int(args.st_len)
    if getattr(args, "st_mult", None) is not None:
        p["mult"] = float(args.st_mult)
    return p


# ---- Backtest engine ----
def _run_backtest_signals(
        timestamps: List[int],
        open_: List[float],
        high: List[float],
        low: List[float],
        close: List[float],
        signals: List[int],
        fee_bps: int = 0,
        slip_bps: int = 0,
        stop_loss_bps: Optional[int] = None,
) -> Tuple[List[Trade], List[float]]:
    trades: List[Trade] = []
    eq: List[float] = []
    pos = 0
    entry_px = 0.0
    entry_ts = 0
    equity = 0.0
    bps_cost = (fee_bps + slip_bps) * 0.0001

    def exit_trade(i_idx: int):
        nonlocal pos, entry_px, entry_ts, equity
        if pos == 0:
            return
        px = close[i_idx]
        ts = timestamps[i_idx]
        raw_ret = (px - entry_px) / entry_px if pos > 0 else (entry_px - px) / entry_px
        pnl = raw_ret - 2 * bps_cost
        trades.append(Trade(entry_ts, entry_px, pos, ts, px, pnl))
        equity += pnl
        pos = 0
        entry_px = 0.0
        entry_ts = 0

    for i in range(len(close)):
        sig = signals[i] if i < len(signals) else 0
        eq.append(equity)

        if pos != 0 and stop_loss_bps is not None and stop_loss_bps > 0:
            adverse = (entry_px - low[i]) / entry_px if pos > 0 else (high[i] - entry_px) / entry_px
            if adverse > stop_loss_bps * 1e-4:
                exit_trade(i)
                continue

        if sig != pos:
            if pos != 0:
                exit_trade(i)
            if sig != 0:
                pos = sig
                entry_px = close[i]
                entry_ts = timestamps[i]

    if pos != 0:
        exit_trade(len(close) - 1)
        if eq:
            eq[-1] = eq[-1]
    return trades, eq


# ---- CSV helpers ----
def _save_trades_csv(path: str, trades: List[Trade]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["entry_ts", "entry_iso", "entry_px", "side", "exit_ts", "exit_iso", "exit_px", "pnl"])
        for t in trades:
            w.writerow([
                t.entry_ts,
                datetime.fromtimestamp(t.entry_ts, tz=timezone.utc).isoformat(),
                f"{t.entry_px:.6f}",
                t.side,
                t.exit_ts,
                datetime.fromtimestamp(t.exit_ts, tz=timezone.utc).isoformat(),
                f"{t.exit_px:.6f}",
                f"{t.pnl:.6f}",
            ])


def _save_equity_csv(path: str, timestamps: List[int], equity: List[float]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ts", "iso", "equity"])
        for ts, eq in zip(timestamps, equity):
            w.writerow([ts, datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(), f"{eq:.6f}"])


# ---- Common CLI args ----
def _add_common_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--strategy", default="sma")
    p.add_argument("--fast", type=int)
    p.add_argument("--slow", type=int)
    p.add_argument("--adx-len", dest="adx_len", type=int)
    p.add_argument("--adx-on", dest="on", type=float)
    p.add_argument("--adx-off", dest="off", type=float)
    p.add_argument("--require-di", action="store_true")
    p.add_argument("--atr-len", dest="atr_len", type=int)
    p.add_argument("--atr-mult", dest="atr_mult", type=float)
    p.add_argument("--st-len", type=int)
    p.add_argument("--st-mult", type=float)

    p.add_argument("--exmo-pair", dest="pair", default="DOGE_EUR")
    p.add_argument("--exmo-candles", dest="candles", default="1m:500")

    p.add_argument("--fee-bps", type=int, default=0)
    p.add_argument("--slip-bps", type=int, default=0)

    p.add_argument("--http-retries", type=int)
    p.add_argument("--http-backoff", type=float)

    p.add_argument("--debug", action="store_true")


def _add_risk_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--max-position-pct", type=float)
    p.add_argument("--stop-loss-bps", type=int)
    p.add_argument("--max-daily-loss-bps", type=int)


# ---- Commands ----
def _run_backtest(args: argparse.Namespace) -> int:
    LOG.info("Command: backtest")
    ts, o, h, l, c = _get_candles_arrays(args.pair, args.candles, args.http_retries, args.http_backoff)
    defn = strat_registry.get(args.strategy)
    params = _build_params_from_args(args.strategy, args)
    signals = defn.generate_signals(close=c, open=o, high=h, low=l, **params)  # type: ignore

    trades, equity = _run_backtest_signals(
        timestamps=ts, open_=o, high=h, low=l, close=c, signals=signals,
        fee_bps=args.fee_bps or 0, slip_bps=args.slip_bps or 0,
        stop_loss_bps=bps_or_none(getattr(args, "stop_loss_bps", None)),
    )

    wins = sum(1 for t in trades if t.pnl > 0)
    n = len(trades)
    win_rate = (wins / n * 100.0) if n else 0.0
    avg_pnl = (sum(t.pnl for t in trades) / n) if n else 0.0
    total_pnl = sum(t.pnl for t in trades)
    maxdd = _max_drawdown(equity)
    sharpe = _sharpe_by_trades([t.pnl for t in trades])

    LOG.info("Backtest %s %s strategy=%s params=%s", args.pair, args.candles, args.strategy, params)
    LOG.info("Trades: %s  WinRate: %.1f%%  AvgPnL: %.6f  TotalPnL: %.6f  MaxDD: %.6f  Sharpe(trades): %.2f",
             n, win_rate, avg_pnl, total_pnl, maxdd, sharpe)

    if getattr(args, "csv_trades", None):
        _save_trades_csv(args.csv_trades, trades)
        LOG.info("Saved trades CSV -> %s", args.csv_trades)
    if getattr(args, "csv_equity", None):
        _save_equity_csv(args.csv_equity, ts, equity)
        LOG.info("Saved equity CSV -> %s", args.csv_equity)
    return 0


def _run_live_observe(args: argparse.Namespace) -> int:
    LOG.info("Command: trade-live")
    params = _build_params_from_args(args.strategy, args)
    LOG.info("[live] observe %s %s strategy=%s params=%s poll=%ss",
             args.pair, args.candles, args.strategy, params, args.poll_sec)
    last_seen_ts = 0
    try:
        while True:
            ts, o, h, l, c = _get_candles_arrays(args.pair, args.candles, args.http_retries, args.http_backoff)
            if ts and ts[-1] != last_seen_ts:
                last_seen_ts = ts[-1]
                defn = strat_registry.get(args.strategy)
                status_text, state = defn.status(close=c, open=o, high=h, low=l, **params)  # type: ignore
                t_iso = datetime.fromtimestamp(ts[-1], tz=timezone.utc).isoformat()
                LOG.info("[live] %s %s", t_iso, status_text)
            time.sleep(max(1, int(args.poll_sec)))
    except KeyboardInterrupt:
        LOG.info("[live] stop by user")
    return 0


@dataclass
class PaperState:
    balance: float
    position: int
    pos_px: float
    last_day: str


def _load_state(path: Optional[str], initial_balance: float) -> PaperState:
    if not path or not os.path.exists(path):
        return PaperState(balance=initial_balance, position=0, pos_px=0.0, last_day="")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return PaperState(**data)
    except Exception:
        return PaperState(balance=initial_balance, position=0, pos_px=0.0, last_day="")


def _save_state(path: Optional[str], state: PaperState) -> None:
    if not path:
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(state), f, ensure_ascii=False, indent=2)


def _run_live_paper(args: argparse.Namespace) -> int:
    LOG.info("Command: trade-live")
    params = _build_params_from_args(args.strategy, args)
    LOG.info("[live:paper] %s %s strategy=%s params=%s poll=%ss",
             args.pair, args.candles, args.strategy, params, args.poll_sec)

    initial_balance = as_float_or_none(getattr(args, "initial_balance", None)) or 1000.0
    fee_bps = args.fee_bps or 0
    slip_bps = args.slip_bps or 0
    max_pos_pct = pct01_or_none(getattr(args, "max_position_pct", None)) or 1.0
    stop_loss_bps = bps_or_none(getattr(args, "stop_loss_bps", None))
    max_daily_loss_bps = bps_or_none(getattr(args, "max_daily_loss_bps", None))
    _ = max_daily_loss_bps  # (зарезервировано под дневной стоп)

    state = _load_state(getattr(args, "state_file", None), initial_balance)
    last_seen_ts = 0
    trades_out: List[Trade] = []
    eq_out_ts: List[int] = []
    eq_out: List[float] = []

    try:
        while True:
            ts, o, h, l, c = _get_candles_arrays(args.pair, args.candles, args.http_retries, args.http_backoff)
            if not ts or ts[-1] == last_seen_ts:
                time.sleep(max(1, int(args.poll_sec)))
                continue
            last_seen_ts = ts[-1]

            defn = strat_registry.get(args.strategy)
            status_text, state_info = defn.status(close=c, open=o, high=h, low=l, **params)  # type: ignore
            sig = int(state_info.get("signal", 0)) if isinstance(state_info, dict) else 0

            px = c[-1]
            tstamp = ts[-1]
            bps_cost = (fee_bps + slip_bps) * 1e-4

            if state.position != 0 and stop_loss_bps:
                adverse = (state.pos_px - l[-1]) / state.pos_px if state.position > 0 else (h[
                                                                                                -1] - state.pos_px) / state.pos_px
                if adverse > stop_loss_bps * 1e-4:
                    raw_ret = (px - state.pos_px) / state.pos_px if state.position > 0 else (
                                                                                                        state.pos_px - px) / state.pos_px
                    pnl = raw_ret - 2 * bps_cost
                    state.balance *= (1.0 + pnl * max_pos_pct)
                    trades_out.append(Trade(entry_ts=tstamp, entry_px=state.pos_px, side=state.position,
                                            exit_ts=tstamp, exit_px=px, pnl=pnl))
                    state.position = 0
                    state.pos_px = 0.0

            if sig != state.position:
                if state.position != 0:
                    raw_ret = (px - state.pos_px) / state.pos_px if state.position > 0 else (
                                                                                                        state.pos_px - px) / state.pos_px
                    pnl = raw_ret - 2 * bps_cost
                    state.balance *= (1.0 + pnl * max_pos_pct)
                    trades_out.append(Trade(entry_ts=tstamp, entry_px=state.pos_px, side=state.position,
                                            exit_ts=tstamp, exit_px=px, pnl=pnl))
                    state.position = 0
                    state.pos_px = 0.0
                if sig != 0:
                    state.position = sig
                    state.pos_px = px

            eq_out_ts.append(tstamp)
            eq_out.append(state.balance)

            t_iso = datetime.fromtimestamp(tstamp, tz=timezone.utc).isoformat()
            LOG.info("[live:paper] %s close=%.6f sig=%+d %s", t_iso, px, sig, status_text)

            _save_state(getattr(args, "state_file", None), state)
            if getattr(args, "csv_trades", None) and trades_out:
                _save_trades_csv(args.csv_trades, trades_out)
            if getattr(args, "csv_equity", None) and eq_out_ts:
                _save_equity_csv(args.csv_equity, eq_out_ts, eq_out)

            time.sleep(max(1, int(args.poll_sec)))
    except KeyboardInterrupt:
        LOG.info("[live:paper] stop by user")
        if getattr(args, "csv_trades", None) and trades_out:
            LOG.info("Saved trades CSV -> %s", args.csv_trades)
        if getattr(args, "csv_equity", None) and eq_out_ts:
            LOG.info("Saved equity CSV -> %s", args.csv_equity)
    return 0


# ---- Research commands ----
def _require_sel() -> None:
    if sel is None:
        raise RuntimeError("Research selector module not available (src/application/research/selector.py).")


def _resolve_strategies(spec: str) -> List[str]:
    spec = (spec or "").strip()
    if spec == "auto":
        return ["sma", "ema", "ema_adx", "ema_adx_atr", "supertrend", "keltner",
                "adx", "sma_atr", "rsi2", "donchian", "bbands", "roc"]
    if "," in spec:
        return [x.strip() for x in spec.split(",") if x.strip()]
    return [spec] if spec else []


def _run_sweep(args: argparse.Namespace) -> int:
    _require_sel()
    LOG.info("Command: sweep")
    strategies = _resolve_strategies(args.strategies)
    LOG.info("Sweep %s %s strategies=%s metric=%s", args.pair, args.candles, strategies, args.metric)
    results = sel.sweep(  # type: ignore[attr-defined]
        pair=args.pair,
        candles_spec=args.candles,
        strategies=strategies,
        metric=args.metric,
        top_n=args.top_n,
        min_trades=args.min_trades,
        grid_file=getattr(args, "grid_file", None),
        http_retries=args.http_retries,
        http_backoff=args.http_backoff,
    )
    if getattr(args, "csv_results", None):
        os.makedirs(os.path.dirname(args.csv_results) or ".", exist_ok=True)
        with open(args.csv_results, "w", encoding="utf-8", newline="") as f:
            csv.writer(f).writerows(results)
        LOG.info("Saved sweep CSV -> %s", args.csv_results)
    return 0


def _run_optimize(args: argparse.Namespace) -> int:
    _require_sel()
    LOG.info("Command: optimize")
    LOG.info("Optimize %s %s strategy=%s metric=%s", args.pair, args.candles, args.strategy, args.metric)
    results = sel.optimize(  # type: ignore[attr-defined]
        pair=args.pair,
        candles_spec=args.candles,
        strategy=args.strategy,
        metric=args.metric,
        top_n=args.top_n,
        min_trades=args.min_trades,
        grid_file=getattr(args, "grid_file", None),
        http_retries=args.http_retries,
        http_backoff=args.http_backoff,
    )
    if getattr(args, "csv_results", None):
        os.makedirs(os.path.dirname(args.csv_results) or ".", exist_ok=True)
        with open(args.csv_results, "w", encoding="utf-8", newline="") as f:
            csv.writer(f).writerows(results)
        LOG.info("Saved optimize CSV -> %s", args.csv_results)
    return 0


def _run_robustness(args: argparse.Namespace) -> int:
    _require_sel()
    LOG.info("Command: robustness")
    results = sel.robustness(  # type: ignore[attr-defined]
        pair=args.pair,
        candles_spec=args.candles,
        strategy=args.strategy,
        params=_build_params_from_args(args.strategy, args),
        level=args.robust_level,
        samples=args.samples,
        http_retries=args.http_retries,
        http_backoff=args.http_backoff,
    )
    if getattr(args, "csv_results", None):
        os.makedirs(os.path.dirname(args.csv_results) or ".", exist_ok=True)
        with open(args.csv_results, "w", encoding="utf-8", newline="") as f:
            csv.writer(f).writerows(results)
        LOG.info("Saved robustness CSV -> %s", args.csv_results)
    return 0


def _run_walk_forward(args: argparse.Namespace) -> int:
    _require_sel()
    LOG.info("Command: walk-forward")
    strategies = _resolve_strategies(args.strategies)
    results = sel.walk_forward(  # type: ignore[attr-defined]
        pair=args.pair,
        candles_spec=args.candles,
        strategies=strategies,
        wf_folds=args.wf_folds,
        wf_train_frac=args.wf_train_frac,
        metric=args.metric,
        min_trades=args.min_trades,
        grid_file=getattr(args, "grid_file", None),
        http_retries=args.http_retries,
        http_backoff=args.http_backoff,
    )
    if getattr(args, "csv_results", None):
        os.makedirs(os.path.dirname(args.csv_results) or ".", exist_ok=True)
        with open(args.csv_results, "w", encoding="utf-8", newline="") as f:
            csv.writer(f).writerows(results)
        LOG.info("Saved walk-forward CSV -> %s", args.csv_results)
    return 0


# ---- Parser/Dispatcher ----
def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="exmo-bot", add_help=True)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("backtest", help="Run simple backtest over candles")
    _add_common_args(p)
    _add_risk_args(p)
    p.add_argument("--csv-trades")
    p.add_argument("--csv-equity")
    p.set_defaults(_handler=_run_backtest)

    p = sub.add_parser("trade-live", help="Run live engine (observe or paper)")
    _add_common_args(p)
    p.add_argument("--mode", choices=["observe", "paper"], default="observe")
    p.add_argument("--poll-sec", type=int, default=10)
    p.add_argument("--heartbeat-sec", type=int, default=60)
    p.add_argument("--initial-balance", type=float)
    _add_risk_args(p)
    p.add_argument("--state-file")
    p.add_argument("--csv-trades")
    p.add_argument("--csv-equity")
    p.set_defaults(_handler=lambda a: _run_live_paper(a) if a.mode == "paper" else _run_live_observe(a))

    p = sub.add_parser("sweep", help="Grid search over multiple strategies")
    _add_common_args(p)
    p.add_argument("--strategies", default="auto")
    p.add_argument("--metric", default="sharpe")
    p.add_argument("--top-n", type=int, default=8)
    p.add_argument("--min-trades", type=int, default=3)
    p.add_argument("--grid-file")
    p.add_argument("--csv-results")
    p.set_defaults(_handler=_run_sweep)

    p = sub.add_parser("optimize", help="Optimize a single strategy over a grid")
    _add_common_args(p)
    p.add_argument("--metric", default="sharpe")
    p.add_argument("--top-n", type=int, default=10)
    p.add_argument("--min-trades", type=int, default=3)
    p.add_argument("--grid-file")
    p.add_argument("--csv-results")
    p.set_defaults(_handler=_run_optimize)

    p = sub.add_parser("robustness", help="Noise/perturbation robustness check")
    _add_common_args(p)
    p.add_argument("--robust-level", dest="robust_level", choices=["lite", "std", "hard"], default="std")
    p.add_argument("--samples", type=int, default=10)
    p.add_argument("--csv-results")
    p.set_defaults(_handler=_run_robustness)

    p = sub.add_parser("walk-forward", help="Walk-forward validation")
    _add_common_args(p)
    p.add_argument("--strategies", default="auto")
    p.add_argument("--wf-folds", type=int, default=3)
    p.add_argument("--wf-train-frac", type=float, default=0.7)
    p.add_argument("--metric", default="sharpe")
    p.add_argument("--min-trades", type=int, default=5)
    p.add_argument("--grid-file")
    p.add_argument("--csv-results")
    p.set_defaults(_handler=_run_walk_forward)

    return ap


def _dispatch_command(args: argparse.Namespace) -> int:
    handler = getattr(args, "_handler", None)
    if handler is None:
        raise SystemExit("No handler bound to command.")
    return handler(args)


def _run_cli(argv: Sequence[str]) -> int:
    debug = any(a in ("--debug",) for a in argv)
    _setup_logging(debug)
    parser = _build_parser()
    args = parser.parse_args(list(argv))
    return _dispatch_command(args)


if __name__ == "__main__":
    sys.exit(_run_cli(sys.argv[1:]))
