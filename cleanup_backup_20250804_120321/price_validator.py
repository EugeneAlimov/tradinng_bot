#!/usr/bin/env python3
"""🛡️ Валидатор цен для предотвращения ошибок ценообразования"""

import logging
from typing import Tuple

class PriceValidator:
    """🛡️ Проверка цен перед создaniem ордеров"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.min_profit_margin = 0.001  # Минимум 0.1% прибыли
        
    def validate_sell_price(self, sell_price: float, avg_buy_price: float, 
                          current_market_price: float) -> Tuple[bool, str, float]:
        """🔍 Проверка цены продажи"""
        
        # Проверка 1: Цена продажи должна быть выше средней цены покупки
        if sell_price <= avg_buy_price:
            safe_price = avg_buy_price * (1 + self.min_profit_margin)
            return False, f"Цена продажи {sell_price:.8f} <= средней покупки {avg_buy_price:.8f}", safe_price
        
        # Проверка 2: Цена продажи не должна быть слишком ниже рынка  
        min_market_price = current_market_price * 0.995  # Макс скидка 0.5%
        if sell_price < min_market_price:
            safe_price = current_market_price * 1.001
            return False, f"Цена продажи {sell_price:.8f} слишком низкая для рынка {current_market_price:.8f}", safe_price
            
        # Проверка 3: Минимальная прибыль
        profit_percent = (sell_price - avg_buy_price) / avg_buy_price
        if profit_percent < self.min_profit_margin:
            safe_price = avg_buy_price * (1 + self.min_profit_margin)
            return False, f"Прибыль {profit_percent*100:.3f}% < минимума {self.min_profit_margin*100:.1f}%", safe_price
        
        return True, "Цена корректна", sell_price
    
    def validate_buy_price(self, buy_price: float, current_market_price: float) -> Tuple[bool, str, float]:
        """🔍 Проверка цены покупки"""
        
        # Покупка не должна быть слишком дорогой
        max_market_price = current_market_price * 1.005  # Макс переплата 0.5%
        if buy_price > max_market_price:
            safe_price = current_market_price * 0.999
            return False, f"Цена покупки {buy_price:.8f} слишком высокая для рынка {current_market_price:.8f}", safe_price
        
        return True, "Цена покупки корректна", buy_price

if __name__ == "__main__":
    # Тест валидатора
    validator = PriceValidator()
    
    # Тест 1: Правильная продажа
    is_valid, reason, safe_price = validator.validate_sell_price(0.180, 0.173, 0.179)
    print(f"Тест 1: {is_valid} - {reason} - {safe_price:.8f}")
    
    # Тест 2: Неправильная продажа (ниже покупки)
    is_valid, reason, safe_price = validator.validate_sell_price(0.170, 0.173, 0.179) 
    print(f"Тест 2: {is_valid} - {reason} - {safe_price:.8f}")
    
    # Тест 3: Продажа слишком дешевая для рынка
    is_valid, reason, safe_price = validator.validate_sell_price(0.175, 0.173, 0.179)
    print(f"Тест 3: {is_valid} - {reason} - {safe_price:.8f}")
