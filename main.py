#!/usr/bin/env python3
"""
Unified entrypoint for running and supervising the EXMO trading bot in Docker/servers.

Subcommands:
  - serve            : run long-lived supervised 'trade-live --mode observe' from a JSON config
  - exmo -- <args>   : proxy into 'python -m src.presentation.cli.app <args...>'
  - healthcheck      : quick EXMO availability check (exit 0 = healthy)
  - generate-config  : emit a config template to a path
  - print-config     : parse & pretty-print an effective config (with env overrides)
  - version          : show versions

Signals (serve):
  - SIGTERM/CTRL+C   : graceful stop (forwards to child, waits)
  - SIGHUP           : reload config, restart child

Environment (serve & healthcheck helpful vars):
  CONFIG_PATH=/config/config.json      # default path to JSON config
  CANDLES_COUNT=2500                   # default history depth for timeframe
  HTTP_RETRIES=5                       # default http retries if not passed by CLI
  HTTP_BACKOFF=0.6                     # default http backoff seconds if not passed by CLI
  DEBUG=1                              # enable debug logging
  SUMMARY_ALERT=1                      # add --summary-alert when running trade-live
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple, List
import subprocess

# ---- logging ----

LOG = logging.getLogger("entry")


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


def _configure_logging(debug_flag: bool) -> None:
    level = logging.DEBUG if (debug_flag or _env_bool("DEBUG")) else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    LOG.debug("Logging configured. Level=%s", logging.getLevelName(level))


# ---- config model ----

@dataclass
class LiveConfig:
    strategy: str
    pair: str
    timeframe: str  # e.g. "5m"
    params: Dict[str, Any]
    poll_sec: int = 10
    heartbeat_sec: int = 60

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "LiveConfig":
        required = ["strategy", "pair", "timeframe", "params"]
        for k in required:
            if k not in d:
                raise ValueError(f"config missing key: {k}")
        if not isinstance(d["params"], dict):
            raise ValueError("config.params must be an object")
        return LiveConfig(
            strategy=str(d["strategy"]),
            pair=str(d["pair"]),
            timeframe=str(d["timeframe"]),
            params=dict(d["params"]),
            poll_sec=int(d.get("poll_sec", 10)),
            heartbeat_sec=int(d.get("heartbeat_sec", 60)),
        )


def _timeframe_to_exmo_candles(tf: str, count: Optional[int]) -> str:
    """
    '5m' -> '5m:COUNT', '1h' -> '60m:COUNT', '1d' -> '1440m:COUNT'
    """
    tf = str(tf).strip().lower()
    if not tf:
        raise ValueError("timeframe is empty")
    num, unit = "", ""
    for ch in tf:
        if ch.isdigit():
            num += ch
        else:
            unit += ch
    if not num or unit not in {"m", "h", "d"}:
        raise ValueError(f"bad timeframe: {tf!r}")
    mult = {"m": 1, "h": 60, "d": 1440}[unit]
    mins = int(num) * mult
    cnt = int(count) if count is not None else _env_int("CANDLES_COUNT", 2500)
    return f"{mins}m:{cnt}"


def _read_config(path: str) -> LiveConfig:
    with open(path, "r", encoding="utf-8") as f:
        obj = json.load(f)
    return LiveConfig.from_dict(obj)


def _effective_config(path: Optional[str], overrides: Dict[str, Any]) -> Tuple[str, LiveConfig]:
    conf_path = path or os.getenv("CONFIG_PATH", "/config/config.json")
    cfg = _read_config(conf_path)
    # apply simple env/CLI overrides if provided (minimal set)
    if "pair" in overrides and overrides["pair"]:
        cfg.pair = overrides["pair"]
    if "timeframe" in overrides and overrides["timeframe"]:
        cfg.timeframe = overrides["timeframe"]
    if "strategy" in overrides and overrides["strategy"]:
        cfg.strategy = overrides["strategy"]
    if "poll_sec" in overrides and overrides["poll_sec"] is not None:
        cfg.poll_sec = int(overrides["poll_sec"])
    if "heartbeat_sec" in overrides and overrides["heartbeat_sec"] is not None:
        cfg.heartbeat_sec = int(overrides["heartbeat_sec"])
    # params override (only keys present in overrides.params)
    if "params" in overrides and isinstance(overrides["params"], dict):
        for k, v in overrides["params"].items():
            if v is not None:
                cfg.params[k] = v
    return conf_path, cfg


# ---- exmo proxy ----

def _run_exmo_passthrough(rest_argv: List[str]) -> int:
    """
    Proxy to src.presentation.cli.app main()
    """
    try:
        from src.presentation.cli import app as exmo_app
    except Exception as e:
        LOG.error("Failed to import src.presentation.cli.app: %s", e)
        return 2
    LOG.debug("exmo passthrough: %s", rest_argv)
    rc = exmo_app.main(rest_argv)
    return int(rc) if isinstance(rc, int) else 0


# ---- healthcheck ----

def _healthcheck(pair: str, timeframe: str, count: Optional[int]) -> int:
    try:
        from src.infrastructure.exchange.exmo_api import build_exmo_from_settings
    except Exception as e:
        LOG.error("Import error: %s", e)
        return 2

    res = 1
    try:
        exmo = build_exmo_from_settings()
        spec = _timeframe_to_exmo_candles(timeframe, count)
        # parse like "5m:2500"
        res_min = int(spec.split(":")[0][:-1])  # drop 'm'
        now = int(time.time())
        since = now - res_min * 60 * 10  # only 10 bars for health
        data = exmo.candles_history(pair, res_min, since, now)
        # basic validation
        candles = data["candles"] if isinstance(data, dict) and "candles" in data else data
        ok = isinstance(candles, list) and len(candles) > 0
        if ok:
            LOG.info("healthcheck ok: pair=%s tf=%s got=%d", pair, timeframe, len(candles))
            res = 0
        else:
            LOG.error("healthcheck failed: empty candles")
            res = 1
    except Exception as e:
        LOG.error("healthcheck exception: %s", e)
        res = 1
    return res


# ---- serve supervisor ----

class _Supervisor:
    def __init__(self, config_path: Optional[str], http_retries: Optional[int], http_backoff: Optional[float],
                 summary_alert: bool, debug: bool):
        self.config_path = config_path
        self.http_retries = http_retries
        self.http_backoff = http_backoff
        self.summary_alert = summary_alert
        self.debug = debug

        self._stop = False
        self._need_reload = False
        self._child: Optional[subprocess.Popen] = None

    def _install_signals(self):
        def _sigterm(_sig, _frm):
            LOG.info("SIGTERM received, stopping...")
            self._stop = True
            self._terminate_child()

        def _sighup(_sig, _frm):
            LOG.info("SIGHUP received, will reload config")
            self._need_reload = True
            self._terminate_child()

        signal.signal(signal.SIGTERM, _sigterm)
        signal.signal(signal.SIGHUP, _sighup)
        signal.signal(signalSIGINT := signal.SIGINT, _sigterm)  # treat Ctrl+C as SIGTERM

    def _terminate_child(self):
        p = self._child
        if not p or p.poll() is not None:
            return
        try:
            LOG.info("sending SIGTERM to child pid=%s", p.pid)
            p.terminate()
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                LOG.warning("child did not exit in 10s, killing...")
                p.kill()
        except Exception as e:
            LOG.error("error terminating child: %s", e)

    def _build_child_cmd(self, cfg: LiveConfig) -> List[str]:
        exmo_candles = _timeframe_to_exmo_candles(cfg.timeframe, None)  # count from env
        cmd = [
            sys.executable, "-m", "src.presentation.cli.app", "trade-live",
            "--mode", "observe",
            "--strategy", cfg.strategy,
            "--exmo-pair", cfg.pair,
            "--exmo-candles", exmo_candles,
            "--poll-sec", str(cfg.poll_sec),
            "--heartbeat-sec", str(cfg.heartbeat_sec),
        ]
        # map params -> CLI
        # supported keys in our app: fast/slow/adx_len/on/off/require_di/atr_len/atr_mult and others if present
        mapping = {
            "fast": "--ema-fast",
            "slow": "--ema-slow",
            "adx_len": "--adx-len",
            "on": "--adx-on",
            "off": "--adx-off",
            "require_di": "--require-di",
            "atr_len": "--atr-len",
            "atr_mult": "--atr-mult",
            "rsi_len": "--rsi-len",
            "low": "--rsi-low",
            "high": "--rsi-high",
            "kc_len": "--kc-len",
            "kc_mult": "--kc-mult",
            "length": "--bb-len",  # for bbands/roc etc (best-effort)
            "mult": "--bb-mult",
        }
        for k, v in cfg.params.items():
            flag = mapping.get(k)
            if not flag or v is None:
                continue
            if isinstance(v, bool):
                if v:
                    cmd.append(flag)
            else:
                cmd.extend([flag, str(v)])

        # summary alert
        if self.summary_alert or _env_bool("SUMMARY_ALERT"):
            cmd.append("--summary-alert")

        # retries/backoff
        if self.http_retries is not None:
            cmd.extend(["--http-retries", str(self.http_retries)])
        if self.http_backoff is not None:
            cmd.extend(["--http-backoff", str(self.http_backoff)])

        if self.debug or _env_bool("DEBUG"):
            cmd.append("--debug")

        return cmd

    def run(self, overrides: Dict[str, Any]) -> int:
        self._install_signals()
        backoff = 1.5
        attempt = 0
        while not self._stop:
            try:
                conf_path, cfg = _effective_config(self.config_path, overrides)
            except Exception as e:
                LOG.error("config load/validate failed: %s", e)
                time.sleep(min(60, 2 + attempt * backoff))
                attempt += 1
                continue

            cmd = self._build_child_cmd(cfg)
            LOG.info("starting child: %s", " ".join(cmd))
            env = os.environ.copy()
            # ensure retries/backoff propagate even if not via CLI (our app also reads ENV)
            if self.http_retries is not None:
                env["HTTP_RETRIES"] = str(self.http_retries)
            if self.http_backoff is not None:
                env["HTTP_BACKOFF"] = str(self.http_backoff)

            self._need_reload = False
            self._child = subprocess.Popen(cmd, env=env)
            rc = None
            try:
                rc = self._child.wait()
            except Exception as e:
                LOG.error("child wait error: %s", e)

            if self._stop:
                LOG.info("stopped. child rc=%s", rc)
                return 0

            if self._need_reload:
                LOG.info("reloading config and restarting child...")
                attempt = 0
                continue

            # unexpected exit — backoff and restart
            LOG.warning("child exited with rc=%s; restarting...", rc)
            sleep = min(60.0, 2.0 + attempt * backoff)
            time.sleep(sleep)
            attempt += 1
        return 0


# ---- CLI ----

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="exmo-bot", description="Supervisor & UX entrypoint for EXMO bot")
    sub = p.add_subparsers(dest="command", metavar="{serve,exmo,healthcheck,generate-config,print-config,version}")

    # serve
    ps = sub.add_parser("serve", help="Run supervised live observe from a config")
    ps.add_argument("--config", type=str, default=None, help="Path to JSON config (default: $CONFIG_PATH or /config/config.json)")
    ps.add_argument("--pair", type=str, default=None, help="Override pair from config")
    ps.add_argument("--timeframe", type=str, default=None, help="Override timeframe (e.g. 5m)")
    ps.add_argument("--poll-sec", type=int, default=None, help="Override poll interval")
    ps.add_argument("--heartbeat-sec", type=int, default=None, help="Override heartbeat interval")
    # small param overrides (optional)
    ps.add_argument("--ema-fast", type=int, default=None)
    ps.add_argument("--ema-slow", type=int, default=None)
    ps.add_argument("--adx-len", type=int, default=None)
    ps.add_argument("--adx-on", type=float, default=None)
    ps.add_argument("--adx-off", type=float, default=None)
    ps.add_argument("--require-di", action="store_true")
    ps.add_argument("--no-require-di", action="store_true")
    ps.add_argument("--atr-len", type=int, default=None)
    ps.add_argument("--atr-mult", type=float, default=None)
    # network hardening
    ps.add_argument("--http-retries", type=int, default=None, help="Override HTTP_RETRIES")
    ps.add_argument("--http-backoff", type=float, default=None, help="Override HTTP_BACKOFF (sec)")
    ps.add_argument("--summary-alert", action="store_true", help="Force summary-alert on child")
    ps.add_argument("--debug", action="store_true")

    # exmo passthrough
    px = sub.add_parser("exmo", help="Proxy to src.presentation.cli.app")
    px.add_argument("rest", nargs=argparse.REMAINDER, help="Arguments after '--' are passed to exmo CLI")
    # usage: python main.py exmo -- backtest --strategy sma ...

    # healthcheck
    ph = sub.add_parser("healthcheck", help="Basic EXMO connectivity check")
    ph.add_argument("--pair", type=str, default=os.getenv("PAIR", "DOGE_EUR"))
    ph.add_argument("--timeframe", type=str, default=os.getenv("TIMEFRAME", "5m"))
    ph.add_argument("--count", type=int, default=_env_int("CANDLES_COUNT", 2500))

    # generate-config
    pg = sub.add_parser("generate-config", help="Generate a config template")
    pg.add_argument("--out", type=str, required=True)

    # print-config
    pp = sub.add_parser("print-config", help="Load and print effective config")
    pp.add_argument("--config", type=str, default=None)

    # version
    sub.add_parser("version", help="Show versions")

    p.add_argument("--debug", action="store_true", help="Debug logs for this entrypoint")
    return p


def _overrides_from_args(args: argparse.Namespace) -> Dict[str, Any]:
    params = {
        "fast": args.ema_fast,
        "slow": args.ema_slow,
        "adx_len": args.adx_len,
        "on": args.adx_on,
        "off": args.adx_off,
        "require_di": (False if getattr(args, "no_require_di", False) else (True if getattr(args, "require_di", False) else None)),
        "atr_len": args.atr_len,
        "atr_mult": args.atr_mult,
    }
    # remove None
    params = {k: v for k, v in params.items() if v is not None}
    return {
        "pair": getattr(args, "pair", None),
        "timeframe": getattr(args, "timeframe", None),
        "poll_sec": getattr(args, "poll_sec", None),
        "heartbeat_sec": getattr(args, "heartbeat_sec", None),
        "params": params,
    }


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(args.debug)

    cmd = args.command
    if not cmd:
        parser.print_help()
        return 0

    if cmd == "exmo":
        # strip leading '--' if present
        rest = args.rest
        if rest and rest[0] == "--":
            rest = rest[1:]
        return _run_exmo_passthrough(rest)

    if cmd == "healthcheck":
        return _healthcheck(args.pair, args.timeframe, args.count)

    if cmd == "generate-config":
        template = {
            "strategy": "ema_adx",
            "pair": "DOGE_EUR",
            "timeframe": "5m",
            "params": { "fast": 12, "slow": 21, "adx_len": 14, "on": 25, "off": 16, "require_di": True },
            "poll_sec": 10,
            "heartbeat_sec": 60
        }
        out = args.out
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(template, f, ensure_ascii=False, indent=2)
        LOG.info("config template written -> %s", out)
        return 0

    if cmd == "print-config":
        path, cfg = _effective_config(args.config, {})
        LOG.info("config path: %s", path)
        print(json.dumps({
            "strategy": cfg.strategy,
            "pair": cfg.pair,
            "timeframe": cfg.timeframe,
            "params": cfg.params,
            "poll_sec": cfg.poll_sec,
            "heartbeat_sec": cfg.heartbeat_sec
        }, ensure_ascii=False, indent=2))
        return 0

    if cmd == "version":
        import platform
        try:
            import src  # type: ignore
            pkg = getattr(src, "__version__", "unknown")
        except Exception:
            pkg = "unknown"
        print(json.dumps({
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "package_version": pkg
        }, indent=2))
        return 0

    if cmd == "serve":
        overrides = _overrides_from_args(args)
        sup = _Supervisor(
            config_path=args.config,
            http_retries=args.http_retries if args.http_retries is not None else _env_int("HTTP_RETRIES", 5),
            http_backoff=args.http_backoff if args.http_backoff is not None else _env_float("HTTP_BACKOFF", 0.6),
            summary_alert=bool(args.summary_alert),
            debug=bool(args.debug),
        )
        return sup.run(overrides)

    parser.error(f"unknown command: {cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
