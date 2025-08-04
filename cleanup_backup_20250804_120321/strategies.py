import logging
import time
from abc import ABC, abstractmethod
from typing import Dict, Any, Tuple, Optional
from dataclasses import dataclass
from datetime import datetime


@dataclass
class TradeSignal:
    """📊 Торговый сигнал"""
    action: str  # 'buy', 'sell', 'hold'
    quantity: float
    price: float
    confidence: float  # 0.0 - 1.0
    reason: str
    strategy: str
    timestamp: datetime


class BaseStrategy(ABC):
    """🏗️ Базовая стратегия"""
    
    def __init__(self, config, name: str):
        self.config = config
        self.name = name
        self.logger = logging.getLogger(f"{__name__}.{name}")
        self.last_signal_time = 0
        self.min_signal_interval = 60  # 60 секунд между сигналами
    
    @abstractmethod
    def analyze(self, market_data: Dict[str, Any], position_data: Dict[str, Any]) -> TradeSignal:
        """Анализ и генерация сигнала"""
        pass
    
    def can_generate_signal(self) -> bool:
        """Проверка возможности генерации сигнала"""
        return time.time() - self.last_signal_time > self.min_signal_interval
    
    def _create_signal(self, action: str, quantity: float, price: float, 
                      confidence: float, reason: str) -> TradeSignal:
        """Создание сигнала"""
        self.last_signal_time = time.time()
        
        return TradeSignal(
            action=action,
            quantity=quantity,
            price=price,
            confidence=confidence,
            reason=reason,
            strategy=self.name,
            timestamp=datetime.now()
        )


class PyramidStrategy(BaseStrategy):
    """🏗️ Пирамидальная стратегия продаж"""
    
    def __init__(self, config):
        super().__init__(config, "pyramid")
        self.last_sell_time = 0
        self.cooldown_seconds = 300  # 5 минут между продажами
        
    def analyze(self, market_data: Dict[str, Any], position_data: Dict[str, Any]) -> TradeSignal:
        """🏗️ Анализ пирамидальной продажи"""
        
        if not position_data or position_data.get('quantity', 0) == 0:
            return self._create_signal('hold', 0, 0, 0, 'Нет позиции')
        
        current_price = market_data['current_price']
        avg_price = position_data['avg_price']
        quantity = position_data['quantity']
        
        if avg_price <= 0:
            return self._create_signal('hold', 0, 0, 0, 'Нет средней цены')
        
        profit_percent = (current_price - avg_price) / avg_price
        
        # 🚨 Стоп-лосс
        if profit_percent <= -self.config.STOP_LOSS_PERCENT:
            return self._create_signal(
                'sell', quantity, current_price * 1.001, 0.95,
                f'Стоп-лосс: {profit_percent*100:.1f}%'
            )
        
        # 🛡️ Блокировка продаж в убытке
        if profit_percent < self.config.MIN_PROFIT_PERCENT:
            return self._create_signal(
                'hold', 0, 0, 0.3,
                f'Удерживаем: прибыль {profit_percent*100:.2f}% < порога {self.config.MIN_PROFIT_PERCENT*100:.1f}%'
            )
        
        # ⏰ Кулдаун
        if time.time() - self.last_sell_time < self.cooldown_seconds:
            remaining = (self.cooldown_seconds - (time.time() - self.last_sell_time)) / 60
            return self._create_signal('hold', 0, 0, 0.2, f'Кулдаун: {remaining:.0f} мин')
        
        # 🏗️ Поиск подходящего уровня пирамиды
        for level in self.config.PYRAMID_LEVELS:
            if profit_percent >= level['profit']:
                sell_quantity = quantity * level['sell_percent']
                profit_eur = sell_quantity * (current_price - avg_price)
                
                if profit_eur >= level['min_eur']:
                    self.last_sell_time = time.time()
                    return self._create_signal(
                        'sell', sell_quantity, current_price * 1.002, 0.8,
                        f'Пирамида: прибыль {profit_percent*100:.1f}% = {profit_eur:.2f} EUR'
                    )
        
        return self._create_signal('hold', 0, 0, 0.4, f'Ждем лучшего уровня: {profit_percent*100:.2f}%')

class DCAStrategy(BaseStrategy):
    """🛒 DCA стратегия"""
    
    def __init__(self, config):
        super().__init__(config, "dca")
        self.last_dca_time = 0
        self.dca_count = 0
        self.last_dca_date = datetime.now().date()
        
    def analyze(self, market_data: Dict[str, Any], position_data: Dict[str, Any]) -> TradeSignal:
        """🛒 Анализ DCA"""
        
        current_price = market_data['current_price']
        balance = market_data['balance']

        # 🛡️ Проверка DCA лимитов
        if hasattr(self, 'dca_limiter') and self.dca_limiter:
            can_dca, reason = self.dca_limiter.can_execute_dca(
                current_price, position_data, balance
            )
            
            if not can_dca:
                return self._create_signal('hold', 0, 0, 0.1, f'DCA заблокирована: {reason}')
        
        if not position_data or position_data.get('quantity', 0) == 0:
            return self._create_signal('hold', 0, 0, 0.1, 'Нет позиции для DCA')
        
        avg_price = position_data['avg_price']
        current_value = position_data['quantity'] * current_price
        
        if avg_price <= 0:
            return self._create_signal('hold', 0, 0, 0.1, 'Нет средней цены')
        
        # Проверяем дневной лимит
        today = datetime.now().date()
        if today != self.last_dca_date:
            self.dca_count = 0
            self.last_dca_date = today
        
        if self.dca_count >= self.config.DCA_DAILY_LIMIT:
            return self._create_signal('hold', 0, 0, 0.1, f'DCA лимит: {self.dca_count}/{self.config.DCA_DAILY_LIMIT}')
        
        # Проверяем кулдаун
        cooldown_seconds = self.config.DCA_COOLDOWN_MINUTES * 60
        if time.time() - self.last_dca_time < cooldown_seconds:
            remaining = (cooldown_seconds - (time.time() - self.last_dca_time)) / 60
            return self._create_signal('hold', 0, 0, 0.2, f'DCA кулдаун: {remaining:.0f} мин')
        
        # Проверяем падение
        drop_percent = (avg_price - current_price) / avg_price
        if drop_percent < self.config.DCA_DROP_THRESHOLD:
            return self._create_signal(
                'hold', 0, 0, 0.3,
                f'Малое падение: {drop_percent*100:.1f}% < {self.config.DCA_DROP_THRESHOLD*100:.0f}%'
            )
        
        # Проверяем лимит позиции
        dca_amount = balance * self.config.DCA_PURCHASE_SIZE
        new_total_value = current_value + dca_amount
        new_position_percent = new_total_value / (balance + new_total_value)
        
        if new_position_percent > self.config.DCA_MAX_POSITION:
            return self._create_signal(
                'hold', 0, 0, 0.2,
                f'Лимит позиции: {new_position_percent*100:.0f}% > {self.config.DCA_MAX_POSITION*100:.0f}%'
            )
        
        # ✅ DCA разрешена
        if balance < dca_amount:
            return self._create_signal('hold', 0, 0, 0.1, f'Недостаточно баланса: {balance:.2f} < {dca_amount:.2f}')
        
        dca_quantity = dca_amount / current_price
        self.last_dca_time = time.time()
        self.dca_count += 1
        
        return self._create_signal(
            'buy', dca_quantity, current_price * 0.9995, 0.7,
            f'DCA: падение {drop_percent*100:.1f}%, размер {self.config.DCA_PURCHASE_SIZE*100:.0f}%'
        )


class StrategyManager:
    """🎯 Менеджер стратегий"""
    
    def __init__(self, config, api_service, position_manager):
        self.config = config
        self.api_service = api_service
        self.position_manager = position_manager
        self.logger = logging.getLogger(__name__)
        
        # Создаем стратегии
        self.pyramid_strategy = PyramidStrategy(config)
        self.dca_strategy = DCAStrategy(config)
        
        # Приоритеты (чем выше, тем важнее)
        self.strategy_priorities = {
            'pyramid': 100,  # Продажа всегда приоритетнее
            'dca': 50        # DCA менее приоритетна
        }
        
    def execute_cycle(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """🔄 Торговый цикл"""
        
        try:
            # Получаем позицию
            position_data = self.position_manager.get_accurate_position_data(self.config.CURRENCY_1)
            
            # Получаем сигналы
            signals = []
            
            pyramid_signal = self.pyramid_strategy.analyze(market_data, position_data)
            if pyramid_signal.action != 'hold':
                signals.append(pyramid_signal)
            
            dca_signal = self.dca_strategy.analyze(market_data, position_data)
            if dca_signal.action != 'hold':
                signals.append(dca_signal)
            
            # Если нет сигналов - держим
            if not signals:
                return {
                    'action': 'hold',
                    'reason': 'Нет торговых сигналов',
                    'success': True,
                    'trade_executed': False
                }
            
            # Выбираем сигнал с наивысшим приоритетом
            best_signal = max(signals, key=lambda s: self.strategy_priorities.get(s.strategy, 0))
            
            # Логируем решение
            self.logger.info(f"🎯 Выбран сигнал: {best_signal.strategy}")
            self.logger.info(f"   Действие: {best_signal.action}")
            self.logger.info(f"   Причина: {best_signal.reason}")
            self.logger.info(f"   Уверенность: {best_signal.confidence:.0%}")
            
            # Исполняем сигнал
            if best_signal.action == 'buy':
                return self._execute_buy(best_signal)
            elif best_signal.action == 'sell':
                return self._execute_sell(best_signal)
            
            return {
                'action': 'hold',
                'reason': best_signal.reason,
                'success': True,
                'trade_executed': False
            }
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка торгового цикла: {e}")
            return {
                'action': 'error',
                'reason': str(e),
                'success': False,
                'trade_executed': False
            }
    
    def _execute_buy(self, signal: TradeSignal) -> Dict[str, Any]:
        """🛒 Исполнение покупки"""
        try:
            result = self.api_service.create_order(
                self.config.get_pair(), signal.quantity, signal.price, 'buy'
            )
            
            if result.get('result'):
                # Обновляем позицию
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
                self.logger.error(f"❌ Ошибка покупки: {result}")
                return {
                    'action': 'buy_failed',
                    'reason': f'API ошибка: {result}',
                    'success': False,
                    'trade_executed': False
                }
                
        except Exception as e:
            self.logger.error(f"❌ Исключение при покупке: {e}")
            return {
                'action': 'buy_error',
                'reason': str(e),
                'success': False,
                'trade_executed': False
            }
    
    def _execute_sell(self, signal: TradeSignal) -> Dict[str, Any]:
        """💎 Исполнение продажи"""
        try:
            result = self.api_service.create_order(
                self.config.get_pair(), signal.quantity, signal.price, 'sell'
            )
            
            if result.get('result'):
                # Обновляем позицию
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
                self.logger.error(f"❌ Ошибка продажи: {result}")
                return {
                    'action': 'sell_failed',
                    'reason': f'API ошибка: {result}',
                    'success': False,
                    'trade_executed': False
                }
                
        except Exception as e:
            self.logger.error(f"❌ Исключение при продаже: {e}")
            return {
                'action': 'sell_error',
                'reason': str(e),
                'success': False,
                'trade_executed': False
            }
