#!/usr/bin/env python3
"""📈 Торговый сервис - Domain слой"""

from typing import Optional, List, Dict, Any
from decimal import Decimal
from datetime import datetime, timedelta
import logging
from dataclasses import dataclass
from enum import Enum

# Импорты из Core слоя
try:
    from ...core.interfaces import ITradingStrategy, IRiskManager, IMarketDataProvider
    from ...core.models import (
        TradeSignal, Position, MarketData, TradingPair,
        Money, Price, OrderResult, StrategySignalType
    )
    from ...core.exceptions import (
        TradingError, ValidationError, RiskManagementError,
        InsufficientBalanceError, InvalidSignalError
    )
    from ...core.events import DomainEvent, publish_event
except ImportError:
    # Fallback для случая если Core слой еще не готов
    class ITradingStrategy: pass
    class IRiskManager: pass
    class IMarketDataProvider: pass
    class TradeSignal: pass
    class Position: pass
    class MarketData: pass
    class TradingPair: pass
    class Money: pass
    class Price: pass
    class OrderResult: pass
    class StrategySignalType: pass
    class TradingError(Exception): pass
    class ValidationError(Exception): pass
    class RiskManagementError(Exception): pass
    class InsufficientBalanceError(Exception): pass
    class InvalidSignalError(Exception): pass
    class DomainEvent: pass
    def publish_event(event): pass


# ================= ДОМЕННЫЕ ТИПЫ =================

class TradingMode(Enum):
    """🎯 Режимы торговли"""
    PAPER = "paper"          # Бумажная торговля
    LIVE = "live"            # Реальная торговля
    SIMULATION = "simulation" # Симуляция


class TradingStatus(Enum):
    """📊 Статусы торговой системы"""
    IDLE = "idle"                    # Простой
    ANALYZING = "analyzing"          # Анализ рынка
    EXECUTING = "executing"          # Исполнение сделки
    RISK_CHECK = "risk_check"        # Проверка рисков
    EMERGENCY_STOP = "emergency_stop" # Аварийная остановка


@dataclass
class TradingContext:
    """🎯 Контекст торговли"""
    trading_pair: TradingPair
    current_price: Price
    position: Optional[Position]
    available_balance: Money
    market_data: MarketData
    risk_level: str

    @property
    def has_position(self) -> bool:
        """Есть ли открытая позиция"""
        return self.position is not None and not self.position.is_empty

    @property
    def position_value(self) -> Optional[Money]:
        """Стоимость текущей позиции"""
        if not self.has_position:
            return None

        value = self.position.quantity * self.current_price.value
        return Money(value, self.trading_pair.quote)


@dataclass
class TradingDecision:
    """🎯 Торговое решение"""
    signal: TradeSignal
    risk_assessment: Dict[str, Any]
    execution_plan: Dict[str, Any]
    confidence: float
    strategy_name: str
    reasoning: str

    @property
    def is_actionable(self) -> bool:
        """Можно ли выполнить решение"""
        return self.signal.is_actionable and self.confidence > 0.5

    @property
    def estimated_value(self) -> Optional[Money]:
        """Оценочная стоимость операции"""
        return self.signal.estimate_trade_value()


# ================= ТОРГОВЫЙ СЕРВИС =================

class TradingService:
    """📈 Основной торговый сервис"""

    def __init__(
        self,
        strategies: List[ITradingStrategy],
        risk_manager: IRiskManager,
        market_data_provider: IMarketDataProvider,
        trading_mode: TradingMode = TradingMode.PAPER
    ):
        self.strategies = strategies
        self.risk_manager = risk_manager
        self.market_data_provider = market_data_provider
        self.trading_mode = trading_mode

        # Состояние
        self.status = TradingStatus.IDLE
        self.last_analysis_time: Optional[datetime] = None
        self.active_strategies: Dict[str, ITradingStrategy] = {}
        self.trading_statistics = TradingStatistics()

        # Логирование
        self.logger = logging.getLogger(__name__)

        # Инициализация стратегий
        self._initialize_strategies()

    def _initialize_strategies(self) -> None:
        """🔧 Инициализация стратегий"""
        for strategy in self.strategies:
            try:
                strategy_name = strategy.get_strategy_name()
                self.active_strategies[strategy_name] = strategy
                self.logger.info(f"✅ Инициализирована стратегия: {strategy_name}")
            except Exception as e:
                self.logger.error(f"❌ Ошибка инициализации стратегии: {e}")

    async def analyze_market(
        self,
        trading_pair: TradingPair,
        position: Optional[Position] = None
    ) -> TradingDecision:
        """📊 Анализ рынка и принятие торгового решения"""

        try:
            self.status = TradingStatus.ANALYZING
            self.logger.debug(f"🔍 Анализ рынка для {trading_pair}")

            # Получаем рыночные данные
            market_data = await self.market_data_provider.get_market_data(str(trading_pair))

            # Создаем контекст торговли
            context = await self._create_trading_context(trading_pair, market_data, position)

            # Анализируем всеми стратегиями
            signals = await self._analyze_with_strategies(market_data, position)

            # Выбираем лучший сигнал
            best_signal = self._select_best_signal(signals)

            # Оцениваем риски
            risk_assessment = await self._assess_risks(best_signal, context)

            # Создаем план исполнения
            execution_plan = self._create_execution_plan(best_signal, context)

            # Формируем решение
            decision = TradingDecision(
                signal=best_signal,
                risk_assessment=risk_assessment,
                execution_plan=execution_plan,
                confidence=self._calculate_confidence(best_signal, risk_assessment),
                strategy_name=best_signal.strategy_name,
                reasoning=self._generate_reasoning(best_signal, risk_assessment)
            )

            self.last_analysis_time = datetime.now()
            self.status = TradingStatus.IDLE

            return decision

        except Exception as e:
            self.status = TradingStatus.IDLE
            raise TradingError(
                f"Ошибка анализа рынка: {e}",
                context={'trading_pair': str(trading_pair)}
            ) from e

    async def execute_decision(
        self,
        decision: TradingDecision,
        dry_run: bool = None
    ) -> OrderResult:
        """⚡ Исполнение торгового решения"""

        if dry_run is None:
            dry_run = self.trading_mode != TradingMode.LIVE

        try:
            self.status = TradingStatus.EXECUTING
            self.logger.info(f"⚡ Исполнение торгового решения: {decision.signal.signal_type}")

            # Валидация решения
            self._validate_decision(decision)

            # Финальная проверка рисков
            if not await self._final_risk_check(decision):
                raise RiskManagementError("Решение заблокировано риск-менеджментом")

            # Исполнение
            if dry_run:
                result = self._simulate_execution(decision)
                self.logger.info(f"📄 Симуляция исполнения: {result}")
            else:
                result = await self._execute_real_trade(decision)
                self.logger.info(f"💰 Реальное исполнение: {result}")

            # Обновляем статистику
            self.trading_statistics.record_trade(decision, result)

            # Публикуем событие
            await self._publish_trade_event(decision, result)

            self.status = TradingStatus.IDLE
            return result

        except Exception as e:
            self.status = TradingStatus.IDLE
            self.trading_statistics.record_error(e)
            raise TradingError(
                f"Ошибка исполнения торгового решения: {e}",
                context={'decision': decision.signal.to_dict() if hasattr(decision.signal, 'to_dict') else str(decision.signal)}
            ) from e

    async def _create_trading_context(
        self,
        trading_pair: TradingPair,
        market_data: MarketData,
        position: Optional[Position]
    ) -> TradingContext:
        """🎯 Создание контекста торговли"""

        # Получаем текущую цену
        current_price = Price(
            value=market_data.current_price,
            pair=trading_pair,
            timestamp=market_data.timestamp
        )

        # Получаем доступный баланс (здесь нужна интеграция с балансовым сервисом)
        available_balance = Money(Decimal('1000'), trading_pair.quote)  # Заглушка

        # Оценка уровня риска
        risk_level = "medium"  # Заглушка

        return TradingContext(
            trading_pair=trading_pair,
            current_price=current_price,
            position=position,
            available_balance=available_balance,
            market_data=market_data,
            risk_level=risk_level
        )

    async def _analyze_with_strategies(
        self,
        market_data: MarketData,
        position: Optional[Position]
    ) -> List[TradeSignal]:
        """🎯 Анализ всеми стратегиями"""

        signals = []

        for strategy_name, strategy in self.active_strategies.items():
            try:
                # Проверяем можно ли выполнять стратегию
                market_conditions = {
                    'volatility': market_data.metadata.get('volatility', 0),
                    'volume': float(market_data.volume_24h),
                    'price_change': market_data.change_24h_percent or 0
                }

                if not strategy.can_execute(market_conditions):
                    self.logger.debug(f"⏸️ Стратегия {strategy_name} пропущена")
                    continue

                # Анализируем
                signal = await strategy.analyze(market_data, position)

                # Валидируем сигнал
                if await strategy.validate_signal(signal):
                    signals.append(signal)
                    self.logger.debug(f"📊 Сигнал от {strategy_name}: {signal.signal_type}")
                else:
                    self.logger.debug(f"❌ Невалидный сигнал от {strategy_name}")

            except Exception as e:
                self.logger.error(f"❌ Ошибка стратегии {strategy_name}: {e}")
                continue

        return signals

    def _select_best_signal(self, signals: List[TradeSignal]) -> TradeSignal:
        """🏆 Выбор лучшего сигнала"""

        if not signals:
            # Создаем сигнал HOLD если нет других
            return TradeSignal(
                signal_type=StrategySignalType.HOLD,
                strategy_name="default",
                reason="Нет активных сигналов"
            )

        # Сортируем по уверенности и приоритету стратегии
        signals.sort(key=lambda s: (s.confidence, self._get_strategy_priority(s.strategy_name)), reverse=True)

        best_signal = signals[0]
        self.logger.debug(f"🏆 Выбран сигнал: {best_signal.signal_type} от {best_signal.strategy_name}")

        return best_signal

    def _get_strategy_priority(self, strategy_name: str) -> int:
        """🎯 Получение приоритета стратегии"""
        strategy = self.active_strategies.get(strategy_name)
        if strategy and hasattr(strategy, 'get_priority'):
            return strategy.get_priority()
        return 50  # Средний приоритет

    async def _assess_risks(
        self,
        signal: TradeSignal,
        context: TradingContext
    ) -> Dict[str, Any]:
        """🛡️ Оценка рисков"""

        try:
            risk_assessment = await self.risk_manager.assess_trade_risk(signal, context.position)

            # Дополнительные проверки
            risk_assessment.update({
                'balance_sufficient': self._check_balance_sufficiency(signal, context),
                'position_limits_ok': self._check_position_limits(signal, context),
                'daily_limits_ok': await self.risk_manager.check_daily_limits()
            })

            return risk_assessment

        except Exception as e:
            self.logger.error(f"❌ Ошибка оценки рисков: {e}")
            return {
                'risk_level': 'high',
                'approved': False,
                'reason': f'Ошибка оценки: {e}'
            }

    def _check_balance_sufficiency(
        self,
        signal: TradeSignal,
        context: TradingContext
    ) -> bool:
        """💰 Проверка достаточности баланса"""

        if signal.signal_type == StrategySignalType.BUY:
            required = signal.quantity * signal.price if signal.price else Decimal('0')
            return context.available_balance.amount >= required

        return True  # Для продажи баланс не нужен

    def _check_position_limits(
        self,
        signal: TradeSignal,
        context: TradingContext
    ) -> bool:
        """📊 Проверка лимитов позиции"""

        # Здесь должна быть логика проверки максимальных размеров позиций
        # Пока возвращаем True
        return True

    async def _final_risk_check(self, decision: TradingDecision) -> bool:
        """🔒 Финальная проверка рисков"""

        try:
            # Проверяем нет ли аварийной остановки
            if await self.risk_manager.emergency_stop_check():
                self.logger.warning("🚨 Аварийная остановка активна")
                return False

            # Проверяем блокировку торговли
            if await self.risk_manager.should_block_trading():
                self.logger.warning("🚫 Торговля заблокирована")
                return False

            # Проверяем уровень риска решения
            risk_level = decision.risk_assessment.get('risk_level', 'unknown')
            if risk_level == 'critical':
                self.logger.warning("🚨 Критический уровень риска")
                return False

            return decision.risk_assessment.get('approved', False)

        except Exception as e:
            self.logger.error(f"❌ Ошибка финальной проверки рисков: {e}")
            return False

    def _create_execution_plan(
        self,
        signal: TradeSignal,
        context: TradingContext
    ) -> Dict[str, Any]:
        """📋 Создание плана исполнения"""

        return {
            'order_type': 'market' if not signal.price else 'limit',
            'quantity': signal.quantity,
            'price': signal.price,
            'estimated_cost': signal.estimate_trade_value(),
            'execution_time': datetime.now(),
            'stop_loss': getattr(signal, 'stop_loss', None),
            'take_profit': getattr(signal, 'take_profit', None)
        }

    def _calculate_confidence(
        self,
        signal: TradeSignal,
        risk_assessment: Dict[str, Any]
    ) -> float:
        """🎯 Расчет итоговой уверенности"""

        base_confidence = signal.confidence
        risk_factor = 1.0

        # Снижаем уверенность в зависимости от уровня риска
        risk_level = risk_assessment.get('risk_level', 'medium')
        if risk_level == 'high':
            risk_factor = 0.7
        elif risk_level == 'critical':
            risk_factor = 0.3

        # Учитываем одобрение риск-менеджера
        if not risk_assessment.get('approved', False):
            risk_factor *= 0.5

        return min(base_confidence * risk_factor, 1.0)

    def _generate_reasoning(
        self,
        signal: TradeSignal,
        risk_assessment: Dict[str, Any]
    ) -> str:
        """💭 Генерация обоснования решения"""

        parts = [
            f"Стратегия: {signal.strategy_name}",
            f"Сигнал: {signal.signal_type}",
            f"Причина: {signal.reason}",
            f"Уверенность стратегии: {signal.confidence:.1%}",
            f"Уровень риска: {risk_assessment.get('risk_level', 'unknown')}"
        ]

        if risk_assessment.get('approved'):
            parts.append("✅ Одобрено риск-менеджментом")
        else:
            parts.append("❌ Не одобрено риск-менеджментом")

        return "; ".join(parts)

    def _validate_decision(self, decision: TradingDecision) -> None:
        """✅ Валидация торгового решения"""

        if not decision.signal:
            raise ValidationError("Отсутствует торговый сигнал")

        if decision.signal.signal_type == StrategySignalType.HOLD:
            return  # HOLD всегда валиден

        if not decision.signal.pair:
            raise ValidationError("Не указана торговая пара")

        if decision.signal.quantity <= 0:
            raise ValidationError(
                "Некорректное количество",
                field="quantity",
                value=decision.signal.quantity
            )

        if decision.confidence < 0.3:
            raise ValidationError(
                "Слишком низкая уверенность для исполнения",
                field="confidence",
                value=decision.confidence
            )

    def _simulate_execution(self, decision: TradingDecision) -> OrderResult:
        """📄 Симуляция исполнения"""

        from ...core.models import OrderType, OrderStatus

        return OrderResult(
            order_id=f"sim_{datetime.now().timestamp()}",
            pair=decision.signal.pair or TradingPair.from_string("DOGE_EUR"),
            order_type=OrderType.BUY if decision.signal.signal_type == StrategySignalType.BUY else OrderType.SELL,
            status=OrderStatus.FILLED,
            requested_quantity=decision.signal.quantity,
            executed_quantity=decision.signal.quantity,
            requested_price=decision.signal.price,
            executed_price=decision.signal.price,
            total_cost=decision.signal.quantity * (decision.signal.price or Decimal('0')),
            commission=Decimal('0')
        )

    async def _execute_real_trade(self, decision: TradingDecision) -> OrderResult:
        """💰 Реальное исполнение сделки"""

        # Здесь должна быть интеграция с реальным API
        # Пока возвращаем симуляцию
        self.logger.warning("⚠️ Реальное исполнение не реализовано, используется симуляция")
        return self._simulate_execution(decision)

    async def _publish_trade_event(
        self,
        decision: TradingDecision,
        result: OrderResult
    ) -> None:
        """📡 Публикация торгового события"""

        try:
            event = DomainEvent()
            event.event_type = "trade_executed"
            event.source = "trading_service"
            event.metadata = {
                'strategy': decision.strategy_name,
                'signal_type': decision.signal.signal_type,
                'order_id': result.order_id,
                'success': result.is_successful
            }

            await publish_event(event)

        except Exception as e:
            self.logger.error(f"❌ Ошибка публикации события: {e}")

    # ================= СТАТИСТИКА И МОНИТОРИНГ =================

    def get_statistics(self) -> Dict[str, Any]:
        """📊 Получение статистики торговли"""
        return self.trading_statistics.to_dict()

    def get_status(self) -> Dict[str, Any]:
        """📋 Получение текущего статуса"""
        return {
            'status': self.status.value,
            'trading_mode': self.trading_mode.value,
            'active_strategies': list(self.active_strategies.keys()),
            'last_analysis': self.last_analysis_time.isoformat() if self.last_analysis_time else None,
            'statistics': self.get_statistics()
        }


# ================= СТАТИСТИКА ТОРГОВЛИ =================

class TradingStatistics:
    """📊 Статистика торговли"""

    def __init__(self):
        self.total_trades = 0
        self.successful_trades = 0
        self.total_volume = Decimal('0')
        self.total_pnl = Decimal('0')
        self.trades_by_strategy: Dict[str, int] = {}
        self.errors_count = 0
        self.start_time = datetime.now()

    def record_trade(self, decision: TradingDecision, result: OrderResult) -> None:
        """📝 Запись сделки"""
        self.total_trades += 1

        if result.is_successful:
            self.successful_trades += 1
            self.total_volume += result.total_cost

        # Статистика по стратегиям
        strategy_name = decision.strategy_name
        self.trades_by_strategy[strategy_name] = self.trades_by_strategy.get(strategy_name, 0) + 1

    def record_error(self, error: Exception) -> None:
        """❌ Запись ошибки"""
        self.errors_count += 1

    @property
    def success_rate(self) -> float:
        """📈 Процент успешных сделок"""
        if self.total_trades == 0:
            return 0.0
        return (self.successful_trades / self.total_trades) * 100

    @property
    def uptime_hours(self) -> float:
        """⏰ Время работы в часах"""
        return (datetime.now() - self.start_time).total_seconds() / 3600

    def to_dict(self) -> Dict[str, Any]:
        """📤 Экспорт статистики"""
        return {
            'total_trades': self.total_trades,
            'successful_trades': self.successful_trades,
            'success_rate': self.success_rate,
            'total_volume': str(self.total_volume),
            'total_pnl': str(self.total_pnl),
            'trades_by_strategy': self.trades_by_strategy,
            'errors_count': self.errors_count,
            'uptime_hours': self.uptime_hours
        }
