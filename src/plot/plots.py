# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Optional, Tuple
import os
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import Rectangle
from datetime import timezone


def plot_ohlc_with_volume(
    df: pd.DataFrame,
    out_path: str,
    title: str,
    sma_overlay: Optional[Tuple[int, int]] = None,
    trades_df: Optional[pd.DataFrame] = None,
) -> None:
    if df.empty or not out_path:
        return
    fig = plt.figure(figsize=(20, 6))
    gs = fig.add_gridspec(2, 1, height_ratios=[4, 1], hspace=0.05)
    ax = fig.add_subplot(gs[0, 0])
    axv = fig.add_subplot(gs[1, 0], sharex=ax)
    ax.set_title(title, fontsize=28, pad=12)

    times = mdates.date2num(pd.to_datetime(df["time"], utc=True))
    for i in range(len(df)):
        t = times[i]
        o,h,l,c,v = df.iloc[i][["open","high","low","close","volume"]]
        color = "green" if c >= o else "red"
        ax.vlines(t, l, h, color=color, linewidth=1)
        ax.add_patch(Rectangle((t - 0.0015, min(o, c)), 0.003, max(abs(c - o), 0.0002),
                               edgecolor=color, facecolor="white", linewidth=1))
        axv.bar(t, v, width=0.003, align="center", edgecolor="none", alpha=0.6, color="green")

    if sma_overlay:
        f, s = sma_overlay
        sma_f = df["close"].rolling(int(f), min_periods=int(f)).mean()
        sma_s = df["close"].rolling(int(s), min_periods=int(s)).mean()
        ax.plot(df["time"], sma_f, linewidth=1.4, label=f"SMA{f}")
        ax.plot(df["time"], sma_s, linewidth=1.4, label=f"SMA{s}")
        ax.legend(loc="upper right")

    if trades_df is not None and not trades_df.empty:
        tdf = trades_df.copy()
        tdf["time"] = pd.to_datetime(tdf["time"], utc=True)
        buys = tdf[tdf["side"] == "buy"]
        sells = tdf[tdf["side"] == "sell"]
        if not buys.empty:  ax.scatter(buys["time"], buys["price"], marker="^", s=64, label="BUY", zorder=5)
        if not sells.empty: ax.scatter(sells["time"], sells["price"], marker="v", s=64, label="SELL", zorder=5)
        ax.legend(loc="upper left")

    ax.grid(True, linestyle=":", alpha=0.4)
    ax.set_ylabel("price")
    axv.set_ylabel("vol")
    axv.grid(True, linestyle=":", alpha=0.4)
    axv.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M\n%Y-%b-%d", tz=timezone.utc))
    plt.setp(ax.get_xticklabels(), visible=False)
    fig.autofmt_xdate()
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    plt.savefig(out_path, bbox_inches="tight", dpi=150)
    plt.close(fig)


def plot_equity(equity_df: pd.DataFrame, out_path: str, title: str = "Backtest Equity Curve (EUR)"):
    if equity_df.empty or not out_path:
        return
    fig = plt.figure(figsize=(20, 5))
    ax = fig.add_subplot(111)
    ax.plot(equity_df["time"], equity_df["equity"])
    ax.grid(True, linestyle=":", alpha=0.4)
    ax.set_title(title, fontsize=22, pad=10)
    ax.set_ylabel("equity")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M\n%Y-%b-%d", tz=timezone.utc))
    fig.autofmt_xdate()
    plt.savefig(out_path, bbox_inches="tight", dpi=150)
    plt.close(fig)


def plot_sma_heatmap(grid_df: pd.DataFrame, metric: str, out_png: str, title: str | None = None) -> None:
    if grid_df.empty or not out_png:
        return
    import matplotlib.pyplot as plt
    pivot = grid_df.pivot(index="slow", columns="fast", values=metric)
    fig = plt.figure(figsize=(10, 8))
    ax = fig.add_subplot(111)
    im = ax.imshow(pivot.values, aspect="auto", origin="lower")
    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels(pivot.columns)
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels(pivot.index)
    ax.set_xlabel("fast"); ax.set_ylabel("slow")
    ax.set_title(title or f"SMA grid heatmap ({metric})")
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    plt.savefig(out_png, bbox_inches="tight", dpi=150)
    plt.close(fig)
