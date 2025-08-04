#!/usr/bin/env python3
"""🛠️ Утилиты для адаптеров"""

import asyncio
import logging
from typing import Any, Dict, List, Optional, Callable
from datetime import datetime, timedelta
from pathlib import Path


class AdapterRegistry:
    """📋 Реестр адаптеров"""
    
    def __init__(self):
        self._adapters: Dict[str, Any] = {}
        self._metadata: Dict[str, Dict[str, Any]] = {}
        self.logger = logging.getLogger(f"{__name__}.AdapterRegistry")
    
    def register(self, name: str, adapter: Any, metadata: Optional[Dict[str, Any]] = None) -> None:
        """📝 Регистрация адаптера"""
        self._adapters[name] = adapter
        self._metadata[name] = metadata or {}
        self._metadata[name]['registered_at'] = datetime.now().isoformat()
        
        self.logger.info(f"📝 Адаптер зарегистрирован: {name}")
    
    def unregister(self, name: str) -> bool:
        """🗑️ Удаление адаптера из реестра"""
        if name in self._adapters:
            del self._adapters[name]
            del self._metadata[name]
            self.logger.info(f"🗑️ Адаптер удален: {name}")
            return True
        return False
    
    def get(self, name: str) -> Optional[Any]:
        """🔍 Получение адаптера по имени"""
        return self._adapters.get(name)
    
    def list_adapters(self) -> List[str]:
        """📋 Список зарегистрированных адаптеров"""
        return list(self._adapters.keys())
    
    def get_metadata(self, name: str) -> Dict[str, Any]:
        """📊 Получение метаданных адаптера"""
        return self._metadata.get(name, {})


class AdapterHealthChecker:
    """🏥 Проверка здоровья адаптеров"""
    
    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.AdapterHealthChecker")
        self._health_checks: Dict[str, Callable] = {}
        self._last_check: Dict[str, datetime] = {}
        self._check_results: Dict[str, Dict[str, Any]] = {}
    
    def register_health_check(self, adapter_name: str, check_func: Callable) -> None:
        """📝 Регистрация проверки здоровья"""
        self._health_checks[adapter_name] = check_func
        self.logger.info(f"📝 Проверка здоровья зарегистрирована для: {adapter_name}")
    
    async def check_adapter_health(self, adapter_name: str) -> Dict[str, Any]:
        """🏥 Проверка здоровья конкретного адаптера"""
        if adapter_name not in self._health_checks:
            return {'status': 'unknown', 'reason': 'No health check registered'}
        
        try:
            check_func = self._health_checks[adapter_name]
            
            # Выполняем проверку с таймаутом
            result = await asyncio.wait_for(
                self._safe_execute_check(check_func),
                timeout=10.0
            )
            
            health_result = {
                'status': 'healthy' if result.get('success', False) else 'unhealthy',
                'timestamp': datetime.now().isoformat(),
                'details': result,
                'adapter': adapter_name
            }
            
            self._last_check[adapter_name] = datetime.now()
            self._check_results[adapter_name] = health_result
            
            return health_result
            
        except asyncio.TimeoutError:
            health_result = {
                'status': 'timeout',
                'timestamp': datetime.now().isoformat(),
                'reason': 'Health check timed out',
                'adapter': adapter_name
            }
            
            self._check_results[adapter_name] = health_result
            return health_result
            
        except Exception as e:
            health_result = {
                'status': 'error',
                'timestamp': datetime.now().isoformat(),
                'error': str(e),
                'adapter': adapter_name
            }
            
            self._check_results[adapter_name] = health_result
            return health_result
    
    async def _safe_execute_check(self, check_func: Callable) -> Dict[str, Any]:
        """🛡️ Безопасное выполнение проверки"""
        try:
            if asyncio.iscoroutinefunction(check_func):
                return await check_func()
            else:
                return check_func()
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    async def check_all_adapters(self) -> Dict[str, Dict[str, Any]]:
        """🏥 Проверка здоровья всех адаптеров"""
        results = {}
        
        for adapter_name in self._health_checks.keys():
            results[adapter_name] = await self.check_adapter_health(adapter_name)
        
        return results
    
    def get_last_check_time(self, adapter_name: str) -> Optional[datetime]:
        """⏰ Время последней проверки"""
        return self._last_check.get(adapter_name)
    
    def get_check_result(self, adapter_name: str) -> Dict[str, Any]:
        """📊 Результат последней проверки"""
        return self._check_results.get(adapter_name, {})


class AdapterMetrics:
    """📊 Метрики адаптеров"""
    
    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.AdapterMetrics")
        self._metrics: Dict[str, List[Dict[str, Any]]] = {}
        self._start_times: Dict[str, datetime] = {}
    
    def start_cycle(self, adapter_name: str) -> None:
        """🚀 Начало цикла адаптера"""
        self._start_times[adapter_name] = datetime.now()
    
    def end_cycle(self, adapter_name: str, success: bool = True, **kwargs) -> None:
        """🏁 Конец цикла адаптера"""
        if adapter_name not in self._start_times:
            self.logger.warning(f"⚠️ Не найдено время начала для {adapter_name}")
            return
        
        start_time = self._start_times[adapter_name]
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        metric = {
            'timestamp': end_time.isoformat(),
            'duration_seconds': duration,
            'success': success,
            **kwargs
        }
        
        if adapter_name not in self._metrics:
            self._metrics[adapter_name] = []
        
        self._metrics[adapter_name].append(metric)
        
        # Ограничиваем количество метрик
        if len(self._metrics[adapter_name]) > 1000:
            self._metrics[adapter_name] = self._metrics[adapter_name][-1000:]
        
        del self._start_times[adapter_name]
    
    def get_metrics(self, adapter_name: str, hours: int = 24) -> List[Dict[str, Any]]:
        """📊 Получение метрик адаптера"""
        if adapter_name not in self._metrics:
            return []
        
        cutoff_time = datetime.now() - timedelta(hours=hours)
        
        return [
            metric for metric in self._metrics[adapter_name]
            if datetime.fromisoformat(metric['timestamp']) >= cutoff_time
        ]
    
    def get_summary(self, adapter_name: str, hours: int = 24) -> Dict[str, Any]:
        """📈 Сводка по метрикам"""
        metrics = self.get_metrics(adapter_name, hours)
        
        if not metrics:
            return {'total_cycles': 0, 'no_data': True}
        
        durations = [m['duration_seconds'] for m in metrics]
        successful_cycles = sum(1 for m in metrics if m['success'])
        
        return {
            'total_cycles': len(metrics),
            'successful_cycles': successful_cycles,
            'success_rate': successful_cycles / len(metrics),
            'avg_duration': sum(durations) / len(durations),
            'min_duration': min(durations),
            'max_duration': max(durations),
            'period_hours': hours
        }


# Глобальные экземпляры утилит
adapter_registry = AdapterRegistry()
adapter_health_checker = AdapterHealthChecker()
adapter_metrics = AdapterMetrics()


def get_adapter_registry() -> AdapterRegistry:
    """📋 Получение глобального реестра адаптеров"""
    return adapter_registry


def get_health_checker() -> AdapterHealthChecker:
    """🏥 Получение глобального чекера здоровья"""
    return adapter_health_checker


def get_metrics_collector() -> AdapterMetrics:
    """📊 Получение глобального сборщика метрик"""
    return adapter_metrics
