# Настройки будут созданы
#!/usr/bin/env python3
"""⚙️ Система конфигурации торговой системы"""

import os
import json
from typing import Dict, Any, Optional, List, Callable, Union
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from datetime import datetime
from enum import Enum

# Импортируем исключения
try:
    from ..core.exceptions import ConfigurationError, ValidationError
except ImportError:
    class ConfigurationError(Exception): pass
    class ValidationError(Exception): pass


# ================= БАЗОВЫЕ ENUMS =================

class Environment(Enum):
    """🌍 Среды выполнения"""
    DEVELOPMENT = "development"
    TESTING = "testing"
    PRODUCTION = "production"


class TradingProfile(Enum):
    """📊 Торговые профили"""
    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    AGGRESSIVE = "aggressive"


# ================= КОНФИГУРАЦИОННЫЕ ГРУППЫ =================

@dataclass
class APISettings:
    """🌐 Настройки API"""
    api_key: str = ""
    api_secret: str = ""
    base_url: str = "https://api.exmo.me/v1.1/"
    timeout_seconds: int = 30
    retry_attempts: int = 3
    retry_delay_seconds: float = 1.0
    rate_limit_per_minute: int = 600
    rate_limit_per_second: int = 10

    def __post_init__(self):
        # Загрузка из переменных окружения
        self.api_key = self.api_key or os.getenv('EXMO_API_KEY', '')
        self.api_secret = self.api_secret or os.getenv('EXMO_API_SECRET', '')

    def validate(self) -> None:
        """✅ Валидация API настроек"""
        if not self.api_key:
            raise ValidationError(
                "API key is required",
                field="api_key",
                value=self.api_key
            )
        if not self.api_secret:
            raise ValidationError(
                "API secret is required",
                field="api_secret",
                value="***hidden***"
            )
        if self.timeout_seconds <= 0:
            raise ValidationError(
                "Timeout must be positive",
                field="timeout_seconds",
                value=self.timeout_seconds
            )


@dataclass
class TradingSettings:
    """📈 Торговые настройки"""
    trading_pair: str = "DOGE_EUR"
    position_size_percent: Decimal = Decimal('6.0')
    min_profit_percent: Decimal = Decimal('2.0')
    max_loss_percent: Decimal = Decimal('15.0')
    stop_loss_percent: Decimal = Decimal('10.0')
    take_profit_percent: Decimal = Decimal('25.0')
    min_order_size_eur: Decimal = Decimal('5.0')
    max_orders_per_day: int = 50
    enable_buy_orders: bool = True
    enable_sell_orders: bool = True

    def __post_init__(self):
        # Преобразуем строки в Decimal
        if isinstance(self.position_size_percent, str):
            self.position_size_percent = Decimal(self.position_size_percent)
        if isinstance(self.min_profit_percent, str):
            self.min_profit_percent = Decimal(self.min_profit_percent)
        if isinstance(self.max_loss_percent, str):
            self.max_loss_percent = Decimal(self.max_loss_percent)
        if isinstance(self.stop_loss_percent, str):
            self.stop_loss_percent = Decimal(self.stop_loss_percent)
        if isinstance(self.take_profit_percent, str):
            self.take_profit_percent = Decimal(self.take_profit_percent)
        if isinstance(self.min_order_size_eur, str):
            self.min_order_size_eur = Decimal(self.min_order_size_eur)

    def validate(self) -> None:
        """✅ Валидация торговых настроек"""
        if self.position_size_percent <= 0 or self.position_size_percent > 100:
            raise ValidationError(
                "Position size must be between 0 and 100 percent",
                field="position_size_percent",
                value=self.position_size_percent
            )

        if self.min_order_size_eur <= 0:
            raise ValidationError(
                "Minimum order size must be positive",
                field="min_order_size_eur",
                value=self.min_order_size_eur
            )

        if self.max_orders_per_day <= 0:
            raise ValidationError(
                "Max orders per day must be positive",
                field="max_orders_per_day",
                value=self.max_orders_per_day
            )


@dataclass
class RiskSettings:
    """🛡️ Настройки управления рисками"""
    emergency_stop_percent: Decimal = Decimal('20.0')
    daily_loss_limit_percent: Decimal = Decimal('10.0')
    max_drawdown_percent: Decimal = Decimal('25.0')
    risk_per_trade_percent: Decimal = Decimal('2.0')
    max_open_positions: int = 3
    enable_emergency_stop: bool = True
    enable_daily_limits: bool = True
    enable_position_limits: bool = True
    correlation_threshold: Decimal = Decimal('0.7')

    def __post_init__(self):
        # Преобразование строк в Decimal
        for field_name, field_value in self.__dict__.items():
            if field_name.endswith('_percent') and isinstance(field_value, str):
                setattr(self, field_name, Decimal(field_value))

    def validate(self) -> None:
        """✅ Валидация настроек рисков"""
        if self.emergency_stop_percent <= 0:
            raise ValidationError(
                "Emergency stop percent must be positive",
                field="emergency_stop_percent",
                value=self.emergency_stop_percent
            )

        if self.max_open_positions <= 0:
            raise ValidationError(
                "Max open positions must be positive",
                field="max_open_positions",
                value=self.max_open_positions
            )


@dataclass
class DCASettings:
    """💰 Настройки DCA (Dollar Cost Averaging)"""
    enable_dca: bool = True
    purchase_size_percent: Decimal = Decimal('50.0')
    max_purchases: int = 5
    price_drop_threshold_percent: Decimal = Decimal('5.0')
    max_dca_per_day: int = 10
    dca_interval_minutes: int = 60
    enable_smart_dca: bool = True

    def __post_init__(self):
        # Преобразование строк в Decimal
        if isinstance(self.purchase_size_percent, str):
            self.purchase_size_percent = Decimal(self.purchase_size_percent)
        if isinstance(self.price_drop_threshold_percent, str):
            self.price_drop_threshold_percent = Decimal(self.price_drop_threshold_percent)

    def validate(self) -> None:
        """✅ Валидация настроек DCA"""
        if self.max_purchases <= 0:
            raise ValidationError(
                "Max DCA purchases must be positive",
                field="max_purchases",
                value=self.max_purchases
            )


@dataclass
class StrategySettings:
    """🎯 Настройки стратегий"""
    primary_strategy: str = "dca"
    secondary_strategies: List[str] = field(default_factory=lambda: ["pyramid", "emergency_exit"])
    strategy_weights: Dict[str, float] = field(default_factory=lambda: {
        "dca": 0.6,
        "pyramid": 0.3,
        "emergency_exit": 0.1
    })
    enable_strategy_switching: bool = True
    strategy_evaluation_interval_minutes: int = 30

    def validate(self) -> None:
        """✅ Валидация настроек стратегий"""
        if not self.primary_strategy:
            raise ValidationError("Primary strategy must be specified")

        # Проверяем что веса стратегий в сумме дают 1.0
        total_weight = sum(self.strategy_weights.values())
        if abs(total_weight - 1.0) > 0.01:
            raise ValidationError(
                f"Strategy weights must sum to 1.0, got {total_weight}",
                field="strategy_weights",
                value=self.strategy_weights
            )


@dataclass
class SystemSettings:
    """⚙️ Системные настройки"""
    log_level: str = "INFO"
    log_file: str = "logs/trading_bot.log"
    max_log_file_size_mb: int = 100
    backup_count: int = 5
    update_interval_seconds: int = 60
    cache_enabled: bool = True
    cache_ttl_seconds: int = 300
    metrics_enabled: bool = True
    health_check_interval_seconds: int = 300

    def validate(self) -> None:
        """✅ Валидация системных настроек"""
        valid_log_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if self.log_level not in valid_log_levels:
            raise ValidationError(
                f"Invalid log level: {self.log_level}",
                field="log_level",
                value=self.log_level
            )

        if self.update_interval_seconds <= 0:
            raise ValidationError(
                "Update interval must be positive",
                field="update_interval_seconds",
                value=self.update_interval_seconds
            )


# ================= ОСНОВНЫЕ НАСТРОЙКИ =================

@dataclass
class TradingSystemSettings:
    """🎛️ Основные настройки торговой системы"""
    profile: TradingProfile = TradingProfile.BALANCED
    environment: Environment = Environment.DEVELOPMENT
    test_mode: bool = True
    dry_run: bool = True

    # Группы настроек
    api: APISettings = field(default_factory=APISettings)
    trading: TradingSettings = field(default_factory=TradingSettings)
    risk: RiskSettings = field(default_factory=RiskSettings)
    dca: DCASettings = field(default_factory=DCASettings)
    strategy: StrategySettings = field(default_factory=StrategySettings)
    system: SystemSettings = field(default_factory=SystemSettings)

    # Кастомные настройки
    custom_settings: Dict[str, Any] = field(default_factory=dict)

    # Метаданные
    version: str = "4.1-refactored"
    created_at: datetime = field(default_factory=datetime.now)

    def apply_profile(self, profile: TradingProfile) -> None:
        """📊 Применение торгового профиля"""
        self.profile = profile

        if profile == TradingProfile.CONSERVATIVE:
            self.trading.position_size_percent = Decimal('4.0')
            self.trading.stop_loss_percent = Decimal('10.0')
            self.trading.take_profit_percent = Decimal('15.0')
            self.risk.risk_per_trade_percent = Decimal('1.0')
            self.dca.max_purchases = 3

        elif profile == TradingProfile.BALANCED:
            self.trading.position_size_percent = Decimal('6.0')
            self.trading.stop_loss_percent = Decimal('15.0')
            self.trading.take_profit_percent = Decimal('25.0')
            self.risk.risk_per_trade_percent = Decimal('2.0')
            self.dca.max_purchases = 5

        elif profile == TradingProfile.AGGRESSIVE:
            self.trading.position_size_percent = Decimal('10.0')
            self.trading.stop_loss_percent = Decimal('20.0')
            self.trading.take_profit_percent = Decimal('35.0')
            self.risk.risk_per_trade_percent = Decimal('3.0')
            self.dca.max_purchases = 7

    def validate(self) -> None:
        """✅ Валидация всех настроек"""
        try:
            self.api.validate()
        except ValidationError as e:
            raise ConfigurationError(f"API settings validation failed: {e}")

        try:
            self.trading.validate()
        except ValidationError as e:
            raise ConfigurationError(f"Trading settings validation failed: {e}")

        try:
            self.risk.validate()
        except ValidationError as e:
            raise ConfigurationError(f"Risk settings validation failed: {e}")

        try:
            self.dca.validate()
        except ValidationError as e:
            raise ConfigurationError(f"DCA settings validation failed: {e}")

        try:
            self.strategy.validate()
        except ValidationError as e:
            raise ConfigurationError(f"Strategy settings validation failed: {e}")

        try:
            self.system.validate()
        except ValidationError as e:
            raise ConfigurationError(f"System settings validation failed: {e}")

    def to_dict(self) -> Dict[str, Any]:
        """📤 Экспорт в словарь"""
        return {
            'profile': self.profile.value,
            'environment': self.environment.value,
            'test_mode': self.test_mode,
            'dry_run': self.dry_run,
            'api': {
                'base_url': self.api.base_url,
                'timeout_seconds': self.api.timeout_seconds,
                'retry_attempts': self.api.retry_attempts,
                'retry_delay_seconds': self.api.retry_delay_seconds,
                'rate_limit_per_minute': self.api.rate_limit_per_minute,
                'rate_limit_per_second': self.api.rate_limit_per_second
            },
            'trading': {
                'trading_pair': self.trading.trading_pair,
                'position_size_percent': str(self.trading.position_size_percent),
                'min_profit_percent': str(self.trading.min_profit_percent),
                'max_loss_percent': str(self.trading.max_loss_percent),
                'stop_loss_percent': str(self.trading.stop_loss_percent),
                'take_profit_percent': str(self.trading.take_profit_percent),
                'min_order_size_eur': str(self.trading.min_order_size_eur),
                'max_orders_per_day': self.trading.max_orders_per_day,
                'enable_buy_orders': self.trading.enable_buy_orders,
                'enable_sell_orders': self.trading.enable_sell_orders
            },
            'risk': {
                'emergency_stop_percent': str(self.risk.emergency_stop_percent),
                'daily_loss_limit_percent': str(self.risk.daily_loss_limit_percent),
                'max_drawdown_percent': str(self.risk.max_drawdown_percent),
                'risk_per_trade_percent': str(self.risk.risk_per_trade_percent),
                'max_open_positions': self.risk.max_open_positions,
                'enable_emergency_stop': self.risk.enable_emergency_stop,
                'enable_daily_limits': self.risk.enable_daily_limits,
                'enable_position_limits': self.risk.enable_position_limits
            },
            'dca': {
                'enable_dca': self.dca.enable_dca,
                'purchase_size_percent': str(self.dca.purchase_size_percent),
                'max_purchases': self.dca.max_purchases,
                'price_drop_threshold_percent': str(self.dca.price_drop_threshold_percent),
                'max_dca_per_day': self.dca.max_dca_per_day,
                'dca_interval_minutes': self.dca.dca_interval_minutes,
                'enable_smart_dca': self.dca.enable_smart_dca
            },
            'strategy': {
                'primary_strategy': self.strategy.primary_strategy,
                'secondary_strategies': self.strategy.secondary_strategies,
                'strategy_weights': self.strategy.strategy_weights,
                'enable_strategy_switching': self.strategy.enable_strategy_switching,
                'strategy_evaluation_interval_minutes': self.strategy.strategy_evaluation_interval_minutes
            },
            'system': {
                'log_level': self.system.log_level,
                'log_file': self.system.log_file,
                'max_log_file_size_mb': self.system.max_log_file_size_mb,
                'backup_count': self.system.backup_count,
                'update_interval_seconds': self.system.update_interval_seconds,
                'cache_enabled': self.system.cache_enabled,
                'cache_ttl_seconds': self.system.cache_ttl_seconds,
                'metrics_enabled': self.system.metrics_enabled,
                'health_check_interval_seconds': self.system.health_check_interval_seconds
            },
            'custom_settings': self.custom_settings,
            'version': self.version,
            'created_at': self.created_at.isoformat()
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TradingSystemSettings':
        """📥 Создание из словаря"""
        settings = cls()

        # Базовые поля
        if 'profile' in data:
            settings.profile = TradingProfile(data['profile'])
        if 'environment' in data:
            settings.environment = Environment(data['environment'])
        if 'test_mode' in data:
            settings.test_mode = data['test_mode']
        if 'dry_run' in data:
            settings.dry_run = data['dry_run']

        # Применяем данные к подструктурам
        if 'api' in data:
            api_data = data['api']
            for key, value in api_data.items():
                if hasattr(settings.api, key):
                    setattr(settings.api, key, value)

        if 'trading' in data:
            trading_data = data['trading']
            for key, value in trading_data.items():
                if hasattr(settings.trading, key):
                    if key.endswith('_percent') and isinstance(value, str):
                        setattr(settings.trading, key, Decimal(value))
                    else:
                        setattr(settings.trading, key, value)

        if 'risk' in data:
            risk_data = data['risk']
            for key, value in risk_data.items():
                if hasattr(settings.risk, key):
                    if key.endswith('_percent') and isinstance(value, str):
                        setattr(settings.risk, key, Decimal(value))
                    else:
                        setattr(settings.risk, key, value)

        if 'dca' in data:
            dca_data = data['dca']
            for key, value in dca_data.items():
                if hasattr(settings.dca, key):
                    if key.endswith('_percent') and isinstance(value, str):
                        setattr(settings.dca, key, Decimal(value))
                    else:
                        setattr(settings.dca, key, value)

        if 'strategy' in data:
            strategy_data = data['strategy']
            for key, value in strategy_data.items():
                if hasattr(settings.strategy, key):
                    setattr(settings.strategy, key, value)

        if 'system' in data:
            system_data = data['system']
            for key, value in system_data.items():
                if hasattr(settings.system, key):
                    setattr(settings.system, key, value)

        if 'custom_settings' in data:
            settings.custom_settings = data['custom_settings']

        return settings


# ================= ПРОВАЙДЕР КОНФИГУРАЦИИ =================

class ConfigProvider:
    """⚙️ Провайдер конфигурации"""

    def __init__(self, settings: Optional[TradingSystemSettings] = None):
        self._settings = settings or TradingSystemSettings()
        self._env_prefix = "TRADING_BOT_"
        self._config_file_path: Optional[Path] = None
        self._listeners: List[Callable[[TradingSystemSettings], None]] = []

    def load_from_env(self) -> 'ConfigProvider':
        """🌍 Загрузка из переменных окружения"""
        # API настройки
        if api_key := os.getenv(f"{self._env_prefix}API_KEY", os.getenv("EXMO_API_KEY")):
            self._settings.api.api_key = api_key

        if api_secret := os.getenv(f"{self._env_prefix}API_SECRET", os.getenv("EXMO_API_SECRET")):
            self._settings.api.api_secret = api_secret

        # Торговые настройки
        if trading_pair := os.getenv(f"{self._env_prefix}TRADING_PAIR"):
            self._settings.trading.trading_pair = trading_pair

        if profile := os.getenv(f"{self._env_prefix}PROFILE"):
            try:
                self._settings.profile = TradingProfile(profile.lower())
                self._settings.apply_profile(self._settings.profile)
            except ValueError:
                pass

        if environment := os.getenv(f"{self._env_prefix}ENVIRONMENT"):
            try:
                self._settings.environment = Environment(environment.lower())
            except ValueError:
                pass

        # Флаги
        if test_mode := os.getenv(f"{self._env_prefix}TEST_MODE"):
            self._settings.test_mode = test_mode.lower() in ('true', '1', 'yes')

        if dry_run := os.getenv(f"{self._env_prefix}DRY_RUN"):
            self._settings.dry_run = dry_run.lower() in ('true', '1', 'yes')

        return self

    def load_from_dotenv(self, env_file: str = ".env") -> 'ConfigProvider':
        """📄 Загрузка из .env файла"""
        env_path = Path(env_file)

        if not env_path.exists():
            return self  # Файл .env опциональный

        try:
            with open(env_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        if '=' in line:
                            key, value = line.split('=', 1)
                            os.environ[key.strip()] = value.strip()

            # После загрузки .env, применяем переменные окружения
            self.load_from_env()

        except Exception as e:
            raise ConfigurationError(f"Failed to load .env file: {e}")

        return self

    def load_from_file(self, config_path: str) -> 'ConfigProvider':
        """📁 Загрузка из файла"""
        config_file = Path(config_path)

        if not config_file.exists():
            raise ConfigurationError(f"Config file not found: {config_path}")

        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                if config_file.suffix.lower() == '.json':
                    config_data = json.load(f)
                else:
                    raise ConfigurationError(f"Unsupported config format: {config_file.suffix}")

            self._settings = TradingSystemSettings.from_dict(config_data)
            self._config_file_path = config_file

        except json.JSONDecodeError as e:
            raise ConfigurationError(f"Invalid JSON in config file: {e}")
        except Exception as e:
            raise ConfigurationError(f"Failed to load config: {e}")

        return self

    def save_to_file(self, config_path: Optional[str] = None) -> None:
        """💾 Сохранение в файл"""
        if config_path:
            file_path = Path(config_path)
        elif self._config_file_path:
            file_path = self._config_file_path
        else:
            file_path = Path("config.json")

        try:
            # Создаем директорию если не существует
            file_path.parent.mkdir(parents=True, exist_ok=True)

            config_data = self._settings.to_dict()

            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=2, ensure_ascii=False)

        except Exception as e:
            raise ConfigurationError(f"Failed to save config: {e}")

    def validate(self) -> 'ConfigProvider':
        """✅ Валидация конфигурации"""
        self._settings.validate()
        return self

    def get_settings(self) -> TradingSystemSettings:
        """📋 Получение настроек"""
        return self._settings

    def add_listener(self, listener: Callable[[TradingSystemSettings], None]) -> None:
        """👂 Добавление слушателя изменений"""
        self._listeners.append(listener)

    def _notify_listeners(self) -> None:
        """📢 Уведомление слушателей"""
        for listener in self._listeners:
            try:
                listener(self._settings)
            except Exception as e:
                import logging
                logging.warning(f"Config listener error: {e}")


# ================= ФАБРИКА КОНФИГУРАЦИЙ =================

class ConfigFactory:
    """🏭 Фабрика конфигураций"""

    @staticmethod
    def create_development_config() -> TradingSystemSettings:
        """💻 Создание конфигурации для разработки"""
        settings = TradingSystemSettings()
        settings.environment = Environment.DEVELOPMENT
        settings.test_mode = True
        settings.dry_run = True
        settings.system.log_level = "DEBUG"
        settings.apply_profile(TradingProfile.CONSERVATIVE)
        return settings

    @staticmethod
    def create_testing_config() -> TradingSystemSettings:
        """🧪 Создание конфигурации для тестирования"""
        settings = TradingSystemSettings()
        settings.environment = Environment.TESTING
        settings.test_mode = True
        settings.dry_run = True
        settings.system.log_level = "DEBUG"
        settings.apply_profile(TradingProfile.BALANCED)
        return settings

    @staticmethod
    def create_production_config() -> TradingSystemSettings:
        """🚀 Создание продакшн конфигурации"""
        settings = TradingSystemSettings()
        settings.environment = Environment.PRODUCTION
        settings.test_mode = False
        settings.dry_run = False
        settings.system.log_level = "INFO"
        settings.apply_profile(TradingProfile.BALANCED)
        return settings


# ================= ГЛОБАЛЬНЫЕ УТИЛИТЫ =================

_global_config_provider: Optional[ConfigProvider] = None


def get_global_config() -> TradingSystemSettings:
    """🌍 Получение глобальной конфигурации"""
    global _global_config_provider

    if _global_config_provider is None:
        _global_config_provider = ConfigProvider()
        _global_config_provider.load_from_dotenv().load_from_env()

        try:
            _global_config_provider.validate()
        except (ConfigurationError, ValidationError):
            # Если валидация не прошла, используем настройки разработки
            _global_config_provider = ConfigProvider(ConfigFactory.create_development_config())

    return _global_config_provider.get_settings()


def set_global_config(settings: TradingSystemSettings) -> None:
    """🌍 Установка глобальной конфигурации"""
    global _global_config_provider
    _global_config_provider = ConfigProvider(settings)


def load_config(
    config_file: Optional[str] = None,
    profile: Optional[TradingProfile] = None,
    environment: Optional[Environment] = None
) -> TradingSystemSettings:
    """📋 Загрузка конфигурации"""
    provider = ConfigProvider()

    # 1. Загрузка из .env файла
    provider.load_from_dotenv()

    # 2. Загрузка из переменных окружения
    provider.load_from_env()

    # 3. Загрузка из файла если указан
    if config_file and Path(config_file).exists():
        provider.load_from_file(config_file)

    # 4. Применение профиля
    if profile:
        provider.get_settings().apply_profile(profile)

    # 5. Установка окружения
    if environment:
        provider.get_settings().environment = environment

    # 6. Валидация
    provider.validate()

    return provider.get_settings()


# ================= КОНСТАНТЫ =================

class ConfigConstants:
    """📋 Конфигурационные константы"""

    # Файлы конфигурации
    DEFAULT_CONFIG_FILE = "config.json"
    DEFAULT_ENV_FILE = ".env"

    # Префиксы переменных окружения
    ENV_PREFIX = "TRADING_BOT_"

    # Допустимые торговые пары
    SUPPORTED_TRADING_PAIRS = [
        "DOGE_EUR", "DOGE_USD", "BTC_EUR", "BTC_USD",
        "ETH_EUR", "ETH_USD", "LTC_EUR", "XRP_EUR"
    ]

    # Лимиты валидации
    MIN_POSITION_SIZE_PERCENT = 0.1
    MAX_POSITION_SIZE_PERCENT = 50.0
    MIN_ORDER_SIZE_EUR = 1.0
    MAX_ORDER_SIZE_EUR = 100000.0

    # Временные интервалы (секунды)
    MIN_UPDATE_INTERVAL = 10
    MAX_UPDATE_INTERVAL = 3600

    # Профили по умолчанию
    DEFAULT_PROFILES = {
        TradingProfile.CONSERVATIVE: {
            "position_size_percent": Decimal("4.0"),
            "stop_loss_percent": Decimal("10.0"),
            "take_profit_percent": Decimal("15.0"),
            "risk_per_trade_percent": Decimal("1.0"),
            "max_dca_purchases": 3,
            "description": "Консервативная торговля с низким риском"
        },
        TradingProfile.BALANCED: {
            "position_size_percent": Decimal("6.0"),
            "stop_loss_percent": Decimal("15.0"),
            "take_profit_percent": Decimal("25.0"),
            "risk_per_trade_percent": Decimal("2.0"),
            "max_dca_purchases": 5,
            "description": "Сбалансированная торговля со средним риском"
        },
        TradingProfile.AGGRESSIVE: {
            "position_size_percent": Decimal("10.0"),
            "stop_loss_percent": Decimal("20.0"),
            "take_profit_percent": Decimal("35.0"),
            "risk_per_trade_percent": Decimal("3.0"),
            "max_dca_purchases": 7,
            "description": "Агрессивная торговля с высоким риском"
        }
    }


# ================= РАСШИРЕННЫЕ УТИЛИТЫ =================

class ConfigValidator:
    """✅ Валидатор конфигурации"""

    @staticmethod
    def validate_trading_pair(pair: str) -> bool:
        """Валидация торговой пары"""
        return pair in ConfigConstants.SUPPORTED_TRADING_PAIRS

    @staticmethod
    def validate_position_size(size_percent: Decimal) -> bool:
        """Валидация размера позиции"""
        return (ConfigConstants.MIN_POSITION_SIZE_PERCENT <=
                float(size_percent) <=
                ConfigConstants.MAX_POSITION_SIZE_PERCENT)

    @staticmethod
    def validate_order_size(size_eur: Decimal) -> bool:
        """Валидация размера ордера"""
        return (ConfigConstants.MIN_ORDER_SIZE_EUR <=
                float(size_eur) <=
                ConfigConstants.MAX_ORDER_SIZE_EUR)

    @staticmethod
    def validate_update_interval(interval_seconds: int) -> bool:
        """Валидация интервала обновления"""
        return (ConfigConstants.MIN_UPDATE_INTERVAL <=
                interval_seconds <=
                ConfigConstants.MAX_UPDATE_INTERVAL)

    @staticmethod
    def validate_full_config(settings: TradingSystemSettings) -> List[str]:
        """Полная валидация конфигурации"""
        errors = []

        try:
            settings.validate()
        except ConfigurationError as e:
            errors.append(str(e))

        # Дополнительные проверки
        if not ConfigValidator.validate_trading_pair(settings.trading.trading_pair):
            errors.append(f"Unsupported trading pair: {settings.trading.trading_pair}")

        if not ConfigValidator.validate_position_size(settings.trading.position_size_percent):
            errors.append(f"Invalid position size: {settings.trading.position_size_percent}%")

        if not ConfigValidator.validate_order_size(settings.trading.min_order_size_eur):
            errors.append(f"Invalid min order size: {settings.trading.min_order_size_eur} EUR")

        if not ConfigValidator.validate_update_interval(settings.system.update_interval_seconds):
            errors.append(f"Invalid update interval: {settings.system.update_interval_seconds} seconds")

        return errors


class ConfigManager:
    """🎛️ Менеджер конфигурации"""

    def __init__(self):
        self._current_config: Optional[TradingSystemSettings] = None
        self._config_history: List[TradingSystemSettings] = []
        self._listeners: List[Callable[[TradingSystemSettings], None]] = []
        self._auto_save_enabled = False
        self._config_file_path: Optional[Path] = None

    def load_default(self) -> TradingSystemSettings:
        """📋 Загрузка конфигурации по умолчанию"""
        self._current_config = load_config()
        self._add_to_history(self._current_config)
        self._notify_listeners()
        return self._current_config

    def load_from_profile(self, profile: TradingProfile) -> TradingSystemSettings:
        """📊 Загрузка из профиля"""
        if profile == TradingProfile.CONSERVATIVE:
            self._current_config = ConfigFactory.create_development_config()
        elif profile == TradingProfile.BALANCED:
            self._current_config = ConfigFactory.create_testing_config()
        else:  # AGGRESSIVE
            self._current_config = ConfigFactory.create_production_config()

        self._current_config.apply_profile(profile)
        self._add_to_history(self._current_config)
        self._notify_listeners()
        return self._current_config

    def load_from_file(self, file_path: str) -> TradingSystemSettings:
        """📁 Загрузка из файла"""
        provider = ConfigProvider()
        provider.load_from_file(file_path)
        self._current_config = provider.get_settings()
        self._config_file_path = Path(file_path)
        self._add_to_history(self._current_config)
        self._notify_listeners()
        return self._current_config

    def save_to_file(self, file_path: Optional[str] = None) -> None:
        """💾 Сохранение в файл"""
        if not self._current_config:
            raise ConfigurationError("No configuration loaded")

        target_path = file_path or self._config_file_path or "config.json"
        provider = ConfigProvider(self._current_config)
        provider.save_to_file(str(target_path))

        if file_path:
            self._config_file_path = Path(file_path)

    def update_setting(self, path: str, value: Any) -> None:
        """🔧 Обновление отдельной настройки"""
        if not self._current_config:
            self.load_default()

        # Разбираем путь типа 'trading.position_size_percent'
        parts = path.split('.')
        obj = self._current_config

        for part in parts[:-1]:
            obj = getattr(obj, part)

        setattr(obj, parts[-1], value)

        # Валидируем после изменения
        self._current_config.validate()

        # Добавляем в историю и уведомляем
        self._add_to_history(self._current_config)
        self._notify_listeners()

        # Автосохранение
        if self._auto_save_enabled and self._config_file_path:
            self.save_to_file()

    def get_setting(self, path: str) -> Any:
        """📖 Получение отдельной настройки"""
        if not self._current_config:
            self.load_default()

        parts = path.split('.')
        obj = self._current_config

        for part in parts:
            obj = getattr(obj, part)

        return obj

    def enable_auto_save(self, file_path: Optional[str] = None) -> None:
        """💾 Включение автосохранения"""
        self._auto_save_enabled = True
        if file_path:
            self._config_file_path = Path(file_path)

    def disable_auto_save(self) -> None:
        """🚫 Отключение автосохранения"""
        self._auto_save_enabled = False

    def add_listener(self, listener: Callable[[TradingSystemSettings], None]) -> None:
        """👂 Добавление слушателя изменений"""
        self._listeners.append(listener)

    def remove_listener(self, listener: Callable[[TradingSystemSettings], None]) -> None:
        """🗑️ Удаление слушателя"""
        if listener in self._listeners:
            self._listeners.remove(listener)

    def get_history(self) -> List[TradingSystemSettings]:
        """📜 Получение истории конфигураций"""
        return self._config_history.copy()

    def rollback(self, steps: int = 1) -> TradingSystemSettings:
        """⏪ Откат к предыдущей конфигурации"""
        if len(self._config_history) <= steps:
            raise ConfigurationError("Not enough history for rollback")

        # Берем конфигурацию на N шагов назад
        target_config = self._config_history[-(steps + 1)]
        self._current_config = target_config
        self._notify_listeners()

        return self._current_config

    def reset_to_defaults(self) -> TradingSystemSettings:
        """🔄 Сброс к настройкам по умолчанию"""
        return self.load_default()

    def validate_current(self) -> List[str]:
        """✅ Валидация текущих настроек"""
        if not self._current_config:
            return ["No configuration loaded"]

        return ConfigValidator.validate_full_config(self._current_config)

    def export_config(self, format_type: str = "json") -> str:
        """📤 Экспорт конфигурации"""
        if not self._current_config:
            raise ConfigurationError("No configuration loaded")

        if format_type.lower() == "json":
            return json.dumps(self._current_config.to_dict(), indent=2, ensure_ascii=False)
        else:
            raise ConfigurationError(f"Unsupported export format: {format_type}")

    def import_config(self, config_data: str, format_type: str = "json") -> TradingSystemSettings:
        """📥 Импорт конфигурации"""
        if format_type.lower() == "json":
            data = json.loads(config_data)
            self._current_config = TradingSystemSettings.from_dict(data)
            self._add_to_history(self._current_config)
            self._notify_listeners()
            return self._current_config
        else:
            raise ConfigurationError(f"Unsupported import format: {format_type}")

    @property
    def current_config(self) -> Optional[TradingSystemSettings]:
        """📋 Текущая конфигурация"""
        return self._current_config

    def _add_to_history(self, config: TradingSystemSettings) -> None:
        """📜 Добавление в историю"""
        # Ограничиваем размер истории
        max_history = 50
        self._config_history.append(config)
        if len(self._config_history) > max_history:
            self._config_history = self._config_history[-max_history:]

    def _notify_listeners(self) -> None:
        """📢 Уведомление слушателей"""
        if self._current_config:
            for listener in self._listeners:
                try:
                    listener(self._current_config)
                except Exception as e:
                    import logging
                    logging.warning(f"Config listener error: {e}")


# ================= ГЛОБАЛЬНЫЙ ЭКЗЕМПЛЯР =================

# Создаем глобальный менеджер конфигурации
_global_config_manager = ConfigManager()


def get_config_manager() -> ConfigManager:
    """🎛️ Получение глобального менеджера конфигурации"""
    return _global_config_manager


def get_current_config() -> TradingSystemSettings:
    """📋 Получение текущей конфигурации"""
    config = _global_config_manager.current_config
    if config is None:
        config = _global_config_manager.load_default()
    return config


def update_config_setting(path: str, value: Any) -> None:
    """🔧 Обновление настройки через глобальный менеджер"""
    _global_config_manager.update_setting(path, value)


def validate_current_config() -> List[str]:
    """✅ Валидация текущей конфигурации"""
    return _global_config_manager.validate_current()


# ================= КОНТЕКСТНЫЙ МЕНЕДЖЕР =================

class ConfigContext:
    """🎯 Контекстный менеджер для временной конфигурации"""

    def __init__(self, temp_config: TradingSystemSettings):
        self.temp_config = temp_config
        self.original_config: Optional[TradingSystemSettings] = None

    def __enter__(self) -> TradingSystemSettings:
        # Сохраняем текущую конфигурацию
        self.original_config = _global_config_manager.current_config

        # Устанавливаем временную
        _global_config_manager._current_config = self.temp_config
        _global_config_manager._notify_listeners()

        return self.temp_config

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Восстанавливаем оригинальную конфигурацию
        if self.original_config:
            _global_config_manager._current_config = self.original_config
            _global_config_manager._notify_listeners()


# ================= ДЕКОРАТОРЫ =================

def with_config(config: TradingSystemSettings):
    """🎯 Декоратор для выполнения функции с определенной конфигурацией"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            with ConfigContext(config):
                return func(*args, **kwargs)
        return wrapper
    return decorator


def require_config_validation(func):
    """✅ Декоратор для обязательной валидации конфигурации"""
    def wrapper(*args, **kwargs):
        errors = validate_current_config()
        if errors:
            raise ConfigurationError(f"Configuration validation failed: {'; '.join(errors)}")
        return func(*args, **kwargs)
    return wrapper
