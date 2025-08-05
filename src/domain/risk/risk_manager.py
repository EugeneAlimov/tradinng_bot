#!/usr/bin/env python3
"""🛡️ Сервис управления рисками - Domain слой (Часть 1)"""

from typing import Optional, Dict, Any, List, Tuple
from decimal import Decimal
from datetime import datetime, timedelta
import logging
from dataclasses import dataclass, field
from enum import Enum

# Импорты из Core слоя
try:
    from ...core.interfaces import IRiskManager
    from ...core.models import TradeSignal, Position, Money, TradingPair, StrategySignalType
    from ...core.exceptions import (
        RiskManagementError, RiskLimitExceededError, EmergencyStopError,
        ValidationError
    )
    from ...core.events import DomainEvent, publish_event
    from ...config.settings import get_current_config
except ImportError:
    # Fallback для случая если Core слой еще не готов
    class IRiskManager: pass
    class TradeSignal: pass
    class Position: pass
    class Money: pass
    class TradingPair: pass
    class StrategySignalType: pass
    class RiskManagementError(Exception): pass
    class RiskLimitExceededError(Exception): pass
    class EmergencyStopError(Exception): pass
    class ValidationError(Exception): pass
    class DomainEvent: pass
    def publish_event(event): pass
    def get_current_config(): return None


# ================= ТИПЫ РИСКОВ =================

class RiskType(Enum):
    """🛡️ Типы рисков"""
    POSITION_SIZE = "position_size"        # Размер позиции
    DAILY_LOSS = "daily_loss"             # Дневные потери
    DRAWDOWN = "drawdown"                 # Просадка
    CORRELATION = "correlation"           # Корреляция
    VOLATILITY = "volatility"             # Волатильность
    LIQUIDITY = "liquidity"               # Ликвидность
    EMERGENCY = "emergency"               # Аварийная ситуация


class RiskSeverity(Enum):
    """📊 Уровни серьезности риска"""
    LOW = "low"                           # Низкий риск
    MEDIUM = "medium"                     # Средний риск
    HIGH = "high"                         # Высокий риск
    CRITICAL = "critical"                 # Критический риск


class RiskAction(Enum):
    """⚡ Действия по рискам"""
    ALLOW = "allow"                       # Разрешить
    WARN = "warn"                         # Предупредить
    LIMIT = "limit"                       # Ограничить
    BLOCK = "block"                       # Заблокировать
    EMERGENCY_EXIT = "emergency_exit"     # Аварийный выход


# ================= МОДЕЛИ РИСКОВ =================

@dataclass
class RiskAssessment:
    """📊 Оценка риска"""
    risk_type: RiskType
    severity: RiskSeverity
    action: RiskAction
    score: float  # 0.0 - 1.0
    description: str
    recommendation: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_critical(self) -> bool:
        """Критический риск"""
        return self.severity == RiskSeverity.CRITICAL

    @property
    def requires_action(self) -> bool:
        """Требует действий"""
        return self.action in [RiskAction.LIMIT, RiskAction.BLOCK, RiskAction.EMERGENCY_EXIT]


@dataclass
class RiskLimits:
    """📏 Лимиты рисков"""
    max_position_size_percent: Decimal = Decimal('10.0')    # Максимальный размер позиции
    max_daily_loss_percent: Decimal = Decimal('5.0')        # Максимальные дневные потери
    max_drawdown_percent: Decimal = Decimal('15.0')         # Максимальная просадка
    max_correlation_threshold: Decimal = Decimal('0.8')     # Максимальная корреляция
    emergency_stop_percent: Decimal = Decimal('20.0')       # Аварийная остановка
    max_trades_per_hour: int = 20                           # Максимум сделок в час
    max_trades_per_day: int = 100                           # Максимум сделок в день
    min_balance_eur: Decimal = Decimal('5.0')               # Минимальный баланс

    def validate(self) -> None:
        """✅ Валидация лимитов"""
        if self.max_position_size_percent <= 0:
            raise ValidationError("Max position size must be positive")
        if self.max_daily_loss_percent <= 0:
            raise ValidationError("Max daily loss must be positive")


@dataclass
class RiskMetrics:
    """📈 Метрики рисков"""
    current_balance: Decimal = Decimal('0')
    total_positions_value: Decimal = Decimal('0')
    daily_pnl: Decimal = Decimal('0')
    total_pnl: Decimal = Decimal('0')
    max_drawdown: Decimal = Decimal('0')
    trades_today: int = 0
    trades_this_hour: int = 0
    last_trade_time: Optional[datetime] = None
    emergency_stops_today: int = 0

    @property
    def portfolio_value(self) -> Decimal:
        """Общая стоимость портфеля"""
        return self.current_balance + self.total_positions_value

    @property
    def daily_return_percent(self) -> float:
        """Дневная доходность в процентах"""
        if self.current_balance <= 0:
            return 0.0
        return float(self.daily_pnl / self.current_balance * 100)


# ================= ОСНОВНОЙ МЕНЕДЖЕР РИСКОВ =================

class RiskManager(IRiskManager):
    """🛡️ Менеджер рисков"""

    def __init__(self, risk_limits: Optional[RiskLimits] = None):
        self.limits = risk_limits or RiskLimits()
        self.metrics = RiskMetrics()

        # Состояние
        self.is_emergency_stopped = False
        self.trading_blocked = False
        self.block_reason = ""

        # История
        self.risk_history: List[RiskAssessment] = []
        self.daily_reset_date = datetime.now().date()

        # Временные метрики
        self.trades_by_hour: Dict[int, int] = {}
        self.last_hour_reset = datetime.now().hour

        # Логирование
        self.logger = logging.getLogger(__name__)

        self.logger.info("🛡️ RiskManager инициализирован")
        self._reset_daily_metrics_if_needed()

    # ================= ОСНОВНЫЕ МЕТОДЫ ИНТЕРФЕЙСА =================

    async def assess_trade_risk(
        self,
        signal: TradeSignal,
        position: Optional[Position] = None
    ) -> Dict[str, Any]:
        """🔍 Оценка риска торговой операции"""

        try:
            self._reset_daily_metrics_if_needed()
            self._reset_hourly_metrics_if_needed()

            assessments = []

            # Оценка размера позиции
            position_risk = await self._assess_position_size_risk(signal, position)
            assessments.append(position_risk)

            # Оценка дневных лимитов
            daily_risk = await self._assess_daily_limits_risk(signal)
            assessments.append(daily_risk)

            # Оценка лимитов сделок
            trading_risk = await self._assess_trading_frequency_risk()
            assessments.append(trading_risk)

            # Оценка баланса
            balance_risk = await self._assess_balance_risk(signal)
            assessments.append(balance_risk)

            # Определяем общий результат
            overall_assessment = self._calculate_overall_risk(assessments)

            # Сохраняем в историю
            self.risk_history.append(overall_assessment)

            # Публикуем событие если риск высокий
            if overall_assessment.severity in [RiskSeverity.HIGH, RiskSeverity.CRITICAL]:
                await self._publish_risk_event(overall_assessment, signal)

            return {
                'risk_level': overall_assessment.severity.value,
                'risk_score': overall_assessment.score,
                'approved': overall_assessment.action == RiskAction.ALLOW,
                'assessments': [self._assessment_to_dict(a) for a in assessments],
                'overall_assessment': self._assessment_to_dict(overall_assessment),
                'recommendation': overall_assessment.recommendation
            }

        except Exception as e:
            self.logger.error(f"❌ Ошибка оценки риска: {e}")
            raise RiskManagementError(f"Ошибка оценки риска: {e}") from e

    async def should_block_trading(self, reason: Optional[str] = None) -> bool:
        """🚫 Проверка блокировки торговли"""

        # Проверяем аварийную остановку
        if self.is_emergency_stopped:
            return True

        # Проверяем ручную блокировку
        if self.trading_blocked:
            return True

        # Проверяем критические условия
        if await self._check_critical_conditions():
            return True

        return False

    async def calculate_position_size(
        self,
        signal: TradeSignal,
        available_balance: Decimal
    ) -> Decimal:
        """📐 Расчет размера позиции"""

        try:
            if signal.signal_type != StrategySignalType.BUY:
                return signal.quantity  # Для продажи возвращаем как есть

            # Получаем настройки из конфигурации
            config = get_current_config()
            if config:
                max_position_percent = config.trading.position_size_percent
            else:
                max_position_percent = self.limits.max_position_size_percent

            # Рассчитываем максимальный размер
            max_position_value = available_balance * (max_position_percent / 100)

            # Учитываем цену
            if signal.price and signal.price > 0:
                max_quantity = max_position_value / signal.price
            else:
                max_quantity = signal.quantity

            # Применяем дополнительные ограничения
            risk_factor = await self._calculate_risk_factor(signal)
            adjusted_quantity = max_quantity * Decimal(str(risk_factor))

            self.logger.debug(f"📐 Размер позиции: {adjusted_quantity} (макс: {max_quantity}, фактор: {risk_factor})")

            return min(adjusted_quantity, signal.quantity)

        except Exception as e:
            self.logger.error(f"❌ Ошибка расчета размера позиции: {e}")
            return Decimal('0')

    async def check_daily_limits(self) -> Dict[str, Any]:
        """📊 Проверка дневных лимитов"""

        self._reset_daily_metrics_if_needed()

        # Проверяем лимит потерь
        daily_loss_limit = self.metrics.current_balance * (self.limits.max_daily_loss_percent / 100)
        daily_loss_exceeded = abs(self.metrics.daily_pnl) > daily_loss_limit if self.metrics.daily_pnl < 0 else False

        # Проверяем лимит сделок
        trades_limit_exceeded = self.metrics.trades_today >= self.limits.max_trades_per_day

        return {
            'daily_pnl': str(self.metrics.daily_pnl),
            'daily_loss_limit': str(daily_loss_limit),
            'daily_loss_exceeded': daily_loss_exceeded,
            'trades_today': self.metrics.trades_today,
            'trades_limit': self.limits.max_trades_per_day,
            'trades_limit_exceeded': trades_limit_exceeded,
            'limits_ok': not (daily_loss_exceeded or trades_limit_exceeded)
        }

    async def get_risk_level(self, signal: TradeSignal) -> str:
        """⚠️ Определение уровня риска"""

        assessment = await self.assess_trade_risk(signal)
        return assessment['risk_level']

    async def emergency_stop_check(self) -> bool:
        """🚨 Проверка условий экстренной остановки"""

        # Уже в аварийном режиме
        if self.is_emergency_stopped:
            return True

        # Проверяем критические потери
        if self._check_emergency_loss_conditions():
            await self._trigger_emergency_stop("Критические потери")
            return True

        # Проверяем критическую просадку
        if self._check_emergency_drawdown_conditions():
            await self._trigger_emergency_stop("Критическая просадка")
            return True

        # Проверяем критический баланс
        if self.metrics.current_balance < self.limits.min_balance_eur:
            await self._trigger_emergency_stop("Критически низкий баланс")
            return True

        return False

    async def check_position_limits(
        self,
        new_position_size: Decimal,
        current_balance: Decimal
    ) -> bool:
        """📏 Проверка лимитов позиции"""

        max_position_value = current_balance * (self.limits.max_position_size_percent / 100)
        return new_position_size <= max_position_value

    async def should_emergency_exit(
        self,
        position: Position,
        current_price: Decimal
    ) -> Tuple[bool, str]:
        """🚨 Проверка необходимости аварийного выхода"""

        if not position or position.is_empty:
            return False, "Нет позиции"

        # Рассчитываем текущий убыток
        current_pnl = position.calculate_pnl(current_price)
        pnl_percent = position.calculate_pnl_percentage(current_price)

        # Проверяем критический убыток
        if pnl_percent <= -float(self.limits.emergency_stop_percent):
            return True, f"Критический убыток: {pnl_percent:.1f}%"

        # Проверяем время в убытке (дополнительное условие)
        if pnl_percent <= -8.0:  # 8% убыток
            time_in_loss = self._get_time_in_loss(position)
            if time_in_loss and time_in_loss > timedelta(hours=4):
                return True, f"Длительный убыток {pnl_percent:.1f}% в течение {time_in_loss}"

        return False, "Условия аварийного выхода не выполнены"

    # ================= ПРИВАТНЫЕ МЕТОДЫ ОЦЕНКИ РИСКОВ =================

    async def _assess_position_size_risk(
        self,
        signal: TradeSignal,
        position: Optional[Position]
    ) -> RiskAssessment:
        """📊 Оценка риска размера позиции"""

        if signal.signal_type != StrategySignalType.BUY:
            return RiskAssessment(
                risk_type=RiskType.POSITION_SIZE,
                severity=RiskSeverity.LOW,
                action=RiskAction.ALLOW,
                score=0.1,
                description="Продажа не увеличивает позицию",
                recommendation="Разрешено"
            )

        # Оцениваем размер новой позиции
        current_position_value = Decimal('0')
        if position and not position.is_empty:
            current_position_value = position.quantity * (signal.price or Decimal('0'))

        new_position_value = signal.quantity * (signal.price or Decimal('0'))
        total_position_value = current_position_value + new_position_value

        max_allowed = self.metrics.current_balance * (self.limits.max_position_size_percent / 100)
        position_ratio = float(total_position_value / max_allowed) if max_allowed > 0 else 1.0

        if position_ratio <= 0.5:
            return RiskAssessment(
                risk_type=RiskType.POSITION_SIZE,
                severity=RiskSeverity.LOW,
                action=RiskAction.ALLOW,
                score=position_ratio * 0.5,
                description=f"Размер позиции {position_ratio:.1%} от лимита",
                recommendation="Разрешено"
            )
        elif position_ratio <= 0.8:
            return RiskAssessment(
                risk_type=RiskType.POSITION_SIZE,
                severity=RiskSeverity.MEDIUM,
                action=RiskAction.WARN,
                score=position_ratio * 0.7,
                description=f"Размер позиции {position_ratio:.1%} от лимита",
                recommendation="Предупреждение о размере позиции"
            )
        elif position_ratio <= 1.0:
            return RiskAssessment(
                risk_type=RiskType.POSITION_SIZE,
                severity=RiskSeverity.HIGH,
                action=RiskAction.LIMIT,
                score=position_ratio * 0.9,
                description=f"Размер позиции {position_ratio:.1%} от лимита",
                recommendation="Ограничить размер позиции"
            )
        else:
            return RiskAssessment(
                risk_type=RiskType.POSITION_SIZE,
                severity=RiskSeverity.CRITICAL,
                action=RiskAction.BLOCK,
                score=1.0,
                description=f"Размер позиции {position_ratio:.1%} превышает лимит",
                recommendation="Заблокировать операцию"
            )

    async def _assess_daily_limits_risk(self, signal: TradeSignal) -> RiskAssessment:
        """📅 Оценка риска дневных лимитов"""

        # Проверяем дневные потери
        if self.metrics.daily_pnl < 0:
            daily_loss_limit = self.metrics.current_balance * (self.limits.max_daily_loss_percent / 100)
            loss_ratio = float(abs(self.metrics.daily_pnl) / daily_loss_limit) if daily_loss_limit > 0 else 0

            if loss_ratio >= 1.0:
                return RiskAssessment(
                    risk_type=RiskType.DAILY_LOSS,
                    severity=RiskSeverity.CRITICAL,
                    action=RiskAction.BLOCK,
                    score=1.0,
                    description=f"Дневные потери {loss_ratio:.1%} от лимита",
                    recommendation="Остановить торговлю на сегодня"
                )
            elif loss_ratio >= 0.8:
                return RiskAssessment(
                    risk_type=RiskType.DAILY_LOSS,
                    severity=RiskSeverity.HIGH,
                    action=RiskAction.WARN,
                    score=loss_ratio,
                    description=f"Дневные потери {loss_ratio:.1%} от лимита",
                    recommendation="Осторожность с новыми сделками"
                )

        return RiskAssessment(
            risk_type=RiskType.DAILY_LOSS,
            severity=RiskSeverity.LOW,
            action=RiskAction.ALLOW,
            score=0.1,
            description="Дневные лимиты в норме",
            recommendation="Разрешено"
        )

    async def _assess_trading_frequency_risk(self) -> RiskAssessment:
        """⏰ Оценка риска частоты торговли"""

        # Проверяем часовой лимит
        current_hour = datetime.now().hour
        trades_this_hour = self.trades_by_hour.get(current_hour, 0)

        if trades_this_hour >= self.limits.max_trades_per_hour:
            return RiskAssessment(
                risk_type=RiskType.LIQUIDITY,
                severity=RiskSeverity.HIGH,
                action=RiskAction.BLOCK,
                score=0.9,
                description=f"Превышен лимит сделок в час: {trades_this_hour}",
                recommendation="Подождать до следующего часа"
            )

        # Проверяем дневной лимит
        if self.metrics.trades_today >= self.limits.max_trades_per_day:
            return RiskAssessment(
                risk_type=RiskType.LIQUIDITY,
                severity=RiskSeverity.CRITICAL,
                action=RiskAction.BLOCK,
                score=1.0,
                description=f"Превышен дневной лимит сделок: {self.metrics.trades_today}",
                recommendation="Остановить торговлю на сегодня"
            )

        return RiskAssessment(
            risk_type=RiskType.LIQUIDITY,
            severity=RiskSeverity.LOW,
            action=RiskAction.ALLOW,
            score=0.1,
            description="Частота торговли в норме",
            recommendation="Разрешено"
        )

    async def _assess_balance_risk(self, signal: TradeSignal) -> RiskAssessment:
        """💰 Оценка риска баланса"""

        if self.metrics.current_balance < self.limits.min_balance_eur:
            return RiskAssessment(
                risk_type=RiskType.LIQUIDITY,
                severity=RiskSeverity.CRITICAL,
                action=RiskAction.EMERGENCY_EXIT,
                score=1.0,
                description=f"Критически низкий баланс: {self.metrics.current_balance}",
                recommendation="Аварийное закрытие позиций"
            )

        # Проверяем достаточность средств для покупки
        if signal.signal_type == StrategySignalType.BUY:
            required_amount = signal.quantity * (signal.price or Decimal('0'))
            if required_amount > self.metrics.current_balance:
                return RiskAssessment(
                    risk_type=RiskType.LIQUIDITY,
                    severity=RiskSeverity.HIGH,
                    action=RiskAction.BLOCK,
                    score=0.8,
                    description=f"Недостаточно средств: нужно {required_amount}, есть {self.metrics.current_balance}",
                    recommendation="Уменьшить размер позиции"
                )

        return RiskAssessment(
            risk_type=RiskType.LIQUIDITY,
            severity=RiskSeverity.LOW,
            action=RiskAction.ALLOW,
            score=0.1,
            description="Баланс достаточен",
            recommendation="Разрешено"
        )

    def _calculate_overall_risk(self, assessments: List[RiskAssessment]) -> RiskAssessment:
        """🎯 Расчет общего риска"""

        if not assessments:
            return RiskAssessment(
                risk_type=RiskType.POSITION_SIZE,
                severity=RiskSeverity.MEDIUM,
                action=RiskAction.WARN,
                score=0.5,
                description="Нет данных для оценки",
                recommendation="Требуется дополнительный анализ"
            )

        # Находим максимальный риск
        max_severity = max(a.severity for a in assessments)
        max_score = max(a.score for a in assessments)

        # Определяем действие на основе критичных оценок
        critical_assessments = [a for a in assessments if a.requires_action]

        if any(a.action == RiskAction.EMERGENCY_EXIT for a in critical_assessments):
            action = RiskAction.EMERGENCY_EXIT
        elif any(a.action == RiskAction.BLOCK for a in critical_assessments):
            action = RiskAction.BLOCK
        elif any(a.action == RiskAction.LIMIT for a in critical_assessments):
            action = RiskAction.LIMIT
        elif any(a.action == RiskAction.WARN for a in assessments):
            action = RiskAction.WARN
        else:
            action = RiskAction.ALLOW

        # Формируем описание
        critical_descriptions = [a.description for a in critical_assessments]
        description = "; ".join(critical_descriptions) if critical_descriptions else "Общая оценка рисков"

        return RiskAssessment(
            risk_type=RiskType.POSITION_SIZE,  # Общий тип
            severity=max_severity,
            action=action,
            score=max_score,
            description=description,
            recommendation=self._get_recommendation_for_action(action),
            metadata={'individual_assessments': len(assessments)}
        )

    # ================= ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ =================

    async def _calculate_risk_factor(self, signal: TradeSignal) -> float:
        """🎯 Расчет фактора риска для позиции"""

        base_factor = 1.0

        # Уменьшаем при высокой волатильности
        if hasattr(signal, 'metadata') and 'volatility' in signal.metadata:
            volatility = signal.metadata['volatility']
            if volatility > 0.05:  # 5% волатильность
                base_factor *= 0.7

        # Уменьшаем при низкой уверенности
        if signal.confidence < 0.7:
            base_factor *= signal.confidence

        # Уменьшаем при дневных потерях
        if self.metrics.daily_pnl < 0:
            loss_factor = 1.0 - min(abs(float(self.metrics.daily_pnl)) / float(self.metrics.current_balance), 0.3)
            base_factor *= loss_factor

        return max(base_factor, 0.1)  # Минимум 10%

    async def _check_critical_conditions(self) -> bool:
        """🚨 Проверка критических условий"""

        # Проверяем аварийные условия
        if await self.emergency_stop_check():
            return True

        # Проверяем критическую частоту ошибок
        if len(self.risk_history) >= 10:
            recent_risks = self.risk_history[-10:]
            critical_count = sum(1 for risk in recent_risks if risk.is_critical)
            if critical_count >= 5:  # 50% критических рисков
                self.logger.warning("🚨 Высокая частота критических рисков")
                return True

        return False

    def _check_emergency_loss_conditions(self) -> bool:
        """💸 Проверка критических потерь"""

        if self.metrics.current_balance <= 0:
            return True

        # Проверяем дневные потери
        daily_loss_threshold = self.metrics.current_balance * (self.limits.emergency_stop_percent / 100)
        if self.metrics.daily_pnl < -daily_loss_threshold:
            return True

        return False

    def _check_emergency_drawdown_conditions(self) -> bool:
        """📉 Проверка критической просадки"""

        drawdown_threshold = self.limits.max_drawdown_percent / 100
        return float(self.metrics.max_drawdown) >= drawdown_threshold

    async def _trigger_emergency_stop(self, reason: str) -> None:
        """🚨 Активация аварийной остановки"""

        if not self.is_emergency_stopped:
            self.is_emergency_stopped = True
            self.metrics.emergency_stops_today += 1

            self.logger.critical(f"🚨 АВАРИЙНАЯ ОСТАНОВКА: {reason}")

            # Публикуем событие
            await self._publish_emergency_event(reason)

            # Блокируем торговлю
            self.trading_blocked = True
            self.block_reason = f"Emergency stop: {reason}"

    def _get_time_in_loss(self, position: Position) -> Optional[timedelta]:
        """⏰ Получение времени нахождения в убытке"""

        # Здесь должна быть логика отслеживания времени убытка
        # Для упрощения возвращаем None
        # В реальной реализации нужно отслеживать когда позиция стала убыточной
        return None

    def _reset_daily_metrics_if_needed(self) -> None:
        """🔄 Сброс дневных метрик при необходимости"""

        current_date = datetime.now().date()
        if current_date != self.daily_reset_date:
            self.logger.info(f"🔄 Сброс дневных метрик: {self.daily_reset_date} -> {current_date}")

            self.metrics.daily_pnl = Decimal('0')
            self.metrics.trades_today = 0
            self.metrics.emergency_stops_today = 0
            self.daily_reset_date = current_date

    def _reset_hourly_metrics_if_needed(self) -> None:
        """🔄 Сброс часовых метрик при необходимости"""

        current_hour = datetime.now().hour
        if current_hour != self.last_hour_reset:
            # Очищаем старые часы (оставляем только текущий и предыдущий)
            hours_to_keep = [current_hour, (current_hour - 1) % 24]
            self.trades_by_hour = {h: count for h, count in self.trades_by_hour.items() if h in hours_to_keep}

            self.last_hour_reset = current_hour

    def _assessment_to_dict(self, assessment: RiskAssessment) -> Dict[str, Any]:
        """📤 Конвертация оценки риска в словарь"""

        return {
            'risk_type': assessment.risk_type.value,
            'severity': assessment.severity.value,
            'action': assessment.action.value,
            'score': assessment.score,
            'description': assessment.description,
            'recommendation': assessment.recommendation,
            'metadata': assessment.metadata
        }

    async def _publish_risk_event(self, assessment: RiskAssessment, signal: TradeSignal) -> None:
        """📡 Публикация события риска"""

        try:
            event = DomainEvent()
            event.event_type = "risk_assessment"
            event.source = "risk_manager"
            event.metadata = {
                'risk_type': assessment.risk_type.value,
                'severity': assessment.severity.value,
                'action': assessment.action.value,
                'score': assessment.score,
                'signal_type': signal.signal_type if hasattr(signal, 'signal_type') else 'unknown',
                'strategy': signal.strategy_name if hasattr(signal, 'strategy_name') else 'unknown'
            }

            await publish_event(event)

        except Exception as e:
            self.logger.error(f"❌ Ошибка публикации события риска: {e}")

    async def _publish_emergency_event(self, reason: str) -> None:
        """🚨 Публикация события аварийной остановки"""

        try:
            event = DomainEvent()
            event.event_type = "emergency_stop"
            event.source = "risk_manager"
            event.metadata = {
                'reason': reason,
                'current_balance': str(self.metrics.current_balance),
                'daily_pnl': str(self.metrics.daily_pnl),
                'trades_today': self.metrics.trades_today
            }

            await publish_event(event)

        except Exception as e:
            self.logger.error(f"❌ Ошибка публикации события аварийной остановки: {e}")

    def _get_recommendation_for_action(self, action: RiskAction) -> str:
        """💡 Получение рекомендации для действия"""
        recommendations = {
            RiskAction.ALLOW: "Операция разрешена",
            RiskAction.WARN: "Рекомендуется осторожность",
            RiskAction.LIMIT: "Рекомендуется ограничить размер операции",
            RiskAction.BLOCK: "Операция заблокирована",
            RiskAction.EMERGENCY_EXIT: "Требуется аварийное закрытие позиций"
        }
        return recommendations.get(action, "Неизвестное действие")

    # ================= ПУБЛИЧНЫЕ МЕТОДЫ УПРАВЛЕНИЯ =================

    def update_balance(self, new_balance: Decimal) -> None:
        """💰 Обновление текущего баланса"""
        old_balance = self.metrics.current_balance
        self.metrics.current_balance = new_balance

        # Обновляем дневный P&L
        if old_balance > 0:
            balance_change = new_balance - old_balance
            self.metrics.daily_pnl += balance_change

        self.logger.debug(f"💰 Баланс обновлен: {old_balance} -> {new_balance}")

    def record_trade(self, pnl: Decimal) -> None:
        """📝 Запись результата сделки"""

        self._reset_daily_metrics_if_needed()
        self._reset_hourly_metrics_if_needed()

        # Обновляем метрики
        self.metrics.trades_today += 1
        self.metrics.last_trade_time = datetime.now()

        # Обновляем часовую статистику
        current_hour = datetime.now().hour
        self.trades_by_hour[current_hour] = self.trades_by_hour.get(current_hour, 0) + 1

        # Обновляем P&L
        self.metrics.daily_pnl += pnl
        self.metrics.total_pnl += pnl

        # Обновляем максимальную просадку
        if pnl < 0:
            current_drawdown = abs(pnl) / self.metrics.current_balance if self.metrics.current_balance > 0 else Decimal('0')
            self.metrics.max_drawdown = max(self.metrics.max_drawdown, current_drawdown)

        self.logger.debug(f"📝 Записана сделка: P&L {pnl}, всего сегодня {self.metrics.trades_today}")

    def manual_emergency_stop(self, reason: str = "Manual stop") -> None:
        """🚨 Ручная аварийная остановка"""

        self.logger.warning(f"🚨 Ручная аварийная остановка: {reason}")
        self.is_emergency_stopped = True
        self.trading_blocked = True
        self.block_reason = reason
        self.metrics.emergency_stops_today += 1

    def reset_emergency_stop(self, reason: str = "Manual reset") -> None:
        """🔄 Сброс аварийной остановки"""

        if self.is_emergency_stopped:
            self.logger.info(f"🔄 Сброс аварийной остановки: {reason}")
            self.is_emergency_stopped = False
            self.trading_blocked = False
            self.block_reason = ""

    def get_risk_statistics(self) -> Dict[str, Any]:
        """📊 Получение статистики рисков"""

        return {
            'metrics': {
                'current_balance': str(self.metrics.current_balance),
                'daily_pnl': str(self.metrics.daily_pnl),
                'total_pnl': str(self.metrics.total_pnl),
                'daily_return_percent': self.metrics.daily_return_percent,
                'max_drawdown': str(self.metrics.max_drawdown),
                'trades_today': self.metrics.trades_today,
                'trades_this_hour': self.trades_by_hour.get(datetime.now().hour, 0),
                'emergency_stops_today': self.metrics.emergency_stops_today,
                'portfolio_value': str(self.metrics.portfolio_value)
            },
            'status': {
                'is_emergency_stopped': self.is_emergency_stopped,
                'trading_blocked': self.trading_blocked,
                'block_reason': self.block_reason
            },
            'limits': {
                'max_position_size_percent': str(self.limits.max_position_size_percent),
                'max_daily_loss_percent': str(self.limits.max_daily_loss_percent),
                'emergency_stop_percent': str(self.limits.emergency_stop_percent),
                'max_trades_per_hour': self.limits.max_trades_per_hour,
                'max_trades_per_day': self.limits.max_trades_per_day
            },
            'recent_assessments': [
                self._assessment_to_dict(assessment)
                for assessment in self.risk_history[-5:]  # Последние 5 оценок
            ]
        }
