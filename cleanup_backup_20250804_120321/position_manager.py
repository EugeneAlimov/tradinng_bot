import json
import logging
import os
from typing import Dict, Any, Optional
from datetime import datetime


class PositionManager:
    """📊 Менеджер торговых позиций"""
    
    def __init__(self, config, api_service):
        self.config = config
        self.api_service = api_service
        self.logger = logging.getLogger(__name__)
        
        # Данные позиций
        self.positions = {}
        self.load_positions_from_file()
        
    def get_accurate_position_data(self, currency: str) -> Dict[str, Any]:
        """📊 Получение точных данных позиции"""
        
        try:
            # Получаем реальный баланс
            real_balance = self.api_service.get_balance(currency)
            
            # Получаем расчетную позицию
            calculated_position = self.positions.get(currency, {
                'quantity': 0.0,
                'avg_price': 0.0,
                'total_cost': 0.0
            })
            
            # Если есть расчетная позиция
            if calculated_position['quantity'] > 0:
                return {
                    'quantity': calculated_position['quantity'],
                    'avg_price': calculated_position['avg_price'],
                    'total_cost': calculated_position['total_cost'],
                    'real_balance': real_balance,
                    'source': 'calculated'
                }
            
            # Если нет расчетной, но есть реальный баланс
            elif real_balance > 0:
                return {
                    'quantity': real_balance,
                    'avg_price': 0.0,
                    'total_cost': 0.0,
                    'real_balance': real_balance,
                    'source': 'real_balance'
                }
            
            # Нет позиции
            else:
                return {
                    'quantity': 0.0,
                    'avg_price': 0.0,
                    'total_cost': 0.0,
                    'real_balance': 0.0,
                    'source': 'none'
                }
                
        except Exception as e:
            self.logger.error(f"❌ Ошибка получения позиции {currency}: {e}")
            return {
                'quantity': 0.0,
                'avg_price': 0.0,
                'total_cost': 0.0,
                'real_balance': 0.0,
                'source': 'error'
            }
    
    def update_position(self, currency: str, trade_info: Dict[str, Any]):
        """📈 Обновление позиции после сделки"""
        
        try:
            current_position = self.positions.get(currency, {
                'quantity': 0.0,
                'avg_price': 0.0,
                'total_cost': 0.0,
                'trades': []
            })
            
            trade_type = trade_info['type']
            quantity = float(trade_info['quantity'])
            price = float(trade_info['price'])
            
            if trade_type == 'buy':
                # Покупка - увеличиваем позицию
                new_quantity = current_position['quantity'] + quantity
                new_cost = current_position['total_cost'] + (quantity * price)
                new_avg_price = new_cost / new_quantity if new_quantity > 0 else 0.0
                
                self.positions[currency] = {
                    'quantity': new_quantity,
                    'avg_price': new_avg_price,
                    'total_cost': new_cost,
                    'trades': current_position.get('trades', []) + [trade_info]
                }
                
                self.logger.info(f"📈 Увеличена позиция {currency}:")
                self.logger.info(f"   {current_position['quantity']:.6f} -> {new_quantity:.6f}")
                self.logger.info(f"   Средняя цена: {current_position['avg_price']:.8f} -> {new_avg_price:.8f}")
                
            elif trade_type == 'sell':
                # Продажа - уменьшаем позицию
                new_quantity = max(0.0, current_position['quantity'] - quantity)
                
                if new_quantity > 0:
                    # Частичная продажа
                    ratio = new_quantity / current_position['quantity']
                    new_cost = current_position['total_cost'] * ratio
                    new_avg_price = current_position['avg_price']  # Средняя цена не меняется
                else:
                    # Полная продажа
                    new_cost = 0.0
                    new_avg_price = 0.0
                
                self.positions[currency] = {
                    'quantity': new_quantity,
                    'avg_price': new_avg_price,
                    'total_cost': new_cost,
                    'trades': current_position.get('trades', []) + [trade_info]
                }
                
                self.logger.info(f"📉 Уменьшена позиция {currency}:")
                self.logger.info(f"   {current_position['quantity']:.6f} -> {new_quantity:.6f}")
            
            # Сохраняем изменения
            self.save_positions_to_file()
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка обновления позиции {currency}: {e}")
    
    def save_positions_to_file(self):
        """💾 Сохранение позиций в файл"""
        try:
            os.makedirs(os.path.dirname(self.config.POSITIONS_FILE), exist_ok=True)
            
            data = {
                'positions': self.positions,
                'last_update': datetime.now().isoformat()
            }
            
            with open(self.config.POSITIONS_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                
        except Exception as e:
            self.logger.error(f"❌ Ошибка сохранения позиций: {e}")
    
    def load_positions_from_file(self):
        """📂 Загрузка позиций из файла"""
        try:
            if os.path.exists(self.config.POSITIONS_FILE):
                with open(self.config.POSITIONS_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.positions = data.get('positions', {})
                    
                self.logger.info(f"📂 Загружено {len(self.positions)} позиций из файла")
                
                # Показываем загруженные позиции
                for currency, position in self.positions.items():
                    if position['quantity'] > 0:
                        self.logger.info(f"   📊 {currency}: {position['quantity']:.6f} "
                                       f"по {position['avg_price']:.8f}")
            else:
                self.logger.info("📂 Файл позиций не найден, начинаем с пустых позиций")
                
        except Exception as e:
            self.logger.error(f"❌ Ошибка загрузки позиций: {e}")
            self.positions = {}
