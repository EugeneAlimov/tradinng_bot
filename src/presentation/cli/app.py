# src/presentation/cli/app.py
from __future__ import annotations

import argparse
import csv
import logging
import math
import os
import sys
import time
from typing import Callable, Optional, Any, Sequence, Dict, List, Tuple

from src.config.settings import get_settings
from src.infrastructure.notify.telegram import TelegramNotifier
from src.domain.risk.risk_service import RiskService, RiskCfg
from src.application.engine.integration import EngineIntegration
from src.infrastructure.exchange.exmo_api import build_exmo_from_settings

LOG = logging.getLogger("cli")


# ---------------------------
# УТИЛИТЫ
# ---------------------------

def _env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


def _configure_logging(debug_flag: bool) -> None:
    level = logging.DEBUG if (debug_flag or _env_bool("DEBUG")) else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    LOG.debug("Logging configured. Level=%s", logging.getLevelName(level))


def _parse_exmo_candles(spec: Optional[str]) -> Tuple[int, int]:
    """
    '1m:300' -> (1, 300). Поддерживаем только m (минуты).
    """
    if not spec:
        return 1, 300
    try:
        frame, cnt = spec.split(":")
        cnt = int(cnt)
        if frame.endswith("m"):
            res_min = int(frame[:-1])
            if res_min > 0 and cnt > 0:
                return res_min, cnt
    except Exception:
        pass
    return 1, 300


def _sma(series: List[float], window: int) -> List[Optional[float]]:
    if window <= 0:
        raise ValueError("window must be > 0")
    out: List[Optional[float]] = [None] * len(series)
    s = 0.0
    for i, x in enumerate(series):
        s += x
        if i >= window:
            s -= series[i - window]
        if i >= window - 1:
            out[i] = s / window
    return out


def _cross_signals(prices: List[float], fast: int, slow: int) -> List[int]:
    """
    Сигналы: +1 (buy), -1 (sell), 0 (держим). Кроссы SMA_fast/SMA_slow.
    """
    sma_f = _sma(prices, fast)
    sma_s = _sma(prices, slow)
    signals = [0] * len(prices)
    last_state = 0
    for i in range(len(prices)):
        if sma_f[i] is None or sma_s[i] is None:
            continue
        state = 1 if sma_f[i] > sma_s[i] else (-1 if sma_f[i] < sma_s[i] else 0)
        if state == 1 and last_state != 1:
            signals[i] = +1
        elif state == -1 and last_state != -1:
            signals[i] = -1
        if state != 0:
            last_state = state
    return signals


def _backtest_sma(prices: List[float], timestamps: List[int], signals: List[int],
                  fee_bps: int, slip_bps: int) -> Dict[str, Any]:
    """
    Базовый бэктест:
      - только long;
      - объём 1 базовая единица;
      - комиссия/проскальзывание в б.п. на каждую сторону.
    PnL считается в котируемой валюте (QUOTE), т.к. 1 * цена.
    """
    fee = fee_bps / 1e4
    slip = slip_bps / 1e4
    position = 0
    entry_price = 0.0
    entry_ts = 0
    trades: List[Dict[str, Any]] = []
    equity_steps: List[Tuple[int, float]] = []  # (ts, equity)
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
                "entry_ts": entry_ts,
                "entry": entry_price,
                "exit_ts": ts,
                "exit": proceeds,
                "pnl": pnl,
                "ret": (pnl / entry_price) if entry_price else 0.0,
            })
            equity += pnl
            equity_steps.append((ts, equity))
            position = 0

    # Закрытие в конце по последней цене (для консистентности отчёта)
    if position == 1 and prices:
        px = prices[-1]
        ts = timestamps[-1]
        fill = px * (1 - slip)
        proceeds = fill * (1 - fee)
        pnl = proceeds - entry_price
        trades.append({
            "entry_ts": entry_ts,
            "entry": entry_price,
            "exit_ts": ts,
            "exit": proceeds,
            "pnl": pnl,
            "ret": (pnl / entry_price) if entry_price else 0.0,
        })
        equity += pnl
        equity_steps.append((ts, equity))
        position = 0

    total_pnl = sum(t["pnl"] for t in trades)
    rets = [t["ret"] for t in trades if math.isfinite(t["ret"])]
    wins = sum(1 for t in trades if t["pnl"] > 0)
    n = len(trades)
    avg_pnl = (total_pnl / n) if n else 0.0
    win_rate = (wins / n) if n else 0.0

    # Max Drawdown по ступенчатой кривой equity
    mdd = 0.0
    peak = -1e18
    for _, eq in equity_steps:
        if eq > peak:
            peak = eq
        mdd = min(mdd, eq - peak)  # отрицательная величина

    # Sharpe по доходностям сделок (условно)
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
        "mdd": mdd,          # отрицательное число
        "sharpe": sharpe,
    }


def _save_trades_csv(path: str, trades: List[Dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["entry_ts", "entry", "exit_ts", "exit", "pnl", "ret"])
        w.writeheader()
        w.writerows(trades)


def _save_equity_csv(path: str, equity_steps: List[Tuple[int, float]]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts", "equity"])
        w.writerows(equity_steps)


# ---------------------------
# CLI
# ---------------------------

def _register_common_flags(sp: argparse._SubParsersAction) -> None:
    """
    Подкоманды + флаги. Для backtest добавлены: fast/slow/fee/slip и CSV-выгрузки.
    """
    for name in ("backtest", "sweep", "walk-forward", "robustness", "optimize", "trade-live"):
        cmd = sp.add_parser(name, help=f"{name} command")

        # Базовые флаги
        cmd.add_argument("--exmo-pair", type=str, default="DOGE_EUR")
        cmd.add_argument("--exmo-candles", type=str, default="1m:500")
        cmd.add_argument("--resample", required=False)

        # Параметры стратегии (для backtest)
        cmd.add_argument("--fast", type=int, default=6)
        cmd.add_argument("--slow", type=int, default=25)
        cmd.add_argument("--fee-bps", type=int, default=10)
        cmd.add_argument("--slip-bps", type=int, default=2)

        # CSV/репорты
        cmd.add_argument("--csv-trades", type=str, default=None, help="Путь для сохранения trades.csv")
        cmd.add_argument("--csv-equity", type=str, default=None, help="Путь для сохранения equity.csv")
        cmd.add_argument("--summary-alert", action="store_true", help="Отправить сводку в Telegram (если настроен)")

        # Stage‑A: Risk / Alerts / Reconcile
        cmd.add_argument("--max-position-pct", type=float, default=None,
                         help="Max position fraction of equity, e.g. 0.25")
        cmd.add_argument("--stop-loss-bps", type=int, default=None,
                         help="Stop loss in bps, e.g. 300 = 3%")
        cmd.add_argument("--reconcile-threshold-qty", type=float, default=None,
                         help="Reconcile threshold on position qty delta")

        cmd.add_argument("--tg-token", type=str, default=None, help="Telegram bot token")
        cmd.add_argument("--tg-chat", type=str, default=None, help="Telegram chat id")

        # Отладка
        cmd.add_argument("--debug", action="store_true")
        cmd.add_argument("--exmo-debug", action="store_true")

        cmd.set_defaults(func=_dispatch_command)


def build_parser(prog: Optional[str] = None) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=prog or "tradinng-bot",
        description="Trading bot CLI"
    )
    sub = p.add_subparsers(dest="command",
                           metavar="{backtest,sweep,walk-forward,robustness,optimize,trade-live}")
    _register_common_flags(sub)
    return p


# ---------------------------
# РАНТАЙМ‑КОМПОЗИЦИЯ (Stage‑A)
# ---------------------------

def _compose_stage_a(args: argparse.Namespace) -> Dict[str, Any]:
    s = get_settings()

    def _opt(val, name, default):
        if val is not None:
            return val
        return getattr(s, name) if hasattr(s, name) else default

    notifier = TelegramNotifier(
        _opt(args.tg_token, "tg_token", ""),
        _opt(args.tg_chat, "tg_chat", "")
    )
    risk_service = RiskService(RiskCfg(
        max_position_pct=_opt(args.max_position_pct, "max_position_pct", 0.25),
        stop_loss_bps=_opt(args.stop_loss_bps, "stop_loss_bps", 300),
        max_daily_loss_bps=None,
    ))
    integration = EngineIntegration(
        notifier=notifier,
        risk=risk_service,
        reconcile_threshold_qty=_opt(args.reconcile_threshold_qty, "reconcile_threshold_qty", 0.0001),
    )
    return dict(settings=s, notifier=notifier, risk_service=risk_service, integration=integration)


# ---------------------------
# BACKTEST PIPELINE
# ---------------------------

def _run_backtest(args: argparse.Namespace, s, notifier: TelegramNotifier) -> int:
    """
    Мини‑бэктест (SMA‑кроссы) + отчёты/CSV.
    """
    pair: str = args.exmo_pair
    res_min, count = _parse_exmo_candles(args.exmo_candles)
    now = int(time.time())
    since = now - res_min * 60 * count

    exmo = build_exmo_from_settings()
    try:
        data = exmo.candles_history(pair, res_min, since, now)
    except Exception as e:
        LOG.error("EXMO candles_history failed: %s", e)
        return 2

    candles = []
    if isinstance(data, dict) and "candles" in data and isinstance(data["candles"], list):
        candles = data["candles"]
    elif isinstance(data, list):
        candles = data
    else:
        LOG.error("Unexpected candles format from EXMO: %s", type(data))
        return 2

    rows: List[Tuple[int, float]] = []
    for c in candles:
        ts = c.get("t") or c.get("time") or c.get("timestamp") or c.get("date")
        close = c.get("c") or c.get("close")
        if ts is None or close is None:
            continue
        try:
            ts = int(ts)
            close = float(close)
        except Exception:
            continue
        rows.append((ts, close))
    rows.sort(key=lambda x: x[0])

    if not rows:
        LOG.error("No candles parsed for %s %s", pair, args.exmo_candles)
        return 2

    ts_list = [ts for ts, _ in rows]
    prices = [p for _, p in rows]
    fast = max(2, int(args.fast))
    slow = max(fast + 1, int(args.slow))

    signals = _cross_signals(prices, fast, slow)
    stats = _backtest_sma(prices, ts_list, signals, fee_bps=int(args.fee_bps), slip_bps=int(args.slip_bps))

    LOG.info("Backtest %s %s fast=%d slow=%d fee=%dbps slip=%dbps",
             pair, args.exmo_candles, fast, slow, int(args.fee_bps), int(args.slip_bps))
    LOG.info("Trades: %d  WinRate: %.1f%%  AvgPnL: %.6f  TotalPnL: %.6f  MaxDD: %.6f  Sharpe(trades): %.2f",
             stats["n_trades"], 100.0 * stats["win_rate"], stats["avg_pnl"], stats["total_pnl"], stats["mdd"], stats["sharpe"])

    # CSV
    if args.csv_trades:
        _save_trades_csv(args.csv_trades, stats["trades"])
        LOG.info("Saved trades CSV -> %s", args.csv_trades)
    if args.csv_equity:
        _save_equity_csv(args.csv_equity, stats["equity_steps"])
        LOG.info("Saved equity CSV -> %s", args.csv_equity)

    # Telegram summary (если включён и настроен)
    if args.summary_alert and notifier.enabled:
        msg = (
            f"<b>Backtest {pair} {args.exmo_candles}</b>\n"
            f"fast={fast} slow={slow} fee={int(args.fee_bps)}bps slip={int(args.slip_bps)}bps\n"
            f"trades={stats['n_trades']} win={stats['win_rate']*100:.1f}% "
            f"avgPnL={stats['avg_pnl']:.6f} totalPnL={stats['total_pnl']:.6f}\n"
            f"maxDD={stats['mdd']:.6f} sharpe={stats['sharpe']:.2f}"
        )
        try:
            notifier.send(msg)
        except Exception:
            pass

    return 0


# ---------------------------
# ОБРАБОТЧИК КОМАНД
# ---------------------------

def _dispatch_command(args: argparse.Namespace) -> int:
    _configure_logging(args.debug)

    if args.exmo_debug or _env_bool("EXMO_DEBUG"):
        os.environ["EXMO_DEBUG"] = "1"
        LOG.debug("EXMO_DEBUG enabled")

    comps = _compose_stage_a(args)
    s = comps["settings"]
    notifier: TelegramNotifier = comps["notifier"]

    cmd = getattr(args, "command", "")
    LOG.info("Command: %s", cmd)

    if cmd == "backtest":
        return _run_backtest(args, s, notifier)
    if cmd == "sweep":
        LOG.info("Sweep pipeline is not wired yet.")
        return 0
    if cmd == "walk-forward":
        LOG.info("Walk-forward pipeline is not wired yet.")
        return 0
    if cmd == "robustness":
        LOG.info("Robustness pipeline is not wired yet.")
        return 0
    if cmd == "optimize":
        LOG.info("Optimize pipeline is not wired yet.")
        return 0
    if cmd == "trade-live":
        LOG.info("Live trading is not wired yet.")
        return 0

    LOG.error("Unknown command: %r", cmd)
    return 2


# ---------------------------
# ВХОДНЫЕ ТОЧКИ
# ---------------------------

def _run_cli(argv: Sequence[str]) -> int:
    parser = build_parser()
    args, _unknown = parser.parse_known_args(list(argv))
    if not getattr(args, "command", None):
        return 0
    func: Optional[Callable[[argparse.Namespace], Any]] = getattr(args, "func", None)
    if func is None:
        return 2
    rc = func(args)
    return int(rc) if isinstance(rc, int) else 0


def main(argv: Optional[Sequence[str]] = None):
    if argv is None:
        return lambda: _run_cli(())  # «callable» для тестов
    return _run_cli(argv)


if __name__ == "__main__":
    sys.exit(_run_cli(sys.argv[1:]))
