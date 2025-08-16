# src/tools/backtest_cli.py
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import List, Dict, Any, Tuple, Optional

from src.infrastructure.exchange.exmo_api import ExmoApi, ExmoCredentials
from src.config.settings import get_settings


# ─────────────────────────────────────────────────────────────────────────────
# Утилиты времени / TF
# ─────────────────────────────────────────────────────────────────────────────
def parse_tf_minutes(tf: str) -> int:
    tf = tf.strip().lower()
    if tf.endswith("m"):
        return int(tf[:-1])
    if tf.endswith("h"):
        return int(tf[:-1]) * 60
    if tf.endswith("d"):
        return int(tf[:-1]) * 60 * 24
    raise ValueError(f"Unsupported timeframe: {tf!r}")


def _downscale_limits(start: int) -> List[int]:
    chain = [start, 1000, 800, 600, 500, 400, 300, 250, 200, 180, 150, 120, 100, 80, 60, 50, 40, 30, 20, 10]
    out: List[int] = []
    for x in chain:
        if x > 0 and x not in out:
            out.append(x)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Ресэмплинг 1m → любой TF (без pandas)
# ─────────────────────────────────────────────────────────────────────────────
def resample_ohlcv_1m(rows_1m: List[Dict[str, Any]], tf_minutes: int) -> List[Dict[str, Any]]:
    if tf_minutes <= 1:
        return rows_1m
    if not rows_1m:
        return []

    # rows: [{'ts': 171..., 'open': '...', 'high': '...', 'low': '...', 'close': '...', 'volume': '...'}]
    out: List[Dict[str, Any]] = []
    bucket: Dict[str, Any] | None = None
    bucket_start: Optional[int] = None

    for r in sorted(rows_1m, key=lambda x: int(x["ts"])):
        ts = int(r["ts"])
        o = Decimal(str(r["open"]))
        h = Decimal(str(r["high"]))
        l = Decimal(str(r["low"]))
        c = Decimal(str(r["close"]))
        v = Decimal(str(r.get("volume", "0")))

        # старт тайм-бакета: кратный tf_minutes
        start = ts - (ts % (tf_minutes * 60))
        if bucket is None or start != bucket_start:
            # закрываем предыдущий
            if bucket is not None:
                out.append({
                    "ts": bucket_start,
                    "open": str(bucket["open"]),
                    "high": str(bucket["high"]),
                    "low": str(bucket["low"]),
                    "close": str(bucket["close"]),
                    "volume": str(bucket["volume"]),
                })
            bucket = {"open": o, "high": h, "low": l, "close": c, "volume": v}
            bucket_start = start
        else:
            # обновляем экстремумы и close/volume
            bucket["high"] = max(bucket["high"], h)
            bucket["low"] = min(bucket["low"], l)
            bucket["close"] = c
            bucket["volume"] += v

    if bucket is not None:
        out.append({
            "ts": bucket_start,
            "open": str(bucket["open"]),
            "high": str(bucket["high"]),
            "low": str(bucket["low"]),
            "close": str(bucket["close"]),
            "volume": str(bucket["volume"]),
        })
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Фетч баров из EXMO с умными фоллбэками
# ─────────────────────────────────────────────────────────────────────────────
def fetch_bars_exmo(pair: str, tf: str, limit: int, debug: bool = False) -> List[Dict[str, Any]]:
    """
    Возвращает список dict-баров формата:
      {'ts': int, 'open': str, 'high': str, 'low': str, 'close': str, 'volume': str}
    """
    s = get_settings()
    api = ExmoApi(ExmoCredentials(s.api_key, s.api_secret), allow_trading=False)

    for lim in _downscale_limits(limit):
        # 1) OHLCV (если реализовано в API)
        data = api.ohlcv(pair=pair, timeframe=tf, limit=lim)
        if debug:
            print(f"[debug] ohlcv({pair},{tf},{lim}) -> {len(data)} bars")
        if isinstance(data, list) and data:
            # может прийти list[list], нормализуем
            if data and isinstance(data[0], list):
                data = [{"ts": int(r[0]), "open": str(r[1]), "high": str(r[2]), "low": str(r[3]), "close": str(r[4]),
                         "volume": str(r[5])} for r in data]
            return data

        # 2) Kline
        data = api.kline(pair=pair, timeframe=tf, limit=lim)
        if debug:
            print(f"[debug] kline({pair},{tf},{lim}) -> {len(data)} bars")
        if isinstance(data, list) and data:
            return data  # уже в dict-виде

        # 3) Candles
        data = api.candles(pair=pair, timeframe=tf, limit=lim)
        if debug:
            print(f"[debug] candles({pair},{tf},{lim}) -> {len(data)} bars")
        if isinstance(data, list) and data:
            return data

    # 4) Фоллбэк: всегда пробуем 1m и ресэмплим
    tfm = parse_tf_minutes(tf)
    if tfm > 1:
        lim_1m = min(max(limit * tfm, 50), 3000)  # сколько минут нужно; небольшой кап
        data_1m = api.candles(pair=pair, timeframe="1m", limit=lim_1m)
        if debug:
            print(f"[debug] fallback candles({pair},1m,{lim_1m}) -> {len(data_1m)} bars")
        if isinstance(data_1m, list) and data_1m:
            agg = resample_ohlcv_1m(data_1m, tfm)
            # оставим «хвост» по лимиту
            return agg[-limit:]

    return []


# ─────────────────────────────────────────────────────────────────────────────
# Простейший SMA backtest
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class SmaCfg:
    fast: int
    slow: int
    fee_bps: Decimal
    size_quote: Decimal


def sma(values: List[Decimal], n: int) -> List[Optional[Decimal]]:
    out: List[Optional[Decimal]] = []
    s = Decimal("0")
    q: List[Decimal] = []
    for v in values:
        q.append(v)
        s += v
        if len(q) > n:
            s -= q.pop(0)
        out.append((s / n) if len(q) == n else None)
    return out


def run_backtest(bars: List[Dict[str, Any]], cfg: SmaCfg, base: str, quote: str) -> Tuple[
    Dict[str, Any], List[Dict[str, Any]], List[Tuple[int, Decimal]]]:
    if not bars:
        return {
            "trades": 0,
            "position": "0",
            "realized": "0",
            "unrealized": "0",
            "total_pnl": "0",
            "fees_quote": "0",
        }, [], []

    closes = [Decimal(str(b["close"])) for b in bars]
    ts = [int(b["ts"]) for b in bars]
    f = sma(closes, cfg.fast)
    s = sma(closes, cfg.slow)

    pos_base = Decimal("0")
    cash_quote = Decimal("0")
    fees_quote = Decimal("0")
    equity_curve: List[Tuple[int, Decimal]] = []
    trades: List[Dict[str, Any]] = []

    def fee(amount_quote: Decimal) -> Decimal:
        return (amount_quote * cfg.fee_bps) / Decimal("10000")

    for i in range(len(closes)):
        price = closes[i]
        ts_i = ts[i]
        equity_curve.append((ts_i, cash_quote + pos_base * price))
        if f[i] is None or s[i] is None:
            continue
        # сигналы
        want_long = f[i] > s[i]
        have_long = pos_base > 0

        if want_long and not have_long:
            # покупаем на size_quote
            q = (cfg.size_quote / price)
            cost = cfg.size_quote
            fee_q = fee(cost)
            cash_quote -= (cost + fee_q)
            pos_base += q
            fees_quote += fee_q
            trades.append({"ts": ts_i, "type": "buy", "price": str(price), "qty": str(q)})
        elif (not want_long) and have_long:
            # закрываем позицию
            proceeds = pos_base * price
            fee_q = fee(proceeds)
            cash_quote += (proceeds - fee_q)
            fees_quote += fee_q
            trades.append({"ts": ts_i, "type": "sell", "price": str(price), "qty": str(pos_base)})
            pos_base = Decimal("0")

    realized = cash_quote
    unrealized = pos_base * closes[-1]
    total = realized + unrealized

    summary = {
        "trades": len(trades),
        "position": str(pos_base),
        "realized": str(realized),
        "unrealized": str(unrealized),
        "total_pnl": str(total),
        "fees_quote": str(fees_quote),
    }
    return summary, trades, equity_curve


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────
def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser("backtest_cli", description="SMA backtest (EXMO/json)")

    p.add_argument("--source", choices=["exmo", "json"], required=True)
    p.add_argument("--json-path", type=str, default=None)

    p.add_argument("--pair", required=True)
    p.add_argument("--tf", required=True)
    p.add_argument("--limit", type=int, default=300)

    p.add_argument("--fast", type=int, default=8)
    p.add_argument("--slow", type=int, default=21)
    p.add_argument("--fee-bps", type=int, default=10)
    p.add_argument("--size-quote", type=str, default="100")

    p.add_argument("--debug-fetch", action="store_true")
    p.add_argument("--plot", type=str, default=None)
    p.add_argument("--save-json", type=str, default=None)
    p.add_argument("--save-trades", type=str, default=None)
    p.add_argument("--save-equity", type=str, default=None)

    return p


def main() -> None:
    args = _build_parser().parse_args()
    pair = args.pair
    base, quote = pair.split("_", 1)

    # загрузка баров
    bars: List[Dict[str, Any]] = []
    if args.source == "exmo":
        bars = fetch_bars_exmo(pair, args.tf, args.limit, debug=args.debug_fetch)
    else:
        if not args.json_path:
            raise SystemExit("Укажи --json-path для source=json")
        with open(args.json_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        # поддержка форматов из main.py (ohlcv/candles/kline)
        rows = raw.get("ohlcv") or raw.get("candles") or raw.get("kline") or []
        # нормализуем: если list[list]
        if rows and isinstance(rows[0], list):
            rows = [{"ts": int(r[0]), "open": str(r[1]), "high": str(r[2]), "low": str(r[3]), "close": str(r[4]),
                     "volume": str(r[5])} for r in rows]
        bars = rows

    if args.debug_fetch:
        print(f"[debug] fetched bars: {len(bars)}")

    if not bars:
        print("Не удалось получить OHLCV")
        return

    # сохраняем то, что загрузили
    if args.save_json:
        with open(args.save_json, "w", encoding="utf-8") as f:
            json.dump(bars, f, ensure_ascii=False, indent=2)
        print(f"→ JSON saved to: {args.save_json}")

    cfg = SmaCfg(
        fast=args.fast,
        slow=args.slow,
        fee_bps=Decimal(args.fee_bps) if isinstance(args.fee_bps, (int, float)) else Decimal(str(args.fee_bps)),
        size_quote=Decimal(str(args.size_quote)),
    )

    summary, trades, equity = run_backtest(bars, cfg, base, quote)

    print(f"SMA backtest {pair} {args.tf}  bars={len(bars)}")
    print(f"  trades: {summary['trades']}")
    print(f"  position: {summary['position']} {base}")
    print(f"  realized: {summary['realized']}")
    print(f"  unrealized: {summary['unrealized']}")
    print(f"  total PnL: {summary['total_pnl']}")
    print(f"  fees (quote): {summary['fees_quote']}")

    # сохранения
    if args.save_trades:
        with open(args.save_trades, "w", encoding="utf-8") as f:
            f.write("ts,type,price,qty\n")
            for t in trades:
                f.write(f"{t['ts']},{t['type']},{t['price']},{t['qty']}\n")
        print(f"→ Trades saved to: {args.save_trades}")

    if args.save_equity:
        with open(args.save_equity, "w", encoding="utf-8") as f:
            f.write("ts,equity\n")
            for ts_i, eq in equity:
                f.write(f"{ts_i},{eq}\n")
        print(f"→ Equity saved to: {args.save_equity}")

    # график (простая линия equity)
    if args.plot:
        try:
            import matplotlib.pyplot as plt
            xs = [x for x, _ in equity]
            ys = [float(str(y)) for _, y in equity]
            plt.figure(figsize=(10, 4))
            plt.plot(xs, ys)
            plt.title(f"Equity {pair} {args.tf}")
            plt.xlabel("ts")
            plt.ylabel("equity")
            plt.tight_layout()
            plt.savefig(args.plot, dpi=120)
            plt.close()
            print(f"→ Chart saved to: {args.plot}")
        except Exception as e:
            print(f"⚠️  Plot error: {e!r}")


if __name__ == "__main__":
    main()
