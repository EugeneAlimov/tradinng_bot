#!/usr/bin/env python3
"""⚙️ Система конфигурации торговой системы - Config слой"""

import os
from typing import Dict, Any, Optional, List, Type, get_type_hints
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from enum import Enum
import json

from ..core.exceptions import ConfigurationError, ValidationError


# ================= PROFILE ENUMS =================

class TradingProfile(Enum):
    """📊 Профили торговли"""
    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    AGGRESSIVE = "aggressive"
    CUSTOM = "custom"


class Environment(Enum):
    """🌍 Окружения"""
    DEVELOPMENT = "development"
    TESTING = "testing"
    PRODUCTION = "production"


# ================= БАЗОВЫЕ НАСТРОЙКИ =================

@dataclass
class APISettings:
    """🌐 Настройки API"""
    base_url: str = "https://api.exmo.com/v1.1/"
    timeout_seconds: int = 10
    max_retries: int = 3
    calls_per_minute: int = 30
    calls_per_hour: int = 300
    
    # Credentials
    api_key: str = ""
    api_secret: str = ""
    
    # Rate limiting
    adaptive_delays: bool = True
    min_delay_seconds: float = 1.0
    max_delay_seconds: float = 30.0
    
    def validate(self) -> None:
        """✅ Валидация настроек API"""
        if not self.api_key:
            raise ConfigurationError("API key is required", config_key="api_key")
        
        if not self.api_secret:
            raise ConfigurationError("API secret is required", config_key="api_secret")
        
        if not self.base_url:
            raise ConfigurationError("Base URL is required", config_key="base_url")
        
        if self.timeout_seconds <= 0:
            raise ValidationError("Timeout must be positive", field="timeout_seconds", value=self.timeout_seconds)
        
        if self.calls_per_minute <= 0 or self.calls_per_hour <= 0:
            raise ValidationError("Rate limits must be positive")


@dataclass
class TradingSettings:
    """📈 Торговые настройки"""
    # Основные параметры
    trading_pair: str = "DOGE_EUR"
    max_position_size_percent: Decimal = Decimal("8")
    min_profit_percent: Decimal = Decimal("1.2")
    stop_loss_percent: Decimal = Decimal("15")
    
    # DCA настройки
    dca_enabled: bool = True
    dca_max_purchases: int = 7
    dca_purchase_size_percent: Decimal = Decimal("8")
    dca_trigger_drop_percent: Decimal = Decimal("1.5")
    dca_cooldown_minutes: int = 3
    dca_max_position_percent: Decimal = Decimal("56")
    
    # Пирамидальная продажа
    pyramid_enabled: bool = True
    pyramid_levels: List[Dict[str, float]] = field(default_factory=lambda: [
        {"profit_percent": 0.8, "sell_percent": 25.0, "min_eur": 0.10},
        {"profit_percent": 2.0, "sell_percent": 35.0, "min_eur": 0.20},
        {"profit_percent": 4.0, "sell_percent": 25.0, "min_eur": 0.30},
        {"profit_percent": 7.0, "sell_percent": 15.0, "min_eur": 0.50},
    ])
    
    # Trailing Stop
    trailing_stop_enabled: bool = True
    trailing_activation_profit_percent: Decimal = Decimal("1.2")
    trailing_distance_percent: Decimal = Decimal("0.5")
    trailing_partial_sell_percent: Decimal = Decimal("70")
    
    # Лимиты
    max_daily_loss_percent: Decimal = Decimal("2")
    max_trades_per_hour: int = 6
    min_order_size_eur: Decimal = Decimal("5")
    
    def validate(self) -> None:
        """✅ Валидация торговых настроек"""
        if not self.trading_pair:
            raise ConfigurationError("Trading pair is required", config_key="trading_pair")
        
        if self.max_position_size_percent <= 0 or self.max_position_size_percent > 100:
            raise ValidationError(
                "Max position size must be between 0 and 100 percent",
                field="max_position_size_percent",
                value=self.max_position_size_percent
            )
        
        if self.dca_max_purchases <= 0:
            raise ValidationError("DCA max purchases must be positive", 
                                field="dca_max_purchases", value=self.dca_max_purchases)
        
        # Валидация пирамидальных уровней
        if self.pyramid_enabled:
            for i, level in enumerate(self.pyramid_levels):
                required_keys = ["profit_percent", "sell_percent", "min_eur"]
                if not all(key in level for key in required_keys):
                    raise ValidationError(f"Pyramid level {i} missing required keys")
        
        # Проверка что сумма DCA не превышает разумные пределы
        total_dca_percent = self.dca_purchase_size_percent * self.dca_max_purchases
        if total_dca_percent > 80:
            raise ValidationError(
                f"Total DCA exposure ({total_dca_percent}%) too high",
                field="dca_total_exposure"
            )


@dataclass
class RiskSettings:
    """🛡️ Настройки риск-менеджмента"""
    # Основные лимиты
    max_drawdown_percent: Decimal = Decimal("8")
    max_daily_loss_eur: Decimal = Decimal("50")
    max_position_value_eur: Decimal = Decimal("500")
    
    # Аварийные настройки
    emergency_exit_enabled: bool = True
    emergency_loss_percent: Decimal = Decimal("10")
    emergency_btc_drop_percent: Decimal = Decimal("5")
    
    # Корреляционный анализ
    btc_correlation_enabled: bool = True
    btc_volatility_threshold_percent: Decimal = Decimal("3")
    correlation_block_minutes: int = 30
    
    # Лимиты времени
    max_position_hold_hours: int = 24
    trading_hours_start: int = 0  # 0-23
    trading_hours_end: int = 23   # 0-23
    trading_enabled_weekends: bool = True
    
    def validate(self) -> None:
        """✅ Валидация настроек риска"""
        if self.max_drawdown_percent <= 0 or self.max_drawdown_percent > 50:
            raise ValidationError("Max drawdown must be between 0 and 50 percent")
        
        if self.max_daily_loss_eur <= 0:
            raise ValidationError("Max daily loss must be positive")
        
        if self.trading_hours_start < 0 or self.trading_hours_start > 23:
            raise ValidationError("Trading hours start must be between 0 and 23")
        
        if self.trading_hours_end < 0 or self.trading_hours_end > 23:
            raise ValidationError("Trading hours end must be between 0 and 23")


@dataclass
class SystemSettings:
    """🖥️ Системные настройки"""
    # Логирование
    log_level: str = "INFO"
    log_file: str = "logs/trading_bot.log"
    log_max_size_mb: int = 100
    log_backup_count: int = 5
    
    # Интервалы обновления
    update_interval_seconds: int = 5
    price_update_interval_seconds: int = 3
    position_check_interval_seconds: int = 10
    
    # Файловая система
    data_directory: str = "data"
    backup_directory: str = "backup"
    reports_directory: str = "reports"
    
    # Кэширование
    cache_enabled: bool = True
    cache_ttl_seconds: int = 30
    cache_max_size: int = 1000
    
    # Мониторинг
    metrics_enabled: bool = True
    health_check_interval_seconds: int = 60
    
    # Производительность
    max_concurrent_api_calls: int = 5
    enable_async_processing: bool = True
    
    def validate(self) -> None:
        """✅ Валидация системных настроек"""
        if self.log_level not in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            raise ValidationError("Invalid log level", field="log_level", value=self.log_level)
        
        if self.update_interval_seconds <= 0:
            raise ValidationError("Update interval must be positive")
        
        # Создание директорий если нужно
        for directory in [self.data_directory, self.backup_directory, self.reports_directory]:
            Path(directory).mkdir(parents=True, exist_ok=True)


# ================= ГЛАВНЫЙ КЛАСС НАСТРОЕК =================

@dataclass
class TradingSystemSettings:
    """⚙️ Основные настройки торговой системы"""
    # Профиль и окружение
    profile: TradingProfile = TradingProfile.BALANCED
    environment: Environment = Environment.DEVELOPMENT
    
    # Компоненты настроек
    api: APISettings = field(default_factory=APISettings)
    trading: TradingSettings = field(default_factory=TradingSettings)
    risk: RiskSettings = field(default_factory=RiskSettings)
    system: SystemSettings = field(default_factory=SystemSettings)
    
    # Тестовый режим
    test_mode: bool = False
    dry_run: bool = False
    
    # Дополнительные настройки
    custom_settings: Dict[str, Any] = field(default_factory=dict)
    
    def validate(self) -> None:
        """✅ Валидация всех настроек"""
        try:
            self.api.validate()
            self.trading.validate()
            self.risk.validate()
            self.system.validate()
            
            # Кросс-валидация
            self._cross_validate()
            
        except (ConfigurationError, ValidationError):
            raise
        except Exception as e:
            raise ConfigurationError(f"Validation failed: {str(e)}")
    
    def _cross_validate(self) -> None:
        """🔄 Кросс-валидация между настройками"""
        # Проверяем соответствие DCA и риск-лимитов
        max_dca_value = (self.trading.dca_purchase_size_percent * 
                        self.trading.dca_max_purchases)
        
        if max_dca_value > self.trading.max_position_size_percent * 2:
            raise ValidationError(
                f"DCA max exposure ({max_dca_value}%) conflicts with position limits"
            )
        
        # Проверяем соответствие API лимитов и торговых интервалов
        trades_per_hour = 3600 / max(self.system.update_interval_seconds, 1)
        if trades_per_hour > self.api.calls_per_hour:
            raise ValidationError(
                "Update interval too fast for API rate limits"
            )
    
    def apply_profile(self, profile: TradingProfile) -> None:
        """📊 Применение торгового профиля"""
        self.profile = profile
        
        if profile == TradingProfile.CONSERVATIVE:
            self.trading.max_position_size_percent = Decimal("4")
            self.trading.min_profit_percent = Decimal("1.5")
            self.trading.dca_purchase_size_percent = Decimal("3")
            self.trading.dca_max_purchases = 5
            self.risk.max_drawdown_percent = Decimal("5")
            
        elif profile == TradingProfile.BALANCED:
            self.trading.max_position_size_percent = Decimal("6")
            self.trading.min_profit_percent = Decimal("1.2")
            self.trading.dca_purchase_size_percent = Decimal("6")
            self.trading.dca_max_purchases = 6
            self.risk.max_drawdown_percent = Decimal("8")
            
        elif profile == TradingProfile.AGGRESSIVE:
            self.trading.max_position_size_percent = Decimal("10")
            self.trading.min_profit_percent = Decimal("1.0")
            self.trading.dca_purchase_size_percent = Decimal("10")
            self.trading.dca_max_purchases = 8
            self.risk.max_drawdown_percent = Decimal("12")
    
    def to_dict(self) -> Dict[str, Any]:
        """📄 Преобразование в словарь"""
        return {
            'profile': self.profile.value,
            'environment': self.environment.value,
            'test_mode': self.test_mode,
            'dry_run': self.dry_run,
            'api': {
                'base_url': self.api.base_url,
                'timeout_seconds': self.api.timeout_seconds,
                'max_retries': self.api.max_retries,
                'calls_per_minute': self.api.calls_per_minute,
                'calls_per_hour': self.api.calls_per_hour,
                'adaptive_delays': self.api.adaptive_delays
            },
            'trading': {
                'trading_pair': self.trading.trading_pair,
                'max_position_size_percent': str(self.trading.max_position_size_percent),
                'min_profit_percent': str(self.trading.min_profit_percent),
                'dca_enabled': self.trading.dca_enabled,
                'dca_max_purchases': self.trading.dca_max_purchases,
                'pyramid_enabled': self.trading.pyramid_enabled,
                'trailing_stop_enabled': self.trading.trailing_stop_enabled
            },
            'risk': {
                'max_drawdown_percent': str(self.risk.max_drawdown_percent),
                'emergency_exit_enabled': self.risk.emergency_exit_enabled,
                'btc_correlation_enabled': self.risk.btc_correlation_enabled
            },
            'system': {
                'log_level': self.system.log_level,
                'update_interval_seconds': self.system.update_interval_seconds,
                'cache_enabled': self.system.cache_enabled,
                'metrics_enabled': self.system.metrics_enabled
            },
            'custom_settings': self.custom_settings
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
        
        # API настройки
        if 'api' in data:
            api_data = data['api']
            for key, value in api_data.items():
                if hasattr(settings.api, key):
                    setattr(settings.api, key, value)
        
        # Торговые настройки
        if 'trading' in data:
            trading_data = data['trading']
            for key, value in trading_data.items():
                if hasattr(settings.trading, key):
                    # Конвертируем Decimal поля
                    if key.endswith('_percent') and isinstance(value, str):
                        setattr(settings.trading, key, Decimal(value))
                    else:
                        setattr(settings.trading, key, value)
        
        # Риск настройки
        if 'risk' in data:
            risk_data = data['risk']
            for key, value in risk_data.items():
                if hasattr(settings.risk, key):
                    if key.endswith('_percent') and isinstance(value, str):
                        setattr(settings.risk, key, Decimal(value))
                    else:
                        setattr(settings.risk, key, value)
        
        # Системные настройки
        if 'system' in data:
            system_data = data['system']
            for key, value in system_data.items():
                if hasattr(settings.system, key):
                    setattr(settings.system, key, value)
        
        # Кастомные настройки
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
    
    def apply_profile(self, profile: TradingProfile) -> 'ConfigProvider':
        """📊 Применение профиля"""
        self._settings.apply_profile(profile)
        self._notify_listeners()
        return self
    
    def set_environment(self, environment: Environment) -> 'ConfigProvider':
        """🌍 Установка окружения"""
        self._settings.environment = environment
        
        # Применяем настройки окружения
        if environment == Environment.DEVELOPMENT:
            self._settings.system.log_level = "DEBUG"
            self._settings.test_mode = True
        elif environment == Environment.TESTING:
            self._settings.test_mode = True
            self._settings.dry_run = True
        elif environment == Environment.PRODUCTION:
            self._settings.system.log_level = "INFO"
            self._settings.test_mode = False
            self._settings.dry_run = False
        
        self._notify_listeners()
        return self
    
    def validate(self) -> 'ConfigProvider':
        """✅ Валидация конфигурации"""
        self._settings.validate()
        return self
    
    def get_settings(self) -> TradingSystemSettings:
        """📋 Получение настроек"""
        return self._settings
    
    def get(self, key: str, default: Any = None) -> Any:
        """🔧 Получение значения по ключу"""
        try:
            # Поддержка вложенных ключей типа 'api.timeout_seconds'
            keys = key.split('.')
            value = self._settings
            
            for k in keys:
                if hasattr(value, k):
                    value = getattr(value, k)
                elif isinstance(value, dict) and k in value:
                    value = value[k]
                else:
                    return default
            
            return value
            
        except Exception:
            return default
    
    def set(self, key: str, value: Any) -> None:
        """🔧 Установка значения"""
        keys = key.split('.')
        
        if len(keys) == 1:
            # Простой ключ
            if hasattr(self._settings, key):
                setattr(self._settings, key, value)
            else:
                self._settings.custom_settings[key] = value
        else:
            # Вложенный ключ
            obj = self._settings
            for k in keys[:-1]:
                if hasattr(obj, k):
                    obj = getattr(obj, k)
                else:
                    raise ConfigurationError(f"Invalid config path: {key}")
            
            if hasattr(obj, keys[-1]):
                setattr(obj, keys[-1], value)
            else:
                raise ConfigurationError(f"Invalid config key: {keys[-1]}")
        
        self._notify_listeners()
    
    def save_to_file(self, file_path: str) -> None:
        """💾 Сохранение в файл"""
        config_file = Path(file_path)
        config_file.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            config_data = self._settings.to_dict()
            
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=2, ensure_ascii=False)
            
        except Exception as e:
            raise ConfigurationError(f"Failed to save config: {e}")
    
    def add_change_listener(self, listener: Callable[[TradingSystemSettings], None]) -> None:
        """👂 Добавление слушателя изменений"""
        self._listeners.append(listener)
    
    def _notify_listeners(self) -> None:
        """📢 Уведомление слушателей об изменениях"""
        for listener in self._listeners:
            try:
                listener(self._settings)
            except Exception as e:
                # Логируем ошибки слушателей, но не прерываем выполнение
                import logging
                logging.error(f"Config listener error: {e}")


# ================= ФАБРИКИ И УТИЛИТЫ =================

class ConfigFactory:
    """🏭 Фабрика конфигураций"""
    
    @staticmethod
    def create_development_config() -> TradingSystemSettings:
        """🛠️ Создание конфигурации для разработки"""
        settings = TradingSystemSettings()
        settings.environment = Environment.DEVELOPMENT
        settings.test_mode = True
        settings.dry_run = True
        settings.system.log_level = "DEBUG"
        settings.system.update_interval_seconds = 10  # Медленнее для отладки
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
    
    @staticmethod
    def create_conservative_config() -> TradingSystemSettings:
        """🛡️ Создание консервативной конфигурации"""
        settings = TradingSystemSettings()
        settings.apply_profile(TradingProfile.CONSERVATIVE)
        return settings
    
    @staticmethod
    def create_aggressive_config() -> TradingSystemSettings:
        """⚡ Создание агрессивной конфигурации"""
        settings = TradingSystemSettings()
        settings.apply_profile(TradingProfile.AGGRESSIVE)
        return settings


def load_config(config_file: Optional[str] = None, 
                profile: Optional[TradingProfile] = None,
                environment: Optional[Environment] = None) -> TradingSystemSettings:
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
        provider.apply_profile(profile)
    
    # 5. Установка окружения
    if environment:
        provider.set_environment(environment)
    
    # 6. Валидация
    provider.validate()
    
    return provider.get_settings()


def create_default_config() -> TradingSystemSettings:
    """🏭 Создание конфигурации по умолчанию"""
    return load_config()


# ================= ГЛОБАЛЬНЫЙ ПРОВАЙДЕР =================

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


# ================= КОНФИГУРАЦИОННЫЕ КОНСТАНТЫ =================

class ConfigConstants:
    """📋 Конфигурационные константы"""
    
    # Файлы конфигурации
    DEFAULT_CONFIG_FILE = "config.json"
    ENV_FILE = ".env"
    
    # Директории
    DEFAULT_DATA_DIR = "data"
    DEFAULT_LOG_DIR = "logs"
    DEFAULT_BACKUP_DIR = "backup"
    DEFAULT_REPORTS_DIR = "reports"
    
    # Торговые пары
    SUPPORTED_PAIRS = [
        "DOGE_EUR", "DOGE_USD", "DOGE_BTC",
        "BTC_EUR", "BTC_USD", "ETH_EUR", "ETH_USD"
    ]
    
    # Лимиты по умолчанию
    DEFAULT_MIN_ORDER_EUR = Decimal("5.0")
    DEFAULT_MAX_POSITION_PERCENT = Decimal("10.0")
    DEFAULT_STOP_LOSS_PERCENT = Decimal("15.0")
    
    # API лимиты (EXMO)
    EXMO_RATE_LIMIT_PER_MINUTE = 30
    EXMO_RATE_LIMIT_PER_HOUR = 300
    EXMO_BASE_URL = "https://api.exmo.com/v1.1/"
    
    # Временные константы
    DEFAULT_UPDATE_INTERVAL = 5  # секунд
    DEFAULT_CACHE_TTL = 30       # секунд
    DEFAULT_API_TIMEOUT = 10     # секунд


# ================= ВАЛИДАТОРЫ =================

class ConfigValidator:
    """✅ Валидатор конфигурации"""
    
    @staticmethod
    def validate_trading_pair(pair: str) -> bool:
        """💱 Валидация торговой пары"""
        if not pair or '_' not in pair:
            return False
        
        parts = pair.split('_')
        if len(parts) != 2:
            return False
        
        base, quote = parts
        return (len(base) >= 2 and len(quote) >= 2 and 
                base.isalpha() and quote.isalpha())
    
    @staticmethod
    def validate_percentage(value: Decimal, min_val: Decimal = Decimal('0'), 
                          max_val: Decimal = Decimal('100')) -> bool:
        """📊 Валидация процентного значения"""
        return min_val <= value <= max_val
    
    @staticmethod
    def validate_positive_number(value: Any) -> bool:
        """➕ Валидация положительного числа"""
        try:
            return float(value) > 0
        except (ValueError, TypeError):
            return False
    
    @staticmethod
    def validate_api_credentials(api_key: str, api_secret: str) -> bool:
        """🔐 Валидация API ключей"""
        return (isinstance(api_key, str) and len(api_key) >= 32 and
                isinstance(api_secret, str) and len(api_secret) >= 32)


# ================= КОНФИГУРАЦИОННЫЕ УТИЛИТЫ =================

def print_config_summary(settings: TradingSystemSettings) -> None:
    """📊 Печать сводки конфигурации"""
    print("⚙️ КОНФИГУРАЦИЯ ТОРГОВОЙ СИСТЕМЫ")
    print("=" * 50)
    print(f"📊 Профиль: {settings.profile.value}")
    print(f"🌍 Окружение: {settings.environment.value}")
    print(f"💱 Торговая пара: {settings.trading.trading_pair}")
    print(f"🧪 Тестовый режим: {settings.test_mode}")
    print(f"🏃 Dry run: {settings.dry_run}")
    
    print(f"\n📈 ТОРГОВЫЕ НАСТРОЙКИ:")
    print(f"  Макс. позиция: {settings.trading.max_position_size_percent}%")
    print(f"  Мин. прибыль: {settings.trading.min_profit_percent}%")
    print(f"  DCA покупок: {settings.trading.dca_max_purchases}")
    print(f"  DCA размер: {settings.trading.dca_purchase_size_percent}%")
    
    print(f"\n🛡️ РИСК-МЕНЕДЖМЕНТ:")
    print(f"  Макс. просадка: {settings.risk.max_drawdown_percent}%")
    print(f"  Аварийный выход: {settings.risk.emergency_exit_enabled}")
    print(f"  BTC корреляция: {settings.risk.btc_correlation_enabled}")
    
    print(f"\n🔌 API НАСТРОЙКИ:")
    print(f"  Лимит в минуту: {settings.api.calls_per_minute}")
    print(f"  Лимит в час: {settings.api.calls_per_hour}")
    print(f"  Таймаут: {settings.api.timeout_seconds}с")
    print(f"  API ключ: {'✅ Настроен' if settings.api.api_key else '❌ Отсутствует'}")


def validate_environment_setup() -> List[str]:
    """🔍 Валидация окружения"""
    issues = []
    
    # Проверка переменных окружения
    required_env_vars = ["EXMO_API_KEY", "EXMO_API_SECRET"]
    for var in required_env_vars:
        if not os.getenv(var):
            issues.append(f"Missing environment variable: {var}")
    
    # Проверка директорий
    required_dirs = ["data", "logs", "backup"]
    for dir_name in required_dirs:
        if not Path(dir_name).exists():
            issues.append(f"Missing directory: {dir_name}")
    
    return issues