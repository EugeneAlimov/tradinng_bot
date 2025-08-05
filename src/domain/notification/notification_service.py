from typing import Optional, List, Dict, Any, Union, Callable
from decimal import Decimal
from datetime import datetime, timedelta
import logging
from dataclasses import dataclass, field
from enum import Enum
import asyncio
import json

# Импорты из Core слоя
try:
    from ...core.interfaces import INotificationService
    from ...core.models import Trade, Position, TradeSignal, OrderResult
    from ...core.exceptions import TradingSystemError, ValidationError
    from ...core.events import DomainEvent, publish_event
    from ...config.settings import get_current_config
except ImportError:
    # Fallback для случая если Core слой еще не готов
    class INotificationService: pass
    class Trade: pass
    class Position: pass
    class TradeSignal: pass
    class OrderResult: pass
    class TradingSystemError(Exception): pass
    class ValidationError(Exception): pass
    class DomainEvent: pass
    def publish_event(event): pass
    def get_current_config(): return None


# ================= ТИПЫ УВЕДОМЛЕНИЙ =================

class NotificationType(Enum):
    """📢 Типы уведомлений"""
    TRADE_EXECUTED = "trade_executed"
    POSITION_OPENED = "position_opened"
    POSITION_CLOSED = "position_closed"
    EMERGENCY_STOP = "emergency_stop"
    RISK_ALERT = "risk_alert"
    PROFIT_TARGET = "profit_target"
    STOP_LOSS = "stop_loss"
    DAILY_REPORT = "daily_report"
    SYSTEM_ERROR = "system_error"
    STRATEGY_SIGNAL = "strategy_signal"


class NotificationPriority(Enum):
    """⚡ Приоритеты уведомлений"""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4
    EMERGENCY = 5


class NotificationChannel(Enum):
    """📱 Каналы уведомлений"""
    CONSOLE = "console"
    LOG_FILE = "log_file"
    EMAIL = "email"
    TELEGRAM = "telegram"
    WEBHOOK = "webhook"
    SMS = "sms"


class NotificationStatus(Enum):
    """📊 Статусы уведомлений"""
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    DELIVERED = "delivered"
    READ = "read"


# ================= МОДЕЛИ УВЕДОМЛЕНИЙ =================

@dataclass
class NotificationTemplate:
    """📝 Шаблон уведомления"""
    id: str
    notification_type: NotificationType
    title_template: str
    message_template: str
    priority: NotificationPriority
    channels: List[NotificationChannel]
    enabled: bool = True
    variables: List[str] = field(default_factory=list)

    def render(self, context: Dict[str, Any]) -> tuple[str, str]:
        """🎨 Рендеринг шаблона с контекстом"""
        try:
            title = self.title_template.format(**context)
            message = self.message_template.format(**context)
            return title, message
        except KeyError as e:
            raise ValidationError(f"Missing template variable: {e}")


@dataclass
class Notification:
    """📢 Уведомление"""
    id: str = field(default_factory=lambda: f"notif_{datetime.now().timestamp()}")
    notification_type: NotificationType = NotificationType.SYSTEM_ERROR
    title: str = ""
    message: str = ""
    priority: NotificationPriority = NotificationPriority.NORMAL
    channels: List[NotificationChannel] = field(default_factory=list)
    status: NotificationStatus = NotificationStatus.PENDING
    context: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    sent_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    retry_count: int = 0
    max_retries: int = 3
    error_message: Optional[str] = None

    @property
    def age_minutes(self) -> float:
        """Возраст уведомления в минутах"""
        return (datetime.now() - self.created_at).total_seconds() / 60

    @property
    def is_expired(self) -> bool:
        """Истекло ли уведомление (24 часа)"""
        return self.age_minutes > 1440

    @property
    def can_retry(self) -> bool:
        """Можно ли повторить отправку"""
        return self.retry_count < self.max_retries and self.status == NotificationStatus.FAILED


@dataclass
class NotificationRule:
    """📋 Правило уведомлений"""
    id: str
    notification_type: NotificationType
    conditions: Dict[str, Any]
    channels: List[NotificationChannel]
    priority: NotificationPriority
    enabled: bool = True
    rate_limit_minutes: int = 0  # Ограничение частоты
    last_sent: Optional[datetime] = None

    def should_send(self, context: Dict[str, Any]) -> bool:
        """✅ Проверка необходимости отправки"""
        if not self.enabled:
            return False

        # Проверка rate limit
        if self.rate_limit_minutes > 0 and self.last_sent:
            time_since_last = datetime.now() - self.last_sent
            if time_since_last.total_seconds() < self.rate_limit_minutes * 60:
                return False

        # Проверка условий
        return self._check_conditions(context)

    def _check_conditions(self, context: Dict[str, Any]) -> bool:
        """🔍 Проверка условий правила"""
        try:
            for condition_key, condition_value in self.conditions.items():
                if condition_key not in context:
                    return False

                context_value = context[condition_key]

                # Простые условия равенства
                if isinstance(condition_value, (str, int, float, bool)):
                    if context_value != condition_value:
                        return False

                # Условия сравнения для числовых значений
                elif isinstance(condition_value, dict):
                    if 'min' in condition_value and context_value < condition_value['min']:
                        return False
                    if 'max' in condition_value and context_value > condition_value['max']:
                        return False

            return True

        except Exception:
            return False


# ================= ОСНОВНОЙ СЕРВИС =================

class NotificationService(INotificationService):
    """📢 Сервис уведомлений"""

    def __init__(self):
        # Шаблоны уведомлений
        self.templates: Dict[str, NotificationTemplate] = {}

        # Правила уведомлений
        self.rules: List[NotificationRule] = []

        # Очередь уведомлений
        self.notification_queue: List[Notification] = []

        # Обработчики каналов
        self.channel_handlers: Dict[NotificationChannel, Callable] = {}

        # Статистика
        self.stats = {
            'total_sent': 0,
            'total_failed': 0,
            'by_type': {},
            'by_channel': {},
            'by_priority': {}
        }

        # Логирование
        self.logger = logging.getLogger(__name__)

        # Инициализация
        self._initialize_default_templates()
        self._initialize_default_rules()
        self._initialize_channel_handlers()

        self.logger.info("📢 NotificationService инициализирован")

    # ================= ОСНОВНЫЕ МЕТОДЫ ИНТЕРФЕЙСА =================

    async def send_trade_notification(
        self,
        trade: Trade,
        notification_type: str = "trade_executed"
    ) -> None:
        """📱 Отправка уведомления о сделке"""

        try:
            context = {
                'trade_id': trade.id,
                'pair': str(trade.pair),
                'order_type': trade.order_type.value,
                'quantity': str(trade.quantity),
                'price': str(trade.price),
                'total_cost': str(trade.total_cost),
                'commission': str(trade.commission),
                'timestamp': trade.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                'strategy_name': trade.strategy_name or 'unknown'
            }

            await self._process_notification(NotificationType.TRADE_EXECUTED, context)

        except Exception as e:
            self.logger.error(f"❌ Ошибка отправки уведомления о сделке: {e}")

    async def send_emergency_notification(
        self,
        message: str,
        severity: str = "high"
    ) -> None:
        """🚨 Отправка экстренного уведомления"""

        try:
            priority_map = {
                'low': NotificationPriority.NORMAL,
                'medium': NotificationPriority.HIGH,
                'high': NotificationPriority.CRITICAL,
                'critical': NotificationPriority.EMERGENCY
            }

            priority = priority_map.get(severity, NotificationPriority.CRITICAL)

            notification = Notification(
                notification_type=NotificationType.EMERGENCY_STOP,
                title="🚨 ЭКСТРЕННОЕ УВЕДОМЛЕНИЕ",
                message=message,
                priority=priority,
                channels=[NotificationChannel.CONSOLE, NotificationChannel.LOG_FILE],
                context={'severity': severity, 'message': message}
            )

            await self._send_notification(notification)

        except Exception as e:
            self.logger.error(f"❌ Ошибка отправки экстренного уведомления: {e}")

    async def send_daily_report(self, report_data: Dict[str, Any]) -> None:
        """📊 Отправка дневного отчета"""

        try:
            context = {
                'date': datetime.now().strftime('%Y-%m-%d'),
                'total_trades': report_data.get('total_trades', 0),
                'total_pnl': str(report_data.get('total_pnl', '0')),
                'win_rate': report_data.get('win_rate', 0),
                'best_trade': str(report_data.get('best_trade', '0')),
                'worst_trade': str(report_data.get('worst_trade', '0')),
                'active_positions': report_data.get('active_positions', 0)
            }

            await self._process_notification(NotificationType.DAILY_REPORT, context)

        except Exception as e:
            self.logger.error(f"❌ Ошибка отправки дневного отчета: {e}")

    # ================= ОБРАБОТКА УВЕДОМЛЕНИЙ =================

    async def _process_notification(
        self,
        notification_type: NotificationType,
        context: Dict[str, Any]
    ) -> None:
        """🔄 Обработка уведомления"""

        try:
            # Проверяем правила
            applicable_rules = [
                rule for rule in self.rules
                if rule.notification_type == notification_type and rule.should_send(context)
            ]

            if not applicable_rules:
                self.logger.debug(f"📢 Нет применимых правил для {notification_type.value}")
                return

            # Создаем уведомления по правилам
            for rule in applicable_rules:
                notification = await self._create_notification_from_rule(
                    rule, notification_type, context
                )
                if notification:
                    await self._send_notification(notification)
                    # Обновляем время последней отправки
                    rule.last_sent = datetime.now()

        except Exception as e:
            self.logger.error(f"❌ Ошибка обработки уведомления: {e}")

    async def _create_notification_from_rule(
        self,
        rule: NotificationRule,
        notification_type: NotificationType,
        context: Dict[str, Any]
    ) -> Optional[Notification]:
        """📝 Создание уведомления из правила"""

        try:
            # Ищем подходящий шаблон
            template = self._find_template(notification_type)
            if not template:
                return None

            # Рендерим шаблон
            title, message = template.render(context)

            # Создаем уведомление
            notification = Notification(
                notification_type=notification_type,
                title=title,
                message=message,
                priority=rule.priority,
                channels=rule.channels,
                context=context
            )

            return notification

        except Exception as e:
            self.logger.error(f"❌ Ошибка создания уведомления из правила: {e}")
            return None

    async def _send_notification(self, notification: Notification) -> bool:
        """📤 Отправка уведомления"""

        try:
            success = False

            # Отправляем по всем каналам
            for channel in notification.channels:
                try:
                    handler = self.channel_handlers.get(channel)
                    if handler:
                        await handler(notification)
                        success = True
                        self._update_stats('by_channel', channel.value, True)
                    else:
                        self.logger.warning(f"⚠️ Нет обработчика для канала {channel.value}")

                except Exception as e:
                    self.logger.error(f"❌ Ошибка отправки через {channel.value}: {e}")
                    self._update_stats('by_channel', channel.value, False)

            # Обновляем статус уведомления
            if success:
                notification.status = NotificationStatus.SENT
                notification.sent_at = datetime.now()
                self.stats['total_sent'] += 1
            else:
                notification.status = NotificationStatus.FAILED
                notification.retry_count += 1
                self.stats['total_failed'] += 1

            # Обновляем статистику
            self._update_stats('by_type', notification.notification_type.value, success)
            self._update_stats('by_priority', notification.priority.value, success)

            return success

        except Exception as e:
            self.logger.error(f"❌ Ошибка отправки уведомления: {e}")
            notification.status = NotificationStatus.FAILED
            notification.error_message = str(e)
            return False

    # ================= ОБРАБОТЧИКИ КАНАЛОВ =================

    async def _console_handler(self, notification: Notification) -> None:
        """🖥️ Обработчик консольных уведомлений"""

        priority_icons = {
            NotificationPriority.LOW: "ℹ️",
            NotificationPriority.NORMAL: "📢",
            NotificationPriority.HIGH: "⚠️",
            NotificationPriority.CRITICAL: "🚨",
            NotificationPriority.EMERGENCY: "🆘"
        }

        icon = priority_icons.get(notification.priority, "📢")
        timestamp = notification.created_at.strftime('%H:%M:%S')

        print(f"{icon} [{timestamp}] {notification.title}")
        if notification.message != notification.title:
            print(f"   {notification.message}")

    async def _log_file_handler(self, notification: Notification) -> None:
        """📝 Обработчик файловых уведомлений"""

        log_level_map = {
            NotificationPriority.LOW: logging.DEBUG,
            NotificationPriority.NORMAL: logging.INFO,
            NotificationPriority.HIGH: logging.WARNING,
            NotificationPriority.CRITICAL: logging.ERROR,
            NotificationPriority.EMERGENCY: logging.CRITICAL
        }

        level = log_level_map.get(notification.priority, logging.INFO)

        log_message = f"[{notification.notification_type.value}] {notification.title}"
        if notification.message != notification.title:
            log_message += f" - {notification.message}"

        self.logger.log(level, log_message, extra={
            'notification_id': notification.id,
            'notification_type': notification.notification_type.value,
            'context': notification.context
        })

    async def _webhook_handler(self, notification: Notification) -> None:
        """🔗 Обработчик webhook уведомлений"""

        # Заглушка для webhook
        webhook_data = {
            'id': notification.id,
            'type': notification.notification_type.value,
            'title': notification.title,
            'message': notification.message,
            'priority': notification.priority.value,
            'timestamp': notification.created_at.isoformat(),
            'context': notification.context
        }

        self.logger.debug(f"🔗 Webhook уведомление: {json.dumps(webhook_data, indent=2)}")

    # ================= ИНИЦИАЛИЗАЦИЯ =================

    def _initialize_default_templates(self) -> None:
        """📋 Инициализация шаблонов по умолчанию"""

        templates = [
            NotificationTemplate(
                id="trade_executed",
                notification_type=NotificationType.TRADE_EXECUTED,
                title_template="💰 Сделка выполнена: {pair}",
                message_template="{order_type} {quantity} {pair} по цене {price} (стратегия: {strategy_name})",
                priority=NotificationPriority.NORMAL,
                channels=[NotificationChannel.CONSOLE, NotificationChannel.LOG_FILE],
                variables=['pair', 'order_type', 'quantity', 'price', 'strategy_name']
            ),

            NotificationTemplate(
                id="emergency_stop",
                notification_type=NotificationType.EMERGENCY_STOP,
                title_template="🚨 АВАРИЙНАЯ ОСТАНОВКА",
                message_template="Система остановлена: {message}",
                priority=NotificationPriority.EMERGENCY,
                channels=[NotificationChannel.CONSOLE, NotificationChannel.LOG_FILE],
                variables=['message']
            ),

            NotificationTemplate(
                id="daily_report",
                notification_type=NotificationType.DAILY_REPORT,
                title_template="📊 Дневной отчет за {date}",
                message_template="Сделок: {total_trades}, P&L: {total_pnl}, Win Rate: {win_rate}%",
                priority=NotificationPriority.NORMAL,
                channels=[NotificationChannel.LOG_FILE],
                variables=['date', 'total_trades', 'total_pnl', 'win_rate']
            ),

            NotificationTemplate(
                id="risk_alert",
                notification_type=NotificationType.RISK_ALERT,
                title_template="⚠️ Предупреждение о рисках",
                message_template="Превышен лимит: {risk_type} ({current_value}/{limit_value})",
                priority=NotificationPriority.HIGH,
                channels=[NotificationChannel.CONSOLE, NotificationChannel.LOG_FILE],
                variables=['risk_type', 'current_value', 'limit_value']
            )
        ]

        for template in templates:
            self.templates[template.id] = template

    def _initialize_default_rules(self) -> None:
        """📋 Инициализация правил по умолчанию"""

        rules = [
            NotificationRule(
                id="all_trades",
                notification_type=NotificationType.TRADE_EXECUTED,
                conditions={},  # Все сделки
                channels=[NotificationChannel.CONSOLE, NotificationChannel.LOG_FILE],
                priority=NotificationPriority.NORMAL
            ),

            NotificationRule(
                id="emergency_only",
                notification_type=NotificationType.EMERGENCY_STOP,
                conditions={},
                channels=[NotificationChannel.CONSOLE, NotificationChannel.LOG_FILE],
                priority=NotificationPriority.EMERGENCY
            ),

            NotificationRule(
                id="daily_reports",
                notification_type=NotificationType.DAILY_REPORT,
                conditions={},
                channels=[NotificationChannel.LOG_FILE],
                priority=NotificationPriority.NORMAL,
                rate_limit_minutes=1440  # Раз в день
            ),

            NotificationRule(
                id="high_risk_alerts",
                notification_type=NotificationType.RISK_ALERT,
                conditions={'severity': 'high'},
                channels=[NotificationChannel.CONSOLE, NotificationChannel.LOG_FILE],
                priority=NotificationPriority.CRITICAL,
                rate_limit_minutes=60  # Не чаще раза в час
            )
        ]

        self.rules.extend(rules)

    def _initialize_channel_handlers(self) -> None:
        """🔧 Инициализация обработчиков каналов"""

        self.channel_handlers = {
            NotificationChannel.CONSOLE: self._console_handler,
            NotificationChannel.LOG_FILE: self._log_file_handler,
            NotificationChannel.WEBHOOK: self._webhook_handler
        }

    # ================= УТИЛИТЫ =================

    def _find_template(self, notification_type: NotificationType) -> Optional[NotificationTemplate]:
        """🔍 Поиск шаблона для типа уведомления"""

        for template in self.templates.values():
            if template.notification_type == notification_type and template.enabled:
                return template
        return None

    def _update_stats(self, category: str, key: str, success: bool) -> None:
        """📊 Обновление статистики"""

        if category not in self.stats:
            self.stats[category] = {}

        if key not in self.stats[category]:
            self.stats[category][key] = {'sent': 0, 'failed': 0}

        if success:
            self.stats[category][key]['sent'] += 1
        else:
            self.stats[category][key]['failed'] += 1

    # ================= УПРАВЛЕНИЕ И МОНИТОРИНГ =================

    def add_rule(self, rule: NotificationRule) -> bool:
        """➕ Добавление правила уведомлений"""

        try:
            # Проверяем уникальность ID
            existing_ids = [r.id for r in self.rules]
            if rule.id in existing_ids:
                self.logger.warning(f"⚠️ Правило {rule.id} уже существует")
                return False

            self.rules.append(rule)
            self.logger.info(f"✅ Правило {rule.id} добавлено")
            return True

        except Exception as e:
            self.logger.error(f"❌ Ошибка добавления правила: {e}")
            return False

    def remove_rule(self, rule_id: str) -> bool:
        """➖ Удаление правила уведомлений"""

        try:
            self.rules = [r for r in self.rules if r.id != rule_id]
            self.logger.info(f"🗑️ Правило {rule_id} удалено")
            return True

        except Exception as e:
            self.logger.error(f"❌ Ошибка удаления правила: {e}")
            return False

    def get_statistics(self) -> Dict[str, Any]:
        """📊 Получение статистики уведомлений"""

        return {
            'total_sent': self.stats['total_sent'],
            'total_failed': self.stats['total_failed'],
            'success_rate': (
                self.stats['total_sent'] /
                (self.stats['total_sent'] + self.stats['total_failed']) * 100
            ) if (self.stats['total_sent'] + self.stats['total_failed']) > 0 else 0,
            'by_type': self.stats.get('by_type', {}),
            'by_channel': self.stats.get('by_channel', {}),
            'by_priority': self.stats.get('by_priority', {}),
            'active_rules': len([r for r in self.rules if r.enabled]),
            'total_templates': len(self.templates)
        }

    async def test_notification(self, channel: NotificationChannel) -> bool:
        """🧪 Тестовое уведомление"""

        try:
            test_notification = Notification(
                notification_type=NotificationType.SYSTEM_ERROR,
                title="🧪 Тестовое уведомление",
                message=f"Проверка канала {channel.value}",
                priority=NotificationPriority.LOW,
                channels=[channel],
                context={'test': True}
            )

            return await self._send_notification(test_notification)

        except Exception as e:
            self.logger.error(f"❌ Ошибка тестового уведомления: {e}")
            return False
