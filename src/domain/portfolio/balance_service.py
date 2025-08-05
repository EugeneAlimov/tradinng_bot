from typing import Optional, Dict, Any, List, Tuple
from decimal import Decimal
from datetime import datetime, timedelta
import logging
from dataclasses import dataclass, field
from enum import Enum
import asyncio

# Импорты из Core слоя
try:
    from ...core.interfaces import IExchangeAPI
    from ...core.models import Money, TradingPair, Trade, Position
    from ...core.exceptions import (
        TradingSystemError, InsufficientBalanceError,
        DataError, ValidationError
    )
    from ...core.events import DomainEvent, publish_event
    from ...config.settings import get_current_config
except ImportError:
    # Fallback для случая если Core слой еще не готов
    class IExchangeAPI: pass
    class Money: pass
    class TradingPair: pass
    class Trade: pass
    class Position: pass
    class TradingSystemError(Exception): pass
    class InsufficientBalanceError(Exception): pass
    class DataError(Exception): pass
    class ValidationError(Exception): pass
    class DomainEvent: pass
    def publish_event(event): pass
    def get_current_config(): return None


# ================= ТИПЫ БАЛАНСОВ =================

class BalanceType(Enum):
    """💰 Типы балансов"""
    AVAILABLE = "available"      # Доступный баланс
    RESERVED = "reserved"        # Зарезервированный в ордерах
    TOTAL = "total"             # Общий баланс
    FROZEN = "frozen"           # Замороженный баланс


class ReservationReason(Enum):
    """🔒 Причины резервирования"""
    OPEN_ORDER = "open_order"           # Открытые ордера
    RISK_MANAGEMENT = "risk_management" # Риск-менеджмент
    MANUAL_LOCK = "manual_lock"         # Ручная блокировка
    MAINTENANCE = "maintenance"         # Техническое обслуживание


@dataclass
class BalanceInfo:
    """💰 Информация о балансе"""
    currency: str
    available: Decimal
    reserved: Decimal
    total: Decimal
    last_updated: datetime = field(default_factory=datetime.now)
    frozen: Decimal = Decimal('0')
    pending_deposits: Decimal = Decimal('0')
    pending_withdrawals: Decimal = Decimal('0')

    @property
    def free_balance(self) -> Decimal:
        """Свободный баланс (доступный - зарезервированный)"""
        return max(self.available - self.reserved, Decimal('0'))

    @property
    def utilization_percent(self) -> float:
        """Процент использования баланса"""
        if self.total <= 0:
            return 0.0
        return float((self.total - self.available) / self.total * 100)

    def to_money(self) -> Money:
        """Конвертация в Money объект"""
        return Money(self.available, self.currency)


@dataclass
class BalanceReservation:
    """🔒 Резервирование баланса"""
    id: str
    currency: str
    amount: Decimal
    reason: ReservationReason
    description: str
    created_at: datetime = field(default_factory=datetime.now)
    expires_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        """Истекло ли резервирование"""
        return self.expires_at is not None and datetime.now() > self.expires_at

    @property
    def age_minutes(self) -> float:
        """Возраст резервирования в минутах"""
        return (datetime.now() - self.created_at).total_seconds() / 60


@dataclass
class PortfolioSummary:
    """📊 Сводка портфеля"""
    total_value_eur: Decimal
    total_value_usd: Decimal
    balances: Dict[str, BalanceInfo]
    largest_holding: str
    diversification_score: float
    last_updated: datetime = field(default_factory=datetime.now)

    @property
    def currencies_count(self) -> int:
        """Количество валют в портфеле"""
        return len([b for b in self.balances.values() if b.total > 0])

    @property
    def dominant_currency_percent(self) -> float:
        """Процент доминирующей валюты"""
        if not self.balances or self.total_value_eur <= 0:
            return 0.0

        max_value = max(
            balance.total for balance in self.balances.values()
        )
        return float(max_value / self.total_value_eur * 100)


# ================= ОСНОВНОЙ СЕРВИС =================

class BalanceService:
    """💰 Сервис управления балансами"""

    def __init__(
        self,
        exchange_api: Optional[IExchangeAPI] = None,
        cache_ttl_seconds: int = 30
    ):
        self.exchange_api = exchange_api
        self.cache_ttl = timedelta(seconds=cache_ttl_seconds)

        # Кэш балансов
        self.balance_cache: Dict[str, Tuple[datetime, BalanceInfo]] = {}

        # Резервирования
        self.reservations: Dict[str, BalanceReservation] = {}

        # История изменений
        self.balance_history: List[Dict[str, Any]] = []
        self.max_history_size = 1000

        # Курсы валют (заглушка для конвертации)
        self.exchange_rates: Dict[str, Decimal] = {
            'EUR': Decimal('1.0'),
            'USD': Decimal('0.85'),
            'BTC': Decimal('45000.0'),
            'ETH': Decimal('2500.0'),
            'DOGE': Decimal('0.08')
        }

        # Логирование
        self.logger = logging.getLogger(__name__)

        self.logger.info("💰 BalanceService инициализирован")

    # ================= ОСНОВНЫЕ МЕТОДЫ =================

    async def get_balance(self, currency: str) -> BalanceInfo:
        """💰 Получение баланса валюты"""

        try:
            currency = currency.upper()

            # Проверяем кэш
            if currency in self.balance_cache:
                cached_time, cached_balance = self.balance_cache[currency]
                if datetime.now() - cached_time < self.cache_ttl:
                    return cached_balance

            # Получаем актуальный баланс
            balance = await self._fetch_balance(currency)

            # Применяем резервирования
            balance = await self._apply_reservations(balance)

            # Кэшируем
            self.balance_cache[currency] = (datetime.now(), balance)

            return balance

        except Exception as e:
            self.logger.error(f"❌ Ошибка получения баланса {currency}: {e}")
            raise DataError(f"Failed to get balance for {currency}: {e}")

    async def get_all_balances(self) -> Dict[str, BalanceInfo]:
        """💰 Получение всех балансов"""

        try:
            if self.exchange_api:
                # Получаем через API
                raw_balances = await self.exchange_api.get_balances()

                balances = {}
                for currency, amount in raw_balances.items():
                    balance_info = BalanceInfo(
                        currency=currency.upper(),
                        available=Decimal(str(amount)),
                        reserved=Decimal('0'),
                        total=Decimal(str(amount))
                    )

                    # Применяем резервирования
                    balance_info = await self._apply_reservations(balance_info)
                    balances[currency.upper()] = balance_info

                # Обновляем кэш
                for currency, balance in balances.items():
                    self.balance_cache[currency] = (datetime.now(), balance)

                return balances

            else:
                # Используем кэш или создаем заглушки
                return await self._get_fallback_balances()

        except Exception as e:
            self.logger.error(f"❌ Ошибка получения всех балансов: {e}")
            return {}

    async def check_balance_sufficiency(
        self,
        currency: str,
        required_amount: Decimal,
        include_reserved: bool = False
    ) -> Tuple[bool, Decimal]:
        """✅ Проверка достаточности баланса"""

        try:
            balance = await self.get_balance(currency)

            available_amount = balance.total if include_reserved else balance.free_balance

            is_sufficient = available_amount >= required_amount
            deficit = max(required_amount - available_amount, Decimal('0'))

            return is_sufficient, deficit

        except Exception as e:
            self.logger.error(f"❌ Ошибка проверки баланса {currency}: {e}")
            return False, required_amount

    async def reserve_balance(
        self,
        currency: str,
        amount: Decimal,
        reason: ReservationReason,
        description: str,
        duration_minutes: Optional[int] = None
    ) -> str:
        """🔒 Резервирование баланса"""

        try:
            # Проверяем достаточность баланса
            is_sufficient, deficit = await self.check_balance_sufficiency(currency, amount)

            if not is_sufficient:
                raise InsufficientBalanceError(
                    required=amount,
                    available=amount - deficit,
                    currency=currency
                )

            # Создаем резервирование
            reservation_id = f"res_{currency}_{datetime.now().timestamp()}"

            expires_at = None
            if duration_minutes:
                expires_at = datetime.now() + timedelta(minutes=duration_minutes)

            reservation = BalanceReservation(
                id=reservation_id,
                currency=currency.upper(),
                amount=amount,
                reason=reason,
                description=description,
                expires_at=expires_at
            )

            self.reservations[reservation_id] = reservation

            # Очищаем кэш для пересчета
            if currency.upper() in self.balance_cache:
                del self.balance_cache[currency.upper()]

            # Записываем в историю
            await self._record_balance_change(
                currency, "reserve", amount, f"Reserved: {description}"
            )

            self.logger.info(f"🔒 Зарезервировано {amount} {currency}: {description}")

            return reservation_id

        except Exception as e:
            self.logger.error(f"❌ Ошибка резервирования {amount} {currency}: {e}")
            raise

    async def release_reservation(self, reservation_id: str) -> bool:
        """🔓 Освобождение резервирования"""

        try:
            if reservation_id not in self.reservations:
                self.logger.warning(f"⚠️ Резервирование {reservation_id} не найдено")
                return False

            reservation = self.reservations[reservation_id]

            # Удаляем резервирование
            del self.reservations[reservation_id]

            # Очищаем кэш
            if reservation.currency in self.balance_cache:
                del self.balance_cache[reservation.currency]

            # Записываем в историю
            await self._record_balance_change(
                reservation.currency, "release", reservation.amount,
                f"Released: {reservation.description}"
            )

            self.logger.info(f"🔓 Освобождено резервирование {reservation_id}: {reservation.amount} {reservation.currency}")

            return True

        except Exception as e:
            self.logger.error(f"❌ Ошибка освобождения резервирования {reservation_id}: {e}")
            return False

    async def get_portfolio_summary(self) -> PortfolioSummary:
        """📊 Сводка портфеля"""

        try:
            balances = await self.get_all_balances()

            total_value_eur = Decimal('0')
            total_value_usd = Decimal('0')

            # Рассчитываем общую стоимость
            for currency, balance in balances.items():
                if balance.total > 0:
                    eur_rate = self.exchange_rates.get(currency, Decimal('0'))
                    usd_rate = eur_rate * self.exchange_rates.get('USD', Decimal('0.85'))

                    total_value_eur += balance.total * eur_rate
                    total_value_usd += balance.total * usd_rate

            # Находим крупнейшую позицию
            largest_holding = ""
            max_value = Decimal('0')

            for currency, balance in balances.items():
                if balance.total > 0:
                    eur_rate = self.exchange_rates.get(currency, Decimal('0'))
                    value = balance.total * eur_rate
                    if value > max_value:
                        max_value = value
                        largest_holding = currency

            # Рассчитываем диверсификацию (простой индекс)
            diversification_score = self._calculate_diversification_score(balances)

            return PortfolioSummary(
                total_value_eur=total_value_eur,
                total_value_usd=total_value_usd,
                balances=balances,
                largest_holding=largest_holding,
                diversification_score=diversification_score
            )

        except Exception as e:
            self.logger.error(f"❌ Ошибка получения сводки портфеля: {e}")
            raise DataError(f"Failed to get portfolio summary: {e}")

    async def update_balance_after_trade(self, trade: Trade) -> None:
        """🔄 Обновление баланса после сделки"""

        try:
            base_currency = trade.pair.base
            quote_currency = trade.pair.quote

            # Очищаем кэш для обеих валют
            for currency in [base_currency, quote_currency]:
                if currency in self.balance_cache:
                    del self.balance_cache[currency]

            if trade.order_type.value.lower() == 'buy':
                # Покупка: увеличиваем base, уменьшаем quote
                await self._record_balance_change(
                    base_currency, "increase", trade.quantity,
                    f"Buy trade: {trade.id}"
                )
                await self._record_balance_change(
                    quote_currency, "decrease", trade.total_cost + trade.commission,
                    f"Buy trade cost: {trade.id}"
                )
            else:
                # Продажа: уменьшаем base, увеличиваем quote
                await self._record_balance_change(
                    base_currency, "decrease", trade.quantity,
                    f"Sell trade: {trade.id}"
                )
                await self._record_balance_change(
                    quote_currency, "increase", trade.total_cost - trade.commission,
                    f"Sell trade proceeds: {trade.id}"
                )

            # Публикуем событие об изменении баланса
            await self._publish_balance_update_event(trade)

        except Exception as e:
            self.logger.error(f"❌ Ошибка обновления баланса после сделки {trade.id}: {e}")

    # ================= ПРИВАТНЫЕ МЕТОДЫ =================

    async def _fetch_balance(self, currency: str) -> BalanceInfo:
        """📥 Получение баланса от биржи"""

        try:
            if self.exchange_api:
                balance_amount = await self.exchange_api.get_balance(currency)

                return BalanceInfo(
                    currency=currency,
                    available=balance_amount,
                    reserved=Decimal('0'),
                    total=balance_amount
                )
            else:
                # Заглушка для тестирования
                return BalanceInfo(
                    currency=currency,
                    available=Decimal('1000'),  # Заглушка
                    reserved=Decimal('0'),
                    total=Decimal('1000')
                )

        except Exception as e:
            self.logger.error(f"❌ Ошибка получения баланса {currency} от биржи: {e}")
            raise

    async def _apply_reservations(self, balance: BalanceInfo) -> BalanceInfo:
        """🔒 Применение резервирований к балансу"""

        try:
            # Очищаем истекшие резервирования
            await self._cleanup_expired_reservations()

            # Суммируем резервирования для данной валюты
            total_reserved = Decimal('0')

            for reservation in self.reservations.values():
                if reservation.currency == balance.currency:
                    total_reserved += reservation.amount

            # Обновляем баланс
            balance.reserved = total_reserved
            balance.available = max(balance.total - total_reserved, Decimal('0'))

            return balance

        except Exception as e:
            self.logger.error(f"❌ Ошибка применения резервирований: {e}")
            return balance

    async def _cleanup_expired_reservations(self) -> None:
        """🧹 Очистка истекших резервирований"""

        try:
            expired_ids = [
                res_id for res_id, reservation in self.reservations.items()
                if reservation.is_expired
            ]

            for res_id in expired_ids:
                reservation = self.reservations[res_id]
                del self.reservations[res_id]

                self.logger.info(f"🧹 Очищено истекшее резервирование: {res_id}")

                # Записываем в историю
                await self._record_balance_change(
                    reservation.currency, "expired_release", reservation.amount,
                    f"Expired reservation: {reservation.description}"
                )

        except Exception as e:
            self.logger.error(f"❌ Ошибка очистки истекших резервирований: {e}")

    async def _get_fallback_balances(self) -> Dict[str, BalanceInfo]:
        """🔄 Получение fallback балансов"""

        # Заглушки для основных валют
        fallback_balances = {
            'EUR': BalanceInfo('EUR', Decimal('1000'), Decimal('0'), Decimal('1000')),
            'USD': BalanceInfo('USD', Decimal('1200'), Decimal('0'), Decimal('1200')),
            'DOGE': BalanceInfo('DOGE', Decimal('10000'), Decimal('0'), Decimal('10000')),
            'BTC': BalanceInfo('BTC', Decimal('0.05'), Decimal('0'), Decimal('0.05'))
        }

        # Применяем резервирования
        for currency, balance in fallback_balances.items():
            fallback_balances[currency] = await self._apply_reservations(balance)

        return fallback_balances

    def _calculate_diversification_score(self, balances: Dict[str, BalanceInfo]) -> float:
        """📊 Расчет индекса диверсификации"""

        try:
            if not balances:
                return 0.0

            # Рассчитываем веса валют
            total_value = Decimal('0')
            values = {}

            for currency, balance in balances.items():
                if balance.total > 0:
                    rate = self.exchange_rates.get(currency, Decimal('0'))
                    value = balance.total * rate
                    values[currency] = value
                    total_value += value

            if total_value <= 0:
                return 0.0

            # Рассчитываем индекс Херфиндаля-Хиршмана (обратный)
            hhi = sum((value / total_value) ** 2 for value in values.values())

            # Нормализуем к 0-100
            max_currencies = len(values)
            if max_currencies <= 1:
                return 0.0

            perfect_diversification = 1.0 / max_currencies
            diversification_score = ((1.0 / max_currencies) / hhi) * 100

            return min(diversification_score, 100.0)

        except Exception as e:
            self.logger.error(f"❌ Ошибка расчета диверсификации: {e}")
            return 0.0

    async def _record_balance_change(
        self,
        currency: str,
        change_type: str,
        amount: Decimal,
        description: str
    ) -> None:
        """📝 Запись изменения баланса в историю"""

        try:
            change_record = {
                'timestamp': datetime.now().isoformat(),
                'currency': currency,
                'change_type': change_type,
                'amount': str(amount),
                'description': description
            }

            self.balance_history.append(change_record)

            # Ограничиваем размер истории
            if len(self.balance_history) > self.max_history_size:
                self.balance_history = self.balance_history[-self.max_history_size//2:]

        except Exception as e:
            self.logger.error(f"❌ Ошибка записи изменения баланса: {e}")

    async def _publish_balance_update_event(self, trade: Trade) -> None:
        """📡 Публикация события обновления баланса"""

        try:
            event = DomainEvent()
            event.event_type = "balance_updated"
            event.source = "balance_service"
            event.metadata = {
                'trade_id': trade.id,
                'base_currency': trade.pair.base,
                'quote_currency': trade.pair.quote,
                'order_type': trade.order_type.value,
                'quantity': str(trade.quantity),
                'total_cost': str(trade.total_cost)
            }

            await publish_event(event)

        except Exception as e:
            self.logger.error(f"❌ Ошибка публикации события баланса: {e}")

    # ================= УПРАВЛЕНИЕ И МОНИТОРИНГ =================

    async def refresh_all_balances(self) -> None:
        """🔄 Принудительное обновление всех балансов"""

        try:
            # Очищаем кэш
            self.balance_cache.clear()

            # Получаем актуальные балансы
            await self.get_all_balances()

            self.logger.info("🔄 Все балансы обновлены")

        except Exception as e:
            self.logger.error(f"❌ Ошибка обновления балансов: {e}")

    def get_reservations_summary(self) -> Dict[str, Any]:
        """📊 Сводка резервирований"""

        try:
            total_reservations = len(self.reservations)
            reservations_by_currency = {}
            reservations_by_reason = {}

            for reservation in self.reservations.values():
                # По валютам
                currency = reservation.currency
                if currency not in reservations_by_currency:
                    reservations_by_currency[currency] = {
                        'count': 0,
                        'total_amount': Decimal('0')
                    }

                reservations_by_currency[currency]['count'] += 1
                reservations_by_currency[currency]['total_amount'] += reservation.amount

                # По причинам
                reason = reservation.reason.value
                reservations_by_reason[reason] = reservations_by_reason.get(reason, 0) + 1

            return {
                'total_reservations': total_reservations,
                'by_currency': {
                    currency: {
                        'count': data['count'],
                        'total_amount': str(data['total_amount'])
                    }
                    for currency, data in reservations_by_currency.items()
                },
                'by_reason': reservations_by_reason,
                'oldest_reservation': (
                    min(self.reservations.values(), key=lambda r: r.created_at).created_at.isoformat()
                    if self.reservations else None
                )
            }

        except Exception as e:
            self.logger.error(f"❌ Ошибка получения сводки резервирований: {e}")
            return {}

    def get_balance_history(self, currency: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """📜 История изменений баланса"""

        try:
            history = self.balance_history

            # Фильтруем по валюте если указана
            if currency:
                history = [
                    record for record in history
                    if record['currency'] == currency.upper()
                ]

            # Ограничиваем количество записей
            return history[-limit:]

        except Exception as e:
            self.logger.error(f"❌ Ошибка получения истории баланса: {e}")
            return []

    def get_service_statistics(self) -> Dict[str, Any]:
        """📊 Статистика сервиса"""

        return {
            'cache_entries': len(self.balance_cache),
            'active_reservations': len(self.reservations),
            'history_records': len(self.balance_history),
            'supported_currencies': len(self.exchange_rates),
            'cache_ttl_seconds': self.cache_ttl.total_seconds(),
            'has_exchange_api': self.exchange_api is not None,
            'oldest_cache_entry': (
                min(cached_time for cached_time, _ in self.balance_cache.values()).isoformat()
                if self.balance_cache else None
            )
        }

    def set_exchange_rate(self, currency: str, rate_to_eur: Decimal) -> None:
        """💱 Установка курса валюты к EUR"""

        try:
            currency = currency.upper()
            self.exchange_rates[currency] = rate_to_eur

            self.logger.info(f"💱 Курс {currency} обновлен: {rate_to_eur} EUR")

        except Exception as e:
            self.logger.error(f"❌ Ошибка установки курса {currency}: {e}")

    async def validate_balances_integrity(self) -> Dict[str, Any]:
        """✅ Валидация целостности балансов"""

        try:
            issues = []

            # Проверяем резервирования
            for res_id, reservation in self.reservations.items():
                balance = await self.get_balance(reservation.currency)

                if reservation.amount > balance.total:
                    issues.append(f"Reservation {res_id} exceeds total balance")

                if reservation.is_expired:
                    issues.append(f"Expired reservation {res_id} not cleaned up")

            # Проверяем кэш
            expired_cache = []
            for currency, (cached_time, _) in self.balance_cache.items():
                if datetime.now() - cached_time > self.cache_ttl:
                    expired_cache.append(currency)

            return {
                'is_valid': len(issues) == 0,
                'issues': issues,
                'expired_cache_entries': expired_cache,
                'total_reservations': len(self.reservations),
                'cache_entries': len(self.balance_cache)
            }

        except Exception as e:
            self.logger.error(f"❌ Ошибка валидации целостности: {e}")
            return {'is_valid': False, 'error': str(e)}
