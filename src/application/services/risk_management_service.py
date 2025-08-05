from typing import Optional, List, Dict, Any, Tuple
from decimal import Decimal
from datetime import datetime, timedelta
import logging
from dataclasses import dataclass, field
from enum import Enum

# Импорты из Core слоя
try:
    from ...core.interfaces import IRiskManager, IPositionManager, IMarketDataProvider
    from ...core.models import (
        TradeSignal, Position, TradingPair, Money, Price,
        MarketData, RiskLevel, StrategySignalType
    )
    from ...core.exceptions import (
        RiskManagementError, EmergencyStopError, ValidationError,
        TradingError, InsufficientBalanceError
    )
    from ...core.events import DomainEvent, publish_event
except ImportError:
    # Fallback для разработки
    class IRiskManager: pass
    class IPositionManager: pass
    class IMarketDataProvider: pass
    
    class TradeSignal: pass
    class Position: pass
    class TradingPair: pass
    class Money: pass
    class Price: pass
    class MarketData: pass
    class RiskLevel: pass
    class StrategySignalType: pass
    
    class RiskManagementError(Exception): pass
    class EmergencyStopError(Exception): pass
    class ValidationError(Exception): pass
    class TradingError(Exception): pass
    class InsufficientBalanceError(Exception): pass
    
    class DomainEvent: pass
    def publish_event(event): pass


class RiskDecision(Enum):
    """🎯 Решения риск-менеджмента"""
    APPROVE = "approve"           # Одобрить операцию
    APPROVE_WITH_LIMITS = "approve_with_limits"  # Одобрить с ограничениями
    REJECT = "reject"            # Отклонить операцию
    EMERGENCY_STOP = "emergency_stop"  # Аварийная остановка


@dataclass
class RiskAssessmentResult:
    """📊 Результат оценки рисков"""
    decision: RiskDecision
    risk_score: float  # 0.0 - 1.0
    confidence: float  # 0.0 - 1.0
    
    # Детали оценки
    factors: Dict[str, Any] = field(default_factory=dict)
    recommendations: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    
    # Ограничения (если применимы)
    max_position_size: Optional[Decimal] = None
    max_trade_amount: Optional[Decimal] = None
    required_stop_loss: Optional[Decimal] = None
    
    # Временные ограничения
    cooldown_period: Optional[timedelta] = None
    valid_until: Optional[datetime] = None
    
    @property
    def is_approved(self) -> bool:
        """Одобрена ли операция"""
        return self.decision in [RiskDecision.APPROVE, RiskDecision.APPROVE_WITH_LIMITS]
    
    @property
    def has_restrictions(self) -> bool:
        """Есть ли ограничения"""
        return self.decision == RiskDecision.APPROVE_WITH_LIMITS
    
    @property
    def is_emergency(self) -> bool:
        """Требуется ли аварийная остановка"""
        return self.decision == RiskDecision.EMERGENCY_STOP


@dataclass
class RiskMonitoringState:
    """📈 Состояние мониторинга рисков"""
    # Текущие лимиты
    daily_loss_limit: Decimal = Decimal('100')  # EUR
    position_size_limit: Decimal = Decimal('0.1')  # 10% от депозита
    max_drawdown_limit: Decimal = Decimal('0.15')  # 15%
    
    # Текущие значения
    daily_loss: Decimal = Decimal('0')
    current_drawdown: Decimal = Decimal('0')
    consecutive_losses: int = 0
    
    # Состояние системы
    emergency_stop_active: bool = False
    trading_blocked: bool = False
    last_assessment_time: Optional[datetime] = None
    
    # Счетчики
    trades_today: int = 0
    risk_violations_today: int = 0
    emergency_stops_count: int = 0


class RiskManagementService:
    """🛡️ Сервис управления рисками"""
    
    def __init__(
        self,
        risk_manager: IRiskManager,
        position_manager: IPositionManager,
        market_data_provider: IMarketDataProvider,
        trading_pair: TradingPair,
        initial_balance: Money
    ):
        self.risk_manager = risk_manager
        self.position_manager = position_manager
        self.market_data_provider = market_data_provider
        self.trading_pair = trading_pair
        self.initial_balance = initial_balance
        
        # Состояние мониторинга
        self.monitoring_state = RiskMonitoringState()
        
        # История оценок
        self.assessment_history: List[RiskAssessmentResult] = []
        self.max_history_size = 1000
        
        # Конфигурация
        self.risk_tolerance = RiskLevel.MEDIUM
        self.auto_emergency_stop = True
        self.assessment_timeout = timedelta(seconds=30)
        
        # Кэш оценок
        self._assessment_cache: Dict[str, Tuple[RiskAssessmentResult, datetime]] = {}
        self.cache_ttl = timedelta(minutes=1)
        
        # Логирование
        self.logger = logging.getLogger(__name__)
        
        # Статистика
        self.stats = {
            'total_assessments': 0,
            'approved_trades': 0,
            'rejected_trades': 0,
            'emergency_stops': 0,
            'false_positives': 0  # Отклоненные операции, которые были бы прибыльными
        }
    
    async def assess_trade_risk(
        self,
        signal: TradeSignal,
        context: Optional[Dict[str, Any]] = None
    ) -> RiskAssessmentResult:
        """🔍 Комплексная оценка риска торговой операции"""
        
        try:
            start_time = datetime.now()
            self.stats['total_assessments'] += 1
            
            self.logger.debug(f"🔍 Оценка риска для {signal.signal_type} {signal.pair}")
            
            # Проверяем кэш
            cache_key = self._get_cache_key(signal)
            cached_result = self._get_cached_assessment(cache_key)
            if cached_result:
                self.logger.debug("💾 Использован кэшированный результат оценки")
                return cached_result
            
            # Выполняем оценку
            result = await self._perform_risk_assessment(signal, context)
            
            # Кэшируем результат
            self._cache_assessment(cache_key, result)
            
            # Сохраняем в историю
            self.assessment_history.append(result)
            if len(self.assessment_history) > self.max_history_size:
                self.assessment_history = self.assessment_history[-self.max_history_size:]
            
            # Обновляем статистику
            if result.is_approved:
                self.stats['approved_trades'] += 1
            else:
                self.stats['rejected_trades'] += 1
            
            if result.is_emergency:
                self.stats['emergency_stops'] += 1
            
            # Обновляем состояние мониторинга
            await self._update_monitoring_state(result)
            
            # Публикуем событие оценки
            await self._publish_risk_assessment_event(signal, result)
            
            assessment_time = (datetime.now() - start_time).total_seconds()
            self.logger.debug(f"✅ Оценка риска завершена за {assessment_time:.3f}с: {result.decision.value}")
            
            return result
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка оценки риска: {e}")
            
            # В случае ошибки возвращаем консервативную оценку
            return RiskAssessmentResult(
                decision=RiskDecision.REJECT,
                risk_score=1.0,
                confidence=0.0,
                warnings=[f"Ошибка оценки риска: {e}"]
            )
    
    async def check_emergency_conditions(self) -> Tuple[bool, Optional[str]]:
        """🚨 Проверка условий аварийной остановки"""
        try:
            # Проверяем через domain risk manager
            should_stop = await self.risk_manager.should_emergency_stop()
            
            if should_stop:
                # Получаем детали от risk manager
                stop_reason = await self._get_emergency_stop_reason()
                
                self.logger.warning(f"🚨 Обнаружены условия аварийной остановки: {stop_reason}")
                
                if self.auto_emergency_stop:
                    await self.trigger_emergency_stop(stop_reason)
                
                return True, stop_reason
            
            return False, None
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка проверки аварийных условий: {e}")
            return False, f"Ошибка проверки: {e}"
    
    async def trigger_emergency_stop(self, reason: str) -> None:
        """🚨 Активация аварийной остановки"""
        try:
            self.logger.critical(f"🚨 АКТИВАЦИЯ АВАРИЙНОЙ ОСТАНОВКИ: {reason}")
            
            # Обновляем состояние
            self.monitoring_state.emergency_stop_active = True
            self.monitoring_state.trading_blocked = True
            self.monitoring_state.emergency_stops_count += 1
            
            # Активируем аварийную остановку в domain layer
            await self.risk_manager.trigger_emergency_stop(reason)
            
            # Публикуем критическое событие
            await self._publish_emergency_event(reason)
            
            # Пытаемся закрыть открытые позиции (если настроено)
            if self.auto_emergency_stop:
                await self._emergency_close_positions(reason)
            
        except Exception as e:
            self.logger.critical(f"💥 КРИТИЧЕСКАЯ ОШИБКА при аварийной остановке: {e}")
            raise EmergencyStopError(f"Не удалось активировать аварийную остановку: {e}")
    
    async def reset_emergency_stop(self, authorization_code: str) -> bool:
        """🔄 Сброс аварийной остановки"""
        try:
            # Здесь можно добавить проверку авторизационного кода
            if not self._validate_authorization(authorization_code):
                self.logger.warning("⚠️ Неверный код авторизации для сброса аварийной остановки")
                return False
            
            self.logger.info("🔄 Сброс аварийной остановки...")
            
            # Сбрасываем состояние
            self.monitoring_state.emergency_stop_active = False
            self.monitoring_state.trading_blocked = False
            
            # Сбрасываем в domain layer
            await self.risk_manager.reset_emergency_stop()
            
            # Публикуем событие сброса
            await self._publish_emergency_reset_event()
            
            self.logger.info("✅ Аварийная остановка сброшена")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка сброса аварийной остановки: {e}")
            return False
    
    async def update_risk_limits(
        self,
        new_limits: Dict[str, Decimal]
    ) -> None:
        """⚙️ Обновление лимитов риска"""
        try:
            self.logger.info(f"⚙️ Обновление лимитов риска: {new_limits}")
            
            # Валидируем новые лимиты
            self._validate_risk_limits(new_limits)
            
            # Обновляем лимиты
            if 'daily_loss_limit' in new_limits:
                self.monitoring_state.daily_loss_limit = new_limits['daily_loss_limit']
            
            if 'position_size_limit' in new_limits:
                self.monitoring_state.position_size_limit = new_limits['position_size_limit']
            
            if 'max_drawdown_limit' in new_limits:
                self.monitoring_state.max_drawdown_limit = new_limits['max_drawdown_limit']
            
            # Обновляем в domain layer
            await self.risk_manager.update_limits(new_limits)
            
            # Публикуем событие обновления
            await self._publish_limits_update_event(new_limits)
            
            self.logger.info("✅ Лимиты риска обновлены")
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка обновления лимитов: {e}")
            raise RiskManagementError(f"Не удалось обновить лимиты: {e}")
    
    async def get_risk_report(self) -> Dict[str, Any]:
        """📊 Получение отчета по рискам"""
        try:
            # Получаем текущую позицию
            current_position = await self.position_manager.get_current_position(self.trading_pair)
            
            # Получаем рыночные данные
            market_data = await self.market_data_provider.get_market_data(self.trading_pair)
            
            # Рассчитываем текущие риски
            current_risk_metrics = await self._calculate_current_risk_metrics(
                current_position, market_data
            )
            
            # Анализ истории оценок
            history_analysis = self._analyze_assessment_history()
            
            return {
                'timestamp': datetime.now().isoformat(),
                'status': {
                    'emergency_stop_active': self.monitoring_state.emergency_stop_active,
                    'trading_blocked': self.monitoring_state.trading_blocked,
                    'risk_tolerance': self.risk_tolerance.value if hasattr(self.risk_tolerance, 'value') else str(self.risk_tolerance)
                },
                'current_limits': {
                    'daily_loss_limit': str(self.monitoring_state.daily_loss_limit),
                    'position_size_limit': str(self.monitoring_state.position_size_limit),
                    'max_drawdown_limit': str(self.monitoring_state.max_drawdown_limit)
                },
                'current_values': {
                    'daily_loss': str(self.monitoring_state.daily_loss),
                    'current_drawdown': str(self.monitoring_state.current_drawdown),
                    'consecutive_losses': self.monitoring_state.consecutive_losses
                },
                'risk_metrics': current_risk_metrics,
                'statistics': self.stats.copy(),
                'history_analysis': history_analysis,
                'recent_assessments': [
                    {
                        'decision': assessment.decision.value,
                        'risk_score': assessment.risk_score,
                        'confidence': assessment.confidence,
                        'warnings_count': len(assessment.warnings)
                    }
                    for assessment in self.assessment_history[-10:]  # Последние 10
                ]
            }
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка создания отчета: {e}")
            return {'error': str(e)}
    
    async def simulate_risk_scenario(
        self,
        scenario: Dict[str, Any]
    ) -> Dict[str, Any]:
        """🎲 Симуляция рискового сценария"""
        try:
            self.logger.info(f"🎲 Симуляция сценария: {scenario.get('name', 'unnamed')}")
            
            # Создаем тестовый сигнал на основе сценария
            test_signal = self._create_test_signal(scenario)
            
            # Выполняем оценку риска
            assessment = await self.assess_trade_risk(test_signal, {'simulation': True})
            
            # Анализируем результат
            simulation_result = {
                'scenario': scenario,
                'assessment': {
                    'decision': assessment.decision.value,
                    'risk_score': assessment.risk_score,
                    'confidence': assessment.confidence,
                    'is_approved': assessment.is_approved,
                    'has_restrictions': assessment.has_restrictions,
                    'warnings': assessment.warnings,
                    'recommendations': assessment.recommendations
                },
                'analysis': {
                    'would_trigger_emergency': assessment.is_emergency,
                    'estimated_impact': self._estimate_scenario_impact(scenario, assessment),
                    'risk_factors': assessment.factors
                }
            }
            
            self.logger.info(f"✅ Симуляция завершена: {assessment.decision.value}")
            return simulation_result
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка симуляции: {e}")
            return {'error': str(e)}
    
    # ================= ПРИВАТНЫЕ МЕТОДЫ =================
    
    async def _perform_risk_assessment(
        self,
        signal: TradeSignal,
        context: Optional[Dict[str, Any]]
    ) -> RiskAssessmentResult:
        """🔍 Выполнение оценки риска"""
        
        # Получаем оценку от domain risk manager
        domain_assessment = await self.risk_manager.assess_trade_risk(signal)
        
        # Дополнительные проверки на application уровне
        additional_checks = await self._perform_additional_checks(signal, context)
        
        # Объединяем результаты
        combined_result = self._combine_assessments(domain_assessment, additional_checks)
        
        return combined_result
    
    async def _perform_additional_checks(
        self,
        signal: TradeSignal,
        context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """🔍 Дополнительные проверки на уровне сервиса"""
        
        checks = {
            'context_validation': True,
            'timing_check': True,
            'market_conditions': True,
            'position_correlation': True
        }
        
        try:
            # Проверка контекста
            if context and context.get('simulation'):
                checks['context_validation'] = True  # Симуляция всегда проходит
            else:
                checks['context_validation'] = await self._validate_trading_context(context)
            
            # Проверка времени торговли
            checks['timing_check'] = self._check_trading_hours()
            
            # Проверка рыночных условий
            checks['market_conditions'] = await self._check_market_conditions()
            
            # Проверка корреляции с существующими позициями
            checks['position_correlation'] = await self._check_position_correlation(signal)
            
        except Exception as e:
            self.logger.warning(f"⚠️ Ошибка дополнительных проверок: {e}")
            checks['error'] = str(e)
        
        return checks
    
    def _combine_assessments(
        self,
        domain_assessment: Any,
        additional_checks: Dict[str, Any]
    ) -> RiskAssessmentResult:
        """🔗 Объединение результатов оценки"""
        
        # Определяем базовое решение из domain assessment
        base_decision = RiskDecision.APPROVE
        risk_score = 0.3
        confidence = 0.8
        
        if hasattr(domain_assessment, 'action'):
            action_value = getattr(domain_assessment.action, 'value', str(domain_assessment.action))
            if action_value == 'block':
                base_decision = RiskDecision.REJECT
                risk_score = 0.8
            elif action_value == 'emergency_exit':
                base_decision = RiskDecision.EMERGENCY_STOP
                risk_score = 1.0
        
        # Учитываем дополнительные проверки
        warnings = []
        recommendations = []
        
        if not additional_checks.get('timing_check', True):
            base_decision = RiskDecision.REJECT
            warnings.append("Торговля вне разрешенных часов")
        
        if not additional_checks.get('market_conditions', True):
            if base_decision == RiskDecision.APPROVE:
                base_decision = RiskDecision.APPROVE_WITH_LIMITS
            warnings.append("Неблагоприятные рыночные условия")
        
        if not additional_checks.get('position_correlation', True):
            recommendations.append("Рассмотрите корреляцию с существующими позициями")
        
        # Собираем факторы
        factors = {
            'domain_assessment': str(domain_assessment),
            'additional_checks': additional_checks,
            'risk_tolerance': str(self.risk_tolerance)
        }
        
        return RiskAssessmentResult(
            decision=base_decision,
            risk_score=risk_score,
            confidence=confidence,
            factors=factors,
            recommendations=recommendations,
            warnings=warnings
        )
    
    async def _get_emergency_stop_reason(self) -> str:
        """🚨 Получение причины аварийной остановки"""
        try:
            # Проверяем различные условия
            reasons = []
            
            if self.monitoring_state.daily_loss >= self.monitoring_state.daily_loss_limit:
                reasons.append(f"Превышен дневной лимит потерь: {self.monitoring_state.daily_loss}")
            
            if self.monitoring_state.current_drawdown >= self.monitoring_state.max_drawdown_limit:
                reasons.append(f"Превышен лимит просадки: {self.monitoring_state.current_drawdown}")
            
            if self.monitoring_state.consecutive_losses >= 5:
                reasons.append(f"Слишком много убыточных сделок подряд: {self.monitoring_state.consecutive_losses}")
            
            return "; ".join(reasons) if reasons else "Неизвестная причина"
            
        except Exception as e:
            return f"Ошибка определения причины: {e}"
    
    async def _emergency_close_positions(self, reason: str) -> None:
        """🚨 Экстренное закрытие позиций"""
        try:
            current_position = await self.position_manager.get_current_position(self.trading_pair)
            
            if current_position and not current_position.is_empty:
                self.logger.critical(f"🚨 Экстренное закрытие позиции: {current_position.quantity}")
                
                # Здесь должна быть логика закрытия позиции
                # Пока оставляем заглушку
                
        except Exception as e:
            self.logger.critical(f"💥 Ошибка экстренного закрытия позиций: {e}")
    
    async def _update_monitoring_state(self, assessment: RiskAssessmentResult) -> None:
        """📊 Обновление состояния мониторинга"""
        self.monitoring_state.last_assessment_time = datetime.now()
        
        if not assessment.is_approved:
            self.monitoring_state.risk_violations_today += 1
    
    async def _calculate_current_risk_metrics(
        self,
        position: Optional[Position],
        market_data: MarketData
    ) -> Dict[str, Any]:
        """📈 Расчет текущих метрик риска"""
        try:
            metrics = {
                'position_risk': 0.0,
                'market_volatility': 0.0,
                'liquidity_risk': 0.0,
                'overall_risk': 0.0
            }
            
            if position and not position.is_empty:
                # Рассчитываем риск позиции
                position_value = position.quantity * market_data.current_price.value
                portfolio_percentage = position_value / self.initial_balance.amount
                metrics['position_risk'] = float(portfolio_percentage)
            
            # Рассчитываем волатильность рынка (упрощенно)
            if hasattr(market_data, 'price_change_24h'):
                metrics['market_volatility'] = abs(float(market_data.price_change_24h))
            
            # Общий риск как среднее
            metrics['overall_risk'] = (
                metrics['position_risk'] + 
                metrics['market_volatility'] + 
                metrics['liquidity_risk']
            ) / 3.0
            
            return metrics
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка расчета метрик риска: {e}")
            return {'error': str(e)}
    
    def _analyze_assessment_history(self) -> Dict[str, Any]:
        """📊 Анализ истории оценок"""
        if not self.assessment_history:
            return {'insufficient_data': True}
        
        recent_assessments = self.assessment_history[-50:]  # Последние 50
        
        approval_rate = sum(1 for a in recent_assessments if a.is_approved) / len(recent_assessments)
        avg_risk_score = sum(a.risk_score for a in recent_assessments) / len(recent_assessments)
        avg_confidence = sum(a.confidence for a in recent_assessments) / len(recent_assessments)
        
        return {
            'total_assessments': len(self.assessment_history),
            'recent_assessments': len(recent_assessments),
            'approval_rate': approval_rate,
            'average_risk_score': avg_risk_score,
            'average_confidence': avg_confidence,
            'emergency_stops': sum(1 for a in recent_assessments if a.is_emergency)
        }
    
    def _get_cache_key(self, signal: TradeSignal) -> str:
        """🔑 Генерация ключа кэша"""
        return f"{signal.signal_type}_{signal.pair}_{signal.quantity}_{signal.confidence}"
    
    def _get_cached_assessment(self, cache_key: str) -> Optional[RiskAssessmentResult]:
        """💾 Получение кэшированной оценки"""
        if cache_key in self._assessment_cache:
            result, timestamp = self._assessment_cache[cache_key]
            if datetime.now() - timestamp < self.cache_ttl:
                return result
            else:
                del self._assessment_cache[cache_key]
        return None
    
    def _cache_assessment(self, cache_key: str, result: RiskAssessmentResult) -> None:
        """💾 Кэширование оценки"""
        self._assessment_cache[cache_key] = (result, datetime.now())
        
        # Ограничиваем размер кэша
        if len(self._assessment_cache) > 100:
            oldest_key = min(self._assessment_cache.keys(), 
                           key=lambda k: self._assessment_cache[k][1])
            del self._assessment_cache[oldest_key]
    
    def _validate_authorization(self, code: str) -> bool:
        """🔐 Валидация кода авторизации"""
        # Здесь должна быть реальная проверка авторизации
        return code == "EMERGENCY_RESET_2024"
    
    def _validate_risk_limits(self, limits: Dict[str, Decimal]) -> None:
        """✅ Валидация лимитов риска"""
        for key, value in limits.items():
            if value < 0:
                raise ValidationError(f"Лимит {key} не может быть отрицательным")
            
            if key == 'position_size_limit' and value > 1:
                raise ValidationError("Лимит размера позиции не может превышать 100%")
    
    async def _validate_trading_context(self, context: Optional[Dict[str, Any]]) -> bool:
        """✅ Валидация торгового контекста"""
        if not context:
            return True  # Отсутствие контекста не критично
        
        # Здесь могут быть дополнительные проверки контекста
        return True
    
    def _check_trading_hours(self) -> bool:
        """🕐 Проверка торговых часов"""
        # Крипто торгуется 24/7, но можно добавить ограничения
        now = datetime.now()
        
        # Пример: не торговать в выходные (опционально)
        # if now.weekday() >= 5:  # Суббота = 5, Воскресенье = 6
        #     return False
        
        return True
    
    async def _check_market_conditions(self) -> bool:
        """📈 Проверка рыночных условий"""
        try:
            market_data = await self.market_data_provider.get_market_data(self.trading_pair)
            
            # Простая проверка волатильности
            if hasattr(market_data, 'volatility') and market_data.volatility > 0.1:  # 10%
                return False
            
            return True
            
        except Exception as e:
            self.logger.warning(f"⚠️ Ошибка проверки рыночных условий: {e}")
            return True  # В случае ошибки разрешаем торговлю
    
    async def _check_position_correlation(self, signal: TradeSignal) -> bool:
        """🔗 Проверка корреляции позиций"""
        try:
            current_position = await self.position_manager.get_current_position(self.trading_pair)
            
            # Если позиции нет - корреляция не важна
            if not current_position or current_position.is_empty:
                return True
            
            # Простая проверка: не увеличивать позицию слишком сильно
            if signal.signal_type == StrategySignalType.BUY:
                if current_position.quantity > self.initial_balance.amount * self.monitoring_state.position_size_limit:
                    return False
            
            return True
            
        except Exception as e:
            self.logger.warning(f"⚠️ Ошибка проверки корреляции: {e}")
            return True
    
    def _create_test_signal(self, scenario: Dict[str, Any]) -> TradeSignal:
        """🎯 Создание тестового сигнала для симуляции"""
        # Создаем тестовый сигнал на основе сценария
        # Здесь должна быть реальная реализация создания TradeSignal
        return None  # Заглушка
    
    def _estimate_scenario_impact(
        self,
        scenario: Dict[str, Any],
        assessment: RiskAssessmentResult
    ) -> Dict[str, Any]:
        """📊 Оценка влияния сценария"""
        return {
            'potential_loss': scenario.get('expected_loss', 0),
            'probability': scenario.get('probability', 0.5),
            'impact_severity': 'high' if assessment.risk_score > 0.7 else 'medium' if assessment.risk_score > 0.4 else 'low'
        }
    
    async def _publish_risk_assessment_event(
        self,
        signal: TradeSignal,
        result: RiskAssessmentResult
    ) -> None:
        """📡 Публикация события оценки риска"""
        try:
            event = DomainEvent()
            event.event_type = "risk_assessment_completed"
            event.source = "risk_management_service"
            event.metadata = {
                'signal_type': str(signal.signal_type) if signal else 'unknown',
                'decision': result.decision.value,
                'risk_score': result.risk_score,
                'confidence': result.confidence,
                'has_warnings': len(result.warnings) > 0
            }
            
            await publish_event(event)
            
        except Exception as e:
            self.logger.warning(f"⚠️ Ошибка публикации события: {e}")
    
    async def _publish_emergency_event(self, reason: str) -> None:
        """📡 Публикация события аварийной остановки"""
        try:
            event = DomainEvent()
            event.event_type = "emergency_stop_triggered"
            event.source = "risk_management_service"
            event.metadata = {
                'reason': reason,
                'timestamp': datetime.now().isoformat(),
                'monitoring_state': {
                    'daily_loss': str(self.monitoring_state.daily_loss),
                    'consecutive_losses': self.monitoring_state.consecutive_losses,
                    'emergency_stops_count': self.monitoring_state.emergency_stops_count
                }
            }
            
            await publish_event(event)
            
        except Exception as e:
            self.logger.critical(f"💥 Ошибка публикации аварийного события: {e}")
    
    async def _publish_emergency_reset_event(self) -> None:
        """📡 Публикация события сброса аварийной остановки"""
        try:
            event = DomainEvent()
            event.event_type = "emergency_stop_reset"
            event.source = "risk_management_service"
            event.metadata = {
                'timestamp': datetime.now().isoformat(),
                'reset_by': 'system'  # Можно добавить информацию о пользователе
            }
            
            await publish_event(event)
            
        except Exception as e:
            self.logger.warning(f"⚠️ Ошибка публикации события сброса: {e}")
    
    async def _publish_limits_update_event(self, new_limits: Dict[str, Decimal]) -> None:
        """📡 Публикация события обновления лимитов"""
        try:
            event = DomainEvent()
            event.event_type = "risk_limits_updated"
            event.source = "risk_management_service"
            event.metadata = {
                'new_limits': {k: str(v) for k, v in new_limits.items()},
                'timestamp': datetime.now().isoformat()
            }
            
            await publish_event(event)
            
        except Exception as e:
            self.logger.warning(f"⚠️ Ошибка публикации события обновления лимитов: {e}")
