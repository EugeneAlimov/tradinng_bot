import requests
import hashlib
import hmac
import time
import json
import logging
from typing import Dict, Any, Optional


class ExmoAPIClient:
    """🌐 API клиент для EXMO"""
    
    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.api_url = 'https://api.exmo.com/v1.1/'
        self.logger = logging.getLogger(__name__)
        
    def _make_request(self, endpoint: str, params: Dict[str, Any] = None) -> Optional[Dict]:
        """📡 Выполнение API запроса"""
        
        if params is None:
            params = {}
        
        params['nonce'] = int(time.time() * 1000)
        
        try:
            # Подготовка данных для подписи
            post_data = '&'.join([f'{k}={v}' for k, v in params.items()])
            
            # Создание подписи
            signature = hmac.new(
                self.api_secret.encode(),
                post_data.encode(),
                hashlib.sha512
            ).hexdigest()
            
            # Заголовки
            headers = {
                'Key': self.api_key,
                'Sign': signature,
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            
            # Выполнение запроса
            response = requests.post(
                self.api_url + endpoint,
                headers=headers,
                data=params,
                timeout=10
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                self.logger.error(f"API ошибка: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            self.logger.error(f"Ошибка API запроса: {e}")
            return None
    
    def get_user_info(self) -> Optional[Dict]:
        """👤 Получение информации о пользователе"""
        return self._make_request('user_info')
    
    def get_ticker(self) -> Optional[Dict]:
        """💱 Получение ticker данных"""
        try:
            response = requests.get(self.api_url + 'ticker', timeout=10)
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            self.logger.error(f"Ошибка получения ticker: {e}")
            return None
    
    def create_order(self, pair: str, quantity: float, price: float, order_type: str) -> Dict:
        """📝 Создание ордера"""
        
        params = {
            'pair': pair,
            'quantity': str(quantity),
            'price': str(price),
            'type': order_type
        }
        
        result = self._make_request('order_create', params)
        
        if result and 'order_id' in result:
            return {'result': True, 'order_id': result['order_id']}
        else:
            return {'result': False, 'error': result}
    
    def get_pair_settings(self) -> Optional[Dict]:
        """⚙️ Получение настроек торговых пар"""
        try:
            response = requests.get(self.api_url + 'pair_settings', timeout=10)
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            self.logger.error(f"Ошибка получения настроек пар: {e}")
            return None
    
    def get_open_orders(self) -> Optional[Dict]:
        """📋 Получение открытых ордеров"""
        return self._make_request('user_open_orders')
    
    def get_trades(self, pair: str, limit: int = 100) -> Optional[Dict]:
        """📊 Получение истории сделок"""
        params = {'pair': pair, 'limit': limit}
        return self._make_request('user_trades', params)
