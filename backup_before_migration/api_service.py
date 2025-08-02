import time
import logging
from typing import Dict, Any


class APIService:
    """🌐 API сервис с кэшированием"""
    
    def __init__(self, api_client, config):
        self.api = api_client
        self.config = config
        self.logger = logging.getLogger(__name__)
        self._cache = {}
        self._cache_timeouts = {'balance': 10, 'price': 3, 'pair_settings': 300}
        
    def get_current_price(self, pair: str) -> float:
        """💱 Получение цены с кэшем"""
        cache_key = f"price_{pair}"
        
        if self._is_cache_valid(cache_key, 'price'):
            return self._cache[cache_key]['value']
        
        try:
            ticker_data = self.api.get_ticker()
            if ticker_data and pair in ticker_data:
                price = float(ticker_data[pair]['last_trade'])
                self._update_cache(cache_key, price, 'price')
                return price
            return 0.0
        except Exception as e:
            self.logger.error(f"Ошибка получения цены {pair}: {e}")
            return 0.0
    
    def get_balance(self, currency: str) -> float:
        """💰 Получение баланса с кэшем"""
        cache_key = f"balance_{currency}"
        
        if self._is_cache_valid(cache_key, 'balance'):
            return self._cache[cache_key]['value']
        
        try:
            user_info = self.api.get_user_info()
            if user_info and 'balances' in user_info:
                balance = float(user_info['balances'].get(currency, 0))
                self._update_cache(cache_key, balance, 'balance')
                return balance
            return 0.0
        except Exception as e:
            self.logger.error(f"Ошибка получения баланса {currency}: {e}")
            return 0.0
    
    def create_order(self, pair: str, quantity: float, price: float, order_type: str) -> Dict[str, Any]:
        """📝 Создание ордера с валидацией"""
        try:
            min_quantity = self._get_min_quantity(pair)
            if quantity < min_quantity:
                quantity = min_quantity
            
            price_precision = self._get_price_precision(pair)
            price = round(price, price_precision)
            
            self.logger.info(f"📝 Создаем ордер: {order_type.upper()} {quantity:.6f} {pair} по {price:.8f}")
            
            result = self.api.create_order(pair, quantity, price, order_type)
            
            if result.get('result'):
                self.logger.info(f"✅ Ордер создан: ID {result.get('order_id')}")
                self._invalidate_balance_cache()
            
            return result
        except Exception as e:
            self.logger.error(f"❌ Исключение при создании ордера: {e}")
            return {'result': False, 'error': str(e)}
    
    def _get_min_quantity(self, pair: str) -> float:
        try:
            settings = self.api.get_pair_settings()
            if settings and pair in settings:
                return float(settings[pair].get('min_quantity', 5.0))
            return 5.0
        except:
            return 5.0
    
    def _get_price_precision(self, pair: str) -> int:
        try:
            settings = self.api.get_pair_settings()
            if settings and pair in settings:
                return int(settings[pair].get('price_precision', 8))
            return 8
        except:
            return 8
    
    def _is_cache_valid(self, key: str, cache_type: str) -> bool:
        if key not in self._cache:
            return False
        cache_entry = self._cache[key]
        timeout = self._cache_timeouts.get(cache_type, 60)
        return time.time() - cache_entry['timestamp'] < timeout
    
    def _update_cache(self, key: str, value: Any, cache_type: str):
        self._cache[key] = {'value': value, 'timestamp': time.time(), 'type': cache_type}
    
    def _invalidate_balance_cache(self):
        keys_to_remove = [k for k in self._cache.keys() if k.startswith('balance_')]
        for key in keys_to_remove:
            del self._cache[key]
    
    def get_cache_stats(self) -> Dict[str, Any]:
        return {
            'total_entries': len(self._cache),
            'balance_entries': len([k for k in self._cache.keys() if k.startswith('balance_')]),
            'price_entries': len([k for k in self._cache.keys() if k.startswith('price_')])
        }
