import logging
import signal
import sys
import time
from datetime import datetime

# Гибридные импорты с fallback
try:
    from hybrid_config import HybridTradingConfig as TradingConfig
except ImportError:
    from config import TradingConfig

from api_client import ExmoAPIClient
from api_service import APIService
from position_manager import PositionManager
from risk_management import RiskManager

# Гибридные компоненты
try:
    from hybrid_strategies import HybridStrategyManager
    HYBRID_STRATEGIES_AVAILABLE = True
except ImportError:
    from strategies import StrategyManager as HybridStrategyManager
    HYBRID_STRATEGIES_AVAILABLE = False

try:
    from hybrid_analytics import HybridAnalytics
    HYBRID_ANALYTICS_AVAILABLE = True
except ImportError:
    try:
        from simple_analytics import SimpleAnalytics as HybridAnalytics
        HYBRID_ANALYTICS_AVAILABLE = False
    except ImportError:
        HybridAnalytics = None
        HYBRID_ANALYTICS_AVAILABLE = False

from rate_limiter import RateLimitedAPIClient

class HybridTradingBot:
    """🤖 Гибридный торговый бот"""

    def __init__(self):
        self.config = TradingConfig()
        self.setup_logging()

        try:
            self.config.print_summary()
        except ValueError as e:
            self.logger.error(str(e))
            sys.exit(1)

        self.initialize_components()

        # Статистика
        self.start_time = time.time()
        self.cycle_count = 0
        self.successful_trades = 0
        self.failed_trades = 0
        self.running = False

        # Graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        self.logger.info("🚀 Гибридный торговый бот инициализирован")
        self._log_system_capabilities()

    def setup_logging(self):
        """📝 Настройка логирования"""
        import os
        os.makedirs('logs', exist_ok=True)

        logging.basicConfig(
            level=getattr(logging, self.config.LOG_LEVEL),
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(self.config.LOG_FILE, encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)

    def initialize_components(self):
        """🔧 Инициализация компонентов"""

        # API клиент с rate limiting
        api_client = ExmoAPIClient(self.config.API_KEY, self.config.API_SECRET)

        if getattr(self.config, 'RATE_LIMITER_ENABLED', True):
            from rate_limiter import RateLimiter
            rate_limiter = RateLimiter(
                getattr(self.config, 'API_CALLS_PER_MINUTE', 25),
                getattr(self.config, 'API_CALLS_PER_HOUR', 250)
            )
            self.api_client = RateLimitedAPIClient(api_client, rate_limiter)
        else:
            self.api_client = api_client

        # API сервис
        self.api_service = APIService(self.api_client, self.config)

        # Основные менеджеры
        self.position_manager = PositionManager(self.config, self.api_service)
        self.risk_manager = RiskManager(self.config)

        # Гибридный менеджер стратегий
        self.strategy_manager = HybridStrategyManager(
            self.config, self.api_service, self.position_manager
        )

        # Гибридная аналитика
        if HybridAnalytics:
            self.analytics = HybridAnalytics()
        else:
            self.analytics = None

    def _log_system_capabilities(self):
        """📊 Логирование возможностей системы"""

        self.logger.info("🔧 ВОЗМОЖНОСТИ ГИБРИДНОЙ СИСТЕМЫ:")
        self.logger.info(f"   🎯 Гибридные стратегии: {'✅' if HYBRID_STRATEGIES_AVAILABLE else '❌'}")
        self.logger.info(f"   📊 Гибридная аналитика: {'✅' if HYBRID_ANALYTICS_AVAILABLE else '❌'}")

        # Проверяем системы безопасности
        safety_systems = []

        if hasattr(self.strategy_manager, 'emergency_exit') and self.strategy_manager.emergency_exit:
            safety_systems.append("🚨 Аварийный выход")

        if hasattr(self.strategy_manager, 'dca_limiter') and self.strategy_manager.dca_limiter:
            safety_systems.append("🛡️ DCA лимитер")

        if safety_systems:
            self.logger.info("🛡️ АКТИВНЫЕ СИСТЕМЫ БЕЗОПАСНОСТИ:")
            for system in safety_systems:
                self.logger.info(f"   {system}")
        else:
            self.logger.warning("⚠️ Системы безопасности недоступны")

    def run(self):
        """🏃 Основной цикл работы"""

        self.running = True
        self.logger.info("🚀 Гибридный торговый бот запущен!")

        while self.running:
            try:
                self.cycle_count += 1
                cycle_start = time.time()

                # Собираем рыночные данные
                market_data = self._collect_market_data()
                if not market_data:
                    time.sleep(self.config.UPDATE_INTERVAL)
                    continue

                # Проверяем безопасность
                if not self._check_basic_safety(market_data):
                    time.sleep(self.config.UPDATE_INTERVAL)
                    continue

                # Выполняем торговый цикл
                if HYBRID_STRATEGIES_AVAILABLE:
                    result = self.strategy_manager.execute_hybrid_cycle(market_data)
                else:
                    result = self.strategy_manager.execute_cycle(market_data)

                # Обрабатываем результат
                self._process_result(result, market_data)

                # Логируем каждый 50-й цикл
                if self.cycle_count % 50 == 0:
                    self._log_statistics()

                # Рассчитываем время ожидания
                cycle_time = time.time() - cycle_start
                sleep_time = max(0, self.config.UPDATE_INTERVAL - cycle_time)
                if sleep_time > 0:
                    time.sleep(sleep_time)

            except KeyboardInterrupt:
                self.logger.info("⌨️ Получен сигнал остановки")
                break
            except Exception as e:
                self.logger.error(f"❌ Критическая ошибка в цикле #{self.cycle_count}: {e}")
                time.sleep(self.config.UPDATE_INTERVAL * 2)

        self.shutdown()

    def _collect_market_data(self) -> dict:
        """📊 Сбор рыночных данных"""
        try:
            current_price = self.api_service.get_current_price(self.config.get_pair())
            balance_eur = self.api_service.get_balance(self.config.CURRENCY_2)

            if current_price <= 0 or balance_eur < 0:
                return None

            return {
                'current_price': current_price,
                'balance': balance_eur,
                'timestamp': time.time()
            }
        except Exception as e:
            self.logger.error(f"❌ Ошибка сбора данных: {e}")
            return None

    def _check_basic_safety(self, market_data: dict) -> bool:
        """🛡️ Базовая проверка безопасности"""
        try:
            # Проверка экстренной остановки
            emergency_stop, reason = self.risk_manager.emergency_stop_check(market_data['balance'])
            if emergency_stop:
                self.logger.error(f"🚨 ЭКСТРЕННАЯ ОСТАНОВКА: {reason}")
                return False

            # Проверка цены
            current_price = market_data['current_price']
            if current_price < 0.05 or current_price > 2.0:
                self.logger.warning(f"⚠️ Подозрительная цена DOGE: {current_price}")
                return False

            return True
        except Exception as e:
            self.logger.error(f"❌ Ошибка проверки безопасности: {e}")
            return False

    def _process_result(self, result: dict, market_data: dict):
        """📋 Обработка результата"""
        if not result.get('success'):
            self.failed_trades += 1
            return

        action = result.get('action', 'hold')
        reason = result.get('reason', '')

        # Эмодзи для действий
        action_emojis = {
            'pyramid_sell': '🏗️',
            'dca_buy': '🛒', 
            'emergency_exit': '🚨',
            'hold': '💎'
        }

        emoji = action_emojis.get(action, '🔄')
        self.logger.info(f"{emoji} {action}: {reason}")

        # Учитываем торговые операции
        if result.get('trade_executed'):
            self.successful_trades += 1

            # Записываем в аналитику
            if self.analytics:
                trade_type = 'buy' if 'buy' in action else 'sell'
                strategy = action.split('_')[0] if '_' in action else 'unknown'

                self.analytics.record_trade(
                    trade_type=trade_type,
                    quantity=result.get('quantity', 0),
                    price=result.get('price', 0),
                    pair=self.config.get_pair(),
                    strategy=strategy
                )

        # Обновляем аналитику
        if self.analytics:
            self.analytics.update_cycle_stats(result)
            self.analytics.update_balance(market_data['balance'])

    def _log_statistics(self):
        """📊 Логирование статистики"""
        uptime = time.time() - self.start_time
        success_rate = (self.successful_trades / max(1, self.successful_trades + self.failed_trades)) * 100

        self.logger.info(f"📊 ГИБРИДНАЯ СТАТИСТИКА (цикл #{self.cycle_count}):")
        self.logger.info(f"   ⏱️ Время работы: {uptime/3600:.1f} часов")
        self.logger.info(f"   ✅ Успешные сделки: {self.successful_trades}")
        self.logger.info(f"   ❌ Неудачные циклы: {self.failed_trades}")
        self.logger.info(f"   📈 Успешность: {success_rate:.1f}%")

    def _signal_handler(self, signum, frame):
        """⌨️ Обработчик сигналов"""
        self.logger.info(f"📡 Получен сигнал {signum}, начинаем остановку...")
        self.running = False

    def shutdown(self):
        """🔚 Завершение работы"""
        try:
            uptime = time.time() - self.start_time

            self.logger.info("🔚 ЗАВЕРШЕНИЕ РАБОТЫ ГИБРИДНОГО БОТА")
            self.logger.info(f"   ⏱️ Время работы: {uptime/3600:.1f} часов")
            self.logger.info(f"   🔄 Всего циклов: {self.cycle_count}")
            self.logger.info(f"   ✅ Успешных сделок: {self.successful_trades}")

            # Сохраняем позиции
            self.position_manager.save_positions_to_file()

            self.logger.info("✅ Гибридный бот завершен корректно")

        except Exception as e:
            self.logger.error(f"❌ Ошибка при завершении: {e}")

if __name__ == "__main__":
    print("🚀 ГИБРИДНЫЙ ТОРГОВЫЙ БОТ DOGE")
    print("=" * 50)
    bot = HybridTradingBot()
    bot.run()
