# hybrid_bot_enhanced.py
#!/usr/bin/env python3
"""🤖 Улучшенный гибридный торговый бот с новой инфраструктурой"""

import asyncio
import logging
import sys
from pathlib import Path

# Добавляем src в путь
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))

from infrastructure.adapter import get_infrastructure


class EnhancedHybridBot:
    """🤖 Улучшенный гибридный бот"""

    def __init__(self):
        self.setup_logging()
        self.infrastructure = None
        self.running = False

        # Старые компоненты (для совместимости)
        self.config = None
        self.api_client = None
        self.position_manager = None
        self.risk_manager = None

        # Новые компоненты
        self.monitoring_enabled = True
        self.dashboard_enabled = False

    def setup_logging(self):
        """📝 Настройка логирования"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('logs/enhanced_bot.log', encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)

    async def initialize(self):
        """🚀 Инициализация бота"""
        try:
            self.logger.info("🚀 Инициализация улучшенного бота...")

            # 1. Инициализируем новую инфраструктуру
            self.infrastructure = await get_infrastructure()

            # 2. Пытаемся загрузить старые компоненты
            await self._load_legacy_components()

            # 3. Настраиваем дашборд
            if self.dashboard_enabled:
                await self._setup_dashboard()

            self.logger.info("✅ Инициализация завершена")

        except Exception as e:
            self.logger.error(f"❌ Ошибка инициализации: {e}")
            raise

    async def _load_legacy_components(self):
        """📜 Загрузка старых компонентов"""
        try:
            # Пытаемся загрузить старую конфигурацию
            try:
                from config import TradingConfig
                self.config = TradingConfig()
                self.logger.info("✅ Старая конфигурация загружена")
            except ImportError:
                self.logger.warning("⚠️ Старая конфигурация недоступна")

            # Пытаемся загрузить старые менеджеры
            try:
                from position_manager import PositionManager
                self.position_manager = PositionManager()
                self.logger.info("✅ PositionManager загружен")
            except ImportError:
                self.logger.warning("⚠️ PositionManager недоступен")

            try:
                from risk_management import RiskManager
                self.risk_manager = RiskManager(self.config)
                self.logger.info("✅ RiskManager загружен")
            except ImportError:
                self.logger.warning("⚠️ RiskManager недоступен")

        except Exception as e:
            self.logger.warning(f"⚠️ Проблема с legacy компонентами: {e}")

    async def _setup_dashboard(self):
        """📊 Настройка дашборда"""
        try:
            if self.infrastructure and self.infrastructure.monitoring:
                from infrastructure.monitoring.service import SimpleWebDashboard

                dashboard = SimpleWebDashboard(self.infrastructure.monitoring, 8080)
                await dashboard.start()

                self.logger.info("📊 Дашборд запущен на http://localhost:8080")
        except Exception as e:
            self.logger.error(f"❌ Ошибка запуска дашборда: {e}")

    async def run(self):
        """🔄 Главный цикл бота"""
        self.running = True
        cycle_count = 0

        self.logger.info("🔄 Запуск главного цикла...")

        try:
            while self.running:
                cycle_count += 1
                cycle_start = asyncio.get_event_loop().time()

                self.logger.info(f"📊 Цикл {cycle_count}")

                try:
                    # Выполняем торговый цикл
                    result = await self._execute_trading_cycle()

                    cycle_duration = asyncio.get_event_loop().time() - cycle_start

                    self.logger.info(f"✅ Цикл {cycle_count} завершен за {cycle_duration:.2f}с: {result.get('reason', 'OK')}")

                    # Записываем метрики
                    if self.infrastructure and self.infrastructure.monitoring:
                        self.infrastructure.monitoring.collector.record_timer("trading_cycle_duration", cycle_duration)
                        self.infrastructure.monitoring.collector.increment_counter("trading_cycles_completed")

                except Exception as e:
                    self.logger.error(f"❌ Ошибка в цикле {cycle_count}: {e}")

                    # Записываем ошибку в мониторинг
                    if self.infrastructure and self.infrastructure.monitoring:
                        self.infrastructure.monitoring.collector.increment_counter("trading_cycle_errors")

                # Пауза между циклами
                await asyncio.sleep(30)  # 30 секунд

        except KeyboardInterrupt:
            self.logger.info("⌨️ Остановка по Ctrl+C")
        except Exception as e:
            self.logger.error(f"❌ Критическая ошибка: {e}")
        finally:
            await self.shutdown()

    async def _execute_trading_cycle(self) -> Dict[str, Any]:
        """📊 Выполнение торгового цикла"""
        try:
            # 1. Собираем рыночные данные
            market_data = await self._collect_market_data()

            # 2. Получаем данные позиций
            position_data = await self._get_position_data()

            # 3. Выполняем торговую логику
            if position_data.get('has_position'):
                return await self._handle_existing_position(market_data, position_data)
            else:
                return await self._handle_no_position(market_data)

        except Exception as e:
            return {"success": False, "reason": f"Ошибка торгового цикла: {e}"}

    async def _collect_market_data(self) -> Dict[str, Any]:
        """📊 Сбор рыночных данных"""
        try:
            pair = "DOGE_EUR"

            # Используем новую инфраструктуру
            if self.infrastructure:
                current_price = await self.infrastructure.get_current_price(pair)
                eur_balance = await self.infrastructure.get_balance("EUR")
                doge_balance = await self.infrastructure.get_balance("DOGE")
            else:
                # Fallback на старые методы
                current_price = 0.18  # Заглушка
                eur_balance = 1000.0
                doge_balance = 0.0

            return {
                "pair": pair,
                "current_price": current_price,
                "eur_balance": eur_balance,
                "doge_balance": doge_balance,
                "timestamp": asyncio.get_event_loop().time()
            }

        except Exception as e:
            self.logger.error(f"Ошибка сбора данных: {e}")
            return {
                "pair": "DOGE_EUR",
                "current_price": 0.0,
                "eur_balance": 0.0,
                "doge_balance": 0.0,
                "error": str(e)
            }

    async def _get_position_data(self) -> Dict[str, Any]:
        """📊 Получение данных позиций"""
        try:
            # Пытаемся использовать старый position_manager
            if self.position_manager:
                position = self.position_manager.get_position("DOGE")
                if position:
                    return {
                        "has_position": True,
                        "quantity": position.get("quantity", 0),
                        "avg_price": position.get("avg_price", 0),
                        "total_cost": position.get("total_cost", 0)
                    }

            # Fallback - проверяем баланс DOGE
            doge_balance = 0.0
            if self.infrastructure:
                doge_balance = await self.infrastructure.get_balance("DOGE")

            return {
                "has_position": doge_balance > 0,
                "quantity": doge_balance,
                "avg_price": 0.18,  # Примерное значение
                "total_cost": doge_balance * 0.18
            }

        except Exception as e:
            self.logger.error(f"Ошибка получения позиции: {e}")
            return {"has_position": False, "error": str(e)}

    async def _handle_existing_position(self, market_data: Dict, position_data: Dict) -> Dict[str, Any]:
        """📊 Обработка существующей позиции"""
        current_price = market_data.get("current_price", 0)
        avg_price = position_data.get("avg_price", 0)

        if current_price == 0 or avg_price == 0:
            return {"success": False, "reason": "Нет данных о ценах"}

        # Рассчитываем прибыль
        profit_percent = ((current_price - avg_price) / avg_price) * 100

        # Простая логика продажи при прибыли > 2%
        if profit_percent > 2.0:
            quantity = position_data.get("quantity", 0)

            if quantity > 0 and self.infrastructure:
                result = await self.infrastructure.create_order(
                    "DOGE_EUR", quantity, current_price, "sell"
                )

                if result.get("success"):
                    return {
                        "success": True,
                        "action": "sell",
                        "reason": f"Продажа с прибылью {profit_percent:.2f}%",
                        "quantity": quantity,
                        "price": current_price
                    }

        return {
            "success": True,
            "action": "hold",
            "reason": f"Удерживаем позицию, прибыль: {profit_percent:.2f}%"
        }

    async def _handle_no_position(self, market_data: Dict) -> Dict[str, Any]:
        """📊 Обработка отсутствия позиции"""
        current_price = market_data.get("current_price", 0)
        eur_balance = market_data.get("eur_balance", 0)

        if current_price == 0 or eur_balance < 50:
            return {"success": False, "reason": "Недостаточно данных или средств"}

        # Простая логика покупки
        purchase_amount = min(eur_balance * 0.1, 100)  # 10% от баланса, максимум 100 EUR
        quantity = purchase_amount / current_price

        if self.infrastructure:
            result = await self.infrastructure.create_order(
                "DOGE_EUR", quantity, current_price, "buy"
            )

            if result.get("success"):
                return {
                    "success": True,
                    "action": "buy",
                    "reason": "Покупка по стратегии",
                    "quantity": quantity,
                    "price": current_price
                }

        return {
            "success": True,
            "action": "wait",
            "reason": "Ожидание лучшей возможности"
        }

    async def shutdown(self):
        """🛑 Корректное завершение"""
        self.running = False

        try:
            if self.infrastructure:
                await self.infrastructure.shutdown()

            self.logger.info("✅ Бот корректно завершен")

        except Exception as e:
            self.logger.error(f"❌ Ошибка при завершении: {e}")


async def main():
    """🚀 Главная функция"""
    bot = EnhancedHybridBot()

    try:
        await bot.initialize()
        await bot.run()
    except Exception as e:
        logging.error(f"❌ Критическая ошибка: {e}")


if __name__ == "__main__":
    asyncio.run(main())
