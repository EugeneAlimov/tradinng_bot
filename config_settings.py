#!/usr/bin/env python3
"""⚙️ Единая система конфигурации торговой системы"""

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Union
from pathlib import Path
from decimal import Decimal

from ..core.models import ConfigProfile, TradingPair
from ..core.constants import (
    Trading, Risk, Timing, Strategies, 
    Analytics, Logging, Profiles, API
)
from ..core.exceptions import ConfigurationError

try:
    from dotenv import load_dotenv
    load_dotenv()
    DOTENV_AVAILABLE = True
except ImportError:
    DOTENV_AVAILABLE = False


@dataclass
class APISettings:
    """🌐 Настройки API"""
    # EXMO API
    exmo_api_key: str = ""
    exmo_api_secret: str = ""
    exmo_base_url: str = API.EXMO_BASE_URL
    exmo_timeout: int = API.EXMO_TIMEOUT
    exmo_max_retries: int = API.EXMO_MAX_RETRIES
    
    # Rate Limiting
    calls_per_minute: int = API.DEFAULT_CALLS_PER_MINUTE
    calls_per_hour: int = API.DEFAULT_CALLS_PER_HOUR
    adaptive_rate_limiting: bool = True
    
    # Кэширование
    cache_enabled: bool = True
    cache_default_ttl: int = Timing.CACHE_DEFAULT_TTL
    cache_price_ttl: int = Timing.CACHE_PRICE_TTL
    cache_balance_ttl: int = Timing.CACHE_BALANCE_TTL
    
    def __post_init__(self):
        """Загрузка из переменных окружения"""
        if not self.exmo_api_key:
            self.exmo_api_key = os.getenv('EXMO_API_KEY', '')
        
        if not self.exmo_api_secret:
            self.exmo_api_secret = os.getenv('EXMO_API_SECRET', '')
    
    def validate(self) -> None:
        """✅ Валидация настроек API"""
        if not self.exmo_api_key:
            raise ConfigurationError("EXMO API ключ не настроен")
        
        if not self.exmo_api_secret:
            raise ConfigurationError("EXMO API секрет не настроен")
        
        if len(self.exmo_api_key) < 32:
            raise ConfigurationError("EXMO API ключ слишком короткий")
        
        if self.calls_per_minute <= 0 or self.calls_per_hour <= 0:
            raise ConfigurationError("Лимиты API должны быть положительными")


@dataclass
class TradingSettings:
    """💱 Торговые настройки"""
    # Торговая пара
    primary_pair: TradingPair = field(default_factory=lambda: TradingPair.from_string(Trading.DEFAULT_PAIR))
    supported_pairs: List[str] = field(default_factory=lambda: Trading.SUPPORTED_PAIRS.copy())
    
    # Размеры позиций
    position_size_percent: float = Risk.DEFAULT_POSITION_SIZE
    min_order_size_eur: Decimal = Trading.MIN_ORDER_SIZE
    max_position_size_percent: float = 50.0
    
    # Прибыль и убытки
    min_profit_percent: float = Risk.DEFAULT_MIN_PROFIT
    stop_loss_percent: float = Risk.DEFAULT_STOP_LOSS
    
    # Комиссии
    taker_fee: Decimal = Trading.TAKER_FEE
    maker_fee: Decimal = Trading.MAKER_FEE
    
    # Точность
    price_precision: int = Trading.PRICE_PRECISION
    quantity_precision: int = Trading.QUANTITY_PRECISION
    
    def validate(self) -> None:
        """✅ Валидация торговых настроек"""
        if not 0.1 <= self.position_size_percent <= 100:
            raise ConfigurationError("Размер позиции должен быть от 0.1% до 100%")
        
        if not 0.1 <= self.min_profit_percent <= 50:
            raise ConfigurationError("Минимальная прибыль должна быть от 0.1% до 50%")
        
        if not 1 <= self.stop_loss_percent <= 50:
            raise ConfigurationError("Стоп-лосс должен быть от 1% до 50%")


@dataclass
class DCASettings:
    """🛒 Настройки DCA стратегии"""
    enabled: bool = True
    drop_threshold_percent: float = Strategies.DCA_DEFAULT_DROP_THRESHOLD
    purchase_size_percent: float = Strategies.DCA_DEFAULT_PURCHASE_SIZE
    max_purchases: int = Strategies.DCA_DEFAULT_MAX_PURCHASES
    cooldown_minutes: int = Strategies.DCA_DEFAULT_COOLDOWN_MINUTES
    max_position_percent: float = Strategies.DCA_DEFAULT_MAX_POSITION
    
    # Лимиты
    max_consecutive: int = Risk.DCA_MAX_CONSECUTIVE
    max_per_day: int = Risk.DCA_MAX_PER_DAY
    min_interval_minutes: int = Risk.DCA_MIN_INTERVAL_MINUTES
    loss_block_threshold_percent: float = Risk.DCA_LOSS_BLOCK_THRESHOLD
    
    def validate(self) -> None:
        """✅ Валидация DCA настроек"""
        if self.enabled:
            if not 0.5 <= self.drop_threshold_percent <= 10:
                raise ConfigurationError("Порог падения DCA должен быть от 0.5% до 10%")
            
            if not 1 <= self.purchase_size_percent <= 20:
                raise ConfigurationError("Размер DCA покупки должен быть от 1% до 20%")
            
            if not 1 <= self.max_purchases <= 10:
                raise ConfigurationError("Максимум DCA покупок должно быть от 1 до 10")


@dataclass
class PyramidSettings:
    """🏗️ Настройки пирамидальной стратегии"""
    enabled: bool = True
    levels: List[Dict[str, float]] = field(default_factory=lambda: Strategies.PYRAMID_DEFAULT_LEVELS.copy())
    
    # Аварийные уровни
    emergency_levels: List[Dict[str, float]] = field(default_factory=lambda: [
        {"loss_pct": 8.0, "sell_pct": 30.0, "time_hours": 4},
        {"loss_pct": 12.0, "sell_pct": 50.0, "time_hours": 0},
        {"loss_pct": 15.0, "sell_pct": 100.0, "time_hours": 0},
    ])
    
    cooldown_minutes: int = 5
    
    def validate(self) -> None:
        """✅ Валидация пирамидальных настроек"""
        if self.enabled:
            for i, level in enumerate(self.levels):
                if not all(key in level for key in ['profit_pct', 'sell_pct', 'min_eur']):
                    raise ConfigurationError(f"Некорректный уровень пирамиды {i}")
                
                if not 0.1 <= level['profit_pct'] <= 50:
                    raise ConfigurationError(f"Прибыль пирамиды {i} должна быть от 0.1% до 50%")


@dataclass
class RiskSettings:
    """🛡️ Настройки управления рисками"""
    # Общие лимиты
    max_daily_loss_percent: float = Risk.MAX_DAILY_LOSS
    max_trades_per_hour: int = Risk.MAX_TRADES_PER_HOUR
    max_trades_per_day: int = Risk.MAX_TRADES_PER_DAY
    max_api_errors_per_hour: int = Risk.MAX_API_ERRORS_PER_HOUR
    
    # Аварийный выход
    emergency_exit_enabled: bool = True
    critical_loss_percent: float = Risk.EMERGENCY_CRITICAL_LOSS
    major_loss_percent: float = Risk.EMERGENCY_MAJOR_LOSS
    significant_loss_percent: float = Risk.EMERGENCY_SIGNIFICANT_LOSS
    time_limit_hours: int = Risk.EMERGENCY_TIME_LIMIT_HOURS
    
    # Волатильность
    high_volatility_threshold_percent: float = Risk.HIGH_VOLATILITY_THRESHOLD
    btc_crash_threshold_percent: float = Risk.BTC_CRASH_THRESHOLD
    correlation_monitoring_enabled: bool = True
    
    def validate(self) -> None:
        """✅ Валидация риск настроек"""
        if not 0.5 <= self.max_daily_loss_percent <= 20:
            raise ConfigurationError("Максимальные дневные потери должны быть от 0.5% до 20%")
        
        if self.emergency_exit_enabled:
            if not 5 <= self.critical_loss_percent <= 50:
                raise ConfigurationError("Критический убыток должен быть от 5% до 50%")


@dataclass
class TimingSettings:
    """⏰ Временные настройки"""
    # Интервалы обновления
    default_update_interval: int = Timing.DEFAULT_UPDATE_INTERVAL
    fast_update_interval: int = Timing.FAST_UPDATE_INTERVAL
    slow_update_interval: int = Timing.SLOW_UPDATE_INTERVAL
    
    # Таймауты
    api_timeout: int = Timing.API_TIMEOUT
    order_timeout: int = Timing.ORDER_TIMEOUT
    price_validity_seconds: int = Timing.PRICE_VALIDITY
    
    # Периоды анализа
    short_analysis_period_days: int = Timing.ANALYSIS_SHORT_PERIOD
    medium_analysis_period_days: int = Timing.ANALYSIS_MEDIUM_PERIOD
    long_analysis_period_days: int = Timing.ANALYSIS_LONG_PERIOD
    
    def validate(self) -> None:
        """✅ Валидация временных настроек"""
        if not 1 <= self.default_update_interval <= 60:
            raise ConfigurationError("Интервал обновления должен быть от 1 до 60 секунд")
        
        if not 1 <= self.api_timeout <= 60:
            raise ConfigurationError("Таймаут API должен быть от 1 до 60 секунд")


@dataclass
class LoggingSettings:
    """📝 Настройки логирования"""
    level: str = Logging.DEFAULT_LEVEL
    console_enabled: bool = True
    file_enabled: bool = True
    
    # Файлы
    file_path: str = "logs/trading_bot.log"
    max_file_size_mb: int = Logging.MAX_LOG_FILE_SIZE // (1024 * 1024)
    max_files: int = Logging.MAX_LOG_FILES
    
    # Форматы
    console_format: str = Logging.CONSOLE_FORMAT
    file_format: str = Logging.FILE_FORMAT
    
    # Категории
    trading_enabled: bool = True
    api_enabled: bool = True
    strategy_enabled: bool = True
    risk_enabled: bool = True
    analytics_enabled: bool = True
    
    def validate(self) -> None:
        """✅ Валидация настроек логирования"""
        if self.level not in Logging.LEVELS:
            raise ConfigurationError(f"Неизвестный уровень логирования: {self.level}")
        
        if self.file_enabled:
            log_dir = Path(self.file_path).parent
            if not log_dir.exists():
                log_dir.mkdir(parents=True, exist_ok=True)


@dataclass
class AnalyticsSettings:
    """📊 Настройки аналитики"""
    enabled: bool = True
    
    # Отчеты
    auto_reports_enabled: bool = True
    daily_report_enabled: bool = True
    weekly_report_enabled: bool = True
    
    # Экспорт
    auto_export_enabled: bool = False
    export_format: str = "json"
    export_directory: str = "data/exports"
    
    # Графики
    charts_enabled: bool = True
    chart_directory: str = "data/charts"
    
    # Метрики
    calculate_sharpe_ratio: bool = True
    risk_free_rate: float = Analytics.SHARPE_RATIO_RISK_FREE_RATE
    
    def validate(self) -> None:
        """✅ Валидация настроек аналитики"""
        if self.enabled:
            if self.export_format not in Analytics.SUPPORTED_EXPORT_FORMATS:
                raise ConfigurationError(f"Неподдерживаемый формат экспорта: {self.export_format}")
            
            # Создаем директории
            if self.auto_export_enabled:
                Path(self.export_directory).mkdir(parents=True, exist_ok=True)
            
            if self.charts_enabled:
                Path(self.chart_directory).mkdir(parents=True, exist_ok=True)


@dataclass
class NotificationSettings:
    """📱 Настройки уведомлений"""
    enabled: bool = False
    
    # Telegram
    telegram_enabled: bool = False
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    
    # Email
    email_enabled: bool = False
    email_smtp_server: str = ""
    email_smtp_port: int = 587
    email_username: str = ""
    email_password: str = ""
    email_to: str = ""
    
    # Webhook
    webhook_enabled: bool = False
    webhook_url: str = ""
    
    # Настройки уведомлений
    trade_notifications: bool = True
    emergency_notifications: bool = True
    daily_report_notifications: bool = True
    error_notifications: bool = True
    
    def __post_init__(self):
        """Загрузка из переменных окружения"""
        if not self.telegram_bot_token:
            self.telegram_bot_token = os.getenv('TELEGRAM_BOT_TOKEN', '')
        
        if not self.telegram_chat_id:
            self.telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID', '')
    
    def validate(self) -> None:
        """✅ Валидация настроек уведомлений"""
        if self.telegram_enabled:
            if not self.telegram_bot_token:
                raise ConfigurationError("Telegram bot token не настроен")
            
            if not self.telegram_chat_id:
                raise ConfigurationError("Telegram chat ID не настроен")


@dataclass
class TradingSystemSettings:
    """🎯 Главная конфигурация торговой системы"""
    
    # Профиль конфигурации
    profile_name: str = Profiles.BALANCED
    
    # Компоненты настроек
    api: APISettings = field(default_factory=APISettings)
    trading: TradingSettings = field(default_factory=TradingSettings)
    dca: DCASettings = field(default_factory=DCASettings)
    pyramid: PyramidSettings = field(default_factory=PyramidSettings)
    risk: RiskSettings = field(default_factory=RiskSettings)
    timing: TimingSettings = field(default_factory=TimingSettings)
    logging: LoggingSettings = field(default_factory=LoggingSettings)
    analytics: AnalyticsSettings = field(default_factory=AnalyticsSettings)
    notifications: NotificationSettings = field(default_factory=NotificationSettings)
    
    # Метаданные
    version: str = "4.1-refactored"
    created_at: str = field(default_factory=lambda: str(datetime.now()))
    
    @classmethod
    def from_profile(cls, profile_name: str) -> 'TradingSystemSettings':
        """🎯 Создание настроек из профиля"""
        if profile_name not in Profiles.PROFILE_CONFIGS:
            raise ConfigurationError(f"Неизвестный профиль: {profile_name}")
        
    @classmethod
    def from_profile(cls, profile_name: str) -> 'TradingSystemSettings':
        """🎯 Создание настроек из профиля"""
        if profile_name not in Profiles.PROFILE_CONFIGS:
            raise ConfigurationError(f"Неизвестный профиль: {profile_name}")
        
        settings = cls(profile_name=profile_name)
        profile_config = Profiles.PROFILE_CONFIGS[profile_name]
        
        # Применяем настройки профиля
        settings.trading.position_size_percent = profile_config["position_size_pct"]
        settings.trading.min_profit_percent = profile_config["min_profit_pct"]
        settings.trading.stop_loss_percent = profile_config["stop_loss_pct"]
        settings.dca.purchase_size_percent = profile_config["dca_purchase_size_pct"]
        settings.dca.max_purchases = profile_config["dca_max_purchases"]
        settings.timing.default_update_interval = profile_config["update_interval"]
        
        return settings
    
    @classmethod
    def from_env(cls) -> 'TradingSystemSettings':
        """🌍 Создание настроек из переменных окружения"""
        settings = cls()
        
        # Автоматическая загрузка из переменных окружения
        # (уже реализована в __post_init__ подкомпонентов)
        
        # Дополнительные переменные окружения
        if profile := os.getenv('TRADING_PROFILE'):
            if profile in Profiles.PROFILE_CONFIGS:
                return cls.from_profile(profile)
        
        # Переопределение отдельных параметров
        if pos_size := os.getenv('POSITION_SIZE_PERCENT'):
            settings.trading.position_size_percent = float(pos_size)
        
        if min_profit := os.getenv('MIN_PROFIT_PERCENT'):
            settings.trading.min_profit_percent = float(min_profit)
        
        if update_interval := os.getenv('UPDATE_INTERVAL'):
            settings.timing.default_update_interval = int(update_interval)
        
        if log_level := os.getenv('LOG_LEVEL'):
            settings.logging.level = log_level.upper()
        
        return settings
    
    @classmethod
    def from_file(cls, file_path: str) -> 'TradingSystemSettings':
        """📁 Загрузка настроек из файла"""
        import json
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Создаем настройки и применяем данные из файла
            settings = cls()
            
            # Применяем настройки из файла (упрощенная версия)
            if 'profile_name' in data:
                settings.profile_name = data['profile_name']
            
            # Здесь можно добавить более сложную логику десериализации
            # В полной реализации стоит использовать библиотеки типа marshmallow
            
            return settings
            
        except FileNotFoundError:
            raise ConfigurationError(f"Файл конфигурации не найден: {file_path}")
        except json.JSONDecodeError as e:
            raise ConfigurationError(f"Ошибка парсинга JSON в {file_path}: {e}")
        except Exception as e:
            raise ConfigurationError(f"Ошибка загрузки конфигурации из {file_path}: {e}")
    
    def validate_all(self) -> None:
        """✅ Валидация всех настроек"""
        try:
            self.api.validate()
            self.trading.validate()
            self.dca.validate()
            self.pyramid.validate()
            self.risk.validate()
            self.timing.validate()
            self.logging.validate()
            self.analytics.validate()
            self.notifications.validate()
            
            # Кросс-валидация между компонентами
            self._validate_cross_component()
            
        except Exception as e:
            raise ConfigurationError(f"Ошибка валидации конфигурации: {e}")
    
    def _validate_cross_component(self) -> None:
        """🔗 Кросс-валидация между компонентами"""
        
        # Проверяем совместимость DCA и торговых настроек
        if self.dca.enabled:
            max_dca_position = self.dca.max_purchases * self.dca.purchase_size_percent
            if max_dca_position > self.trading.max_position_size_percent:
                raise ConfigurationError(
                    f"Максимальная DCA позиция ({max_dca_position}%) превышает "
                    f"лимит позиции ({self.trading.max_position_size_percent}%)"
                )
        
        # Проверяем совместимость риск-настроек
        if self.risk.emergency_exit_enabled:
            if self.risk.critical_loss_percent <= self.trading.stop_loss_percent:
                raise ConfigurationError(
                    "Критический убыток должен быть больше обычного стоп-лосса"
                )
        
        # Проверяем API лимиты vs торговые лимиты
        max_trades_per_minute = self.risk.max_trades_per_hour / 60
        if max_trades_per_minute > self.api.calls_per_minute * 0.5:  # 50% запросов на торговлю
            raise ConfigurationError(
                "Лимит сделок может превысить лимиты API"
            )
    
    def to_dict(self) -> Dict[str, Any]:
        """📋 Экспорт настроек в словарь"""
        from dataclasses import asdict
        return asdict(self)
    
    def save_to_file(self, file_path: str) -> None:
        """💾 Сохранение настроек в файл"""
        import json
        from pathlib import Path
        
        # Создаем директорию если не существует
        Path(file_path).parent.mkdir(parents=True, exist_ok=True)
        
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(self.to_dict(), f, indent=2, ensure_ascii=False, default=str)
                
        except Exception as e:
            raise ConfigurationError(f"Ошибка сохранения конфигурации в {file_path}: {e}")
    
    def get_profile_config(self) -> ConfigProfile:
        """🎯 Получение объекта профиля конфигурации"""
        if self.profile_name == Profiles.CONSERVATIVE:
            return ConfigProfile.create_conservative()
        elif self.profile_name == Profiles.AGGRESSIVE:
            return ConfigProfile.create_aggressive()
        else:
            return ConfigProfile.create_balanced()
    
    def print_summary(self) -> None:
        """📋 Вывод сводки настроек"""
        print(f"⚙️ КОНФИГУРАЦИЯ ТОРГОВОЙ СИСТЕМЫ v{self.version}")
        print("=" * 60)
        print(f"📊 Профиль: {self.profile_name}")
        print(f"💱 Торговая пара: {self.trading.primary_pair}")
        print(f"📊 Размер позиции: {self.trading.position_size_percent:.1f}%")
        print(f"💎 Мин. прибыль: {self.trading.min_profit_percent:.1f}%")
        print(f"🚨 Стоп-лосс: {self.trading.stop_loss_percent:.1f}%")
        print()
        
        print("🔧 АКТИВНЫЕ СИСТЕМЫ:")
        print(f"   🛒 DCA стратегия: {'✅' if self.dca.enabled else '❌'}")
        print(f"   🏗️ Пирамидальная продажа: {'✅' if self.pyramid.enabled else '❌'}")
        print(f"   🚨 Аварийный выход: {'✅' if self.risk.emergency_exit_enabled else '❌'}")
        print(f"   📊 Аналитика: {'✅' if self.analytics.enabled else '❌'}")
        print(f"   📱 Уведомления: {'✅' if self.notifications.enabled else '❌'}")
        print()
        
        print("⏰ ИНТЕРВАЛЫ:")
        print(f"   Обновление: {self.timing.default_update_interval}с")
        print(f"   DCA кулдаун: {self.dca.cooldown_minutes}мин")
        print(f"   API таймаут: {self.timing.api_timeout}с")
        print()
        
        print("🛡️ ЛИМИТЫ БЕЗОПАСНОСТИ:")
        print(f"   Максимальные дневные потери: {self.risk.max_daily_loss_percent:.1f}%")
        print(f"   Критический убыток: {self.risk.critical_loss_percent:.1f}%")
        print(f"   Сделок в час: {self.risk.max_trades_per_hour}")
        print(f"   API вызовов в минуту: {self.api.calls_per_minute}")


class ConfigurationManager:
    """🎛️ Менеджер конфигурации"""
    
    def __init__(self):
        self._settings: Optional[TradingSystemSettings] = None
        self._config_file_path = "config/settings.json"
    
    @property
    def settings(self) -> TradingSystemSettings:
        """⚙️ Получение текущих настроек"""
        if self._settings is None:
            self.load_default()
        return self._settings
    
    def load_default(self) -> None:
        """🔄 Загрузка настроек по умолчанию"""
        self._settings = TradingSystemSettings.from_env()
        self._settings.validate_all()
    
    def load_from_profile(self, profile_name: str) -> None:
        """🎯 Загрузка настроек из профиля"""
        self._settings = TradingSystemSettings.from_profile(profile_name)
        self._settings.validate_all()
    
    def load_from_file(self, file_path: Optional[str] = None) -> None:
        """📁 Загрузка настроек из файла"""
        path = file_path or self._config_file_path
        self._settings = TradingSystemSettings.from_file(path)
        self._settings.validate_all()
    
    def save_current(self, file_path: Optional[str] = None) -> None:
        """💾 Сохранение текущих настроек"""
        if self._settings is None:
            raise ConfigurationError("Нет настроек для сохранения")
        
        path = file_path or self._config_file_path
        self._settings.save_to_file(path)
    
    def update_setting(self, path: str, value: Any) -> None:
        """🔧 Обновление отдельной настройки"""
        if self._settings is None:
            self.load_default()
        
        # Простая реализация обновления по пути (можно улучшить)
        parts = path.split('.')
        obj = self._settings
        
        for part in parts[:-1]:
            obj = getattr(obj, part)
        
        setattr(obj, parts[-1], value)
        
        # Валидируем после изменения
        self._settings.validate_all()
    
    def get_setting(self, path: str) -> Any:
        """📖 Получение отдельной настройки"""
        if self._settings is None:
            self.load_default()
        
        parts = path.split('.')
        obj = self._settings
        
        for part in parts:
            obj = getattr(obj, part)
        
        return obj
    
    def reset_to_defaults(self) -> None:
        """🔄 Сброс к настройкам по умолчанию"""
        self._settings = None
        self.load_default()
    
    def validate_current(self) -> bool:
        """✅ Валидация текущих настроек"""
        try:
            if self._settings:
                self._settings.validate_all()
            return True
        except ConfigurationError:
            return False
    
    def get_profiles_list(self) -> List[str]:
        """📋 Список доступных профилей"""
        return list(Profiles.PROFILE_CONFIGS.keys())
    
    def create_custom_profile(
        self, 
        name: str, 
        base_profile: str = Profiles.BALANCED,
        **overrides
    ) -> None:
        """🎨 Создание кастомного профиля"""
        if base_profile not in Profiles.PROFILE_CONFIGS:
            raise ConfigurationError(f"Базовый профиль не найден: {base_profile}")
        
        # Создаем новый профиль на основе существующего
        new_profile = Profiles.PROFILE_CONFIGS[base_profile].copy()
        new_profile.update(overrides)
        
        # Добавляем в список профилей
        Profiles.PROFILE_CONFIGS[name] = new_profile


# Глобальный экземпляр менеджера конфигурации
config_manager = ConfigurationManager()

# Удобные функции для быстрого доступа
def get_settings() -> TradingSystemSettings:
    """⚙️ Получение текущих настроек"""
    return config_manager.settings

def load_config(profile_name: Optional[str] = None, file_path: Optional[str] = None) -> TradingSystemSettings:
    """🔄 Загрузка конфигурации"""
    if file_path:
        config_manager.load_from_file(file_path)
    elif profile_name:
        config_manager.load_from_profile(profile_name)
    else:
        config_manager.load_default()
    
    return config_manager.settings

def save_config(file_path: Optional[str] = None) -> None:
    """💾 Сохранение конфигурации"""
    config_manager.save_current(file_path)

def update_config(path: str, value: Any) -> None:
    """🔧 Обновление настройки"""
    config_manager.update_setting(path, value)


if __name__ == "__main__":
    # Пример использования
    print("🎯 Тестирование системы конфигурации")
    
    # Загружаем настройки по умолчанию
    settings = TradingSystemSettings.from_env()
    
    # Валидируем
    try:
        settings.validate_all()
        print("✅ Валидация успешна")
    except ConfigurationError as e:
        print(f"❌ Ошибка валидации: {e}")
    
    # Выводим сводку
    settings.print_summary()
    
    # Тестируем профили
    print("\n🎯 Тестирование профилей:")
    for profile_name in [Profiles.CONSERVATIVE, Profiles.BALANCED, Profiles.AGGRESSIVE]:
        try:
            profile_settings = TradingSystemSettings.from_profile(profile_name)
            profile_settings.validate_all()
            print(f"✅ Профиль {profile_name}: OK")
        except Exception as e:
            print(f"❌ Профиль {profile_name}: {e}")