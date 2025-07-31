# config_updated.py - Обновленная конфигурация с настройками восстановления
import os
from dataclasses import dataclass
from typing import Dict, Any

# Попытка загрузить .env файл (если установлена python-dotenv)
try:
    from dotenv import load_dotenv

    load_dotenv()
    print("✅ .env файл загружен")
except ImportError:
    print("ℹ️  python-dotenv не установлен, используем системные переменные")
except Exception as e:
    print(f"⚠️  Ошибка загрузки .env: {e}")


@dataclass
class TradingConfig:
    # API настройки
    API_KEY: str = os.getenv('EXMO_API_KEY', '')
    API_SECRET: str = os.getenv('EXMO_API_SECRET', '')
    API_URL: str = 'api.exmo.com'
    API_VERSION: str = 'v1.1'

    # Торговые настройки
    CURRENCY_1: str = os.getenv('TRADING_PAIR_1', 'DOGE')  # Торгуемая валюта
    CURRENCY_2: str = os.getenv('TRADING_PAIR_2', 'EUR')  # Базовая валюта

    # 🆕 поле для автокомиссии
    AUTO_COMMISSION_RATE: float = 0.003  # Дефолт 0.3%, будет обновлено из API

    # DCA настройки
    DCA_ENABLED = True
    DCA_MAX_PURCHASES = 7  # Максимум 7 покупок на дне
    DCA_PURCHASE_SIZE = 0.08  # 8% депозита на покупку
    DCA_MAX_POSITION = 0.56  # Максимум 56% в позиции

    # 🩹 НОВЫЕ настройки системы восстановления убытков
    LOSS_RECOVERY_ENABLED: bool = False  # Включить систему восстановления
    DCA_LOSS_THRESHOLD: float = 0.02  # DCA докупка при убытке >2%
    DCA_MAX_RECOVERY_ATTEMPTS: int = 3  # Максимум 3 DCA докупки
    EMERGENCY_STOP_LOSS: float = 0.08  # Экстренный стоп при -8%
    TIME_BASED_STOP_HOURS: int = 6  # Временной стоп через 6 часов
    MIN_TIME_BETWEEN_DCA_MINUTES: int = 30  # 30 минут между DCA докупками
    TRAILING_IN_LOSS_ENABLED: bool = True  # Trailing stop даже в убытке

    # 🛡️ СМЯГЧЕННОЕ управление рисками
    MAX_POSITION_SIZE: float = 0.08  # 8% от депозита
    MAX_DAILY_LOSS: float = 0.02  # 2% максимальных потерь в день
    STOP_LOSS_PERCENT: float = 0.15  # 15% стоп-лосс (был 8%)
    MAX_LOSS_PER_TRADE: float = 0.005  # Максимум 0.5% убытка на сделку

    # Ручная настройка позиций
    MANUAL_DOGE_PRICE: float = float(os.getenv('MANUAL_DOGE_PRICE', '0.0'))

    # 🐕 DOGE-ОПТИМИЗИРОВАННЫЕ параметры стратегии
    BASE_PROFIT_MARKUP: float = 0.001  # 0.1% базовая прибыль
    MIN_SPREAD: float = 0.002  # 0.2% минимальный спред
    VOLATILITY_PERIOD: int = 50

    # ⚡ УЛЬТРА-БЫСТРЫЕ технические параметры для DOGE
    ORDER_LIFE_TIME: int = 900  # 15 минут
    PRICE_CHECK_PERIOD: int = 600  # Проверка цен каждые 10 минут
    UPDATE_INTERVAL: int = 5  # 5 секунд базовый интервал

    # 🚀 АДАПТИВНЫЕ интервалы для разных режимов
    ADAPTIVE_INTERVALS = {
        'normal': 8,  # Обычный режим - 8 секунд
        'position': 6,  # Есть позиция - 6 секунд
        'waiting': 5,  # Ожидание активации trailing - 5 секунд
        'trailing': 2,  # Активный trailing stop - 2 секунды
        'emergency': 1,  # Экстренные ситуации - 1 секунда
        'recovery': 3  # 🩹 НОВОЕ: Режим восстановления убытков - 3 секунды
    }

    # 🎯 DOGE-СПЕЦИФИЧНЫЕ параметры для фильтрации сделок
    MIN_VOLATILITY_THRESHOLD: float = 0.0002  # 0.02% минимальная волатильность
    MAX_PRICE_DEVIATION: float = 0.003  # Максимальное отклонение цены ордера

    # 💰 СБАЛАНСИРОВАННЫЕ параметры прибыльности
    MIN_PROFIT_TO_SELL: float = 0.012  # 1.2% минимальная прибыль для продажи
    FAST_PROFIT_THRESHOLD: float = 2.0  # Быстрая продажа при 2% прибыли
    COMMISSION_BUFFER: float = 0.007  # Буфер на комиссии

    # 📊 БЫСТРЫЙ анализ для DOGE
    MIN_DATA_POINTS: int = 15  # 15 точек = 2.5 минуты
    STABLE_MARKET_THRESHOLD: float = 0.001  # Порог стабильного рынка
    MICRO_DIP_THRESHOLD: float = 0.005  # Порог микропадения 0.5%
    RANGE_POSITION_BUY: float = 0.3  # Покупать в нижних 30% диапазона

    # 🚀 ВКЛЮЧАЕМ умные входы на микро-падениях
    QUICK_ENTRY_ON_DIP: bool = True  # Включено для DOGE
    DIP_THRESHOLD_MINOR: float = 0.003  # Малое падение 0.3%
    DIP_THRESHOLD_MAJOR: float = 0.008  # Большое падение 0.8%

    # 💡 УМНОЕ ценообразование для DOGE
    AGGRESSIVE_PRICING: bool = True  # Включено - нужно для микро-спредов
    MARKET_PRICE_OFFSET: float = 0.001  # Маленькая скидка от рынка
    QUICK_FILL_OFFSET: float = 0.0005  # Быстрое исполнение

    # 🔒 ВАЖНЫЕ защиты
    MAX_TRADES_PER_HOUR: int = 6  # Увеличено до 6 сделок в час (было 4)
    MIN_TIME_BETWEEN_TRADES: int = 300  # 5 минут между сделками
    POSITION_VALIDATION_ENABLED: bool = True  # Важная защита
    MAX_POSITION_DISCREPANCY: float = 0.15  # 🔧 УВЕЛИЧЕНО до 15% (было 1%)

    # 🐕 DOGE-специфичные параметры
    STAGNATION_PROTECTION: bool = True  # Защита от принудительной торговли
    MAX_STAGNATION_CYCLES: int = 120  # 120 * 5 сек = 10 минут
    FORCE_TRADE_DISABLED: bool = False  # Включаем для DOGE

    # 🎯 DOGE-оптимизации
    ENABLE_MICRO_SCALPING: bool = True  # Включить микро-скальпинг
    MICRO_PROFIT_THRESHOLD: float = 0.004  # 0.4% микро-прибыль
    DOGE_VOLUME_CHECK: bool = True  # Проверка объемов для DOGE
    MIN_ORDER_VOLUME_EUR: float = 55  # Минимальный объем ордера

    # 🧠 НОВЫЕ настройки Trend Filter
    TREND_FILTER_ENABLED: bool = True                    # Включить фильтр трендов
    TREND_BEARISH_THRESHOLD_4H: float = -0.08           # -8% за 4ч = сильный медведь
    TREND_BEARISH_THRESHOLD_1H: float = -0.04           # -4% за 1ч = медведь
    TREND_DCA_DISABLE_THRESHOLD: float = -0.05          # Отключать DCA при -5% за 4ч
    TREND_BUY_DISABLE_THRESHOLD: float = -0.10          # Отключать покупки при -10% за 4ч
    TREND_HIGH_VOLATILITY_THRESHOLD: float = 0.05       # 5% волатильность = высокая
    TREND_CONFIDENCE_MIN: float = 0.6                   # Минимальная уверенность для решений

    # Логирование
    LOG_LEVEL: str = 'INFO'
    LOG_FILE: str = 'trading_bot_recovery.log'  # 🩹 НОВОЕ имя лога

    def __post_init__(self):
        """🧮 Расширенная валидация настроек с проверкой системы восстановления"""

        # Проверяем что прибыль больше комиссий
        total_commission = self.AUTO_COMMISSION_RATE * 2  # Покупка + продажа

        if self.BASE_PROFIT_MARKUP <= total_commission:
            print(
                f"⚠️  ВНИМАНИЕ: Прибыль {self.BASE_PROFIT_MARKUP * 100:.1f}% ≤ комиссий {total_commission * 100:.1f}%")
            print(f"🔧 Автоматически увеличиваем до {(total_commission + 0.001) * 100:.1f}%")
            self.BASE_PROFIT_MARKUP = total_commission + 0.001

        # 🩹 НОВЫЕ проверки для системы восстановления
        if self.LOSS_RECOVERY_ENABLED:
            # Проверяем логику порогов убытков
            if self.DCA_LOSS_THRESHOLD >= self.EMERGENCY_STOP_LOSS:
                print(
                    f"⚠️  ВНИМАНИЕ: DCA порог {self.DCA_LOSS_THRESHOLD * 100:.0f}% >= экстренного стопа {self.EMERGENCY_STOP_LOSS * 100:.0f}%")
                self.DCA_LOSS_THRESHOLD = self.EMERGENCY_STOP_LOSS * 0.5
                print(f"🔧 Автоматически корректируем DCA порог до {self.DCA_LOSS_THRESHOLD * 100:.0f}%")

            # Проверяем что есть запас для DCA
            max_dca_risk = self.DCA_LOSS_THRESHOLD * self.DCA_MAX_RECOVERY_ATTEMPTS
            if max_dca_risk > self.EMERGENCY_STOP_LOSS * 0.8:
                print(f"⚠️  ВНИМАНИЕ: Суммарный DCA риск {max_dca_risk * 100:.0f}% слишком близок к стоп-лоссу")

        print(f"🐕 DOGE-ОПТИМИЗИРОВАННЫЕ НАСТРОЙКИ С СИСТЕМОЙ ВОССТАНОВЛЕНИЯ:")
        print(f"   💰 Прибыль на сделку: {self.BASE_PROFIT_MARKUP * 100:.1f}%")
        print(f"   🎯 Размер позиции: {self.MAX_POSITION_SIZE * 100:.0f}%")
        print(f"   ⚡ Базовый интервал: {self.UPDATE_INTERVAL} сек")
        print(f"   🌊 Мин. волатильность: {self.MIN_VOLATILITY_THRESHOLD * 100:.2f}%")
        print(f"   📊 Точек данных: {self.MIN_DATA_POINTS}")
        print(f"   💎 Мин. прибыль продажи: {self.MIN_PROFIT_TO_SELL * 100:.1f}%")

        # 🩹 Логируем настройки восстановления
        if self.LOSS_RECOVERY_ENABLED:
            print(f"   🩹 СИСТЕМА ВОССТАНОВЛЕНИЯ:")
            print(f"      DCA при убытке: >{self.DCA_LOSS_THRESHOLD * 100:.0f}%")
            print(f"      Максимум DCA: {self.DCA_MAX_RECOVERY_ATTEMPTS}")
            print(f"      Экстренный стоп: {self.EMERGENCY_STOP_LOSS * 100:.0f}%")
            print(f"      Временной стоп: {self.TIME_BASED_STOP_HOURS} часов")
            print(f"      Интервал DCA: {self.MIN_TIME_BETWEEN_DCA_MINUTES} минут")

        # Расчет экономики
        net_profit = self.BASE_PROFIT_MARKUP - total_commission
        print(f"   📈 Чистая прибыль с сделки: {net_profit * 100:.2f}%")

        if net_profit <= 0:
            print(f"🚨 ОШИБКА: Отрицательная прибыль! Увеличьте BASE_PROFIT_MARKUP")
        elif net_profit < 0.001:
            print(f"⚠️  ВНИМАНИЕ: Очень маленькая прибыль, высокий риск")
        else:
            print(f"✅ Экономика сделки положительная")

        # Проверка на DOGE-совместимость
        if self.MIN_VOLATILITY_THRESHOLD <= 0.0002:
            print(f"🐕 Отлично! Настройки оптимизированы для DOGE микро-движений")
        elif self.MIN_VOLATILITY_THRESHOLD <= 0.001:
            print(f"🐕 Хорошо! Настройки подходят для DOGE торговли")
        else:
            print(f"⚠️  ВНИМАНИЕ: Настройки могут пропускать DOGE возможности")

        # 🩹 Финальная проверка совместимости систем
        self._validate_system_compatibility()

    def _validate_system_compatibility(self):
        """🔧 Проверка совместимости всех систем"""

        issues = []

        # Проверяем совместимость DCA и recovery
        if self.DCA_ENABLED and self.LOSS_RECOVERY_ENABLED:
            if self.DCA_MAX_PURCHASES * self.DCA_PURCHASE_SIZE > self.DCA_MAX_POSITION:
                issues.append("DCA: Максимум покупок * размер > максимальной позиции")

        # Проверяем адаптивные интервалы
        if 'recovery' not in self.ADAPTIVE_INTERVALS:
            self.ADAPTIVE_INTERVALS['recovery'] = 3
            issues.append("Добавлен отсутствующий интервал 'recovery'")

        # Проверяем лимиты торговли
        max_trades_per_day = self.MAX_TRADES_PER_HOUR * 24
        max_dca_trades = self.DCA_MAX_PURCHASES + self.DCA_MAX_RECOVERY_ATTEMPTS

        if max_dca_trades > max_trades_per_day * 0.5:
            issues.append(f"DCA+Recovery может создать {max_dca_trades} сделок, что много для дневного лимита")

        # Выводим найденные проблемы
        if issues:
            print(f"⚠️  НАЙДЕННЫЕ ПРОБЛЕМЫ СОВМЕСТИМОСТИ:")
            for issue in issues:
                print(f"   • {issue}")
        else:
            print(f"✅ Все системы совместимы")

    def get_recovery_settings(self) -> Dict[str, Any]:
        """🩹 НОВЫЙ МЕТОД: Получение настроек системы восстановления"""
        return {
            'enabled': self.LOSS_RECOVERY_ENABLED,
            'dca_loss_threshold': self.DCA_LOSS_THRESHOLD,
            'dca_max_attempts': self.DCA_MAX_RECOVERY_ATTEMPTS,
            'emergency_stop_loss': self.EMERGENCY_STOP_LOSS,
            'time_based_stop_hours': self.TIME_BASED_STOP_HOURS,
            'min_time_between_dca_minutes': self.MIN_TIME_BETWEEN_DCA_MINUTES,
            'trailing_in_loss_enabled': self.TRAILING_IN_LOSS_ENABLED
        }

    def get_doge_optimizations(self) -> Dict[str, Any]:
        """🐕 Получение DOGE-специфичных оптимизаций"""
        return {
            'min_volatility_threshold': self.MIN_VOLATILITY_THRESHOLD,
            'enable_micro_scalping': self.ENABLE_MICRO_SCALPING,
            'micro_profit_threshold': self.MICRO_PROFIT_THRESHOLD,
            'quick_entry_on_dip': self.QUICK_ENTRY_ON_DIP,
            'aggressive_pricing': self.AGGRESSIVE_PRICING,
            'adaptive_intervals': self.ADAPTIVE_INTERVALS
        }

    def update_for_paper_trading(self):
        """📝 НОВЫЙ МЕТОД: Настройки для тестового режима"""
        print("📝 Переключение в тестовый режим (paper trading)")

        # Ускоряем все процессы для тестов
        self.UPDATE_INTERVAL = 1  # 1 секунда
        self.MIN_TIME_BETWEEN_TRADES = 60  # 1 минута между сделками
        self.MIN_TIME_BETWEEN_DCA_MINUTES = 5  # 5 минут между DCA
        self.TIME_BASED_STOP_HOURS = 1  # 1 час для временного стопа

        # Более агрессивные пороги для быстрого тестирования
        self.DCA_LOSS_THRESHOLD = 0.01  # 1% вместо 2%
        self.EMERGENCY_STOP_LOSS = 0.05  # 5% вместо 8%

        # Ускоряем адаптивные интервалы
        for mode in self.ADAPTIVE_INTERVALS:
            self.ADAPTIVE_INTERVALS[mode] = max(1, self.ADAPTIVE_INTERVALS[mode] // 2)

        print("✅ Тестовый режим активирован")

    def update_for_conservative_mode(self):
        """🛡️ НОВЫЙ МЕТОД: Консервативные настройки"""
        print("🛡️ Переключение в консервативный режим")

        # Увеличиваем безопасность
        self.MAX_POSITION_SIZE = 0.05  # 5% вместо 8%
        self.DCA_LOSS_THRESHOLD = 0.03  # 3% вместо 2%
        self.DCA_MAX_RECOVERY_ATTEMPTS = 2  # 2 вместо 3
        self.EMERGENCY_STOP_LOSS = 0.06  # 6% вместо 8%

        # Более строгие требования к прибыли
        self.MIN_PROFIT_TO_SELL = 0.015  # 1.5% вместо 1.2%
        self.BASE_PROFIT_MARKUP = 0.002  # 0.2% вместо 0.1%

        # Замедляем торговлю
        self.MIN_TIME_BETWEEN_TRADES = 600  # 10 минут
        self.MIN_TIME_BETWEEN_DCA_MINUTES = 60  # 1 час между DCA

        print("✅ Консервативный режим активирован")

    def update_for_aggressive_mode(self):
        """🚀 НОВЫЙ МЕТОД: Агрессивные настройки"""
        print("🚀 Переключение в агрессивный режим")

        # Увеличиваем активность
        self.MAX_POSITION_SIZE = 0.12  # 12% вместо 8%
        self.DCA_LOSS_THRESHOLD = 0.015  # 1.5% вместо 2%
        self.DCA_MAX_RECOVERY_ATTEMPTS = 4  # 4 вместо 3
        self.MAX_TRADES_PER_HOUR = 8  # 8 вместо 6

        # Более низкие требования к прибыли
        self.MIN_PROFIT_TO_SELL = 0.008  # 0.8% вместо 1.2%

        # Ускоряем торговлю
        self.MIN_TIME_BETWEEN_TRADES = 180  # 3 минуты
        self.MIN_TIME_BETWEEN_DCA_MINUTES = 15  # 15 минут между DCA

        # Ускоряем все интервалы
        for mode in self.ADAPTIVE_INTERVALS:
            self.ADAPTIVE_INTERVALS[mode] = max(1, int(self.ADAPTIVE_INTERVALS[mode] * 0.7))

        print("✅ Агрессивный режим активирован")

    def print_current_settings(self):
        """📊 НОВЫЙ МЕТОД: Вывод текущих настроек"""
        print("\n📊 ТЕКУЩИЕ НАСТРОЙКИ БОТА:")
        print("=" * 50)

        print("🎯 Основные параметры:")
        print(f"   Пара: {self.CURRENCY_1}_{self.CURRENCY_2}")
        print(f"   Размер позиции: {self.MAX_POSITION_SIZE * 100:.0f}%")
        print(f"   Базовая прибыль: {self.BASE_PROFIT_MARKUP * 100:.2f}%")
        print(f"   Мин. прибыль продажи: {self.MIN_PROFIT_TO_SELL * 100:.1f}%")
        print(f"   Комиссия: {self.AUTO_COMMISSION_RATE * 100:.1f}%")

        print("\n🩹 Система восстановления:")
        print(f"   Включена: {'ДА' if self.LOSS_RECOVERY_ENABLED else 'НЕТ'}")
        if self.LOSS_RECOVERY_ENABLED:
            print(f"   DCA при убытке: >{self.DCA_LOSS_THRESHOLD * 100:.0f}%")
            print(f"   Максимум DCA: {self.DCA_MAX_RECOVERY_ATTEMPTS}")
            print(f"   Экстренный стоп: {self.EMERGENCY_STOP_LOSS * 100:.0f}%")
            print(f"   Временной стоп: {self.TIME_BASED_STOP_HOURS} ч")

        print("\n⚡ Скорость торговли:")
        print(f"   Базовый интервал: {self.UPDATE_INTERVAL} сек")
        print(f"   Между сделками: {self.MIN_TIME_BETWEEN_TRADES // 60} мин")
        print(f"   Между DCA: {self.MIN_TIME_BETWEEN_DCA_MINUTES} мин")
        print(f"   Макс. сделок/час: {self.MAX_TRADES_PER_HOUR}")

        print("\n🛡️ Защиты:")
        print(f"   Стоп-лосс: {self.STOP_LOSS_PERCENT * 100:.0f}%")
        print(f"   Макс. дневные потери: {self.MAX_DAILY_LOSS * 100:.0f}%")
        print(f"   Валидация позиций: {'ВКЛ' if self.POSITION_VALIDATION_ENABLED else 'ВЫКЛ'}")
        print(f"   Макс. расхождение: {self.MAX_POSITION_DISCREPANCY * 100:.0f}%")

        print("\n🐕 DOGE оптимизации:")
        print(f"   Мин. волатильность: {self.MIN_VOLATILITY_THRESHOLD * 100:.2f}%")
        print(f"   Микро-скальпинг: {'ВКЛ' if self.ENABLE_MICRO_SCALPING else 'ВЫКЛ'}")
        print(f"   Быстрые входы: {'ВКЛ' if self.QUICK_ENTRY_ON_DIP else 'ВЫКЛ'}")
        print(f"   Агрессивные цены: {'ВКЛ' if self.AGGRESSIVE_PRICING else 'ВЫКЛ'}")


# 🔧 ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
def create_test_config() -> TradingConfig:
    """📝 Создание тестовой конфигурации"""
    config = TradingConfig()
    config.update_for_paper_trading()
    return config


def create_conservative_config() -> TradingConfig:
    """🛡️ Создание консервативной конфигурации"""
    config = TradingConfig()
    config.update_for_conservative_mode()
    return config


def create_aggressive_config() -> TradingConfig:
    """🚀 Создание агрессивной конфигурации"""
    config = TradingConfig()
    config.update_for_aggressive_mode()
    return config


def compare_configs():
    """📊 Сравнение разных конфигураций"""
    print("📊 СРАВНЕНИЕ КОНФИГУРАЦИЙ")
    print("=" * 60)

    configs = {
        "Обычная": TradingConfig(),
        "Консервативная": create_conservative_config(),
        "Агрессивная": create_aggressive_config(),
        "Тестовая": create_test_config()
    }

    metrics = [
        ("Размер позиции", "MAX_POSITION_SIZE", "%"),
        ("DCA порог", "DCA_LOSS_THRESHOLD", "%"),
        ("Экстренный стоп", "EMERGENCY_STOP_LOSS", "%"),
        ("Мин. прибыль", "MIN_PROFIT_TO_SELL", "%"),
        ("Интервал", "UPDATE_INTERVAL", "сек"),
        ("DCA попыток", "DCA_MAX_RECOVERY_ATTEMPTS", "шт")
    ]

    print(f"{'Метрика':<20} {'Обычная':<12} {'Консерв':<12} {'Агресс':<12} {'Тест':<12}")
    print("-" * 60)

    for metric_name, attr_name, unit in metrics:
        row = f"{metric_name:<20}"
        for config_name, config in configs.items():
            value = getattr(config, attr_name, 0)
            if unit == "%":
                formatted = f"{value * 100:.1f}%"
            elif unit == "сек":
                formatted = f"{value}сек"
            else:
                formatted = f"{value}{unit}"
            row += f" {formatted:<12}"
        print(row)


if __name__ == "__main__":
    print("⚙️ КОНФИГУРАЦИЯ ТОРГОВОГО БОТА С СИСТЕМОЙ ВОССТАНОВЛЕНИЯ")
    print("=" * 60)

    # Создаем стандартную конфигурацию
    config = TradingConfig()
    config.print_current_settings()

    print(f"\n🔧 ДОСТУПНЫЕ РЕЖИМЫ:")
    print(f"   📝 Тестовый: create_test_config()")
    print(f"   🛡️ Консервативный: create_conservative_config()")
    print(f"   🚀 Агрессивный: create_aggressive_config()")

    print(f"\n📊 Для сравнения всех режимов запустите: compare_configs()")

    # Показываем настройки восстановления
    recovery_settings = config.get_recovery_settings()
    print(f"\n🩹 НАСТРОЙКИ СИСТЕМЫ ВОССТАНОВЛЕНИЯ:")
    for key, value in recovery_settings.items():
        if isinstance(value, float) and 0 < value < 1:
            print(f"   {key}: {value * 100:.1f}%")
        elif isinstance(value, bool):
    # 🔇 НАСТРОЙКИ ОПТИМИЗИРОВАННОГО ЛОГИРОВАНИЯ
    QUIET_MODE: bool = True
    LOG_ONLY_EVENTS: bool = True
    AGGREGATE_RATE_LIMITS: bool = True
    LOG_PRICE_CHANGES_THRESHOLD: float = 0.005
    LOG_PNL_CHANGES_THRESHOLD: float = 0.01

    # 📊 НАСТРОЙКИ АНАЛИЗА ТРЕНДОВ
    ENABLE_TREND_ANALYSIS: bool = True
    TREND_DATA_RETENTION_DAYS: int = 30
    TREND_UPDATE_INTERVAL_MINUTES: int = 10

    # 🎯 НАСТРОЙКИ ЧАСТИЧНОЙ ТОРГОВЛИ
    ENABLE_PARTIAL_TRADING: bool = True
    PARTIAL_MIN_LAYER_PROFIT: float = 0.012
    PARTIAL_MAX_HOLD_DAYS: int = 7
    PARTIAL_LAYER_TOLERANCE: float = 0.02

            print(f"   {key}: {'ВКЛ' if value else 'ВЫКЛ'}")
        else:
            print(f"   {key}: {value}")