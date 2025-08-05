from typing import Optional, Dict, Any, List
from decimal import Decimal
from datetime import datetime, timedelta
import logging
import asyncio
from dataclasses import dataclass

# Импорты из Core слоя
try:
    from ...core.interfaces import (
        ITradingStrategy, IRiskManager, IMarketDataProvider,
        IPositionManager, IExchangeAPI, INotificationService
    )
    from ...core.models import (
        TradingPair, Position, TradeSignal, MarketData,
        OrderResult, Money, Price, StrategySignalType
    )
    from ...core.exceptions import (
        TradingError, RiskManagementError, APIError,
        ValidationError, EmergencyStopError
    )
    from ...core.events import DomainEvent, publish_event
    from ...core.di_container import DependencyContainer
except ImportError:
    # Fallback для разработки
    class ITradingStrategy: pass
    class IRiskManager: pass
    class IMarketDataProvider: pass
    class IPositionManager: pass  
    class IExchangeAPI: pass
    class INotificationService: pass
    
    class TradingPair: pass
    class Position: pass
    class TradeSignal: pass
    class MarketData: pass
    class OrderResult: pass
    class Money: pass
    class Price: pass
    class StrategySignalType: pass
    
    class TradingError(Exception): pass
    class RiskManagementError(Exception): pass
    class APIError(Exception): pass
    class ValidationError(Exception): pass
    class EmergencyStopError(Exception): pass
    
    class DomainEvent: pass
    def publish_event(event): pass
    class DependencyContainer: pass


@dataclass
class TradingContext:
    """🎯 Контекст торговой операции"""
    trading_pair: TradingPair
    current_price: Price
    market_data: MarketData
    position: Optional[Position]
    available_balance: Money
    risk_level: str
    session_id: str


@dataclass
class TradingResult:
    """📊 Результат торговой операции"""
    success: bool
    action: str  # 'buy', 'sell', 'hold'
    order_result: Optional[OrderResult] = None
    message: str = ""
    risk_assessment: Dict[str, Any] = None
    execution_time: Optional[datetime] = None
    context: Optional[TradingContext] = None


class TradingOrchestrator:
    """🎯 Главный координатор торговых операций"""
    
    def __init__(
        self,
        container: DependencyContainer,
        trading_pair: TradingPair = None,
        enabled: bool = True
    ):
        # Инжектим зависимости из контейнера
        self.trading_service = container.resolve(ITradingStrategy)
        self.risk_manager = container.resolve(IRiskManager)
        self.market_data_provider = container.resolve(IMarketDataProvider)
        self.position_manager = container.resolve(IPositionManager)
        self.exchange_api = container.resolve(IExchangeAPI)
        self.notification_service = container.resolve(INotificationService)
        
        # Конфигурация
        self.trading_pair = trading_pair or TradingPair("DOGE", "EUR")
        self.enabled = enabled
        
        # Состояние
        self.is_running = False
        self.current_session_id = None
        self.last_execution_time = None
        self.execution_count = 0
        
        # Статистика
        self.stats = {
            'total_cycles': 0,
            'successful_trades': 0,
            'failed_trades': 0,
            'holds': 0,
            'last_error': None
        }
        
        # Логирование
        self.logger = logging.getLogger(__name__)
        
    async def start_trading_session(self) -> str:
        """🚀 Запуск торговой сессии"""
        if self.is_running:
            raise TradingError("Торговая сессия уже запущена")
            
        try:
            # Генерируем ID сессии
            self.current_session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            
            # Проверяем готовность всех компонентов
            await self._validate_components()
            
            # Инициализируем сессию
            await self._initialize_session()
            
            self.is_running = True
            self.logger.info(f"🚀 Торговая сессия запущена: {self.current_session_id}")
            
            # Публикуем событие старта
            await self._publish_session_event("session_started")
            
            return self.current_session_id
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка запуска сессии: {e}")
            raise TradingError(f"Не удалось запустить торговую сессию: {e}")
    
    async def stop_trading_session(self) -> None:
        """⏹️ Остановка торговой сессии"""
        if not self.is_running:
            return
            
        try:
            self.logger.info("⏹️ Остановка торговой сессии...")
            
            # Завершаем активные операции
            await self._finalize_session()
            
            self.is_running = False
            self.current_session_id = None
            
            # Публикуем событие остановки
            await self._publish_session_event("session_stopped")
            
            self.logger.info("✅ Торговая сессия остановлена")
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка остановки сессии: {e}")
    
    async def execute_trading_cycle(self) -> TradingResult:
        """🔄 Выполнение одного торгового цикла"""
        if not self.is_running:
            raise TradingError("Торговая сессия не запущена")
            
        start_time = datetime.now()
        self.stats['total_cycles'] += 1
        
        try:
            self.logger.debug(f"🔄 Начало торгового цикла #{self.stats['total_cycles']}")
            
            # 1. Сбор контекста торговли
            context = await self._collect_trading_context()
            
            # 2. Анализ рынка и получение сигнала
            signal = await self._analyze_market(context)
            
            # 3. Оценка рисков
            risk_assessment = await self._assess_risks(signal, context)
            
            # 4. Принятие решения
            decision = await self._make_trading_decision(signal, risk_assessment, context)
            
            # 5. Исполнение решения
            result = await self._execute_decision(decision, context)
            
            # 6. Обновление статистики
            await self._update_statistics(result)
            
            # 7. Уведомления
            await self._send_notifications(result)
            
            self.last_execution_time = datetime.now()
            execution_duration = (self.last_execution_time - start_time).total_seconds()
            
            self.logger.info(
                f"✅ Торговый цикл завершен за {execution_duration:.2f}с: {result.action}"
            )
            
            return result
            
        except EmergencyStopError as e:
            # Аварийная остановка - критическая ситуация
            self.logger.critical(f"🚨 АВАРИЙНАЯ ОСТАНОВКА: {e}")
            await self.stop_trading_session()
            
            result = TradingResult(
                success=False,
                action="emergency_stop",
                message=f"Аварийная остановка: {e}"
            )
            
            self.stats['failed_trades'] += 1
            return result
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка торгового цикла: {e}")
            self.stats['last_error'] = str(e)
            
            # Пытаемся восстановиться от ошибки
            await self._handle_cycle_error(e)
            
            return TradingResult(
                success=False,
                action="error",
                message=f"Ошибка цикла: {e}"
            )
    
    async def _collect_trading_context(self) -> TradingContext:
        """📊 Сбор контекста для торговли"""
        try:
            # Получаем текущие рыночные данные
            market_data = await self.market_data_provider.get_market_data(self.trading_pair)
            
            # Получаем текущую позицию
            position = await self.position_manager.get_current_position(self.trading_pair)
            
            # Получаем доступный баланс
            balance = await self.exchange_api.get_balance()
            available_balance = Money(
                balance.get(self.trading_pair.quote, {}).get('available', 0),
                self.trading_pair.quote
            )
            
            # Получаем текущую оценку рисков
            risk_level = await self.risk_manager.get_current_risk_level()
            
            return TradingContext(
                trading_pair=self.trading_pair,
                current_price=market_data.current_price,
                market_data=market_data,
                position=position,
                available_balance=available_balance,
                risk_level=risk_level,
                session_id=self.current_session_id
            )
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка сбора контекста: {e}")
            raise TradingError(f"Не удалось собрать торговый контекст: {e}")
    
    async def _analyze_market(self, context: TradingContext) -> TradeSignal:
        """📈 Анализ рынка и получение торгового сигнала"""
        try:
            # Используем торговый сервис для анализа
            decision = await self.trading_service.analyze_market(
                context.trading_pair,
                context.position
            )
            
            return decision.signal
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка анализа рынка: {e}")
            
            # Возвращаем безопасный сигнал HOLD
            return TradeSignal(
                signal_type=StrategySignalType.HOLD,
                pair=context.trading_pair,
                strategy_name="emergency_hold",
                reason=f"Ошибка анализа: {e}",
                confidence=0.0
            )
    
    async def _assess_risks(
        self, 
        signal: TradeSignal, 
        context: TradingContext
    ) -> Dict[str, Any]:
        """🛡️ Оценка рисков торговой операции"""
        try:
            # Проверяем экстренную остановку
            if await self.risk_manager.should_emergency_stop():
                raise EmergencyStopError("Активирована аварийная остановка")
            
            # Оцениваем риски сигнала
            assessment = await self.risk_manager.assess_trade_risk(signal)
            
            return {
                'risk_level': assessment.severity.value if hasattr(assessment, 'severity') else 'unknown',
                'approved': assessment.action.value == 'allow' if hasattr(assessment, 'action') else False,
                'recommendation': getattr(assessment, 'recommendation', ''),
                'score': getattr(assessment, 'score', 0.0),
                'details': assessment
            }
            
        except EmergencyStopError:
            raise  # Пробрасываем аварийную остановку
        except Exception as e:
            self.logger.error(f"❌ Ошибка оценки рисков: {e}")
            
            # В случае ошибки - консервативная оценка
            return {
                'risk_level': 'high',
                'approved': False,
                'recommendation': 'Отклонено из-за ошибки оценки рисков',
                'score': 0.0,
                'error': str(e)
            }
    
    async def _make_trading_decision(
        self,
        signal: TradeSignal,
        risk_assessment: Dict[str, Any],
        context: TradingContext
    ) -> Dict[str, Any]:
        """🎯 Принятие финального торгового решения"""
        
        # Если риск-менеджер не одобрил - отклоняем
        if not risk_assessment.get('approved', False):
            return {
                'action': 'hold',
                'reason': f"Отклонено риск-менеджментом: {risk_assessment.get('recommendation', '')}",
                'signal': signal,
                'risk_assessment': risk_assessment,
                'approved': False
            }
        
        # Если сигнал HOLD - держим позицию
        if signal.signal_type == StrategySignalType.HOLD:
            return {
                'action': 'hold',
                'reason': signal.reason,
                'signal': signal,
                'risk_assessment': risk_assessment,
                'approved': True
            }
        
        # Проверяем достаточность баланса для покупки
        if signal.signal_type == StrategySignalType.BUY:
            required_amount = signal.quantity * signal.price if signal.price else Decimal('0')
            if context.available_balance.amount < required_amount:
                return {
                    'action': 'hold',
                    'reason': f'Недостаточно средств: нужно {required_amount}, доступно {context.available_balance.amount}',
                    'signal': signal,
                    'risk_assessment': risk_assessment,
                    'approved': False
                }
        
        # Решение одобрено
        return {
            'action': signal.signal_type.value.lower(),
            'reason': signal.reason,
            'signal': signal,
            'risk_assessment': risk_assessment,
            'approved': True,
            'quantity': signal.quantity,
            'price': signal.price
        }
    
    async def _execute_decision(
        self,
        decision: Dict[str, Any],
        context: TradingContext
    ) -> TradingResult:
        """⚡ Исполнение торгового решения"""
        
        action = decision['action']
        
        try:
            if action == 'hold':
                self.stats['holds'] += 1
                return TradingResult(
                    success=True,
                    action='hold',
                    message=decision['reason'],
                    risk_assessment=decision['risk_assessment'],
                    execution_time=datetime.now(),
                    context=context
                )
            
            elif action in ['buy', 'sell']:
                # Исполняем торговую операцию
                order_result = await self._execute_trade_order(decision, context)
                
                if order_result and getattr(order_result, 'success', False):
                    self.stats['successful_trades'] += 1
                    
                    # Обновляем позицию
                    await self.position_manager.update_position_from_trade(order_result)
                    
                    return TradingResult(
                        success=True,
                        action=action,
                        order_result=order_result,
                        message=f"Успешно выполнен {action}",
                        risk_assessment=decision['risk_assessment'],
                        execution_time=datetime.now(),
                        context=context
                    )
                else:
                    self.stats['failed_trades'] += 1
                    return TradingResult(
                        success=False,
                        action=action,
                        order_result=order_result,
                        message=f"Ошибка исполнения {action}",
                        risk_assessment=decision['risk_assessment'],
                        execution_time=datetime.now(),
                        context=context
                    )
            
            else:
                raise TradingError(f"Неизвестное действие: {action}")
                
        except Exception as e:
            self.logger.error(f"❌ Ошибка исполнения решения: {e}")
            self.stats['failed_trades'] += 1
            
            return TradingResult(
                success=False,
                action=action,
                message=f"Ошибка исполнения: {e}",
                risk_assessment=decision['risk_assessment'],
                execution_time=datetime.now(),
                context=context
            )
    
    async def _execute_trade_order(
        self,
        decision: Dict[str, Any],
        context: TradingContext
    ) -> Optional[OrderResult]:
        """💱 Исполнение торгового ордера"""
        try:
            signal = decision['signal']
            
            # Создаем ордер через биржевой API
            order_result = await self.exchange_api.create_order(
                pair=str(signal.pair),
                order_type=signal.signal_type.value.lower(),
                quantity=signal.quantity,
                price=signal.price
            )
            
            self.logger.info(f"📋 Ордер создан: {order_result}")
            return order_result
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка создания ордера: {e}")
            return None
    
    async def _validate_components(self) -> None:
        """✅ Проверка готовности всех компонентов"""
        components = {
            'trading_service': self.trading_service,
            'risk_manager': self.risk_manager,
            'market_data_provider': self.market_data_provider,
            'position_manager': self.position_manager,
            'exchange_api': self.exchange_api,
            'notification_service': self.notification_service
        }
        
        for name, component in components.items():
            if component is None:
                raise TradingError(f"Компонент {name} не инициализирован")
    
    async def _initialize_session(self) -> None:
        """🔧 Инициализация торговой сессии"""
        # Сбрасываем статистику сессии
        self.execution_count = 0
        self.last_execution_time = None
        
        # Проверяем подключение к API
        try:
            await self.exchange_api.test_connection()
        except Exception as e:
            raise TradingError(f"Нет подключения к бирже: {e}")
    
    async def _finalize_session(self) -> None:
        """🏁 Завершение торговой сессии"""
        # Сохраняем финальную статистику
        session_stats = {
            'session_id': self.current_session_id,
            'total_cycles': self.stats['total_cycles'],
            'successful_trades': self.stats['successful_trades'],
            'failed_trades': self.stats['failed_trades'],
            'success_rate': (self.stats['successful_trades'] / max(self.stats['total_cycles'], 1)) * 100
        }
        
        self.logger.info(f"📊 Статистика сессии: {session_stats}")
    
    async def _update_statistics(self, result: TradingResult) -> None:
        """📊 Обновление статистики"""
        self.execution_count += 1
        
        # Дополнительная статистика может быть добавлена здесь
        
    async def _send_notifications(self, result: TradingResult) -> None:
        """📢 Отправка уведомлений"""
        try:
            if self.notification_service and result.action != 'hold':
                await self.notification_service.send_trade_notification(result)
        except Exception as e:
            self.logger.warning(f"⚠️ Ошибка отправки уведомления: {e}")
    
    async def _publish_session_event(self, event_type: str) -> None:
        """📡 Публикация события сессии"""
        try:
            event = DomainEvent()
            event.event_type = event_type
            event.source = "trading_orchestrator"
            event.metadata = {
                'session_id': self.current_session_id,
                'trading_pair': str(self.trading_pair),
                'stats': self.stats.copy()
            }
            
            await publish_event(event)
            
        except Exception as e:
            self.logger.warning(f"⚠️ Ошибка публикации события: {e}")
    
    async def _handle_cycle_error(self, error: Exception) -> None:
        """🔧 Обработка ошибки торгового цикла"""
        # Базовая обработка - логирование
        # Можно добавить логику восстановления
        pass
    
    def get_session_statistics(self) -> Dict[str, Any]:
        """📊 Получение статистики сессии"""
        return {
            'session_id': self.current_session_id,
            'is_running': self.is_running,
            'execution_count': self.execution_count,
            'last_execution_time': self.last_execution_time,
            'stats': self.stats.copy(),
            'trading_pair': str(self.trading_pair),
            'enabled': self.enabled
        }
    
    def enable_trading(self) -> None:
        """✅ Включение торговли"""
        self.enabled = True
        self.logger.info("✅ Торговля включена")
    
    def disable_trading(self) -> None:
        """🚫 Отключение торговли"""
        self.enabled = False
        self.logger.info("🚫 Торговля отключена")
