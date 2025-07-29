import time
import logging
from typing import Dict, List, Optional
from collections import deque
from threading import Lock
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class APILimits:
    """📊 Лимиты API для разных типов запросов"""
    requests_per_second: int
    requests_per_minute: int
    requests_per_hour: int
    trading_requests_per_minute: int = 10  # Специальный лимит для торговых операций


class RateLimiter:
    """⏱️ Умный rate limiter с поддержкой разных типов запросов"""

    def __init__(self, api_limits: APILimits):
        self.limits = api_limits
        self.logger = logging.getLogger(__name__)

        # Трекинг запросов по времени
        self.requests_per_second = deque(maxlen=api_limits.requests_per_second * 2)
        self.requests_per_minute = deque(maxlen=api_limits.requests_per_minute * 2)
        self.requests_per_hour = deque(maxlen=api_limits.requests_per_hour * 2)
        self.trading_requests = deque(maxlen=api_limits.trading_requests_per_minute * 2)

        # Блокировка для thread-safety
        self._lock = Lock()

        # Статистика
        self.total_requests = 0
        self.total_waits = 0
        self.total_wait_time = 0.0
        self.last_request_time = 0.0

        self.logger.info("⏱️ Rate Limiter инициализирован")
        self.logger.info(f"   📊 Лимиты: {api_limits.requests_per_second}/сек, {api_limits.requests_per_minute}/мин")
        self.logger.info(f"   🔄 Торговые операции: {api_limits.trading_requests_per_minute}/мин")

    def wait_if_needed(self, request_type: str = 'general') -> float:
        """⏰ Ожидание если нужно соблюсти лимиты"""

        with self._lock:
            current_time = time.time()
            wait_time = 0.0

            # Очищаем старые записи
            self._cleanup_old_requests(current_time)

            # Проверяем лимиты и рассчитываем необходимую задержку
            wait_time = self._calculate_wait_time(current_time, request_type)

            if wait_time > 0:
                self.logger.info(f"⏳ Rate limit: ожидание {wait_time:.2f}с для {request_type}")
                self.total_waits += 1
                self.total_wait_time += wait_time

                # Освобождаем lock перед сном
                self._lock.release()
                time.sleep(wait_time)
                self._lock.acquire()

                # Обновляем время после ожидания
                current_time = time.time()

            # Регистрируем запрос
            self._register_request(current_time, request_type)

            return wait_time

    def _cleanup_old_requests(self, current_time: float):
        """🧹 Очистка старых записей запросов"""

        # Очищаем запросы старше 1 секунды
        while self.requests_per_second and current_time - self.requests_per_second[0] >= 1.0:
            self.requests_per_second.popleft()

        # Очищаем запросы старше 1 минуты
        while self.requests_per_minute and current_time - self.requests_per_minute[0] >= 60.0:
            self.requests_per_minute.popleft()

        # Очищаем запросы старше 1 часа
        while self.requests_per_hour and current_time - self.requests_per_hour[0] >= 3600.0:
            self.requests_per_hour.popleft()

        # Очищаем торговые запросы старше 1 минуты
        while self.trading_requests and current_time - self.trading_requests[0][0] >= 60.0:
            self.trading_requests.popleft()

    def _calculate_wait_time(self, current_time: float, request_type: str) -> float:
        """⏰ Расчет необходимого времени ожидания"""

        max_wait = 0.0

        # Проверка лимита за секунду
        if len(self.requests_per_second) >= self.limits.requests_per_second:
            oldest_request = self.requests_per_second[0]
            wait_for_second = 1.0 - (current_time - oldest_request)
            max_wait = max(max_wait, wait_for_second)

        # Проверка лимита за минуту
        if len(self.requests_per_minute) >= self.limits.requests_per_minute:
            oldest_request = self.requests_per_minute[0]
            wait_for_minute = 60.0 - (current_time - oldest_request)
            max_wait = max(max_wait, wait_for_minute)

        # Проверка лимита за час
        if len(self.requests_per_hour) >= self.limits.requests_per_hour:
            oldest_request = self.requests_per_hour[0]
            wait_for_hour = 3600.0 - (current_time - oldest_request)
            max_wait = max(max_wait, wait_for_hour)

        # Специальная проверка для торговых операций
        if request_type in ['order_create', 'order_cancel', 'trading']:
            trading_count = len([req for req in self.trading_requests
                                 if req[1] in ['order_create', 'order_cancel', 'trading']])

            if trading_count >= self.limits.trading_requests_per_minute:
                oldest_trading = min(self.trading_requests, key=lambda x: x[0])[0]
                wait_for_trading = 60.0 - (current_time - oldest_trading)
                max_wait = max(max_wait, wait_for_trading)

        # Минимальная задержка между запросами (100ms)
        if self.last_request_time > 0:
            min_interval = 0.1
            since_last = current_time - self.last_request_time
            if since_last < min_interval:
                max_wait = max(max_wait, min_interval - since_last)

        return max(0.0, max_wait)

    def _register_request(self, current_time: float, request_type: str):
        """📝 Регистрация нового запроса"""

        self.requests_per_second.append(current_time)
        self.requests_per_minute.append(current_time)
        self.requests_per_hour.append(current_time)

        if request_type in ['order_create', 'order_cancel', 'trading']:
            self.trading_requests.append((current_time, request_type))

        self.total_requests += 1
        self.last_request_time = current_time

    def get_stats(self) -> Dict[str, any]:
        """📊 Статистика rate limiter"""

        current_time = time.time()

        # Очищаем для точной статистики
        self._cleanup_old_requests(current_time)

        # Подсчет запросов за разные периоды
        requests_last_second = len(self.requests_per_second)
        requests_last_minute = len(self.requests_per_minute)
        requests_last_hour = len(self.requests_per_hour)
        trading_requests_minute = len([req for req in self.trading_requests
                                       if req[1] in ['order_create', 'order_cancel', 'trading']])

        # Загрузка (в процентах от лимита)
        load_per_second = (requests_last_second / self.limits.requests_per_second) * 100
        load_per_minute = (requests_last_minute / self.limits.requests_per_minute) * 100
        load_per_hour = (requests_last_hour / self.limits.requests_per_hour) * 100

        avg_wait_time = self.total_wait_time / max(1, self.total_waits)

        return {
            'total_requests': self.total_requests,
            'total_waits': self.total_waits,
            'total_wait_time': self.total_wait_time,
            'avg_wait_time': avg_wait_time,
            'requests_last_second': requests_last_second,
            'requests_last_minute': requests_last_minute,
            'requests_last_hour': requests_last_hour,
            'trading_requests_last_minute': trading_requests_minute,
            'load_percentage': {
                'per_second': load_per_second,
                'per_minute': load_per_minute,
                'per_hour': load_per_hour
            },
            'limits': {
                'per_second': self.limits.requests_per_second,
                'per_minute': self.limits.requests_per_minute,
                'per_hour': self.limits.requests_per_hour,
                'trading_per_minute': self.limits.trading_requests_per_minute
            }
        }

    def log_stats(self):
        """📝 Логирование статистики"""
        stats = self.get_stats()

        self.logger.info("📊 СТАТИСТИКА RATE LIMITER:")
        self.logger.info(f"   📈 Всего запросов: {stats['total_requests']}")
        self.logger.info(f"   ⏳ Ожиданий: {stats['total_waits']}")
        self.logger.info(f"   🕒 Среднее ожидание: {stats['avg_wait_time']:.2f}с")

        self.logger.info(f"   📊 Текущая загрузка:")
        self.logger.info(
            f"      За секунду: {stats['requests_last_second']}/{stats['limits']['per_second']} ({stats['load_percentage']['per_second']:.1f}%)")
        self.logger.info(
            f"      За минуту: {stats['requests_last_minute']}/{stats['limits']['per_minute']} ({stats['load_percentage']['per_minute']:.1f}%)")
        self.logger.info(
            f"      Торговых/мин: {stats['trading_requests_last_minute']}/{stats['limits']['trading_per_minute']}")

        if stats['load_percentage']['per_minute'] > 80:
            self.logger.warning(f"⚠️ Высокая загрузка API: {stats['load_percentage']['per_minute']:.1f}%")


class ExmoRateLimiter(RateLimiter):
    """🔄 Специализированный rate limiter для EXMO API"""

    def __init__(self):
        # Лимиты EXMO (консервативные значения)
        exmo_limits = APILimits(
            requests_per_second=8,  # EXMO позволяет 10/сек, берем 8 для безопасности
            requests_per_minute=300,  # EXMO позволяет 600/мин, берем 300
            requests_per_hour=10000,  # EXMO позволяет больше, но лучше ограничить
            trading_requests_per_minute=20,  # Торговые операции еще более ограничены
        )

        super().__init__(exmo_limits)

    def wait_for_trading_request(self) -> float:
        """🔄 Специальное ожидание для торговых запросов"""
        return self.wait_if_needed('trading')

    def wait_for_market_data(self) -> float:
        """📊 Ожидание для запросов рыночных данных"""
        return self.wait_if_needed('market_data')

    def wait_for_account_data(self) -> float:
        """👤 Ожидание для запросов данных аккаунта"""
        return self.wait_if_needed('account')


# Интеграция с API клиентом
class RateLimitedAPIClient:
    """🔗 API клиент с встроенным rate limiting"""

    def __init__(self, original_api_client):
        self.api = original_api_client
        self.rate_limiter = ExmoRateLimiter()
        self.logger = logging.getLogger(__name__)

        # Статистика блокировок
        self.blocked_requests = 0
        self.total_wait_time = 0.0

    def get_user_info(self):
        """👤 Получение информации о пользователе с rate limiting"""
        wait_time = self.rate_limiter.wait_for_account_data()
        self.total_wait_time += wait_time

        return self.api.get_user_info()

    def get_open_orders(self):
        """📋 Получение открытых ордеров с rate limiting"""
        wait_time = self.rate_limiter.wait_for_account_data()
        self.total_wait_time += wait_time

        return self.api.get_open_orders()

    def create_order(self, pair: str, quantity: float, price: float, order_type: str):
        """📝 Создание ордера с rate limiting"""
        wait_time = self.rate_limiter.wait_for_trading_request()
        self.total_wait_time += wait_time

        if wait_time > 5.0:  # Если ждем больше 5 секунд
            self.blocked_requests += 1
            self.logger.warning(f"⚠️ Долгое ожидание торгового запроса: {wait_time:.2f}с")

        return self.api.create_order(pair, quantity, price, order_type)

    def cancel_order(self, order_id: int):
        """❌ Отмена ордера с rate limiting"""
        wait_time = self.rate_limiter.wait_for_trading_request()
        self.total_wait_time += wait_time

        return self.api.cancel_order(order_id)

    def get_trades(self, pair: str):
        """📈 Получение сделок с rate limiting"""
        wait_time = self.rate_limiter.wait_for_market_data()
        self.total_wait_time += wait_time

        return self.api.get_trades(pair)

    def get_user_trades(self, pair: str, limit: int = 100):
        """📊 Получение истории сделок с rate limiting"""
        wait_time = self.rate_limiter.wait_for_account_data()
        self.total_wait_time += wait_time

        return self.api.get_user_trades(pair, limit)

    def get_pair_settings(self):
        """⚙️ Получение настроек пар с rate limiting"""
        wait_time = self.rate_limiter.wait_for_market_data()
        self.total_wait_time += wait_time

        return self.api.get_pair_settings()

    def check_connection(self) -> bool:
        """🔗 Проверка соединения с rate limiting"""
        try:
            wait_time = self.rate_limiter.wait_for_market_data()
            self.total_wait_time += wait_time

            return self.api.check_connection()
        except Exception:
            return False

    def get_rate_limit_stats(self) -> Dict[str, any]:
        """📊 Статистика rate limiting"""
        limiter_stats = self.rate_limiter.get_stats()

        return {
            **limiter_stats,
            'blocked_requests': self.blocked_requests,
            'client_total_wait_time': self.total_wait_time,
            'efficiency': {
                'wait_time_per_request': self.total_wait_time / max(1, limiter_stats['total_requests']),
                'block_rate': (self.blocked_requests / max(1, limiter_stats['total_requests'])) * 100
            }
        }

    def log_rate_limit_stats(self):
        """📝 Логирование статистики"""
        self.rate_limiter.log_stats()

        stats = self.get_rate_limit_stats()
        self.logger.info(f"🔗 СТАТИСТИКА API КЛИЕНТА:")
        self.logger.info(f"   🚫 Заблокированных запросов: {stats['blocked_requests']}")
        self.logger.info(f"   ⏱️ Общее время ожидания: {stats['client_total_wait_time']:.1f}с")
        self.logger.info(f"   📊 Ожидание на запрос: {stats['efficiency']['wait_time_per_request']:.2f}с")
        self.logger.info(f"   📈 Процент блокировок: {stats['efficiency']['block_rate']:.1f}%")

    def close(self):
        """🔚 Закрытие с финальной статистикой"""
        self.log_rate_limit_stats()
        if hasattr(self.api, 'close'):
            self.api.close()


if __name__ == "__main__":
    # Тестирование rate limiter
    print("🧪 ТЕСТИРОВАНИЕ RATE LIMITER")
    print("=" * 40)

    # Создаем тестовый лимитер
    test_limits = APILimits(
        requests_per_second=2,
        requests_per_minute=10,
        requests_per_hour=100,
        trading_requests_per_minute=3
    )

    limiter = RateLimiter(test_limits)

    # Тестируем несколько запросов
    for i in range(5):
        start_time = time.time()
        wait_time = limiter.wait_if_needed('general')
        end_time = time.time()

        print(f"Запрос {i + 1}: ожидание {wait_time:.2f}с, реальное время {end_time - start_time:.2f}с")

    # Тестируем торговые запросы
    print("\n📈 Тестирование торговых запросов:")
    for i in range(4):
        start_time = time.time()
        wait_time = limiter.wait_if_needed('trading')
        end_time = time.time()

        print(f"Торговый запрос {i + 1}: ожидание {wait_time:.2f}с")

    # Статистика
    print("\n📊 Финальная статистика:")
    limiter.log_stats()
