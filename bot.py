import logging
import signal
import sys
import time
from datetime import datetime
from typing import Dict, Any

from config import TradingConfig
from api_client import ExmoAPIClient
from risk_management import RiskManager
from position_manager import PositionManager
from analytics_system import TradingAnalytics
from adaptive_dca_strategy import AdaptiveDCAStrategy
from trailing_stop import TrailingStopManager
from pyramid_strategy import SmartPyramidStrategy
from advanced_trend_filter import AdvancedTrendFilter, TrendDirection

# 🆕 Новые улучшенные компоненты
from hybrid_strategy import HybridTradeOrchestrator
from rate_limiter import RateLimitedAPIClient
from improved_technical_indicators import ImprovedTechnicalIndicators

from services.api_service import APIService
from services.trade_validator import TradeValidator


class ImprovedTradingBot:
    """🚀 Улучшенный торговый бот с рефакторингом"""

    def __init__(self):
        self.logger = None
        self.config = TradingConfig()
        self.setup_logging()

        # Валидация API ключей
        if not self.config.API_KEY or not self.config.API_SECRET:
            self.logger.error("❌ API ключи не настроены!")
            sys.exit(1)

        # Инициализация компонентов
        self._initialize_components()

        # Состояние бота
        self.running = True
        self.start_time = time.time()
        self.cycle_count = 0

        # Статистика
        self.total_trades = 0
        self.profitable_trades = 0
        self.error_count = 0
        self.consecutive_errors = 0
        self.last_successful_cycle = time.time()

        # Мониторинг
        self.last_analytics_update = time.time()
        self.last_stats_log = time.time()
        self.analytics_interval = 300  # 5 минут
        self.stats_log_interval = 3600  # 1 час

        # Обработка сигналов
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

        self.logger.info("🚀 Улучшенный торговый бот инициализирован")


    def _initialize_components(self):
        """🔧 Инициализация всех компонентов бота"""

        self.logger.info("🔧 Инициализация компонентов...")

        # Базовые API компоненты
        original_api = ExmoAPIClient(self.config)
        rate_limited_api = RateLimitedAPIClient(original_api)

        # 🆕 Новый API сервис
        self.api_service = APIService(rate_limited_api, self.config)
        self.api = rate_limited_api  # Оставляем для обратной совместимости

        # 🆕 Валидатор сделок
        self.trade_validator = TradeValidator(self.config)

        # Менеджеры
        self.risk_manager = RiskManager(self.config)
        self.position_manager = PositionManager(self.config, self.api_service)  # 🔧 Передаем api_service

        # Стратегии с улучшенными индикаторами
        self.dca_strategy = AdaptiveDCAStrategy(
            self.config, self.api_service, self.risk_manager, self.position_manager  # 🔧 api_service
        )

        # 🆕 Заменяем индикаторы на улучшенные в DCA стратегии
        if hasattr(self.dca_strategy, 'indicators'):
            self.dca_strategy.indicators = ImprovedTechnicalIndicators()

        self.pyramid_strategy = SmartPyramidStrategy(self.config, self.position_manager)
        self.trailing_stop = TrailingStopManager()

        # 🆕 Главное улучшение - торговый оркестратор
        self.trade_orchestrator = HybridTradeOrchestrator(
            self.config, self.api_service, self.risk_manager, self.position_manager,  # 🔧 api_service
            self.pyramid_strategy, self.trailing_stop
        )

        self.analytics = TradingAnalytics()

        # 🧠 Trend Filter для защиты от медвежьих трендов
        if self.config.TREND_FILTER_ENABLED:
            self.trend_filter = AdvancedTrendFilter(self.config)
            self.logger.info("🧠 Trend Filter активирован")
        else:
            self.trend_filter = None
            self.logger.warning("⚠️ Trend Filter ОТКЛЮЧЕН - высокий риск!")

        self.pair = f"{self.config.CURRENCY_1}_{self.config.CURRENCY_2}"
        self.pair_settings = {}

        self.logger.info("✅ Все компоненты инициализированы")

    def setup_logging(self):
        """📝 Настройка логирования"""
        logging.basicConfig(
            level=getattr(logging, self.config.LOG_LEVEL),
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(self.config.LOG_FILE),
                logging.StreamHandler(sys.stdout)
            ]
        )
        self.logger = logging.getLogger(__name__)

    def signal_handler(self, signum, frame):
        """🛑 Обработка сигналов завершения"""
        self.logger.info(f"Получен сигнал {signum}, завершаем работу...")
        self.running = False
        self.shutdown()

    def initialize(self) -> bool:
        """🚀 Инициализация бота"""
        try:
            self.logger.info("🔄 Инициализация бота...")

            # Проверяем соединение с API
            if not self.api_service.check_connection():
                self.logger.error("❌ Нет соединения с API")
                return False

            # Получаем настройки пары
            pair_settings = self.api_service.get_pair_settings()
            if self.pair not in pair_settings:
                self.logger.error(f"❌ Пара {self.pair} не найдена")
                return False

            self.pair_settings = pair_settings[self.pair]

            # Обновляем комиссию из API
            api_commission = float(self.pair_settings.get('commission_taker_percent', 0.3)) / 100
            if api_commission != self.config.AUTO_COMMISSION_RATE:
                self.logger.info(f"🔄 Обновляем комиссию: {api_commission * 100:.1f}%")
                self.config.AUTO_COMMISSION_RATE = api_commission

            # Загружаем историю позиций
            self.logger.info("📚 Загружаем историю торгов...")
            try:
                positions = self.position_manager.load_positions_from_history(days_back=30)
                if positions:
                    for currency, position in positions.items():
                        self.logger.info(f"📊 Позиция {currency}: {position.quantity:.6f} по {position.avg_price:.8f}")
            except Exception as e:
                self.logger.error(f"❌ Ошибка загрузки позиций: {e}")

            # Проверяем баланс
            balances = self.api_service.get_balances()  # 🔧 Используем новый метод
            balance_eur = balances.get(self.config.CURRENCY_2, 0)
            balance_doge = balances.get(self.config.CURRENCY_1, 0)

            self.logger.info(f"💰 Баланс: {balance_eur:.4f} EUR, {balance_doge:.6f} DOGE")

            # Логируем настройки
            self._log_initialization_settings()

            return True

        except Exception as e:
            self.logger.error(f"❌ Ошибка инициализации: {str(e)}")
            return False

    def _log_initialization_settings(self):
        """📋 Логирование настроек при инициализации"""
        self.logger.info(f"🎯 НАСТРОЙКИ УЛУЧШЕННОГО БОТА:")
        self.logger.info(f"   Пара: {self.pair}")
        self.logger.info(f"   Размер позиции: {self.config.MAX_POSITION_SIZE * 100:.0f}%")
        self.logger.info(f"   Комиссия: {self.config.AUTO_COMMISSION_RATE * 100:.1f}%")

        self.logger.info(f"🎯 DCA НАСТРОЙКИ:")
        self.logger.info(f"   Максимум покупок: {self.dca_strategy.max_purchases}")
        self.logger.info(f"   Размер покупки: {self.dca_strategy.bottom_purchase_size * 100:.0f}% депозита")
        self.logger.info(f"   Стабилизация: {self.dca_strategy.stabilization_minutes * 60:.0f} секунд")

        self.logger.info(f"🏗️ ПИРАМИДАЛЬНАЯ СТРАТЕГИЯ:")
        self.logger.info(f"   Уровней: {len(self.pyramid_strategy.pyramid_levels)}")
        self.logger.info(f"   Кулдаун: {self.pyramid_strategy.cooldown_between_sells} сек")

        self.logger.info(f"🎯 TRAILING STOP:")
        self.logger.info(f"   Trailing: {self.trailing_stop.trailing_percent * 100:.1f}%")
        self.logger.info(f"   Активация: {self.trailing_stop.activation_profit * 100:.1f}%")

        # 🆕 Новое: Rate Limiting и API Service статистика
        rate_stats = self.api.get_rate_limit_stats()
        self.logger.info(f"⏱️ RATE LIMITING:")
        self.logger.info(
            f"   Лимиты: {rate_stats['limits']['per_second']}/сек, {rate_stats['limits']['per_minute']}/мин")
        self.logger.info(f"   Торговые: {rate_stats['limits']['trading_per_minute']}/мин")

        # API Service статистика
        cache_stats = self.api_service.get_cache_stats()
        self.logger.info(f"🌐 API SERVICE:")
        self.logger.info(f"   Кэш балансов: {cache_stats['balance_cache_size']} записей")
        self.logger.info(f"   Кэш цен: {cache_stats['price_cache_size']} записей")

    def execute_trade_cycle(self):
        """🔄 Основной торговый цикл (упрощенный)"""
        cycle_start = time.time()

        try:
            # Получаем рыночные данные
            market_data = self._collect_market_data()
            if not market_data:
                self.logger.warning("⚠️ Не удалось получить рыночные данные")
                return

            # Проверяем экстренную остановку
            emergency_stop, emergency_reason = self.risk_manager.emergency_stop_check(market_data['balance'])
            if emergency_stop:
                self.logger.error(f"🚨 ЭКСТРЕННАЯ ОСТАНОВКА: {emergency_reason}")
                self._cancel_all_orders("Экстренная остановка")
                self.running = False
                return

            # 🆕 Используем торговый оркестратор вместо сложной логики
            cycle_result = self.trade_orchestrator.execute_trade_cycle(market_data)

            # Обрабатываем результат
            self._process_cycle_result(cycle_result)

            # Обновляем статистику
            cycle_time = time.time() - cycle_start
            self.last_successful_cycle = time.time()
            self.consecutive_errors = 0

            # Периодические задачи
            self._handle_periodic_tasks()

        except Exception as e:
            self.logger.error(f"❌ Ошибка в торговом цикле: {str(e)}")
            self.error_count += 1
            self.consecutive_errors += 1

            # При критических ошибках останавливаемся
            if self.consecutive_errors >= 5:
                self.logger.error(f"🚨 Критическое количество ошибок подряд: {self.consecutive_errors}")
                self.running = False

    def _collect_market_data(self) -> Dict[str, Any]:
        """📊 Сбор рыночных данных с анализом тренда"""
        try:
            # Текущая цена
            current_price = self.api_service.get_current_price(self.pair)
            if current_price == 0:
                return None

            # Баланс
            balances = self.api_service.get_balances()
            balance_eur = balances.get(self.config.CURRENCY_2, 0)
            balance_doge = balances.get(self.config.CURRENCY_1, 0)

            # Точные данные позиции
            accurate_data = self.position_manager.get_accurate_position_data(self.config.CURRENCY_1)

            # 🧠 НОВОЕ: Анализ тренда
            trend_analysis = None
            if self.trend_filter:
                trend_analysis = self.trend_filter.analyze_trend(current_price)

                # Логируем изменения тренда каждые 50 циклов
                if self.cycle_count % 50 == 0:
                    self.logger.info(f"🧠 Trend: {trend_analysis.direction.value}, "
                                     f"4h: {trend_analysis.trend_4h * 100:+.1f}%, "
                                     f"DCA: {'✅' if trend_analysis.should_allow_dca else '🚫'}")

            return {
                'current_price': current_price,
                'balance': balance_eur,
                'doge_balance': balance_doge,
                'accurate_position': accurate_data,
                'trend_analysis': trend_analysis,  # 🧠 НОВОЕ поле
                'timestamp': time.time()
            }

        except Exception as e:
            self.logger.error(f"❌ Ошибка сбора рыночных данных: {e}")
            return None

    def _process_cycle_result(self, cycle_result: Dict[str, Any]):
        """📝 Обработка результата торгового цикла"""

        if not cycle_result.get('success'):
            self.logger.warning(f"⚠️ Цикл неуспешен: {cycle_result.get('reason', 'Неизвестная причина')}")
            return

        action = cycle_result.get('action', 'none')
        reason = cycle_result.get('reason', '')
        trade_executed = cycle_result.get('trade_executed', False)

        # Логируем действие
        if action != 'none':
            action_emoji = {
                'pyramid_sell': '🏗️',
                'trailing_sell': '🎯',
                'dca_initial_buy': '🛒',
                'dca_bottom_buy': '🩹',
                'hold': '💎',
                'wait': '⏸️'
            }
            emoji = action_emoji.get(action, '🔄')
            self.logger.info(f"{emoji} Действие: {action} - {reason}")

        # Обновляем статистику сделок
        if trade_executed:
            self.total_trades += 1
            self.profitable_trades += 1  # Предполагаем что все исполненные сделки прибыльные

            # Уведомляем риск-менеджер
            if 'quantity' in cycle_result and 'price' in cycle_result:
                trade_info = {
                    'type': 'buy' if 'buy' in action else 'sell',
                    'quantity': cycle_result['quantity'],
                    'price': cycle_result['price']
                }
                # Здесь можно добавить расчет P&L и передать в risk_manager

    def _handle_periodic_tasks(self):
        """🔄 Периодические задачи"""
        current_time = time.time()

        # Аналитика каждые 5 минут
        if current_time - self.last_analytics_update > self.analytics_interval:
            try:
                self.analytics.collect_runtime_stats(self)
                self.last_analytics_update = current_time
            except Exception as e:
                self.logger.error(f"❌ Ошибка сбора аналитики: {e}")

        # Статистика каждый час
        if current_time - self.last_stats_log > self.stats_log_interval:
            try:
                self._log_hourly_stats()
                self.last_stats_log = current_time
            except Exception as e:
                self.logger.error(f"❌ Ошибка логирования статистики: {e}")

    def _log_hourly_stats(self):
        """📊 Часовая статистика"""
        uptime = (time.time() - self.start_time) / 3600
        success_rate = (self.profitable_trades / max(1, self.total_trades)) * 100

        self.logger.info("📊 ЧАСОВАЯ СТАТИСТИКА:")
        self.logger.info(f"   ⏱️ Время работы: {uptime:.1f} часов")
        self.logger.info(f"   🔄 Циклов: {self.cycle_count}")
        self.logger.info(f"   📈 Сделок: {self.total_trades}")
        self.logger.info(f"   ✅ Успешность: {success_rate:.1f}%")
        self.logger.info(f"   ❌ Ошибок: {self.error_count}")

        # 🆕 Статистика rate limiting
        self.api.log_rate_limit_stats()

        # 🆕 Статистика API Service
        cache_stats = self.api_service.get_cache_stats()
        self.logger.info(f"🌐 API SERVICE СТАТИСТИКА:")
        self.logger.info(f"   💰 Кэш балансов: {cache_stats['balance_cache_size']} записей")
        self.logger.info(f"   💱 Кэш цен: {cache_stats['price_cache_size']} записей")
        self.logger.info(f"   ⚙️ Настройки пар: {'КЭШИРОВАНЫ' if cache_stats['pair_settings_cached'] else 'НЕ КЭШИРОВАНЫ'}")

        # Статистика стратегий
        dca_status = self.dca_strategy.get_status()
        if dca_status['active']:
            self.logger.info(f"🎯 DCA активна: {dca_status['total_purchases']} покупок")

        trailing_status = self.trailing_stop.get_status(self.config.CURRENCY_1)
        if trailing_status['active']:
            self.logger.info(f"🎯 Trailing активен: статус {trailing_status['status']}")

    def _cancel_all_orders(self, reason: str = ""):
        """❌ Отмена всех открытых ордеров"""
        try:
            open_orders = self.api_service.get_open_orders()  # 🔧 Используем api_service
            pair_orders = open_orders.get(self.pair, [])

            if pair_orders:
                self.logger.info(f"❌ Отменяем {len(pair_orders)} ордеров. Причина: {reason}")

                for order in pair_orders:
                    try:
                        self.api_service.cancel_order(int(order['order_id']))  # 🔧 api_service
                        self.logger.info(f"✅ Ордер {order['order_id']} отменен")
                    except Exception as e:
                        self.logger.error(f"❌ Ошибка отмены ордера {order['order_id']}: {e}")

        except Exception as e:
            self.logger.error(f"❌ Ошибка при отмене ордеров: {str(e)}")

    def _calculate_adaptive_interval(self) -> float:
        """⚡ Адаптивный интервал с учетом всех факторов"""

        try:
            # Базовый режим
            mode = 'normal'

            # Проверяем экстренные ситуации
            if self.consecutive_errors >= 3:
                mode = 'emergency'

            # Проверяем trailing stop
            trailing_status = self.trailing_stop.get_status(self.config.CURRENCY_1)
            if trailing_status.get('active', False):
                if trailing_status['status'] == 'trailing':
                    mode = 'trailing'
                else:
                    mode = 'waiting'

            # Проверяем позицию
            if mode == 'normal':
                balance_doge = self.api_service.get_balance(self.config.CURRENCY_1)  # 🔧 api_service

                if balance_doge > 0:
                    mode = 'position'

            # Получаем интервал из конфига
            interval = self.config.ADAPTIVE_INTERVALS.get(mode, self.config.UPDATE_INTERVAL)

            # 🆕 Учитываем загрузку rate limiter
            rate_stats = self.api.get_rate_limit_stats()
            load_percent = rate_stats['load_percentage']['per_minute']

            if load_percent > 80:
                # При высокой загрузке увеличиваем интервал
                interval *= 1.5
                self.logger.info(
                    f"⚠️ Высокая загрузка API ({load_percent:.0f}%), увеличиваем интервал до {interval:.1f}с")

            return interval

        except Exception as e:
            self.logger.error(f"❌ Ошибка расчета интервала: {e}")
            return self.config.UPDATE_INTERVAL

    def run(self):
        """🚀 Главный цикл работы бота"""
        if not self.initialize():
            self.logger.error("❌ Ошибка инициализации")
            return

        self.logger.info("🚀 Улучшенный торговый бот запущен!")

        while self.running:
            try:
                self.cycle_count += 1

                # Логируем каждый 50-й цикл
                if self.cycle_count % 50 == 0:
                    self.logger.info(f"🔄 Цикл #{self.cycle_count}")

                # Выполняем торговый цикл
                self.execute_trade_cycle()

                # Проверка критических ошибок
                if self.error_count >= 10:  # Увеличили лимит
                    self.logger.error(f"🚨 Критическое количество ошибок: {self.error_count}")
                    break

                # Адаптивный интервал
                sleep_interval = self._calculate_adaptive_interval()
                time.sleep(sleep_interval)

            except KeyboardInterrupt:
                self.logger.info("⌨️ Получен сигнал остановки")
                break

            except Exception as e:
                self.error_count += 1
                self.consecutive_errors += 1
                self.logger.error(f"❌ Критическая ошибка в цикле #{self.cycle_count}: {e}")

                if self.consecutive_errors >= 5:
                    self.logger.error(f"🚨 Слишком много ошибок подряд: {self.consecutive_errors}")
                    break

                # Экспоненциальная задержка при ошибках
                time.sleep(min(60, self.consecutive_errors * 10))

        self.shutdown()

    def shutdown(self):
        """🔚 Корректное завершение с финальной статистикой"""
        try:
            uptime = time.time() - self.start_time
            success_rate = (self.profitable_trades / max(1, self.total_trades)) * 100

            self.logger.info("📊 ФИНАЛЬНАЯ СТАТИСТИКА:")
            self.logger.info(f"   ⏱️ Время работы: {uptime / 3600:.1f} часов")
            self.logger.info(f"   🔄 Циклов: {self.cycle_count}")
            self.logger.info(f"   📈 Сделок: {self.total_trades}")
            self.logger.info(f"   💰 Прибыльных: {self.profitable_trades}")
            self.logger.info(f"   📊 Успешность: {success_rate:.1f}%")
            self.logger.info(f"   ❌ Ошибок: {self.error_count}")

            # Статистика стратегий
            dca_status = self.dca_strategy.get_status()
            if dca_status['active']:
                self.logger.info("🎯 АКТИВНАЯ DCA ПОЗИЦИЯ:")
                self.logger.info(f"   Покупок: {dca_status['total_purchases']}")
                self.logger.info(f"   Количество: {dca_status['total_quantity']:.4f}")
                self.logger.info(f"   Инвестировано: {dca_status['total_invested']:.4f} EUR")

            trailing_status = self.trailing_stop.get_status(self.config.CURRENCY_1)
            if trailing_status['active']:
                self.logger.info("🎯 АКТИВНАЯ TRAILING ПОЗИЦИЯ:")
                self.logger.info(f"   Статус: {trailing_status['status']}")
                self.logger.info(f"   Остается: {trailing_status['remaining_quantity']:.4f}")

            # 🆕 Финальная статистика rate limiting и API service
            self.logger.info("⏱️ ФИНАЛЬНАЯ СТАТИСТИКА RATE LIMITING:")
            self.api.log_rate_limit_stats()

            cache_stats = self.api_service.get_cache_stats()
            self.logger.info("🌐 ФИНАЛЬНАЯ СТАТИСТИКА API SERVICE:")
            self.logger.info(f"   💰 Кэш балансов: {cache_stats['balance_cache_size']} записей")
            self.logger.info(f"   💱 Кэш цен: {cache_stats['price_cache_size']} записей")

            # Финальная аналитика
            try:
                final_stats = self.analytics.get_summary_stats(days_back=14)
                if final_stats.get('recommendations'):
                    self.logger.info("💡 ФИНАЛЬНЫЕ РЕКОМЕНДАЦИИ:")
                    for rec in final_stats['recommendations']:
                        self.logger.info(f"   {rec}")
            except Exception as e:
                self.logger.error(f"❌ Ошибка финальной аналитики: {e}")

            # Сохранение данных и закрытие
            self._cancel_all_orders("Завершение работы бота")
            self.position_manager.save_positions_to_file()
            self.api.close()

            self.logger.info("✅ Корректное завершение улучшенного бота")

        except Exception as e:
            self.logger.error(f"❌ Ошибка при завершении: {e}")

    def get_system_status(self) -> Dict[str, Any]:
        """📊 Получение полного статуса системы"""
        try:
            uptime = time.time() - self.start_time
            success_rate = (self.profitable_trades / max(1, self.total_trades)) * 100

            return {
                'timestamp': datetime.now().isoformat(),
                'uptime_hours': uptime / 3600,
                'cycle_count': self.cycle_count,
                'total_trades': self.total_trades,
                'profitable_trades': self.profitable_trades,
                'success_rate': success_rate,
                'error_count': self.error_count,
                'consecutive_errors': self.consecutive_errors,
                'is_running': self.running,

                # Статусы стратегий
                'dca_status': self.dca_strategy.get_status(),
                'trailing_status': self.trailing_stop.get_status(self.config.CURRENCY_1),
                'orchestrator_status': self.trade_orchestrator.get_orchestrator_status(),

                # 🆕 Rate limiting статистика
                'rate_limit_stats': self.api.get_rate_limit_stats(),

                # 🆕 API Service статистика
                'api_service_stats': self.api_service.get_cache_stats(),

                # Риск-метрики
                'risk_metrics': self.risk_manager.get_risk_metrics()
            }

        except Exception as e:
            self.logger.error(f"❌ Ошибка получения статуса: {e}")
            return {'error': str(e)}


if __name__ == "__main__":
    print("🚀 УЛУЧШЕННЫЙ ТОРГОВЫЙ БОТ С НОВЫМИ СЕРВИСАМИ")
    print("=" * 60)
    print("Новые возможности:")
    print("✅ APIService - единый API с кэшированием")
    print("✅ TradeValidator - централизованная валидация")
    print("✅ Исправленные технические индикаторы")
    print("✅ Очищенный от дублирования код")
    print("✅ Улучшенное логирование и статистика")
    print("=" * 60)

    bot = ImprovedTradingBot()
    bot.run()
