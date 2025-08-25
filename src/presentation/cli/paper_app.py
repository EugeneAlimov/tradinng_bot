# src/presentation/cli/paper_app.py
from __future__ import annotations

import argparse, logging, os, sys, time
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from src.application.live.paper import PaperEngine, PaperConfig
from src.application.live.state_store import StateStore
from src.infrastructure.exmo_cache import fetch_with_cache
from src.infrastructure.exchange.exmo_api import build_exmo_from_settings
from src.application.research.strategies import strat_registry  # твой реестр стратегий
from src.application.research.selector import _call_with_supported  # уже есть в проекте (хелпер)
from src.presentation.cli.app import _parse_exmo_candles, _save_trades_csv, _save_equity_csv  # переиспользуем

try:
    from src.infrastructure.notify.telegram import TelegramNotifier  # если есть
except Exception:
    TelegramNotifier = None  # type: ignore

LOG = logging.getLogger("paper")


def _configure_logging(debug: bool):
    level = logging.DEBUG if debug or os.getenv("DEBUG") else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    LOG.debug("Logging configured. Level=%s", logging.getLevelName(level))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="paper", description="Paper trading runner with resume & cache")
    p.add_argument("--strategy", required=True)
    p.add_argument("--exmo-pair", required=True)
    p.add_argument("--exmo-candles", required=True, help="e.g. 5m:2500")
    # strategy params (часть — общие для EMA/ADX/ATR и т.п.)
    p.add_argument("--ema-fast", type=int)
    p.add_argument("--ema-slow", type=int)
    p.add_argument("--adx-len", type=int)
    p.add_argument("--adx-on", type=float)
    p.add_argument("--adx-off", type=float)
    p.add_argument("--require-di", action="store_true")
    p.add_argument("--no-require-di", action="store_true")
    p.add_argument("--atr-len", type=int)
    p.add_argument("--atr-mult", type=float)

    p.add_argument("--poll-sec", type=int, default=10)
    p.add_argument("--heartbeat-sec", type=int, default=60)

    # paper config
    p.add_argument("--initial-balance", type=float, default=1000.0)
    p.add_argument("--fee-bps", type=int, default=10)
    p.add_argument("--slip-bps", type=int, default=2)
    p.add_argument("--max-position-pct", type=float, default=0.25)
    p.add_argument("--stop-loss-bps", type=int, default=300)
    p.add_argument("--max-daily-loss-bps", type=int, default=0)

    # resume
    p.add_argument("--state-file", type=str, default="out/paper_state.json")

    # outputs
    p.add_argument("--csv-trades", type=str, default="out/paper_trades.csv")
    p.add_argument("--csv-equity", type=str, default="out/paper_equity.csv")

    # notifier
    p.add_argument("--summary-alert", action="store_true")
    p.add_argument("--debug", action="store_true")
    return p


def _params_from_args(args: argparse.Namespace) -> Dict[str, Any]:
    params = {
        "fast": args.ema_fast,
        "slow": args.ema_slow,
        "adx_len": args.adx_len,
        "on": args.adx_on,
        "off": args.adx_off,
        "require_di": (
            False if getattr(args, "no_require_di", False) else (True if getattr(args, "require_di", False) else None)),
        "atr_len": args.atr_len,
        "atr_mult": args.atr_mult,
    }
    return {k: v for k, v in params.items() if v is not None}


def _fetch_ohlc(pair: str, res_min: int, count: int) -> Dict[str, List[float]]:
    exmo = build_exmo_from_settings()
    now = int(time.time())
    since = now - res_min * 60 * count
    data = fetch_with_cache(exmo, pair, res_min, since, now)
    candles = data["candles"] if isinstance(data, dict) else data
    # ожидается список dict с ключами 't','o','h','l','c' или похожими — ориентируемся на используемые поля проекта
    ts = [int(x["t"]) for x in candles]
    op = [float(x["o"]) for x in candles]
    hi = [float(x["h"]) for x in candles]
    lo = [float(x["l"]) for x in candles]
    cl = [float(x["c"]) for x in candles]
    return {"ts": ts, "open": op, "high": hi, "low": lo, "close": cl}


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(args.debug)

    strat_name = args.strategy
    defn = strat_registry.get(strat_name)
    if defn is None:
        LOG.error("Unknown strategy: %s", strat_name)
        return 2
    params = _params_from_args(args)

    res_min, count = _parse_exmo_candles(args.exmo_candles)

    # state
    store = StateStore(args.state_file)
    snapshot = store.load()

    # engine
    cfg = PaperConfig(
        initial_balance=args.initial_balance,
        fee_bps=args.fee_bps,
        slip_bps=args.slip_bps,
        max_position_pct=args.max_position_pct,
        stop_loss_bps=args.stop_loss_bps,
        max_daily_loss_bps=(args.max_daily_loss_bps or None),
    )
    # risk сервис из проекта
    from src.application.core.engine_integration import EngineIntegration
    from src.application.core.position import PnLCalculator
    from src.infrastructure.logger import get_logger
    integration = EngineIntegration(logger=get_logger("paper"))

    engine = PaperEngine(cfg, integration.risk, snapshot=snapshot)

    # notifier
    notifier = None
    if args.summary_alert and TelegramNotifier is not None:
        try:
            notifier = TelegramNotifier.from_env()
        except Exception:
            notifier = None

    LOG.info("[paper] %s %s strategy=%s params=%s poll=%ds",
             args.exmo_pair, args.exmo_candles, strat_name, params, args.poll_sec)

    last_closed_ts: Optional[int] = None
    last_state_for_msg: Optional[int] = None
    last_hb = 0.0

    try:
        while True:
            try:
                ohlc = _fetch_ohlc(args.exmo_pair, res_min, count)
            except Exception as e:
                LOG.error("[paper] fetch error: %s", e)
                time.sleep(args.poll_sec)
                continue

            ts = ohlc["ts"];
            o = ohlc["open"];
            h = ohlc["high"];
            l = ohlc["low"];
            c = ohlc["close"]
            if len(ts) < 2:
                time.sleep(args.poll_sec);
                continue

            i_closed = len(ts) - 2
            ts_closed = ts[i_closed]
            if last_closed_ts is not None and ts_closed <= last_closed_ts:
                time.sleep(args.poll_sec);
                continue

            # signals
            signals = _call_with_supported(defn.generate_signals,
                                           arrays={"ts": ts, "open": o, "high": h, "low": l, "close": c},
                                           extra_params=params)
            sig = int(signals[i_closed]) if isinstance(signals, list) and len(signals) > i_closed else 0
            status_text, _ = _call_with_supported(defn.status,
                                                  arrays={"ts": ts, "open": o, "high": h, "low": l, "close": c},
                                                  extra_params=params)

            changed = engine.on_new_closed_bar(ts_closed, o[i_closed], h[i_closed], l[i_closed], c[i_closed], sig)

            t_iso = datetime.fromtimestamp(ts_closed, tz=timezone.utc).isoformat()
            LOG.info("[paper] %s close=%.6f sig=%+d %s", t_iso, c[i_closed], sig, status_text)

            # save snapshot раз в тик (дёшево и безопасно)
            try:
                store.save(engine.snapshot())
            except Exception:
                pass

            # сообщения
            if notifier:
                if changed is not None:
                    state_change, equity = changed
                    if state_change != 0 or last_state_for_msg != state_change:
                        arrow = "🟢 BUY" if state_change == +1 else ("🔴 SELL" if state_change == -1 else "⏸ HOLD")
                        msg = (f"<b>Paper {args.exmo_pair}</b> {args.exmo_candles} [{strat_name}]\n"
                               f"{arrow} close={c[i_closed]:.6f}\n"
                               f"{status_text}\n"
                               f"equity={equity:.4f} params={params}")
                        try:
                            notifier.send(msg)
                        except Exception:
                            pass
                        last_state_for_msg = state_change

                now_mono = time.monotonic()
                if (now_mono - last_hb) >= max(5, args.heartbeat_sec):
                    eq = engine.export_equity()[-1][1] if engine.export_equity() else 0.0
                    try:
                        notifier.send(f"✅ paper ok {args.exmo_pair} eq={eq:.4f} {status_text}")
                    except Exception:
                        pass
                    last_hb = now_mono

            last_closed_ts = ts_closed
            time.sleep(args.poll_sec)

    except KeyboardInterrupt:
        LOG.info("[paper] stop by user")
        try:
            store.save(engine.snapshot())
        except Exception:
            pass
        # CSV выгрузка
        try:
            os.makedirs(os.path.dirname(args.csv_trades) or ".", exist_ok=True)
            os.makedirs(os.path.dirname(args.csv_equity) or ".", exist_ok=True)
            _save_trades_csv(args.csv_trades, engine.export_trades())
            _save_equity_csv(args.csv_equity, engine.export_equity())
            LOG.info("Saved trades -> %s; equity -> %s", args.csv_trades, args.csv_equity)
        except Exception as e:
            LOG.warning("CSV save failed: %s", e)
        return 0


if __name__ == "__main__":
    sys.exit(main())
