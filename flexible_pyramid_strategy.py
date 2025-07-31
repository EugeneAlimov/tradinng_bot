# flexible_pyramid_strategy.py
"""
🏗️ ПАТЧ 4: Гибкая пирамидальная стратегия с аварийными продажами
Заменяет жесткую блокировку на умную систему выхода
"""

import time
import logging
from typing import Dict, Any, List, Tuple, Optional


class FlexiblePyramidStrategy:
    """🏗️ Улучшенная пирамидальная стратегия с аварийными выходами"""
    
    def __init__(self, config, api_service, position_manager):
        self.config = config
        self.api_service = api_service
        self.position_manager = position_manager
        self.logger = logging.getLogger(__name__)
        
        # 🏗️ Основные уровни пирамиды (как было)
        self.pyramid_levels = [
            {'name': 'fast', 'profit_target': 0.008, 'sell_percentage': 0.25, 'min_profit_eur': 0.10},
            {'name': 'medium', 'profit_target': 0.020, 'sell_percentage': 0.35, 'min_profit_eur': 0.20},
            {'name': 'good', 'profit_target': 0.040, 'sell_percentage': 0.25, 'min_profit_eur': 0.30},
            {'name': 'excellent', 'profit_target': 0.070, 'sell_percentage': 0.15, 'min_profit_eur': 0.50}
        ]
        
        # 🚨 НОВЫЕ аварийные уровни для убыточных позиций
        self.emergency_levels = [
            {
                'name': 'partial_exit',
                'loss_threshold': -0.08,    # При убытке 8%
                'sell_percentage': 0.30,    # Продаем 30%
                'condition': 'time_based',  # + держим больше 4 часов
                'time_hours': 4,
                'description': 'Частичный выход при длительном убытке'
            },
            {
                'name': 'damage_control',
                'loss_threshold': -0.12,    # При убытке 12%
                'sell_percentage': 0.50,    # Продаем 50%
                'condition': 'immediate',   # Немедленно
                'description': 'Контроль ущерба'
            },
            {
                'name': 'emergency_exit',
                'loss_threshold': -0.15,    # При убытке 15%
                'sell_percentage': 1.00,    # Продаем все
                'condition': 'immediate',   # Немедленно
                'description': 'Полный аварийный выход'
            }
        ]
        
        # 📊 Трекинг времени позиций
        self.position_start_times = {}
        self.last_emergency_sell = 0
        self.cooldown_between_emergency = 1800  # 30 минут между аварийными продажами
        
        self.logger.info("🏗️ FlexiblePyramidStrategy инициализирована")
        self.logger.info(f"   🎯 Обычных уровней: {len(self.pyramid_levels)}")
        self.logger.info(f"   🚨 Аварийных уровней: {len(self.emergency_levels)}")
    
    def analyze_sell_opportunity(self, current_price: float, 
                               position_data: Dict[str, Any]) -> Dict[str, Any]:
        """🏗️ Анализ возможности продажи (обычной или аварийной)"""
        
        if not position_data or position_data.get('quantity', 0) == 0:
            return {'should_sell': False, 'reason': 'Нет позиции'}
        
        avg_price = position_data['avg_price']
        quantity = position_data['quantity']
        profit_percent = (current_price - avg_price) / avg_price
        
        # 🎯 ПРИОРИТЕТ 1: Проверяем аварийные условия
        emergency_result = self._check_emergency_conditions(
            current_price, position_data, profit_percent
        )
        if emergency_result['should_sell']:
            return emergency_result
        
        # 🏗️ ПРИОРИТЕТ 2: Обычная пирамидальная продажа (только в прибыли)
        if profit_percent > 0:
            pyramid_result = self._check_pyramid_levels(
                current_price, position_data, profit_percent
            )
            if pyramid_result['should_sell']:
                return pyramid_result
        
        # 📊 Информация о текущем состоянии
        return {
            'should_sell': False,
            'reason': f'Убыток {profit_percent*100:.1f}% - ожидаем восстановления или аварийных условий',
            'current_profit_percent': profit_percent * 100,
            'emergency_status': self._get_emergency_status(profit_percent, position_data)
        }
    
    def _check_emergency_conditions(self, current_price: float, 
                                  position_data: Dict[str, Any], 
                                  profit_percent: float) -> Dict[str, Any]:
        """🚨 Проверка аварийных условий продажи"""
        
        # Проверяем кулдаун между аварийными продажами
        if time.time() - self.last_emergency_sell < self.cooldown_between_emergency:
            remaining_cooldown = (self.cooldown_between_emergency - 
                                (time.time() - self.last_emergency_sell)) / 60
            return {
                'should_sell': False,
                'reason': f'Кулдаун аварийных продаж: {remaining_cooldown:.0f}мин'
            }
        
        currency = self.config.CURRENCY_1
        position_age_hours = self._get_position_age_hours(currency)
        
        # Проверяем каждый аварийный уровень
        for level in self.emergency_levels:
            if profit_percent <= level['loss_threshold']:
                
                # Проверяем дополнительные условия
                if level['condition'] == 'time_based':
                    if position_age_hours < level.get('time_hours', 0):
                        continue  # Еще не время
                
                # Рассчитываем количество к продаже
                quantity = position_data['quantity']
                sell_quantity = quantity * level['sell_percentage']
                
                # Агрессивная цена для быстрого исполнения
                aggressive_price = current_price * 0.995  # Скидка 0.5%
                
                self.logger.critical(f"🚨 АВАРИЙНЫЙ УРОВЕНЬ АКТИВИРОВАН!")
                self.logger.critical(f"   Уровень: {level['name']}")
                self.logger.critical(f"   Убыток: {profit_percent*100:.1f}%")
                self.logger.critical(f"   Продаем: {sell_quantity:.6f} ({level['sell_percentage']*100:.0f}%)")
                self.logger.critical(f"   Возраст позиции: {position_age_hours:.1f}ч")
                
                return {
                    'should_sell': True,
                    'sell_type': 'emergency',
                    'level_name': level['name'],
                    'quantity_to_sell': sell_quantity,
                    'suggested_price': aggressive_price,
                    'reason': f"{level['description']}: убыток {profit_percent*100:.1f}%",
                    'emergency_level': level,
                    'profit_percent': profit_percent * 100
                }
        
        return {'should_sell': False}
    
    def _check_pyramid_levels(self, current_price: float, 
                            position_data: Dict[str, Any], 
                            profit_percent: float) -> Dict[str, Any]:
        """🏗️ Проверка обычных пирамидальных уровней"""
        
        # Это оригинальная логика пирамиды (работает только в прибыли)
        best_level = None
        max_profit_eur = 0
        
        for level in self.pyramid_levels:
            if profit_percent >= level['profit_target']:
                
                # Рассчитываем прибыль в EUR для этого уровня
                quantity = position_data['quantity']
                sell_quantity = quantity * level['sell_percentage']
                profit_per_coin = current_price - position_data['avg_price']
                total_profit_eur = sell_quantity * profit_per_coin
                
                # Проверяем минимальную прибыль
                if total_profit_eur >= level['min_profit_eur']:
                    if total_profit_eur > max_profit_eur:
                        max_profit_eur = total_profit_eur
                        best_level = level
        
        if best_level:
            quantity = position_data['quantity']
            sell_quantity = quantity * best_level['sell_percentage']
            
            return {
                'should_sell': True,
                'sell_type': 'pyramid',
                'level_name': best_level['name'],
                'quantity_to_sell': sell_quantity,
                'suggested_price': current_price,
                'reason': f"Пирамида {best_level['name']}: прибыль {max_profit_eur:.2f} EUR",
                'profit_eur': max_profit_eur,
                'profit_percent': profit_percent * 100
            }
        
        return {'should_sell': False}
    
    def execute_sell(self, sell_data: Dict[str, Any]) -> Dict[str, Any]:
        """💼 Исполнение продажи (обычной или аварийной)"""
        
        try:
            quantity = sell_data['quantity_to_sell']
            price = sell_data['suggested_price']
            sell_type = sell_data['sell_type']
            
            self.logger.info(f"🏗️ Исполняем {sell_type} продажу:")
            self.logger.info(f"   Количество: {quantity:.6f}")
            self.logger.info(f"   Цена: {price:.8f}")
            self.logger.info(f"   Причина: {sell_data['reason']}")
            
            # Создаем ордер
            result = self.api_service.create_sell_order(
                quantity=quantity,
                price=price
            )
            
            if result['success']:
                # Обновляем позицию
                self.position_manager.update_position(
                    currency=self.config.CURRENCY_1,
                    trade_info={
                        'type': f'{sell_type}_sell',
                        'quantity': -quantity,  # Отрицательное для продажи
                        'price': price,
                        'reason': sell_data['reason'],
                        'level': sell_data.get('level_name', 'unknown')
                    }
                )
                
                # Если это аварийная продажа, обновляем время последней
                if sell_type == 'emergency':
                    self.last_emergency_sell = time.time()
                
                return {
                    'success': True,
                    'sell_type': sell_type,
                    'quantity_sold': quantity,
                    'price': price,
                    'order_id': result.get('order_id'),
                    'profit_eur': sell_data.get('profit_eur', 0)
                }
            else:
                return {'success': False, 'error': result.get('error')}
                
        except Exception as e:
            self.logger.error(f"❌ Ошибка исполнения продажи: {e}")
            return {'success': False, 'error': str(e)}
    
    def _get_position_age_hours(self, currency: str) -> float:
        """⏰ Получение возраста позиции в часах"""
        
        if currency not in self.position_start_times:
            # Если не знаем когда началась, считаем что недавно
            self.position_start_times[currency] = time.time()
            return 0.0
        
        age_seconds = time.time() - self.position_start_times[currency]
        return age_seconds / 3600
    
    def register_position_start(self, currency: str) -> None:
        """📝 Регистрация начала новой позиции"""
        self.position_start_times[currency] = time.time()
        self.logger.info(f"📝 Зарегистрировано начало позиции {currency}")
    
    def _get_emergency_status(self, profit_percent: float, 
                            position_data: Dict[str, Any]) -> Dict[str, Any]:
        """📊 Статус аварийных условий"""
        
        currency = self.config.CURRENCY_1
        position_age_hours = self._get_position_age_hours(currency)
        
        status = {
            'position_age_hours': position_age_hours,
            'profit_percent': profit_percent * 100,
            'next_emergency_level': None,
            'time_until_emergency': None
        }
        
        # Находим ближайший аварийный уровень
        for level in self.emergency_levels:
            if profit_percent > level['loss_threshold']:
                if level['condition'] == 'time_based':
                    required_hours = level.get('time_hours', 0)
                    if position_age_hours < required_hours:
                        status['next_emergency_level'] = level['name']
                        status['time_until_emergency'] = required_hours - position_age_hours
                        break
        
        return status