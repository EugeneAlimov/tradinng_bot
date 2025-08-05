from typing import Optional, List, Dict, Any, Tuple
from decimal import Decimal
from datetime import datetime, timedelta
import logging
from dataclasses import dataclass, field
from enum import Enum

# Импорты из Core слоя
try:
    from ...core.interfaces import IPositionManager, IPersistenceService, IExchangeAPI
    from ...core.models import (
        Position, TradingPair, Money, Price, OrderResult,
        TradeResult, PositionStatus
    )
    from ...core.exceptions import (
        TradingError, ValidationError, DataError,
        InsufficientBalanceError, PositionError
    )
    from ...core.events import DomainEvent, publish_event
except ImportError:
    # Fallback для разработки
    class IPositionManager: pass
    class IPersistenceService: pass
    class IExchangeAPI: pass
    
    class Position: pass
    class TradingPair: pass
    class Money: pass
    class Price: pass
    class OrderResult: pass
    class TradeResult: pass
    class PositionStatus: pass
    
    class TradingError(Exception): pass
    class ValidationError(Exception): pass
    class DataError(Exception): pass
    class InsufficientBalanceError(Exception): pass
    class PositionError(Exception): pass
    
    class DomainEvent: pass
    def publish_event(event): pass


class PositionUpdateType(Enum):
    """🔄 Типы обновления позиции"""
    TRADE_EXECUTED = "trade_executed"
    BALANCE_SYNC = "balance_sync"
    MANUAL_ADJUSTMENT = "manual_adjustment"
    PROFIT_REALIZATION = "profit_realization"
    STOP_LOSS = "stop_loss"


@dataclass
class PositionMetrics:
    """📈 Метрики позиции"""
    total_invested: Decimal = Decimal('0')
    total_realized_pnl: Decimal = Decimal('0')
    unrealized_pnl: Decimal = Decimal('0')
    average_buy_price: Decimal = Decimal('0')
    current_value: Decimal = Decimal('0')
    roi_percentage: Decimal = Decimal('0')
    holding_time: timedelta = field(default_factory=lambda: timedelta())
    trade_count: int = 0
    win_rate: Decimal = Decimal('0')
    
    @property
    def total_pnl(self) -> Decimal:
        """Общий P&L"""
        return self.total_realized_pnl + self.unrealized_pnl
    
    @property
    def is_profitable(self) -> bool:
        """Прибыльна ли позиция"""
        return self.total_pnl > 0


@dataclass 
class PositionSnapshot:
    """📸 Снимок состояния позиции"""
    timestamp: datetime
    position: Position
    metrics: PositionMetrics
    market_price: Price
    balance_info: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        """Конвертация в словарь"""
        return {
            'timestamp': self.timestamp.isoformat(),
            'position': {
                'pair': str(self.position.pair) if self.position else None,
                'quantity': str(self.position.quantity) if self.position else '0',
                'avg_price': str(self.position.average_price) if self.position else '0',
                'status': self.position.status.value if self.position else 'empty'
            },
            'metrics': {
                'total_pnl': str(self.metrics.total_pnl),
                'roi_percentage': str(self.metrics.roi_percentage),
                'current_value': str(self.metrics.current_value)
            },
            'market_price': str(self.market_price.value) if self.market_price else '0'
        }


class PositionService:
    """📊 Сервис управления торговыми позициями"""
    
    def __init__(
        self,
        position_manager: IPositionManager,
        persistence_service: IPersistenceService,
        exchange_api: IExchangeAPI,
        trading_pair: TradingPair
    ):
        self.position_manager = position_manager
        self.persistence = persistence_service
        self.exchange_api = exchange_api
        self.trading_pair = trading_pair
        
        # Текущее состояние
        self.current_position: Optional[Position] = None
        self.position_history: List[PositionSnapshot] = []
        self.last_sync_time: Optional[datetime] = None
        
        # Метрики
        self.metrics = PositionMetrics()
        
        # Конфигурация
        self.auto_sync_enabled = True
        self.sync_interval = timedelta(minutes=5)
        self.max_history_items = 1000
        
        # Логирование
        self.logger = logging.getLogger(__name__)
        
    async def initialize(self) -> None:
        """🚀 Инициализация сервиса позиций"""
        try:
            self.logger.info("🚀 Инициализация PositionService...")
            
            # Загружаем последнюю позицию
            await self._load_current_position()
            
            # Загружаем историю
            await self._load_position_history()
            
            # Синхронизируем с биржей
            await self.sync_with_exchange()
            
            # Пересчитываем метрики
            await self._recalculate_metrics()
            
            self.logger.info("✅ PositionService инициализирован")
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка инициализации PositionService: {e}")
            raise
    
    async def get_current_position(self) -> Optional[Position]:
        """📊 Получение текущей позиции"""
        if self.auto_sync_enabled and self._should_sync():
            await self.sync_with_exchange()
        
        return self.current_position
    
    async def update_position_from_trade(
        self,
        trade_result: OrderResult,
        update_type: PositionUpdateType = PositionUpdateType.TRADE_EXECUTED
    ) -> Position:
        """🔄 Обновление позиции на основе результата торговли"""
        
        try:
            self.logger.info(f"🔄 Обновление позиции от торговли: {trade_result}")
            
            # Валидируем торговый результат
            await self._validate_trade_result(trade_result)
            
            # Создаем снимок до изменения
            snapshot_before = await self._create_position_snapshot("before_trade")
            
            # Обновляем позицию через Domain сервис
            updated_position = await self.position_manager.update_from_trade(trade_result)
            
            # Обновляем текущую позицию
            self.current_position = updated_position
            
            # Пересчитываем метрики
            await self._recalculate_metrics()
            
            # Создаем снимок после изменения
            snapshot_after = await self._create_position_snapshot("after_trade")
            
            # Сохраняем изменения
            await self._save_position_update(updated_position, update_type)
            
            # Публикуем событие обновления
            await self._publish_position_update_event(
                snapshot_before, snapshot_after, update_type
            )
            
            self.logger.info(f"✅ Позиция обновлена: {updated_position}")
            return updated_position
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка обновления позиции: {e}")
            raise PositionError(f"Не удалось обновить позицию: {e}")
    
    async def sync_with_exchange(self) -> bool:
        """🔄 Синхронизация позиции с биржей"""
        try:
            self.logger.debug("🔄 Синхронизация с биржей...")
            
            # Получаем актуальный баланс с биржи
            exchange_balance = await self.exchange_api.get_balance()
            
            # Получаем баланс по нашей торговой паре
            base_balance = exchange_balance.get(self.trading_pair.base, {})
            quote_balance = exchange_balance.get(self.trading_pair.quote, {})
            
            base_amount = Decimal(str(base_balance.get('available', 0)))
            quote_amount = Decimal(str(quote_balance.get('available', 0)))
            
            # Сравниваем с нашими данными
            sync_needed = await self._check_sync_needed(base_amount, quote_amount)
            
            if sync_needed:
                # Выполняем синхронизацию
                await self._perform_sync(base_amount, quote_amount)
                self.logger.info("✅ Синхронизация завершена")
                
            self.last_sync_time = datetime.now()
            return sync_needed
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка синхронизации: {e}")
            return False
    
    async def calculate_position_metrics(
        self, 
        current_price: Price
    ) -> PositionMetrics:
        """📈 Расчет метрик позиции"""
        try:
            if not self.current_position or self.current_position.is_empty:
                return PositionMetrics()
            
            position = self.current_position
            
            # Базовые расчеты
            current_value = position.quantity * current_price.value
            total_invested = position.quantity * position.average_price
            unrealized_pnl = current_value - total_invested
            
            # ROI процент  
            roi_percentage = (unrealized_pnl / total_invested * 100) if total_invested > 0 else Decimal('0')
            
            # Время держания позиции
            holding_time = datetime.now() - position.opened_at if position.opened_at else timedelta()
            
            # Обновляем метрики
            self.metrics.total_invested = total_invested
            self.metrics.unrealized_pnl = unrealized_pnl
            self.metrics.current_value = current_value
            self.metrics.roi_percentage = roi_percentage
            self.metrics.holding_time = holding_time
            self.metrics.average_buy_price = position.average_price
            
            return self.metrics
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка расчета метрик: {e}")
            return self.metrics
    
    async def get_position_history(
        self, 
        days_back: int = 7
    ) -> List[PositionSnapshot]:
        """📜 Получение истории позиций"""
        try:
            cutoff_date = datetime.now() - timedelta(days=days_back)
            
            # Фильтруем историю по дате
            filtered_history = [
                snapshot for snapshot in self.position_history
                if snapshot.timestamp >= cutoff_date
            ]
            
            return sorted(filtered_history, key=lambda x: x.timestamp, reverse=True)
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка получения истории: {e}")
            return []
    
    async def get_position_performance(self) -> Dict[str, Any]:
        """📊 Получение показателей производительности позиции"""
        try:
            if not self.current_position:
                return {'status': 'no_position'}
            
            # Получаем текущую цену
            market_data = await self.exchange_api.get_ticker(str(self.trading_pair))
            current_price = Price(Decimal(str(market_data.get('last', 0))), self.trading_pair.quote)
            
            # Рассчитываем метрики
            metrics = await self.calculate_position_metrics(current_price)
            
            # Анализ истории
            history_analysis = await self._analyze_position_history()
            
            return {
                'position': {
                    'pair': str(self.trading_pair),
                    'quantity': str(self.current_position.quantity),
                    'average_price': str(self.current_position.average_price),
                    'status': self.current_position.status.value,
                    'opened_at': self.current_position.opened_at.isoformat() if self.current_position.opened_at else None
                },
                'metrics': {
                    'current_value': str(metrics.current_value),
                    'total_invested': str(metrics.total_invested),
                    'unrealized_pnl': str(metrics.unrealized_pnl),
                    'realized_pnl': str(metrics.total_realized_pnl),
                    'total_pnl': str(metrics.total_pnl),
                    'roi_percentage': str(metrics.roi_percentage),
                    'holding_time_hours': str(metrics.holding_time.total_seconds() / 3600)
                },
                'market': {
                    'current_price': str(current_price.value),
                    'price_change_from_avg': str(current_price.value - self.current_position.average_price)
                },
                'analysis': history_analysis
            }
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка анализа производительности: {e}")
            return {'error': str(e)}
    
    async def close_position(
        self, 
        close_price: Price,
        reason: str = "manual_close"
    ) -> OrderResult:
        """🔒 Закрытие позиции"""
        try:
            if not self.current_position or self.current_position.is_empty:
                raise PositionError("Нет открытой позиции для закрытия")
            
            self.logger.info(f"🔒 Закрытие позиции: {self.current_position.quantity} по {close_price}")
            
            # Создаем ордер на продажу всей позиции
            sell_order = await self.exchange_api.create_order(
                pair=str(self.trading_pair),
                order_type='sell',
                quantity=self.current_position.quantity,
                price=close_price.value
            )
            
            if sell_order.success:
                # Обновляем позицию
                await self.update_position_from_trade(sell_order, PositionUpdateType.PROFIT_REALIZATION)
                
                # Рассчитываем финальный P&L
                final_pnl = (close_price.value - self.current_position.average_price) * self.current_position.quantity
                
                self.logger.info(f"✅ Позиция закрыта с P&L: {final_pnl}")
                
                return sell_order
            else:
                raise TradingError(f"Не удалось закрыть позицию: {sell_order.error_message}")
                
        except Exception as e:
            self.logger.error(f"❌ Ошибка закрытия позиции: {e}")
            raise
    
    async def adjust_position(
        self,
        adjustment: Decimal,
        adjustment_type: str,
        reason: str
    ) -> None:
        """🔧 Ручная корректировка позиции"""
        try:
            if not self.current_position:
                raise PositionError("Нет позиции для корректировки")
            
            self.logger.info(f"🔧 Корректировка позиции: {adjustment_type} {adjustment}")
            
            # Создаем корректировку через position manager
            await self.position_manager.adjust_position(
                self.current_position,
                adjustment,
                adjustment_type,
                reason
            )
            
            # Пересчитываем метрики
            await self._recalculate_metrics()
            
            # Сохраняем изменения
            await self._save_position_update(
                self.current_position,
                PositionUpdateType.MANUAL_ADJUSTMENT
            )
            
            self.logger.info("✅ Позиция скорректирована")
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка корректировки позиции: {e}")
            raise
    
    async def export_position_data(
        self,
        format_type: str = "json",
        include_history: bool = True
    ) -> Dict[str, Any]:
        """📤 Экспорт данных позиции"""
        try:
            # Базовые данные позиции
            export_data = {
                'current_position': {
                    'pair': str(self.trading_pair),
                    'quantity': str(self.current_position.quantity) if self.current_position else '0',
                    'average_price': str(self.current_position.average_price) if self.current_position else '0',
                    'status': self.current_position.status.value if self.current_position else 'empty',
                    'opened_at': self.current_position.opened_at.isoformat() if self.current_position and self.current_position.opened_at else None
                },
                'metrics': {
                    'total_invested': str(self.metrics.total_invested),
                    'realized_pnl': str(self.metrics.total_realized_pnl),
                    'unrealized_pnl': str(self.metrics.unrealized_pnl),
                    'roi_percentage': str(self.metrics.roi_percentage),
                    'trade_count': self.metrics.trade_count
                },
                'export_timestamp': datetime.now().isoformat()
            }
            
            # Добавляем историю если требуется
            if include_history:
                export_data['history'] = [
                    snapshot.to_dict() for snapshot in self.position_history[-100:]  # Последние 100
                ]
            
            return export_data
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка экспорта данных: {e}")
            return {'error': str(e)}
    
    # ================= ПРИВАТНЫЕ МЕТОДЫ =================
    
    async def _load_current_position(self) -> None:
        """📥 Загрузка текущей позиции"""
        try:
            position_data = await self.persistence.load_data(f"position_{self.trading_pair}")
            if position_data:
                self.current_position = self._deserialize_position(position_data)
                self.logger.debug("📥 Текущая позиция загружена")
        except Exception as e:
            self.logger.warning(f"⚠️ Не удалось загрузить позицию: {e}")
            self.current_position = None
    
    async def _load_position_history(self) -> None:
        """📥 Загрузка истории позиций"""
        try:
            history_data = await self.persistence.load_data(f"position_history_{self.trading_pair}")
            if history_data and isinstance(history_data, list):
                self.position_history = [
                    self._deserialize_snapshot(item) for item in history_data[-self.max_history_items:]
                ]
                self.logger.debug(f"📥 Загружено {len(self.position_history)} записей истории")
        except Exception as e:
            self.logger.warning(f"⚠️ Не удалось загрузить историю: {e}")
            self.position_history = []
    
    async def _save_position_update(
        self,
        position: Position,
        update_type: PositionUpdateType
    ) -> None:
        """💾 Сохранение обновления позиции"""
        try:
            # Сохраняем текущую позицию
            position_data = self._serialize_position(position)
            await self.persistence.save_data(f"position_{self.trading_pair}", position_data)
            
            # Добавляем в историю
            snapshot = await self._create_position_snapshot(f"update_{update_type.value}")
            self.position_history.append(snapshot)
            
            # Ограничиваем размер истории
            if len(self.position_history) > self.max_history_items:
                self.position_history = self.position_history[-self.max_history_items:]
            
            # Сохраняем историю
            history_data = [self._serialize_snapshot(s) for s in self.position_history]
            await self.persistence.save_data(f"position_history_{self.trading_pair}", history_data)
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка сохранения позиции: {e}")
    
    async def _recalculate_metrics(self) -> None:
        """🔄 Пересчет метрик позиции"""
        try:
            if not self.current_position:
                self.metrics = PositionMetrics()
                return
            
            # Получаем текущую цену для расчетов
            market_data = await self.exchange_api.get_ticker(str(self.trading_pair))
            current_price = Price(Decimal(str(market_data.get('last', 0))), self.trading_pair.quote)
            
            # Пересчитываем метрики
            self.metrics = await self.calculate_position_metrics(current_price)
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка пересчета метрик: {e}")
    
    async def _create_position_snapshot(self, reason: str) -> PositionSnapshot:
        """📸 Создание снимка позиции"""
        try:
            # Получаем текущую цену
            market_data = await self.exchange_api.get_ticker(str(self.trading_pair))
            current_price = Price(Decimal(str(market_data.get('last', 0))), self.trading_pair.quote)
            
            # Получаем баланс
            balance_info = await self.exchange_api.get_balance()
            
            return PositionSnapshot(
                timestamp=datetime.now(),
                position=self.current_position,
                metrics=self.metrics,
                market_price=current_price,
                balance_info=balance_info
            )
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка создания снимка: {e}")
            # Возвращаем минимальный снимок
            return PositionSnapshot(
                timestamp=datetime.now(),
                position=self.current_position,
                metrics=self.metrics,
                market_price=Price(Decimal('0'), self.trading_pair.quote),
                balance_info={}
            )
    
    def _should_sync(self) -> bool:
        """🔍 Проверка необходимости синхронизации"""
        if not self.last_sync_time:
            return True
        
        return (datetime.now() - self.last_sync_time) > self.sync_interval
    
    async def _check_sync_needed(
        self,
        exchange_base_amount: Decimal,
        exchange_quote_amount: Decimal
    ) -> bool:
        """🔍 Проверка необходимости синхронизации баланса"""
        if not self.current_position:
            return exchange_base_amount > 0
        
        # Допустимая разница в 1%
        tolerance = Decimal('0.01')
        position_amount = self.current_position.quantity
        
        if position_amount == 0:
            return exchange_base_amount > 0
        
        difference = abs(exchange_base_amount - position_amount) / position_amount
        return difference > tolerance
    
    async def _perform_sync(
        self,
        exchange_base_amount: Decimal,
        exchange_quote_amount: Decimal
    ) -> None:
        """🔄 Выполнение синхронизации"""
        try:
            self.logger.info(f"🔄 Синхронизация: биржа={exchange_base_amount}, позиция={self.current_position.quantity if self.current_position else 0}")
            
            # Здесь можно добавить логику корректировки позиции
            # на основе реального баланса биржи
            
            if self.current_position and exchange_base_amount != self.current_position.quantity:
                await self.adjust_position(
                    exchange_base_amount - self.current_position.quantity,
                    "balance_sync",
                    f"Синхронизация с биржей: {exchange_base_amount}"
                )
                
        except Exception as e:
            self.logger.error(f"❌ Ошибка выполнения синхронизации: {e}")
    
    async def _validate_trade_result(self, trade_result: OrderResult) -> None:
        """✅ Валидация результата торговли"""
        if not trade_result:
            raise ValidationError("Пустой результат торговли")
        
        if not hasattr(trade_result, 'success') or not trade_result.success:
            raise ValidationError("Торговая операция не была успешной")
        
        if not hasattr(trade_result, 'quantity') or trade_result.quantity <= 0:
            raise ValidationError("Некорректное количество в торговом результате")
    
    async def _analyze_position_history(self) -> Dict[str, Any]:
        """📊 Анализ истории позиции"""
        try:
            if len(self.position_history) < 2:
                return {'insufficient_data': True}
            
            # Базовая статистика
            snapshots = self.position_history[-30:]  # Последние 30 записей
            
            pnl_values = [float(s.metrics.total_pnl) for s in snapshots if s.metrics]
            max_pnl = max(pnl_values) if pnl_values else 0
            min_pnl = min(pnl_values) if pnl_values else 0
            
            return {
                'snapshots_analyzed': len(snapshots),
                'max_pnl': max_pnl,
                'min_pnl': min_pnl,
                'pnl_volatility': max_pnl - min_pnl,
                'current_vs_max': (float(self.metrics.total_pnl) / max_pnl * 100) if max_pnl != 0 else 0
            }
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка анализа истории: {e}")
            return {'error': str(e)}
    
    async def _publish_position_update_event(
        self,
        before: PositionSnapshot,
        after: PositionSnapshot,
        update_type: PositionUpdateType
    ) -> None:
        """📡 Публикация события обновления позиции"""
        try:
            event = DomainEvent()
            event.event_type = "position_updated"
            event.source = "position_service"
            event.metadata = {
                'trading_pair': str(self.trading_pair),
                'update_type': update_type.value,
                'before': before.to_dict(),
                'after': after.to_dict()
            }
            
            await publish_event(event)
            
        except Exception as e:
            self.logger.warning(f"⚠️ Ошибка публикации события: {e}")
    
    def _serialize_position(self, position: Position) -> Dict[str, Any]:
        """📤 Сериализация позиции"""
        if not position:
            return {}
        
        return {
            'pair': str(position.pair),
            'quantity': str(position.quantity),
            'average_price': str(position.average_price),
            'status': position.status.value,
            'opened_at': position.opened_at.isoformat() if position.opened_at else None,
            'total_cost': str(getattr(position, 'total_cost', 0))
        }
    
    def _deserialize_position(self, data: Dict[str, Any]) -> Position:
        """📥 Десериализация позиции"""
        # Здесь должна быть логика создания Position из словаря
        # Возвращаем заглушку для примера
        return None
    
    def _serialize_snapshot(self, snapshot: PositionSnapshot) -> Dict[str, Any]:
        """📤 Сериализация снимка"""
        return snapshot.to_dict()
    
    def _deserialize_snapshot(self, data: Dict[str, Any]) -> PositionSnapshot:
        """📥 Десериализация снимка"""
        # Здесь должна быть логика создания PositionSnapshot из словаря
        # Возвращаем заглушку для примера
        return None
