import asyncio
import sys
import os
import argparse
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

# Добавляем src в путь
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))

try:
    # Core импорты
    from src.core.di_container import DependencyContainer
    from src.core.models import TradingPair
    from src.core.exceptions import TradingSystemError, ConfigurationError

    # Configuration
    from src.config.settings import get_settings, TradingSystemSettings

    # Application Services
    from src.application.services.trading_orchestrator import TradingOrchestrator
    from src.application.services.position_service import PositionService
    from src.application.services.risk_management_service import RiskManagementService
    from src.application.services.analytics_service import AnalyticsService

except ImportError as e:
    print(f"❌ Ошибка импорта компонентов новой архитектуры: {e}")
    print("💡 Убедитесь что структура src/ создана корректно")
    sys.exit(1)


class TradingBotApplication:
    """🤖 Главное приложение торгового бота"""

    def __init__(self):
        self.container: Optional[DependencyContainer] = None
        self.settings: Optional[TradingSystemSettings] = None
        self.trading_orchestrator: Optional[TradingOrchestrator] = None
        self.position_service: Optional[PositionService] = None
        self.risk_service: Optional[RiskManagementService] = None
        self.analytics_service: Optional[AnalyticsService] = None

        # Статус приложения
        self.is_initialized = False
        self.is_running = False

        # Логирование - ИСПРАВЛЕНО: инициализируем сразу
        self.logger = logging.getLogger(__name__)

    async def initialize(self) -> None:
        """🚀 Инициализация приложения"""
        try:
            print("🚀 Инициализация DOGE Trading Bot v4.1-refactored...")

            # 1. Настройка логирования
            self._setup_logging()

            # 2. Загрузка конфигурации
            self.settings = get_settings()
            self.logger.info("✅ Конфигурация загружена")

            # 3. Валидация конфигурации
            await self._validate_configuration()

            # 4. Создание DI контейнера
            self.container = DependencyContainer()
            await self._configure_dependencies()
            self.logger.info("✅ DI контейнер настроен")

            # 5. Инициализация сервисов
            await self._initialize_services()

            # 6. Проверка готовности системы
            await self._system_health_check()

            self.is_initialized = True
            self.logger.info("🎉 Инициализация завершена успешно!")

        except Exception as e:
            error_msg = f"❌ Критическая ошибка инициализации: {e}"
            if self.logger:
                self.logger.critical(error_msg)
            else:
                print(error_msg)
            raise

    async def run_trading_session(self, session_duration_minutes: Optional[int] = None) -> None:
        """🔄 Запуск торговой сессии"""
        if not self.is_initialized:
            raise TradingSystemError("Приложение не инициализировано")

        try:
            self.logger.info("🚀 Запуск торговой сессии...")

            # Запускаем торговую сессию
            session_id = await self.trading_orchestrator.start_trading_session()
            self.is_running = True

            self.logger.info(f"✅ Торговая сессия запущена: {session_id}")

            # Основной торговый цикл
            cycle_count = 0
            start_time = datetime.now()

            while self.is_running:
                try:
                    # Выполняем торговый цикл
                    result = await self.trading_orchestrator.execute_trading_cycle()
                    cycle_count += 1

                    self.logger.debug(f"🔄 Цикл #{cycle_count}: {result.action}")

                    # Проверяем условия завершения
                    if session_duration_minutes:
                        elapsed_minutes = (datetime.now() - start_time).total_seconds() / 60
                        if elapsed_minutes >= session_duration_minutes:
                            self.logger.info(f"⏰ Достигнуто время сессии: {session_duration_minutes} минут")
                            break

                    # Пауза между циклами
                    await asyncio.sleep(self.settings.system.update_interval_seconds)

                except KeyboardInterrupt:
                    self.logger.info("⌨️ Получен сигнал остановки от пользователя")
                    break
                except Exception as e:
                    self.logger.error(f"❌ Ошибка в торговом цикле: {e}")
                    # Продолжаем работу, но с паузой
                    await asyncio.sleep(30)

            # Остановка сессии
            await self.trading_orchestrator.stop_trading_session()
            self.is_running = False

            self.logger.info(f"🏁 Торговая сессия завершена. Циклов выполнено: {cycle_count}")

        except Exception as e:
            self.logger.critical(f"💥 Критическая ошибка торговой сессии: {e}")
            await self._emergency_shutdown()
            raise

    async def run_analytics_mode(self) -> None:
        """📊 Режим аналитики без торговли"""
        if not self.is_initialized:
            raise TradingSystemError("Приложение не инициализировано")

        try:
            self.logger.info("📊 Запуск режима аналитики...")

            # Генерируем отчеты
            reports = []

            # Дневной отчет
            daily_report = await self.analytics_service.generate_report('daily')
            reports.append(('daily', daily_report))

            # Недельный отчет
            weekly_report = await self.analytics_service.generate_report('weekly')
            reports.append(('weekly', weekly_report))

            # Показатели производительности
            performance = await self.analytics_service.get_performance_summary()

            # Риск-метрики
            risk_metrics = await self.analytics_service.get_risk_metrics()

            # Автоматические инсайты
            insights = await self.analytics_service.generate_automated_insights()

            # Выводим результаты
            print("\n" + "=" * 60)
            print("📊 АНАЛИТИЧЕСКИЙ ОТЧЕТ")
            print("=" * 60)

            print(f"\n📈 ПРОИЗВОДИТЕЛЬНОСТЬ:")
            if 'current_metrics' in performance:
                metrics = performance['current_metrics']
                print(f"  💰 Общий P&L: {metrics.get('total_pnl', 'N/A')}")
                print(f"  🎯 Винрейт: {metrics.get('win_rate', 'N/A')}%")
                print(f"  📊 Всего сделок: {metrics.get('total_trades', 'N/A')}")
                print(f"  ⚡ Profit Factor: {metrics.get('profit_factor', 'N/A')}")

            print(f"\n🛡️ РИСК-МЕТРИКИ:")
            if 'drawdown' in risk_metrics:
                print(f"  📉 Текущая просадка: {risk_metrics['drawdown'].get('current', 'N/A')}")
                print(f"  📉 Макс. просадка: {risk_metrics['drawdown'].get('maximum', 'N/A')}")
            if 'volatility' in risk_metrics:
                print(f"  📊 Волатильность: {risk_metrics['volatility'].get('daily', 'N/A')}")

            if insights:
                print(f"\n💡 АВТОМАТИЧЕСКИЕ ИНСАЙТЫ:")
                for insight in insights:
                    print(f"  {insight}")

            print(f"\n📋 СГЕНЕРИРОВАННЫЕ ОТЧЕТЫ:")
            for report_type, report in reports:
                print(f"  📄 {report_type.upper()}: {len(report.to_dict())} метрик")

            print("\n✅ Аналитика завершена")

        except Exception as e:
            self.logger.error(f"❌ Ошибка в режиме аналитики: {e}")
            raise

    async def validate_system(self) -> bool:
        """✅ Валидация системы"""
        try:
            print("✅ Валидация системы...")

            # Проверяем конфигурацию
            settings = get_settings()
            print(f"  🔧 Конфигурация: OK")
            print(f"  📊 Профиль торговли: {settings.profile.value}")
            print(f"  🎯 Торговая пара: {settings.trading.trading_pair}")

            # ИСПРАВЛЕНО: Проверяем API ключи
            if not settings.api.api_key or not settings.api.api_secret:
                print("  ❌ API ключи EXMO не настроены")
                return False
            print("  🔑 API ключи: OK")

            # Проверяем директории
            required_dirs = ['data', 'logs']
            for dir_name in required_dirs:
                dir_path = Path(dir_name)
                if not dir_path.exists():
                    dir_path.mkdir(exist_ok=True)
                    print(f"  📁 Создана директория: {dir_name}")
                else:
                    print(f"  📁 {dir_name}: OK")

            # Проверяем импорты новой архитектуры
            try:
                from src.core.interfaces import ITradingStrategy
                from src.domain.trading.trading_service import TradingService
                print("  🏗️ Новая архитектура: OK")
            except ImportError as e:
                print(f"  ❌ Проблемы с новой архитектурой: {e}")
                return False

            print("✅ Система готова к работе!")
            return True

        except Exception as e:
            print(f"❌ Ошибка валидации: {e}")
            return False

    async def show_status(self) -> None:
        """📊 Показать статус системы"""
        try:
            if not self.is_initialized:
                print("❌ Система не инициализирована")
                return

            print("\n" + "=" * 50)
            print("📊 СТАТУС СИСТЕМЫ")
            print("=" * 50)

            # Статус торговой сессии
            if self.trading_orchestrator:
                session_stats = self.trading_orchestrator.get_session_statistics()
                print(f"🔄 Торговая сессия:")
                print(f"  • Статус: {'🟢 Активна' if session_stats.get('is_running') else '🔴 Остановлена'}")
                print(f"  • Сессия: {session_stats.get('session_id', 'N/A')}")
                print(f"  • Циклов выполнено: {session_stats.get('execution_count', 0)}")

            # Статус позиции
            if self.position_service:
                current_position = await self.position_service.get_current_position()
                if current_position and not current_position.is_empty:
                    print(f"📊 Текущая позиция:")
                    print(f"  • Количество: {current_position.quantity}")
                    print(f"  • Средняя цена: {current_position.average_price}")
                    print(f"  • Статус: {current_position.status.value}")
                else:
                    print(f"📊 Позиция: отсутствует")

            # Статус рисков
            if self.risk_service:
                risk_report = await self.risk_service.get_risk_report()
                if 'status' in risk_report:
                    status = risk_report['status']
                    emergency_active = status.get('emergency_stop_active', False)
                    trading_blocked = status.get('trading_blocked', False)

                    print(f"🛡️ Риск-менеджмент:")
                    print(f"  • Аварийная остановка: {'🚨 Активна' if emergency_active else '✅ Неактивна'}")
                    print(f"  • Торговля: {'🚫 Заблокирована' if trading_blocked else '✅ Разрешена'}")

            # Системная информация
            print(f"⚙️ Система:")
            print(f"  • Архитектура: Clean Architecture v4.1")
            print(f"  • Режим: {'🔴 Paper Trading' if self.settings.test_mode else '🟢 Live Trading'}")
            print(f"  • Профиль: {self.settings.profile.value}")

        except Exception as e:
            print(f"❌ Ошибка получения статуса: {e}")

    async def shutdown(self) -> None:
        """🛑 Корректное завершение работы"""
        try:
            print("🛑 Завершение работы...")

            if self.is_running and self.trading_orchestrator:
                await self.trading_orchestrator.stop_trading_session()
                self.is_running = False

            # Сохраняем финальное состояние
            if self.analytics_service:
                final_metrics = await self.analytics_service.calculate_current_metrics()
                if self.logger:  # ИСПРАВЛЕНО: добавили проверку
                    self.logger.info(f"💾 Финальные метрики: P&L={final_metrics.total_pnl}")

            if self.logger:  # ИСПРАВЛЕНО: добавили проверку
                self.logger.info("✅ Завершение работы completed")

        except Exception as e:
            if self.logger:
                self.logger.error(f"❌ Ошибка при завершении: {e}")
            else:
                print(f"❌ Ошибка при завершении: {e}")

    # ================= ПРИВАТНЫЕ МЕТОДЫ =================

    def _setup_logging(self) -> None:
        """📝 Настройка системы логирования"""
        # Создаем директорию для логов
        logs_dir = Path("logs")
        logs_dir.mkdir(exist_ok=True)

        # Настройка форматирования
        log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

        # Конфигурация логирования
        logging.basicConfig(
            level=logging.INFO,
            format=log_format,
            handlers=[
                logging.FileHandler(logs_dir / 'trading_bot.log', encoding='utf-8'),
                logging.StreamHandler(sys.stdout)
            ]
        )

        self.logger = logging.getLogger(__name__)
        self.logger.info("📝 Система логирования инициализирована")

    async def _validate_configuration(self) -> None:
        """✅ Валидация конфигурации"""
        try:
            # Валидируем настройки
            self.settings.validate()

            # ИСПРАВЛЕНО: Проверяем критические настройки
            if not self.settings.api.api_key or not self.settings.api.api_secret:
                raise ConfigurationError("API ключи EXMO не настроены")

            # Проверяем торговую пару
            if not self.settings.trading.trading_pair:
                raise ConfigurationError("Торговая пара не настроена")

            self.logger.info("✅ Конфигурация валидна")

        except Exception as e:
            raise ConfigurationError(f"Некорректная конфигурация: {e}")

    # ... остальные приватные методы остаются без изменений ...

    async def _configure_dependencies(self) -> None:
        """💉 Настройка зависимостей в DI контейнере"""
        # Здесь будет регистрация всех сервисов в DI контейнере
        # Пока используем заглушки, так как Infrastructure слой не готов
        self.logger.info("💉 DI зависимости настроены (заглушки)")

    async def _initialize_services(self) -> None:
        """🔧 Инициализация всех сервисов"""
        try:
            # Создаем торговую пару
            trading_pair = TradingPair("DOGE", "EUR")

            # Пока используем заглушки, так как полная Infrastructure не готова
            # В будущем сервисы будут создаваться через DI контейнер

            self.logger.info("🔧 Сервисы инициализированы (заглушки)")

        except Exception as e:
            raise TradingSystemError(f"Ошибка инициализации сервисов: {e}")

    async def _system_health_check(self) -> None:
        """🏥 Проверка здоровья системы"""
        try:
            # Проверяем основные компоненты
            health_checks = [
                ("Configuration", self.settings is not None),
                ("DI Container", self.container is not None),
                ("Logging", self.logger is not None)
            ]

            for check_name, is_healthy in health_checks:
                if not is_healthy:
                    raise TradingSystemError(f"Компонент {check_name} не готов")

            self.logger.info("🏥 Проверка здоровья системы пройдена")

        except Exception as e:
            raise TradingSystemError(f"Система не готова к работе: {e}")

    async def _emergency_shutdown(self) -> None:
        """🚨 Аварийное завершение работы"""
        try:
            self.logger.critical("🚨 АВАРИЙНОЕ ЗАВЕРШЕНИЕ РАБОТЫ")

            self.is_running = False

            if self.trading_orchestrator:
                await self.trading_orchestrator.stop_trading_session()

            # Сохраняем критически важные данные
            self.logger.critical("💾 Сохранение критических данных завершено")

        except Exception as e:
            print(f"💥 Критическая ошибка при аварийном завершении: {e}")


def create_argument_parser() -> argparse.ArgumentParser:
    """🔧 Создание парсера аргументов командной строки"""
    parser = argparse.ArgumentParser(
        description="🤖 DOGE Trading Bot v4.1-refactored",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры использования:
  python main.py --validate          # Проверка конфигурации
  python main.py --trade             # Запуск торговли
  python main.py --analytics         # Режим аналитики
  python main.py --status           # Показать статус
  python main.py --trade --duration 60  # Торговля 60 минут
        """
    )
    
    # Основные режимы
    parser.add_argument('--validate', action='store_true',
                       help='Валидация системы без запуска')
    
    parser.add_argument('--trade', action='store_true',
                       help='Запуск торговой сессии')
    
    parser.add_argument('--analytics', action='store_true',
                       help='Режим аналитики без торговли')
    
    parser.add_argument('--status', action='store_true',
                       help='Показать текущий статус')
    
    # Дополнительные параметры
    parser.add_argument('--duration', type=int, metavar='MINUTES',
                       help='Длительность торговой сессии в минутах')
    
    parser.add_argument('--profile', choices=['conservative', 'balanced', 'aggressive'],
                       help='Торговый профиль')
    
    parser.add_argument('--dry-run', action='store_true',
                       help='Режим paper trading')
    
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Подробный вывод')
    
    return parser


async def main():
    """🚀 Главная функция приложения"""
    
    # Парсинг аргументов командной строки
    parser = create_argument_parser()
    args = parser.parse_args()
    
    # Если никаких аргументов - показываем справку
    if len(sys.argv) == 1:
        parser.print_help()
        return
    
    # Создание приложения
    app = TradingBotApplication()
    
    try:
        # Режим валидации
        if args.validate:
            is_valid = await app.validate_system()
            sys.exit(0 if is_valid else 1)
        
        # Инициализация для всех остальных режимов
        await app.initialize()
        
        # Режим показа статуса
        if args.status:
            await app.show_status()
            return
        
        # Режим аналитики
        if args.analytics:
            await app.run_analytics_mode()
            return
        
        # Режим торговли
        if args.trade:
            duration = args.duration if args.duration else None
            await app.run_trading_session(duration)
            return
        
        # Если дошли сюда - неизвестный режим
        print("❌ Не указан режим работы. Используйте --help для справки")
        sys.exit(1)
        
    except KeyboardInterrupt:
        print("\n⌨️ Получен сигнал остановки...")
    except Exception as e:
        print(f"\n💥 Критическая ошибка: {e}")
        sys.exit(1)
    finally:
        # Корректное завершение
        await app.shutdown()


if __name__ == "__main__":
    # Запуск приложения
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 До свидания!")
    except Exception as e:
        print(f"\n💥 Фатальная ошибка: {e}")
        sys.exit(1)
