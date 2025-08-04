import logging
import signal
import sys
import time
from datetime import datetime

from config import TradingConfig
from api_client import ExmoAPIClient
from api_service import APIService
from position_manager import PositionManager
from risk_management import RiskManager
from strategies import StrategyManager
from emergency_exit_manager import EmergencyExitManager
from dca_limiter import DCALimiter
from rate_limiter import RateLimitedAPIClient
from simple_analytics import SimpleAnalytics


class TradingBot:
    """🤖 Основной торговый бот"""

    def __init__(self):
        self.config = TradingConfig()
        self.setup_logging()

        # Проверяем конфигурацию
        try:
            self.config.print_summary()
        except ValueError as e:
            self.logger.error(str(e))
            sys.exit(1)

        # Инициализация компонентов
        self.api_client = ExmoAPIClient(self.config.API_KEY, self.config.API_SECRET)
        self.api_service = APIService(self.api_client, self.config)
        self.position_manager = PositionManager(self.config, self.api_service)
        self.risk_manager = RiskManager(self.config)
        self.strategy_manager = StrategyManager(self.config, self.api_service, self.position_manager)

        # 🚨 Системы безопасности
        if getattr(self.config, 'EMERGENCY_EXIT_ENABLED', False):
            self.emergency_exit = EmergencyExitManager(self.config, self.api_service, self.position_manager)
            self.logger.info("🚨 EmergencyExitManager активирован")
        else:
            self.emergency_exit = None
            
        if getattr(self.config, 'DCA_LIMITER_ENABLED', False):
            self.dca_limiter = DCALimiter(self.config)
            self.logger.info("🛡️ DCALimiter активирован")
        else:
            self.dca_limiter = None
        
        # 📊 Аналитика
        if getattr(self.config, 'ANALYTICS_ENABLED', False):
            self.analytics = SimpleAnalytics()
            self.last_analytics_report = time.time()
            self.logger.info("📊 SimpleAnalytics активирована")
        else:
            self.analytics = None
        
        # ⚡ Rate Limiting для API клиента
        if getattr(self.config, 'RATE_LIMITER_ENABLED', False):
            from rate_limiter import RateLimiter
            rate_limiter = RateLimiter(
                getattr(self.config, 'API_CALLS_PER_MINUTE', 30),
                getattr(self.config, 'API_CALLS_PER_HOUR', 300)
            )
            self.api_client = RateLimitedAPIClient(self.api_client, rate_limiter)
            self.logger.info("⚡ RateLimiter активирован")

        # Статистика
        self.start_time = time.time()
        self.cycle_count = 0
        self.successful_trades = 0
        self.failed_trades = 0
        self.running = False

        # Graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        self.logger.info("🤖 Торговый бот инициализирован")

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

    def initialize(self) -> bool:
        """🔧 Инициализация перед запуском"""
        try:
            # Проверка API
            user_info = self.api_client.get_user_info()
            if not user_info:
                self.logger.error("❌ Не удалось подключиться к API")
                return False

            # Проверка балансов
            eur_balance = self.api_service.get_balance(self.config.CURRENCY_2)
            doge_balance = self.api_service.get_balance(self.config.CURRENCY_1)

            self.logger.info(f"💰 Баланс: {eur_balance:.4f} {self.config.CURRENCY_2}, "
                           f"{doge_balance:.4f} {self.config.CURRENCY_1}")

            if eur_balance < 1.0 and doge_balance < 1.0:
                self.logger.error("❌ Недостаточно средств для торговли")
                return False

            # Загрузка позиций
            position_data = self.position_manager.get_accurate_position_data(self.config.CURRENCY_1)
            if position_data['quantity'] > 0:
                self.logger.info(f"📊 Загружена позиция: {position_data['quantity']:.4f} "
                               f"по средней цене {position_data['avg_price']:.8f}")

            return True

        except Exception as e:
            self.logger.error(f"❌ Ошибка инициализации: {e}")
            return False

    def run(self):
        """🏃 Основной цикл работы"""
        if not self.initialize():
            self.logger.error("❌ Инициализация неудачна, завершение")
            return

        self.running = True
        self.logger.info("🚀 Торговый бот запущен!")

        while self.running:
            try:
                self.cycle_count += 1
                cycle_start = time.time()

                # Собираем рыночные данные
                market_data = self._collect_market_data()
                if not market_data:
                    self.logger.warning("⚠️ Не удалось получить рыночные данные")
                    time.sleep(self.config.UPDATE_INTERVAL)
                    continue

                # Проверяем безопасность
                if not self._check_safety(market_data):
                    self.logger.warning("⚠️ Проверка безопасности не пройдена")
                    time.sleep(self.config.UPDATE_INTERVAL)
                    continue

                # Выполняем торговый цикл
                
                # 🚨 Проверка аварийных условий
                if self.emergency_exit:
                    emergency_result = self.emergency_exit.check_emergency_conditions(
                        self.config.CURRENCY_1, market_data['current_price']
                    )
                    
                    if emergency_result.should_exit:
                        self.logger.critical(f"🚨 АВАРИЙНЫЙ ВЫХОД: {emergency_result.reason}")
                        exit_result = self.emergency_exit.execute_emergency_exit(
                            self.config.CURRENCY_1, emergency_result
                        )
                        
                        if exit_result['success'] and self.analytics:
                            self.analytics.update_cycle_stats({'emergency_exit': True})
                        
                        time.sleep(self.config.UPDATE_INTERVAL * 2)
                        continue
                
                result = self.strategy_manager.execute_cycle(market_data)

                # Обрабатываем результат
                self._process_result(result)

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
                self.risk_manager.register_error()
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

    def _check_safety(self, market_data: dict) -> bool:
        """🛡️ Проверка безопасности"""
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

    def _process_result(self, result: dict):
        """📋 Обработка результата"""
        if not result.get('success'):
            self.failed_trades += 1
            self.logger.warning(f"⚠️ Неуспешный цикл: {result.get('reason')}")
            return

        action = result.get('action', 'hold')
        reason = result.get('reason', '')

        # Эмодзи для действий
        action_emojis = {
            'pyramid_sell': '🏗️',
            'dca_buy': '🛒', 
            'hold': '💎',
            'wait': '⏸️'
        }

        emoji = action_emojis.get(action, '🔄')
        self.logger.info(f"{emoji} {action}: {reason}")

        # Учитываем торговые операции
        if result.get('trade_executed'):
            self.successful_trades += 1
            self.risk_manager.reset_error_count()

    def _log_statistics(self):
        """📊 Логирование статистики"""
        uptime = time.time() - self.start_time
        success_rate = (self.successful_trades / max(1, self.successful_trades + self.failed_trades)) * 100

        self.logger.info(f"📊 СТАТИСТИКА (цикл #{self.cycle_count}):")
        self.logger.info(f"   ⏱️ Время работы: {uptime/3600:.1f} часов")
        self.logger.info(f"   ✅ Успешные сделки: {self.successful_trades}")
        self.logger.info(f"   ❌ Неудачные циклы: {self.failed_trades}")
        self.logger.info(f"   📈 Успешность: {success_rate:.1f}%")

        # Кэш статистика
        cache_stats = self.api_service.get_cache_stats()
        self.logger.info(f"   🌐 Кэш записей: {cache_stats['total_entries']}")

    def _signal_handler(self, signum, frame):
        """⌨️ Обработчик сигналов"""
        self.logger.info(f"📡 Получен сигнал {signum}, начинаем остановку...")
        self.running = False

    def shutdown(self):
        """🔚 Завершение работы"""
        try:
            uptime = time.time() - self.start_time

            self.logger.info("🔚 ЗАВЕРШЕНИЕ РАБОТЫ БОТА")
            self.logger.info(f"   ⏱️ Время работы: {uptime/3600:.1f} часов")
            self.logger.info(f"   🔄 Всего циклов: {self.cycle_count}")
            self.logger.info(f"   ✅ Успешных сделок: {self.successful_trades}")

            # Сохраняем позиции
            self.position_manager.save_positions_to_file()
            self.logger.info("💾 Позиции сохранены")

            self.logger.info("✅ Бот завершен корректно")

        except Exception as e:
            self.logger.error(f"❌ Ошибка при завершении: {e}")


if __name__ == "__main__":
    print("🤖 ТОРГОВЫЙ БОТ DOGE")
    print("=" * 30)

    bot = TradingBot()
    bot.run()
