#!/usr/bin/env python3
"""⚙️ Миграция Part 3 - Конфигурация"""

import logging
from pathlib import Path


class Migration:
    """⚙️ Миграция системы конфигурации"""
    
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.src_dir = project_root / "src"
        self.config_dir = self.src_dir / "config"
        self.logger = logging.getLogger(__name__)

    def execute(self) -> bool:
        """🚀 Выполнение миграции"""
        try:
            self.logger.info("⚙️ Создание системы конфигурации...")
            
            # Создаем структуру директорий
            self._create_directory_structure()
            
            # Создаем базовые настройки
            self._create_settings()
            
            # Создаем константы
            self._create_constants()
            
            self.logger.info("✅ Система конфигурации создана")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка создания конфигурации: {e}")
            return False

    def _create_directory_structure(self):
        """📁 Создание структуры директорий"""
        dirs_to_create = [
            self.config_dir,
        ]
        
        for dir_path in dirs_to_create:
            dir_path.mkdir(parents=True, exist_ok=True)
            
            # Создаем __init__.py
            init_file = dir_path / "__init__.py"
            if not init_file.exists():
                init_file.write_text('"""⚙️ Конфигурация торговой системы"""\n')

    def _create_settings(self):
        """⚙️ Создание основных настроек"""
        settings_content = '''#!/usr/bin/env python3
"""⚙️ Основные настройки торговой системы"""

import os
from pathlib import Path
from typing import Optional, Dict, Any, List
from decimal import Decimal
from dataclasses import dataclass, field
from dotenv import load_dotenv

from ..core.exceptions import ConfigurationError, ValidationError


@dataclass
class ExchangeSettings:
    """🌐 Настройки биржи"""
    api_key: str = ""
    api_secret: str = ""
    base_url: str = "https://api.exmo.com/v1.1/"
    timeout: int = 10
    max_retries: int = 3
    rate_limit_per_minute: int = 30
    rate_limit_per_hour: int = 300
    
    def validate(self) -> bool:
        """✅ Валидация настроек биржи"""
        if not self.api_key or not self.api_secret:
            raise ConfigurationError("API ключи не установлены")
        
        if len(self.api_key) < 10 or len(self.api_secret) < 10:
            raise ConfigurationError("API ключи слишком короткие")
        
        if self.timeout <= 0 or self.max_retries <= 0:
            raise ConfigurationError("Timeout и max_retries должны быть положительными")
        
        return True


@dataclass
class TradingSettings:
    """💱 Торговые настройки"""
    trading_pair: str = "DOGE_EUR"
    position_size_percent: Decimal = Decimal("6.0")
    max_position_size_percent: Decimal = Decimal("50.0")
    min_order_size: Decimal = Decimal("5.0")
    stop_loss_percent: Decimal = Decimal("15.0")
    take_profit_percent: Decimal = Decimal("2.0")
    max_daily_trades: int = 20
    cooldown_minutes: int = 15
    
    def validate(self) -> bool:
        """✅ Валидация торговых настроек"""
        if self.position_size_percent <= 0 or self.position_size_percent > 100:
            raise ValidationError("position_size_percent", "Must be between 0 and 100")
        
        if self.max_position_size_percent <= 0 or self.max_position_size_percent > 100:
            raise ValidationError("max_position_size_percent", "Must be between 0 and 100")
        
        if self.position_size_percent > self.max_position_size_percent:
            raise ValidationError("position_size_percent", "Cannot exceed max_position_size_percent")
        
        if self.min_order_size <= 0:
            raise ValidationError("min_order_size", "Must be positive")
        
        if self.max_daily_trades <= 0:
            raise ValidationError("max_daily_trades", "Must be positive")
        
        return True


@dataclass
class DCASettings:
    """🛒 Настройки DCA стратегии"""
    enabled: bool = True
    drop_threshold_percent: Decimal = Decimal("1.5")
    purchase_size_percent: Decimal = Decimal("3.0")
    max_purchases: int = 5
    max_position_percent: Decimal = Decimal("45.0")
    cooldown_minutes: int = 20
    max_consecutive: int = 3
    max_per_day: int = 5
    loss_block_threshold_percent: Decimal = Decimal("8.0")
    
    def validate(self) -> bool:
        """✅ Валидация настроек DCA"""
        if self.drop_threshold_percent <= 0:
            raise ValidationError("drop_threshold_percent", "Must be positive")
        
        if self.purchase_size_percent <= 0 or self.purchase_size_percent > 50:
            raise ValidationError("purchase_size_percent", "Must be between 0 and 50")
        
        if self.max_purchases <= 0:
            raise ValidationError("max_purchases", "Must be positive")
        
        if self.max_position_percent <= 0 or self.max_position_percent > 100:
            raise ValidationError("max_position_percent", "Must be between 0 and 100")
        
        return True


@dataclass
class RiskSettings:
    """🛡️ Настройки управления рисками"""
    emergency_exit_enabled: bool = True
    emergency_exit_threshold_percent: Decimal = Decimal("15.0")
    critical_loss_threshold_percent: Decimal = Decimal("10.0")
    max_position_hold_hours: int = 24
    max_daily_loss_percent: Decimal = Decimal("5.0")
    dca_limiter_enabled: bool = True
    btc_correlation_enabled: bool = True
    btc_volatility_threshold_percent: Decimal = Decimal("3.0")
    
    def validate(self) -> bool:
        """✅ Валидация настроек рисков"""
        if self.emergency_exit_threshold_percent <= 0:
            raise ValidationError("emergency_exit_threshold_percent", "Must be positive")
        
        if self.critical_loss_threshold_percent >= self.emergency_exit_threshold_percent:
            raise ValidationError("critical_loss_threshold_percent", 
                                "Must be less than emergency_exit_threshold_percent")
        
        if self.max_daily_loss_percent <= 0 or self.max_daily_loss_percent > 50:
            raise ValidationError("max_daily_loss_percent", "Must be between 0 and 50")
        
        return True


@dataclass
class LoggingSettings:
    """📝 Настройки логирования"""
    level: str = "INFO"
    enable_file_logging: bool = True
    enable_console_logging: bool = True
    log_dir: str = "logs"
    main_log_file: str = "trading_bot.log"
    trades_log_file: str = "trades.log"
    errors_log_file: str = "errors.log"
    max_log_size_mb: int = 50
    backup_count: int = 5
    
    def validate(self) -> bool:
        """✅ Валидация настроек логирования"""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if self.level not in valid_levels:
            raise ValidationError("level", f"Must be one of: {valid_levels}")
        
        if self.max_log_size_mb <= 0:
            raise ValidationError("max_log_size_mb", "Must be positive")
        
        return True


@dataclass
class Settings:
    """⚙️ Главный класс настроек"""
    # Основные секции
    exchange: ExchangeSettings = field(default_factory=ExchangeSettings)
    trading: TradingSettings = field(default_factory=TradingSettings)
    dca: DCASettings = field(default_factory=DCASettings)
    risk: RiskSettings = field(default_factory=RiskSettings)
    logging: LoggingSettings = field(default_factory=LoggingSettings)
    
    # Метаданные
    profile_name: str = "balanced"
    mode: str = "live"  # live, paper, backtest
    version: str = "4.1-refactored"
    
    def validate(self) -> bool:
        """✅ Полная валидация всех настроек"""
        try:
            self.exchange.validate()
            self.trading.validate()
            self.dca.validate()
            self.risk.validate()
            self.logging.validate()
            
            # Проверка совместимости настроек
            self._validate_compatibility()
            
            return True
            
        except (ValidationError, ConfigurationError) as e:
            raise ConfigurationError(f"Validation failed: {e}")
    
    def _validate_compatibility(self) -> None:
        """🔗 Валидация совместимости настроек"""
        # DCA + Trading совместимость
        total_dca_position = self.dca.purchase_size_percent * self.dca.max_purchases
        if total_dca_position > self.trading.max_position_size_percent:
            raise ValidationError("dca_compatibility", 
                                "Total DCA position exceeds max position size")
    
    def to_dict(self) -> Dict[str, Any]:
        """📋 Конвертация в словарь"""
        from dataclasses import asdict
        return asdict(self)


# Глобальная переменная для кэширования настроек
_cached_settings: Optional[Settings] = None


def get_settings(force_reload: bool = False) -> Settings:
    """⚙️ Получение настроек (с кэшированием)"""
    global _cached_settings
    
    if _cached_settings is None or force_reload:
        _cached_settings = load_settings()
    
    return _cached_settings


def load_settings() -> Settings:
    """📥 Загрузка настроек из файлов"""
    # Загружаем переменные окружения
    env_file = Path(".env")
    if env_file.exists():
        load_dotenv(env_file)
    
    # Создаем базовые настройки
    settings = Settings()
    
    # Загружаем настройки биржи из переменных окружения
    settings.exchange.api_key = os.getenv("EXMO_API_KEY", "")
    settings.exchange.api_secret = os.getenv("EXMO_API_SECRET", "")
    
    # Торговая пара
    trading_pair_1 = os.getenv("TRADING_PAIR_1", "DOGE")
    trading_pair_2 = os.getenv("TRADING_PAIR_2", "EUR")
    settings.trading.trading_pair = f"{trading_pair_1}_{trading_pair_2}"
    
    # Профиль
    profile_name = os.getenv("TRADING_PROFILE", "balanced")
    settings.profile_name = profile_name
    
    # Режим
    mode = os.getenv("TRADING_MODE", "live")
    settings.mode = mode
    
    # Применяем профиль
    _apply_profile(settings, profile_name)
    
    return settings


def _apply_profile(settings: Settings, profile_name: str) -> None:
    """📊 Применение профиля к настройкам"""
    if profile_name == "conservative":
        settings.trading.position_size_percent = Decimal("4.0")
        settings.trading.stop_loss_percent = Decimal("10.0")
        settings.trading.max_daily_trades = 10
        settings.dca.max_purchases = 3
        settings.risk.max_daily_loss_percent = Decimal("3.0")
        
    elif profile_name == "aggressive":
        settings.trading.position_size_percent = Decimal("10.0")
        settings.trading.stop_loss_percent = Decimal("20.0")
        settings.trading.max_daily_trades = 30
        settings.dca.max_purchases = 7
        settings.risk.max_daily_loss_percent = Decimal("8.0")
        
    # balanced - по умолчанию


def save_settings(settings: Settings, file_path: Optional[Path] = None) -> None:
    """💾 Сохранение настроек в файл"""
    import json
    
    if file_path is None:
        file_path = Path("config.json")
    
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(settings.to_dict(), f, indent=2, ensure_ascii=False, default=str)


def create_env_example() -> str:
    """📄 Создание примера .env файла"""
    return '''# 🔑 API настройки EXMO
EXMO_API_KEY=your_api_key_here
EXMO_API_SECRET=your_api_secret_here

# 💱 Торговые настройки
TRADING_PAIR_1=DOGE
TRADING_PAIR_2=EUR
TRADING_PROFILE=balanced
TRADING_MODE=live

# 📢 Уведомления (опционально)
TELEGRAM_ENABLED=false
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# 📝 Логирование
LOG_LEVEL=INFO
'''


if __name__ == "__main__":
    # Тестирование настроек
    try:
        settings = get_settings()
        settings.validate()
        print("✅ Настройки валидны")
        print(f"📊 Профиль: {settings.profile_name}")
        print(f"💱 Торговая пара: {settings.trading.trading_pair}")
        print(f"💰 Размер позиции: {settings.trading.position_size_percent}%")
    except Exception as e:
        print(f"❌ Ошибка настроек: {e}")
    
    # Создание примера .env
    env_example = create_env_example()
    print("\n📄 Пример .env файла:")
    print(env_example)
'''

        settings_file = self.config_dir / "settings.py"
        settings_file.write_text(settings_content)
        self.logger.info("  ✅ Создан settings.py")

    def _create_constants(self):
        """📊 Создание констант"""
        constants_content = '''#!/usr/bin/env python3
"""📊 Константы торговой системы"""

from decimal import Decimal
from typing import Dict, List

# 🌐 API Константы
class API:
    # EXMO API
    EXMO_BASE_URL = "https://api.exmo.com/v1.1/"
    EXMO_TIMEOUT = 10
    EXMO_MAX_RETRIES = 3
    
    # Rate Limiting
    DEFAULT_CALLS_PER_MINUTE = 30
    DEFAULT_CALLS_PER_HOUR = 300
    
    # HTTP коды
    HTTP_OK = 200
    HTTP_TOO_MANY_REQUESTS = 429
    HTTP_UNAUTHORIZED = 401
    HTTP_FORBIDDEN = 403
    HTTP_NOT_FOUND = 404
    HTTP_SERVER_ERROR = 500

# 💱 Торговые константы
class Trading:
    # Торговые пары
    DEFAULT_PAIR = "DOGE_EUR"
    SUPPORTED_PAIRS = ["DOGE_EUR", "DOGE_USD", "DOGE_BTC", "ETH_EUR", "BTC_EUR"]
    
    # Минимальные размеры
    MIN_ORDER_SIZE = Decimal("5.0")
    MIN_QUANTITY = Decimal("0.000001")
    MIN_PRICE = Decimal("0.00000001")
    
    # Комиссии EXMO
    TAKER_FEE = Decimal("0.003")  # 0.3%
    MAKER_FEE = Decimal("0.002")  # 0.2%
    
    # Точность
    PRICE_PRECISION = 8
    QUANTITY_PRECISION = 6

# 🎯 Стратегии
class Strategies:
    # Приоритеты
    EMERGENCY_EXIT_PRIORITY = 1000
    PYRAMID_SELL_PRIORITY = 100
    DCA_BUY_PRIORITY = 50
    TRAILING_STOP_PRIORITY = 75
    HOLD_PRIORITY = 1
    
    # DCA настройки
    DCA_DEFAULT_DROP_THRESHOLD = 1.5  # %
    DCA_DEFAULT_PURCHASE_SIZE = 3.0   # % от депозита
    DCA_DEFAULT_MAX_PURCHASES = 5
    DCA_DEFAULT_COOLDOWN_MINUTES = 20
    DCA_DEFAULT_MAX_POSITION = 45.0   # % от депозита

# 🛡️ Риск-менеджмент
class Risk:
    # Лимиты убытков
    DEFAULT_STOP_LOSS = 15.0          # %
    EMERGENCY_EXIT_THRESHOLD = 15.0   # %
    CRITICAL_LOSS_THRESHOLD = 10.0    # %
    
    # Размеры позиций
    DEFAULT_POSITION_SIZE = 6.0       # % от депозита
    MAX_POSITION_SIZE = 50.0          # %
    MIN_POSITION_SIZE = 1.0           # %
    
    # Временные лимиты
    MAX_POSITION_HOLD_HOURS = 24
    DCA_COOLDOWN_MINUTES = 30
    EMERGENCY_COOLDOWN_HOURS = 2

# 📝 Логирование
class Logging:
    DEFAULT_LEVEL = "INFO"
    LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
    
    # Файлы логов
    MAIN_LOG_FILE = "logs/trading_bot.log"
    TRADES_LOG_FILE = "logs/trades.log"
    ERRORS_LOG_FILE = "logs/errors.log"

# 📊 Аналитика
class Analytics:
    # Интервалы обновления
    FAST_UPDATE_SECONDS = 5
    NORMAL_UPDATE_SECONDS = 15
    SLOW_UPDATE_SECONDS = 60
    
    # Периоды анализа
    SHORT_PERIOD_MINUTES = 15
    MEDIUM_PERIOD_MINUTES = 60
    LONG_PERIOD_MINUTES = 240

# Валюты и форматирование
SUPPORTED_CURRENCIES = ["EUR", "USD", "BTC", "ETH", "DOGE"]
DECIMAL_PLACES = 8
PERCENTAGE_PRECISION = 2

# 🏗️ Dependency Injection
class DI:
    SINGLETON_LIFETIME = "singleton"
    TRANSIENT_LIFETIME = "transient"
    SCOPED_LIFETIME = "scoped"

# ⚙️ Конфигурация
class Config:
    ENV_FILE = ".env"
    CONFIG_FILE = "config.yaml"
    
    # Профили
    CONSERVATIVE_PROFILE = "conservative"
    BALANCED_PROFILE = "balanced"
    AGGRESSIVE_PROFILE = "aggressive"
    
    # Режимы
    LIVE_MODE = "live"
    PAPER_MODE = "paper"
    BACKTEST_MODE = "backtest"

# 📢 Уведомления
class Notifications:
    # Типы уведомлений
    INFO_TYPE = "info"
    WARNING_TYPE = "warning"
    ERROR_TYPE = "error"
    EMERGENCY_TYPE = "emergency"
    
    # Каналы
    CONSOLE_CHANNEL = "console"
    FILE_CHANNEL = "file"
    TELEGRAM_CHANNEL = "telegram"
    EMAIL_CHANNEL = "email"

# 🧪 Тестирование
class Testing:
    # Маркеры pytest
    UNIT_MARKER = "unit"
    INTEGRATION_MARKER = "integration"
    SLOW_MARKER = "slow"
    
    # Мок данные
    MOCK_BALANCE = Decimal("1000.0")
    MOCK_PRICE = Decimal("0.18")
    MOCK_QUANTITY = Decimal("100.0")

# 🏥 Мониторинг
class Monitoring:
    # Интервалы проверки здоровья
    HEALTH_CHECK_INTERVAL_SECONDS = 30
    API_CHECK_INTERVAL_SECONDS = 60
    
    # Таймауты
    HEALTH_CHECK_TIMEOUT = 5
    API_CHECK_TIMEOUT = 10
    
    # Пороги предупреждений
    HIGH_CPU_THRESHOLD = 80.0     # %
    HIGH_MEMORY_THRESHOLD = 80.0  # %
    LOW_DISK_THRESHOLD = 10.0     # %

# 🔄 Адаптеры
class Adapters:
    # Режимы адаптации
    HYBRID_MODE = "hybrid"
    LEGACY_MODE = "legacy"
    NEW_MODE = "new"
    
    # Префиксы старых классов
    LEGACY_PREFIX = "Legacy"
    ADAPTED_PREFIX = "Adapted"

# 📅 Временные константы
class Time:
    SECONDS_IN_MINUTE = 60
    MINUTES_IN_HOUR = 60
    HOURS_IN_DAY = 24
    DAYS_IN_WEEK = 7
    
    # Интервалы обновления
    FAST_UPDATE_INTERVAL = 5      # секунд
    NORMAL_UPDATE_INTERVAL = 15   # секунд
    SLOW_UPDATE_INTERVAL = 60     # секунд

# 🎨 UI/Отображение
class Display:
    # Цвета для консольного вывода
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"
    END = "\033[0m"
    
    # Эмодзи для статусов
    SUCCESS_EMOJI = "✅"
    ERROR_EMOJI = "❌"
    WARNING_EMOJI = "⚠️"
    INFO_EMOJI = "ℹ️"
    MONEY_EMOJI = "💰"
    CHART_EMOJI = "📊"
    ROBOT_EMOJI = "🤖"

# 📊 Математические константы
class Math:
    # Пороги для сравнений
    EPSILON = 1e-8
    PERCENTAGE_MULTIPLIER = 100
    
    # Статистические константы
    CONFIDENCE_INTERVAL_95 = 1.96
    CONFIDENCE_INTERVAL_99 = 2.576

# 🔐 Безопасность
class Security:
    # Минимальные требования к API ключам
    MIN_API_KEY_LENGTH = 10
    MIN_API_SECRET_LENGTH = 10
    
    # Таймауты безопасности
    API_TIMEOUT_SECONDS = 30
    MAX_RETRY_ATTEMPTS = 3
    RETRY_DELAY_SECONDS = 1

# 📁 Файловая система
class FileSystem:
    # Директории
    DATA_DIR = "data"
    LOGS_DIR = "logs"
    CONFIG_DIR = "config"
    BACKUP_DIR = "backup"
    CHARTS_DIR = "charts"
    REPORTS_DIR = "reports"
    
    # Файлы данных
    POSITIONS_FILE = "positions.json"
    TRADES_FILE = "trades_history.json"
    CONFIG_FILE = "runtime_config.json"
    
    # Расширения файлов
    JSON_EXT = ".json"
    LOG_EXT = ".log"
    CSV_EXT = ".csv"
    PNG_EXT = ".png"

# 🌐 Сеть
class Network:
    # Таймауты
    DEFAULT_TIMEOUT = 10
    LONG_TIMEOUT = 30
    SHORT_TIMEOUT = 5
    
    # Retry настройки
    MAX_RETRIES = 3
    RETRY_DELAY = 1
    BACKOFF_FACTOR = 2

# 📈 Технический анализ
class TechnicalAnalysis:
    # Периоды для индикаторов
    RSI_PERIOD = 14
    MA_SHORT_PERIOD = 10
    MA_LONG_PERIOD = 50
    MACD_FAST_PERIOD = 12
    MACD_SLOW_PERIOD = 26
    MACD_SIGNAL_PERIOD = 9
    
    # Пороги для сигналов
    RSI_OVERSOLD = 30
    RSI_OVERBOUGHT = 70
    VOLUME_SPIKE_THRESHOLD = 2.0  # 200% от среднего

# 💎 Качество кода
class CodeQuality:
    # Максимальные размеры
    MAX_FUNCTION_LINES = 50
    MAX_CLASS_LINES = 500
    MAX_FILE_LINES = 1000
    MAX_COMPLEXITY = 10
    
    # Покрытие тестами
    MIN_TEST_COVERAGE = 80  # %

# 🚀 Производительность
class Performance:
    # Лимиты производительности
    MAX_RESPONSE_TIME_MS = 1000
    MAX_MEMORY_USAGE_MB = 500
    MAX_CPU_USAGE_PERCENT = 80
    
    # Кэширование
    CACHE_TTL_SECONDS = 300  # 5 минут
    MAX_CACHE_SIZE = 1000

# 🎯 Цели производительности
class Targets:
    # Торговые цели
    DAILY_PROFIT_TARGET_PERCENT = 1.0
    WEEKLY_PROFIT_TARGET_PERCENT = 5.0
    MONTHLY_PROFIT_TARGET_PERCENT = 20.0
    
    # Риски
    MAX_DAILY_LOSS_PERCENT = 2.0
    MAX_WEEKLY_LOSS_PERCENT = 5.0
    MAX_MONTHLY_LOSS_PERCENT = 10.0
    
    # Эффективность
    MIN_WIN_RATE_PERCENT = 60.0
    MIN_PROFIT_FACTOR = 1.5
    MAX_DRAWDOWN_PERCENT = 10.0

# 📦 Версионирование
class Versions:
    CURRENT_VERSION = "4.1-refactored"
    MIGRATION_VERSION = "4.1"
    LEGACY_VERSION = "4.0"
    
    # Совместимость API
    MIN_PYTHON_VERSION = (3, 8)
    RECOMMENDED_PYTHON_VERSION = (3, 11)

# 🏷️ Метки и теги
class Tags:
    # Теги для стратегий
    DCA_TAG = "dca"
    PYRAMID_TAG = "pyramid"
    TRAILING_TAG = "trailing"
    EMERGENCY_TAG = "emergency"
    
    # Теги для анализа
    BULLISH_TAG = "bullish"
    BEARISH_TAG = "bearish"
    NEUTRAL_TAG = "neutral"
    VOLATILE_TAG = "volatile"

# 🔧 Инструменты разработки
class DevTools:
    # Форматтеры
    BLACK_LINE_LENGTH = 88
    ISORT_PROFILE = "black"
    
    # Линтеры
    PYLINT_MIN_SCORE = 8.0
    FLAKE8_MAX_LINE_LENGTH = 88
    
    # Документация
    DOCSTRING_STYLE = "google"


# Глобальные настройки по умолчанию
DEFAULT_SETTINGS = {
    'trading': {
        'position_size_percent': 6.0,
        'max_position_size_percent': 50.0,
        'stop_loss_percent': 15.0,
        'take_profit_percent': 2.0,
        'max_daily_trades': 20,
        'cooldown_minutes': 15
    },
    'dca': {
        'enabled': True,
        'drop_threshold_percent': 1.5,
        'purchase_size_percent': 3.0,
        'max_purchases': 5,
        'max_position_percent': 45.0,
        'cooldown_minutes': 20
    },
    'risk': {
        'emergency_exit_enabled': True,
        'emergency_exit_threshold_percent': 15.0,
        'critical_loss_threshold_percent': 10.0,
        'max_daily_loss_percent': 5.0
    }
}

# Профили конфигурации
TRADING_PROFILES = {
    'conservative': {
        'position_size_percent': 4.0,
        'stop_loss_percent': 10.0,
        'max_daily_trades': 10,
        'dca_max_purchases': 3,
        'max_daily_loss_percent': 3.0
    },
    'balanced': {
        'position_size_percent': 6.0,
        'stop_loss_percent': 15.0,
        'max_daily_trades': 20,
        'dca_max_purchases': 5,
        'max_daily_loss_percent': 5.0
    },
    'aggressive': {
        'position_size_percent': 10.0,
        'stop_loss_percent': 20.0,
        'max_daily_trades': 30,
        'dca_max_purchases': 7,
        'max_daily_loss_percent': 8.0
    }
}


def get_profile_settings(profile_name: str) -> Dict:
    """📊 Получение настроек профиля"""
    return TRADING_PROFILES.get(profile_name, TRADING_PROFILES['balanced'])


def validate_constants():
    """✅ Валидация констант"""
    # Проверяем логическую согласованность
    assert Risk.CRITICAL_LOSS_THRESHOLD < Risk.EMERGENCY_EXIT_THRESHOLD
    assert Trading.MIN_QUANTITY < Trading.MIN_ORDER_SIZE
    assert API.DEFAULT_CALLS_PER_MINUTE * 60 <= API.DEFAULT_CALLS_PER_HOUR
    
    print("✅ Константы валидны")


if __name__ == "__main__":
    # Тестирование констант
    validate_constants()
    
    print(f"🌐 API URL: {API.EXMO_BASE_URL}")
    print(f"💱 Торговая пара по умолчанию: {Trading.DEFAULT_PAIR}")
    print(f"🛡️ Аварийный порог: {Risk.EMERGENCY_EXIT_THRESHOLD}%")
    print(f"📊 Интервал обновления: {Analytics.NORMAL_UPDATE_SECONDS}с")
    
    # Проверяем профили
    for profile_name, settings in TRADING_PROFILES.items():
        print(f"📊 Профиль {profile_name}: позиция {settings['position_size_percent']}%")
    
    print("📊 Константы системы готовы")
'''

        constants_file = self.config_dir / "constants.py"
        constants_file.write_text(constants_content)
        self.logger.info("  ✅ Создан constants.py")
    