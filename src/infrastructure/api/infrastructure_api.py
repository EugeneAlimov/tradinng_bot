#!/usr/bin/env python3
"""🌐 Инфраструктурный слой - API клиенты"""

import time
import logging
import hashlib
import hmac
import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Union, Protocol
from decimal import Decimal
from datetime import datetime, timedelta
from collections import deque

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..core.interfaces import IExchangeAPI, ICacheService, IMonitoringService
from ..core.models import TradeOrder, TradingPair, APIResponse, ErrorInfo
from ..core.exceptions import APIError, RateLimitError, ConnectionError
from ..core.constants import API, Trading
from ..config.settings import APISettings


@dataclass
class APIMetrics:
    """📊 Метрики API"""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    average_response_time: float = 0.0
    rate_limit_hits: int = 0
    last_request_time: datetime = field(default_factory=datetime.now)
    
    @property
    def success_rate(self) -> float:
        """Процент успешных запросов"""
        if self.total_requests == 0:
            return 100.0
        return (self.successful_requests / self.total_requests) * 100
    
    @property
    def error_rate(self) -> float:
        """Процент ошибочных запросов"""
        return 100.0 - self.success_rate


class RateLimiter:
    """⚡ Умный ограничитель частоты запросов"""
    
    def __init__(
        self, 
        calls_per_minute: int = 30, 
        calls_per_hour: int = 300,
        adaptive: bool = True
    ):
        self.calls_per_minute = calls_per_minute
        self.calls_per_hour = calls_per_hour
        self.adaptive = adaptive
        
        # Очереди для отслеживания запросов
        self.minute_calls: deque = deque()
        self.hour_calls: deque = deque()
        
        # Адаптивное управление
        self.adaptive_delay = 0.0
        self.error_count = 0
        self.last_error_time = 0.0
        
        # Статистика
        self.metrics = APIMetrics()
        
        self.logger = logging.getLogger(__name__)
    
    async def acquire_permit(self, endpoint: str = "unknown") -> float:
        """🎫 Получение разрешения на запрос"""
        current_time = time.time()
        
        # Очищаем старые записи
        self._cleanup_old_calls(current_time)
        
        # Рассчитываем время ожидания
        wait_time = self._calculate_wait_time(current_time)
        
        if wait_time > 0:
            self.logger.debug(f"⏳ Rate limit: ожидание {wait_time:.1f}с для {endpoint}")
            await asyncio.sleep(wait_time)
        
        # Добавляем адаптивную задержку
        if self.adaptive_delay > 0:
            await asyncio.sleep(self.adaptive_delay)
        
        # Регистрируем вызов
        self._register_call(current_time)
        
        return wait_time + self.adaptive_delay
    
    def register_success(self, response_time: float) -> None:
        """✅ Регистрация успешного запроса"""
        self.metrics.successful_requests += 1
        self.metrics.total_requests += 1
        self.metrics.last_request_time = datetime.now()
        
        # Обновляем среднее время ответа
        total_time = self.metrics.average_response_time * (self.metrics.successful_requests - 1)
        self.metrics.average_response_time = (total_time + response_time) / self.metrics.successful_requests
        
        # Уменьшаем адаптивную задержку при успешных запросах
        if self.adaptive and self.adaptive_delay > 0:
            self.adaptive_delay = max(0, self.adaptive_delay - 0.1)
    
    def register_error(self, error_type: str) -> None:
        """❌ Регистрация ошибки"""
        self.metrics.failed_requests += 1
        self.metrics.total_requests += 1
        self.metrics.last_request_time = datetime.now()
        
        if "rate_limit" in error_type.lower() or "429" in error_type:
            self.metrics.rate_limit_hits += 1
            self.error_count += 1
            self.last_error_time = time.time()
            
            if self.adaptive:
                # Увеличиваем задержку при ошибках rate limit
                self.adaptive_delay = min(30.0, self.adaptive_delay + 2.0)
                self.logger.warning(f"🚨 Rate limit hit, увеличиваем задержку до {self.adaptive_delay:.1f}с")
    
    def _cleanup_old_calls(self, current_time: float) -> None:
        """🧹 Очистка старых записей"""
        minute_threshold = current_time - 60
        hour_threshold = current_time - 3600
        
        while self.minute_calls and self.minute_calls[0] <= minute_threshold:
            self.minute_calls.popleft()
        
        while self.hour_calls and self.hour_calls[0] <= hour_threshold:
            self.hour_calls.popleft()
    
    def _calculate_wait_time(self, current_time: float) -> float:
        """⏱️ Расчет времени ожидания"""
        wait_times = []
        
        # Проверяем лимит по минутам
        if len(self.minute_calls) >= self.calls_per_minute:
            oldest_call = self.minute_calls[0]
            wait_time = 60 - (current_time - oldest_call)
            if wait_time > 0:
                wait_times.append(wait_time)
        
        # Проверяем лимит по часам
        if len(self.hour_calls) >= self.calls_per_hour:
            oldest_call = self.hour_calls[0]
            wait_time = 3600 - (current_time - oldest_call)
            if wait_time > 0:
                wait_times.append(wait_time)
        
        return max(wait_times) if wait_times else 0.0
    
    def _register_call(self, current_time: float) -> None:
        """📝 Регистрация вызова"""
        self.minute_calls.append(current_time)
        self.hour_calls.append(current_time)
    
    def get_status(self) -> Dict[str, Any]:
        """📊 Получение статуса rate limiter"""
        current_time = time.time()
        self._cleanup_old_calls(current_time)
        
        return {
            "limits": {
                "calls_per_minute": self.calls_per_minute,
                "calls_per_hour": self.calls_per_hour
            },
            "current_load": {
                "calls_this_minute": len(self.minute_calls),
                "calls_this_hour": len(self.hour_calls),
                "load_percentage_minute": (len(self.minute_calls) / self.calls_per_minute) * 100,
                "load_percentage_hour": (len(self.hour_calls) / self.calls_per_hour) * 100
            },
            "adaptive": {
                "enabled": self.adaptive,
                "current_delay": self.adaptive_delay,
                "error_count": self.error_count,
                "minutes_since_last_error": (current_time - self.last_error_time) / 60 if self.last_error_time > 0 else None
            },
            "metrics": {
                "total_requests": self.metrics.total_requests,
                "success_rate": self.metrics.success_rate,
                "error_rate": self.metrics.error_rate,
                "average_response_time": self.metrics.average_response_time,
                "rate_limit_hits": self.metrics.rate_limit_hits
            }
        }


class HTTPClient:
    """🌐 HTTP клиент с retry логикой"""
    
    def __init__(self, base_url: str, timeout: int = 10, max_retries: int = 3):
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        
        # Создаем сессию с retry стратегией
        self.session = requests.Session()
        
        retry_strategy = Retry(
            total=max_retries,
            status_forcelist=[429, 500, 502, 503, 504],
            method_whitelist=["HEAD", "GET", "OPTIONS", "POST"],
            backoff_factor=1
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        
        self.logger = logging.getLogger(__name__)
    
    async def get(self, endpoint: str, params: Optional[Dict] = None) -> requests.Response:
        """GET запрос"""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        return await self._make_request("GET", url, params=params)
    
    async def post(self, endpoint: str, data: Optional[Dict] = None, headers: Optional[Dict] = None) -> requests.Response:
        """POST запрос"""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        return await self._make_request("POST", url, data=data, headers=headers)
    
    async def _make_request(self, method: str, url: str, **kwargs) -> requests.Response:
        """Выполнение запроса"""
        kwargs.setdefault('timeout', self.timeout)
        
        try:
            # Выполняем запрос в отдельном потоке чтобы не блокировать event loop
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, 
                lambda: self.session.request(method, url, **kwargs)
            )
            
            # Проверяем статус ответа
            response.raise_for_status()
            return response
            
        except requests.exceptions.Timeout as e:
            raise ConnectionError(f"Timeout при запросе к {url}") from e
        except requests.exceptions.ConnectionError as e:
            raise ConnectionError(f"Ошибка соединения с {url}") from e
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                raise RateLimitError("Превышен лимит запросов") from e
            raise APIError(f"HTTP ошибка {e.response.status_code}: {e.response.text}") from e
        except Exception as e:
            raise APIError(f"Неожиданная ошибка при запросе: {str(e)}") from e


class ExmoAPIClient(IExchangeAPI):
    """🏛️ EXMO API клиент с полной функциональностью"""
    
    def __init__(self, settings: APISettings, rate_limiter: Optional[RateLimiter] = None):
        self.settings = settings
        self.rate_limiter = rate_limiter or RateLimiter(
            settings.calls_per_minute,
            settings.calls_per_hour,
            settings.adaptive_rate_limiting
        )
        
        self.http_client = HTTPClient(
            settings.exmo_base_url,
            settings.exmo_timeout,
            settings.exmo_max_retries
        )
        
        self.logger = logging.getLogger(__name__)
        
        # Кэш для минимизации повторных запросов
        self._cache: Dict[str, Any] = {}
        self._cache_timestamps: Dict[str, datetime] = {}
    
    async def get_balance(self, currency: str) -> Decimal:
        """💰 Получение баланса валюты"""
        try:
            user_info = await self._authenticated_request("user_info")
            
            if user_info and "balances" in user_info:
                balance_str = user_info["balances"].get(currency, "0")
                return Decimal(str(balance_str))
            
            return Decimal("0")
            
        except Exception as e:
            self.logger.error(f"Ошибка получения баланса {currency}: {e}")
            return Decimal("0")
    
    async def get_current_price(self, pair: str) -> Decimal:
        """💱 Получение текущей цены пары"""
        try:
            # Проверяем кэш
            cache_key = f"price_{pair}"
            if self._is_cache_valid(cache_key, self.settings.cache_price_ttl):
                return Decimal(str(self._cache[cache_key]))
            
            ticker_data = await self._public_request("ticker")
            
            if ticker_data and pair in ticker_data:
                price_str = ticker_data[pair]["last_trade"]
                price = Decimal(str(price_str))
                
                # Сохраняем в кэш
                self._update_cache(cache_key, float(price))
                
                return price
            
            raise APIError(f"Пара {pair} не найдена в ticker данных")
            
        except Exception as e:
            self.logger.error(f"Ошибка получения цены {pair}: {e}")
            raise APIError(f"Не удалось получить цену для {pair}") from e
    
    async def create_order(
        self,
        pair: str,
        quantity: Decimal,
        price: Decimal,
        order_type: str
    ) -> Dict[str, Any]:
        """📝 Создание ордера"""
        try:
            # Валидация параметров
            await self._validate_order_params(pair, quantity, price, order_type)
            
            params = {
                "pair": pair,
                "quantity": str(quantity),
                "price": str(price),
                "type": order_type
            }
            
            self.logger.info(f"📝 Создаем ордер: {order_type.upper()} {quantity} {pair} по {price}")
            
            result = await self._authenticated_request("order_create", params)
            
            if result and result.get("result"):
                self.logger.info(f"✅ Ордер создан: ID {result.get('order_id')}")
                
                # Инвалидируем кэш баланса
                self._invalidate_balance_cache()
                
                return {
                    "success": True,
                    "order_id": result.get("order_id"),
                    "result": result
                }
            else:
                error_msg = result.get("error", "Неизвестная ошибка") if result else "Пустой ответ API"
                self.logger.error(f"❌ Ошибка создания ордера: {error_msg}")
                return {
                    "success": False,
                    "error": error_msg,
                    "result": result
                }
                
        except Exception as e:
            self.logger.error(f"❌ Исключение при создании ордера: {e}")
            return {
                "success": False,
                "error": str(e),
                "result": None
            }
    
    async def get_order_book(self, pair: str, limit: int = 100) -> Dict[str, Any]:
        """📊 Получение стакана ордеров"""
        try:
            params = {"pair": pair}
            if limit != 100:
                params["limit"] = str(limit)
            
            return await self._public_request("order_book", params)
            
        except Exception as e:
            self.logger.error(f"Ошибка получения стакана {pair}: {e}")
            raise APIError(f"Не удалось получить стакан для {pair}") from e
    
    async def get_trades_history(self, pair: str, limit: int = 100) -> List[Dict[str, Any]]:
        """📈 Получение истории сделок"""
        try:
            params = {"pair": pair}
            if limit != 100:
                params["limit"] = str(limit)
            
            result = await self._authenticated_request("user_trades", params)
            
            if result and pair in result:
                return result[pair]
            
            return []
            
        except Exception as e:
            self.logger.error(f"Ошибка получения истории сделок {pair}: {e}")
            return []
    
    async def get_open_orders(self) -> Dict[str, Any]:
        """📋 Получение открытых ордеров"""
        try:
            return await self._authenticated_request("user_open_orders") or {}
        except Exception as e:
            self.logger.error(f"Ошибка получения открытых ордеров: {e}")
            return {}
    
    async def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """❌ Отмена ордера"""
        try:
            params = {"order_id": order_id}
            result = await self._authenticated_request("order_cancel", params)
            
            if result and result.get("result"):
                self.logger.info(f"✅ Ордер {order_id} отменен")
                return {"success": True, "result": result}
            else:
                error_msg = result.get("error", "Неизвестная ошибка") if result else "Пустой ответ API"
                return {"success": False, "error": error_msg}
                
        except Exception as e:
            self.logger.error(f"Ошибка отмены ордера {order_id}: {e}")
            return {"success": False, "error": str(e)}
    
    async def _public_request(self, endpoint: str, params: Optional[Dict] = None) -> Optional[Dict]:
        """🔓 Публичный API запрос"""
        try:
            await self.rate_limiter.acquire_permit(endpoint)
            
            start_time = time.time()
            response = await self.http_client.get(endpoint, params)
            response_time = time.time() - start_time
            
            self.rate_limiter.register_success(response_time)
            
            return response.json()
            
        except Exception as e:
            self.rate_limiter.register_error(str(e))
            raise
    
    async def _authenticated_request(self, endpoint: str, params: Optional[Dict] = None) -> Optional[Dict]:
        """🔐 Аутентифицированный API запрос"""
        if params is None:
            params = {}
        
        # Добавляем nonce
        params["nonce"] = str(int(time.time() * 1000))
        
        # Создаем подпись
        post_data = "&".join([f"{k}={v}" for k, v in params.items()])
        signature = hmac.new(
            self.settings.exmo_api_secret.encode(),
            post_data.encode(),
            hashlib.sha512
        ).hexdigest()
        
        headers = {
            "Key": self.settings.exmo_api_key,
            "Sign": signature,
            "Content-Type": "application/x-www-form-urlencoded"
        }
        
        try:
            await self.rate_limiter.acquire_permit(endpoint)
            
            start_time = time.time()
            response = await self.http_client.post(endpoint, data=params, headers=headers)
            response_time = time.time() - start_time
            
            self.rate_limiter.register_success(response_time)
            
            return response.json()
            
        except Exception as e:
            self.rate_limiter.register_error(str(e))
            raise
    
    async def _validate_order_params(self, pair: str, quantity: Decimal, price: Decimal, order_type: str) -> None:
        """✅ Валидация параметров ордера"""
        if quantity <= 0:
            raise APIError("Количество должно быть положительным")
        
        if price <= 0:
            raise APIError("Цена должна быть положительной")
        
        if order_type not in ["buy", "sell"]:
            raise APIError("Тип ордера должен быть 'buy' или 'sell'")
        
        # Проверяем минимальные значения (можно расширить)
        if quantity < Trading.MIN_QUANTITY:
            raise APIError(f"Количество меньше минимального: {Trading.MIN_QUANTITY}")
        
        if price < Trading.MIN_PRICE:
            raise APIError(f"Цена меньше минимальной: {Trading.MIN_PRICE}")
    
    def _is_cache_valid(self, key: str, ttl_seconds: int) -> bool:
        """🕒 Проверка валидности кэша"""
        if key not in self._cache or key not in self._cache_timestamps:
            return False
        
        age = datetime.now() - self._cache_timestamps[key]
        return age.total_seconds() < ttl_seconds
    
    def _update_cache(self, key: str, value: Any) -> None:
        """💾 Обновление кэша"""
        self._cache[key] = value
        self._cache_timestamps[key] = datetime.now()
    
    def _invalidate_balance_cache(self) -> None:
        """🗑️ Инвалидация кэша балансов"""
        keys_to_remove = [key for key in self._cache.keys() if key.startswith("balance_")]
        for key in keys_to_remove:
            self._cache.pop(key, None)
            self._cache_timestamps.pop(key, None)
    
    def get_status(self) -> Dict[str, Any]:
        """📊 Получение статуса API клиента"""
        return {
            "client_type": "ExmoAPIClient",
            "rate_limiter": self.rate_limiter.get_status(),
            "cache": {
                "entries": len(self._cache),
                "cache_keys": list(self._cache.keys())
            },
            "settings": {
                "base_url": self.settings.exmo_base_url,
                "timeout": self.settings.exmo_timeout,
                "max_retries": self.settings.exmo_max_retries,
                "cache_enabled": self.settings.cache_enabled
            }
        }


# Фабрика для создания API клиентов
class APIClientFactory:
    """🏭 Фабрика API клиентов"""
    
    @staticmethod
    def create_exmo_client(settings: APISettings) -> ExmoAPIClient:
        """Создание EXMO клиента"""
        rate_limiter = RateLimiter(
            settings.calls_per_minute,
            settings.calls_per_hour,
            settings.adaptive_rate_limiting
        )
        
        return ExmoAPIClient(settings, rate_limiter)
    
    @staticmethod
    def create_client_from_config(exchange: str, settings: APISettings) -> IExchangeAPI:
        """Создание клиента по названию биржи"""
        if exchange.lower() == "exmo":
            return APIClientFactory.create_exmo_client(settings)
        else:
            raise ValueError(f"Неподдерживаемая биржа: {exchange}")
