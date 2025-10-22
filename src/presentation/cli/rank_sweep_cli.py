#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import math
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd


def _to_builtin(obj):
    """Convert numpy/pandas scalars to python builtins for JSON."""
    if isinstance(obj, (np.generic,)):
        return obj.item()
    if isinstance(obj, (pd.Timestamp,)):
        return obj.isoformat()
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")


def parse_args(argv: Optional[List[str]] = None):
    p = argparse.ArgumentParser("rank_sweep_cli.py")
    p.add_argument("--in", dest="inp", required=True, help="CSV с результатами sweep")
    p.add_argument("--objective", default="net_pnl", choices=["net_pnl", "avg_pnl", "win_rate"])
    p.add_argument("--top-k", type=int, default=50)
    # порог по сделкам (ручной/авто)
    p.add_argument("--min-trades", type=int, default=None)
    p.add_argument("--auto-min-trades", action="store_true")
    # робаст-фильтр
    p.add_argument("--neighbor-radius", type=float, default=1.0)
    p.add_argument("--robust-pos-share", type=float, default=0.6)
    p.add_argument("--robust-min-median", type=float, default=0.0)
    p.add_argument("--robust-min-trades", type=int, default=None,
                   help="Если не задан — возьмём выбранный min_trades")
    # артефакты
    p.add_argument("--out-top", default="reports/top_ranked.csv")
    p.add_argument("--out-robust", default="reports/top_robust.csv")
    p.add_argument("--emit-champion-json", default=None, help="reports/champion.json")
    p.add_argument("--emit-champion-cli", default=None, help="reports/champion_cli.sh")
    return p.parse_args(argv)


NUMERIC_FOR_NEIGHBORHOOD = [
    "adx_off", "stop_atr", "take_atr", "trail_atr",
    "cooldown_bars", "min_hold_bars", "breakeven_rr", "trail_activate_rr",
    "avg_pnl",
]


def auto_pick_min_trades(df: pd.DataFrame, top_k: int) -> int:
    print("[rank] Подбираю авто-порог по сделкам...")
    candidates = [3, 5, 10, 20, 30, 50]
    for mt in candidates:
        left = (df["trades"] >= mt).sum()
        print(f"  · Пробую min_trades={mt}: остаётся {left} строк.")
        if left >= max(top_k, math.ceil(0.2 * len(df))):
            print(f"[rank] Выбран min_trades={mt}")
            return mt
    mt = candidates[0]
    print(f"[rank] Выбран min_trades={mt} (fallback)")
    return mt


def build_champion(row: pd.Series) -> dict:
    cfg_keys = [
        "resample", "ema_fast", "ema_slow", "adx_len",
        "adx_on", "adx_off", "require_di", "htf_tf",
        "stop_atr", "take_atr", "trail_atr",
        "cooldown_bars", "min_hold_bars",
        "breakeven_rr", "trail_activate_rr",
        "fee_bps", "slip_bps", "qty",
    ]
    met_keys = ["trades", "win_rate", "net_pnl", "avg_pnl"]

    cfg = {k: row[k] for k in cfg_keys if k in row}
    met = {k: row[k] for k in met_keys if k in row}

    cfg = {k: _to_builtin(v) if isinstance(v, np.generic) else v for k, v in cfg.items()}
    met = {k: _to_builtin(v) if isinstance(v, np.generic) else v for k, v in met.items()}

    return {"config": cfg, "metrics": met}


def main(argv: Optional[List[str]] = None):
    args = parse_args(argv)

    df = pd.read_csv(args.inp)
    print(f"[rank] Загружено строк: {len(df)}. Колонки: {list(df.columns)}")

    if "error" in df.columns:
        df = df[df["error"].isna()]

    if args.objective not in df.columns:
        raise SystemExit(f"[rank] Нет столбца objective='{args.objective}' в CSV.")

    # min_trades
    if args.min_trades is not None:
        min_trades = args.min_trades
    elif args.auto_min_trades:
        min_trades = auto_pick_min_trades(df, args.top_k)
    else:
        min_trades = 0

    df_f = df[df["trades"] >= min_trades].copy()
    print(f"[rank] После фильтра min_trades={min_trades}: осталось {len(df_f)} из {len(df)}.")
    if len(df_f) == 0:
        print("[rank] После фильтрации по min_trades данных не осталось.")
        return 0

    df_f = df_f.sort_values(args.objective, ascending=False).reset_index(drop=True)

    # top-k
    top_k = min(args.top_k, len(df_f))
    top = df_f.head(top_k).copy()
    Path(args.out_top).parent.mkdir(parents=True, exist_ok=True)
    top.to_csv(args.out_top, index=False)
    print(f"[rank] Топ-{top_k}: отобрано {len(top)} строк (из {len(df_f)}).")
    print(f"[rank] Сохранил top-k в: {args.out_top}")

    # робаст
    robust_min_trades = min_trades if args.robust_min_trades is None else args.robust_min_trades
    use_cols = [c for c in NUMERIC_FOR_NEIGHBORHOOD if c in df_f.columns]
    print(f"[rank] Параметры для окрестности (числовые): {use_cols}")

    def is_robust(row):
        mask = pd.Series([True] * len(df_f))
        for c in use_cols:
            val = row[c]
            mask &= (df_f[c] - val).abs() <= args.neighbor_radius
        neigh = df_f.loc[mask]
        neigh = neigh[neigh["trades"] >= robust_min_trades]
        if len(neigh) == 0:
            return False
        pos_share = (neigh[args.objective] >= 0).mean()
        median_obj = neigh[args.objective].median()
        return (pos_share >= args.robust_pos_share) and (median_obj >= args.robust_min_median)

    robust_mask = top.apply(is_robust, axis=1)
    robust = top[robust_mask].copy()
    Path(args.out_robust).parent.mkdir(parents=True, exist_ok=True)
    robust.to_csv(args.out_robust, index=False)
    print(
        f"[rank] Робаст-фильтр: осталось {len(robust)} из {len(top)} "
        f"(порог pos_share>={args.robust_pos_share}, median>={args.robust_min_median}, "
        f"min_trades>={robust_min_trades}, radius={args.neighbor_radius})."
    )
    print(f"[rank] Сохранил робастные в: {args.out_robust}")

    champion_src = robust if len(robust) > 0 else top
    if len(robust) == 0:
        print("[rank] Робастный пул пуст — беру чемпиона из top-k.")
    champion_row = champion_src.iloc[0]
    champion = build_champion(champion_row)

    if args.emit_champion_json:
        Path(args.emit_champion_json).parent.mkdir(parents=True, exist_ok=True)
        with open(args.emit_champion_json, "w", encoding="utf-8") as f:
            json.dump(champion, f, ensure_ascii=False, indent=2, default=_to_builtin)
        print(f"[rank] Чемпион сохранён в JSON: {args.emit_champion_json}")

    if args.emit_champion_cli:
        cfg = champion["config"]
        parts = [
            "python -m src.presentation.cli.paper_trade_cmd",
            f"--ohlcv {{ohlcv}}",
            f"--resample {cfg['resample']}",
            f"--ema-fast {cfg['ema_fast']}",
            f"--ema-slow {cfg['ema_slow']}",
            f"--adx-len {cfg['adx_len']}",
            f"--adx-on {cfg['adx_on']}",
            f"--adx-off {cfg['adx_off']}",
            f"--require-di {cfg['require_di']}",
            f"--htf-tf {cfg['htf_tf']}",
            f"--stop-atr {cfg['stop_atr']}",
            f"--take-atr {cfg['take_atr']}",
            f"--trail-atr {cfg['trail_atr']}",
            f"--cooldown-bars {cfg['cooldown_bars']}",
            f"--min-hold-bars {cfg['min_hold_bars']}",
            f"--breakeven-rr {cfg['breakeven_rr']}",
            f"--trail-activate-rr {cfg['trail_activate_rr']}",
            f"--fee-bps {cfg['fee_bps']}",
            f"--slip-bps {cfg['slip_bps']}",
            f"--qty {cfg['qty']}",
            "--trades-out {trades_out}",
        ]
        script = "#!/usr/bin/env bash\nset -euo pipefail\n" + " \\\n  ".join(parts) + "\n"
        outp = Path(args.emit_champion_cli)
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_text(script, encoding="utf-8")
        outp.chmod(0o755)
        print(f"[rank] Чемпион CLI сохранён: {outp}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
