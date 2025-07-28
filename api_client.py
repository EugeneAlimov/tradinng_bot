import hmac
import hashlib
import time
import json
import requests
import logging
from typing import Dict, Any, Optional
from config import TradingConfig


class ExmoAPIError(Exception):
    pass


class ExmoAPIClient:
    def __init__(self, config: TradingConfig):
        self.config = config
        self.api_secret = bytes(config.API_SECRET, encoding='utf-8')
        self.logger = logging.getLogger(__name__)

        # 🔄 Создаем сессию для переиспользования соединений
        self.session = requests.Session()
        self.session.headers.update({
            "Content-type": "application/x-www-form-urlencoded",
            "User-Agent": "DOGE-Trading-Bot/1.0"
        })

        # ⚙️ Настройки retry и timeout
        self.max_retries = 3
        self.retry_delay = 2
        self.timeout = 30

        self.logger.info("🔗 API клиент инициализирован с retry логикой")

    def _create_signature(self, data: str) -> str:
        """Создание подписи для запроса"""
        H = hmac.new(key=self.api_secret, digestmod=hashlib.sha512)
        H.update(data.encode('utf-8'))
        return H.hexdigest()

    def _make_request_with_retry(self, method: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """🔄 Выполнение запроса с retry логикой"""
        if params is None:
            params = {}

        last_exception = None

        for attempt in range(self.max_retries):
            try:
                return self._make_single_request(method, params)

            except (requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout,
                    requests.exceptions.RequestException) as e:

                last_exception = e
                attempt_num = attempt + 1

                if attempt_num < self.max_retries:
                    delay = self.retry_delay * attempt_num  # Экспоненциальная задержка
                    self.logger.warning(f"⚠️ Попытка {attempt_num} неудачна: {str(e)}")
                    self.logger.warning(f"🔄 Повтор через {delay} секунд...")
                    time.sleep(delay)
                else:
                    self.logger.error(f"❌ Все {self.max_retries} попытки неудачны")

            except ExmoAPIError as e:
                # API ошибки не ретраим
                self.logger.error(f"❌ API ошибка: {str(e)}")
                raise e

            except Exception as e:
                # Неожиданные ошибки логируем и ретраим
                last_exception = e
                attempt_num = attempt + 1

                if attempt_num < self.max_retries:
                    self.logger.warning(f"⚠️ Неожиданная ошибка в попытке {attempt_num}: {str(e)}")
                    time.sleep(self.retry_delay)
                else:
                    self.logger.error(f"❌ Критическая ошибка после {self.max_retries} попыток")

        # Если дошли сюда - все попытки неудачны
        raise ExmoAPIError(
            f"Не удалось выполнить запрос после {self.max_retries} попыток. Последняя ошибка: {str(last_exception)}")

    def _make_single_request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """🌐 Выполнение одиночного запроса"""
        params['nonce'] = int(round(time.time() * 1000))
        payload = self._encode_params(params)

        sign = self._create_signature(payload)
        headers = {
            "Key": self.config.API_KEY,
            "Sign": sign
        }

        url = f"https://{self.config.API_URL}/{self.config.API_VERSION}/{method}"

        try:
            response = self.session.post(
                url,
                data=payload,
                headers=headers,
                timeout=self.timeout
            )

            # Проверяем HTTP статус
            response.raise_for_status()

            # Парсим JSON
            try:
                obj = response.json()
            except json.JSONDecodeError as e:
                raise ExmoAPIError(f"Неверный JSON ответ: {str(e)}")

            # Проверяем API ошибки
            if isinstance(obj, dict) and 'error' in obj and obj['error']:
                raise ExmoAPIError(f"API Error: {obj['error']}")

            return obj

        except requests.exceptions.Timeout:
            raise ExmoAPIError(f"Timeout при запросе {method}")
        except requests.exceptions.ConnectionError:
            raise ExmoAPIError(f"Connection error при запросе {method}")
        except requests.exceptions.HTTPError as e:
            raise ExmoAPIError(f"HTTP {e.response.status_code} при запросе {method}")

    def _encode_params(self, params: Dict[str, Any]) -> str:
        """📝 Кодирование параметров для POST запроса"""
        # Конвертируем все в строки и кодируем
        encoded_params = []
        for key, value in params.items():
            if value is not None:
                encoded_params.append(f"{key}={value}")
        return "&".join(encoded_params)

    def get_user_info(self) -> Dict[str, Any]:
        """👤 Получение информации о пользователе"""
        return self._make_request_with_retry('user_info')

    def get_open_orders(self) -> Dict[str, Any]:
        """📋 Получение открытых ордеров"""
        return self._make_request_with_retry('user_open_orders')

    def create_order(self, pair: str, quantity: float, price: float, order_type: str) -> Dict[str, Any]:
        """📝 Создание ордера"""
        params = {
            'pair': pair,
            'quantity': quantity,
            'price': price,
            'type': order_type
        }

        self.logger.info(f"📝 Создаем ордер: {order_type} {quantity} {pair} по {price}")
        result = self._make_request_with_retry('order_create', params)

        if result.get('result'):
            self.logger.info(f"✅ Ордер создан успешно: {result.get('order_id')}")
        else:
            self.logger.error(f"❌ Ошибка создания ордера: {result}")

        return result

    def cancel_order(self, order_id: int) -> Dict[str, Any]:
        """❌ Отмена ордера"""
        self.logger.info(f"❌ Отменяем ордер: {order_id}")
        result = self._make_request_with_retry('order_cancel', {'order_id': order_id})

        if result.get('result'):
            self.logger.info(f"✅ Ордер {order_id} отменен успешно")
        else:
            self.logger.error(f"❌ Ошибка отмены ордера {order_id}: {result}")

        return result

    def get_trades(self, pair: str) -> Dict[str, Any]:
        """📈 Получение последних сделок по паре"""
        return self._make_request_with_retry('trades', {'pair': pair})

    def get_user_trades(self, pair: str, limit: int = 100) -> Dict[str, Any]:
        """📊 Получение истории сделок пользователя"""
        params = {
            'pair': pair,
            'limit': limit
        }
        return self._make_request_with_retry('user_trades', params)

    def get_order_trades(self, order_id: int) -> Dict[str, Any]:
        """🔍 Получение сделок по конкретному ордеру"""
        return self._make_request_with_retry('order_trades', {'order_id': order_id})

    def get_pair_settings(self) -> Dict[str, Any]:
        """⚙️ Получение настроек торговых пар"""
        try:
            url = f"https://{self.config.API_URL}/{self.config.API_VERSION}/pair_settings"
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            return response.json()

        except Exception as e:
            raise ExmoAPIError(f"Error getting pair settings: {str(e)}")

    def check_connection(self) -> bool:
        """🔗 Проверка соединения с API"""
        try:
            self.get_pair_settings()
            self.logger.info("✅ Соединение с API работает")
            return True
        except Exception as e:
            self.logger.error(f"❌ Проблемы с соединением: {str(e)}")
            return False

    def close(self):
        """🔚 Закрытие сессии"""
        if self.session:
            self.session.close()
            self.logger.info("🔚 API сессия закрыта")

    def __enter__(self):
        """🔗 Context manager поддержка"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """🔚 Context manager поддержка"""
        self.close()