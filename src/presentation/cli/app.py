# src/presentation/cli/app.py
from __future__ import annotations

import argparse
import csv
import logging
import math
import os
import sys
import time
from datetime import datetime, timezone
from typing import Callable, Optional, Any, Sequence, Dict, List, Tuple

from src.config.settings import get_settings
from src.infrastructure.notify.telegram import TelegramNotifier
from src.domain.risk.risk_service import RiskService, RiskCfg
from src.application.engine.integration import EngineIntegration
from src.infrastructure.exchange.exmo_api import build_exmo_from_settings
from src.domain.strategy import registry as strat_registry

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


def _unix_seconds(ts_like: Any) -> Optional[int]:
    try:
        ts = float(ts_like)
    except Exception:
        return None
    if ts > 1e15:       # µs
        ts /= 1_000_000.0
    elif ts > 1e12:     # ms
        ts /= 1_000.0
    return int(ts)


# ---------------------------
# BACKTEST (общие метрики)
# ---------------------------

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
    Флаг --strategy и параметры для стратегий:
      sma:      --fast --slow
      rsi2:     --rsi-len --rsi-low --rsi-high
      donchian: --don-n
      ema:      --ema-fast --ema-slow
      macd:     --macd-fast --macd-slow --macd-signal
      bbands:   --bb-len --bb-mult --bb-exit (mid|upper)
      roc:      --roc-len
    """
    for name in ("backtest", "sweep", "walk-forward", "robustness", "optimize"):
        cmd = sp.add_parser(name, help=f"{name} command")

        # Источник данных
        cmd.add_argument("--exmo-pair", type=str, default="DOGE_EUR")
        cmd.add_argument("--exmo-candles", type=str, default="1m:500")

        # Стратегии
        cmd.add_argument("--strategy", type=str, default="sma", choices=strat_registry.names())
        # SMA
        cmd.add_argument("--fast", type=int, default=None)
        cmd.add_argument("--slow", type=int, default=None)
        # RSI2
        cmd.add_argument("--rsi-len", type=int, default=None)
        cmd.add_argument("--rsi-low", type=float, default=None)
        cmd.add_argument("--rsi-high", type=float, default=None)
        # Donchian
        cmd.add_argument("--don-n", type=int, default=None)
        # EMA
        cmd.add_argument("--ema-fast", type=int, default=None)
        cmd.add_argument("--ema-slow", type=int, default=None)
        # MACD
        cmd.add_argument("--macd-fast", type=int, default=None)
        cmd.add_argument("--macd-slow", type=int, default=None)
        cmd.add_argument("--macd-signal", type=int, default=None)
        # Bollinger
        cmd.add_argument("--bb-len", type=int, default=None)
        cmd.add_argument("--bb-mult", type=float, default=None)
        cmd.add_argument("--bb-exit", type=str, choices=["mid", "upper"], default=None)
        # ROC
        cmd.add_argument("--roc-len", type=int, default=None)

        # Симуляция
        cmd.add_argument("--fee-bps", type=int, default=10)
        cmd.add_argument("--slip-bps", type=int, default=2)

        # CSV/репорты
        cmd.add_argument("--csv-trades", type=str, default=None)
        cmd.add_argument("--csv-equity", type=str, default=None)
        cmd.add_argument("--summary-alert", action="store_true")

        # Risk
        cmd.add_argument("--max-position-pct", type=float, default=None)
        cmd.add_argument("--stop-loss-bps", type=int, default=None)
        cmd.add_argument("--max-daily-loss-bps", type=int, default=None)
        cmd.add_argument("--reconcile-threshold-qty", type=float, default=None)

        # Telegram
        cmd.add_argument("--tg-token", type=str, default=None)
        cmd.add_argument("--tg-chat", type=str, default=None)

        cmd.add_argument("--debug", action="store_true")
        cmd.add_argument("--exmo-debug", action="store_true")

        cmd.set_defaults(func=_dispatch_command)

    live = sp.add_parser("trade-live", help="Live pipelines")
    live.add_argument("--mode", type=str, choices=["observe"], default="observe")
    live.add_argument("--exmo-pair", type=str, default="DOGE_EUR")
    live.add_argument("--exmo-candles", type=str, default="1m:300")

    live.add_argument("--strategy", type=str, default="sma", choices=strat_registry.names())
    live.add_argument("--fast", type=int, default=None)
    live.add_argument("--slow", type=int, default=None)
    live.add_argument("--rsi-len", type=int, default=None)
    live.add_argument("--rsi-low", type=float, default=None)
    live.add_argument("--rsi-high", type=float, default=None)
    live.add_argument("--don-n", type=int, default=None)
    live.add_argument("--ema-fast", type=int, default=None)
    live.add_argument("--ema-slow", type=int, default=None)
    live.add_argument("--macd-fast", type=int, default=None)
    live.add_argument("--macd-slow", type=int, default=None)
    live.add_argument("--macd-signal", type=int, default=None)
    live.add_argument("--bb-len", type=int, default=None)
    live.add_argument("--bb-mult", type=float, default=None)
    live.add_argument("--bb-exit", type=str, choices=["mid", "upper"], default=None)
    live.add_argument("--roc-len", type=int, default=None)

    live.add_argument("--poll-sec", type=int, default=10)
    live.add_argument("--heartbeat-sec", type=int, default=30)
    live.add_argument("--summary-alert", action="store_true")

    live.add_argument("--max-position-pct", type=float, default=None)
    live.add_argument("--stop-loss-bps", type=int, default=None)
    live.add_argument("--max-daily-loss-bps", type=int, default=None)
    live.add_argument("--reconcile-threshold-qty", type=float, default=None)

    live.add_argument("--tg-token", type=str, default=None)
    live.add_argument("--tg-chat", type=str, default=None)

    live.add_argument("--debug", action="store_true")
    live.add_argument("--exmo-debug", action="store_true")
    live.set_defaults(func=_dispatch_command)


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
# РАНТАЙМ-КОМПОЗИЦИЯ (Stage-A)
# ---------------------------

def _compose_stage_a(args: argparse.Namespace) -> Dict[str, Any]:
    s = get_settings()

    def _opt(val, name, default):
        if val is not None:
            return val
        return getattr(s, name) if hasattr(s, name) else default

    notifier = TelegramNotifier(
        _opt(getattr(args, "tg_token", None), "tg_token", ""),
        _opt(getattr(args, "tg_chat", None), "tg_chat", "")
    )
    risk_service = RiskService(RiskCfg(
        max_position_pct=_opt(getattr(args, "max_position_pct", None), "max_position_pct", 0.25),
        stop_loss_bps=_opt(getattr(args, "stop_loss_bps", None), "stop_loss_bps", 300),
        max_daily_loss_bps=_opt(getattr(args, "max_daily_loss_bps", None), "max_daily_loss_bps", None),
    ))
    integration = EngineIntegration(
        notifier=notifier,
        risk=risk_service,
        reconcile_threshold_qty=_opt(getattr(args, "reconcile_threshold_qty", None), "reconcile_threshold_qty", 0.0001),
    )
    return dict(settings=s, notifier=notifier, risk_service=risk_service, integration=integration)


# ---------------------------
# ДАННЫЕ: EXMO свечи
# ---------------------------

def _fetch_candles(pair: str, res_min: int, count: int) -> List[Tuple[int, float]]:
    now = int(time.time())
    since = now - res_min * 60 * count
    exmo = build_exmo_from_settings()
    data = exmo.candles_history(pair, res_min, since, now)
    candles = []
    if isinstance(data, dict) and "candles" in data and isinstance(data["candles"], list):
        candles = data["candles"]
    elif isinstance(data, list):
        candles = data
    else:
        raise RuntimeError(f"Unexpected candles format: {type(data)}")
    rows: List[Tuple[int, float]] = []
    for c in candles:
        ts_raw = c.get("t") or c.get("time") or c.get("timestamp") or c.get("date")
        close_raw = c.get("c") or c.get("close")
        if ts_raw is None or close_raw is None:
            continue
        ts = _unix_seconds(ts_raw)
        try:
            close = float(close_raw)
        except Exception:
            continue
        if ts is None:
            continue
        rows.append((ts, close))
    rows.sort(key=lambda x: x[0])
    return rows


# ---------------------------
# ПАРАМЕТРЫ СТРАТЕГИИ
# ---------------------------

def _strategy_params_from_args(name: str, args: argparse.Namespace) -> Dict[str, Any]:
    defn = strat_registry.get(name)
    params = dict(defn.defaults)

    if name == "sma":
        if args.fast is not None: params["fast"] = int(args.fast)
        if args.slow is not None: params["slow"] = int(args.slow)

    elif name == "rsi2":
        if args.rsi_len is not None: params["rsi_len"] = int(args.rsi_len)
        if args.rsi_low is not None: params["low"] = float(args.rsi_low)
        if args.rsi_high is not None: params["high"] = float(args.rsi_high)

    elif name == "donchian":
        if args.don_n is not None: params["n"] = int(args.don_n)

    elif name == "ema":
        if args.ema_fast is not None: params["fast"] = int(args.ema_fast)
        if args.ema_slow is not None: params["slow"] = int(args.ema_slow)

    elif name == "macd":
        if args.macd_fast is not None: params["fast"] = int(args.macd_fast)
        if args.macd_slow is not None: params["slow"] = int(args.macd_slow)
        if args.macd_signal is not None: params["signal"] = int(args.macd_signal)

    elif name == "bbands":
        if args.bb_len is not None: params["length"] = int(args.bb_len)
        if args.bb_mult is not None: params["mult"] = float(args.bb_mult)
        if args.bb_exit is not None: params["exit_rule"] = str(args.bb_exit).lower()

    elif name == "roc":
        if args.roc_len is not None: params["length"] = int(args.roc_len)

    return params


# ---------------------------
# BACKTEST PIPELINE
# ---------------------------

def _run_backtest(args: argparse.Namespace, s, notifier: TelegramNotifier) -> int:
    pair: str = args.exmo_pair
    res_min, count = _parse_exmo_candles(args.exmo_candles)
    try:
        rows = _fetch_candles(pair, res_min, count)
    except Exception as e:
        LOG.error("EXMO candles_history failed: %s", e)
        return 2

    if not rows:
        LOG.error("No candles parsed for %s %s", pair, args.exmo_candles)
        return 2

    ts_list = [ts for ts, _ in rows]
    prices = [p for _, p in rows]

    strat_name = args.strategy
    defn = strat_registry.get(strat_name)
    params = _strategy_params_from_args(strat_name, args)

    signals = defn.generate_signals(prices, **params)
    stats = _backtest_long_only(prices, ts_list, signals, fee_bps=int(args.fee_bps), slip_bps=int(args.slip_bps))

    status_text, _ = defn.status(prices, **params)
    LOG.info("Backtest %s %s strategy=%s params=%s", pair, args.exmo_candles, strat_name, params)
    LOG.info("%s", status_text)
    LOG.info("Trades: %d  WinRate: %.1f%%  AvgPnL: %.6f  TotalPnL: %.6f  MaxDD: %.6f  Sharpe(trades): %.2f",
             stats["n_trades"], 100.0 * stats["win_rate"], stats["avg_pnl"],
             stats["total_pnl"], stats["mdd"], stats["sharpe"])

    if getattr(args, "csv_trades", None):
        _save_trades_csv(args.csv_trades, stats["trades"])
        LOG.info("Saved trades CSV -> %s", args.csv_trades)
    if getattr(args, "csv_equity", None):
        _save_equity_csv(args.csv_equity, stats["equity_steps"])
        LOG.info("Saved equity CSV -> %s", args.csv_equity)

    if getattr(args, "summary_alert", False) and notifier.enabled:
        msg = (
            f"<b>Backtest {pair} {args.exmo_candles} [{strat_name}]</b>\n"
            f"params={params}\n"
            f"trades={stats['n_trades']} win={stats['win_rate']*100:.1f}% "
            f"avgPnL={stats['avg_pnl']:.6f} totalPnL={stats['total_pnl']:.6f}\n"
            f"maxDD={stats['mdd']:.6f} sharpe={stats['sharpe']:.2f}\n"
            f"{status_text}"
        )
        try:
            notifier.send(msg)
        except Exception:
            pass

    return 0


# ---------------------------
# LIVE: OBSERVE
# ---------------------------

def _run_live_observe(args: argparse.Namespace, s, notifier: TelegramNotifier, integration: EngineIntegration) -> int:
    pair: str = args.exmo_pair
    res_min, count = _parse_exmo_candles(args.exmo_candles)
    strat_name = args.strategy
    defn = strat_registry.get(strat_name)
    params = _strategy_params_from_args(strat_name, args)

    poll_sec = max(1, int(args.poll_sec))
    hb_sec = max(5, int(args.heartbeat_sec))

    last_ts = 0
    last_state = None
    last_hb = 0.0

    LOG.info("[live] observe %s %s strategy=%s params=%s poll=%ds",
             pair, args.exmo_candles, strat_name, params, poll_sec)

    try:
        while True:
            try:
                rows = _fetch_candles(pair, res_min, count)
            except Exception as e:
                LOG.error("[live] EXMO error: %s", e)
                time.sleep(poll_sec)
                continue

            if not rows:
                time.sleep(poll_sec)
                continue

            ts_list = [ts for ts, _ in rows]
            prices = [p for _, p in rows]

            status_text, state = defn.status(prices, **params)
            i = len(prices) - 1
            ts = ts_list[i]
            close = prices[i]

            if ts != last_ts:
                t_iso = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
                LOG.info("[live] %s tick  close=%.6f  %s", t_iso, close, status_text)

                if args.summary_alert and notifier.enabled and (last_state is None or state != last_state):
                    arrow = "🔼" if state == 1 else ("🔽" if state == -1 else "⏸")
                    msg = (
                        f"<b>Signal {pair}</b> {args.exmo_candles} [{strat_name}]\n"
                        f"{arrow} state={state} close={close:.6f}\n"
                        f"{status_text}\n"
                        f"params={params}"
                    )
                    try:
                        notifier.send(msg)
                    except Exception:
                        pass

                last_ts = ts
                last_state = state

            now_mono = time.monotonic()
            if args.summary_alert and notifier.enabled and (now_mono - last_hb >= hb_sec):
                try:
                    notifier.send(f"✅ live {pair} ok  close={close:.6f}  {status_text}")
                except Exception:
                    pass
                last_hb = now_mono

            time.sleep(poll_sec)

    except KeyboardInterrupt:
        LOG.info("[live] stop by user")
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
    integration: EngineIntegration = comps["integration"]

    cmd = getattr(args, "command", "")
    LOG.info("Command: %s", cmd)

    if cmd == "backtest":
        return _run_backtest(args, s, notifier)
    if cmd == "trade-live":
        if args.mode == "observe":
            return _run_live_observe(args, s, notifier, integration)
        LOG.error("Unsupported live mode: %s", args.mode)
        return 2
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
