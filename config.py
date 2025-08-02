import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


@dataclass
class TradingConfig:
    """⚙️ Конфигурация торгового бота"""
    
    # 🔑 API настройки
    API_KEY: str = os.getenv('EXMO_API_KEY', '')
    API_SECRET: str = os.getenv('EXMO_API_SECRET', '')
    
    # 💱 Торговая пара
    CURRENCY_1: str = 'DOGE'
    CURRENCY_2: str = 'EUR'
    
    # 📊 Основные торговые параметры
    POSITION_SIZE: float = 0.06  # 6% для безопасного тестирования              # 8% депозита на позицию
    MIN_PROFIT_PERCENT: float = 0.006  # 0.6% для быстрых продаж        # 0.8% минимальная прибыль
    STOP_LOSS_PERCENT: float = 0.08          # 8% стоп-лосс
    COMMISSION_RATE: float = 0.003           # 0.3% комиссия
    
    # 🏗️ Пирамидальная стратегия
    PYRAMID_LEVELS = [
        {'profit': 0.008, 'sell_percent': 0.25, 'min_eur': 0.08},  # Быстрый уровень,  # 1.5% -> 30%
        {'profit': 0.020, 'sell_percent': 0.35, 'min_eur': 0.15},  # Средний уровень,  # 3.5% -> 40%
        {'profit': 0.040, 'sell_percent': 0.40, 'min_eur': 0.25},  # Хороший уровень,  # 6.0% -> 30%
    ]
    
    # 🛒 DCA стратегия
    DCA_DROP_THRESHOLD: float = 0.02         # 6% падение для DCA
    DCA_PURCHASE_SIZE: float = 0.03          # 3% депозита на DCA
    DCA_MAX_POSITION: float = 0.50           # 50% максимум позиции
    DCA_COOLDOWN_MINUTES: int = 25  # 25 минут между DCA           # 40 минут между DCA
    DCA_DAILY_LIMIT: int = 4  # 4 DCA в день                 # Максимум 2 DCA в день
    
    # ⏱️ Тайминги
    UPDATE_INTERVAL: int = 6  # 6 секунд для активной торговли                 # 8 секунд между циклами
    LOG_LEVEL: str = 'DEBUG' # 'INFO'
    
    # 📁 Файлы
    POSITIONS_FILE: str = 'data/positions.json'
    LOG_FILE: str = 'logs/trading_bot.log'
    
    
    # 🚨 Настройки аварийного выхода
    EMERGENCY_EXIT_ENABLED: bool = True
    EMERGENCY_CRITICAL_LOSS: float = 0.15      # 15% критический убыток
    EMERGENCY_MAJOR_LOSS: float = 0.12         # 12% большой убыток  
    EMERGENCY_SIGNIFICANT_LOSS: float = 0.08   # 8% значительный убыток
    
    # 🛡️ Настройки DCA лимитера
    DCA_LIMITER_ENABLED: bool = True
    DCA_MAX_PER_DAY: int = 5                   # Максимум DCA в день
    DCA_MAX_CONSECUTIVE: int = 3               # Максимум DCA подряд
    DCA_MIN_INTERVAL_MINUTES: int = 30         # Минимальный интервал между DCA
    DCA_LOSS_BLOCK_THRESHOLD: float = 0.08     # Блокировка при убытке >8%
    
    # ⚡ Настройки Rate Limiter
    RATE_LIMITER_ENABLED: bool = True
    API_CALLS_PER_MINUTE: int = 30             # Вызовов API в минуту
    API_CALLS_PER_HOUR: int = 300              # Вызовов API в час
    
    # 📊 Настройки аналитики
    ANALYTICS_ENABLED: bool = True

    def __post_init__(self):
        """🔧 Проверка настроек"""
        if not self.API_KEY or not self.API_SECRET:
            raise ValueError("❌ API ключи не настроены в .env файле!")
    
    def get_pair(self) -> str:
        """💱 Получение торговой пары"""
        return f"{self.CURRENCY_1}_{self.CURRENCY_2}"
    
    def print_summary(self):
        """📋 Сводка настроек"""
        print("⚙️ КОНФИГУРАЦИЯ БОТА:")
        print(f"   💱 Пара: {self.get_pair()}")
        print(f"   📊 Размер позиции: {self.POSITION_SIZE*100:.0f}%")
        print(f"   💎 Мин. прибыль: {self.MIN_PROFIT_PERCENT*100:.1f}%")
        print(f"   🚨 Стоп-лосс: {self.STOP_LOSS_PERCENT*100:.0f}%")
        print(f"   🏗️ Пирамида: {len(self.PYRAMID_LEVELS)} уровня")
        print(f"   🛒 DCA: {self.DCA_DROP_THRESHOLD*100:.0f}% падение")
