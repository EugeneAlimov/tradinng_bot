#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CSV helpers: печать топов из sweep/robustness/wf CSV.
"""

import sys
import csv
from pathlib import Path


def _read_csv(path):
    rows = []
    with open(path, "r", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)
    return rows


def top_from_sweep(path, limit=20):
    rows = _read_csv(path)

    def key(r):
        score = float(r.get("score") or 0)
        sharpe = float(r.get("sharpe") or 0)
        total = float(r.get("totalPnL") or 0)
        maxdd = float(r.get("maxDD") or 0)
        ddp = -abs(maxdd)
        return score + 0.8 * sharpe + 0.5 * total + 0.2 * ddp

    rows = sorted(rows, key=key, reverse=True)[:limit]
    for i, r in enumerate(rows, 1):
        print(
            f"{i:2d}. {r.get('strategy', '?'):14s} score={r.get('score')} sharpe={r.get('sharpe')} total={r.get('totalPnL')} maxDD={r.get('maxDD')} params={r.get('params')}")


def main():
    if len(sys.argv) < 3:
        print("Usage: python tools/csv_tools.py sweep <csv> [limit]")
        return
    mode = sys.argv[1]
    if mode == "sweep":
        path = sys.argv[2]
        limit = int(sys.argv[3]) if len(sys.argv) > 3 else 20
        if not Path(path).exists():
            print("CSV not found:", path)
            return
        top_from_sweep(path, limit)
    else:
        print("Unknown mode:", mode)


if __name__ == "__main__":
    main()
