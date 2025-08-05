from typing import Optional, List, Dict, Any, AsyncIterator
from decimal import Decimal
from datetime import datetime, timedelta
import logging
from dataclasses import dataclass, field
from enum import Enum
import asyncio

# Импорты из Core слоя
try:
    from ...core.interfaces import IMarketDataProvider
    from ...core.models import (
        MarketData, TradingPair, Price, Money
    )
    from ...core.exceptions import (
        TradingError, ValidationError, DataError, CacheError
    )
    from ...core.events import DomainEvent, publish_event
    from ...config.settings import get_current_config
except ImportError:
    # Fallback для случая если Core слой еще не готов
    class IMarketDataProvider: pass
    class MarketData: pass
    class TradingPair: pass
    class Price: pass
    class Money: pass
    class TradingError(Exception): pass
    class ValidationError(Exception): pass
    class DataError(Exception): pass
    class CacheError(Exception): pass
    class DomainEvent: pass
    def publish_event(event): pass
    def get_current_config(): return None


# ================= ТИПЫ ДАННЫХ =================

class DataSource(Enum):
    """📊 Источники данных"""
    EXCHANGE_API = "exchange_api"
    CACHED = "cached"
    AGGREGATED = "aggregated"
    FALLBACK = "fallback"


class DataQuality(Enum):
    """✅ Качество данных"""
    EXCELLENT = "excellent"    # Свежие данные из API
    GOOD = "good"             # Кэшированные данные
    ACCEPTABLE = "acceptable"  # Агрегированные данные
    POOR = "poor"             # Старые данные


@dataclass
class MarketDataMetrics:
    """📈 Метрики рыночных данных"""
    total_requests: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    api_calls: int = 0
    failed_requests: int = 0
    average_response_time: float = 0.0
    last_update: Optional[datetime] = None

    @property
    def cache_hit_rate(self) -> float:
        """Процент попаданий в кэш"""
        total = self.cache_hits + self.cache_misses
        return (self.cache_hits / total * 100) if total > 0 else 0.0

    @property
    def success_rate(self) -> float:
        """Процент успешных запросов"""
        total = self.total_requests
        successful = total - self.failed_requests
        return (successful / total * 100) if total > 0 else 0.0


@dataclass
class CachedMarketData:
    """🗄️ Кэшированные рыночные данные"""
    data: MarketData
    source: DataSource
    quality: DataQuality
    cached_at: datetime
    expires_at: datetime
    access_count: int = 0

    @property
    def is_expired(self) -> bool:
        """Истекли ли данные"""
        return datetime.now() > self.expires_at

    @property
    def age_seconds(self) -> float:
        """Возраст данных в секундах"""
        return (datetime.now() - self.cached_at).total_seconds()


# ================= ОСНОВНОЙ СЕРВИС =================

class MarketDataService(IMarketDataProvider):
    """📊 Сервис рыночных данных"""

    def __init__(
        self,
        exchange_provider: Optional[IMarketDataProvider] = None,
        cache_ttl_seconds: int = 60,
        max_cache_size: int = 1000
    ):
        self.exchange_provider = exchange_provider
        self.cache_ttl = timedelta(seconds=cache_ttl_seconds)
        self.max_cache_size = max_cache_size

        # Кэш данных
        self.cache: Dict[str, CachedMarketData] = {}

        # Подписки на обновления
        self.price_subscriptions: Dict[str, List[callable]] = {}

        # Метрики
        self.metrics = MarketDataMetrics()

        # Логирование
        self.logger = logging.getLogger(__name__)

        self.logger.info("📊 MarketDataService инициализирован")

    # ================= ОСНОВНЫЕ МЕТОДЫ ИНТЕРФЕЙСА =================

    async def get_market_data(self, pair: str) -> MarketData:
        """📈 Получение рыночных данных"""

        try:
            self.metrics.total_requests += 1
            start_time = datetime.now()

            # Проверяем кэш
            cached_data = await self._get_from_cache(pair)
            if cached_data and not cached_data.is_expired:
                self.metrics.cache_hits += 1
                cached_data.access_count += 1

                self.logger.debug(f"📊 Данные из кэша для {pair}")
                return cached_data.data

            self.metrics.cache_misses += 1

            # Получаем данные из внешнего источника
            if self.exchange_provider:
                try:
                    self.metrics.api_calls += 1
                    market_data = await self.exchange_provider.get_market_data(pair)

                    # Кэшируем данные
                    await self._cache_data(pair, market_data, DataSource.EXCHANGE_API)

                    # Обновляем метрики
                    response_time = (datetime.now() - start_time).total_seconds()
                    self._update_response_time(response_time)

                    self.logger.debug(f"📊 Данные из API для {pair}")
                    return market_data

                except Exception as e:
                    self.logger.warning(f"⚠️ Ошибка получения данных из API для {pair}: {e}")
                    self.metrics.failed_requests += 1

            # Пытаемся использовать устаревшие кэшированные данные
            if cached_data:
                self.logger.warning(f"⚠️ Используем устаревшие данные для {pair}")
                return cached_data.data

            # Создаем заглушку если ничего нет
            fallback_data = await self._create_fallback_data(pair)
            await self._cache_data(pair, fallback_data, DataSource.FALLBACK)

            self.logger.warning(f"⚠️ Используем fallback данные для {pair}")
            return fallback_data

        except Exception as e:
            self.metrics.failed_requests += 1
            self.logger.error(f"❌ Ошибка получения рыночных данных для {pair}: {e}")
            raise DataError(f"Не удалось получить данные для {pair}: {e}") from e

    async def get_historical_data(
        self,
        pair: str,
        period: str,
        limit: int = 100
    ) -> List[MarketData]:
        """📜 Исторические данные"""

        try:
            cache_key = f"{pair}_{period}_{limit}_historical"

            # Проверяем кэш
            cached_data = await self._get_from_cache(cache_key)
            if cached_data and not cached_data.is_expired:
                if isinstance(cached_data.data, list):
                    return cached_data.data

            # Получаем из внешнего источника
            if self.exchange_provider:
                try:
                    historical_data = await self.exchange_provider.get_historical_data(
                        pair, period, limit
                    )

                    # Кэшируем с увеличенным TTL для исторических данных
                    extended_ttl = self.cache_ttl * 5
                    await self._cache_historical_data(
                        cache_key, historical_data, extended_ttl
                    )

                    return historical_data

                except Exception as e:
                    self.logger.warning(f"⚠️ Ошибка получения исторических данных: {e}")

            return []

        except Exception as e:
            self.logger.error(f"❌ Ошибка получения исторических данных: {e}")
            return []

    async def subscribe_to_price_updates(
        self,
        pair: str,
        callback: callable
    ) -> None:
        """🔔 Подписка на обновления цен"""

        try:
            if pair not in self.price_subscriptions:
                self.price_subscriptions[pair] = []

            self.price_subscriptions[pair].append(callback)

            self.logger.info(f"🔔 Подписка на обновления {pair} создана")

        except Exception as e:
            self.logger.error(f"❌ Ошибка создания подписки для {pair}: {e}")

    async def get_price_stream(self, pair: str) -> AsyncIterator[Price]:
        """🌊 Поток цен в реальном времени"""

        try:
            if self.exchange_provider and hasattr(self.exchange_provider, 'get_price_stream'):
                async for price in self.exchange_provider.get_price_stream(pair):
                    # Кэшируем цену
                    await self._cache_price(pair, price)

                    # Уведомляем подписчиков
                    await self._notify_price_subscribers(pair, price)

                    yield price
            else:
                # Fallback - периодическое получение данных
                while True:
                    try:
                        market_data = await self.get_market_data(pair)
                        yield market_data.price
                        await asyncio.sleep(5)  # 5 секунд между обновлениями
                    except Exception as e:
                        self.logger.error(f"❌ Ошибка в потоке цен для {pair}: {e}")
                        await asyncio.sleep(10)

        except Exception as e:
            self.logger.error(f"❌ Ошибка создания потока цен для {pair}: {e}")

    # ================= КЭШИРОВАНИЕ =================

    async def _get_from_cache(self, key: str) -> Optional[CachedMarketData]:
        """📖 Получение из кэша"""

        try:
            if key in self.cache:
                return self.cache[key]
            return None

        except Exception as e:
            self.logger.error(f"❌ Ошибка чтения кэша для {key}: {e}")
            return None

    async def _cache_data(
        self,
        pair: str,
        data: MarketData,
        source: DataSource
    ) -> None:
        """💾 Кэширование данных"""

        try:
            # Определяем качество данных
            quality = self._determine_data_quality(source, data)

            # Создаем кэшированную запись
            cached_data = CachedMarketData(
                data=data,
                source=source,
                quality=quality,
                cached_at=datetime.now(),
                expires_at=datetime.now() + self.cache_ttl
            )

            # Проверяем размер кэша
            await self._ensure_cache_size()

            # Сохраняем в кэш
            self.cache[pair] = cached_data

        except Exception as e:
            self.logger.error(f"❌ Ошибка кэширования данных для {pair}: {e}")

    async def _cache_historical_data(
        self,
        key: str,
        data: List[MarketData],
        ttl: timedelta
    ) -> None:
        """📜 Кэширование исторических данных"""

        try:
            cached_data = CachedMarketData(
                data=data,
                source=DataSource.EXCHANGE_API,
                quality=DataQuality.GOOD,
                cached_at=datetime.now(),
                expires_at=datetime.now() + ttl
            )

            await self._ensure_cache_size()
            self.cache[key] = cached_data

        except Exception as e:
            self.logger.error(f"❌ Ошибка кэширования исторических данных: {e}")

    async def _cache_price(self, pair: str, price: Price) -> None:
        """💰 Кэширование цены"""

        try:
            price_key = f"{pair}_price"

            # Создаем минимальные market data только с ценой
            market_data = MarketData(
                pair=TradingPair.from_string(pair),
                price=price,
                timestamp=price.timestamp
            )

            await self._cache_data(price_key, market_data, DataSource.EXCHANGE_API)

        except Exception as e:
            self.logger.error(f"❌ Ошибка кэширования цены для {pair}: {e}")

    async def _ensure_cache_size(self) -> None:
        """🧹 Контроль размера кэша"""

        try:
            if len(self.cache) >= self.max_cache_size:
                # Удаляем самые старые записи
                sorted_items = sorted(
                    self.cache.items(),
                    key=lambda x: x[1].cached_at
                )

                # Удаляем 20% самых старых записей
                items_to_remove = len(sorted_items) // 5
                for i in range(items_to_remove):
                    key_to_remove = sorted_items[i][0]
                    del self.cache[key_to_remove]

                self.logger.debug(f"🧹 Очищен кэш: удалено {items_to_remove} записей")

        except Exception as e:
            self.logger.error(f"❌ Ошибка очистки кэша: {e}")

    # ================= ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ =================

    def _determine_data_quality(
        self,
        source: DataSource,
        data: MarketData
    ) -> DataQuality:
        """✅ Определение качества данных"""

        if source == DataSource.EXCHANGE_API:
            # Проверяем свежесть данных
            age_seconds = (datetime.now() - data.timestamp).total_seconds()
            if age_seconds < 30:
                return DataQuality.EXCELLENT
            elif age_seconds < 120:
                return DataQuality.GOOD
            else:
                return DataQuality.ACCEPTABLE

        elif source == DataSource.CACHED:
            return DataQuality.GOOD

        elif source == DataSource.AGGREGATED:
            return DataQuality.ACCEPTABLE

        else:  # FALLBACK
            return DataQuality.POOR

    async def _create_fallback_data(self, pair: str) -> MarketData:
        """🔄 Создание fallback данных"""

        try:
            trading_pair = TradingPair.from_string(pair)

            # Используем базовую цену (в реальной системе можно брать из исторических данных)
            fallback_price = Price(
                value=Decimal('0.1'),  # Заглушка
                pair=trading_pair,
                timestamp=datetime.now()
            )

            return MarketData(
                pair=trading_pair,
                price=fallback_price,
                volume_24h=Decimal('0'),
                timestamp=datetime.now(),
                metadata={'source': 'fallback', 'quality': 'poor'}
            )

        except Exception as e:
            self.logger.error(f"❌ Ошибка создания fallback данных: {e}")
            raise DataError(f"Не удалось создать fallback данные для {pair}")

    async def _notify_price_subscribers(self, pair: str, price: Price) -> None:
        """🔔 Уведомление подписчиков об изменении цены"""

        try:
            if pair in self.price_subscriptions:
                for callback in self.price_subscriptions[pair]:
                    try:
                        if asyncio.iscoroutinefunction(callback):
                            await callback(price)
                        else:
                            callback(price)
                    except Exception as e:
                        self.logger.error(f"❌ Ошибка в callback подписчика: {e}")

        except Exception as e:
            self.logger.error(f"❌ Ошибка уведомления подписчиков для {pair}: {e}")

    def _update_response_time(self, response_time: float) -> None:
        """⏱️ Обновление среднего времени ответа"""

        if self.metrics.average_response_time == 0:
            self.metrics.average_response_time = response_time
        else:
            # Экспоненциальное сглаживание
            alpha = 0.1
            self.metrics.average_response_time = (
                alpha * response_time +
                (1 - alpha) * self.metrics.average_response_time
            )

    # ================= УПРАВЛЕНИЕ И МОНИТОРИНГ =================

    async def clear_cache(self) -> None:
        """🧹 Очистка кэша"""

        try:
            cleared_items = len(self.cache)
            self.cache.clear()

            self.logger.info(f"🧹 Кэш очищен: удалено {cleared_items} записей")

        except Exception as e:
            self.logger.error(f"❌ Ошибка очистки кэша: {e}")

    async def get_cache_statistics(self) -> Dict[str, Any]:
        """📊 Статистика кэша"""

        try:
            total_items = len(self.cache)
            expired_items = sum(1 for item in self.cache.values() if item.is_expired)

            quality_stats = {}
            source_stats = {}

            for cached_data in self.cache.values():
                # Статистика по качеству
                quality = cached_data.quality.value
                quality_stats[quality] = quality_stats.get(quality, 0) + 1

                # Статистика по источникам
                source = cached_data.source.value
                source_stats[source] = source_stats.get(source, 0) + 1

            return {
                'total_items': total_items,
                'expired_items': expired_items,
                'active_items': total_items - expired_items,
                'quality_distribution': quality_stats,
                'source_distribution': source_stats,
                'max_cache_size': self.max_cache_size,
                'cache_utilization_percent': (total_items / self.max_cache_size) * 100
            }

        except Exception as e:
            self.logger.error(f"❌ Ошибка получения статистики кэша: {e}")
            return {}

    def get_metrics(self) -> Dict[str, Any]:
        """📈 Получение метрик сервиса"""

        return {
            'requests': {
                'total': self.metrics.total_requests,
                'failed': self.metrics.failed_requests,
                'success_rate': self.metrics.success_rate
            },
            'cache': {
                'hits': self.metrics.cache_hits,
                'misses': self.metrics.cache_misses,
                'hit_rate': self.metrics.cache_hit_rate
            },
            'api': {
                'calls': self.metrics.api_calls,
                'average_response_time': self.metrics.average_response_time
            },
            'subscriptions': {
                'active_pairs': len(self.price_subscriptions),
                'total_subscribers': sum(len(subs) for subs in self.price_subscriptions.values())
            },
            'last_update': self.metrics.last_update.isoformat() if self.metrics.last_update else None
        }

    async def cleanup_expired_cache(self) -> int:
        """🧹 Очистка истекших записей кэша"""

        try:
            expired_keys = [
                key for key, cached_data in self.cache.items()
                if cached_data.is_expired
            ]

            for key in expired_keys:
                del self.cache[key]

            if expired_keys:
                self.logger.debug(f"🧹 Удалено {len(expired_keys)} истекших записей")

            return len(expired_keys)

        except Exception as e:
            self.logger.error(f"❌ Ошибка очистки истекших записей: {e}")
            return 0
