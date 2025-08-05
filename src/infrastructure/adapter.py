import asyncio
import logging
from typing import Dict, Any, Optional
from pathlib import Path

from .api.client import ExmoAPIClient, APIClientFactory
from .cache.cache import CacheFactory, InMemoryCache
from .persistence.repository import RepositoryFactory, RepositoryConfig
from .monitoring.service import MonitoringFactory, MonitoringService
from ..config.settings import get_settings


class InfrastructureAdapter:
    """🔗 Адаптер инфраструктуры"""

    def __init__(self):
        self.settings = get_settings()
        self.logger = logging.getLogger(__name__)

        # Компоненты инфраструктуры
        self.api_client: Optional[ExmoAPIClient] = None
        self.cache: Optional[InMemoryCache] = None
        self.monitoring: Optional[MonitoringService] = None
        self.repositories = {}

        # Флаги инициализации
        self._initialized = False

    async def initialize(self) -> None:
        """🚀 Инициализация инфраструктуры"""
        if self._initialized:
            return

        try:
            # 1. Инициализация API клиента
            await self._init_api_client()

            # 2. Инициализация кэша
            await self._init_cache()

            # 3. Инициализация репозиториев
            await self._init_repositories()

            # 4. Инициализация мониторинга
            await self._init_monitoring()

            self._initialized = True
            self.logger.info("✅ Инфраструктура инициализирована")

        except Exception as e:
            self.logger.error(f"❌ Ошибка инициализации инфраструктуры: {e}")
            raise

    async def _init_api_client(self) -> None:
        """🌐 Инициализация API клиента"""
        try:
            from ..config.settings import APISettings

            api_settings = APISettings(
                exmo_api_key=self.settings.exmo_api_key,
                exmo_api_secret=self.settings.exmo_api_secret,
                calls_per_minute=getattr(self.settings, 'api_calls_per_minute', 30),
                calls_per_hour=getattr(self.settings, 'api_calls_per_hour', 300)
            )

            self.api_client = APIClientFactory.create_exmo_client(api_settings)
            self.logger.info("✅ API клиент инициализирован")

        except Exception as e:
            self.logger.warning(f"⚠️ API клиент недоступен: {e}")

    async def _init_cache(self) -> None:
        """💾 Инициализация кэша"""
        try:
            if getattr(self.settings, 'cache_enabled', True):
                self.cache = CacheFactory.create_memory_cache(
                    max_size=getattr(self.settings, 'cache_max_size', 1000),
                    default_ttl=getattr(self.settings, 'cache_ttl', 300)
                )
                await self.cache.start()
                self.logger.info("✅ Кэш инициализирован")

        except Exception as e:
            self.logger.warning(f"⚠️ Кэш недоступен: {e}")

    async def _init_repositories(self) -> None:
        """🗄️ Инициализация репозиториев"""
        try:
            config = RepositoryConfig(
                storage_type=getattr(self.settings, 'storage_type', 'json'),
                storage_path=getattr(self.settings, 'storage_path', 'data'),
                backup_enabled=getattr(self.settings, 'backup_enabled', True)
            )

            # Создаем репозитории
            from ..core.models import Position, TradeResult
            self.repositories['positions'] = RepositoryFactory.create_position_repository(config)
            self.repositories['trades'] = RepositoryFactory.create_trade_repository(config)

            self.logger.info("✅ Репозитории инициализированы")

        except Exception as e:
            self.logger.warning(f"⚠️ Репозитории недоступны: {e}")

    async def _init_monitoring(self) -> None:
        """📊 Инициализация мониторинга"""
        try:
            if getattr(self.settings, 'monitoring_enabled', True):
                self.monitoring = MonitoringFactory.create_monitoring_service(
                    notification_type=getattr(self.settings, 'notification_type', 'console'),
                    export_path=getattr(self.settings, 'export_path', 'monitoring_data')
                )
                await self.monitoring.start()
                self.logger.info("✅ Мониторинг инициализирован")

        except Exception as e:
            self.logger.warning(f"⚠️ Мониторинг недоступен: {e}")

    async def shutdown(self) -> None:
        """🛑 Корректное завершение"""
        try:
            if self.cache:
                await self.cache.stop()

            if self.monitoring:
                await self.monitoring.stop()

            self.logger.info("✅ Инфраструктура завершена")

        except Exception as e:
            self.logger.error(f"❌ Ошибка завершения: {e}")

    # Удобные методы для использования в старом боте

    async def get_current_price(self, pair: str) -> float:
        """💱 Получение цены с кэшированием"""
        if not self.api_client:
            return 0.0

        try:
            # Пытаемся получить из кэша
            if self.cache:
                cached_price = await self.cache.get(f"price_{pair}")
                if cached_price:
                    return float(cached_price)

            # Получаем из API
            price = await self.api_client.get_current_price(pair)
            price_float = float(price)

            # Кэшируем
            if self.cache:
                await self.cache.set(f"price_{pair}", price_float, ttl=30)

            # Записываем в мониторинг
            if self.monitoring:
                await self.monitoring.record_api_call("get_current_price", True, 0.5)

            return price_float

        except Exception as e:
            self.logger.error(f"Ошибка получения цены {pair}: {e}")
            if self.monitoring:
                await self.monitoring.record_api_call("get_current_price", False, 0.0)
            return 0.0

    async def get_balance(self, currency: str) -> float:
        """💰 Получение баланса с кэшированием"""
        if not self.api_client:
            return 0.0

        try:
            # Пытаемся получить из кэша
            if self.cache:
                cached_balance = await self.cache.get(f"balance_{currency}")
                if cached_balance:
                    return float(cached_balance)

            # Получаем из API
            balance = await self.api_client.get_balance(currency)
            balance_float = float(balance)

            # Кэшируем на короткое время
            if self.cache:
                await self.cache.set(f"balance_{currency}", balance_float, ttl=60)

            # Записываем в мониторинг
            if self.monitoring:
                await self.monitoring.record_balance(currency, balance_float)
                await self.monitoring.record_api_call("get_balance", True, 0.3)

            return balance_float

        except Exception as e:
            self.logger.error(f"Ошибка получения баланса {currency}: {e}")
            if self.monitoring:
                await self.monitoring.record_api_call("get_balance", False, 0.0)
            return 0.0

    async def create_order(self, pair: str, quantity: float, price: float, order_type: str) -> Dict[str, Any]:
        """📝 Создание ордера с мониторингом"""
        if not self.api_client:
            return {"success": False, "error": "API клиент недоступен"}

        try:
            from decimal import Decimal

            result = await self.api_client.create_order(
                pair, Decimal(str(quantity)), Decimal(str(price)), order_type
            )

            # Записываем в мониторинг
            if self.monitoring:
                await self.monitoring.record_trade(
                    pair, order_type, quantity, price, result.get("success", False)
                )
                await self.monitoring.record_api_call("create_order", result.get("success", False), 1.0)

            # Сохраняем в репозиторий
            if result.get("success") and "trades" in self.repositories:
                try:
                    # Создаем запись о сделке (адаптируем под вашу модель)
                    trade_data = {
                        "pair": pair,
                        "action": order_type,
                        "quantity": quantity,
                        "price": price,
                        "success": True,
                        "timestamp": datetime.now()
                    }
                    # await self.repositories['trades'].save(trade_data)
                except Exception as e:
                    self.logger.warning(f"Не удалось сохранить сделку: {e}")

            return result

        except Exception as e:
            self.logger.error(f"Ошибка создания ордера: {e}")
            if self.monitoring:
                await self.monitoring.record_api_call("create_order", False, 0.0)
            return {"success": False, "error": str(e)}

    async def get_monitoring_status(self) -> Dict[str, Any]:
        """📊 Получение статуса мониторинга"""
        if not self.monitoring:
            return {"error": "Мониторинг недоступен"}

        try:
            return await self.monitoring.get_system_status()
        except Exception as e:
            return {"error": str(e)}


# Глобальный экземпляр адаптера
_infrastructure_adapter: Optional[InfrastructureAdapter] = None

async def get_infrastructure() -> InfrastructureAdapter:
    """🔗 Получение глобального экземпляра инфраструктуры"""
    global _infrastructure_adapter

    if _infrastructure_adapter is None:
        _infrastructure_adapter = InfrastructureAdapter()
        await _infrastructure_adapter.initialize()

    return _infrastructure_adapter
