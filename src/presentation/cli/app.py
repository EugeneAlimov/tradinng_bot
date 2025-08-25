# src/presentation/cli/app.py
from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import os
import sys
import time
import inspect
from datetime import datetime, timezone
from typing import Callable, Optional, Any, Sequence, Dict, List, Tuple

from src.config.settings import get_settings
from src.infrastructure.notify.telegram import TelegramNotifier
from src.domain.risk.risk_service import RiskService, RiskCfg
from src.application.engine.integration import EngineIntegration
from src.infrastructure.exchange.exmo_api import build_exmo_from_settings
from src.domain.strategy import registry as strat_registry
from src.application.research import selector as sel
from src.application.live.paper import PaperEngine, PaperConfig

LOG = logging.getLogger("cli")


# ========= common utils =========

def _env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        v = os.getenv(name)
        return int(v) if v is not None else default
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        v = os.getenv(name)
        return float(v) if v is not None else default
    except Exception:
        return default


def _apply_live_config_to_args(args):
    """
    Подмешивает значения из JSON-конфига в args.
    Поддерживает поля:
      strategy, pair, timeframe (напр. '5m'), params{fast, slow, adx_len, on, off, require_di, atr_len, atr_mult},
      poll_sec, heartbeat_sec.
    """
    if not getattr(args, "config", None):
        return args

    import json, re
    with open(args.config, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    # стратегия/пара/таймфрейм
    if "strategy" in cfg:
        args.strategy = cfg["strategy"]
    if "pair" in cfg:
        args.exmo_pair = cfg["pair"]

    # timeframe '5m' -> exmo-candles "5m:2500" (если в args уже есть, не трогаем count)
    tf = cfg.get("timeframe")
    if tf:
        m = re.fullmatch(r"(\d+)([mhd])", str(tf).strip().lower())
        if not m:
            raise ValueError(f"Bad timeframe in config: {tf!r}")
        n, unit = int(m.group(1)), m.group(2)
        mult = {"m": 1, "h": 60, "d": 1440}[unit]
        res_min = n * mult
        # извлечём существующий count из args.exmo_candles, если он уже задан
        default_count = 2500
        count = default_count
        if getattr(args, "exmo_candles", None):
            try:
                parts = str(args.exmo_candles).split(":")
                if len(parts) == 2 and parts[1].isdigit():
                    count = int(parts[1])
            except Exception:
                pass
        args.exmo_candles = f"{res_min}m:{count}" if unit != "m" else f"{n}m:{count}"

    # параметры стратегии -> CLI поля
    p = cfg.get("params", {}) or {}

    def _set(name, val):
        setattr(args, name, val)

    # общеуниверсальные ключи (map -> CLI-параметры)
    if "fast" in p:         _set("ema_fast", int(p["fast"]))
    if "slow" in p:         _set("ema_slow", int(p["slow"]))
    if "adx_len" in p:      _set("adx_len", int(p["adx_len"]))
    if "on" in p:           _set("adx_on", float(p["on"]))
    if "off" in p:          _set("adx_off", float(p["off"]))
    if "require_di" in p:   _set("require_di", bool(p["require_di"]))
    if "atr_len" in p:      _set("atr_len", int(p["atr_len"]))
    if "atr_mult" in p:     _set("atr_mult", float(p["atr_mult"]))

    # сервисные тайминги
    if "poll_sec" in cfg:       args.poll_sec = int(cfg["poll_sec"])
    if "heartbeat_sec" in cfg:  args.heartbeat_sec = int(cfg["heartbeat_sec"])
    return args


def _configure_logging(debug_flag: bool) -> None:
    level = logging.DEBUG if (debug_flag or _env_bool("DEBUG")) else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
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
    if ts > 1e15:
        ts /= 1_000_000.0
    elif ts > 1e12:
        ts /= 1_000.0
    return int(ts)


# ========= backtester (same as before) =========

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


# ========= data: EXMO candles =========

def _fetch_candles_ohlc(pair: str, res_min: int, count: int) -> Dict[str, List[float]]:
    """
    Тянем свечи EXMO с ретраями и экспоненциальным бэкофом.
    Параметры можно подкрутить переменными окружения:
      HTTP_RETRIES (int, по умолчанию 3)
      HTTP_BACKOFF (float секунд, по умолчанию 0.8)
    """
    retries = max(0, _env_int("HTTP_RETRIES", 3))
    backoff = max(0.0, _env_float("HTTP_BACKOFF", 0.8))

    res_min = max(1, int(res_min))
    count = max(10, int(count))

    last_err: Optional[Exception] = None
    for attempt in range(retries + 1):
        now = int(time.time())
        since = now - res_min * 60 * count
        try:
            exmo = build_exmo_from_settings()
            data = exmo.candles_history(pair, res_min, since, now)

            # Нормализуем ответ
            if isinstance(data, dict) and "candles" in data and isinstance(data["candles"], list):
                candles = data["candles"]
            elif isinstance(data, list):
                candles = data
            else:
                raise RuntimeError(f"Unexpected candles format: {type(data)}")

            ts: List[int] = []
            o: List[float] = []
            h: List[float] = []
            l: List[float] = []
            c: List[float] = []
            for cndl in candles:
                ts_raw = cndl.get("t") or cndl.get("time") or cndl.get("timestamp") or cndl.get("date")
                open_raw = cndl.get("o") or cndl.get("open") or cndl.get("O")
                high_raw = cndl.get("h") or cndl.get("high") or cndl.get("H")
                low_raw = cndl.get("l") or cndl.get("low") or cndl.get("L")
                close_raw = cndl.get("c") or cndl.get("close") or cndl.get("C")
                ts_sec = _unix_seconds(ts_raw)
                if ts_sec is None or close_raw is None:
                    continue
                try:
                    oc = float(close_raw)
                    oo = float(open_raw) if open_raw is not None else oc
                    oh = float(high_raw) if high_raw is not None else oc
                    ol = float(low_raw) if low_raw is not None else oc
                except Exception:
                    continue
                ts.append(ts_sec)
                o.append(oo)
                h.append(oh)
                l.append(ol)
                c.append(oc)

            zipped = sorted(zip(ts, o, h, l, c), key=lambda x: x[0])
            if not zipped:
                raise RuntimeError("Empty candles after parse")

            ts, o, h, l, c = map(list, zip(*zipped))
            return {"ts": ts, "open": o, "high": h, "low": l, "close": c}

        except Exception as e:
            last_err = e
            if attempt >= retries:
                # проиграли — пусть наверх, поведение прежнее
                raise
            sleep = backoff * (2 ** attempt)
            LOG.warning("EXMO fetch failed (attempt %d/%d): %s; retry in %.2fs",
                        attempt + 1, retries + 1, e, sleep)
            time.sleep(sleep)

    # теоретически недостижимо, но чтобы mypy не ругался
    raise RuntimeError(f"EXMO fetch failed: {last_err}")


# ========= safe strategy call =========

def _call_with_supported(fn: Callable[..., Any], arrays: Dict[str, List[float]], extra_params: Dict[str, Any]) -> Any:
    candidate_kwargs = {
        "prices": arrays.get("close"),
        "ts": arrays.get("ts"),
        "close": arrays.get("close"),
        "open": arrays.get("open"),
        "high": arrays.get("high"),
        "low": arrays.get("low"),
    }
    candidate_kwargs.update(extra_params or {})
    sig = inspect.signature(fn)
    supported = {k: v for k, v in candidate_kwargs.items() if k in sig.parameters}
    return fn(**supported)


# ========= CLI wiring =========

def _register_common_flags(sp: argparse._SubParsersAction) -> None:
    """
    Команды:
      backtest, sweep, optimize, walk-forward, robustness, auto-pick, trade-live
    """
    for name in ("backtest", "sweep", "optimize", "walk-forward", "robustness", "auto-pick", "trade-live"):
        cmd = sp.add_parser(name, help=f"{name} command")

        # Источник данных
        cmd.add_argument("--exmo-pair", type=str, default="DOGE_EUR")
        cmd.add_argument("--exmo-candles", type=str, default="1m:1000" if name in (
            "sweep", "optimize", "walk-forward", "auto-pick", "robustness") else "1m:500")

        # Стратегии
        if name in ("backtest", "optimize", "robustness", "trade-live"):
            cmd.add_argument("--strategy", type=str, default="sma", choices=strat_registry.names())
        else:
            cmd.add_argument("--strategies", type=str, default="auto", help="comma-separated or 'auto'")

        # Общие параметры стратегий
        cmd.add_argument("--fast", type=int, default=None)
        cmd.add_argument("--slow", type=int, default=None)
        cmd.add_argument("--rsi-len", type=int, default=None)
        cmd.add_argument("--rsi-low", type=float, default=None)
        cmd.add_argument("--rsi-high", type=float, default=None)
        cmd.add_argument("--don-n", type=int, default=None)
        cmd.add_argument("--ema-fast", type=int, default=None)
        cmd.add_argument("--ema-slow", type=int, default=None)
        cmd.add_argument("--macd-fast", type=int, default=None)
        cmd.add_argument("--macd-slow", type=int, default=None)
        cmd.add_argument("--macd-signal", type=int, default=None)
        cmd.add_argument("--bb-len", type=int, default=None)
        cmd.add_argument("--bb-mult", type=float, default=None)
        cmd.add_argument("--bb-exit", type=str, choices=["mid", "upper"], default=None)
        cmd.add_argument("--roc-len", type=int, default=None)
        cmd.add_argument("--st-len", type=int, default=None)
        cmd.add_argument("--st-mult", type=float, default=None)
        cmd.add_argument("--kc-len", type=int, default=None)
        cmd.add_argument("--kc-mult", type=float, default=None)
        cmd.add_argument("--kc-mode", type=str, choices=["breakout", "meanrev"], default=None)
        cmd.add_argument("--kc-exit", type=str, choices=["mid", "upper"], default=None)
        cmd.add_argument("--adx-len", type=int, default=None)
        cmd.add_argument("--adx-min", type=float, default=None)
        cmd.add_argument("--atr-len", type=int, default=None)
        cmd.add_argument("--atr-mult", type=float, default=None)
        cmd.add_argument("--ce-len", type=int, default=None)
        cmd.add_argument("--adx-on", type=float, default=None)
        cmd.add_argument("--adx-off", type=float, default=None)
        cmd.add_argument("--require-di", action="store_true")
        cmd.add_argument("--no-require-di", action="store_true")

        # Симуляция
        cmd.add_argument("--fee-bps", type=int, default=10)
        cmd.add_argument("--slip-bps", type=int, default=2)

        # Sweep/Optimize/WF/Robustness scoring & constraints
        if name in ("sweep", "optimize", "walk-forward", "auto-pick"):
            cmd.add_argument("--grid-file", type=str, default=None)
            cmd.add_argument("--metric", type=str, default="score", choices=["score", "sharpe", "total", "winrate"])
            cmd.add_argument("--top-n", type=int, default=10)
            cmd.add_argument("--min-trades", type=int, default=3)
            cmd.add_argument("--min-win", type=float, default=None, help="%, e.g. 30 for 30%")
            cmd.add_argument("--max-dd", type=float, default=None, help="absolute |mdd| limit, same units as PnL")

            # weights for score
            cmd.add_argument("--w-sharpe", type=float, default=1.0)
            cmd.add_argument("--w-total", type=float, default=0.75)
            cmd.add_argument("--w-win", type=float, default=0.25)
            cmd.add_argument("--w-dd", type=float, default=0.5)
            cmd.add_argument("--w-trades", type=float, default=0.2)

        if name == "walk-forward":
            cmd.add_argument("--wf-folds", type=int, default=3)
            cmd.add_argument("--wf-train-frac", type=float, default=0.7)

        if name in ("robustness", "auto-pick"):
            cmd.add_argument("--robust", action="store_true", help="enable robustness stress test")
            cmd.add_argument("--robust-level", type=str, default="std", choices=["light", "std", "hard"])
            cmd.add_argument("--samples", type=int, default=1)

        if name == "auto-pick":
            cmd.add_argument("--wf-check", action="store_true", help="run walk-forward on top-1")
            cmd.add_argument("--run-live", action="store_true", help="after pick, start observe")
            cmd.add_argument("--poll-sec", type=int, default=10)
            cmd.add_argument("--heartbeat-sec", type=int, default=60)

        # --- ДОБАВЛЕНО: специфично для trade-live ---
        if name == "trade-live":
            cmd.add_argument("--mode", type=str, default="observe", choices=["observe", "paper"])
            cmd.add_argument("--poll-sec", type=int, default=10)
            cmd.add_argument("--heartbeat-sec", type=int, default=60)
            cmd.add_argument("--config", type=str, default=None, help="Path to JSON config for live run")
            cmd.add_argument("--http-retries", type=int, default=None, help="Override HTTP_RETRIES env")
            cmd.add_argument("--http-backoff", type=float, default=None, help="Override HTTP_BACKOFF env (sec)")
            # paper-mode specific:
            cmd.add_argument("--initial-balance", type=float, default=1000.0)
            cmd.add_argument("--csv-trades", type=str, default=None)
            cmd.add_argument("--csv-equity", type=str, default=None)

        # CSV/репорты
        if name in ("backtest",):
            cmd.add_argument("--csv-trades", type=str, default=None)
            cmd.add_argument("--csv-equity", type=str, default=None)
            cmd.add_argument("--summary-alert", action="store_true")
        if name in ("sweep", "optimize", "walk-forward", "robustness", "auto-pick"):
            cmd.add_argument("--csv-results", type=str, default=None)

        # Risk (зарезервировано)
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


def build_parser(prog: Optional[str] = None) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=prog or "tradinng-bot", description="Trading bot CLI")
    sub = p.add_subparsers(dest="command",
                           metavar="{backtest,sweep,optimize,walk-forward,robustness,auto-pick,trade-live}")
    _register_common_flags(sub)
    return p


# ========= stage-A composition =========

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


# ========= params mapper =========

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
    elif name == "supertrend":
        if args.st_len is not None: params["atr_len"] = int(args.st_len)
        if args.st_mult is not None: params["mult"] = float(args.st_mult)
    elif name == "keltner":
        if args.kc_len is not None: params["kc_len"] = int(args.kc_len)
        if args.kc_mult is not None: params["kc_mult"] = float(args.kc_mult)
        if args.kc_mode is not None: params["mode"] = str(args.kc_mode)
        if args.kc_exit is not None: params["exit_rule"] = str(args.kc_exit)
    elif name == "adx":
        if args.adx_len is not None: params["adx_len"] = int(args.adx_len)
        if args.adx_min is not None: params["min_adx"] = float(args.adx_min)
    elif name == "sma_atr":
        if args.fast is not None: params["fast"] = int(args.fast)
        if args.slow is not None: params["slow"] = int(args.slow)
        if args.atr_len is not None: params["atr_len"] = int(args.atr_len)
        if args.atr_mult is not None: params["atr_mult"] = float(args.atr_mult)
        if args.ce_len is not None: params["chandelier_len"] = int(args.ce_len)
    elif name == "ema_adx":
        if args.ema_fast is not None: params["fast"] = int(args.ema_fast)
        if args.ema_slow is not None: params["slow"] = int(args.ema_slow)
        if args.adx_len is not None: params["adx_len"] = int(args.adx_len)
        if args.adx_on is not None: params["on"] = float(args.adx_on)
        if args.adx_off is not None: params["off"] = float(args.adx_off)
        if getattr(args, "no_require_di", False):
            params["require_di"] = False
        elif getattr(args, "require_di", False):
            params["require_di"] = True
    elif name == "ema_adx_atr":
        if args.ema_fast is not None: params["fast"] = int(args.ema_fast)
        if args.ema_slow is not None: params["slow"] = int(args.ema_slow)
        if args.adx_len is not None:  params["adx_len"] = int(args.adx_len)
        if args.adx_on is not None:   params["on"] = float(args.adx_on)
        if args.adx_off is not None:  params["off"] = float(args.adx_off)
        if getattr(args, "no_require_di", False):
            params["require_di"] = False
        elif getattr(args, "require_di", False):
            params["require_di"] = True
        if args.atr_len is not None:  params["atr_len"] = int(args.atr_len)
        if args.atr_mult is not None: params["atr_mult"] = float(args.atr_mult)

    return params


# ========= core runners =========

def _resolve_strategies_list(arg: str) -> List[str]:
    if not arg or arg.strip().lower() == "auto":
        return list(sel.default_grids().keys())
    return [s.strip() for s in arg.split(",") if s.strip()]


def _print_table(rows: List[List[Any]], header: List[str]) -> None:
    widths = [len(h) for h in header]
    for r in rows:
        for i, x in enumerate(r):
            widths[i] = max(widths[i], len(str(x)))

    def fmt(row):
        return "  ".join(str(x).ljust(widths[i], " ") for i, x in enumerate(row))

    LOG.info(fmt(header))
    for r in rows:
        LOG.info(fmt(r))


def _save_results_csv(path: str, rows: List[List[Any]], header: List[str]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def _fetch_ohlc_from_args(args: argparse.Namespace) -> Dict[str, List[float]]:
    res_min, count = _parse_exmo_candles(args.exmo_candles)
    ohlc = _fetch_candles_ohlc(args.exmo_pair, res_min, count)
    if not ohlc["ts"]:
        raise RuntimeError("No candles parsed")
    return ohlc


def _weights_from_args(args: argparse.Namespace) -> sel.ScoreWeights:
    return sel.ScoreWeights(
        w_sharpe=float(getattr(args, "w_sharpe", 1.0)),
        w_total=float(getattr(args, "w_total", 0.75)),
        w_win=float(getattr(args, "w_win", 0.25)),
        w_dd=float(getattr(args, "w_dd", 0.5)),
        w_trades=float(getattr(args, "w_trades", 0.2)),
    )


def _constraints_from_args(args: argparse.Namespace) -> sel.Constraints:
    return sel.Constraints(
        min_trades=int(getattr(args, "min_trades", 3)),
        min_win=(float(args.min_win) / 100.0 if getattr(args, "min_win", None) is not None else None),
        max_dd_abs=float(args.max_dd) if getattr(args, "max_dd", None) is not None else None,
    )


def _robust_cfg_from_args(args: argparse.Namespace) -> sel.RobustCfg:
    level = getattr(args, "robust_level", "std")
    if level == "light":
        return sel.RobustCfg(fee_mults=(1.0, 1.5), slip_mults=(1.0, 1.5), noise_bps=(0.0, 5.0), bar_shifts=(0, 1),
                             param_jitter_pct=0.05, samples=int(getattr(args, "samples", 1)))
    if level == "hard":
        return sel.RobustCfg(fee_mults=(1.0, 1.5, 2.0), slip_mults=(1.0, 1.5, 2.0), noise_bps=(0.0, 5.0, 10.0, 15.0),
                             bar_shifts=(0, 1, 2, 3), param_jitter_pct=0.15, samples=int(getattr(args, "samples", 1)))
    return sel.RobustCfg(samples=int(getattr(args, "samples", 1)))  # std


# ---- backtest ----

def _run_backtest(args: argparse.Namespace, s, notifier: TelegramNotifier) -> int:
    try:
        ohlc = _fetch_ohlc_from_args(args)
    except Exception as e:
        LOG.error("EXMO candles_history failed: %s", e)
        return 2

    ts_list = ohlc["ts"]
    open_arr = ohlc["open"]
    high_arr = ohlc["high"]
    low_arr = ohlc["low"]
    close_arr = ohlc["close"]
    strat_name = args.strategy
    defn = strat_registry.get(strat_name)
    params = _strategy_params_from_args(strat_name, args)

    signals = _call_with_supported(defn.generate_signals,
                                   arrays={"ts": ts_list, "open": open_arr, "high": high_arr, "low": low_arr,
                                           "close": close_arr},
                                   extra_params=params)

    stats = _backtest_long_only(close_arr, ts_list, signals, fee_bps=int(args.fee_bps), slip_bps=int(args.slip_bps))
    status_text, _ = _call_with_supported(defn.status,
                                          arrays={"ts": ts_list, "open": open_arr, "high": high_arr, "low": low_arr,
                                                  "close": close_arr},
                                          extra_params=params)

    LOG.info("Backtest %s %s strategy=%s params=%s", args.exmo_pair, args.exmo_candles, strat_name, params)
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
        msg = (f"<b>Backtest {args.exmo_pair} {args.exmo_candles} [{strat_name}]</b>\n"
               f"params={params}\n"
               f"trades={stats['n_trades']} win={stats['win_rate'] * 100:.1f}% "
               f"avgPnL={stats['avg_pnl']:.6f} totalPnL={stats['total_pnl']:.6f}\n"
               f"maxDD={stats['mdd']:.6f} sharpe={stats['sharpe']:.2f}\n"
               f"{status_text}")
        try:
            notifier.send(msg)
        except Exception:
            pass
    return 0


# ---- sweep/optimize/wf ----

def _run_sweep(args: argparse.Namespace) -> int:
    try:
        ohlc = _fetch_ohlc_from_args(args)
    except Exception as e:
        LOG.error("EXMO candles_history failed: %s", e)
        return 2

    strategies = _resolve_strategies_list(args.strategies)
    grid = sel.load_grid_json(args.grid_file) if args.grid_file else None

    LOG.info("Sweep %s %s strategies=%s metric=%s", args.exmo_pair, args.exmo_candles, strategies, args.metric)
    results = sel.sweep(ohlc, strategies, grid, args.fee_bps, args.slip_bps, min_trades=args.min_trades)
    results = sel.apply_constraints(results, _constraints_from_args(args))
    if args.metric == "score":
        results = sel.score_rows(results, _weights_from_args(args))
    ranked = sel.rank(results, metric=args.metric, top_n=args.top_n)

    header = ["strategy", "params", "trades", "win%", "avgPnL", "totalPnL", "maxDD", "sharpe", "score"]
    rows = [r.to_list() for r in ranked]
    _print_table(rows, header)
    if args.csv_results:
        _save_results_csv(args.csv_results, rows, header)
        LOG.info("Saved sweep CSV -> %s", args.csv_results)
    return 0


def _run_optimize(args: argparse.Namespace) -> int:
    try:
        ohlc = _fetch_ohlc_from_args(args)
    except Exception as e:
        LOG.error("EXMO candles_history failed: %s", e)
        return 2

    strategy = args.strategy
    grid_all = sel.load_grid_json(args.grid_file) if args.grid_file else None
    grid = grid_all if (grid_all and strategy in grid_all) else {strategy: sel.default_grids().get(strategy, [])}
    if not grid.get(strategy):
        LOG.error("No grid for strategy=%s", strategy)
        return 2

    LOG.info("Optimize %s %s strategy=%s metric=%s", args.exmo_pair, args.exmo_candles, strategy, args.metric)
    results = sel.sweep(ohlc, [strategy], grid, args.fee_bps, args.slip_bps, min_trades=args.min_trades)
    results = sel.apply_constraints(results, _constraints_from_args(args))
    if args.metric == "score":
        results = sel.score_rows(results, _weights_from_args(args))
    ranked = sel.rank(results, metric=args.metric, top_n=args.top_n)

    header = ["strategy", "params", "trades", "win%", "avgPnL", "totalPnL", "maxDD", "sharpe", "score"]
    rows = [r.to_list() for r in ranked]
    _print_table(rows, header)
    if args.csv_results:
        _save_results_csv(args.csv_results, rows, header)
        LOG.info("Saved optimize CSV -> %s", args.csv_results)
    return 0


def _run_walk_forward(args: argparse.Namespace) -> int:
    try:
        ohlc = _fetch_ohlc_from_args(args)
    except Exception as e:
        LOG.error("EXMO candles_history failed: %s", e)
        return 2

    strategies = _resolve_strategies_list(args.strategies)
    grid = sel.load_grid_json(args.grid_file) if args.grid_file else None

    LOG.info("Walk-Forward %s %s strategies=%s folds=%d train_frac=%.2f metric=%s",
             args.exmo_pair, args.exmo_candles, strategies, args.wf_folds, args.wf_train_frac, args.metric)

    weights = _weights_from_args(args) if args.metric == "score" else None
    folds, agg = sel.walk_forward(
        ohlc, strategies, grid, args.fee_bps, args.slip_bps,
        folds=args.wf_folds, train_frac=args.wf_train_frac,
        min_trades=args.min_trades, rank_metric=args.metric,
        score_weights=weights, constraints=_constraints_from_args(args)
    )

    for idx, f in enumerate(folds, 1):
        if f.best and f.test_eval:
            LOG.info("[WF %d] train[0:%d) test[%d:%d) -> best=%s %s | test: trades=%d total=%.6f sharpe=%.2f",
                     idx, f.train_to, f.test_from, f.test_to,
                     f.best.strategy, f.best.params,
                     f.test_eval.n_trades, f.test_eval.total_pnl, f.test_eval.sharpe)
        else:
            LOG.info("[WF %d] train[0:%d) test[%d:%d) -> insufficient data", idx, f.train_to, f.test_from, f.test_to)

    LOG.info("WF aggregate: folds=%d trades=%d totalPnL=%.6f avgSharpe=%.2f",
             agg["folds"], agg["n_trades"], agg["total_pnl"], agg["avg_sharpe"])

    if args.csv_results:
        header = ["fold", "train_to", "test_from", "test_to", "strategy", "params", "trades", "totalPnL", "sharpe"]
        rows: List[List[Any]] = []
        for i, f in enumerate(folds, 1):
            if f.best and f.test_eval:
                rows.append([i, f.train_to, f.test_from, f.test_to,
                             f.best.strategy, f.best.params,
                             f.test_eval.n_trades, round(f.test_eval.total_pnl, 6), round(f.test_eval.sharpe, 3)])
        _save_results_csv(args.csv_results, rows, header)
        LOG.info("Saved walk-forward CSV -> %s", args.csv_results)
    return 0


# ---- robustness ----

def _run_robustness(args: argparse.Namespace) -> int:
    try:
        ohlc = _fetch_ohlc_from_args(args)
    except Exception as e:
        LOG.error("EXMO candles_history failed: %s", e)
        return 2

    strategy = args.strategy
    params = _strategy_params_from_args(strategy, args)
    LOG.info("Robustness %s %s strategy=%s params=%s level=%s",
             args.exmo_pair, args.exmo_candles, strategy, params, args.robust_level)

    cfg = _robust_cfg_from_args(args)
    r = sel.robustness(ohlc, strategy, params, args.fee_bps, args.slip_bps, cfg)
    header = ["passes", "total", "pass_ratio", "avgSharpe", "avgTotal", "worstSharpe", "worstTotal", "robustScore"]
    rows = [[r.passes, r.total, round(r.passes / r.total if r.total else 0.0, 3),
             round(r.avg_sharpe, 3), round(r.avg_total, 6), round(r.worst_sharpe, 3), round(r.worst_total, 6),
             round(r.score, 3)]]
    _print_table(rows, header)
    if args.csv_results:
        _save_results_csv(args.csv_results, rows, header)
        LOG.info("Saved robustness CSV -> %s", args.csv_results)
    return 0


# ---- auto-pick (sweep -> score/constraints -> optional robustness -> optional WF -> optional live) ----

def _run_auto_pick(args: argparse.Namespace, s, notifier: TelegramNotifier, integration: EngineIntegration) -> int:
    try:
        ohlc = _fetch_ohlc_from_args(args)
    except Exception as e:
        LOG.error("EXMO candles_history failed: %s", e)
        return 2

    strategies = _resolve_strategies_list(args.strategies)
    grid = sel.load_grid_json(args.grid_file) if args.grid_file else None
    LOG.info("Auto-Pick %s %s strategies=%s metric=%s", args.exmo_pair, args.exmo_candles, strategies, args.metric)

    results = sel.sweep(ohlc, strategies, grid, args.fee_bps, args.slip_bps, min_trades=args.min_trades)
    results = sel.apply_constraints(results, _constraints_from_args(args))
    if args.metric == "score":
        results = sel.score_rows(results, _weights_from_args(args))
    ranked = sel.rank(results, metric=args.metric, top_n=max(3, args.top_n))

    if not ranked:
        LOG.error("No candidates after ranking")
        return 2

    # optional robustness on top-K
    if args.robust:
        cfg = _robust_cfg_from_args(args)
        scored: List[Tuple[float, sel.EvalRow]] = []
        for r in ranked[:args.top_n]:
            rob = sel.robustness(ohlc, r.strategy, r.params, args.fee_bps, args.slip_bps, cfg)
            # комбинируем исходный score/метрику и робастность
            base = r.score if args.metric == "score" else r.sharpe
            combo = 0.7 * base + 0.3 * rob.score
            scored.append((combo, r))
            LOG.info("[robust] %s %s -> base=%.3f robust=%.3f combo=%.3f", r.strategy, r.params, base, rob.score, combo)
        scored.sort(key=lambda x: x[0], reverse=True)
        best = scored[0][1]
    else:
        best = ranked[0]

    LOG.info("Picked: %s %s", best.strategy, best.params)

    # optional WF check
    if getattr(args, "wf_check", False):
        folds, agg = sel.walk_forward(ohlc, [best.strategy], {best.strategy: [best.params]}, args.fee_bps,
                                      args.slip_bps,
                                      folds=3, train_frac=0.7, min_trades=args.min_trades, rank_metric="sharpe")
        LOG.info("WF check: folds=%d trades=%d totalPnL=%.6f avgSharpe=%.2f",
                 agg["folds"], agg["n_trades"], agg["total_pnl"], agg["avg_sharpe"])

    # print suggested command and optionally run live observe
    LOG.info("Suggested live command:\n"
             "python -m src.presentation.cli.app trade-live --mode observe "
             f"--strategy {best.strategy} "
             f"{' '.join(f'--{k.replace('_', '-')} {v}' for k, v in best.params.items())} "
             f"--exmo-pair {args.exmo_pair} --exmo-candles {args.exmo_candles} "
             f"--poll-sec {args.poll_sec if hasattr(args, 'poll_sec') else 10} "
             f"--heartbeat-sec {args.heartbeat_sec if hasattr(args, 'heartbeat_sec') else 60} --summary-alert")

    if getattr(args, "run_live", False):
        # inline observe loop with chosen params
        return _observe_inline(args, best.strategy, best.params, s, notifier, integration)
    return 0


def _observe_inline(args: argparse.Namespace, strategy: str, params: Dict[str, Any], s, notifier: TelegramNotifier,
                    integration: EngineIntegration) -> int:
    pair: str = args.exmo_pair
    res_min, count = _parse_exmo_candles(args.exmo_candles)
    defn = strat_registry.get(strategy)

    poll_sec = max(1, int(getattr(args, "poll_sec", 10)))
    hb_sec = max(5, int(getattr(args, "heartbeat_sec", 60)))
    last_ts = 0
    last_state = None
    last_hb = 0.0

    LOG.info("[live] observe %s %s strategy=%s params=%s poll=%ds",
             pair, args.exmo_candles, strategy, params, poll_sec)

    try:
        while True:
            try:
                ohlc = _fetch_candles_ohlc(pair, res_min, count)
            except Exception as e:
                LOG.error("[live] EXMO error: %s", e)
                time.sleep(poll_sec)
                continue

            ts_list = ohlc["ts"]
            open_arr = ohlc["open"]
            high_arr = ohlc["high"]
            low_arr = ohlc["low"]
            close_arr = ohlc["close"]
            if not ts_list:
                time.sleep(poll_sec)
                continue

            status_text, state = _call_with_supported(defn.status,
                                                      arrays={"ts": ts_list, "open": open_arr, "high": high_arr,
                                                              "low": low_arr, "close": close_arr},
                                                      extra_params=params)
            i = len(close_arr) - 1
            ts = ts_list[i]
            close = close_arr[i]

            if ts != last_ts:
                t_iso = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
                LOG.info("[live] %s tick  close=%.6f  %s", t_iso, close, status_text)

                if getattr(args, "summary_alert", False) and notifier.enabled and (
                        last_state is None or state != last_state):
                    arrow = "🔼" if state == 1 else ("🔽" if state == -1 else "⏸")
                    msg = (f"<b>Signal {pair}</b> {args.exmo_candles} [{strategy}]\n"
                           f"{arrow} state={state} close={close:.6f}\n"
                           f"{status_text}\n"
                           f"params={params}")
                    try:
                        notifier.send(msg)
                    except Exception:
                        pass

                last_ts = ts
                last_state = state

            now_mono = time.monotonic()
            if getattr(args, "summary_alert", False) and notifier.enabled and (now_mono - last_hb >= hb_sec):
                try:
                    notifier.send(f"✅ live {pair} ok  close={close:.6f}  {status_text}")
                except Exception:
                    pass
                last_hb = now_mono

            time.sleep(poll_sec)

    except KeyboardInterrupt:
        LOG.info("[live] stop by user")
        return 0


# ---- trade-live (observe mode) ----

def _run_live_observe(args: argparse.Namespace, s, notifier: TelegramNotifier, integration: EngineIntegration) -> int:
    return _observe_inline(args, args.strategy, _strategy_params_from_args(args.strategy, args), s, notifier,
                           integration)


def _run_live_paper(args: argparse.Namespace, s, notifier: TelegramNotifier, integration: EngineIntegration) -> int:
    pair: str = args.exmo_pair
    res_min, count = _parse_exmo_candles(args.exmo_candles)
    strat_name = args.strategy
    defn = strat_registry.get(strat_name)
    params = _strategy_params_from_args(strat_name, args)

    poll_sec = max(1, int(getattr(args, "poll_sec", 10)))
    hb_sec = max(5, int(getattr(args, "heartbeat_sec", 60)))
    last_hb = 0.0
    last_closed_ts: Optional[int] = None
    last_state_for_msg: Optional[int] = None

    # Paper engine
    cfg = PaperConfig(
        initial_balance=float(getattr(args, "initial_balance", 1000.0)),
        fee_bps=int(getattr(args, "fee_bps", 10)),
        slip_bps=int(getattr(args, "slip_bps", 2)),
        max_position_pct=float(getattr(args, "max_position_pct", 0.25)) if getattr(args, "max_position_pct",
                                                                                   None) is not None else 0.25,
        stop_loss_bps=int(getattr(args, "stop_loss_bps", 300)) if getattr(args, "stop_loss_bps",
                                                                          None) is not None else 300,
        max_daily_loss_bps=int(getattr(args, "max_daily_loss_bps", 0)) or None,
    )
    engine = PaperEngine(cfg, integration.risk)

    LOG.info("[live:paper] %s %s strategy=%s params=%s poll=%ds",
             pair, args.exmo_candles, strat_name, params, poll_sec)

    try:
        while True:
            try:
                ohlc = _fetch_candles_ohlc(pair, res_min, count)
            except Exception as e:
                LOG.error("[live:paper] EXMO error: %s", e)
                time.sleep(poll_sec)
                continue

            ts = ohlc["ts"]
            o = ohlc["open"]
            h = ohlc["high"]
            l = ohlc["low"]
            c = ohlc["close"]
            if len(ts) < 2:
                time.sleep(poll_sec)
                continue

            # используем ПРЕДЫДУЩУЮ свечу как "закрытую"
            i_closed = len(ts) - 2
            ts_closed = ts[i_closed]
            if last_closed_ts is not None and ts_closed <= last_closed_ts:
                # ждём новую свечу
                time.sleep(poll_sec)
                continue

            # генерим сигналы на всём массиве (стратегии уже умеют)
            signals = _call_with_supported(defn.generate_signals,
                                           arrays={"ts": ts, "open": o, "high": h, "low": l, "close": c},
                                           extra_params=params)
            sig = int(signals[i_closed]) if isinstance(signals, list) and len(signals) > i_closed else 0

            # update status (для логов/уведомлений)
            status_text, _state = _call_with_supported(defn.status,
                                                       arrays={"ts": ts, "open": o, "high": h, "low": l, "close": c},
                                                       extra_params=params)

            # совершаем действие по закрытой свече
            changed = engine.on_new_closed_bar(ts_closed, o[i_closed], h[i_closed], l[i_closed], c[i_closed], sig)

            # логи/уведомления на события
            t_iso = datetime.fromtimestamp(ts_closed, tz=timezone.utc).isoformat()
            LOG.info("[live:paper] %s close=%.6f sig=%+d %s", t_iso, c[i_closed], sig, status_text)

            if changed is not None:
                state_change, equity = changed
                if getattr(args, "summary_alert", False) and notifier.enabled:
                    if state_change != 0 or last_state_for_msg != state_change:
                        arrow = "🟢 BUY" if state_change == +1 else ("🔴 SELL" if state_change == -1 else "⏸ HOLD")
                        msg = (f"<b>Paper {pair}</b> {args.exmo_candles} [{strat_name}]\n"
                               f"{arrow} close={c[i_closed]:.6f}\n"
                               f"{status_text}\n"
                               f"equity={equity:.4f} params={params}")
                        try:
                            notifier.send(msg)
                        except Exception:
                            pass
                        last_state_for_msg = state_change

            # heartbeat
            now_mono = time.monotonic()
            if getattr(args, "summary_alert", False) and notifier.enabled and (now_mono - last_hb >= hb_sec):
                eq = engine.export_equity()[-1][1] if engine.export_equity() else 0.0
                try:
                    notifier.send(f"✅ live:paper {pair} ok  equity={eq:.4f}  {status_text}")
                except Exception:
                    pass
                last_hb = now_mono

            last_closed_ts = ts_closed
            time.sleep(poll_sec)

    except KeyboardInterrupt:
        LOG.info("[live:paper] stop by user")
        # по выходу — если просили, сохраним CSV через общие хелперы из app.py
        if getattr(args, "csv_trades", None):
            _save_trades_csv(args.csv_trades, engine.export_trades())
            LOG.info("Saved trades CSV -> %s", args.csv_trades)
        if getattr(args, "csv_equity", None):
            _save_equity_csv(args.csv_equity, engine.export_equity())
            LOG.info("Saved equity CSV -> %s", args.csv_equity)
        return 0


# ========= dispatcher =========

def _dispatch_command(args: argparse.Namespace) -> int:
    _configure_logging(args.debug)

    if args.exmo_debug or _env_bool("EXMO_DEBUG"):
        os.environ["EXMO_DEBUG"] = "1"
        LOG.debug("EXMO_DEBUG enabled")

    # ДОБАВЛЕНО: применяем конфиг и CLI-ретраи до запуска live
    if getattr(args, "command", "") == "trade-live":
        args = _apply_live_config_to_args(args)
        if getattr(args, "http_retries", None) is not None:
            os.environ["HTTP_RETRIES"] = str(args.http_retries)
        if getattr(args, "http_backoff", None) is not None:
            os.environ["HTTP_BACKOFF"] = str(args.http_backoff)

    comps = _compose_stage_a(args)
    s = comps["settings"]
    notifier: TelegramNotifier = comps["notifier"]
    integration: EngineIntegration = comps["integration"]

    cmd = getattr(args, "command", "")
    LOG.info("Command: %s", cmd)

    if cmd == "backtest":
        return _run_backtest(args, s, notifier)
    if cmd == "sweep":
        return _run_sweep(args)
    if cmd == "optimize":
        return _run_optimize(args)
    if cmd == "walk-forward":
        return _run_walk_forward(args)
    if cmd == "robustness":
        return _run_robustness(args)
    if cmd == "auto-pick":
        return _run_auto_pick(args, s, notifier, integration)
    if cmd == "trade-live":
        mode = getattr(args, "mode", "observe")
        if mode == "observe":
            return _run_live_observe(args, s, notifier, integration)
        if mode == "paper":
            return _run_live_paper(args, s, notifier, integration)
        LOG.error("Unsupported live mode: %s", mode)
        return 2

    LOG.error("Unknown command: %r", cmd)
    return 2


# ========= entry points =========

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
        return lambda: _run_cli(())  # callable for tests
    return _run_cli(argv)


if __name__ == "__main__":
    sys.exit(_run_cli(sys.argv[1:]))
