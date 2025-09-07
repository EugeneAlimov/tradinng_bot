# src/monitoring/monitor.py
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
from enum import Enum

LOG = logging.getLogger(__name__)


class AlertSeverity(Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class HealthCheck:
    name: str
    check_func: Callable[[], bool]
    interval: int = 30  # seconds
    last_run: float = field(default_factory=time.time)
    status: bool = True


@dataclass
class Alert:
    severity: AlertSeverity
    title: str
    message: str
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)


class MonitoringSystem:
    """
    Простая система мониторинга с health checks и алертами
    """

    def __init__(self, bot_name: str = "trading_bot"):
        self.bot_name = bot_name
        self.health_checks: Dict[str, HealthCheck] = {}
        self.alerts: List[Alert] = []
        self.metrics: Dict[str, Any] = {}
        self.enabled = True

    def add_health_check(self, name: str, check_func: Callable[[], bool], interval: int = 30) -> None:
        """Добавляет health check"""
        if not self.enabled:
            return

        self.health_checks[name] = HealthCheck(
            name=name,
            check_func=check_func,
            interval=interval
        )
        LOG.debug(f"[monitor] Added health check: {name}")

    def remove_health_check(self, name: str) -> None:
        """Удаляет health check"""
        if name in self.health_checks:
            del self.health_checks[name]
            LOG.debug(f"[monitor] Removed health check: {name}")

    def run_health_checks(self) -> Dict[str, bool]:
        """Запускает все health checks"""
        results = {}
        current_time = time.time()

        for name, check in self.health_checks.items():
            if current_time - check.last_run >= check.interval:
                try:
                    result = check.check_func()
                    check.status = result
                    check.last_run = current_time
                    results[name] = result

                    if not result:
                        self.record_alert(
                            AlertSeverity.WARNING,
                            f"Health check failed: {name}",
                            f"Health check '{name}' returned False"
                        )

                except Exception as e:
                    check.status = False
                    check.last_run = current_time
                    results[name] = False

                    self.record_alert(
                        AlertSeverity.ERROR,
                        f"Health check error: {name}",
                        f"Health check '{name}' raised exception: {e}"
                    )

            else:
                results[name] = check.status

        return results

    def record_metric(self, name: str, value: Any) -> None:
        """Записывает метрику"""
        if not self.enabled:
            return

        self.metrics[name] = {
            "value": value,
            "timestamp": time.time()
        }
        LOG.debug(f"[monitor] Metric {name} = {value}")

    def record_alert(self, severity: AlertSeverity, title: str, message: str, **metadata) -> None:
        """Записывает алерт"""
        if not self.enabled:
            return

        alert = Alert(
            severity=severity,
            title=title,
            message=message,
            metadata=metadata
        )

        self.alerts.append(alert)

        # Ограничиваем количество алертов в памяти
        if len(self.alerts) > 1000:
            self.alerts = self.alerts[-500:]

        LOG.info(f"[monitor] {severity.value.upper()}: {title} - {message}")

    def record_error(self, error_type: str, error_msg: str, critical: bool = False) -> None:
        """Записывает ошибку как алерт"""
        severity = AlertSeverity.CRITICAL if critical else AlertSeverity.ERROR
        self.record_alert(
            severity,
            f"Error: {error_type}",
            error_msg
        )

    def get_health_status(self) -> Dict[str, Any]:
        """Возвращает текущий статус здоровья системы"""
        health_results = self.run_health_checks()

        return {
            "bot_name": self.bot_name,
            "timestamp": time.time(),
            "overall_healthy": all(health_results.values()) if health_results else True,
            "health_checks": health_results,
            "recent_alerts": self.alerts[-10:],  # Последние 10 алертов
            "metrics_count": len(self.metrics)
        }

    def get_metrics(self) -> Dict[str, Any]:
        """Возвращает все метрики"""
        return dict(self.metrics)

    def get_alerts(self, severity: Optional[AlertSeverity] = None, limit: int = 100) -> List[Alert]:
        """Возвращает алерты (опционально отфильтрованные по severity)"""
        alerts = self.alerts

        if severity:
            alerts = [a for a in alerts if a.severity == severity]

        return alerts[-limit:]

    def clear_alerts(self) -> None:
        """Очищает все алерты"""
        self.alerts.clear()
        LOG.debug("[monitor] Alerts cleared")

    def disable(self) -> None:
        """Отключает мониторинг"""
        self.enabled = False
        LOG.debug("[monitor] Monitoring disabled")

    def enable(self) -> None:
        """Включает мониторинг"""
        self.enabled = True
        LOG.debug("[monitor] Monitoring enabled")


# Для обратной совместимости
@dataclass
class Monitor:
    name: str = "default"
    enabled: bool = True

    def start(self) -> None:
        LOG.debug("[monitor] start %s", self.name)

    def stop(self) -> None:
        LOG.debug("[monitor] stop %s", self.name)

    def event(self, title: str, text: Optional[str] = None) -> None:
        LOG.info("[monitor] %s: %s", title, text or "")
