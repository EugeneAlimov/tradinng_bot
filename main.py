#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import inspect
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

# Настройки (ENV/.env/YAML) — безопасны, если файл отсутствует
try:
    from src.config.settings import load_settings
except Exception:
    def load_settings():
        class _S:
            exmo_api_key = None
            exmo_api_secret = None
            exmo_base_url = "https://api.exmo.com/v1.1"
            exmo_timeout = 20
            default_pair = None
            max_notional_eur = 100.0
            maker_by_default = True
            data_dir = Path("data")
            nonce_file = Path("data/.exmo_nonce")
            log_level = "INFO"
            mask_api_keys_in_logs = True
            debug = False
            @property
            def log_level_int(self) -> int:
                return logging.INFO
        return _S()

# Новая подкоманда live-trade (из нашего модуля)
try:
    from src.presentation.cli.trade_live_cmd import register_trade_live
except Exception:
    def register_trade_live(_):  # мягкий фолбэк
        pass


# -----------------------------
# Утилиты CLI/парсинга списков
# -----------------------------

def _normalize_resample(s: str) -> str:
    """
    В проекте встречались '5m' и '5T'. Оставим как есть — Pandas поймёт оба.
    Чуть нормализуем пробелы/регистр.
    """
    return str(s or "").strip()


def _parse_range_spec(spec: str) -> List[float]:
    """
    Разбор формата "start:end:step" (включительно), поддерживает float.
    Примеры:
      "5:20:5" -> [5, 10, 15, 20]
      "0.1:0.5:0.1" -> [0.1, 0.2, 0.3, 0.4, 0.5]
    """
    parts = [p.strip() for p in str(spec).split(":")]
    if len(parts) != 3:
        raise ValueError(f"Bad range spec: {spec!r}. Expected 'start:end:step'.")
    start, end, step = map(float, parts)
    if step == 0:
        raise ValueError("step must be non-zero")
    out: List[float] = []
    x = start
    # учитываем направление шага
    if step > 0:
        while x <= end + 1e-12:
            out.append(round(x, 12))
            x += step
    else:
        while x >= end - 1e-12:
            out.append(round(x, 12))
            x += step
    return out


def _parse_num_list(spec: Optional[str], as_int: bool = True) -> Optional[List[Union[int, float]]]:
    """
    Разбирает либо CSV ('1,2,3'), либо 'start:end:step'. Возвращает None, если spec пуст.
    """
    if not spec:
        return None
    s = str(spec).strip()
    if ":" in s:
        vals = _parse_range_spec(s)
    else:
        vals = [float(x.strip()) for x in s.split(",") if x.strip()]

    if as_int:
        return [int(round(v)) for v in vals]
    return vals


def _span_string(pair_span: str) -> str:
    """
    Оставляем '1m:5000' как есть (функции проекта сами парсят span).
    """
    return str(pair_span).strip()


def _json_dumps(obj: Any) -> str:
    def _default(o: Any):
        if isinstance(o, Path):
            return str(o)
        try:
            import pandas as pd  # noqa
            import numpy as np   # noqa
            # лёгкая попытка конвертации популярных объектов
            if hasattr(o, "to_dict"):
                return o.to_dict()  # type: ignore
        except Exception:
            pass
        return repr(o)
    return json.dumps(obj, ensure_ascii=False, indent=2, default=_default)


def _call_with_filtered_kwargs(func, **kwargs):
    sig = inspect.signature(func)
    filt = {k: v for k, v in kwargs.items() if k in sig.parameters}
    return func(**filt)


# -----------------------------
# Построение парсера
# -----------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tradinng-bot",
        description="Trading research & live-trade CLI",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command")

    # --- backtest (минимальный passthrough) ---
    p_bt = subparsers.add_parser("backtest", help="Single run backtest")
    p_bt.add_argument("--exmo-pair", required=True, type=str)
    p_bt.add_argument("--exmo-candles", required=True, type=str, help="e.g. 1m:5000")
    p_bt.add_argument("--resample", default="5m", type=str)
    p_bt.add_argument("--fast", type=int, required=True)
    p_bt.add_argument("--slow", type=int, required=True)
    p_bt.add_argument("--hysteresis-bps", dest="hysteresis_bps", type=int, default=0)
    p_bt.add_argument("--cooldown-bars", dest="cooldown_bars", type=int, default=0)
    p_bt.add_argument("--fee-bps", dest="fee_bps", type=int, default=10)
    p_bt.add_argument("--slip-bps", dest="slip_bps", type=int, default=2)
    p_bt.add_argument("--qty-eur", dest="qty_eur", type=float, default=100.0)
    p_bt.add_argument("--max-daily-loss-bps", dest="max_daily_loss_bps", type=int, default=0)
    p_bt.add_argument("--json-metrics", dest="json_metrics", type=str, default=None)
    p_bt.set_defaults(func=cmd_backtest)

    # --- sweep (grid) ---
    p_sw = subparsers.add_parser("sweep", help="Parameter sweep")
    p_sw.add_argument("--exmo-pair", required=True, type=str)
    p_sw.add_argument("--exmo-candles", required=True, type=str)
    p_sw.add_argument("--resample", default="5m", type=str)
    p_sw.add_argument("--fast-list", type=str, required=True, help="CSV or start:end:step")
    p_sw.add_argument("--slow-list", type=str, required=True, help="CSV or start:end:step")
    p_sw.add_argument("--hyst-list", dest="hyst_list", type=str, default="0")
    p_sw.add_argument("--cooldown-list", dest="cooldown_list", type=str, default="0")
    p_sw.add_argument("--qty-list", dest="qty_list", type=str, default="100")
    p_sw.add_argument("--fee-bps", dest="fee_bps", type=int, default=10)
    p_sw.add_argument("--slip-bps", dest="slip_bps", type=int, default=2)
    p_sw.add_argument("--max-daily-loss-bps", dest="max_daily_loss_bps", type=int, default=0)
    p_sw.add_argument("--sort-by", type=str, default="calmar")
    p_sw.add_argument("--top-n", type=int, default=20)
    p_sw.add_argument("--verbose", action="store_true")
    p_sw.add_argument("--out-dir", dest="out_dir", type=str, default="data/optimize")
    p_sw.set_defaults(func=cmd_sweep)

    # --- walk-forward ---
    p_wf = subparsers.add_parser("walk-forward", help="Walk-forward validation")
    p_wf.add_argument("--exmo-pair", required=True, type=str)
    p_wf.add_argument("--exmo-candles", required=True, type=str)
    p_wf.add_argument("--resample", default="5m", type=str)
    p_wf.add_argument("--fast", type=int, required=True)
    p_wf.add_argument("--slow", type=int, required=True)
    p_wf.add_argument("--hysteresis-bps", dest="hysteresis_bps", type=int, default=0)
    p_wf.add_argument("--cooldown-bars", dest="cooldown_bars", type=int, default=0)
    p_wf.add_argument("--qty-eur", dest="qty_eur", type=float, default=100.0)
    p_wf.add_argument("--fee-bps", dest="fee_bps", type=int, default=10)
    p_wf.add_argument("--slip-bps", dest="slip_bps", type=int, default=2)
    p_wf.add_argument("--max-daily-loss-bps", dest="max_daily_loss_bps", type=int, default=0)
    p_wf.add_argument("--folds", type=int, default=4)
    p_wf.add_argument("--min-train-bars", dest="min_train_bars", type=int, default=150)
    p_wf.add_argument("--min-valid-bars", dest="min_valid_bars", type=int, default=100)
    p_wf.add_argument("--out-dir", dest="out_dir", type=str, default="data/optimize")
    p_wf.set_defaults(func=cmd_walkforward)

    # --- robustness (rank stability) ---
    p_rb = subparsers.add_parser("robustness", help="Compute stability ranking from sweep CSV")
    p_rb.add_argument("--sweep-csv", required=True, type=str)
    p_rb.add_argument("--min-trades", type=int, default=0)
    p_rb.add_argument("--metric", type=str, default="calmar")
    p_rb.add_argument("--d-fast", dest="d_fast", type=int, default=2)
    p_rb.add_argument("--d-slow", dest="d_slow", type=int, default=5)
    p_rb.add_argument("--d-hyst", dest="d_hyst", type=int, default=5)
    p_rb.add_argument("--d-cd", dest="d_cd", type=int, default=2)
    p_rb.add_argument("--ranked-csv", dest="ranked_csv", type=str, default=None)
    p_rb.set_defaults(func=cmd_robustness)

    # --- optimize (комбайн) ---
    p_opt = subparsers.add_parser("optimize", help="Full pipeline: sweep -> rank -> WF -> (final backtest)")
    p_opt.add_argument("--exmo-pair", required=True, type=str)
    p_opt.add_argument("--exmo-candles", required=True, type=str, help="e.g. 1m:5000")
    p_opt.add_argument("--resample", default="5m", type=str)

    p_opt.add_argument("--fast-list", type=str, required=True, help="CSV or start:end:step")
    p_opt.add_argument("--slow-list", type=str, required=True, help="CSV or start:end:step")
    p_opt.add_argument("--hyst-list", dest="hyst_list", type=str, default="0")
    p_opt.add_argument("--cooldown-list", dest="cooldown_list", type=str, default="0")
    p_opt.add_argument("--qty-list", dest="qty_list", type=str, default="100")

    p_opt.add_argument("--fee-bps", dest="fee_bps", type=int, default=10)
    p_opt.add_argument("--slip-bps", dest="slip_bps", type=int, default=2)
    p_opt.add_argument("--max-daily-loss-bps", dest="max_daily_loss_bps", type=int, default=0)

    p_opt.add_argument("--metric", type=str, default="calmar")
    p_opt.add_argument("--min-trades", dest="min_trades", type=int, default=0)
    p_opt.add_argument("--d-fast", dest="d_fast", type=int, default=2)
    p_opt.add_argument("--d-slow", dest="d_slow", type=int, default=5)
    p_opt.add_argument("--d-hyst", dest="d_hyst", type=int, default=5)
    p_opt.add_argument("--d-cd", dest="d_cd", type=int, default=2)

    p_opt.add_argument("--wf-top-n", dest="wf_top_n", type=int, default=10)
    p_opt.add_argument("--folds", type=int, default=4)
    p_opt.add_argument("--min-train-bars", dest="min_train_bars", type=int, default=150)
    p_opt.add_argument("--min-valid-bars", dest="min_valid_bars", type=int, default=100)

    # WF фильтры (всё опционально — будем передавать только если функция их принимает)
    p_opt.add_argument("--wf-min-pf", dest="wf_min_pf", type=float, default=None)
    p_opt.add_argument("--wf-min-return", dest="wf_min_return", type=float, default=None)
    p_opt.add_argument("--wf-max-dd", dest="wf_max_dd", type=float, default=None)
    p_opt.add_argument("--wf-min-winrate", dest="wf_min_winrate", type=float, default=None)
    p_opt.add_argument("--wf-min-sharpe", dest="wf_min_sharpe", type=float, default=None)
    p_opt.add_argument("--wf-min-cagr", dest="wf_min_cagr", type=float, default=None)
    p_opt.add_argument("--wf-min-calmar", dest="wf_min_calmar", type=float, default=None)
    p_opt.add_argument("--wf-min-folds", dest="wf_min_folds", type=int, default=None)
    p_opt.add_argument("--wf-min-trades", dest="wf_min_trades", type=int, default=None)
    p_opt.add_argument("--wf-max-exposure", dest="wf_max_exposure", type=float, default=None)

    p_opt.add_argument("--rank-by",
                       choices=["oos_profit_factor_mean", "oos_total_return_pct_mean",
                                "oos_calmar_mean", "oos_sharpe_mean", "oos_cagr_pct_mean"],
                       default="oos_total_return_pct_mean")

    p_opt.add_argument("--final-backtest", dest="final_backtest", action="store_true", default=False)
    p_opt.add_argument("--report-html", dest="report_html", type=str, default=None)
    p_opt.add_argument("--out-dir", dest="out_dir", type=str, default="data/optimize")
    p_opt.set_defaults(func=cmd_optimize)

    # --- подключаем новую подкоманду trade-live ---
    register_trade_live(subparsers)

    return parser


# -----------------------------
# Хэндлеры команд
# -----------------------------

def cmd_backtest(args: argparse.Namespace) -> None:
    settings = load_settings()
    _setup_logging(settings)

    try:
        # ленивый импорт, чтобы не падать если команда не используется
        from src.backtest.vectorized_bt import BtConfig, run_backtest  # type: ignore
    except Exception as e:
        _fatal(f"Модуль backtest недоступен: {e}")

    bt_kwargs = dict(
        pair=str(args.exmo_pair),
        span=_span_string(args.exmo_candles),
        resample=_normalize_resample(args.resample),
        fast=int(args.fast),
        slow=int(args.slow),
        hysteresis_bps=int(args.hysteresis_bps),
        cooldown_bars=int(args.cooldown_bars),
        fee_bps=int(args.fee_bps),
        slip_bps=int(args.slip_bps),
        qty_eur=float(args.qty_eur),
        max_daily_loss_bps=int(args.max_daily_loss_bps),
    )

    # Создаём BtConfig только из тех полей, что он принимает
    bt = _instantiate_filtered(BtConfig, **bt_kwargs)

    # Запускаем бэктест
    result = _call_with_filtered_kwargs(run_backtest, cfg=bt)

    # Аккуратно печатаем JSON метрик
    print(_json_dumps(result))

    # при необходимости — сохранить json метрик
    if getattr(args, "json_metrics", None):
        p = Path(args.json_metrics)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_json_dumps(result), encoding="utf-8")


def cmd_sweep(args: argparse.Namespace) -> None:
    settings = load_settings()
    _setup_logging(settings)

    try:
        from src.backtest.sweep import run_sweep, SweepCfg  # type: ignore
    except Exception as e:
        _fatal(f"Модуль sweep недоступен: {e}")

    cfg_kwargs = dict(
        pair=str(args.exmo_pair),
        span=_span_string(args.exmo_candles),
        resample=_normalize_resample(args.resample),
        fast_list=_parse_num_list(args.fast_list, as_int=True),
        slow_list=_parse_num_list(args.slow_list, as_int=True),
        hyst_list=_parse_num_list(args.hyst_list, as_int=True),
        cooldown_list=_parse_num_list(args.cooldown_list, as_int=True),
        qty_list=_parse_num_list(args.qty_list, as_int=False),
        fee_bps=int(args.fee_bps),
        slip_bps=int(args.slip_bps),
        max_daily_loss_bps=int(args.max_daily_loss_bps),
        sort_by=str(args.sort_by or "calmar"),
        top_n=int(args.top_n or 20),
        verbose=bool(args.verbose),
        out_dir=Path(args.out_dir),
    )

    scfg = _instantiate_filtered(SweepCfg, **cfg_kwargs)
    out_csv = _call_with_filtered_kwargs(run_sweep, cfg=scfg)
    print(_json_dumps({"sweep_csv": str(out_csv)}))


def cmd_walkforward(args: argparse.Namespace) -> None:
    settings = load_settings()
    _setup_logging(settings)

    try:
        from src.backtest.walkforward import WFConfig, run_walkforward  # type: ignore
    except Exception as e:
        _fatal(f"Модуль walk-forward недоступен: {e}")

    cfg_kwargs = dict(
        pair=str(args.exmo_pair),
        span=_span_string(args.exmo_candles),
        resample=_normalize_resample(args.resample),
        fast=int(args.fast),
        slow=int(args.slow),
        hysteresis_bps=int(args.hysteresis_bps),
        cooldown_bars=int(args.cooldown_bars),
        qty_eur=float(args.qty_eur),
        fee_bps=int(args.fee_bps),
        slip_bps=int(args.slip_bps),
        max_daily_loss_bps=int(args.max_daily_loss_bps),
        folds=int(args.folds),
        min_train_bars=int(args.min_train_bars),
        min_valid_bars=int(args.min_valid_bars),
        out_dir=Path(args.out_dir),
    )

    wfc = _instantiate_filtered(WFConfig, **cfg_kwargs)
    out_csv = _call_with_filtered_kwargs(run_walkforward, cfg=wfc)
    print(_json_dumps({"wf_csv": str(out_csv)}))


def cmd_robustness(args: argparse.Namespace) -> None:
    settings = load_settings()
    _setup_logging(settings)

    try:
        from src.backtest.robustness import compute_stability  # type: ignore
    except Exception as e:
        _fatal(f"Модуль robustness недоступен: {e}")

    ranked_csv = _call_with_filtered_kwargs(
        compute_stability,
        csv_path=Path(args.sweep_csv),
        min_trades=int(args.min_trades),
        metric=str(args.metric or "calmar"),
        d_fast=int(args.d_fast),
        d_slow=int(args.d_slow),
        d_hyst=int(args.d_hyst),
        d_cd=int(args.d_cd),
        out_csv=(Path(args.ranked_csv) if args.ranked_csv else None),
    )
    print(_json_dumps({"ranked_csv": str(ranked_csv)}))


def cmd_optimize(args: argparse.Namespace) -> None:
    settings = load_settings()
    _setup_logging(settings)

    try:
        from src.backtest.optimize import run_optimize  # type: ignore
    except Exception as e:
        _fatal(f"Модуль optimize недоступен: {e}")

    inp_kwargs = dict(
        pair=str(args.exmo_pair),
        span=_span_string(args.exmo_candles),
        resample=_normalize_resample(args.resample),

        fast_list=_parse_num_list(args.fast_list, as_int=True),
        slow_list=_parse_num_list(args.slow_list, as_int=True),
        hyst_list=_parse_num_list(args.hyst_list, as_int=True),
        cooldown_list=_parse_num_list(args.cooldown_list, as_int=True),
        qty_list=_parse_num_list(args.qty_list, as_int=False),

        fee_bps=int(args.fee_bps),
        slip_bps=int(args.slip_bps),
        max_daily_loss_bps=int(args.max_daily_loss_bps),

        metric=str(args.metric or "calmar"),
        min_trades=int(args.min_trades),
        d_fast=int(args.d_fast),
        d_slow=int(args.d_slow),
        d_hyst=int(args.d_hyst),
        d_cd=int(args.d_cd),

        wf_top_n=int(args.wf_top_n),
        folds=int(args.folds),
        min_train_bars=int(args.min_train_bars),
        min_valid_bars=int(args.min_valid_bars),

        wf_min_pf=args.wf_min_pf,
        wf_min_return=args.wf_min_return,
        wf_max_dd=args.wf_max_dd,
        wf_min_winrate=args.wf_min_winrate,
        wf_min_sharpe=args.wf_min_sharpe,
        wf_min_cagr=args.wf_min_cagr,
        wf_min_calmar=args.wf_min_calmar,
        wf_min_folds=args.wf_min_folds,
        wf_min_trades=args.wf_min_trades,
        wf_max_exposure=args.wf_max_exposure,

        rank_by=str(args.rank_by),
        final_backtest=bool(args.final_backtest),

        out_dir=Path(args.out_dir),
        report_html=(Path(args.report_html) if args.report_html else None),
    )

    # Фильтруем по сигнатуре run_optimize
    result = _call_with_filtered_kwargs(run_optimize, **inp_kwargs)
    print(_json_dumps(result))


# -----------------------------
# Вспомогательные штуки
# -----------------------------

def _instantiate_filtered(cls, **kwargs):
    sig = inspect.signature(cls)
    filt = {k: v for k, v in kwargs.items() if k in sig.parameters}
    return cls(**filt)


def _setup_logging(settings) -> None:
    logging.basicConfig(
        level=settings.log_level_int,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Безопасность: не печатаем ключи
    if settings.mask_api_keys_in_logs:
        for k in ("EXMO_API_KEY", "EXMO_API_SECRET"):
            if k in os.environ:
                os.environ[k] = _mask(os.environ[k])


def _mask(s: str, keep_last: int = 0) -> str:
    s = str(s or "")
    if not s:
        return ""
    if keep_last <= 0:
        return "*" * min(6, len(s))
    n = max(0, len(s) - keep_last)
    return "*" * n + s[-keep_last:]


def _fatal(msg: str) -> None:
    print(_json_dumps({"error": msg}), file=sys.stderr)
    sys.exit(2)


# -----------------------------
# Точка входа
# -----------------------------

def main() -> None:
    parser = build_parser()
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(0)
    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(1)
    try:
        args.func(args)
    except SystemExit:
        raise
    except Exception as e:
        _fatal(f"Unhandled error: {e}")


if __name__ == "__main__":
    import os
    main()
