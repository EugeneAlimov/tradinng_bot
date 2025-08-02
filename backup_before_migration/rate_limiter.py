# rate_limiter.py
"""⚡ ИСПРАВЛЕННЫЙ умный ограничитель частоты API запросов"""

import time
import logging
from collections import deque
from typing import Dict, Any, Optional


class RateLimiter:
    """⚡ Исправленный rate limiter"""
    
    def __init__(self, calls_per_minute: int = 30, calls_per_hour: int = 300):
        self.calls_per_minute = calls_per_minute
        self.calls_per_hour = calls_per_hour
        self.logger = logging.getLogger(__name__)
        
        # Буферы для отслеживания вызовов
        self.minute_calls = deque()
        self.hour_calls = deque()
        
        # Статистика
        self.total_calls = 0
        self.total_waits = 0
        self.total_wait_time = 0.0
        self.blocked_calls = 0
        
        # Адаптивное управление
        self.adaptive_delay = 2.0
        self.last_error_time = 0
        
        self.logger.info("⚡ RateLimiter исправлен и инициализирован")
    
    def wait_if_needed(self, endpoint: str = "unknown") -> float:
        """⚡ Ожидание если необходимо соблюсти лимиты"""
        
        current_time = time.time()
        self._cleanup_old_calls(current_time)
        wait_time = self._calculate_wait_time(current_time)
        
        if wait_time > 0:
            self.total_waits += 1
            self.total_wait_time += wait_time
            self.logger.info(f"⏳ Rate limit: ожидание {wait_time:.1f}с для {endpoint}")
            time.sleep(wait_time)
        
        if self.adaptive_delay > 0:
            time.sleep(self.adaptive_delay)
        
        self._register_call(current_time)
        return wait_time + self.adaptive_delay
    
    def register_api_error(self, error_type: str = "unknown") -> None:
        """❌ Регистрация ошибки API"""
        
        self.last_error_time = time.time()
        
        if "rate limit" in error_type.lower() or "429" in error_type:
            self.adaptive_delay = min(30.0, self.adaptive_delay * 2.0)
            self.blocked_calls += 1
            self.logger.warning(f"🚫 Rate limit блокировка, задержка увеличена до {self.adaptive_delay:.1f}с")
        else:
            self.adaptive_delay = min(10.0, self.adaptive_delay * 1.2)
    
    def register_api_success(self, duration: float = 0.0) -> None:
        """✅ Регистрация успешного API вызова"""
        
        if self.adaptive_delay > 2.0:
            self.adaptive_delay = max(2.0, self.adaptive_delay * 0.9)
    
    def _cleanup_old_calls(self, current_time: float) -> None:
        """🧹 Очистка старых записей"""
        
        while self.minute_calls and current_time - self.minute_calls[0] > 60:
            self.minute_calls.popleft()
        
        while self.hour_calls and current_time - self.hour_calls[0] > 3600:
            self.hour_calls.popleft()
    
    def _calculate_wait_time(self, current_time: float) -> float:
        """⏰ Расчет времени ожидания"""
        
        wait_times = []
        
        if len(self.minute_calls) >= self.calls_per_minute:
            oldest_call = self.minute_calls[0]
            wait_for_minute = 60 - (current_time - oldest_call) + 1
            if wait_for_minute > 0:
                wait_times.append(wait_for_minute)
        
        if len(self.hour_calls) >= self.calls_per_hour:
            oldest_call = self.hour_calls[0]
            wait_for_hour = 3600 - (current_time - oldest_call) + 1
            if wait_for_hour > 0:
                wait_times.append(wait_for_hour)
        
        return max(wait_times) if wait_times else 0.0
    
    def _register_call(self, timestamp: float) -> None:
        """📊 Регистрация вызова"""
        
        self.minute_calls.append(timestamp)
        self.hour_calls.append(timestamp)
        self.total_calls += 1
    
    def get_rate_limit_stats(self) -> Dict[str, Any]:
        """📊 ИСПРАВЛЕННАЯ функция статистики"""
        
        current_time = time.time()
        self._cleanup_old_calls(current_time)
        
        load_percentage_minute = (len(self.minute_calls) / self.calls_per_minute) * 100
        load_percentage_hour = (len(self.hour_calls) / self.calls_per_hour) * 100
        
        success_rate = ((self.total_calls - self.blocked_calls) / max(self.total_calls, 1)) * 100
        wait_ratio = (self.total_waits / max(self.total_calls, 1)) * 100
        avg_wait_time = self.total_wait_time / max(self.total_waits, 1)
        
        return {
            'system_active': True,
            'current_limits': {
                'calls_per_minute': self.calls_per_minute,
                'calls_per_hour': self.calls_per_hour
            },
            'current_load': {
                'calls_this_minute': len(self.minute_calls),
                'calls_this_hour': len(self.hour_calls),
                'load_percentage_minute': round(load_percentage_minute, 1),
                'load_percentage_hour': round(load_percentage_hour, 1)
            },
            'adaptive_control': {
                'current_adaptive_delay': round(self.adaptive_delay, 2),
                'minutes_since_last_error': round((current_time - self.last_error_time) / 60, 1) if self.last_error_time > 0 else None
            },
            'statistics': {
                'total_calls': self.total_calls,
                'total_waits': self.total_waits,
                'total_wait_time_seconds': round(self.total_wait_time, 1),
                'blocked_calls': self.blocked_calls,
                'success_rate_percent': round(success_rate, 1)
            },
            'efficiency': {
                'wait_ratio_percent': round(wait_ratio, 1),
                'average_wait_time_seconds': round(avg_wait_time, 2) if self.total_waits > 0 else 0
            }
        }


class RateLimitedAPIClient:
    """🌐 ИСПРАВЛЕННЫЙ API клиент с rate limiting"""
    
    def __init__(self, original_api_client, rate_limiter: Optional[RateLimiter] = None):
        self.api = original_api_client
        self.rate_limiter = rate_limiter or RateLimiter()
        self.logger = logging.getLogger(__name__)
    
    def _make_rate_limited_call(self, method_name: str, *args, **kwargs):
        """🌐 Выполнение API вызова с rate limiting"""
        
        wait_time = self.rate_limiter.wait_if_needed(method_name)
        
        start_time = time.time()
        try:
            method = getattr(self.api, method_name)
            result = method(*args, **kwargs)
            
            duration = time.time() - start_time
            self.rate_limiter.register_api_success(duration)
            
            return result
            
        except Exception as e:
            error_type = type(e).__name__
            if hasattr(e, 'response') and hasattr(e.response, 'status_code'):
                error_type += f"_{e.response.status_code}"
            
            self.rate_limiter.register_api_error(error_type)
            raise
    
    def get_user_info(self):
        return self._make_rate_limited_call('get_user_info')
    
    def get_ticker(self):
        return self._make_rate_limited_call('get_ticker')
    
    def create_order(self, pair: str, quantity: float, price: float, order_type: str):
        return self._make_rate_limited_call('create_order', pair, quantity, price, order_type)
    
    def get_pair_settings(self):
        return self._make_rate_limited_call('get_pair_settings')
    
    def get_open_orders(self):
        return self._make_rate_limited_call('get_open_orders')
    
    def get_trades(self, pair: str, limit: int = 100):
        return self._make_rate_limited_call('get_trades', pair, limit)
    
    def get_rate_limit_stats(self):
        return self.rate_limiter.get_rate_limit_stats()
