import logging
import time
from abc import ABC, abstractmethod
from typing import Dict, Any, Tuple, Optional, List
from dataclasses import dataclass
from datetime import datetime

@dataclass
class HybridTradeSignal:
    """📊 Гибридный торговый сигнал"""
    action: str
    quantity: float
    price: float
    confidence: float
    reason: str
    strategy: str
    priority: int
    timestamp: datetime

class HybridStrategyManager:
    """🎯 Гибридный менеджер стратегий"""

    def __init__(self, config, api_service, position_manager):
        self.config = config
        self.api_service = api_service
        self.position_manager = position_manager
        self.logger = logging.getLogger(__name__)

        # Подключаем системы безопасности
        self.emergency_exit = None
        self.dca_limiter = None
        self._initialize_safety_systems()

        # Базовые стратегии
        from strategies import PyramidStrategy, DCAStrategy
        self.pyramid_strategy = PyramidStrategy(self.config)
        self.dca_strategy = DCAStrategy(self.config)

        # Приоритеты стратегий
        self.strategy_priorities = {
            'emergency_exit': 1000,
            'pyramid_sell': 100,
            'dca_buy': 50,
            'hold': 1
        }

    def _initialize_safety_systems(self):
        """🛡️ Инициализация систем безопасности"""

        try:
            if getattr(self.config, 'EMERGENCY_EXIT_ENABLED', False):
                from emergency_exit_manager import EmergencyExitManager
                self.emergency_exit = EmergencyExitManager(
                    self.config, self.api_service, self.position_manager
                )
                self.logger.info("🚨 EmergencyExitManager подключен")
        except ImportError:
            self.logger.warning("⚠️ EmergencyExitManager недоступен")

        try:
            if getattr(self.config, 'DCA_LIMITER_ENABLED', False):
                from dca_limiter import DCALimiter
                self.dca_limiter = DCALimiter(self.config)
                self.logger.info("🛡️ DCALimiter подключен")
        except ImportError:
            self.logger.warning("⚠️ DCALimiter недоступен")

    def execute_hybrid_cycle(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """🔄 Гибридный торговый цикл"""

        try:
            # 1. Проверяем аварийные условия
            emergency_result = self._check_emergency_conditions(market_data)
            if emergency_result['should_exit']:
                return self._execute_emergency_exit(emergency_result)

            # 2. Получаем сигналы от стратегий
            position_data = self.position_manager.get_accurate_position_data(self.config.CURRENCY_1)
            signals = []

            # Пирамидальная стратегия
            try:
                pyramid_signal = self.pyramid_strategy.analyze(market_data, position_data)
                if pyramid_signal.action != 'hold':
                    signals.append(HybridTradeSignal(
                        action=pyramid_signal.action,
                        quantity=pyramid_signal.quantity,
                        price=pyramid_signal.price,
                        confidence=pyramid_signal.confidence,
                        reason=pyramid_signal.reason,
                        strategy='pyramid',
                        priority=self.strategy_priorities.get('pyramid_sell', 100),
                        timestamp=datetime.now()
                    ))
            except Exception as e:
                self.logger.error(f"❌ Ошибка пирамидальной стратегии: {e}")

            # DCA стратегия
            try:
                dca_signal = self.dca_strategy.analyze(market_data, position_data)
                if dca_signal.action != 'hold':
                    signals.append(HybridTradeSignal(
                        action=dca_signal.action,
                        quantity=dca_signal.quantity,
                        price=dca_signal.price,
                        confidence=dca_signal.confidence,
                        reason=dca_signal.reason,
                        strategy='dca',
                        priority=self.strategy_priorities.get('dca_buy', 50),
                        timestamp=datetime.now()
                    ))
            except Exception as e:
                self.logger.error(f"❌ Ошибка DCA стратегии: {e}")

            # 3. Выбираем лучший сигнал
            if not signals:
                return {
                    'action': 'hold',
                    'reason': 'Нет торговых сигналов',
                    'success': True,
                    'trade_executed': False
                }

            best_signal = max(signals, key=lambda s: s.priority)

            # 4. Выполняем сигнал
            return self._execute_signal(best_signal)

        except Exception as e:
            self.logger.error(f"❌ Ошибка гибридного цикла: {e}")
            return {
                'action': 'error',
                'reason': str(e),
                'success': False,
                'trade_executed': False
            }

    def _check_emergency_conditions(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """🚨 Проверка аварийных условий"""

        if not self.emergency_exit:
            return {'should_exit': False, 'reason': 'Emergency system not available'}

        try:
            current_price = market_data['current_price']
            emergency_result = self.emergency_exit.check_emergency_conditions(
                self.config.CURRENCY_1, current_price
            )

            return {
                'should_exit': emergency_result.should_exit,
                'reason': emergency_result.reason,
                'urgency': emergency_result.urgency,
                'sell_percentage': emergency_result.sell_percentage,
                'recommended_price': emergency_result.recommended_price
            }

        except Exception as e:
            self.logger.error(f"❌ Ошибка проверки аварийных условий: {e}")
            return {'should_exit': False, 'reason': f'Emergency check error: {e}'}

    def _execute_emergency_exit(self, emergency_result: Dict[str, Any]) -> Dict[str, Any]:
        """🚨 Выполнение аварийного выхода"""

        self.logger.critical(f"🚨 ВЫПОЛНЕНИЕ АВАРИЙНОГО ВЫХОДА: {emergency_result['reason']}")

        if self.emergency_exit:
            exit_result = self.emergency_exit.execute_emergency_exit(
                self.config.CURRENCY_1, emergency_result
            )

            return {
                'action': 'emergency_exit',
                'reason': emergency_result['reason'],
                'success': exit_result['success'],
                'trade_executed': exit_result['success'],
                'emergency_exit': True,
                'urgency': emergency_result.get('urgency', 'high')
            }

        return {
            'action': 'emergency_exit_failed',
            'reason': 'Emergency exit system unavailable',
            'success': False,
            'trade_executed': False
        }

    def _execute_signal(self, signal: HybridTradeSignal) -> Dict[str, Any]:
        """📊 Выполнение торгового сигнала"""

        try:
            if signal.action == 'buy':
                return self._execute_buy(signal)
            elif signal.action == 'sell':
                return self._execute_sell(signal)

            return {
                'action': 'hold',
                'reason': signal.reason,
                'success': True,
                'trade_executed': False
            }

        except Exception as e:
            self.logger.error(f"❌ Ошибка выполнения сигнала: {e}")
            return {
                'action': 'signal_error',
                'reason': str(e),
                'success': False,
                'trade_executed': False
            }

    def _execute_buy(self, signal: HybridTradeSignal) -> Dict[str, Any]:
        """🛒 Выполнение покупки"""
        try:
            result = self.api_service.create_order(
                self.config.get_pair(), signal.quantity, signal.price, 'buy'
            )

            if result.get('result'):
                trade_info = {
                    'type': 'buy',
                    'quantity': signal.quantity,
                    'price': signal.price,
                    'timestamp': int(time.time())
                }
                self.position_manager.update_position(self.config.CURRENCY_1, trade_info)

                self.logger.info(f"✅ {signal.strategy} покупка: {signal.quantity:.4f} по {signal.price:.8f}")

                return {
                    'action': f'{signal.strategy}_buy',
                    'reason': signal.reason,
                    'success': True,
                    'trade_executed': True,
                    'quantity': signal.quantity,
                    'price': signal.price
                }
            else:
                return {
                    'action': 'buy_failed',
                    'reason': f'API ошибка: {result}',
                    'success': False,
                    'trade_executed': False
                }
        except Exception as e:
            return {
                'action': 'buy_error',
                'reason': str(e),
                'success': False,
                'trade_executed': False
            }

    def _execute_sell(self, signal: HybridTradeSignal) -> Dict[str, Any]:
        """💎 Выполнение продажи"""
        try:
            # 🚨 ИСПРАВЛЕНИЕ: Проверяем цену перед продажей
            safe_price = max(signal.price, signal.price * 1.001)  # Минимум +0.1%
            result = self.api_service.create_order(
                self.config.get_pair(), signal.quantity, safe_price, 'sell'
            )

            if result.get('result'):
                trade_info = {
                    'type': 'sell',
                    'quantity': signal.quantity,
                    'price': signal.price,
                    'timestamp': int(time.time())
                }
                self.position_manager.update_position(self.config.CURRENCY_1, trade_info)

                self.logger.info(f"✅ {signal.strategy} продажа: {signal.quantity:.4f} по {signal.price:.8f}")

                return {
                    'action': f'{signal.strategy}_sell',
                    'reason': signal.reason,
                    'success': True,
                    'trade_executed': True,
                    'quantity': signal.quantity,
                    'price': signal.price
                }
            else:
                return {
                    'action': 'sell_failed',
                    'reason': f'API ошибка: {result}',
                    'success': False,
                    'trade_executed': False
                }
        except Exception as e:
            return {
                'action': 'sell_error',
                'reason': str(e),
                'success': False,
                'trade_executed': False
            }

if __name__ == "__main__":
    print("🎯 Гибридные стратегии инициализированы")
