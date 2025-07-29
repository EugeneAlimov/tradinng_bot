import time
import logging
from typing import Dict, Any, Optional, Tuple
from config import TradingConfig


class APIService:
    """🌐 Единый сервис для всех API операций с кэшированием"""

    def __init__(self, api_client, config: TradingConfig):
        self.api = api_client
        self.config = config
        self.logger = logging.getLogger(__name__)

        # Кэш для оптимизации повторных запросов
        self._balance_cache = {}
        self._price_cache = {}
        self._pair_settings_cache = None
        self._cache_timeout = 5  # 5 секунд

    def get_balance(self, currency: str) -> float:
        """💰 Получение баланса с кэшированием"""
        cache_key = f"balance_{currency}"

        # Проверяем кэш
        if self._is_cache_valid(cache_key):
            return self._balance_cache[cache_key]['value']

        try:
            user_info = self.api.get_user_info()
            balance = float(user_info.get('balances', {}).get(currency, 0))

            # Кэшируем результат
            self._balance_cache[cache_key] = {
                'value': balance,
                'timestamp': time.time()
            }

            self.logger.debug(f"💰 Баланс {currency}: {balance}")
            return balance

        except Exception as e:
            self.logger.error(f"❌ Ошибка получения баланса {currency}: {e}")
            return 0.0

    def get_balances(self) -> Dict[str, float]:
        """💰 Получение всех балансов одним запросом"""
        try:
            user_info = self.api.get_user_info()
            balances = user_info.get('balances', {})

            # Кэшируем все балансы
            current_time = time.time()
            for currency, balance in balances.items():
                cache_key = f"balance_{currency}"
                self._balance_cache[cache_key] = {
                    'value': float(balance),
                    'timestamp': current_time
                }

            return {k: float(v) for k, v in balances.items()}

        except Exception as e:
            self.logger.error(f"❌ Ошибка получения балансов: {e}")
            return {}

    def get_current_price(self, pair: str) -> float:
        """💱 Получение текущей цены с кэшированием"""
        cache_key = f"price_{pair}"

        # Проверяем кэш (более короткий для цен - 2 секунды)
        if self._is_cache_valid(cache_key, timeout=2):
            return self._price_cache[cache_key]['value']

        try:
            trades = self.api.get_trades(pair)
            if pair in trades and trades[pair]:
                price = float(trades[pair][0]['price'])

                # Кэшируем цену
                self._price_cache[cache_key] = {
                    'value': price,
                    'timestamp': time.time()
                }

                return price
        except Exception as e:
            self.logger.error(f"❌ Ошибка получения цены {pair}: {e}")

        return 0.0

    def create_order_safe(self, pair: str, quantity: float,
                          price: float, order_type: str) -> Dict[str, Any]:
        """📝 Безопасное создание ордера с едиными проверками"""

        # Единая валидация параметров
        if not self._validate_order_params(pair, quantity, price, order_type):
            return {'result': False, 'error': 'Invalid order parameters'}

        try:
            # Получаем настройки пары (с кэшированием)
            pair_settings = self.get_pair_settings()
            pair_info = pair_settings.get(pair, {})

            # Проверяем минимальное количество
            min_quantity = float(pair_info.get('min_quantity', 5.0))
            if quantity < min_quantity:
                self.logger.warning(f"⚠️ Количество {quantity:.6f} < минимума {min_quantity:.6f}, увеличиваем")
                quantity = min_quantity

            # Единое округление цены
            precision = int(pair_info.get('price_precision', 8))
            price_rounded = round(price, precision)

            # Проверяем минимальную сумму
            min_amount = float(pair_info.get('min_amount', 10.0))
            order_amount = quantity * price_rounded

            if order_amount < min_amount:
                return {
                    'result': False,
                    'error': f'Order amount {order_amount:.4f} < minimum {min_amount}'
                }

            # Единое логирование
            self.logger.info(f"📝 Создаем ордер: {order_type.upper()} {quantity:.6f} {pair} по {price_rounded:.8f}")

            # Создаем ордер
            result = self.api.create_order(pair, quantity, price_rounded, order_type)

            if result.get('result'):
                self.logger.info(f"✅ Ордер создан: ID {result.get('order_id', 'N/A')}")
                # Сбрасываем кэш балансов после успешного ордера
                self._invalidate_balance_cache()
            else:
                self.logger.error(f"❌ Ошибка создания ордера: {result}")

            return result

        except Exception as e:
            self.logger.error(f"❌ Исключение при создании ордера: {e}")
            return {'result': False, 'error': str(e)}

    def get_pair_settings(self) -> Dict[str, Any]:
        """⚙️ Получение настроек пар с кэшированием"""
        # Кэшируем настройки пар на 1 час (они редко меняются)
        if (self._pair_settings_cache and
                time.time() - self._pair_settings_cache['timestamp'] < 3600):
            return self._pair_settings_cache['data']

        try:
            settings = self.api.get_pair_settings()
            self._pair_settings_cache = {
                'data': settings,
                'timestamp': time.time()
            }
            return settings

        except Exception as e:
            self.logger.error(f"❌ Ошибка получения настроек пар: {e}")
            return {}

    def get_open_orders(self):
        """📋 Получение открытых ордеров (прозрачно передаем в API)"""
        return self.api.get_open_orders()

    def cancel_order(self, order_id: int):
        """❌ Отмена ордера (прозрачно передаем в API)"""
        result = self.api.cancel_order(order_id)
        if result.get('result'):
            # Сбрасываем кэш балансов после отмены ордера
            self._invalidate_balance_cache()
        return result

    def get_user_trades(self, pair: str, limit: int = 100):
        """📊 Получение истории сделок (прозрачно передаем в API)"""
        return self.api.get_user_trades(pair, limit)

    def get_order_trades(self, order_id: int):
        """🔍 Получение сделок по ордеру (прозрачно передаем в API)"""
        return self.api.get_order_trades(order_id)

    def get_user_info(self):
        """👤 Получение информации о пользователе (прозрачно передаем в API)"""
        return self.api.get_user_info()

    def create_order(self, pair: str, quantity: float, price: float, order_type: str):
        """📝 Создание ордера (обертка для совместимости, использует create_order_safe)"""
        return self.create_order_safe(pair, quantity, price, order_type)

    def check_connection(self) -> bool:
        """🔗 Проверка соединения (прозрачно передаем в API)"""
        return self.api.check_connection()

    def _validate_order_params(self, pair: str, quantity: float,
                               price: float, order_type: str) -> bool:
        """✅ Валидация параметров ордера"""
        if not pair or not isinstance(pair, str):
            self.logger.error("❌ Некорректная пара")
            return False

        if quantity <= 0:
            self.logger.error(f"❌ Некорректное количество: {quantity}")
            return False

        if price <= 0:
            self.logger.error(f"❌ Некорректная цена: {price}")
            return False

        if order_type not in ['buy', 'sell']:
            self.logger.error(f"❌ Некорректный тип ордера: {order_type}")
            return False

        return True

    def _is_cache_valid(self, cache_key: str, timeout: int = None) -> bool:
        """⏰ Проверка валидности кэша"""
        if timeout is None:
            timeout = self._cache_timeout

        cache_dict = None
        if cache_key.startswith('balance_'):
            cache_dict = self._balance_cache
        elif cache_key.startswith('price_'):
            cache_dict = self._price_cache

        if not cache_dict or cache_key not in cache_dict:
            return False

        age = time.time() - cache_dict[cache_key]['timestamp']
        return age < timeout

    def _invalidate_balance_cache(self):
        """🗑️ Сброс кэша балансов"""
        self._balance_cache.clear()
        self.logger.debug("🗑️ Кэш балансов сброшен")

    def get_cache_stats(self) -> Dict[str, Any]:
        """📊 Статистика кэша"""
        return {
            'balance_cache_size': len(self._balance_cache),
            'price_cache_size': len(self._price_cache),
            'pair_settings_cached': self._pair_settings_cache is not None
        }