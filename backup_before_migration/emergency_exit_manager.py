# emergency_exit_manager.py
"""🚨 Система аварийного выхода из критических убытков"""

import time
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Tuple, Optional
from dataclasses import dataclass


@dataclass
class EmergencyExitResult:
    """Результат проверки аварийного выхода"""
    should_exit: bool
    reason: str
    urgency: str  # 'low', 'medium', 'high', 'critical'
    sell_percentage: float  # 0.0 - 1.0
    recommended_price: float
    

class EmergencyExitManager:
    """🚨 Менеджер аварийного выхода из критических ситуаций"""
    
    def __init__(self, config, api_service, position_manager):
        self.config = config
        self.api_service = api_service
        self.position_manager = position_manager
        self.logger = logging.getLogger(__name__)
        
        # 🚨 Уровни аварийного выхода
        self.emergency_levels = {
            'critical_loss': {
                'threshold': -0.15,        # 15% убыток
                'sell_percentage': 1.0,    # Продать все
                'urgency': 'critical',
                'immediate': True
            },
            'major_loss': {
                'threshold': -0.12,        # 12% убыток
                'sell_percentage': 0.70,   # Продать 70%
                'urgency': 'high',
                'immediate': True
            },
            'significant_loss_time': {
                'threshold': -0.08,        # 8% убыток
                'sell_percentage': 0.40,   # Продать 40%
                'urgency': 'medium',
                'time_condition': 4        # + 4 часа в убытке
            }
        }
        
        # Отслеживание времени в убытке
        self.position_start_times = {}
        self.loss_start_times = {}
        
        self.logger.info("🚨 EmergencyExitManager инициализирован")
        
    def check_emergency_conditions(self, currency: str, current_price: float) -> EmergencyExitResult:
        """🚨 Основная проверка условий аварийного выхода"""
        
        try:
            position_data = self.position_manager.get_accurate_position_data(currency)
            
            if not position_data or position_data.get('quantity', 0) <= 0:
                return EmergencyExitResult(
                    should_exit=False, reason="Нет позиции", urgency='low',
                    sell_percentage=0.0, recommended_price=current_price
                )
            
            avg_price = position_data.get('avg_price', 0)
            if avg_price <= 0:
                return EmergencyExitResult(
                    should_exit=False, reason="Некорректная средняя цена", urgency='low',
                    sell_percentage=0.0, recommended_price=current_price
                )
            
            # Вычисляем убыток
            loss_percentage = (avg_price - current_price) / avg_price
            loss_duration_hours = self._get_loss_duration_hours(currency, loss_percentage)
            
            # Проверяем каждый уровень
            for level_name, level_config in self.emergency_levels.items():
                if loss_percentage <= level_config['threshold']:
                    
                    # Проверяем временные условия
                    if 'time_condition' in level_config:
                        required_hours = level_config['time_condition']
                        if loss_duration_hours < required_hours:
                            continue
                    
                    # Условия выполнены
                    recommended_price = current_price * 0.995  # Агрессивная цена
                    
                    result = EmergencyExitResult(
                        should_exit=True,
                        reason=f"{level_name}: убыток {loss_percentage*100:.1f}%",
                        urgency=level_config['urgency'],
                        sell_percentage=level_config['sell_percentage'],
                        recommended_price=recommended_price
                    )
                    
                    self.logger.warning(f"🚨 АВАРИЙНОЕ УСЛОВИЕ: {result.reason}")
                    return result
            
            return EmergencyExitResult(
                should_exit=False,
                reason=f"Убыток {loss_percentage*100:.2f}% в пределах нормы",
                urgency='low', sell_percentage=0.0, recommended_price=current_price
            )
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка проверки аварийных условий: {e}")
            return EmergencyExitResult(
                should_exit=False, reason=f"Ошибка: {str(e)}", urgency='low',
                sell_percentage=0.0, recommended_price=current_price
            )
    
    def execute_emergency_exit(self, currency: str, exit_result: EmergencyExitResult) -> Dict[str, Any]:
        """🚨 Выполнение аварийного выхода"""
        
        try:
            if not exit_result.should_exit:
                return {'success': False, 'reason': 'Аварийный выход не требуется'}
            
            position_data = self.position_manager.get_accurate_position_data(currency)
            if not position_data or position_data.get('quantity', 0) <= 0:
                return {'success': False, 'reason': 'Нет позиции для выхода'}
            
            total_quantity = position_data['quantity']
            sell_quantity = total_quantity * exit_result.sell_percentage
            
            self.logger.critical(f"🚨 ВЫПОЛНЕНИЕ АВАРИЙНОГО ВЫХОДА:")
            self.logger.critical(f"   📊 Валюта: {currency}")
            self.logger.critical(f"   🎯 Причина: {exit_result.reason}")
            self.logger.critical(f"   📦 Количество: {sell_quantity:.6f}")
            
            # Выполняем продажу
            pair = self.config.get_pair()
            result = self.api_service.create_order(
                pair, sell_quantity, exit_result.recommended_price, 'sell'
            )
            
            if result.get('result'):
                # Обновляем позицию
                trade_info = {
                    'type': 'sell',
                    'quantity': sell_quantity,
                    'price': exit_result.recommended_price,
                    'timestamp': int(time.time()),
                    'emergency_exit': True
                }
                
                self.position_manager.update_position(currency, trade_info)
                
                self.logger.critical(f"✅ АВАРИЙНЫЙ ВЫХОД ВЫПОЛНЕН!")
                
                return {
                    'success': True,
                    'order_id': result.get('order_id'),
                    'quantity_sold': sell_quantity,
                    'price': exit_result.recommended_price,
                    'urgency': exit_result.urgency
                }
            else:
                self.logger.error(f"❌ Ошибка аварийного ордера: {result}")
                return {'success': False, 'reason': f'API ошибка: {result}'}
                
        except Exception as e:
            self.logger.error(f"❌ Исключение при аварийном выходе: {e}")
            return {'success': False, 'reason': f'Исключение: {str(e)}'}
    
    def _get_loss_duration_hours(self, currency: str, loss_percentage: float) -> float:
        """🕐 Получение времени в убытке"""
        current_time = time.time()
        
        if loss_percentage <= 0:
            if currency in self.loss_start_times:
                del self.loss_start_times[currency]
            return 0.0
        
        if currency not in self.loss_start_times:
            self.loss_start_times[currency] = current_time
            return 0.0
        
        duration_seconds = current_time - self.loss_start_times[currency]
        return duration_seconds / 3600
