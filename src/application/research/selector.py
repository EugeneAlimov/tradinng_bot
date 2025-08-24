# src/application/research/selector.py
from __future__ import annotations

import json
import math
import itertools
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Iterable

from src.domain.strategy import registry as strat_registry


# ---------- helpers: safe-call & backtest ----------

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
        "mdd": mdd,
        "sharpe": sharpe,
    }


# ---------- grids ----------

def _grid_product(grid: Dict[str, Iterable[Any]]) -> List[Dict[str, Any]]:
    keys = list(grid.keys())
    vals = [list(v) for v in grid.values()]
    return [dict(zip(keys, comb)) for comb in itertools.product(*vals)]


def default_grids() -> Dict[str, List[Dict[str, Any]]]:
    """Небольшие дефолтные сетки — безопасно и быстро прогоняются."""
    return {
        "sma": _grid_product({"fast": [6, 10, 12], "slow": [20, 25, 30]}),
        "ema": _grid_product({"fast": [9, 12], "slow": [21, 26, 34]}),
        "ema_adx": _grid_product({
            "fast": [9, 12], "slow": [21, 26],
            "adx_len": [14], "on": [20.0, 22.0, 25.0], "off": [16.0, 18.0, 20.0],
            "require_di": [True],
        }),
        "supertrend": _grid_product({"atr_len": [7, 10, 14], "mult": [2.5, 3.0, 3.5]}),
        "keltner": _grid_product({"kc_len": [20, 30], "kc_mult": [1.5, 2.0], "mode": ["breakout"]}),
        "adx": _grid_product({"adx_len": [14], "min_adx": [20.0, 25.0]}),
        "sma_atr": _grid_product({"fast": [6, 10], "slow": [25, 40], "atr_len": [14], "atr_mult": [2.5, 3.0], "chandelier_len": [22]}),
        "rsi2": _grid_product({"rsi_len": [2], "low": [5.0, 10.0], "high": [90.0, 95.0]}),
        "donchian": _grid_product({"n": [20, 55]}),
        "bbands": _grid_product({"length": [20], "mult": [2.0], "exit_rule": ["mid"]}),
        "roc": _grid_product({"length": [10, 20]}),
    }


def load_grid_json(path: Optional[str]) -> Optional[Dict[str, List[Dict[str, Any]]]]:
    if not path:
        return None
    with open(path, "r", encoding="utf-8") as f:
        obj = json.load(f)
    # ожидаем {strategy_name: [{...}, {...}], ...}
    if not isinstance(obj, dict):
        raise ValueError("grid JSON must be an object {strategy: [param_dicts...]}")
    norm: Dict[str, List[Dict[str, Any]]] = {}
    for k, v in obj.items():
        if isinstance(v, dict):  # поддержка dict of lists -> product
            norm[k] = _grid_product({kk: (vv if isinstance(vv, list) else [vv]) for kk, vv in v.items()})
        elif isinstance(v, list):
            norm[k] = [x for x in v if isinstance(x, dict)]
        else:
            raise ValueError(f"grid for '{k}' must be a dict or list of dict")
    return norm


# ---------- eval ----------

@dataclass
class EvalRow:
    strategy: str
    params: Dict[str, Any]
    n_trades: int
    win_rate: float
    avg_pnl: float
    total_pnl: float
    mdd: float
    sharpe: float

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
        if name not in g:
            # если сетка не задана явно — используем дефолт, если есть
            dg = default_grids().get(name, [])
        else:
            dg = g[name]
        for params in dg:
            row = eval_one(ohlc, name, params, fee_bps, slip_bps)
            if row.n_trades >= min_trades:
                results.append(row)
    return results


def rank(results: List[EvalRow], metric: str = "sharpe", top_n: int = 10) -> List[EvalRow]:
    key = metric.lower()
    if key == "sharpe":
        s = sorted(results, key=lambda r: (r.sharpe, r.total_pnl), reverse=True)
    elif key in ("total", "total_pnl"):
        s = sorted(results, key=lambda r: (r.total_pnl, r.sharpe), reverse=True)
    elif key in ("win", "winrate"):
        s = sorted(results, key=lambda r: (r.win_rate, r.sharpe), reverse=True)
    else:
        s = sorted(results, key=lambda r: (r.sharpe, r.total_pnl), reverse=True)
    return s[:max(1, top_n)]


# ---------- walk-forward ----------

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
                 rank_metric: str = "sharpe") -> Tuple[List[WFFold], Dict[str, Any]]:
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

    # агрегируем тестовые метрики
    agg = {"folds": len(folds_out), "n_trades": 0, "total_pnl": 0.0, "avg_sharpe": 0.0}
    sh_list: List[float] = []
    for f in folds_out:
        if f.test_eval:
            agg["n_trades"] += f.test_eval.n_trades
            agg["total_pnl"] += f.test_eval.total_pnl
            sh_list.append(f.test_eval.sharpe)
    agg["avg_sharpe"] = (sum(sh_list) / len(sh_list)) if sh_list else 0.0
    return folds_out, agg
