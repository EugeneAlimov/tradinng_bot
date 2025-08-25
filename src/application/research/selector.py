# src/application/research/selector.py
from __future__ import annotations

import itertools
import json
import math
import random
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

from src.domain.strategy import registry as strat_registry


# =========================
# Low-level helpers
# =========================

def _safe_call(fn, arrays: Dict[str, List[float]], params: Dict[str, Any]):
    import inspect
    candidate = {
        "prices": arrays.get("close"),
        "ts": arrays.get("ts"),
        "close": arrays.get("close"),
        "open": arrays.get("open"),
        "high": arrays.get("high"),
        "low": arrays.get("low"),
        **(params or {}),
    }
    sig = inspect.signature(fn)
    return fn(**{k: v for k, v in candidate.items() if k in sig.parameters})


def _backtest_long_only(prices: List[float], timestamps: List[int], signals: List[int],
                        fee_bps: int, slip_bps: int) -> Dict[str, Any]:
    fee = fee_bps / 1e4
    slip = slip_bps / 1e4
    position = 0
    entry_price = 0.0
    entry_ts = 0
    trades: List[Dict[str, Any]] = []
    equity_steps: List[Tuple[int, float]] = []
    equity = 0.0

    for i, sig in enumerate(signals):
        px = prices[i]
        ts = timestamps[i]
        if sig == +1 and position == 0:
            fill = px * (1 + slip)
            cost = fill * (1 + fee)
            entry_price = cost
            entry_ts = ts
            position = 1
        elif sig == -1 and position == 1:
            fill = px * (1 - slip)
            proceeds = fill * (1 - fee)
            pnl = proceeds - entry_price
            trades.append({
                "entry_ts": entry_ts, "entry": entry_price,
                "exit_ts": ts, "exit": proceeds,
                "pnl": pnl, "ret": (pnl / entry_price) if entry_price else 0.0,
            })
            equity += pnl
            equity_steps.append((ts, equity))
            position = 0

    if position == 1 and prices:
        px = prices[-1]
        ts = timestamps[-1]
        fill = px * (1 - slip)
        proceeds = fill * (1 - fee)
        pnl = proceeds - entry_price
        trades.append({
            "entry_ts": entry_ts, "entry": entry_price,
            "exit_ts": ts, "exit": proceeds,
            "pnl": pnl, "ret": (pnl / entry_price) if entry_price else 0.0,
        })
        equity += pnl
        equity_steps.append((ts, equity))

    total_pnl = sum(t["pnl"] for t in trades)
    rets = [t["ret"] for t in trades if math.isfinite(t["ret"])]
    wins = sum(1 for t in trades if t["pnl"] > 0)
    n = len(trades)
    avg_pnl = (total_pnl / n) if n else 0.0
    win_rate = (wins / n) if n else 0.0

    mdd = 0.0
    peak = -1e18
    for _, eq in equity_steps:
        if eq > peak:
            peak = eq
        mdd = min(mdd, eq - peak)

    if len(rets) >= 2:
        mu = sum(rets) / len(rets)
        var = sum((r - mu) ** 2 for r in rets) / (len(rets) - 1)
        std = math.sqrt(var) if var > 0 else 0.0
        sharpe = (mu / std) * math.sqrt(len(rets)) if std > 0 else 0.0
    else:
        sharpe = 0.0

    return {
        "trades": trades,
        "equity_steps": equity_steps,
        "n_trades": n,
        "total_pnl": total_pnl,
        "avg_pnl": avg_pnl,
        "win_rate": win_rate,
        "mdd": mdd,  # <= 0
        "sharpe": sharpe,
    }


# =========================
# Grids
# =========================

def _grid_product(grid: Dict[str, Iterable[Any]]) -> List[Dict[str, Any]]:
    keys = list(grid.keys())
    vals = [list(v) for v in grid.values()]
    return [dict(zip(keys, comb)) for comb in itertools.product(*vals)]


def default_grids() -> Dict[str, List[Dict[str, Any]]]:
    return {
        "sma": _grid_product({"fast": [6, 10, 12], "slow": [20, 25, 30]}),
        "ema": _grid_product({"fast": [9, 12], "slow": [21, 26, 34]}),
        "ema_adx": _grid_product({
            "fast": [9, 12], "slow": [21, 26],
            "adx_len": [14], "on": [20.0, 22.0, 25.0], "off": [16.0, 18.0, 20.0],
            "require_di": [True],
        }),
        "ema_adx_atr": _grid_product({
            "fast": [9, 12],
            "slow": [21, 26, 34],
            "adx_len": [14],
            "on": [20.0, 22.0, 25.0],
            "off": [16.0, 18.0, 20.0],
            "require_di": [True],
            "atr_len": [14],
            "atr_mult": [2.5, 3.0]
        }),
        "supertrend": _grid_product({"atr_len": [7, 10, 14], "mult": [2.5, 3.0, 3.5]}),
        "keltner": _grid_product({"kc_len": [20, 30], "kc_mult": [1.5, 2.0], "mode": ["breakout"]}),
        "adx": _grid_product({"adx_len": [14], "min_adx": [20.0, 25.0]}),
        "sma_atr": _grid_product(
            {"fast": [6, 10], "slow": [25, 40], "atr_len": [14], "atr_mult": [2.5, 3.0], "chandelier_len": [22]}),
        "rsi2": _grid_product({"rsi_len": [2], "low": [5.0, 10.0], "high": [90.0, 95.0]}),
        "donchian": _grid_product({"n": [20, 55]}),
        "bbands": _grid_product({"length": [20], "mult": [2.0], "exit_rule": ["mid"]}),
        "roc": _grid_product({"length": [10, 20]}),
    }


def load_grid_json(path: Optional[str]) -> Optional[Dict[str, List[Dict[str, Any]]]]:
    """
    Читает JSON-грид из файла или из stdin, если path == "-".
    Форматы:
      - { "strategy": {param: [..], ...}, ... }  -> Декартово произведение
      - { "strategy": [ {param: val, ...}, ...], ... } -> Список пресетов
    """
    if not path:
        return None

    import sys
    if path == "-":
        obj = json.load(sys.stdin)
    else:
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)

    if not isinstance(obj, dict):
        raise ValueError("grid JSON must be an object {strategy: [param_dicts...] or dict-of-lists}")

    norm: Dict[str, List[Dict[str, Any]]] = {}
    for k, v in obj.items():
        if isinstance(v, dict):
            norm[k] = _grid_product({kk: (vv if isinstance(vv, list) else [vv]) for kk, vv in v.items()})
        elif isinstance(v, list):
            norm[k] = [x for x in v if isinstance(x, dict)]
        else:
            raise ValueError(f"grid for '{k}' must be a dict or list of dict")
    return norm


# =========================
# Evaluation rows
# =========================

@dataclass
class EvalRow:
    strategy: str
    params: Dict[str, Any]
    n_trades: int
    win_rate: float  # 0..1
    avg_pnl: float
    total_pnl: float
    mdd: float  # <= 0 (equity drawdown in absolute PnL units)
    sharpe: float
    score: float = 0.0  # filled by scoring

    def to_list(self) -> List[Any]:
        return [
            self.strategy,
            self.params,
            self.n_trades,
            round(self.win_rate * 100, 1),
            round(self.avg_pnl, 6),
            round(self.total_pnl, 6),
            round(self.mdd, 6),
            round(self.sharpe, 3),
            round(self.score, 3),
        ]


def eval_one(ohlc: Dict[str, List[float]], strategy: str, params: Dict[str, Any],
             fee_bps: int, slip_bps: int) -> EvalRow:
    defn = strat_registry.get(strategy)
    signals = _safe_call(defn.generate_signals, ohlc, params)
    stats = _backtest_long_only(ohlc["close"], ohlc["ts"], signals, fee_bps, slip_bps)
    return EvalRow(
        strategy=strategy,
        params=dict(params),
        n_trades=stats["n_trades"],
        win_rate=stats["win_rate"],
        avg_pnl=stats["avg_pnl"],
        total_pnl=stats["total_pnl"],
        mdd=stats["mdd"],
        sharpe=stats["sharpe"],
    )


def sweep(ohlc: Dict[str, List[float]],
          strategies: List[str],
          grid: Optional[Dict[str, List[Dict[str, Any]]]],
          fee_bps: int, slip_bps: int,
          min_trades: int = 3) -> List[EvalRow]:
    g = grid or default_grids()
    results: List[EvalRow] = []
    for name in strategies:
        dg = g.get(name, default_grids().get(name, []))
        for params in dg:
            row = eval_one(ohlc, name, params, fee_bps, slip_bps)
            if row.n_trades >= min_trades:
                results.append(row)
    return results


# =========================
# Scoring & constraints
# =========================

@dataclass
class ScoreWeights:
    w_sharpe: float = 1.0
    w_total: float = 0.75
    w_win: float = 0.25
    w_dd: float = 0.5  # applies to (1 - norm(abs(DD)))
    w_trades: float = 0.2


@dataclass
class Constraints:
    min_trades: int = 3
    min_win: Optional[float] = None  # in [0..1]
    max_dd_abs: Optional[float] = None  # absolute |mdd| upper bound


def _minmax(xs: List[float]) -> Tuple[List[float], float, float]:
    if not xs:
        return [], 0.0, 1.0
    lo = min(xs)
    hi = max(xs)
    if hi - lo < 1e-12:
        return [0.5 for _ in xs], lo, hi
    return [(x - lo) / (hi - lo) for x in xs], lo, hi


def apply_constraints(rows: List[EvalRow], cons: Constraints) -> List[EvalRow]:
    out: List[EvalRow] = []
    for r in rows:
        if r.n_trades < cons.min_trades:
            continue
        if cons.min_win is not None and r.win_rate < cons.min_win:
            continue
        if cons.max_dd_abs is not None and abs(r.mdd) > cons.max_dd_abs:
            continue
        out.append(r)
    return out


def score_rows(rows: List[EvalRow], w: ScoreWeights) -> List[EvalRow]:
    """
    Заполняет r.score нормированной смесью метрик.
    ВАЖНО: берём ИМЕННО первый элемент из _minmax(...) — список нормированных значений.
    """
    if not rows:
        return rows

    sharpe_norm, _, _ = _minmax([r.sharpe for r in rows])
    total_norm, _, _ = _minmax([r.total_pnl for r in rows])
    win_vals = [r.win_rate for r in rows]  # уже 0..1
    trades_norm, _, _ = _minmax([float(r.n_trades) for r in rows])
    dd_abs = [abs(r.mdd) for r in rows]
    dd_norm_raw, _, _ = _minmax(dd_abs)
    dd_norm = [1.0 - x for x in dd_norm_raw]  # меньше DD -> лучше

    # подстраховка на случай NaN/inf
    def _clean(x: float) -> float:
        if not math.isfinite(x):
            return 0.0
        return max(0.0, min(1.0, x))

    sharpe_norm = [_clean(x) for x in sharpe_norm]
    total_norm = [_clean(x) for x in total_norm]
    win_vals = [_clean(x) for x in win_vals]
    trades_norm = [_clean(x) for x in trades_norm]
    dd_norm = [_clean(x) for x in dd_norm]

    for i, r in enumerate(rows):
        r.score = (
                w.w_sharpe * sharpe_norm[i] +
                w.w_total * total_norm[i] +
                w.w_win * win_vals[i] +
                w.w_dd * dd_norm[i] +
                w.w_trades * trades_norm[i]
        )
    return rows


def rank(rows: List[EvalRow], metric: str = "sharpe", top_n: int = 10) -> List[EvalRow]:
    key = metric.lower()
    if key == "score":
        s = sorted(rows, key=lambda r: (r.score, r.sharpe, r.total_pnl), reverse=True)
    elif key == "sharpe":
        s = sorted(rows, key=lambda r: (r.sharpe, r.total_pnl), reverse=True)
    elif key in ("total", "total_pnl"):
        s = sorted(rows, key=lambda r: (r.total_pnl, r.sharpe), reverse=True)
    elif key in ("win", "winrate"):
        s = sorted(rows, key=lambda r: (r.win_rate, r.sharpe), reverse=True)
    else:
        s = sorted(rows, key=lambda r: (r.sharpe, r.total_pnl), reverse=True)
    return s[:max(1, top_n)]


# =========================
# Robustness
# =========================

@dataclass
class RobustCfg:
    # процентные множители комиссий/проскальзывания (1.0 = базовое)
    fee_mults: Tuple[float, ...] = (1.0, 1.5, 2.0)
    slip_mults: Tuple[float, ...] = (1.0, 1.5, 2.0)
    # амплитуда шума на OHLC в bps цены (0.0..)
    noise_bps: Tuple[float, ...] = (0.0, 5.0, 10.0)
    # смещение окна (бар-алайнмент), сколько баров можно «сдвинуть»
    bar_shifts: Tuple[int, ...] = (0, 1, 2)
    # джиттер параметров (% от значения, применяется симметрично)
    param_jitter_pct: float = 0.1
    # сэмплов на одну конфигурацию
    samples: int = 1


def _jitter_params(params: Dict[str, Any], pct: float) -> Dict[str, Any]:
    out = dict(params)
    for k, v in list(out.items()):
        if isinstance(v, (int, float)):
            delta = abs(v) * pct
            if isinstance(v, int):
                out[k] = max(1, int(round(v + random.uniform(-delta, delta))))
            else:
                out[k] = v + random.uniform(-delta, delta)
    return out


def _apply_noise_ohlc(ohlc: Dict[str, List[float]], bps: float) -> Dict[str, List[float]]:
    if bps <= 0:
        return ohlc
    scale = bps / 1e4
    rnd = random.random
    noisy = {}
    for k in ("open", "high", "low", "close"):
        arr = []
        for px in ohlc[k]:
            noise = (rnd() - 0.5) * 2.0 * scale * px
            arr.append(max(1e-12, px + noise))
        noisy[k] = arr
    noisy["ts"] = list(ohlc["ts"])
    return noisy


def _shift_slice(ohlc: Dict[str, List[float]], shift: int) -> Dict[str, List[float]]:
    if shift <= 0:
        return ohlc
    n = len(ohlc["close"])
    s = min(shift, max(0, n - 5))
    return {k: v[s:] for k, v in ohlc.items()}


@dataclass
class RobustResult:
    passes: int
    total: int
    avg_sharpe: float
    avg_total: float
    worst_sharpe: float
    worst_total: float
    score: float


def robustness(ohlc: Dict[str, List[float]], strategy: str, params: Dict[str, Any],
               fee_bps: int, slip_bps: int, cfg: RobustCfg) -> RobustResult:
    defn = strat_registry.get(strategy)

    res_sh: List[float] = []
    res_tot: List[float] = []
    passed = 0
    total = 0

    for fm in cfg.fee_mults:
        for sm in cfg.slip_mults:
            for nb in cfg.noise_bps:
                for bs in cfg.bar_shifts:
                    for _ in range(max(1, cfg.samples)):
                        p = _jitter_params(params, cfg.param_jitter_pct) if cfg.param_jitter_pct > 0 else params
                        o = _apply_noise_ohlc(ohlc, nb)
                        o = _shift_slice(o, bs)

                        signals = _safe_call(defn.generate_signals, o, p)
                        stats = _backtest_long_only(o["close"], o["ts"], signals,
                                                    int(round(fee_bps * fm)),
                                                    int(round(slip_bps * sm)))
                        total += 1
                        res_sh.append(stats["sharpe"])
                        res_tot.append(stats["total_pnl"])
                        if stats["sharpe"] > 0.0 and stats["total_pnl"] > 0.0:
                            passed += 1

    avg_sh = sum(res_sh) / len(res_sh) if res_sh else 0.0
    avg_tot = sum(res_tot) / len(res_tot) if res_tot else 0.0
    worst_sh = min(res_sh) if res_sh else 0.0
    worst_tot = min(res_tot) if res_tot else 0.0
    # интегральная оценка: доля прохождений + усреднённые метрики
    score = (passed / total if total else 0.0) + 0.25 * max(0.0, avg_sh) + 0.1 * max(0.0, avg_tot)
    return RobustResult(passed, total, avg_sh, avg_tot, worst_sh, worst_tot, score)


# =========================
# Walk-Forward
# =========================

@dataclass
class WFFold:
    train_from: int
    train_to: int
    test_from: int
    test_to: int
    best: Optional[EvalRow]
    test_eval: Optional[EvalRow]


def _slice_ohlc(ohlc: Dict[str, List[float]], start: int, end: int) -> Dict[str, List[float]]:
    keys = ["ts", "open", "high", "low", "close"]
    return {k: ohlc[k][start:end] for k in keys}


def walk_forward(ohlc: Dict[str, List[float]],
                 strategies: List[str],
                 grid: Optional[Dict[str, List[Dict[str, Any]]]],
                 fee_bps: int, slip_bps: int,
                 folds: int = 3,
                 train_frac: float = 0.7,
                 min_trades: int = 3,
                 rank_metric: str = "sharpe",
                 score_weights: Optional[ScoreWeights] = None,
                 constraints: Optional[Constraints] = None) -> Tuple[List[WFFold], Dict[str, Any]]:
    n = len(ohlc["close"])
    train_len = max(10, int(n * train_frac))
    test_len = max(5, int((n - train_len) / max(1, folds)))
    folds_out: List[WFFold] = []
    pos = train_len
    for _ in range(folds):
        tr_from = 0
        tr_to = pos
        te_from = pos
        te_to = min(n, pos + test_len)
        if te_from >= te_to:
            break
        tr = _slice_ohlc(ohlc, tr_from, tr_to)
        te = _slice_ohlc(ohlc, te_from, te_to)

        sw = sweep(tr, strategies, grid, fee_bps, slip_bps, min_trades=min_trades)
        if constraints:
            sw = apply_constraints(sw, constraints)
        if score_weights and rank_metric == "score":
            sw = score_rows(sw, score_weights)
        ranked = rank(sw, metric=rank_metric, top_n=1)
        best = ranked[0] if ranked else None

        test_eval = None
        if best is not None:
            test_eval = eval_one(te, best.strategy, best.params, fee_bps, slip_bps)

        folds_out.append(WFFold(
            train_from=tr_from, train_to=tr_to,
            test_from=te_from, test_to=te_to,
            best=best, test_eval=test_eval
        ))
        pos = te_to

    agg = {"folds": len(folds_out), "n_trades": 0, "total_pnl": 0.0, "avg_sharpe": 0.0}
    sh_list: List[float] = []
    for f in folds_out:
        if f.test_eval:
            agg["n_trades"] += f.test_eval.n_trades
            agg["total_pnl"] += f.test_eval.total_pnl
            sh_list.append(f.test_eval.sharpe)
    agg["avg_sharpe"] = (sum(sh_list) / len(sh_list)) if sh_list else 0.0
    return folds_out, agg
