# src/backtest/optimize.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Dict, Any

import json
import pandas as pd

from .sweep import SweepCfg, run_sweep, parse_int_list, parse_float_list, _resample_ohlc, _fetch_exmo_candles_cached, _simulate_on_df, _normalize_resample_rule
from .robustness import compute_stability
from .walkforward import WFConfig, run_walkforward


@dataclass
class OptimizeInput:
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
    metric: str
    min_trades: int
    d_fast: int
    d_slow: int
    d_hyst: int
    d_cd: int
    wf_top_n: int
    folds: int
    min_train_bars: int
    min_valid_bars: int
    wf_min_pf: float = 0.0
    wf_min_return: float = -1e9
    wf_max_dd: float = 1e9
    wf_min_winrate: float = 0.0
    wf_min_sharpe: float = -1e9
    wf_min_cagr: float = -1e9
    wf_min_calmar: float = -1e9
    wf_min_folds: int = 1
    wf_min_trades: int = 0
    wf_max_exposure: float = 100.0
    rank_by: str = "oos_total_return_pct_mean"
    final_backtest: bool = False


def run_optimize(
    *,
    pair: str, span: str, resample: Optional[str],
    fast_list: List[int], slow_list: List[int], hyst_list: List[int], cooldown_list: List[int], qty_list: List[float],
    fee_bps: int, slip_bps: int, max_daily_loss_bps: int,
    metric: str, min_trades: int, d_fast: int, d_slow: int, d_hyst: int, d_cd: int,
    wf_top_n: int, folds: int, min_train_bars: int, min_valid_bars: int,
    wf_min_pf: float = 0.0, wf_min_return: float = -1e9, wf_max_dd: float = 1e9,
    wf_min_winrate: float = 0.0, wf_min_sharpe: float = -1e9, wf_min_cagr: float = -1e9, wf_min_calmar: float = -1e9,
    wf_min_folds: int = 1, wf_min_trades: int = 0, wf_max_exposure: float = 100.0,
    rank_by: str = "oos_total_return_pct_mean", final_backtest: bool = False,
    out_dir: Path | str = Path("data/optimize"), report_html: Optional[Path] = None,
) -> Dict[str, Any]:
    out_root = Path(out_dir); out_root.mkdir(parents=True, exist_ok=True)

    # 1) SWEEP (устойчивый fetch внутри)
    sweep_csv = run_sweep(SweepCfg(
        pair=pair, span=span, resample=resample,
        fast_list=fast_list, slow_list=slow_list, hyst_list=hyst_list,
        cooldown_list=cooldown_list, qty_list=qty_list,
        fee_bps=fee_bps, slip_bps=slip_bps, max_daily_loss_bps=max_daily_loss_bps,
        out_dir=out_root,
    ))
    sweep_csv_path = Path(sweep_csv)

    # 2) ROBUSTNESS
    ranked = compute_stability(
        csv_path=sweep_csv_path, metric=metric, min_trades=min_trades,
        d_fast=d_fast, d_slow=d_slow, d_hyst=d_hyst, d_cd=d_cd,
        top_n=max(1, wf_top_n),
    )
    ranked_csv = out_root / f"ranked_{pair}_{_normalize_resample_rule(resample) or 'raw'}_{pd.Timestamp.utcnow().strftime('%Y%m%d-%H%M%S')}.csv"
    ranked.to_csv(ranked_csv, index=False)

    if ranked.empty or (list(ranked.columns) == ["error"]):
        result = {
            "sweep_csv": str(sweep_csv_path),
            "ranked_csv": str(ranked_csv),
            "wf_csv": None,
            "report_html": str(report_html) if report_html else None,
            "message": "Ranked table is empty or contains only errors; stopping before WF.",
        }
        # минимальный HTML-отчёт с примерами ошибок
        if report_html:
            try:
                df = pd.read_csv(sweep_csv_path)
                err_sample = df.loc[df["error"].astype(str).str.strip() != "", "error"].head(10).tolist() if "error" in df.columns else []
            except Exception:
                err_sample = []
            html = []
            html.append("<html><head><meta charset='utf-8'><title>Optimize Report</title></head><body>")
            html.append("<h1>Optimize Report</h1>")
            html.append(f"<p><b>Pair:</b> {pair} &nbsp; <b>Resample:</b> {_normalize_resample_rule(resample) or 'raw'}</p>")
            html.append(f"<p><b>Sweep CSV:</b> {sweep_csv_path}</p>")
            html.append(f"<p><b>Ranked CSV:</b> {ranked_csv}</p>")
            html.append("<h2>Stopped before WF</h2>")
            html.append("<p>Ranked table is empty or contains only errors.</p>")
            if err_sample:
                html.append("<h3>Error samples from sweep:</h3><ul>")
                for e in err_sample:
                    html.append(f"<li>{e}</li>")
                html.append("</ul>")
            html.append("</body></html>")
            Path(report_html).parent.mkdir(parents=True, exist_ok=True)
            Path(report_html).write_text("\n".join(html), encoding="utf-8")
        return result

    # 3) WF по top-N
    top = ranked.head(wf_top_n).copy()
    wf_rows = []
    for _, row in top.iterrows():
        cfg = WFConfig(
            pair=pair, span=span, resample=resample,
            fast=int(row.get("fast")), slow=int(row.get("slow")),
            hysteresis_bps=int(row.get("hysteresis_bps")), cooldown_bars=int(row.get("cooldown_bars")),
            fee_bps=fee_bps, slip_bps=slip_bps, qty_eur=float(row.get("qty_eur", 100.0)),
            max_daily_loss_bps=max_daily_loss_bps,
            folds=folds, min_train_bars=min_train_bars, min_valid_bars=min_valid_bars,
        )
        df_folds, agg = run_walkforward(cfg)

        passed = True
        n_folds = len(df_folds)
        if n_folds < wf_min_folds: passed = False
        if df_folds["profit_factor"].replace([float("inf"), -float("inf")], pd.NA).mean() < wf_min_pf: passed = False
        if df_folds["total_return_pct"].mean() < 100.0 * wf_min_return: passed = False
        if df_folds["max_drawdown_pct"].mean() < -100.0 * wf_max_dd: passed = False
        if df_folds["winrate_pct"].mean() < 100.0 * wf_min_winrate: passed = False
        if df_folds["sharpe"].mean() < wf_min_sharpe: passed = False
        if df_folds["cagr_pct"].mean() < 100.0 * wf_min_cagr: passed = False
        if df_folds["calmar"].replace([float("inf"), -float("inf")], pd.NA).mean() < 100.0 * wf_min_calmar: passed = False
        if "exposure_pct" in df_folds.columns and df_folds["exposure_pct"].mean() > wf_max_exposure: passed = False

        wf_rows.append({
            "fast": cfg.fast, "slow": cfg.slow, "hysteresis_bps": cfg.hysteresis_bps,
            "cooldown_bars": cfg.cooldown_bars, "qty_eur": cfg.qty_eur,
            **agg, "wf_pass": bool(passed),
        })

    wf_df = pd.DataFrame(wf_rows)
    wf_csv = out_root / f"wf_{pair}_{_normalize_resample_rule(resample) or 'raw'}_{pd.Timestamp.utcnow().strftime('%Y%m%d-%H%M%S')}.csv"
    wf_df.to_csv(wf_csv, index=False)

    # 4) выбор лучшего
    df_sel = wf_df[wf_df["wf_pass"]] if (not wf_df.empty and wf_df["wf_pass"].any()) else wf_df
    best = None if df_sel.empty else df_sel.sort_values(by=rank_by, ascending=False).iloc[0].to_dict()

    # 5) финальный бэктест
    final_metrics: Optional[Dict[str, Any]] = None
    if final_backtest and best is not None:
        raw = _fetch_exmo_candles_cached(pair, span, retries=3).sort_index()
        ohlc = _resample_ohlc(raw, resample)
        met, trades, equity = _simulate_on_df(
            ohlc,
            fast=int(best["fast"]), slow=int(best["slow"]),
            hysteresis_bps=int(best["hysteresis_bps"]), cooldown_bars=int(best["cooldown_bars"]),
            fee_bps=fee_bps, slip_bps=slip_bps, qty_eur=float(best["qty_eur"]),
            resample_rule=resample, pair_name=pair,
        )
        base = f"final_{pair}_{_normalize_resample_rule(resample) or 'raw'}_{int(best['fast'])}-{int(best['slow'])}_h{int(best['hysteresis_bps'])}_cd{int(best['cooldown_bars'])}_q{int(best['qty_eur'])}"
        trades_csv = Path(out_dir) / f"{base}_trades.csv"
        equity_csv = Path(out_dir) / f"{base}_equity.csv"
        trades.to_csv(trades_csv, index=False)
        equity.to_csv(equity_csv, index=True)
        final_metrics = {"metrics": met, "trades_csv": str(trades_csv), "equity_csv": str(equity_csv)}

    # 6) отчёт HTML (минимальный)
    if report_html:
        html = []
        html.append("<html><head><meta charset='utf-8'><title>Optimize Report</title></head><body>")
        html.append("<h1>Optimize Report</h1>")
        html.append(f"<p><b>Pair:</b> {pair} &nbsp; <b>Resample:</b> {_normalize_resample_rule(resample) or 'raw'}</p>")
        html.append(f"<p><b>Sweep CSV:</b> {sweep_csv_path}</p>")
        html.append(f"<p><b>Ranked CSV:</b> {ranked_csv}</p>")
        html.append(f"<p><b>WF CSV:</b> {wf_csv}</p>")
        if best:
            html.append("<h2>Best config (after WF filters)</h2>")
            html.append("<pre>" + json.dumps(best, ensure_ascii=False, indent=2) + "</pre>")
        if final_metrics:
            html.append("<h2>Final backtest</h2>")
            html.append("<pre>" + json.dumps(final_metrics["metrics"], ensure_ascii=False, indent=2) + "</pre>")
            html.append(f"<p>Trades: {final_metrics['trades_csv']}<br>Equity: {final_metrics['equity_csv']}</p>")
        html.append("</body></html>")
        Path(report_html).parent.mkdir(parents=True, exist_ok=True)
        Path(report_html).write_text("\n".join(html), encoding="utf-8")

    return {
        "sweep_csv": str(sweep_csv_path),
        "ranked_csv": str(ranked_csv),
        "wf_csv": str(wf_csv),
        "report_html": str(report_html) if report_html else None,
        "best": best,
        "final_metrics": final_metrics,
    }
