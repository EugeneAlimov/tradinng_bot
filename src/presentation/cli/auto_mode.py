# src/presentation/cli/auto_mode.py
from __future__ import annotations

import json
import os
import sys
import logging
from dataclasses import dataclass
from typing import Any, Dict, List

# --- engine hooks (оставляем как было)
from src.presentation.cli.engine import (
    run_optimize,
    run_robustness,
    run_walk_forward,
)

log = logging.getLogger("auto_mode")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


# ===== Grid resolver (совместимость по расположению и имени функции) ==========

def _import_registry_module():
    """
    Пытаемся найти модуль реестра стратегий:
      1) src.backtest.registry
      2) src.domain.strategy.registry
    """
    try:
        import importlib
        return importlib.import_module("src.backtest.registry")
    except Exception:
        pass
    try:
        import importlib
        return importlib.import_module("src.domain.strategy.registry")
    except Exception:
        pass
    raise ImportError("Cannot import strategy registry from either "
                      "`src.backtest.registry` or `src.domain.strategy.registry`")


def _get_default_grid(strategy_name: str) -> List[Dict[str, Any]]:
    """
    Поддерживаем разные API:
      - get_default_grid() -> {name: grid[]}
      - get_default_grid(name) -> grid[]
      - get_default_param_grid(name) -> grid[]
      - default_grid(name) -> grid[]   ИЛИ  default_grid() -> {name: grid[]}
    """
    reg = _import_registry_module()

    # 1) get_default_grid
    if hasattr(reg, "get_default_grid"):
        fn = getattr(reg, "get_default_grid")
        try:
            grid_map = fn()  # вариант без аргументов, вернёт dict
            if isinstance(grid_map, dict):
                return list(grid_map.get(strategy_name, []))
        except TypeError:
            # вариант с именем стратегии
            try:
                res = fn(strategy_name)
                if isinstance(res, list):
                    return list(res)
            except Exception:
                pass

    # 2) get_default_param_grid
    if hasattr(reg, "get_default_param_grid"):
        fn = getattr(reg, "get_default_param_grid")
        try:
            res = fn(strategy_name)
            if isinstance(res, list):
                return list(res)
        except Exception:
            pass

    # 3) default_grid
    if hasattr(reg, "default_grid"):
        fn = getattr(reg, "default_grid")
        try:
            res = fn(strategy_name)  # вариант с именем
            if isinstance(res, list):
                return list(res)
        except TypeError:
            # вариант без аргументов -> dict
            try:
                grid_map = fn()
                if isinstance(grid_map, dict):
                    return list(grid_map.get(strategy_name, []))
            except Exception:
                pass

    raise ImportError(f"Default grid function not found/unsupported in registry for '{strategy_name}'")


# ===== Параметры CLI авто-пайплайна ===========================================

@dataclass
class AutoArgs:
    pair: str  # "DOGE_EUR"
    candles: str  # "5m:800"
    strategy: str  # "ema_adx"
    top_n: int  # 10
    min_trades: int  # 2/3
    rb_windows: int  # 8
    wf_folds: int  # 6
    wf_train_frac: float  # 0.7
    out_dir: str  # "runs/auto"
    preset_path: str  # path to preset.json


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _sort_by_primary_metrics(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def key(r: Dict[str, Any]):
        m = r.get("metrics", {})
        return (
            float(m.get("sharpe", float("-inf"))),
            float(m.get("cagr", float("-inf"))),
            float(m.get("winrate", float("-inf"))),
            int(m.get("trades", -1)),
        )

    return sorted(results, key=key, reverse=True)


def _filter_min_trades(results: List[Dict[str, Any]], min_trades: int) -> List[Dict[str, Any]]:
    keep: List[Dict[str, Any]] = []
    for r in results:
        trades = int(r.get("metrics", {}).get("trades", 0))
        if trades >= min_trades:
            keep.append(r)
    return keep


def _take_top_params(results: List[Dict[str, Any]], n: int) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in results[:n]:
        p = dict(r.get("params", {}))
        for k in ("fast", "slow", "adx_len"):
            if isinstance(p.get(k), float):
                p[k] = int(round(p[k]))
        out.append({"params": p, "metrics": r.get("metrics", {})})
    return out


def _save_preset(path: str, pair: str, candles: str, strategy: str, params: Dict[str, Any]) -> None:
    preset = {
        "pair": pair,
        "timeframe": candles.split(":")[0],
        "strategy": strategy,
        "params": params,
        "risk": {"max_position_pct": 0.25, "stop_loss_bps": 250, "cooldown_bars": 3},
        "fees": {"fee_bps": 10, "slip_bps": 2},
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(preset, f, ensure_ascii=False, indent=2)


def _print_ready_command(pair: str, candles: str, strategy: str, params: Dict[str, Any]) -> None:
    tf = candles.split(":")[0]
    fast = params.get("fast")
    slow = params.get("slow")
    adx_len = params.get("adx_len")
    on = params.get("on")
    off = params.get("off")
    require_di = params.get("require_di", True)

    cmd = [
        "PYTHONPATH=. python -m src.presentation.cli.app",
        f"--pair {pair} --candles {tf}:2500",
        "trade-live",
        "--mode observe",
        f"--strategy {strategy}",
        f"--ema-fast {fast} --ema-slow {slow}",
        f"--adx-len {adx_len} --adx-on {on} --adx-off {off}" + (" --require-di" if require_di else ""),
        "--poll-sec 10 --summary-alert",
        "--risk-max-position-pct 25",
        "--risk-stop-loss-bps 250",
        "--cooldown-bars 3",
        "--fee-bps 10 --slip-bps 2",
        "--debug",
    ]
    print("\nReady-to-trade:\n" + " \\\n  ".join(cmd) + "\n")


# ===== Основной авто-пайплайн ==================================================

def run_auto_pipeline(a: AutoArgs) -> Dict[str, Any]:
    """
    optimize → robustness → walk-forward → best → save preset → print command
    """
    _ensure_dir(a.out_dir)

    # 1) GRID
    grid = _get_default_grid(a.strategy)
    if not grid:
        raise RuntimeError(f"Empty param grid for strategy={a.strategy}")

    # 2) OPTIMIZE
    log.info("Stage 1/3: optimize...")
    opt_results = run_optimize(
        pair=a.pair,
        candles=a.candles,
        strategy=a.strategy,
        grid=grid,
        top_n=a.top_n,
    )
    opt_results = _filter_min_trades(opt_results, a.min_trades)
    opt_results = _sort_by_primary_metrics(opt_results)
    top = _take_top_params(opt_results, a.top_n)
    if not top:
        raise RuntimeError("No candidates after optimize/min_trades")

    # 3) ROBUSTNESS
    log.info("Stage 2/3: robustness...")
    rb_results = run_robustness(
        pair=a.pair,
        candles=a.candles,
        strategy=a.strategy,
        candidates=[t["params"] for t in top],
        windows=a.rb_windows,
    )
    rb_results = _filter_min_trades(rb_results, a.min_trades)
    rb_results = _sort_by_primary_metrics(rb_results)
    rb_top = _take_top_params(rb_results, min(len(rb_results), a.top_n))
    if not rb_top:
        raise RuntimeError("No candidates after robustness")

    # 4) WALK-FORWARD
    log.info("Stage 3/3: walk-forward...")
    wf_results = run_walk_forward(
        pair=a.pair,
        candles=a.candles,
        strategy=a.strategy,
        candidates=[t["params"] for t in rb_top],
        folds=a.wf_folds,
        train_frac=a.wf_train_frac,
    )
    wf_results = _filter_min_trades(wf_results, a.min_trades)
    wf_results = _sort_by_primary_metrics(wf_results)
    best = wf_results[0] if wf_results else rb_top[0]

    params = dict(best.get("params", {}))
    for k in ("fast", "slow", "adx_len"):
        if k in params:
            params[k] = int(round(params[k]))

    # 5) SAVE + PRINT
    _save_preset(a.preset_path, a.pair, a.candles, a.strategy, params)
    log.info(f"Preset saved to: {a.preset_path}")
    _print_ready_command(a.pair, a.candles, a.strategy, params)

    return best


# ===== CLI-обёртка =============================================================

def _parse_cli(argv: List[str]) -> AutoArgs:
    import argparse
    p = argparse.ArgumentParser("auto_mode")
    p.add_argument("--pair", required=True)
    p.add_argument("--candles", required=True, help="e.g. 5m:800")
    p.add_argument("--strategy", default="ema_adx")
    p.add_argument("--top-n", type=int, default=10)
    p.add_argument("--min-trades", type=int, default=2)
    p.add_argument("--rb-windows", type=int, default=8)
    p.add_argument("--wf-folds", type=int, default=6)
    p.add_argument("--wf-train-frac", type=float, default=0.7)
    p.add_argument("--out-dir", default="runs/auto")
    p.add_argument("--preset-path", default=None)
    args = p.parse_args(argv)

    preset_path = args.preset_path or os.path.join(
        args.out_dir, f"preset_{args.strategy}_{args.pair}_{args.candles.split(':')[0]}.json"
    )
    return AutoArgs(
        pair=args.pair,
        candles=args.candles,
        strategy=args.strategy,
        top_n=args.top_n,
        min_trades=args.min_trades,
        rb_windows=args.rb_windows,
        wf_folds=args.wf_folds,
        wf_train_frac=args.wf_train_frac,
        out_dir=args.out_dir,
        preset_path=preset_path,
    )


def main():
    a = _parse_cli(sys.argv[1:])
    best = run_auto_pipeline(a)
    m = best.get("metrics", {})
    log.info(
        f"BEST — sharpe={m.get('sharpe')} cagr={m.get('cagr')} "
        f"winrate={m.get('winrate')} trades={m.get('trades')}"
    )


if __name__ == "__main__":
    main()
