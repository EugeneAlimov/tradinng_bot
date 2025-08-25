# src/monitoring/monitor.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Callable, Deque, List
from datetime import datetime, timedelta
from enum import Enum
from collections import deque
import threading
import time
import logging
import json
import http.server
import socketserver

logger = logging.getLogger(__name__)


class AlertSeverity(Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class MetricType(Enum):
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"


@dataclass
class Metric:
    name: str
    type: MetricType
    value: float = 0.0
    labels: Dict[str, str] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class Alert:
    severity: AlertSeverity
    title: str
    message: str
    metric: Optional[str] = None
    value: Optional[float] = None
    timestamp: datetime = field(default_factory=datetime.now)
    resolved: bool = False


class HealthCheck:
    def __init__(self, name: str, check_fn: Callable[[], bool], interval: int = 60):
        self.name = name
        self.check_fn = check_fn
        self.interval = interval
        self.last_check: Optional[datetime] = None
        self.is_healthy: bool = True
        self.error_count: int = 0
        self.last_error: Optional[str] = None


class MonitoringSystem:
    def __init__(
            self,
            bot_name: str = "tradinng_bot",
            alert_email: Optional[str] = None,
            telegram_token: Optional[str] = None,
            telegram_chat_id: Optional[str] = None,
            metrics_http_bind: Optional[str] = None,  # "127.0.0.1:9103"
    ):
        self.bot_name = bot_name
        self.alert_email = alert_email
        self.telegram_token = telegram_token
        self.telegram_chat_id = telegram_chat_id

        self.metrics: Dict[str, Metric] = {}
        self.metrics_history: Dict[str, Deque] = {}
        self.max_hist = 1000

        self.alerts: List[Alert] = []
        self.alert_rules: List[Dict[str, Any]] = []
        self.health: Dict[str, HealthCheck] = {}
        self.stats = {
            "start_time": datetime.now(),
            "total_trades": 0,
            "successful_trades": 0,
            "failed_trades": 0,
            "total_errors": 0,
            "last_error": None,
            "uptime_seconds": 0.0,
        }

        self._start_monitoring_thread()
        if metrics_http_bind:
            self._start_metrics_http(metrics_http_bind)

    # ---------- Metrics ----------
    def record_metric(self, name: str, value: float, mtype: MetricType = MetricType.GAUGE,
                      labels: Optional[Dict[str, str]] = None):
        m = Metric(name=name, type=mtype, value=value, labels=labels or {})
        self.metrics[name] = m
        if name not in self.metrics_history:
            self.metrics_history[name] = deque(maxlen=self.max_hist)
        self.metrics_history[name].append((m.timestamp, value))
        self._check_rules(m)

    def record_trade(self, pair: str, side: str, quantity: float, price: float,
                     pnl: Optional[float] = None, success: bool = True):
        self.stats["total_trades"] += 1
        if success:
            self.stats["successful_trades"] += 1
        else:
            self.stats["failed_trades"] += 1
        self.record_metric("trades_total", float(self.stats["total_trades"]), MetricType.COUNTER)
        self.record_metric("trade_volume", float(quantity * price), MetricType.GAUGE, {"pair": pair, "side": side})
        if pnl is not None:
            self.record_metric("trade_pnl", float(pnl), MetricType.GAUGE, {"pair": pair})
            if pnl < -100.0:
                self.create_alert(AlertSeverity.WARNING, "Large Loss", f"{pair}: loss {pnl:.2f} EUR",
                                  metric="trade_pnl", value=float(pnl))

    def record_error(self, error_type: str, error_msg: str, critical: bool = False):
        self.stats["total_errors"] += 1
        self.stats["last_error"] = {"type": error_type, "message": error_msg, "ts": datetime.now().isoformat()}
        self.record_metric("errors_total", float(self.stats["total_errors"]), MetricType.COUNTER, {"type": error_type})
        self.create_alert(AlertSeverity.CRITICAL if critical else AlertSeverity.ERROR,
                          f"Error: {error_type}", error_msg)

    def add_health_check(self, name: str, check_fn: Callable[[], bool], interval: int = 60):
        self.health[name] = HealthCheck(name, check_fn, interval)

    def add_alert_rule(self, metric: str, condition: str, threshold: float,
                       severity: AlertSeverity, message_tmpl: str):
        self.alert_rules.append({
            "metric": metric, "condition": condition, "threshold": threshold,
            "severity": severity, "message_template": message_tmpl
        })

    def create_alert(self, severity: AlertSeverity, title: str, message: str,
                     metric: Optional[str] = None, value: Optional[float] = None):
        al = Alert(severity=severity, title=title, message=message, metric=metric, value=value)
        self.alerts.append(al)
        # отправка — только Telegram (email — за пределами этой версии)
        if self.telegram_token and self.telegram_chat_id:
            self._send_telegram(al)
        logger.warning("ALERT [%s] %s: %s", severity.value, title, message)

    def _check_rules(self, metric: Metric) -> None:
        for r in self.alert_rules:
            if r["metric"] != metric.name:
                continue
            cond = r["condition"]
            thr = r["threshold"]
            val = metric.value
            fired = (cond == "gt" and val > thr) or (cond == "lt" and val < thr) or (cond == "eq" and val == thr)
            if fired:
                msg = r["message_template"].format(metric=metric.name, value=val, threshold=thr)
                self.create_alert(r["severity"], f"Metric: {metric.name}", msg, metric=metric.name, value=val)

    # ---------- Background ----------
    def _start_monitoring_thread(self) -> None:
        def loop():
            while True:
                try:
                    self.stats["uptime_seconds"] = (datetime.now() - self.stats["start_time"]).total_seconds()
                    for name, hc in self.health.items():
                        if hc.last_check is None or (datetime.now() - hc.last_check).total_seconds() >= hc.interval:
                            try:
                                ok = hc.check_fn()
                                hc.is_healthy = ok
                                hc.last_check = datetime.now()
                                if not ok:
                                    hc.error_count += 1
                                    if hc.error_count == 1:
                                        self.create_alert(AlertSeverity.WARNING, f"Health Failed: {name}",
                                                          f"{name} unhealthy")
                                else:
                                    if hc.error_count > 0:
                                        self.create_alert(AlertSeverity.INFO, f"Health Recovered: {name}",
                                                          f"{name} healthy again")
                                    hc.error_count = 0
                            except Exception as e:
                                hc.is_healthy = False
                                hc.last_error = str(e)
                                hc.error_count += 1
                    time.sleep(10)
                except Exception as e:
                    logger.error("monitor loop error: %s", e)
                    time.sleep(30)

        t = threading.Thread(target=loop, daemon=True)
        t.start()

    # ---------- Telegram ----------
    def _send_telegram(self, alert: Alert):
        try:
            import requests  # optional dep
            emoji = {
                AlertSeverity.INFO: "ℹ️",
                AlertSeverity.WARNING: "⚠️",
                AlertSeverity.ERROR: "🔴",
                AlertSeverity.CRITICAL: "🚨",
            }
            text = f"{emoji.get(alert.severity, '')} *{alert.title}*\n\n{alert.message}"
            if alert.metric and alert.value is not None:
                text += f"\n\n`{alert.metric}` = `{alert.value}`"
            url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
            requests.post(url, json={"chat_id": self.telegram_chat_id, "text": text, "parse_mode": "Markdown"})
        except Exception as e:
            logger.error("telegram notify failed: %s", e)

    # ---------- /metrics ----------
    def _start_metrics_http(self, bind: str):
        host, port_s = bind.split(":", 1)
        port = int(port_s)
        system = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # type: ignore
                if self.path != "/metrics":
                    self.send_response(404)
                    self.end_headers()
                    return
                body = system.export_prometheus().encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args, **kwargs):  # silence
                return

        def serve():
            with socketserver.TCPServer((host, port), Handler) as httpd:
                logger.info("metrics http at http://%s:%d/metrics", host, port)
                httpd.serve_forever()

        t = threading.Thread(target=serve, daemon=True)
        t.start()

    def export_prometheus(self) -> str:
        lines = []
        for name, m in self.metrics.items():
            labels = ",".join(f'{k}="{v}"' for k, v in m.labels.items())
            if labels:
                lines.append(f"{name}{{{labels}}} {m.value}")
            else:
                lines.append(f"{name} {m.value}")
        return "\n".join(lines)

    def get_status(self) -> Dict[str, Any]:
        health_status = {
            name: {
                "healthy": hc.is_healthy,
                "last_check": hc.last_check.isoformat() if hc.last_check else None,
                "error_count": hc.error_count,
            } for name, hc in self.health.items()
        }
        recent_alerts = [{"severity": a.severity.value, "title": a.title, "ts": a.timestamp.isoformat()}
                         for a in self.alerts[-10:]]
        return {
            "bot_name": self.bot_name,
            "uptime_sec": self.stats["uptime_seconds"],
            "health": health_status,
            "stats": {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in self.stats.items()},
            "recent_alerts": recent_alerts,
            "metrics_count": len(self.metrics),
        }
