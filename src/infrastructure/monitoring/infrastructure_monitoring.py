#!/usr/bin/env python3
"""📊 Инфраструктурный слой - Система мониторинга и метрик"""

import time
import asyncio
import logging
import psutil
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Callable, Union
from datetime import datetime, timedelta
from collections import defaultdict, deque
from enum import Enum
from pathlib import Path
import json

from ..core.interfaces import IMonitoringService, INotificationService
from ..core.models import TradingPair
from ..core.exceptions import MonitoringError
from ..core.constants import Timing


class MetricType(Enum):
    """📈 Типы метрик"""
    COUNTER = "counter"      # Счетчик (только растет)
    GAUGE = "gauge"          # Измеритель (может расти и падать)
    HISTOGRAM = "histogram"  # Гистограмма (распределение значений)
    TIMER = "timer"          # Таймер (время выполнения)


class AlertLevel(Enum):
    """🚨 Уровни алертов"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class MetricValue:
    """📊 Значение метрики"""
    value: Union[int, float]
    timestamp: datetime = field(default_factory=datetime.now)
    tags: Dict[str, str] = field(default_factory=dict)
    
    def __post_init__(self):
        if isinstance(self.timestamp, str):
            self.timestamp = datetime.fromisoformat(self.timestamp)


@dataclass
class Alert:
    """🚨 Алерт"""
    id: str
    level: AlertLevel
    message: str
    metric_name: str
    value: float
    threshold: float
    timestamp: datetime = field(default_factory=datetime.now)
    resolved: bool = False
    resolved_at: Optional[datetime] = None
    
    def resolve(self) -> None:
        """✅ Разрешение алерта"""
        self.resolved = True
        self.resolved_at = datetime.now()


@dataclass
class SystemMetrics:
    """🖥️ Системные метрики"""
    cpu_percent: float
    memory_percent: float
    memory_available_mb: float
    disk_usage_percent: float
    disk_free_gb: float
    network_sent_mb: float
    network_recv_mb: float
    process_count: int
    uptime_seconds: float
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class TradingMetrics:
    """💱 Торговые метрики"""
    total_trades: int = 0
    successful_trades: int = 0
    failed_trades: int = 0
    total_profit: float = 0.0
    total_loss: float = 0.0
    win_rate: float = 0.0
    average_profit: float = 0.0
    average_loss: float = 0.0
    max_drawdown: float = 0.0
    current_balance: float = 0.0
    active_positions: int = 0
    api_calls_count: int = 0
    api_errors_count: int = 0
    last_trade_time: Optional[datetime] = None
    timestamp: datetime = field(default_factory=datetime.now)


class MetricCollector:
    """📈 Сборщик метрик"""
    
    def __init__(self, max_history: int = 10000):
        self.max_history = max_history
        
        # Хранилища метрик
        self._counters: Dict[str, float] = defaultdict(float)
        self._gauges: Dict[str, float] = {}
        self._histograms: Dict[str, deque] = defaultdict(lambda: deque(maxlen=max_history))