import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

@dataclass
class HybridTradingConfig:
    """⚙️ Гибридная конфигурация торгового бота"""

    # 🔑 API настройки
    API_KEY: str = os.getenv('EXMO_API_KEY', '')
    API_SECRET: str = os.getenv('EXMO_API_SECRET', '')

    # 💱 Торговая пара
    CURRENCY_1: str = 'DOGE'
    CURRENCY_2: str = 'EUR'

    # 📊 Основные торговые параметры (балансированные)
    POSITION_SIZE: float = 0.06              # 6% депозита на позицию
    MIN_PROFIT_PERCENT: float = 0.008        # 0.8% минимальная прибыль
    STOP_LOSS_PERCENT: float = 0.08          # 8% стоп-лосс
    COMMISSION_RATE: float = 0.003           # 0.3% комиссия

    # 🏗️ Гибридная пирамидальная стратегия
    PYRAMID_LEVELS = [
        {'profit': 0.008, 'sell_percent': 0.25, 'min_eur': 0.08},
        {'profit': 0.020, 'sell_percent': 0.30, 'min_eur': 0.15},
        {'profit': 0.040, 'sell_percent': 0.35, 'min_eur': 0.25},
        {'profit': 0.070, 'sell_percent': 0.10, 'min_eur': 0.40},
    ]

    # 🛒 Улучшенная DCA стратегия
    DCA_DROP_THRESHOLD: float = 0.015        # 1.5% падение для DCA
    DCA_PURCHASE_SIZE: float = 0.03          # 3% депозита на DCA
    DCA_MAX_POSITION: float = 0.45           # 45% максимум позиции
    DCA_COOLDOWN_MINUTES: int = 20           # 20 минут между DCA
    DCA_DAILY_LIMIT: int = 5                 # 5 DCA в день

    # ⏱️ Тайминги
    UPDATE_INTERVAL: int = 5                 # 5 секунд между циклами
    LOG_LEVEL: str = 'INFO'

    # 📁 Файлы
    POSITIONS_FILE: str = 'data/positions.json'
    LOG_FILE: str = 'logs/hybrid_trading_bot.log'
    ANALYTICS_DIR: str = 'data/analytics'

    # 🚨 Системы аварийного выхода
    EMERGENCY_EXIT_ENABLED: bool = True
    EMERGENCY_CRITICAL_LOSS: float = 0.15
    EMERGENCY_MAJOR_LOSS: float = 0.12
    EMERGENCY_SIGNIFICANT_LOSS: float = 0.08

    # 🛡️ DCA лимитер
    DCA_LIMITER_ENABLED: bool = True
    DCA_MAX_PER_DAY: int = 5
    DCA_MAX_CONSECUTIVE: int = 3
    DCA_MIN_INTERVAL_MINUTES: int = 25
    DCA_LOSS_BLOCK_THRESHOLD: float = 0.08

    # ⚡ Rate Limiter
    RATE_LIMITER_ENABLED: bool = True
    API_CALLS_PER_MINUTE: int = 25
    API_CALLS_PER_HOUR: int = 250

    # 🧠 Продвинутые фичи
    TREND_FILTER_ENABLED: bool = True
    ADVANCED_INDICATORS_ENABLED: bool = True
    HYBRID_ORCHESTRATOR_ENABLED: bool = True

    # 📊 Аналитика
    ANALYTICS_ENABLED: bool = True
    SIMPLE_ANALYTICS: bool = True
    ADVANCED_ANALYTICS: bool = True
    CHARTS_ENABLED: bool = True

    def __post_init__(self):
        """🔧 Проверка настроек"""
        if not self.API_KEY or not self.API_SECRET:
            raise ValueError("❌ API ключи не настроены в .env файле!")

        # Создаем директории
        import os
        os.makedirs(os.path.dirname(self.POSITIONS_FILE), exist_ok=True)
        os.makedirs(os.path.dirname(self.LOG_FILE), exist_ok=True)
        os.makedirs(self.ANALYTICS_DIR, exist_ok=True)

    def get_pair(self) -> str:
        """💱 Получение торговой пары"""
        return f"{self.CURRENCY_1}_{self.CURRENCY_2}"

    def print_summary(self):
        """📋 Сводка гибридных настроек"""
        print("⚙️ ГИБРИДНАЯ КОНФИГУРАЦИЯ БОТА:")
        print(f"   💱 Пара: {self.get_pair()}")
        print(f"   📊 Размер позиции: {self.POSITION_SIZE*100:.0f}%")
        print(f"   💎 Мин. прибыль: {self.MIN_PROFIT_PERCENT*100:.1f}%")
        print(f"   🚨 Стоп-лосс: {self.STOP_LOSS_PERCENT*100:.0f}%")
        print()
        print("🔧 АКТИВНЫЕ СИСТЕМЫ:")
        print(f"   🚨 Аварийный выход: {'✅' if self.EMERGENCY_EXIT_ENABLED else '❌'}")
        print(f"   🛡️ DCA лимитер: {'✅' if self.DCA_LIMITER_ENABLED else '❌'}")
        print(f"   🧠 Фильтр трендов: {'✅' if self.TREND_FILTER_ENABLED else '❌'}")
        print(f"   📊 Расш. аналитика: {'✅' if self.ADVANCED_ANALYTICS else '❌'}")

# Для обратной совместимости
TradingConfig = HybridTradingConfig

if __name__ == "__main__":
    config = HybridTradingConfig()
    config.print_summary()
