#!/usr/bin/env python3
"""🌐 Адаптер для существующего API клиента"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from decimal import Decimal
from typing import Dict, Any

class APIAdapter:
    """Адаптер для старого API клиента"""

    def __init__(self, api_key: str, api_secret: str):
        # Импортируем старый API клиент
        try:
            from api_client import ExmoAPIClient
            self.old_client = ExmoAPIClient(api_key, api_secret)
        except ImportError:
            raise ImportError("Не удалось импортировать старый API клиент")

    async def get_balance(self, currency: str) -> Decimal:
        """Получение баланса через старый клиент"""
        try:
            user_info = self.old_client.get_user_info()
            if user_info and 'balances' in user_info:
                balance = user_info['balances'].get(currency, '0')
                return Decimal(str(balance))
            return Decimal('0')
        except Exception:
            return Decimal('0')

    async def get_current_price(self, pair: str) -> Decimal:
        """Получение цены через старый клиент"""
        try:
            ticker = self.old_client.get_ticker()
            if ticker and pair in ticker:
                price = ticker[pair]['last_trade']
                return Decimal(str(price))
            return Decimal('0')
        except Exception:
            return Decimal('0')

    async def create_order(self, pair: str, quantity: Decimal, price: Decimal, order_type: str) -> Dict[str, Any]:
        """Создание ордера через старый клиент"""
        try:
            result = self.old_client.create_order(pair, float(quantity), float(price), order_type)
            return result or {'result': False}
        except Exception as e:
            return {'result': False, 'error': str(e)}
