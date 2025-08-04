#!/usr/bin/env python3
"""🎮 Миграция Part 7 - Слой приложения"""

import logging
from pathlib import Path


class Migration:
    """🎮 Миграция слоя приложения"""
    
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.src_dir = project_root / "src"
        self.application_dir = self.src_dir / "application"
        self.logger = logging.getLogger(__name__)

    def execute(self) -> bool:
        """🚀 Выполнение миграции"""
        try:
            self.logger.info("🎮 Создание слоя приложения...")
            
            # Создаем структуру директорий
            self._create_directory_structure()
            
            # Создаем торговый сервис
            self._create_trading_service()
            
            # Создаем оркестратор
            self._create_orchestrator()
            
            self.logger.info("✅ Слой приложения создан")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка создания слоя приложения: {e}")
            return False

    def _create_directory_structure(self):
        """📁 Создание структуры директорий"""
        dirs_to_create = [
            self.application_dir,
            self.application_dir / "services",
            self.application_dir / "orchestrators",
        ]
        
        for dir_path in dirs_to_create:
            dir_path.mkdir(parents=True, exist_ok=True)
            
            # Создаем __init__.py
            init_file = dir_path / "__init__.py"
            if not init_file.exists():
                init_file.write_text('"""🎮 Слой приложения"""\n')

    def _create_trading_service(self):
        """🎯 Создание торгового сервиса"""
        trading_service_content = '''#!/usr/bin/env python3
"""🎯 Торговый сервис"""

import asyncio
import logging
from typing import Dict, Any, Optional, List
from decimal import Decimal
from datetime import datetime

from ...core.interfaces import IExchangeAPI, ITradingStrategy, IRiskManager, IPositionManager
from ...core.models import TradeSignal, MarketData, Position, TradingPair, SignalAction
from ...core.exceptions import TradingSystemError, APIError, StrategyError
from ...core.base import BaseService
from ...infrastructure.di_container import injectable


@injectable
class TradingService(BaseService):
    """🎯 Основной торговый сервис"""
    
    def __init__(self, 
                 exchange_api: IExchangeAPI,
                 risk_manager: IRiskManager,
                 position_manager: IPositionManager):
        super().__init__("trading_service")
        
        self.exchange_api = exchange_api
        self.risk_manager = risk_manager
        self.position_manager = position_manager
        
        # Активные стратегии
        self.strategies: List[ITradingStrategy] = []
        
        # Состояние сервиса
        self.is_trading_enabled = True
        self.last_trade_time: Optional[datetime] = None
        self.active_orders: Dict[str, Dict[str, Any]] = {}
        
        # Статистика
        self.trades_count = 0
        self.successful_trades = 0
        
    async def _initialize_implementation(self) -> None:
        """🚀 Инициализация торгового сервиса"""
        # Проверяем подключение к API
        try:
            # Тестовый запрос
            await self.exchange_api.get_balance("EUR")
            self.logger.info("✅ Подключение к API проверено")
        except Exception as e:
            self.logger.error(f"❌ Ошибка подключения к API: {e}")
            raise TradingSystemError("Не удалось подключиться к API биржи")
    
    def add_strategy(self, strategy: ITradingStrategy) -> None:
        """➕ Добавление торговой стратегии"""
        self.strategies.append(strategy)
        self.logger.info(f"➕ Добавлена стратегия: {strategy.get_strategy_name()}")
    
    def remove_strategy(self, strategy_name: str) -> bool:
        """➖ Удаление торговой стратегии"""
        for i, strategy in enumerate(self.strategies):
            if strategy.get_strategy_name() == strategy_name:
                del self.strategies[i]
                self.logger.info(f"➖ Удалена стратегия: {strategy_name}")
                return True
        return False
    
    async def execute_trading_cycle(self, trading_pair: TradingPair) -> Dict[str, Any]:
        """🔄 Выполнение торгового цикла"""
        try:
            # Получаем рыночные данные
            market_data = await self._get_market_data(trading_pair)
            
            # Получаем текущую позицию
            position = await self.position_manager.get_position(trading_pair.base)
            
            # Анализируем сигналы от всех стратегий
            signals = await self._analyze_strategies(market_data, position)
            
            # Выбираем лучший сигнал
            best_signal = await self._select_best_signal(signals)
            
            if not best_signal:
                return {
                    'action': 'hold',
                    'reason': 'Нет торговых сигналов',
                    'signals_count': len(signals)
                }
            
            # Проверяем риски
            risk_assessment = await self.risk_manager.assess_risk(best_signal, position)
            
            if not risk_assessment['can_execute']:
                return {
                    'action': 'blocked',
                    'reason': f"Заблокировано риск-менеджером: {'; '.join(risk_assessment['risk_factors'])}",
                    'risk_score': risk_assessment['risk_score']
                }
            
            # Исполняем сигнал
            execution_result = await self._execute_signal(best_signal)
            
            return {
                'action': best_signal.action.value,
                'signal': {
                    'strategy': best_signal.strategy_name,
                    'confidence': best_signal.confidence,
                    'reason': best_signal.reason,
                    'quantity': float(best_signal.quantity),
                    'price': float(best_signal.price) if best_signal.price else None
                },
                'execution': execution_result,
                'risk_assessment': risk_assessment
            }
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка торгового цикла: {e}")
            return {
                'action': 'error',
                'reason': f"Ошибка: {e}",
                'error_type': type(e).__name__
            }
    
    async def _get_market_data(self, trading_pair: TradingPair) -> MarketData:
        """📊 Получение рыночных данных"""
        try:
            # Получаем текущую цену
            current_price = await self.exchange_api.get_current_price(str(trading_pair))
            
            # Получаем баланс для дополнительной информации
            balance = await self.exchange_api.get_balance(trading_pair.quote)
            
            # Создаем объект рыночных данных
            market_data = MarketData(
                trading_pair=trading_pair,
                current_price=current_price,
                timestamp=datetime.now()
            )
            
            # Добавляем дополнительную информацию
            market_data.additional_data['balance'] = float(balance)
            
            return market_data
            
        except APIError as e:
            self.logger.error(f"❌ Ошибка получения рыночных данных: {e}")
            raise
        except Exception as e:
            self.logger.error(f"❌ Неожиданная ошибка получения данных: {e}")
            raise TradingSystemError(f"Ошибка получения рыночных данных: {e}")
    
    async def _analyze_strategies(self, market_data: MarketData, 
                                 position: Optional[Position]) -> List[TradeSignal]:
        """🧠 Анализ сигналов от всех стратегий"""
        signals = []
        
        for strategy in self.strategies:
            try:
                signal = await strategy.analyze(market_data, position)
                if signal and signal.action != SignalAction.HOLD:
                    signals.append(signal)
                    self.logger.debug(f"📈 Сигнал от {strategy.get_strategy_name()}: "
                                    f"{signal.action.value} {signal.confidence:.2f}")
            except StrategyError as e:
                self.logger.warning(f"⚠️ Ошибка стратегии {strategy.get_strategy_name()}: {e}")
            except Exception as e:
                self.logger.error(f"❌ Неожиданная ошибка стратегии {strategy.get_strategy_name()}: {e}")
        
        return signals
    
    async def _select_best_signal(self, signals: List[TradeSignal]) -> Optional[TradeSignal]:
        """🎯 Выбор лучшего сигнала"""
        if not signals:
            return None
        
        # Сортируем по приоритету и уверенности
        def signal_priority(signal: TradeSignal) -> float:
            # Аварийный выход имеет наивысший приоритет
            if signal.action == SignalAction.EMERGENCY_EXIT:
                return 1000.0 + signal.confidence
            elif signal.action == SignalAction.SELL:
                return 100.0 + signal.confidence
            elif signal.action == SignalAction.BUY:
                return 50.0 + signal.confidence
            else:
                return signal.confidence
        
        best_signal = max(signals, key=signal_priority)
        
        self.logger.info(f"🎯 Выбран сигнал: {best_signal.strategy_name} "
                        f"{best_signal.action.value} confidence={best_signal.confidence:.2f}")
        
        return best_signal
    
    async def _execute_signal(self, signal: TradeSignal) -> Dict[str, Any]:
        """⚡ Исполнение торгового сигнала"""
        try:
            if not self.is_trading_enabled:
                return {
                    'success': False,
                    'reason': 'Торговля отключена',
                    'order_id': None
                }
            
            # Определяем тип ордера
            order_type = self._get_order_type(signal)
            
            # Создаем ордер
            order_result = await self.exchange_api.create_order(
                pair=str(signal.trading_pair),
                quantity=signal.quantity,
                price=signal.price or Decimal('0'),
                order_type=order_type
            )
            
            # Сохраняем информацию об ордере
            order_id = order_result.get('order_id')
            if order_id:
                self.active_orders[order_id] = {
                    'signal': signal,
                    'created_at': datetime.now(),
                    'status': 'created'
                }
            
            # Обновляем статистику
            self.trades_count += 1
            self.last_trade_time = datetime.now()
            
            self.logger.info(f"⚡ Ордер создан: {order_type} {signal.quantity} "
                           f"по {signal.price} (ID: {order_id})")
            
            return {
                'success': True,
                'order_id': order_id,
                'order_type': order_type,
                'quantity': float(signal.quantity),
                'price': float(signal.price) if signal.price else None,
                'created_at': datetime.now().isoformat()
            }
            
        except APIError as e:
            self.logger.error(f"❌ Ошибка API при создании ордера: {e}")
            return {
                'success': False,
                'reason': f'API ошибка: {e}',
                'order_id': None
            }
        except Exception as e:
            self.logger.error(f"❌ Неожиданная ошибка исполнения: {e}")
            return {
                'success': False,
                'reason': f'Ошибка исполнения: {e}',
                'order_id': None
            }
    
    def _get_order_type(self, signal: TradeSignal) -> str:
        """📋 Определение типа ордера"""
        if signal.action == SignalAction.BUY:
            return "buy" if signal.price is None else "limit_buy"
        elif signal.action in [SignalAction.SELL, SignalAction.EMERGENCY_EXIT]:
            return "sell" if signal.price is None else "limit_sell"
        else:
            raise ValueError(f"Неподдерживаемое действие сигнала: {signal.action}")
    
    def enable_trading(self) -> None:
        """✅ Включение торговли"""
        self.is_trading_enabled = True
        self.logger.info("✅ Торговля включена")
    
    def disable_trading(self) -> None:
        """🚫 Отключение торговли"""
        self.is_trading_enabled = False
        self.logger.warning("🚫 Торговля отключена")
    
    def get_service_status(self) -> Dict[str, Any]:
        """📊 Получение статуса сервиса"""
        base_status = super().get_status()
        
        trading_status = {
            'is_trading_enabled': self.is_trading_enabled,
            'strategies_count': len(self.strategies),
            'active_orders_count': len(self.active_orders),
            'total_trades': self.trades_count,
            'successful_trades': self.successful_trades,
            'success_rate': (self.successful_trades / max(1, self.trades_count)) * 100,
            'last_trade_time': self.last_trade_time.isoformat() if self.last_trade_time else None
        }
        
        return {**base_status, **trading_status}


if __name__ == "__main__":
    print("🎯 Торговый сервис готов к использованию")
'''

        service_file = self.application_dir / "services" / "trading_service.py"
        service_file.write_text(trading_service_content)
        self.logger.info("  ✅ Создан services/trading_service.py")

    def _create_orchestrator(self):
        """🎼 Создание оркестратора"""
        orchestrator_content = '''#!/usr/bin/env python3
"""🎼 Торговый оркестратор"""

import asyncio
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta

from ...core.models import TradingPair, SystemStatus
from ...core.interfaces import IHealthChecker
from ...infrastructure.di_container import injectable
from ..services.trading_service import TradingService


@injectable
class TradingOrchestrator:
    """🎼 Главный оркестратор торговых операций"""
    
    def __init__(self, 
                 trading_service: TradingService,
                 health_checker: IHealthChecker):
        self.trading_service = trading_service
        self.health_checker = health_checker
        self.logger = logging.getLogger(f"{__name__}.TradingOrchestrator")
        
        # Состояние оркестратора
        self.is_running = False
        self.trading_pairs: List[TradingPair] = []
        self.cycle_interval = 15  # секунд
        self.last_cycle_time: Optional[datetime] = None
        
        # Статистика
        self.total_cycles = 0
        self.successful_cycles = 0
        self.errors_count = 0
        
        self.logger.info("🎼 Торговый оркестратор инициализирован")
    
    def add_trading_pair(self, trading_pair: TradingPair) -> None:
        """➕ Добавление торговой пары"""
        self.trading_pairs.append(trading_pair)
        self.logger.info(f"➕ Добавлена торговая пара: {trading_pair}")
    
    def set_cycle_interval(self, seconds: int) -> None:
        """⏰ Установка интервала торгового цикла"""
        self.cycle_interval = max(5, seconds)  # Минимум 5 секунд
        self.logger.info(f"⏰ Интервал торгового цикла: {self.cycle_interval}с")
    
    async def start(self) -> None:
        """🚀 Запуск торгового оркестратора"""
        if self.is_running:
            self.logger.warning("⚠️ Оркестратор уже запущен")
            return
        
        self.logger.info("🚀 Запуск торгового оркестратора...")
        
        # Инициализируем торговый сервис
        if not await self.trading_service.initialize():
            raise RuntimeError("Не удалось инициализировать торговый сервис")
        
        self.is_running = True
        
        try:
            await self._main_loop()
        except Exception as e:
            self.logger.error(f"❌ Ошибка в главном цикле: {e}")
            raise
        finally:
            await self.stop()
    
    async def stop(self) -> None:
        """🛑 Остановка торгового оркестратора"""
        if not self.is_running:
            return
        
        self.logger.info("🛑 Остановка торгового оркестратора...")
        self.is_running = False
        
        # Завершаем торговый сервис
        await self.trading_service.shutdown()
        
        self.logger.info("✅ Торговый оркестратор остановлен")
    
    async def _main_loop(self) -> None:
        """🔄 Главный цикл торговых операций"""
        self.logger.info("🔄 Запуск главного торгового цикла")
        
        while self.is_running:
            cycle_start = datetime.now()
            
            try:
                # Проверяем здоровье системы
                health_status = await self.health_checker.check_health()
                
                if not health_status.get('overall_status') == 'healthy':
                    self.logger.warning("⚠️ Система нездорова, пропускаем цикл")
                    await asyncio.sleep(self.cycle_interval)
                    continue
                
                # Выполняем торговые циклы для всех пар
                cycle_results = []
                for trading_pair in self.trading_pairs:
                    try:
                        result = await self.trading_service.execute_trading_cycle(trading_pair)
                        cycle_results.append({
                            'trading_pair': str(trading_pair),
                            'result': result,
                            'success': result.get('action') != 'error'
                        })
                        
                        # Логируем результат
                        action = result.get('action', 'unknown')
                        reason = result.get('reason', 'No reason')
                        
                        if action == 'error':
                            self.logger.error(f"❌ {trading_pair}: {reason}")
                        elif action in ['buy', 'sell', 'emergency_exit']:
                            self.logger.info(f"💱 {trading_pair}: {action.upper()} - {reason}")
                        else:
                            self.logger.debug(f"📊 {trading_pair}: {action} - {reason}")
                        
                    except Exception as e:
                        self.logger.error(f"❌ Ошибка цикла для {trading_pair}: {e}")
                        cycle_results.append({
                            'trading_pair': str(trading_pair),
                            'result': {'action': 'error', 'reason': str(e)},
                            'success': False
                        })
                
                # Обновляем статистику
                self.total_cycles += 1
                successful_pairs = sum(1 for r in cycle_results if r['success'])
                
                if successful_pairs == len(self.trading_pairs):
                    self.successful_cycles += 1
                else:
                    self.errors_count += 1
                
                self.last_cycle_time = cycle_start
                
                # Логируем статистику цикла
                cycle_duration = (datetime.now() - cycle_start).total_seconds()
                self.logger.info(f"🔄 Цикл #{self.total_cycles} завершен за {cycle_duration:.2f}с, "
                               f"успешно: {successful_pairs}/{len(self.trading_pairs)}")
                
            except Exception as e:
                self.logger.error(f"❌ Ошибка в торговом цикле: {e}")
                self.errors_count += 1
            
            # Ждем до следующего цикла
            await asyncio.sleep(self.cycle_interval)
    
    async def execute_manual_cycle(self, trading_pair: TradingPair) -> Dict[str, Any]:
        """🎯 Ручное выполнение торгового цикла"""
        self.logger.info(f"🎯 Ручное выполнение цикла для {trading_pair}")
        
        try:
            result = await self.trading_service.execute_trading_cycle(trading_pair)
            
            self.logger.info(f"✅ Ручной цикл завершен: {result.get('action', 'unknown')}")
            return result
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка ручного цикла: {e}")
            return {
                'action': 'error',
                'reason': str(e),
                'error_type': type(e).__name__
            }
    
    def get_status(self) -> Dict[str, Any]:
        """📊 Получение статуса оркестратора"""
        uptime_seconds = 0
        if self.last_cycle_time:
            uptime_seconds = int((datetime.now() - self.last_cycle_time).total_seconds())
        
        success_rate = 0.0
        if self.total_cycles > 0:
            success_rate = (self.successful_cycles / self.total_cycles) * 100
        
        return {
            'is_running': self.is_running,
            'trading_pairs_count': len(self.trading_pairs),
            'cycle_interval_seconds': self.cycle_interval,
            'total_cycles': self.total_cycles,
            'successful_cycles': self.successful_cycles,
            'errors_count': self.errors_count,
            'success_rate': round(success_rate, 2),
            'last_cycle_time': self.last_cycle_time.isoformat() if self.last_cycle_time else None,
            'uptime_seconds': uptime_seconds,
            'trading_service_status': self.trading_service.get_service_status()
        }
    
    def get_detailed_status(self) -> Dict[str, Any]:
        """📋 Подробный статус со всеми сервисами"""
        return {
            'orchestrator': self.get_status(),
            'trading_pairs': [str(pair) for pair in self.trading_pairs],
            'performance_metrics': {
                'avg_cycle_duration': self._calculate_avg_cycle_duration(),
                'cycles_per_hour': self._calculate_cycles_per_hour(),
                'error_rate': self._calculate_error_rate()
            }
        }
    
    def _calculate_avg_cycle_duration(self) -> float:
        """📊 Расчет средней длительности цикла"""
        # Упрощенный расчет - в реальности нужно сохранять историю
        return self.cycle_interval * 1.1  # Примерно на 10% больше интервала
    
    def _calculate_cycles_per_hour(self) -> float:
        """📊 Расчет циклов в час"""
        return 3600 / self.cycle_interval
    
    def _calculate_error_rate(self) -> float:
        """📊 Расчет процента ошибок"""
        if self.total_cycles == 0:
            return 0.0
        return (self.errors_count / self.total_cycles) * 100


if __name__ == "__main__":
    print("🎼 Торговый оркестратор готов к использованию")
'''

        orchestrator_file = self.application_dir / "orchestrators" / "trading_orchestrator.py"
        orchestrator_file.write_text(orchestrator_content)
        self.logger.info("  ✅ Создан orchestrators/trading_orchestrator.py")