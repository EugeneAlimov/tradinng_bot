from typing import Optional, List, Dict, Any, Tuple
from decimal import Decimal
from datetime import datetime, timedelta
import logging
from dataclasses import dataclass, field
from enum import Enum
import asyncio

# Импорты из Core слоя
try:
    from ...core.interfaces import IEmergencyExitStrategy, ITradeExecutor, IPositionManager, IRiskManager
    from ...core.models import (
        Position, TradeSignal, OrderResult, TradingPair,
        StrategySignalType, RiskLevel
    )
    from ...core.exceptions import (
        EmergencyStopError, TradingError, RiskManagementError,
        PositionError, ValidationError
    )
    from ...core.events import DomainEvent, publish_event
    from ...config.settings import get_current_config
except ImportError:
    # Fallback для случая если Core слой еще не готов
    class IEmergencyExitStrategy: pass
    class ITradeExecutor: pass
    class IPositionManager: pass
    class IRiskManager: pass
    class Position: pass
    class TradeSignal: pass
    class OrderResult: pass
    class TradingPair: pass
    class StrategySignalType: pass
    class RiskLevel: pass
    class EmergencyStopError(Exception): pass
    class TradingError(Exception): pass
    class RiskManagementError(Exception): pass
    class PositionError(Exception): pass
    class ValidationError(Exception): pass
    class DomainEvent: pass
    def publish_event(event): pass
    def get_current_config(): return None


# ================= ТИПЫ АВАРИЙНЫХ ВЫХОДОВ =================

class EmergencyTrigger(Enum):
    """🚨 Триггеры аварийного выхода"""
    STOP_LOSS = "stop_loss"                    # Стоп-лосс
    DRAWDOWN_LIMIT = "drawdown_limit"          # Лимит просадки
    DAILY_LOSS_LIMIT = "daily_loss_limit"      # Дневной лимит убытков
    POSITION_LOSS = "position_loss"            # Убыток по позиции
    MARKET_CRASH = "market_crash"              # Обвал рынка
    CORRELATION_SPIKE = "correlation_spike"    # Всплеск корреляции
    LIQUIDITY_CRISIS = "liquidity_crisis"      # Кризис ликвидности
    MANUAL_TRIGGER = "manual_trigger"          # Ручной триггер
    SYSTEM_ERROR = "system_error"              # Системная ошибка


class EmergencyLevel(Enum):
    """📊 Уровни аварийности"""
    YELLOW = "yellow"      # Предупреждение
    ORANGE = "orange"      # Повышенная готовность
    RED = "red"           # Критическая ситуация
    BLACK = "black"       # Катастрофа


class ExitStrategy(Enum):
    """🎯 Стратегии выхода"""
    IMMEDIATE = "immediate"            # Немедленный выход
    GRADUAL = "gradual"               # Постепенный выход
    SELECTIVE = "selective"           # Селективный выход
    PARTIAL = "partial"               # Частичный выход
    HOLD_AND_MONITOR = "hold_monitor" # Удержание с мониторингом


@dataclass
class EmergencyCondition:
    """⚠️ Условие аварийного выхода"""
    id: str
    trigger: EmergencyTrigger
    level: EmergencyLevel
    threshold_value: Decimal
    current_value: Decimal
    description: str
    is_active: bool = True
    cooldown_minutes: int = 30
    last_triggered: Optional[datetime] = None

    @property
    def is_triggered(self) -> bool:
        """Сработало ли условие"""
        if not self.is_active:
            return False

        # Проверяем cooldown
        if self.last_triggered:
            cooldown_period = timedelta(minutes=self.cooldown_minutes)
            if datetime.now() - self.last_triggered < cooldown_period:
                return False

        # Проверяем превышение порога
        return self.current_value >= self.threshold_value

    @property
    def severity_score(self) -> float:
        """Оценка серьезности (0-100)"""
        if self.threshold_value <= 0:
            return 0.0

        ratio = float(self.current_value / self.threshold_value)

        # Масштабируем в зависимости от уровня
        level_multipliers = {
            EmergencyLevel.YELLOW: 25,
            EmergencyLevel.ORANGE: 50,
            EmergencyLevel.RED: 75,
            EmergencyLevel.BLACK: 100
        }

        base_score = level_multipliers.get(self.level, 50)
        return min(base_score * ratio, 100.0)


@dataclass
class EmergencyAction:
    """🎯 Аварийное действие"""
    id: str
    trigger: EmergencyTrigger
    strategy: ExitStrategy
    target_positions: List[str]  # Валюты для выхода
    exit_percentage: float       # Процент позиции для выхода
    priority: int               # Приоритет исполнения
    max_slippage: Decimal       # Максимальный слиппаж
    timeout_seconds: int        # Таймаут исполнения
    description: str
    created_at: datetime = field(default_factory=datetime.now)
    executed_at: Optional[datetime] = None
    is_executed: bool = False
    execution_results: List[OrderResult] = field(default_factory=list)

    @property
    def execution_time_seconds(self) -> Optional[float]:
        """Время исполнения в секундах"""
        if self.executed_at:
            return (self.executed_at - self.created_at).total_seconds()
        return None


@dataclass
class MarketConditions:
    """📊 Рыночные условия"""
    btc_change_24h: Decimal = Decimal('0')
    market_fear_index: int = 50  # 0-100
    volume_spike_ratio: Decimal = Decimal('1')
    correlation_to_btc: Decimal = Decimal('0')
    liquidity_score: Decimal = Decimal('100')
    volatility_index: Decimal = Decimal('0')

    def get_danger_level(self) -> EmergencyLevel:
        """Определение уровня опасности рынка"""
        danger_score = 0

        # BTC падение
        if self.btc_change_24h < Decimal('-10'):
            danger_score += 30
        elif self.btc_change_24h < Decimal('-5'):
            danger_score += 15

        # Индекс страха
        if self.market_fear_index < 20:
            danger_score += 25
        elif self.market_fear_index < 40:
            danger_score += 10

        # Ликвидность
        if self.liquidity_score < 30:
            danger_score += 25
        elif self.liquidity_score < 60:
            danger_score += 10

        # Волатильность
        if self.volatility_index > Decimal('50'):
            danger_score += 20

        if danger_score >= 70:
            return EmergencyLevel.BLACK
        elif danger_score >= 50:
            return EmergencyLevel.RED
        elif danger_score >= 30:
            return EmergencyLevel.ORANGE
        else:
            return EmergencyLevel.YELLOW


# ================= ОСНОВНОЙ СЕРВИС =================

class EmergencyExitService(IEmergencyExitStrategy):
    """🚨 Сервис аварийного выхода"""

    def __init__(
        self,
        trade_executor: ITradeExecutor,
        position_manager: IPositionManager,
        risk_manager: IRiskManager
    ):
        self.trade_executor = trade_executor
        self.position_manager = position_manager
        self.risk_manager = risk_manager

        # Условия аварийного выхода
        self.emergency_conditions: Dict[str, EmergencyCondition] = {}

        # История аварийных действий
        self.emergency_history: List[EmergencyAction] = []

        # Состояние системы
        self.is_emergency_active = False
        self.emergency_level = EmergencyLevel.YELLOW
        self.last_market_check = datetime.now()

        # Настройки
        self.max_concurrent_exits = 5
        self.default_exit_timeout = 30  # секунд
        self.market_check_interval = timedelta(minutes=1)

        # Логирование
        self.logger = logging.getLogger(__name__)

        # Инициализация условий по умолчанию
        self._initialize_default_conditions()

        self.logger.info("🚨 EmergencyExitService инициализирован")

    # ================= ОСНОВНЫЕ МЕТОДЫ ИНТЕРФЕЙСА =================

    async def assess_emergency_conditions(
        self,
        position: Position,
        current_price: Decimal,
        market_data: Dict[str, Any]
    ) -> Tuple[bool, str, float]:
        """🔍 Оценка аварийных условий"""

        try:
            # Обновляем рыночные условия
            market_conditions = self._parse_market_data(market_data)

            # Обновляем условия на основе позиции
            await self._update_position_conditions(position, current_price)

            # Обновляем рыночные условия
            await self._update_market_conditions(market_conditions)

            # Проверяем все условия
            triggered_conditions = []
            max_severity = 0.0

            for condition in self.emergency_conditions.values():
                if condition.is_triggered:
                    triggered_conditions.append(condition)
                    max_severity = max(max_severity, condition.severity_score)

            if triggered_conditions:
                # Определяем процент выхода на основе серьезности
                exit_percentage = self._calculate_exit_percentage(max_severity)

                # Формируем описание причин
                reasons = [cond.description for cond in triggered_conditions]
                reason_text = "; ".join(reasons)

                self.logger.warning(f"🚨 Аварийные условия сработали: {reason_text}")

                return True, reason_text, exit_percentage

            return False, "Аварийные условия не выполнены", 0.0

        except Exception as e:
            self.logger.error(f"❌ Ошибка оценки аварийных условий: {e}")
            return True, f"Ошибка оценки: {e}", 100.0  # В случае ошибки - полный выход

    async def get_exit_price(
        self,
        position: Position,
        current_price: Decimal
    ) -> Decimal:
        """💰 Получение цены выхода"""

        try:
            # Получаем настройки из конфигурации
            config = get_current_config()

            if config and hasattr(config, 'emergency'):
                max_slippage = config.emergency.max_slippage_percent / 100
            else:
                max_slippage = Decimal('0.02')  # 2% по умолчанию

            # Для аварийного выхода применяем слиппаж в худшую сторону
            emergency_price = current_price * (Decimal('1') - max_slippage)

            self.logger.debug(f"💰 Аварийная цена выхода: {emergency_price} (слиппаж: {max_slippage*100}%)")

            return emergency_price

        except Exception as e:
            self.logger.error(f"❌ Ошибка расчета цены выхода: {e}")
            # В случае ошибки возвращаем цену с 5% слиппажем
            return current_price * Decimal('0.95')

    async def execute_emergency_exit(
        self,
        positions: List[Position],
        trigger: EmergencyTrigger,
        exit_percentage: float = 100.0
    ) -> List[OrderResult]:
        """🚨 Исполнение аварийного выхода"""

        try:
            self.logger.critical(f"🚨 НАЧИНАЕТСЯ АВАРИЙНЫЙ ВЫХОД: {trigger.value}")

            # Активируем аварийный режим
            self.is_emergency_active = True

            # Создаем аварийное действие
            action = EmergencyAction(
                id=f"emergency_{datetime.now().timestamp()}",
                trigger=trigger,
                strategy=ExitStrategy.IMMEDIATE,
                target_positions=[pos.currency for pos in positions],
                exit_percentage=exit_percentage,
                priority=1,
                max_slippage=Decimal('0.05'),  # 5% максимальный слиппаж
                timeout_seconds=self.default_exit_timeout,
                description=f"Emergency exit triggered by {trigger.value}"
            )

            # Исполняем выход для каждой позиции
            results = []

            for position in positions:
                try:
                    result = await self._execute_position_exit(position, action)
                    if result:
                        results.append(result)
                        action.execution_results.append(result)

                except Exception as e:
                    self.logger.error(f"❌ Ошибка выхода из позиции {position.currency}: {e}")
                    continue

            # Завершаем действие
            action.executed_at = datetime.now()
            action.is_executed = True
            self.emergency_history.append(action)

            # Публикуем событие
            await self._publish_emergency_event(action, results)

            self.logger.critical(f"🚨 АВАРИЙНЫЙ ВЫХОД ЗАВЕРШЕН: {len(results)} позиций закрыто")

            return results

        except Exception as e:
            self.logger.critical(f"🚨 КРИТИЧЕСКАЯ ОШИБКА АВАРИЙНОГО ВЫХОДА: {e}")
            raise EmergencyStopError(f"Emergency exit failed: {e}")
        finally:
            self.is_emergency_active = False

    async def check_system_health(self) -> Dict[str, Any]:
        """🏥 Проверка состояния системы"""

        try:
            health_status = {
                'is_emergency_active': self.is_emergency_active,
                'emergency_level': self.emergency_level.value,
                'active_conditions': len([c for c in self.emergency_conditions.values() if c.is_active]),
                'triggered_conditions': len([c for c in self.emergency_conditions.values() if c.is_triggered]),
                'last_emergency': None,
                'system_status': 'healthy'
            }

            # Информация о последнем аварийном выходе
            if self.emergency_history:
                last_emergency = self.emergency_history[-1]
                health_status['last_emergency'] = {
                    'trigger': last_emergency.trigger.value,
                    'executed_at': last_emergency.executed_at.isoformat() if last_emergency.executed_at else None,
                    'positions_affected': len(last_emergency.target_positions),
                    'success_rate': len(last_emergency.execution_results) / len(last_emergency.target_positions) if last_emergency.target_positions else 0
                }

            # Определяем общий статус системы
            triggered_count = health_status['triggered_conditions']

            if triggered_count >= 3:
                health_status['system_status'] = 'critical'
            elif triggered_count >= 2:
                health_status['system_status'] = 'warning'
            elif triggered_count >= 1:
                health_status['system_status'] = 'caution'

            return health_status

        except Exception as e:
            self.logger.error(f"❌ Ошибка проверки состояния системы: {e}")
            return {
                'system_status': 'error',
                'error': str(e),
                'is_emergency_active': self.is_emergency_active
            }

    # ================= УПРАВЛЕНИЕ УСЛОВИЯМИ =================

    def add_emergency_condition(self, condition: EmergencyCondition) -> bool:
        """➕ Добавление условия аварийного выхода"""

        try:
            self.emergency_conditions[condition.id] = condition

            self.logger.info(f"➕ Добавлено условие аварийного выхода: {condition.id}")
            return True

        except Exception as e:
            self.logger.error(f"❌ Ошибка добавления условия: {e}")
            return False

    def remove_emergency_condition(self, condition_id: str) -> bool:
        """➖ Удаление условия аварийного выхода"""

        try:
            if condition_id in self.emergency_conditions:
                del self.emergency_conditions[condition_id]
                self.logger.info(f"➖ Удалено условие: {condition_id}")
                return True

            return False

        except Exception as e:
            self.logger.error(f"❌ Ошибка удаления условия: {e}")
            return False

    def activate_condition(self, condition_id: str) -> bool:
        """🔛 Активация условия"""

        if condition_id in self.emergency_conditions:
            self.emergency_conditions[condition_id].is_active = True
            self.logger.info(f"🔛 Активировано условие: {condition_id}")
            return True

        return False

    def deactivate_condition(self, condition_id: str) -> bool:
        """🔚 Деактивация условия"""

        if condition_id in self.emergency_conditions:
            self.emergency_conditions[condition_id].is_active = False
            self.logger.info(f"🔚 Деактивировано условие: {condition_id}")
            return True

        return False

    # ================= ПРИВАТНЫЕ МЕТОДЫ =================

    def _initialize_default_conditions(self) -> None:
        """🔧 Инициализация условий по умолчанию"""

        default_conditions = [
            EmergencyCondition(
                id="daily_loss_limit",
                trigger=EmergencyTrigger.DAILY_LOSS_LIMIT,
                level=EmergencyLevel.RED,
                threshold_value=Decimal('500'),  # 500 EUR дневной убыток
                current_value=Decimal('0'),
                description="Превышен дневной лимит убытков",
                cooldown_minutes=60
            ),

            EmergencyCondition(
                id="position_loss_20",
                trigger=EmergencyTrigger.POSITION_LOSS,
                level=EmergencyLevel.ORANGE,
                threshold_value=Decimal('20'),  # 20% убыток по позиции
                current_value=Decimal('0'),
                description="Убыток по позиции превысил 20%",
                cooldown_minutes=30
            ),

            EmergencyCondition(
                id="position_loss_30",
                trigger=EmergencyTrigger.POSITION_LOSS,
                level=EmergencyLevel.RED,
                threshold_value=Decimal('30'),  # 30% убыток по позиции
                current_value=Decimal('0'),
                description="Критический убыток по позиции 30%",
                cooldown_minutes=15
            ),

            EmergencyCondition(
                id="market_crash",
                trigger=EmergencyTrigger.MARKET_CRASH,
                level=EmergencyLevel.BLACK,
                threshold_value=Decimal('15'),  # BTC падение на 15%
                current_value=Decimal('0'),
                description="Обвал рынка - BTC падение >15%",
                cooldown_minutes=180
            )
        ]

        for condition in default_conditions:
            self.emergency_conditions[condition.id] = condition

    async def _execute_position_exit(
        self,
        position: Position,
        action: EmergencyAction
    ) -> Optional[OrderResult]:
        """🏃 Исполнение выхода из позиции"""

        try:
            # Рассчитываем количество для продажи
            exit_quantity = position.quantity * Decimal(str(action.exit_percentage / 100))

            if exit_quantity <= 0:
                return None

            # Получаем цену выхода
            current_price = Decimal('0.1')  # Заглушка - должна быть получена от market data
            exit_price = current_price * (Decimal('1') - action.max_slippage)

            # Создаем сигнал для аварийного выхода
            emergency_signal = TradeSignal(
                signal_type=StrategySignalType.EMERGENCY_EXIT,
                pair=TradingPair(position.currency, 'EUR'),
                quantity=exit_quantity,
                price=exit_price,
                confidence=1.0,
                strategy_name="emergency_exit",
                reason=action.description,
                risk_level=RiskLevel.CRITICAL
            )

            # Исполняем через trade executor
            result = await self.trade_executor.execute_signal(emergency_signal)

            self.logger.warning(f"🏃 Аварийный выход из {position.currency}: {exit_quantity}")

            return result

        except Exception as e:
            self.logger.error(f"❌ Ошибка выхода из позиции {position.currency}: {e}")
            return None

    async def _update_position_conditions(
        self,
        position: Position,
        current_price: Decimal
    ) -> None:
        """📊 Обновление условий на основе позиции"""

        try:
            # Рассчитываем P&L процент
            pnl_percent = position.calculate_pnl_percentage(current_price)

            # Обновляем условия убытка по позиции
            for condition in self.emergency_conditions.values():
                if condition.trigger == EmergencyTrigger.POSITION_LOSS:
                    condition.current_value = Decimal(str(abs(pnl_percent))) if pnl_percent < 0 else Decimal('0')

        except Exception as e:
            self.logger.error(f"❌ Ошибка обновления условий позиции: {e}")

    async def _update_market_conditions(self, market_conditions: MarketConditions) -> None:
        """📈 Обновление рыночных условий"""

        try:
            # Обновляем рыночные триггеры
            for condition in self.emergency_conditions.values():
                if condition.trigger == EmergencyTrigger.MARKET_CRASH:
                    condition.current_value = abs(market_conditions.btc_change_24h)

            # Обновляем общий уровень аварийности
            self.emergency_level = market_conditions.get_danger_level()

        except Exception as e:
            self.logger.error(f"❌ Ошибка обновления рыночных условий: {e}")

    def _parse_market_data(self, market_data: Dict[str, Any]) -> MarketConditions:
        """📊 Парсинг рыночных данных"""

        return MarketConditions(
            btc_change_24h=Decimal(str(market_data.get('btc_change_24h', 0))),
            market_fear_index=market_data.get('fear_index', 50),
            volume_spike_ratio=Decimal(str(market_data.get('volume_spike', 1))),
            correlation_to_btc=Decimal(str(market_data.get('btc_correlation', 0))),
            liquidity_score=Decimal(str(market_data.get('liquidity', 100))),
            volatility_index=Decimal(str(market_data.get('volatility', 0)))
        )

    def _calculate_exit_percentage(self, severity_score: float) -> float:
        """📊 Расчет процента выхода на основе серьезности"""

        if severity_score >= 90:
            return 100.0  # Полный выход
        elif severity_score >= 75:
            return 75.0   # 75% выход
        elif severity_score >= 50:
            return 50.0   # Половина позиции
        elif severity_score >= 25:
            return 25.0   # Четверть позиции
        else:
            return 10.0   # Минимальный выход

    async def _publish_emergency_event(
        self,
        action: EmergencyAction,
        results: List[OrderResult]
    ) -> None:
        """📡 Публикация события аварийного выхода"""

        try:
            event = DomainEvent()
            event.event_type = "emergency_exit_executed"
            event.source = "emergency_exit_service"
            event.metadata = {
                'trigger': action.trigger.value,
                'strategy': action.strategy.value,
                'positions_count': len(action.target_positions),
                'exit_percentage': action.exit_percentage,
                'successful_exits': len(results),
                'execution_time': action.execution_time_seconds,
                'description': action.description
            }

            await publish_event(event)

        except Exception as e:
            self.logger.error(f"❌ Ошибка публикации события: {e}")

    # ================= МОНИТОРИНГ И СТАТИСТИКА =================

    def get_emergency_statistics(self) -> Dict[str, Any]:
        """📊 Статистика аварийных выходов"""

        try:
            total_emergencies = len(self.emergency_history)
            successful_emergencies = len([a for a in self.emergency_history if a.is_executed])

            # Статистика по триггерам
            trigger_stats = {}
            for action in self.emergency_history:
                trigger = action.trigger.value
                trigger_stats[trigger] = trigger_stats.get(trigger, 0) + 1

            # Средний процент выхода
            avg_exit_percentage = 0.0
            if self.emergency_history:
                avg_exit_percentage = sum(a.exit_percentage for a in self.emergency_history) / len(self.emergency_history)

            return {
                'total_emergencies': total_emergencies,
                'successful_emergencies': successful_emergencies,
                'success_rate': (successful_emergencies / total_emergencies * 100) if total_emergencies > 0 else 0,
                'trigger_statistics': trigger_stats,
                'average_exit_percentage': avg_exit_percentage,
                'active_conditions': len([c for c in self.emergency_conditions.values() if c.is_active]),
                'current_emergency_level': self.emergency_level.value,
                'last_emergency': (
                    self.emergency_history[-1].executed_at.isoformat()
                    if self.emergency_history and self.emergency_history[-1].executed_at else None
                )
            }

        except Exception as e:
            self.logger.error(f"❌ Ошибка получения статистики: {e}")
            return {}

    def get_conditions_status(self) -> List[Dict[str, Any]]:
        """📋 Статус всех условий"""

        conditions_status = []

        for condition in self.emergency_conditions.values():
            conditions_status.append({
                'id': condition.id,
                'trigger': condition.trigger.value,
                'level': condition.level.value,
                'is_active': condition.is_active,
                'is_triggered': condition.is_triggered,
                'threshold': str(condition.threshold_value),
                'current': str(condition.current_value),
                'severity_score': condition.severity_score,
                'description': condition.description,
                'last_triggered': (
                    condition.last_triggered.isoformat()
                    if condition.last_triggered else None
                )
            })

        return conditions_status

    async def manual_emergency_trigger(
        self,
        reason: str,
        target_currencies: Optional[List[str]] = None,
        exit_percentage: float = 50.0
    ) -> List[OrderResult]:
        """🔴 Ручной запуск аварийного выхода"""

        try:
            self.logger.warning(f"🔴 РУЧНОЙ АВАРИЙНЫЙ ВЫХОД: {reason}")

            # Получаем позиции для выхода
            all_positions = await self.position_manager.get_all_positions()

            if target_currencies:
                positions = [p for p in all_positions if p.currency in target_currencies]
            else:
                positions = all_positions

            # Исполняем аварийный выход
            return await self.execute_emergency_exit(
                positions=positions,
                trigger=EmergencyTrigger.MANUAL_TRIGGER,
                exit_percentage=exit_percentage
            )

        except Exception as e:
            self.logger.error(f"❌ Ошибка ручного аварийного выхода: {e}")
            raise EmergencyStopError(f"Manual emergency exit failed: {e}")
