# emergency_exit_manager.py
"""
🚨 ПАТЧ 1: Система аварийного выхода из убыточных позиций
Решает проблему "заблокированного" бота в убытке
"""

import time
import logging
from typing import Dict, Any, Tuple, Optional
from datetime import datetime, timedelta


class EmergencyExitManager:
    """🚨 Менеджер аварийного выхода из критических ситуаций"""
    
    def __init__(self, config, api_service, position_manager):
        self.config = config
        self.api_service = api_service
        self.position_manager = position_manager
        self.logger = logging.getLogger(__name__)
        
        # 🚨 Критические пороги
        self.CRITICAL_LOSS_THRESHOLD = 0.10    # 10% критический убыток
        self.EMERGENCY_LOSS_THRESHOLD = 0.15   # 15% экстренный выход
        self.TIME_BASED_THRESHOLD = 24 * 3600  # 24 часа в убытке
        self.MODERATE_LOSS_TIME = 6 * 3600     # 6 часов умеренного убытка
        
        # 📊 Трекинг времени в убытке
        self.loss_start_time = {}
        
        self.logger.info("🚨 EmergencyExitManager инициализирован")
        self.logger.info(f"   💥 Критический убыток: {self.CRITICAL_LOSS_THRESHOLD*100:.0f}%")
        self.logger.info(f"   🚨 Экстренный выход: {self.EMERGENCY_LOSS_THRESHOLD*100:.0f}%")
    
    def should_emergency_exit(self, position_data: Dict[str, Any], 
                            current_price: float) -> Tuple[bool, str, float]:
        """🚨 Проверка необходимости аварийного выхода"""
        
        if not position_data or position_data['quantity'] == 0:
            return False, "Нет позиции", 0.0
            
        # Рассчитываем текущий убыток
        avg_price = position_data['avg_price']
        quantity = position_data['quantity']
        current_value = quantity * current_price
        invested_value = quantity * avg_price
        loss_percent = (current_price - avg_price) / avg_price
        
        currency = self.config.CURRENCY_1
        
        # 🚨 КРИТЕРИЙ 1: Экстренный стоп-лосс (15%)
        if loss_percent <= -self.EMERGENCY_LOSS_THRESHOLD:
            return True, f"ЭКСТРЕННЫЙ СТОП: убыток {loss_percent*100:.1f}%", 1.0
            
        # 🚨 КРИТЕРИЙ 2: Критический убыток (10%) + время
        if loss_percent <= -self.CRITICAL_LOSS_THRESHOLD:
            # Отслеживаем время в критическом убытке
            if currency not in self.loss_start_time:
                self.loss_start_time[currency] = time.time()
                self.logger.warning(f"⏰ Начало отсчета критического убытка: {loss_percent*100:.1f}%")
                
            time_in_loss = time.time() - self.loss_start_time[currency]
            
            if time_in_loss > self.TIME_BASED_THRESHOLD:
                return True, f"ВРЕМЕННОЙ СТОП: {loss_percent*100:.1f}% уже {time_in_loss/3600:.1f}ч", 1.0
        else:
            # Сбрасываем таймер если убыток уменьшился
            if currency in self.loss_start_time:
                del self.loss_start_time[currency]
                
        # 🚨 КРИТЕРИЙ 3: Умеренный убыток (5%) + длительное время
        if loss_percent <= -0.05:  # 5%
            if currency not in self.loss_start_time:
                self.loss_start_time[currency] = time.time()
                
            time_in_loss = time.time() - self.loss_start_time[currency]
            
            if time_in_loss > self.MODERATE_LOSS_TIME:
                # Частичная продажа 30%
                return True, f"ЧАСТИЧНЫЙ ВЫХОД: {loss_percent*100:.1f}% держится {time_in_loss/3600:.1f}ч", 0.3
                
        return False, "Аварийный выход не требуется", 0.0
    
    def execute_emergency_exit(self, position_data: Dict[str, Any], 
                             current_price: float, sell_percentage: float, 
                             reason: str) -> Dict[str, Any]:
        """🚨 Исполнение аварийного выхода"""
        
        try:
            quantity = position_data['quantity']
            sell_quantity = quantity * sell_percentage
            
            # Агрессивная цена для быстрого исполнения (скидка 0.3%)
            aggressive_price = current_price * 0.997
            
            self.logger.critical(f"🚨 АВАРИЙНЫЙ ВЫХОД АКТИВИРОВАН!")
            self.logger.critical(f"   Причина: {reason}")
            self.logger.critical(f"   Продаем: {sell_quantity:.6f} из {quantity:.6f} ({sell_percentage*100:.0f}%)")
            self.logger.critical(f"   Цена: {aggressive_price:.8f} (скидка 0.3%)")
            
            # Создаем ордер через API Service
            result = self.api_service.create_sell_order(
                quantity=sell_quantity,
                price=aggressive_price
            )
            
            if result['success']:
                # Обновляем позицию
                self.position_manager.update_position(
                    currency=self.config.CURRENCY_1,
                    trade_info={
                        'type': 'emergency_exit',
                        'quantity': -sell_quantity,  # Отрицательное для продажи
                        'price': aggressive_price,
                        'reason': reason
                    }
                )
                
                return {
                    'success': True,
                    'action': 'emergency_exit',
                    'quantity_sold': sell_quantity,
                    'price': aggressive_price,
                    'reason': reason,
                    'order_id': result.get('order_id')
                }
            else:
                self.logger.error(f"❌ Ошибка аварийного выхода: {result.get('error')}")
                return {'success': False, 'error': result.get('error')}
                
        except Exception as e:
            self.logger.error(f"❌ Критическая ошибка аварийного выхода: {e}")
            return {'success': False, 'error': str(e)}
    
    def get_emergency_status(self, position_data: Dict[str, Any], 
                           current_price: float) -> Dict[str, Any]:
        """📊 Статус системы аварийного выхода"""
        
        if not position_data or position_data['quantity'] == 0:
            return {'status': 'no_position'}
            
        avg_price = position_data['avg_price']
        loss_percent = (current_price - avg_price) / avg_price
        currency = self.config.CURRENCY_1
        
        status = {
            'loss_percent': loss_percent * 100,
            'is_critical': loss_percent <= -self.CRITICAL_LOSS_THRESHOLD,
            'is_emergency': loss_percent <= -self.EMERGENCY_LOSS_THRESHOLD,
            'time_in_loss': 0
        }
        
        if currency in self.loss_start_time:
            status['time_in_loss'] = time.time() - self.loss_start_time[currency]
            status['time_in_loss_hours'] = status['time_in_loss'] / 3600
            
        return status