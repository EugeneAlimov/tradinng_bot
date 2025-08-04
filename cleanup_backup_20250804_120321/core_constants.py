#!/usr/bin/env python3
"""🎯 Константы торговой системы"""

from decimal import Decimal
from typing import Dict, List

# 🌐 API Константы
class API:
    # EXMO API
    EXMO_BASE_URL = "https://api.exmo.com/v1.1/"
    EXMO_TIMEOUT = 10
    EXMO_MAX_RETRIES = 3
    
    # Rate Limiting (по умолчанию)
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
    MIN_ORDER_SIZE = Decimal("5.0")  # Минимальный размер ордера в EUR
    MIN_QUANTITY = Decimal("0.000001")  # Минимальное количество
    MIN_PRICE = Decimal("0.00000001")  # Минимальная цена
    
    # Комиссии (EXMO)
    TAKER_FEE = Decimal("0.003")  # 0.3%
    MAKER_FEE = Decimal("0.002")  # 0.2%
    
    # Точность
    PRICE_PRECISION = 8
    QUANTITY_PRECISION = 6


# 🎯 Стратегии
class Strategies:
    # Приоритеты стратегий
    EMERGENCY_EXIT_PRIORITY = 1000
    PYRAMID_SELL_PRIORITY = 100
    DCA_BUY_PRIORITY = 50
    TRAILING_STOP_PRIORITY = 75
    HOLD_PRIORITY = 1
    
    # DCA настройки по умолчанию
    DCA_DEFAULT_DROP_THRESHOLD = 1.5  # %
    DCA_DEFAULT_PURCHASE_SIZE = 3.0   # % от депозита
    DCA_DEFAULT_MAX_PURCHASES = 5
    DCA_DEFAULT_COOLDOWN_MINUTES = 20
    DCA_DEFAULT_MAX_POSITION = 45.0   # % от депозита
    
    # Пирамида по умолчанию
    PYRAMID_DEFAULT_LEVELS = [
        {"profit_pct": 0.8, "sell_pct": 25.0, "min_eur": 0.08},
        {"profit_pct": 2.0, "sell_pct": 35.0, "min_eur": 0.15},
        {"profit_pct": 4.0, "sell_pct": 25.0, "min_eur": 0.25},
        {"profit_pct": 7.0, "sell_pct": 15.0, "min_eur": 0.40},
    ]
    
    # Trailing Stop
    TRAILING_ACTIVATION_PROFIT = 1.2  # % прибыли для активации
    TRAILING_DISTANCE = 0.5           # % расстояние от пика
    TRAILING_PARTIAL_SELL = 70.0      # % продажи при активации


# 🛡️ Риск-менеджмент
class Risk:
    # Общие лимиты
    DEFAULT_POSITION_SIZE = 6.0       # % от депозита
    DEFAULT_MIN_PROFIT = 0.8          # % минимальная прибыль
    DEFAULT_STOP_LOSS = 8.0           # % стоп-лосс
    MAX_DAILY_LOSS = 2.0              # % максимальные потери в день
    
    # Аварийный выход
    EMERGENCY_CRITICAL_LOSS = 15.0    # % критический убыток
    EMERGENCY_MAJOR_LOSS = 12.0       # % большой убыток
    EMERGENCY_SIGNIFICANT_LOSS = 8.0  # % значительный убыток
    EMERGENCY_TIME_LIMIT_HOURS = 24   # часов в убытке
    
    # DCA лимиты
    DCA_MAX_CONSECUTIVE = 3           # Максимум DCA подряд
    DCA_MAX_PER_DAY = 5              # Максимум DCA в день
    DCA_MIN_INTERVAL_MINUTES = 25     # Минимальный интервал между DCA
    DCA_LOSS_BLOCK_THRESHOLD = 8.0    # % убытка для блокировки DCA
    
    # Волатильность
    HIGH_VOLATILITY_THRESHOLD = 3.0   # % волатильность для блокировки
    BTC_CRASH_THRESHOLD = 5.0         # % падение BTC для блокировки
    
    # Лимиты операций
    MAX_TRADES_PER_HOUR = 6
    MAX_TRADES_PER_DAY = 50
    MAX_API_ERRORS_PER_HOUR = 10


# ⏰ Временные константы
class Timing:
    # Интервалы обновления
    DEFAULT_UPDATE_INTERVAL = 6       # секунд
    FAST_UPDATE_INTERVAL = 3          # секунд (при активной торговле)
    SLOW_UPDATE_INTERVAL = 10         # секунд (в спокойном режиме)
    
    # Таймауты
    API_TIMEOUT = 10                  # секунд
    ORDER_TIMEOUT = 30                # секунд
    PRICE_VALIDITY = 60               # секунд
    
    # Кэширование
    CACHE_DEFAULT_TTL = 300           # 5 минут
    CACHE_PRICE_TTL = 10              # 10 секунд
    CACHE_BALANCE_TTL = 30            # 30 секунд
    CACHE_SETTINGS_TTL = 3600         # 1 час
    
    # Периоды анализа
    ANALYSIS_SHORT_PERIOD = 14        # дней
    ANALYSIS_MEDIUM_PERIOD = 30       # дней
    ANALYSIS_LONG_PERIOD = 90         # дней


# 📊 Аналитика
class Analytics:
    # Метрики
    MIN_TRADES_FOR_ANALYSIS = 10
    SHARPE_RATIO_RISK_FREE_RATE = 0.02  # 2% годовых
    
    # Экспорт форматы
    SUPPORTED_EXPORT_FORMATS = ["json", "csv", "xlsx"]
    
    # Типы отчетов
    REPORT_TYPES = [
        "daily", "weekly", "monthly", 
        "performance", "risk", "trades"
    ]
    
    # Графики
    CHART_TYPES = [
        "pnl", "balance", "trades", 
        "drawdown", "correlation"
    ]


# 📝 Логирование
class Logging:
    # Уровни
    LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    DEFAULT_LEVEL = "INFO"
    
    # Форматы
    CONSOLE_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    FILE_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s"
    
    # Размеры файлов
    MAX_LOG_FILE_SIZE = 10 * 1024 * 1024  # 10MB
    MAX_LOG_FILES = 5
    
    # Категории логов
    TRADING_LOGGER = "trading"
    API_LOGGER = "api"
    STRATEGY_LOGGER = "strategy"
    RISK_LOGGER = "risk"
    ANALYTICS_LOGGER = "analytics"


# 🗄️ Персистентность
class Persistence:
    # Директории
    DATA_DIR = "data"
    LOGS_DIR = "logs"
    CONFIG_DIR = "config"
    BACKUP_DIR = "backup"
    TEMP_DIR = "temp"
    
    # Файлы
    POSITIONS_FILE = "positions.json"
    TRADES_FILE = "trades_history.json"
    ANALYTICS_FILE = "analytics.json"
    CONFIG_FILE = "settings.json"
    
    # Бэкапы
    BACKUP_INTERVAL_HOURS = 6
    MAX_BACKUPS = 30
    BACKUP_NAME_FORMAT = "%Y%m%d_%H%M%S"


# 📡 События
class Events:
    # Типы событий
    TRADE_EXECUTED = "trade_executed"
    POSITION_OPENED = "position_opened"
    POSITION_CLOSED = "position_closed"
    EMERGENCY_EXIT = "emergency_exit"
    RISK_LIMIT_EXCEEDED = "risk_limit_exceeded"
    STRATEGY_SIGNAL = "strategy_signal"
    API_ERROR = "api_error"
    SYSTEM_START = "system_start"
    SYSTEM_STOP = "system_stop"
    
    # Приоритеты событий
    PRIORITY_LOW = 1
    PRIORITY_NORMAL = 2
    PRIORITY_HIGH = 3
    PRIORITY_URGENT = 4
    PRIORITY_CRITICAL = 5


# 📱 Уведомления
class Notifications:
    # Типы уведомлений
    EMAIL = "email"
    TELEGRAM = "telegram"
    WEBHOOK = "webhook"
    CONSOLE = "console"
    
    # Шаблоны уведомлений
    TRADE_NOTIFICATION = "trade_executed"
    EMERGENCY_ALERT = "emergency_exit"
    DAILY_REPORT = "daily_report"
    ERROR_ALERT = "error_alert"
    
    # Настройки Telegram
    TELEGRAM_MAX_MESSAGE_LENGTH = 4096
    TELEGRAM_RETRY_ATTEMPTS = 3


# 🔧 Конфигурационные профили
class Profiles:
    # Имена профилей
    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    AGGRESSIVE = "aggressive"
    CUSTOM = "custom"
    
    # Параметры профилей
    PROFILE_CONFIGS = {
        CONSERVATIVE: {
            "position_size_pct": 4.0,
            "min_profit_pct": 1.2,
            "stop_loss_pct": 6.0,
            "dca_purchase_size_pct": 2.0,
            "dca_max_purchases": 3,
            "update_interval": 8
        },
        BALANCED: {
            "position_size_pct": 6.0,
            "min_profit_pct": 0.8,
            "stop_loss_pct": 8.0,
            "dca_purchase_size_pct": 3.0,
            "dca_max_purchases": 5,
            "update_interval": 6
        },
        AGGRESSIVE: {
            "position_size_pct": 10.0,
            "min_profit_pct": 0.6,
            "stop_loss_pct": 12.0,
            "dca_purchase_size_pct": 5.0,
            "dca_max_purchases": 7,
            "update_interval": 4
        }
    }


# 🌐 Внешние сервисы
class ExternalServices:
    # CoinGecko (для BTC данных)
    COINGECKO_BASE_URL = "https://api.coingecko.com/api/v3"
    COINGECKO_TIMEOUT = 5
    
    # Telegram Bot API
    TELEGRAM_BASE_URL = "https://api.telegram.org/bot"
    
    # Webhook endpoints
    DEFAULT_WEBHOOK_TIMEOUT = 10
    WEBHOOK_MAX_RETRIES = 3


# 🔐 Безопасность
class Security:
    # API ключи
    MIN_API_KEY_LENGTH = 32
    API_KEY_PATTERN = r"^[A-Za-z0-9+/]{32,}={0,2}$"
    
    # Шифрование
    ENCRYPTION_ALGORITHM = "AES-256-GCM"
    KEY_DERIVATION_ITERATIONS = 100000
    
    # Валидация
    MAX_CONFIG_VALUE = 1000000
    MIN_CONFIG_VALUE = -1000000
    
    # Паттерны валидации
    CURRENCY_PATTERN = r"^[A-Z]{3,5}$"
    PAIR_PATTERN = r"^[A-Z]{3,5}_[A-Z]{3,5}$"


# 📊 Технические индикаторы
class Indicators:
    # RSI
    RSI_PERIOD = 14
    RSI_OVERBOUGHT = 70
    RSI_OVERSOLD = 30
    
    # MACD
    MACD_FAST_PERIOD = 12
    MACD_SLOW_PERIOD = 26
    MACD_SIGNAL_PERIOD = 9
    
    # Bollinger Bands
    BB_PERIOD = 20
    BB_STD_DEV = 2
    
    # Moving Averages
    SMA_SHORT_PERIOD = 7
    SMA_LONG_PERIOD = 25
    EMA_PERIOD = 12
    
    # Минимальные данные для расчета
    MIN_DATA_POINTS = 50


# 🎨 UI/UX
class UI:
    # Эмодзи для логов
    EMOJIS = {
        "buy": "🛒",
        "sell": "💎",
        "hold": "💎",
        "profit": "📈",
        "loss": "📉",
        "emergency": "🚨",
        "warning": "⚠️",
        "info": "ℹ️",
        "success": "✅",
        "error": "❌",
        "money": "💰",
        "chart": "📊",
        "robot": "🤖",
        "shield": "🛡️",
        "rocket": "🚀"
    }
    
    # Цвета для консоли
    COLORS = {
        "red": "\033[91m",
        "green": "\033[92m",
        "yellow": "\033[93m",
        "blue": "\033[94m",
        "purple": "\033[95m",
        "cyan": "\033[96m",
        "white": "\033[97m",
        "reset": "\033[0m"
    }


# 🧪 Тестирование
class Testing:
    # Моковые данные
    MOCK_BALANCE = Decimal("1000.0")
    MOCK_PRICE = Decimal("0.18")
    MOCK_QUANTITY = Decimal("100.0")
    
    # Тестовые пары
    TEST_PAIR = "TEST_EUR"
    
    # Допустимые отклонения
    PRICE_TOLERANCE = Decimal("0.001")
    QUANTITY_TOLERANCE = Decimal("0.000001")
    
    # Тестовые периоды
    BACKTEST_START_DATE = "2023-01-01"
    BACKTEST_END_DATE = "2023-12-31"


# 🚀 Производительность
class Performance:
    # Лимиты памяти
    MAX_MEMORY_MB = 512
    MAX_CACHE_ENTRIES = 1000
    
    # Оптимизация
    BATCH_SIZE = 100
    MAX_CONCURRENT_REQUESTS = 5
    
    # Мониторинг
    PERFORMANCE_CHECK_INTERVAL = 300  # 5 минут
    
    # Circuit Breaker
    CIRCUIT_BREAKER_FAILURE_THRESHOLD = 5
    CIRCUIT_BREAKER_TIMEOUT = 60
    CIRCUIT_BREAKER_RECOVERY_TIMEOUT = 300


# 📈 Backtesting
class Backtesting:
    # Параметры по умолчанию
    DEFAULT_INITIAL_BALANCE = Decimal("1000.0")
    DEFAULT_COMMISSION_RATE = Decimal("0.003")
    
    # Статистики
    MIN_TRADES_FOR_STATS = 10
    CONFIDENCE_LEVEL = 0.95
    
    # Периоды
    LOOKBACK_PERIODS = [7, 14, 30, 60, 90, 180, 365]


# 🔄 Версионирование
class Versioning:
    MAJOR = 4
    MINOR = 1
    PATCH = 0
    SUFFIX = "refactored"
    
    @classmethod
    def get_version(cls) -> str:
        """📋 Получение версии"""
        version = f"{cls.MAJOR}.{cls.MINOR}.{cls.PATCH}"
        if cls.SUFFIX:
            version += f"-{cls.SUFFIX}"
        return version
    
    @classmethod
    def get_version_info(cls) -> Dict[str, any]:
        """📊 Информация о версии"""
        return {
            "version": cls.get_version(),
            "major": cls.MAJOR,
            "minor": cls.MINOR,
            "patch": cls.PATCH,
            "suffix": cls.SUFFIX
        }


# 🎯 Константы сообщений
class Messages:
    # Успех
    SYSTEM_STARTED = "🚀 Торговая система запущена"
    TRADE_EXECUTED = "✅ Сделка выполнена"
    POSITION_OPENED = "📊 Позиция открыта"
    POSITION_CLOSED = "🔒 Позиция закрыта"
    
    # Предупреждения
    HIGH_VOLATILITY = "⚠️ Высокая волатильность рынка"
    APPROACHING_LIMIT = "⚠️ Приближение к лимиту"
    API_RATE_LIMIT = "⚠️ Ограничение скорости API"
    
    # Ошибки
    INSUFFICIENT_BALANCE = "❌ Недостаточно средств"
    API_CONNECTION_ERROR = "❌ Ошибка подключения к API"
    POSITION_NOT_FOUND = "❌ Позиция не найдена"
    INVALID_CONFIGURATION = "❌ Некорректная конфигурация"
    
    # Критические
    EMERGENCY_EXIT_TRIGGERED = "🚨 АВАРИЙНЫЙ ВЫХОД АКТИВИРОВАН"
    SYSTEM_OVERLOAD = "🚨 ПЕРЕГРУЗКА СИСТЕМЫ"
    CRITICAL_ERROR = "🚨 КРИТИЧЕСКАЯ ОШИБКА"


# 🔗 URL и пути
class Paths:
    # Относительные пути
    SRC = "src"
    CORE = f"{SRC}/core"
    DOMAIN = f"{SRC}/domain"
    INFRASTRUCTURE = f"{SRC}/infrastructure"
    APPLICATION = f"{SRC}/application"
    PRESENTATION = f"{SRC}/presentation"
    CONFIG = f"{SRC}/config"
    
    # Файлы конфигурации
    ENV_FILE = ".env"
    SETTINGS_FILE = f"{CONFIG}/settings.json"
    PROFILES_FILE = f"{CONFIG}/profiles.json"
    
    # Документация
    DOCS = "docs"
    README = "README.md"
    CHANGELOG = "CHANGELOG.md"


# Валидация констант при импорте
def validate_constants():
    """✅ Валидация значений констант"""
    
    # Проверяем торговые лимиты
    assert Trading.MIN_ORDER_SIZE > 0, "Минимальный размер ордера должен быть положительным"
    assert Trading.TAKER_FEE >= 0, "Комиссия не может быть отрицательной"
    
    # Проверяем риск-параметры
    assert 0 < Risk.DEFAULT_POSITION_SIZE < 100, "Размер позиции должен быть от 0 до 100%"
    assert Risk.DEFAULT_STOP_LOSS > 0, "Стоп-лосс должен быть положительным"
    
    # Проверяем временные интервалы
    assert Timing.DEFAULT_UPDATE_INTERVAL > 0, "Интервал обновления должен быть положительным"
    assert Timing.API_TIMEOUT > 0, "Таймаут API должен быть положительным"


# Автоматическая валидация при импорте модуля
if __name__ != "__main__":
    validate_constants()