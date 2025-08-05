from typing import Optional, List, Dict, Any, Tuple
from decimal import Decimal
from datetime import datetime, timedelta
import logging
from dataclasses import dataclass, field
from enum import Enum
import asyncio

# Импорты из Core слоя
try:
    from ...core.interfaces import ITradingStrategy, IDCAStrategy, IPyramidStrategy, IEmergencyExitStrategy
    from ...core.models import (
        TradeSignal, Position, MarketData, TradingPair,
        StrategySignalType, RiskLevel
    )
    from ...core.exceptions import (
        StrategyError, StrategyNotAvailableError, ValidationError
    )
    from ...core.events import DomainEvent, publish_event
    from ...config.settings import get_current_config
except ImportError:
    # Fallback для случая если Core слой еще не готов
    class ITradingStrategy: pass
    class IDCAStrategy: pass
    class IPyramidStrategy: pass
    class IEmergencyExitStrategy: pass
    class TradeSignal: pass
    class Position: pass
    class MarketData: pass
    class TradingPair: pass
    class StrategySignalType: pass
    class RiskLevel: pass
    class StrategyError(Exception): pass
    class StrategyNotAvailableError(Exception): pass
    class ValidationError(Exception): pass
    class DomainEvent: pass
    def publish_event(event): pass
    def get_current_config(): return None


# ================= ТИПЫ СТРАТЕГИЙ =================

class StrategyType(Enum):
    """🎯 Типы стратегий"""
    DCA = "dca"                    # Dollar Cost Averaging
    PYRAMID = "pyramid"            # Пирамидальная продажа
    TRAILING_STOP = "trailing_stop" # Трейлинг стоп
    EMERGENCY_EXIT = "emergency_exit" # Аварийный выход
    MOMENTUM = "momentum"          # Моментум
    MEAN_REVERSION = "mean_reversion" # Возврат к среднему


class StrategyStatus(Enum):
    """📊 Статусы стратегий"""
    ACTIVE = "active"              # Активна
    PAUSED = "paused"              # Приостановлена
    DISABLED = "disabled"          # Отключена
    ERROR = "error"                # Ошибка


@dataclass
class StrategyMetrics:
    """📈 Метрики стратегии"""
    total_signals: int = 0
    executed_signals: int = 0
    successful_trades: int = 0
    total_pnl: Decimal = Decimal('0')
    win_rate: float = 0.0
    average_signal_confidence: float = 0.0
    last_signal_time: Optional[datetime] = None
    execution_errors: int = 0

    @property
    def execution_rate(self) -> float:
        """Процент исполненных сигналов"""
        return (self.executed_signals / self.total_signals * 100) if self.total_signals > 0 else 0.0

    @property
    def success_rate(self) -> float:
        """Процент успешных сделок"""
        return (self.successful_trades / self.executed_signals * 100) if self.executed_signals > 0 else 0.0


@dataclass
class StrategyConfiguration:
    """⚙️ Конфигурация стратегии"""
    name: str
    strategy_type: StrategyType
    priority: int
    weight: float  # Вес стратегии при комбинировании сигналов
    enabled: bool = True
    risk_level: RiskLevel = RiskLevel.MEDIUM
    parameters: Dict[str, Any] = field(default_factory=dict)
    conditions: Dict[str, Any] = field(default_factory=dict)  # Условия активации

    def validate(self) -> bool:
        """✅ Валидация конфигурации"""
        if self.priority < 1 or self.priority > 100:
            return False
        if self.weight < 0 or self.weight > 1:
            return False
        return True


@dataclass
class StrategyInstance:
    """🎯 Экземпляр стратегии"""
    id: str
    strategy: ITradingStrategy
    config: StrategyConfiguration
    status: StrategyStatus = StrategyStatus.ACTIVE
    metrics: StrategyMetrics = field(default_factory=StrategyMetrics)
    last_error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    last_executed_at: Optional[datetime] = None

    @property
    def is_active(self) -> bool:
        """Активна ли стратегия"""
        return self.status == StrategyStatus.ACTIVE and self.config.enabled

    @property
    def uptime_hours(self) -> float:
        """Время работы в часах"""
        return (datetime.now() - self.created_at).total_seconds() / 3600


@dataclass
class CombinedSignal:
    """🎯 Комбинированный сигнал от нескольких стратегий"""
    final_signal_type: StrategySignalType
    confidence: float
    contributing_signals: List[Tuple[str, TradeSignal]]  # (strategy_name, signal)
    reasoning: str
    created_at: datetime = field(default_factory=datetime.now)

    @property
    def strategy_count(self) -> int:
        """Количество стратегий в сигнале"""
        return len(self.contributing_signals)


# ================= ОСНОВНОЙ ОРКЕСТРАТОР =================

class StrategyOrchestrator:
    """🎭 Оркестратор торговых стратегий"""

    def __init__(self):
        # Зарегистрированные стратегии
        self.strategies: Dict[str, StrategyInstance] = {}

        # Активные конфигурации
        self.active_pairs: Dict[str, List[str]] = {}  # pair -> [strategy_ids]

        # История сигналов
        self.signal_history: List[CombinedSignal] = []
        self.max_history_size = 1000

        # Общие метрики
        self.total_combined_signals = 0
        self.last_analysis_time: Optional[datetime] = None

        # Логирование
        self.logger = logging.getLogger(__name__)

        self.logger.info("🎭 StrategyOrchestrator инициализирован")

    # ================= УПРАВЛЕНИЕ СТРАТЕГИЯМИ =================

    def register_strategy(
        self,
        strategy_id: str,
        strategy: ITradingStrategy,
        config: StrategyConfiguration
    ) -> bool:
        """📝 Регистрация стратегии"""

        try:
            # Валидация конфигурации
            if not config.validate():
                raise ValidationError(f"Некорректная конфигурация стратегии {strategy_id}")

            # Проверяем уникальность ID
            if strategy_id in self.strategies:
                self.logger.warning(f"⚠️ Стратегия {strategy_id} уже зарегистрирована, обновляем")

            # Создаем экземпляр стратегии
            instance = StrategyInstance(
                id=strategy_id,
                strategy=strategy,
                config=config
            )

            # Регистрируем
            self.strategies[strategy_id] = instance

            self.logger.info(f"✅ Стратегия зарегистрирована: {strategy_id} ({config.strategy_type.value})")
            return True

        except Exception as e:
            self.logger.error(f"❌ Ошибка регистрации стратегии {strategy_id}: {e}")
            return False

    def unregister_strategy(self, strategy_id: str) -> bool:
        """🗑️ Удаление стратегии"""

        try:
            if strategy_id not in self.strategies:
                self.logger.warning(f"⚠️ Стратегия {strategy_id} не найдена")
                return False

            # Удаляем из активных пар
            for pair_strategies in self.active_pairs.values():
                if strategy_id in pair_strategies:
                    pair_strategies.remove(strategy_id)

            # Удаляем стратегию
            del self.strategies[strategy_id]

            self.logger.info(f"🗑️ Стратегия {strategy_id} удалена")
            return True

        except Exception as e:
            self.logger.error(f"❌ Ошибка удаления стратегии {strategy_id}: {e}")
            return False

    def activate_strategy_for_pair(self, strategy_id: str, pair: str) -> bool:
        """🔛 Активация стратегии для торговой пары"""

        try:
            if strategy_id not in self.strategies:
                raise StrategyNotAvailableError(strategy_id, "Strategy not registered")

            instance = self.strategies[strategy_id]
            if not instance.is_active:
                raise StrategyNotAvailableError(strategy_id, f"Strategy status: {instance.status}")

            # Добавляем в активные пары
            if pair not in self.active_pairs:
                self.active_pairs[pair] = []

            if strategy_id not in self.active_pairs[pair]:
                self.active_pairs[pair].append(strategy_id)
                self.logger.info(f"🔛 Стратегия {strategy_id} активирована для {pair}")

            return True

        except Exception as e:
            self.logger.error(f"❌ Ошибка активации стратегии {strategy_id} для {pair}: {e}")
            return False

    def deactivate_strategy_for_pair(self, strategy_id: str, pair: str) -> bool:
        """🔚 Деактивация стратегии для торговой пары"""

        try:
            if pair in self.active_pairs and strategy_id in self.active_pairs[pair]:
                self.active_pairs[pair].remove(strategy_id)
                self.logger.info(f"🔚 Стратегия {strategy_id} деактивирована для {pair}")
                return True

            return False

        except Exception as e:
            self.logger.error(f"❌ Ошибка деактивации стратегии: {e}")
            return False

    # ================= АНАЛИЗ И ГЕНЕРАЦИЯ СИГНАЛОВ =================

    async def analyze_market(
        self,
        pair: str,
        market_data: MarketData,
        position: Optional[Position] = None
    ) -> CombinedSignal:
        """📊 Анализ рынка всеми активными стратегиями"""

        try:
            self.last_analysis_time = datetime.now()

            # Получаем активные стратегии для пары
            active_strategy_ids = self.active_pairs.get(pair, [])
            if not active_strategy_ids:
                return self._create_hold_signal("Нет активных стратегий")

            # Анализируем каждой стратегией
            signals = []
            for strategy_id in active_strategy_ids:
                try:
                    signal = await self._analyze_with_strategy(
                        strategy_id, market_data, position
                    )
                    if signal:
                        signals.append((strategy_id, signal))

                except Exception as e:
                    self.logger.error(f"❌ Ошибка анализа стратегией {strategy_id}: {e}")
                    await self._handle_strategy_error(strategy_id, e)

            # Комбинируем сигналы
            combined_signal = await self._combine_signals(signals, pair)

            # Сохраняем в историю
            self._add_to_history(combined_signal)

            # Публикуем событие
            await self._publish_signal_event(combined_signal, pair)

            self.total_combined_signals += 1

            return combined_signal

        except Exception as e:
            self.logger.error(f"❌ Ошибка анализа рынка для {pair}: {e}")
            return self._create_hold_signal(f"Ошибка анализа: {e}")

    async def _analyze_with_strategy(
        self,
        strategy_id: str,
        market_data: MarketData,
        position: Optional[Position]
    ) -> Optional[TradeSignal]:
        """🎯 Анализ одной стратегией"""

        try:
            instance = self.strategies[strategy_id]

            if not instance.is_active:
                return None

            # Проверяем условия выполнения
            if not await self._check_strategy_conditions(instance, market_data):
                return None

            # Выполняем анализ
            signal = await instance.strategy.analyze(market_data, position)

            # Валидируем сигнал
            if await instance.strategy.validate_signal(signal):
                # Обновляем метрики
                instance.metrics.total_signals += 1
                instance.metrics.last_signal_time = datetime.now()
                instance.last_executed_at = datetime.now()

                # Обновляем среднюю уверенность
                self._update_average_confidence(instance, signal.confidence)

                return signal
            else:
                self.logger.debug(f"❌ Невалидный сигнал от {strategy_id}")
                return None

        except Exception as e:
            self.logger.error(f"❌ Ошибка анализа стратегией {strategy_id}: {e}")
            raise StrategyError(f"Strategy analysis failed: {e}", strategy_name=strategy_id)

    async def _combine_signals(
        self,
        signals: List[Tuple[str, TradeSignal]],
        pair: str
    ) -> CombinedSignal:
        """🎯 Комбинирование сигналов от разных стратегий"""

        try:
            if not signals:
                return self._create_hold_signal("Нет сигналов от стратегий")

            # Анализируем типы сигналов
            signal_votes = {
                StrategySignalType.BUY: [],
                StrategySignalType.SELL: [],
                StrategySignalType.HOLD: [],
                StrategySignalType.EMERGENCY_EXIT: []
            }

            # Группируем сигналы по типам с учетом весов
            for strategy_id, signal in signals:
                instance = self.strategies[strategy_id]
                weight = instance.config.weight
                weighted_confidence = signal.confidence * weight

                signal_votes[signal.signal_type].append({
                    'strategy_id': strategy_id,
                    'signal': signal,
                    'weight': weight,
                    'weighted_confidence': weighted_confidence
                })

            # Определяем итоговый тип сигнала
            final_signal_type = self._determine_final_signal_type(signal_votes)

            # Рассчитываем итоговую уверенность
            final_confidence = self._calculate_combined_confidence(
                signal_votes[final_signal_type]
            )

            # Генерируем обоснование
            reasoning = self._generate_combination_reasoning(signal_votes, final_signal_type)

            return CombinedSignal(
                final_signal_type=final_signal_type,
                confidence=final_confidence,
                contributing_signals=signals,
                reasoning=reasoning
            )

        except Exception as e:
            self.logger.error(f"❌ Ошибка комбинирования сигналов: {e}")
            return self._create_hold_signal(f"Ошибка комбинирования: {e}")

    def _determine_final_signal_type(
        self,
        signal_votes: Dict[StrategySignalType, List[Dict]]
    ) -> StrategySignalType:
        """🎯 Определение итогового типа сигнала"""

        # Экстренный выход имеет абсолютный приоритет
        if signal_votes[StrategySignalType.EMERGENCY_EXIT]:
            return StrategySignalType.EMERGENCY_EXIT

        # Подсчет взвешенных голосов
        weighted_scores = {}
        for signal_type, votes in signal_votes.items():
            if signal_type == StrategySignalType.EMERGENCY_EXIT:
                continue

            total_score = sum(vote['weighted_confidence'] for vote in votes)
            weighted_scores[signal_type] = total_score

        # Определяем победителя
        if not weighted_scores:
            return StrategySignalType.HOLD

        winner = max(weighted_scores.items(), key=lambda x: x[1])

        # Если счет слишком низкий или близкий - HOLD
        if winner[1] < 0.3:
            return StrategySignalType.HOLD

        # Проверяем на близость счетов (неопределенность)
        sorted_scores = sorted(weighted_scores.values(), reverse=True)
        if len(sorted_scores) > 1 and (sorted_scores[0] - sorted_scores[1]) < 0.1:
            return StrategySignalType.HOLD

        return winner[0]

    def _calculate_combined_confidence(self, winning_votes: List[Dict]) -> float:
        """📊 Расчет комбинированной уверенности"""

        if not winning_votes:
            return 0.0

        # Средневзвешенная уверенность
        total_weight = sum(vote['weight'] for vote in winning_votes)
        if total_weight == 0:
            return 0.0

        weighted_confidence = sum(
            vote['signal'].confidence * vote['weight']
            for vote in winning_votes
        )

        return min(weighted_confidence / total_weight, 1.0)

    # ================= ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ =================

    async def _check_strategy_conditions(
        self,
        instance: StrategyInstance,
        market_data: MarketData
    ) -> bool:
        """✅ Проверка условий выполнения стратегии"""

        try:
            # Проверяем условия из конфигурации
            conditions = instance.config.conditions

            # Проверка времени
            if 'min_interval_minutes' in conditions:
                if instance.last_executed_at:
                    min_interval = timedelta(minutes=conditions['min_interval_minutes'])
                    if datetime.now() - instance.last_executed_at < min_interval:
                        return False

            # Проверка волатильности
            if 'min_volatility' in conditions:
                volatility = market_data.metadata.get('volatility', 0)
                if volatility < conditions['min_volatility']:
                    return False

            # Проверка объема
            if 'min_volume' in conditions:
                if market_data.volume_24h < Decimal(str(conditions['min_volume'])):
                    return False

            # Используем метод стратегии
            market_conditions = {
                'volatility': market_data.metadata.get('volatility', 0),
                'volume': float(market_data.volume_24h),
                'price_change': market_data.change_24h_percent or 0
            }

            return instance.strategy.can_execute(market_conditions)

        except Exception as e:
            self.logger.error(f"❌ Ошибка проверки условий стратегии: {e}")
            return False

    async def _handle_strategy_error(self, strategy_id: str, error: Exception) -> None:
        """🚨 Обработка ошибки стратегии"""

        try:
            instance = self.strategies[strategy_id]
            instance.metrics.execution_errors += 1
            instance.last_error = str(error)

            # Если много ошибок - приостанавливаем стратегию
            if instance.metrics.execution_errors >= 5:
                instance.status = StrategyStatus.ERROR
                self.logger.warning(f"⚠️ Стратегия {strategy_id} приостановлена из-за ошибок")

                # Публикуем событие об ошибке
                await self._publish_strategy_error_event(strategy_id, error)

        except Exception as e:
            self.logger.error(f"❌ Ошибка обработки ошибки стратегии: {e}")

    def _create_hold_signal(self, reason: str) -> CombinedSignal:
        """🔄 Создание HOLD сигнала"""

        return CombinedSignal(
            final_signal_type=StrategySignalType.HOLD,
            confidence=1.0,
            contributing_signals=[],
            reasoning=reason
        )

    def _update_average_confidence(self, instance: StrategyInstance, confidence: float) -> None:
        """📊 Обновление средней уверенности стратегии"""

        if instance.metrics.average_signal_confidence == 0:
            instance.metrics.average_signal_confidence = confidence
        else:
            # Экспоненциальное сглаживание
            alpha = 0.1
            instance.metrics.average_signal_confidence = (
                alpha * confidence +
                (1 - alpha) * instance.metrics.average_signal_confidence
            )

    def _generate_combination_reasoning(
        self,
        signal_votes: Dict[StrategySignalType, List[Dict]],
        final_signal_type: StrategySignalType
    ) -> str:
        """💭 Генерация обоснования комбинированного решения"""

        try:
            reasoning_parts = []

            # Добавляем информацию о голосах
            for signal_type, votes in signal_votes.items():
                if votes:
                    strategies = [vote['strategy_id'] for vote in votes]
                    reasoning_parts.append(f"{signal_type.value}: {', '.join(strategies)}")

            # Добавляем информацию о победителе
            winner_votes = signal_votes[final_signal_type]
            if winner_votes:
                total_confidence = sum(vote['signal'].confidence for vote in winner_votes)
                avg_confidence = total_confidence / len(winner_votes)
                reasoning_parts.append(f"Итого: {final_signal_type.value} (confidence: {avg_confidence:.2f})")

            return "; ".join(reasoning_parts)

        except Exception:
            return f"Combined signal: {final_signal_type.value}"

    def _add_to_history(self, signal: CombinedSignal) -> None:
        """📜 Добавление сигнала в историю"""

        try:
            self.signal_history.append(signal)

            # Ограничиваем размер истории
            if len(self.signal_history) > self.max_history_size:
                self.signal_history = self.signal_history[-self.max_history_size:]

        except Exception as e:
            self.logger.error(f"❌ Ошибка добавления в историю: {e}")

    async def _publish_signal_event(self, signal: CombinedSignal, pair: str) -> None:
        """📡 Публикация события о сигнале"""

        try:
            event = DomainEvent()
            event.event_type = "combined_signal_generated"
            event.source = "strategy_orchestrator"
            event.metadata = {
                'pair': pair,
                'signal_type': signal.final_signal_type.value,
                'confidence': signal.confidence,
                'strategy_count': signal.strategy_count,
                'reasoning': signal.reasoning
            }

            await publish_event(event)

        except Exception as e:
            self.logger.error(f"❌ Ошибка публикации события: {e}")

    async def _publish_strategy_error_event(self, strategy_id: str, error: Exception) -> None:
        """🚨 Публикация события об ошибке стратегии"""

        try:
            event = DomainEvent()
            event.event_type = "strategy_error"
            event.source = "strategy_orchestrator"
            event.metadata = {
                'strategy_id': strategy_id,
                'error': str(error),
                'error_type': type(error).__name__
            }

            await publish_event(event)

        except Exception as e:
            self.logger.error(f"❌ Ошибка публикации события об ошибке: {e}")

    # ================= СТАТИСТИКА И МОНИТОРИНГ =================

    def get_strategy_statistics(self) -> Dict[str, Any]:
        """📊 Статистика всех стратегий"""

        try:
            total_strategies = len(self.strategies)
            active_strategies = sum(1 for s in self.strategies.values() if s.is_active)

            strategy_stats = {}
            for strategy_id, instance in self.strategies.items():
                strategy_stats[strategy_id] = {
                    'status': instance.status.value,
                    'type': instance.config.strategy_type.value,
                    'priority': instance.config.priority,
                    'weight': instance.config.weight,
                    'uptime_hours': instance.uptime_hours,
                    'metrics': {
                        'total_signals': instance.metrics.total_signals,
                        'execution_rate': instance.metrics.execution_rate,
                        'average_confidence': instance.metrics.average_signal_confidence,
                        'errors': instance.metrics.execution_errors
                    }
                }

            return {
                'summary': {
                    'total_strategies': total_strategies,
                    'active_strategies': active_strategies,
                    'total_combined_signals': self.total_combined_signals,
                    'active_pairs': len(self.active_pairs),
                    'last_analysis': self.last_analysis_time.isoformat() if self.last_analysis_time else None
                },
                'strategies': strategy_stats,
                'active_pairs': {
                    pair: strategy_ids for pair, strategy_ids in self.active_pairs.items()
                },
                'recent_signals': len([
                    s for s in self.signal_history[-10:]
                    if s.final_signal_type != StrategySignalType.HOLD
                ])
            }

        except Exception as e:
            self.logger.error(f"❌ Ошибка получения статистики: {e}")
            return {}

    def pause_strategy(self, strategy_id: str) -> bool:
        """⏸️ Приостановка стратегии"""

        try:
            if strategy_id in self.strategies:
                self.strategies[strategy_id].status = StrategyStatus.PAUSED
                self.logger.info(f"⏸️ Стратегия {strategy_id} приостановлена")
                return True
            return False

        except Exception as e:
            self.logger.error(f"❌ Ошибка приостановки стратегии: {e}")
            return False

    def resume_strategy(self, strategy_id: str) -> bool:
        """▶️ Возобновление стратегии"""

        try:
            if strategy_id in self.strategies:
                instance = self.strategies[strategy_id]
                if instance.status in [StrategyStatus.PAUSED, StrategyStatus.ERROR]:
                    instance.status = StrategyStatus.ACTIVE
                    instance.last_error = None
                    self.logger.info(f"▶️ Стратегия {strategy_id} возобновлена")
                    return True
            return False

        except Exception as e:
            self.logger.error(f"❌ Ошибка возобновления стратегии: {e}")
            return False
