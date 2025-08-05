from typing import Optional, List, Dict, Any, Tuple
from decimal import Decimal
from datetime import datetime, timedelta
import logging
from dataclasses import dataclass, field
from enum import Enum
import json

# Импорты из Core слоя
try:
    from ...core.interfaces import IPositionManager, IPersistenceService, IMarketDataProvider
    from ...core.models import (
        Position, TradeResult, TradingPair, Money, Price,
        OrderResult, MarketData
    )
    from ...core.exceptions import (
        DataError, ValidationError, TradingSystemError
    )
    from ...core.events import DomainEvent, publish_event
except ImportError:
    # Fallback для разработки
    class IPositionManager: pass
    class IPersistenceService: pass
    class IMarketDataProvider: pass
    
    class Position: pass
    class TradeResult: pass
    class TradingPair: pass
    class Money: pass
    class Price: pass
    class OrderResult: pass
    class MarketData: pass
    
    class DataError(Exception): pass
    class ValidationError(Exception): pass
    class TradingSystemError(Exception): pass
    
    class DomainEvent: pass
    def publish_event(event): pass


class ReportType(Enum):
    """📋 Типы отчетов"""
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    PERFORMANCE = "performance"
    RISK = "risk"
    TRADING_SESSION = "trading_session"
    POSITION_ANALYSIS = "position_analysis"


class MetricType(Enum):
    """📈 Типы метрик"""
    PNL = "pnl"                    # Прибыль/убыток
    ROI = "roi"                    # Рентабельность
    WIN_RATE = "win_rate"          # Процент прибыльных сделок
    DRAWDOWN = "drawdown"          # Просадка
    VOLATILITY = "volatility"      # Волатильность
    SHARPE_RATIO = "sharpe_ratio"  # Коэффициент Шарпа
    TRADES_COUNT = "trades_count"  # Количество сделок


@dataclass
class TradingMetrics:
    """📊 Торговые метрики"""
    # Базовые метрики
    total_pnl: Decimal = Decimal('0')
    realized_pnl: Decimal = Decimal('0')
    unrealized_pnl: Decimal = Decimal('0')
    
    # Торговая активность
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    
    # Финансовые показатели
    total_volume: Decimal = Decimal('0')
    average_trade_size: Decimal = Decimal('0')
    largest_win: Decimal = Decimal('0')
    largest_loss: Decimal = Decimal('0')
    
    # Временные показатели
    total_trading_time: timedelta = field(default_factory=lambda: timedelta())
    average_holding_time: timedelta = field(default_factory=lambda: timedelta())
    
    @property
    def win_rate(self) -> float:
        """Процент прибыльных сделок"""
        if self.total_trades == 0:
            return 0.0
        return (self.winning_trades / self.total_trades) * 100
    
    @property
    def average_win(self) -> Decimal:
        """Средняя прибыль по прибыльным сделкам"""
        if self.winning_trades == 0:
            return Decimal('0')
        return self.realized_pnl / self.winning_trades if self.realized_pnl > 0 else Decimal('0')
    
    @property
    def average_loss(self) -> Decimal:
        """Средний убыток по убыточным сделкам"""
        if self.losing_trades == 0:
            return Decimal('0')
        total_losses = sum(trade.pnl for trade in [] if hasattr(trade, 'pnl') and trade.pnl < 0)
        return abs(total_losses / self.losing_trades) if self.losing_trades > 0 else Decimal('0')
    
    @property
    def profit_factor(self) -> float:
        """Фактор прибыльности (отношение прибылей к убыткам)"""
        if self.average_loss == 0:
            return float('inf') if self.average_win > 0 else 0.0
        return float(self.average_win / self.average_loss)


@dataclass
class PerformanceReport:
    """📈 Отчет о производительности"""
    report_type: ReportType
    period_start: datetime
    period_end: datetime
    trading_pair: TradingPair
    
    # Основные метрики
    metrics: TradingMetrics
    
    # Дополнительная аналитика
    daily_pnl: List[Tuple[datetime, Decimal]] = field(default_factory=list)
    hourly_activity: Dict[int, int] = field(default_factory=dict)  # час -> количество сделок
    
    # Анализ рисков
    max_drawdown: Decimal = Decimal('0')
    volatility: float = 0.0
    var_95: Decimal = Decimal('0')  # Value at Risk 95%
    
    # Рекомендации
    recommendations: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Конвертация в словарь"""
        return {
            'report_type': self.report_type.value,
            'period': {
                'start': self.period_start.isoformat(),
                'end': self.period_end.isoformat(),
                'duration_days': (self.period_end - self.period_start).days
            },
            'trading_pair': str(self.trading_pair),
            'metrics': {
                'total_pnl': str(self.metrics.total_pnl),
                'realized_pnl': str(self.metrics.realized_pnl),
                'unrealized_pnl': str(self.metrics.unrealized_pnl),
                'total_trades': self.metrics.total_trades,
                'win_rate': round(self.metrics.win_rate, 2),
                'total_volume': str(self.metrics.total_volume),
                'average_trade_size': str(self.metrics.average_trade_size),
                'profit_factor': round(self.metrics.profit_factor, 2)
            },
            'risk_analysis': {
                'max_drawdown': str(self.max_drawdown),
                'volatility': round(self.volatility, 4),
                'var_95': str(self.var_95)
            },
            'activity_analysis': {
                'daily_pnl_count': len(self.daily_pnl),
                'most_active_hour': max(self.hourly_activity.items(), key=lambda x: x[1])[0] if self.hourly_activity else None,
                'trading_days': len([pnl for date, pnl in self.daily_pnl if pnl != 0])
            },
            'recommendations': self.recommendations,
            'warnings': self.warnings,
            'generated_at': datetime.now().isoformat()
        }


class AnalyticsService:
    """📊 Сервис аналитики и отчетности"""
    
    def __init__(
        self,
        position_manager: IPositionManager,
        persistence_service: IPersistenceService,
        market_data_provider: IMarketDataProvider,
        trading_pair: TradingPair
    ):
        self.position_manager = position_manager
        self.persistence = persistence_service
        self.market_data_provider = market_data_provider
        self.trading_pair = trading_pair
        
        # Кэш для аналитических данных
        self._metrics_cache: Dict[str, Tuple[Any, datetime]] = {}
        self.cache_ttl = timedelta(minutes=15)
        
        # История метрик
        self.metrics_history: List[Tuple[datetime, TradingMetrics]] = []
        self.max_history_size = 10000
        
        # Конфигурация
        self.auto_reports_enabled = True
        self.report_generation_time = 22  # 22:00 для дневных отчетов
        
        # Логирование
        self.logger = logging.getLogger(__name__)
        
    async def initialize(self) -> None:
        """🚀 Инициализация сервиса аналитики"""
        try:
            self.logger.info("🚀 Инициализация AnalyticsService...")
            
            # Загружаем историю метрик
            await self._load_metrics_history()
            
            # Загружаем историю сделок
            await self._load_trades_history()
            
            # Устанавливаем базовые метрики
            await self._initialize_baseline_metrics()
            
            self.logger.info("✅ AnalyticsService инициализирован")
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка инициализации AnalyticsService: {e}")
            raise
    
    async def calculate_current_metrics(self) -> TradingMetrics:
        """📊 Расчет текущих торговых метрик"""
        try:
            # Проверяем кэш
            cached_metrics = self._get_cached_metrics("current_metrics")
            if cached_metrics:
                return cached_metrics
            
            self.logger.debug("📊 Расчет текущих метрик...")
            
            # Получаем данные для расчета
            current_position = await self.position_manager.get_current_position(self.trading_pair)
            trades_history = await self._get_trades_history()
            
            # Рассчитываем метрики
            metrics = await self._calculate_metrics_from_data(current_position, trades_history)
            
            # Кэшируем результат
            self._cache_metrics("current_metrics", metrics)
            
            # Добавляем в историю
            self.metrics_history.append((datetime.now(), metrics))
            if len(self.metrics_history) > self.max_history_size:
                self.metrics_history = self.metrics_history[-self.max_history_size:]
            
            return metrics
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка расчета метрик: {e}")
            return TradingMetrics()  # Возвращаем пустые метрики
    
    async def generate_report(
        self,
        report_type: ReportType,
        period_days: Optional[int] = None,
        custom_start: Optional[datetime] = None,
        custom_end: Optional[datetime] = None
    ) -> PerformanceReport:
        """📋 Генерация отчета о производительности"""
        try:
            self.logger.info(f"📋 Генерация отчета: {report_type.value}")
            
            # Определяем период анализа
            period_start, period_end = self._determine_report_period(
                report_type, period_days, custom_start, custom_end
            )
            
            # Получаем данные за период
            period_data = await self._get_period_data(period_start, period_end)
            
            # Рассчитываем метрики для периода
            period_metrics = await self._calculate_period_metrics(period_data)
            
            # Выполняем дополнительную аналитику
            risk_analysis = await self._analyze_risk_metrics(period_data)
            activity_analysis = self._analyze_trading_activity(period_data)
            
            # Генерируем рекомендации
            recommendations, warnings = self._generate_insights(period_metrics, risk_analysis)
            
            # Создаем отчет
            report = PerformanceReport(
                report_type=report_type,
                period_start=period_start,
                period_end=period_end,
                trading_pair=self.trading_pair,
                metrics=period_metrics,
                daily_pnl=activity_analysis.get('daily_pnl', []),
                hourly_activity=activity_analysis.get('hourly_activity', {}),
                max_drawdown=risk_analysis.get('max_drawdown', Decimal('0')),
                volatility=risk_analysis.get('volatility', 0.0),
                var_95=risk_analysis.get('var_95', Decimal('0')),
                recommendations=recommendations,
                warnings=warnings
            )
            
            # Сохраняем отчет
            await self._save_report(report)
            
            # Публикуем событие
            await self._publish_report_event(report)
            
            self.logger.info(f"✅ Отчет {report_type.value} сгенерирован")
            return report
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка генерации отчета: {e}")
            raise DataError(f"Не удалось сгенерировать отчет: {e}")
    
    async def get_performance_summary(self, days_back: int = 30) -> Dict[str, Any]:
        """📈 Получение сводки производительности"""
        try:
            # Получаем текущие метрики
            current_metrics = await self.calculate_current_metrics()
            
            # Получаем исторические данные
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days_back)
            
            historical_data = await self._get_period_data(start_date, end_date)
            
            # Анализируем тренды
            trends = self._analyze_performance_trends(historical_data)
            
            # Сравниваем с предыдущим периодом
            comparison = await self._compare_with_previous_period(days_back)
            
            return {
                'current_metrics': {
                    'total_pnl': str(current_metrics.total_pnl),
                    'win_rate': round(current_metrics.win_rate, 2),
                    'total_trades': current_metrics.total_trades,
                    'profit_factor': round(current_metrics.profit_factor, 2)
                },
                'period_analysis': {
                    'days_analyzed': days_back,
                    'start_date': start_date.isoformat(),
                    'end_date': end_date.isoformat(),
                    'total_trading_days': len([d for d in historical_data if d.get('trades_count', 0) > 0])
                },
                'trends': trends,
                'comparison': comparison,
                'generated_at': datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка получения сводки: {e}")
            return {'error': str(e)}
    
    async def track_trade_performance(self, trade_result: OrderResult) -> None:
        """📊 Отслеживание производительности сделки"""
        try:
            if not trade_result or not getattr(trade_result, 'success', False):
                return
            
            self.logger.debug(f"📊 Отслеживание сделки: {trade_result}")
            
            # Анализируем сделку
            trade_analysis = await self._analyze_single_trade(trade_result)
            
            # Обновляем статистику
            await self._update_trade_statistics(trade_analysis)
            
            # Проверяем на аномалии
            anomalies = self._detect_trade_anomalies(trade_analysis)
            if anomalies:
                await self._handle_trade_anomalies(anomalies, trade_result)
            
            # Публикуем событие анализа сделки
            await self._publish_trade_analysis_event(trade_analysis)
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка отслеживания сделки: {e}")
    
    async def get_risk_metrics(self) -> Dict[str, Any]:
        """🛡️ Получение метрик риска"""
        try:
            # Получаем исторические данные для анализа риска
            end_date = datetime.now()
            start_date = end_date - timedelta(days=90)  # 3 месяца для анализа риска
            
            historical_data = await self._get_period_data(start_date, end_date)
            
            # Рассчитываем риск-метрики
            risk_metrics = await self._calculate_risk_metrics(historical_data)
            
            return {
                'analysis_period': {
                    'start': start_date.isoformat(),
                    'end': end_date.isoformat(),
                    'days': 90
                },
                'drawdown': {
                    'current': str(risk_metrics.get('current_drawdown', 0)),
                    'maximum': str(risk_metrics.get('max_drawdown', 0)),
                    'average': str(risk_metrics.get('avg_drawdown', 0))
                },
                'volatility': {
                    'daily': round(risk_metrics.get('daily_volatility', 0), 4),
                    'weekly': round(risk_metrics.get('weekly_volatility', 0), 4),
                    'monthly': round(risk_metrics.get('monthly_volatility', 0), 4)
                },
                'value_at_risk': {
                    'var_95': str(risk_metrics.get('var_95', 0)),
                    'var_99': str(risk_metrics.get('var_99', 0)),
                    'expected_shortfall': str(risk_metrics.get('expected_shortfall', 0))
                },
                'risk_ratios': {
                    'sharpe_ratio': round(risk_metrics.get('sharpe_ratio', 0), 3),
                    'sortino_ratio': round(risk_metrics.get('sortino_ratio', 0), 3),
                    'calmar_ratio': round(risk_metrics.get('calmar_ratio', 0), 3)
                },
                'generated_at': datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка расчета риск-метрик: {e}")
            return {'error': str(e)}
    
    async def export_analytics_data(
        self,
        format_type: str = "json",
        period_days: int = 30,
        include_trades: bool = True,
        include_positions: bool = True
    ) -> Dict[str, Any]:
        """📤 Экспорт аналитических данных"""
        try:
            self.logger.info(f"📤 Экспорт данных в формате {format_type}")
            
            # Определяем период экспорта
            end_date = datetime.now()
            start_date = end_date - timedelta(days=period_days)
            
            export_data = {
                'export_info': {
                    'format': format_type,
                    'period_days': period_days,
                    'start_date': start_date.isoformat(),
                    'end_date': end_date.isoformat(),
                    'generated_at': datetime.now().isoformat()
                }
            }
            
            # Добавляем основные метрики
            current_metrics = await self.calculate_current_metrics()
            export_data['current_metrics'] = {
                'total_pnl': str(current_metrics.total_pnl),
                'realized_pnl': str(current_metrics.realized_pnl),
                'unrealized_pnl': str(current_metrics.unrealized_pnl),
                'total_trades': current_metrics.total_trades,
                'win_rate': current_metrics.win_rate,
                'profit_factor': current_metrics.profit_factor
            }
            
            # Добавляем исторические данные сделок
            if include_trades:
                trades_data = await self._export_trades_data(start_date, end_date)
                export_data['trades_history'] = trades_data
            
            # Добавляем данные позиций
            if include_positions:
                positions_data = await self._export_positions_data(start_date, end_date)
                export_data['positions_history'] = positions_data
            
            # Добавляем аналитические расчеты
            export_data['analytics'] = {
                'daily_pnl': await self._get_daily_pnl_series(start_date, end_date),
                'performance_metrics': await self._get_performance_metrics_series(start_date, end_date),
                'risk_metrics': await self.get_risk_metrics()
            }
            
            # Сохраняем экспорт
            await self._save_export_data(export_data, format_type)
            
            return export_data
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка экспорта данных: {e}")
            return {'error': str(e)}
    
    async def generate_automated_insights(self) -> List[str]:
        """🤖 Генерация автоматических инсайтов"""
        try:
            insights = []
            
            # Анализируем текущие метрики
            current_metrics = await self.calculate_current_metrics()
            
            # Инсайты по винрейту
            if current_metrics.win_rate > 70:
                insights.append(f"🎯 Отличный винрейт {current_metrics.win_rate:.1f}% - стратегия работает эффективно")
            elif current_metrics.win_rate < 40:
                insights.append(f"⚠️ Низкий винрейт {current_metrics.win_rate:.1f}% - рассмотрите корректировку стратегии")
            
            # Инсайты по profit factor
            if current_metrics.profit_factor > 2.0:
                insights.append(f"💰 Высокий profit factor {current_metrics.profit_factor:.2f} - прибыли значительно превышают потери")
            elif current_metrics.profit_factor < 1.0:
                insights.append(f"🚨 Profit factor {current_metrics.profit_factor:.2f} ниже 1.0 - стратегия убыточна")
            
            # Анализируем тренды
            trends = await self._analyze_recent_trends()
            
            if trends.get('pnl_trend') == 'improving':
                insights.append("📈 Прибыльность улучшается в последние дни")
            elif trends.get('pnl_trend') == 'declining':
                insights.append("📉 Прибыльность снижается - возможно нужна корректировка")
            
            # Анализируем торговую активность
            if current_metrics.total_trades > 0:
                avg_trade_frequency = current_metrics.total_trades / max(current_metrics.total_trading_time.days, 1)
                if avg_trade_frequency > 5:
                    insights.append("⚡ Высокая торговая активность - следите за комиссиями")
                elif avg_trade_frequency < 0.5:
                    insights.append("🐌 Низкая торговая активность - возможно упускаете возможности")
            
            # Анализируем размеры сделок
            if current_metrics.average_trade_size > Decimal('0'):
                insights.append(f"📊 Средний размер сделки: {current_metrics.average_trade_size:.2f}")
            
            return insights
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка генерации инсайтов: {e}")
            return [f"Ошибка анализа: {e}"]
    
    # ================= ПРИВАТНЫЕ МЕТОДЫ =================
    
    async def _load_metrics_history(self) -> None:
        """📥 Загрузка истории метрик"""
        try:
            history_data = await self.persistence.load_data(f"metrics_history_{self.trading_pair}")
            if history_data and isinstance(history_data, list):
                # Десериализация истории метрик
                self.metrics_history = []
                for item in history_data[-self.max_history_size:]:
                    if isinstance(item, dict) and 'timestamp' in item and 'metrics' in item:
                        timestamp = datetime.fromisoformat(item['timestamp'])
                        metrics = self._deserialize_metrics(item['metrics'])
                        self.metrics_history.append((timestamp, metrics))
                
                self.logger.debug(f"📥 Загружено {len(self.metrics_history)} записей метрик")
        except Exception as e:
            self.logger.warning(f"⚠️ Не удалось загрузить историю метрик: {e}")
            self.metrics_history = []
    
    async def _load_trades_history(self) -> None:
        """📥 Загрузка истории сделок"""
        try:
            # Загружаем историю сделок из persistence
            trades_data = await self.persistence.load_data(f"trades_history_{self.trading_pair}")
            if trades_data:
                self.logger.debug(f"📥 Загружена история сделок: {len(trades_data) if isinstance(trades_data, list) else 'unknown'}")
        except Exception as e:
            self.logger.warning(f"⚠️ Не удалось загрузить историю сделок: {e}")
    
    async def _initialize_baseline_metrics(self) -> None:
        """🎯 Инициализация базовых метрик"""
        try:
            if not self.metrics_history:
                # Создаем начальные метрики
                initial_metrics = TradingMetrics()
                self.metrics_history.append((datetime.now(), initial_metrics))
                self.logger.debug("🎯 Созданы начальные метрики")
        except Exception as e:
            self.logger.error(f"❌ Ошибка инициализации базовых метрик: {e}")
    
    async def _get_trades_history(self) -> List[Dict[str, Any]]:
        """📜 Получение истории сделок"""
        try:
            trades_data = await self.persistence.load_data(f"trades_history_{self.trading_pair}")
            return trades_data if isinstance(trades_data, list) else []
        except Exception as e:
            self.logger.error(f"❌ Ошибка получения истории сделок: {e}")
            return []
    
    async def _calculate_metrics_from_data(
        self,
        current_position: Optional[Position],
        trades_history: List[Dict[str, Any]]
    ) -> TradingMetrics:
        """📊 Расчет метрик на основе данных"""
        
        metrics = TradingMetrics()
        
        try:
            # Анализируем историю сделок
            if trades_history:
                total_pnl = Decimal('0')
                winning_trades = 0
                losing_trades = 0
                total_volume = Decimal('0')
                largest_win = Decimal('0')
                largest_loss = Decimal('0')
                
                for trade in trades_history:
                    if isinstance(trade, dict):
                        pnl = Decimal(str(trade.get('pnl', 0)))
                        volume = Decimal(str(trade.get('volume', 0)))
                        
                        total_pnl += pnl
                        total_volume += volume
                        
                        if pnl > 0:
                            winning_trades += 1
                            largest_win = max(largest_win, pnl)
                        elif pnl < 0:
                            losing_trades += 1
                            largest_loss = min(largest_loss, pnl)
                
                metrics.total_trades = len(trades_history)
                metrics.winning_trades = winning_trades
                metrics.losing_trades = losing_trades
                metrics.realized_pnl = total_pnl
                metrics.total_volume = total_volume
                metrics.largest_win = largest_win
                metrics.largest_loss = abs(largest_loss)
                
                if metrics.total_trades > 0:
                    metrics.average_trade_size = total_volume / metrics.total_trades
            
            # Добавляем нереализованную прибыль от текущей позиции
            if current_position and not current_position.is_empty:
                try:
                    # Получаем текущую цену
                    market_data = await self.market_data_provider.get_market_data(self.trading_pair)
                    current_value = current_position.quantity * market_data.current_price.value
                    position_cost = current_position.quantity * current_position.average_price
                    metrics.unrealized_pnl = current_value - position_cost
                except Exception as e:
                    self.logger.warning(f"⚠️ Не удалось рассчитать нереализованную прибыль: {e}")
            
            # Итоговая прибыль
            metrics.total_pnl = metrics.realized_pnl + metrics.unrealized_pnl
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка расчета метрик: {e}")
        
        return metrics
    
    def _determine_report_period(
        self,
        report_type: ReportType,
        period_days: Optional[int],
        custom_start: Optional[datetime],
        custom_end: Optional[datetime]
    ) -> Tuple[datetime, datetime]:
        """📅 Определение периода отчета"""
        
        end_date = custom_end or datetime.now()
        
        if custom_start:
            start_date = custom_start
        elif period_days:
            start_date = end_date - timedelta(days=period_days)
        else:
            # Стандартные периоды по типу отчета
            if report_type == ReportType.DAILY:
                start_date = end_date - timedelta(days=1)
            elif report_type == ReportType.WEEKLY:
                start_date = end_date - timedelta(weeks=1)
            elif report_type == ReportType.MONTHLY:
                start_date = end_date - timedelta(days=30)
            else:
                start_date = end_date - timedelta(days=7)  # По умолчанию неделя
        
        return start_date, end_date
    
    async def _get_period_data(
        self,
        start_date: datetime,
        end_date: datetime
    ) -> List[Dict[str, Any]]:
        """📊 Получение данных за период"""
        try:
            # Получаем данные из истории метрик
            period_data = []
            
            for timestamp, metrics in self.metrics_history:
                if start_date <= timestamp <= end_date:
                    period_data.append({
                        'timestamp': timestamp,
                        'metrics': metrics,
                        'total_pnl': metrics.total_pnl,
                        'trades_count': metrics.total_trades
                    })
            
            return period_data
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка получения данных за период: {e}")
            return []
    
    async def _calculate_period_metrics(
        self,
        period_data: List[Dict[str, Any]]
    ) -> TradingMetrics:
        """📊 Расчет метрик за период"""
        
        if not period_data:
            return TradingMetrics()
        
        # Берем последние метрики из периода
        latest_data = max(period_data, key=lambda x: x['timestamp'])
        return latest_data.get('metrics', TradingMetrics())
    
    async def _analyze_risk_metrics(
        self,
        period_data: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """🛡️ Анализ риск-метрик"""
        
        risk_analysis = {
            'max_drawdown': Decimal('0'),
            'volatility': 0.0,
            'var_95': Decimal('0')
        }
        
        try:
            if not period_data:
                return risk_analysis
            
            # Извлекаем P&L значения
            pnl_values = [float(item['total_pnl']) for item in period_data if 'total_pnl' in item]
            
            if len(pnl_values) < 2:
                return risk_analysis
            
            # Рассчитываем максимальную просадку
            peak = pnl_values[0]
            max_drawdown = 0
            
            for pnl in pnl_values:
                if pnl > peak:
                    peak = pnl
                drawdown = peak - pnl
                if drawdown > max_drawdown:
                    max_drawdown = drawdown
            
            risk_analysis['max_drawdown'] = Decimal(str(max_drawdown))
            
            # Рассчитываем волатильность
            if len(pnl_values) > 1:
                import statistics
                volatility = statistics.stdev(pnl_values) if len(pnl_values) > 1 else 0
                risk_analysis['volatility'] = volatility
            
            # VaR 95% (упрощенный расчет)
            if len(pnl_values) >= 20:  # Минимум данных для VaR
                sorted_pnl = sorted(pnl_values)
                var_95_index = int(len(sorted_pnl) * 0.05)
                risk_analysis['var_95'] = Decimal(str(abs(sorted_pnl[var_95_index])))
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка анализа риск-метрик: {e}")
        
        return risk_analysis
    
    def _analyze_trading_activity(
        self,
        period_data: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """📈 Анализ торговой активности"""
        
        activity_analysis = {
            'daily_pnl': [],
            'hourly_activity': {}
        }
        
        try:
            # Группируем данные по дням
            daily_pnl = {}
            hourly_activity = {}
            
            for item in period_data:
                timestamp = item['timestamp']
                pnl = item.get('total_pnl', Decimal('0'))
                
                # Группировка по дням
                date_key = timestamp.date()
                if date_key not in daily_pnl:
                    daily_pnl[date_key] = Decimal('0')
                daily_pnl[date_key] += pnl
                
                # Группировка по часам
                hour_key = timestamp.hour
                if hour_key not in hourly_activity:
                    hourly_activity[hour_key] = 0
                hourly_activity[hour_key] += 1
            
            # Конвертируем в нужный формат
            activity_analysis['daily_pnl'] = [
                (datetime.combine(date, datetime.min.time()), pnl)
                for date, pnl in sorted(daily_pnl.items())
            ]
            activity_analysis['hourly_activity'] = hourly_activity
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка анализа активности: {e}")
        
        return activity_analysis
    
    def _generate_insights(
        self,
        metrics: TradingMetrics,
        risk_analysis: Dict[str, Any]
    ) -> Tuple[List[str], List[str]]:
        """💡 Генерация инсайтов и предупреждений"""
        
        recommendations = []
        warnings = []
        
        # Анализ винрейта
        if metrics.win_rate > 80:
            recommendations.append("Отличный винрейт! Рассмотрите увеличение размера позиций")
        elif metrics.win_rate < 30:
            warnings.append(f"Низкий винрейт {metrics.win_rate:.1f}% - требуется анализ стратегии")
        
        # Анализ profit factor
        if metrics.profit_factor < 1.0:
            warnings.append(f"Profit factor {metrics.profit_factor:.2f} - стратегия убыточна")
        elif metrics.profit_factor > 3.0:
            recommendations.append("Высокий profit factor - стратегия очень эффективна")
        
        # Анализ просадки
        max_drawdown = risk_analysis.get('max_drawdown', Decimal('0'))
        if max_drawdown > Decimal('100'):  # Более 100 EUR просадки
            warnings.append(f"Высокая просадка {max_drawdown} EUR - усильте риск-менеджмент")
        
        # Анализ волатильности
        volatility = risk_analysis.get('volatility', 0)
        if volatility > 50:  # Высокая волатильность
            warnings.append("Высокая волатильность результатов - рассмотрите снижение рисков")
        
        return recommendations, warnings
    
    def _get_cached_metrics(self, cache_key: str) -> Optional[TradingMetrics]:
        """💾 Получение кэшированных метрик"""
        if cache_key in self._metrics_cache:
            metrics, timestamp = self._metrics_cache[cache_key]
            if datetime.now() - timestamp < self.cache_ttl:
                return metrics
            else:
                del self._metrics_cache[cache_key]
        return None
    
    def _cache_metrics(self, cache_key: str, metrics: TradingMetrics) -> None:
        """💾 Кэширование метрик"""
        self._metrics_cache[cache_key] = (metrics, datetime.now())
        
        # Ограничиваем размер кэша
        if len(self._metrics_cache) > 50:
            oldest_key = min(self._metrics_cache.keys(),
                           key=lambda k: self._metrics_cache[k][1])
            del self._metrics_cache[oldest_key]
    
    async def _save_report(self, report: PerformanceReport) -> None:
        """💾 Сохранение отчета"""
        try:
            report_data = report.to_dict()
            filename = f"report_{report.report_type.value}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            await self.persistence.save_data(filename, report_data)
        except Exception as e:
            self.logger.error(f"❌ Ошибка сохранения отчета: {e}")
    
    def _serialize_metrics(self, metrics: TradingMetrics) -> Dict[str, Any]:
        """📤 Сериализация метрик"""
        return {
            'total_pnl': str(metrics.total_pnl),
            'realized_pnl': str(metrics.realized_pnl),
            'unrealized_pnl': str(metrics.unrealized_pnl),
            'total_trades': metrics.total_trades,
            'winning_trades': metrics.winning_trades,
            'losing_trades': metrics.losing_trades,
            'total_volume': str(metrics.total_volume),
            'average_trade_size': str(metrics.average_trade_size),
            'largest_win': str(metrics.largest_win),
            'largest_loss': str(metrics.largest_loss)
        }
    
    def _deserialize_metrics(self, data: Dict[str, Any]) -> TradingMetrics:
        """📥 Десериализация метрик"""
        metrics = TradingMetrics()
        
        try:
            metrics.total_pnl = Decimal(str(data.get('total_pnl', 0)))
            metrics.realized_pnl = Decimal(str(data.get('realized_pnl', 0)))
            metrics.unrealized_pnl = Decimal(str(data.get('unrealized_pnl', 0)))
            metrics.total_trades = int(data.get('total_trades', 0))
            metrics.winning_trades = int(data.get('winning_trades', 0))
            metrics.losing_trades = int(data.get('losing_trades', 0))
            metrics.total_volume = Decimal(str(data.get('total_volume', 0)))
            metrics.average_trade_size = Decimal(str(data.get('average_trade_size', 0)))
            metrics.largest_win = Decimal(str(data.get('largest_win', 0)))
            metrics.largest_loss = Decimal(str(data.get('largest_loss', 0)))
        except Exception as e:
            self.logger.error(f"❌ Ошибка десериализации метрик: {e}")
        
        return metrics
    
    # Заглушки для методов, которые требуют дополнительной реализации
    async def _analyze_single_trade(self, trade_result: OrderResult) -> Dict[str, Any]:
        """📊 Анализ отдельной сделки"""
        return {'trade_id': getattr(trade_result, 'id', 'unknown')}
    
    async def _update_trade_statistics(self, trade_analysis: Dict[str, Any]) -> None:
        """📊 Обновление статистики сделок"""
        pass
    
    def _detect_trade_anomalies(self, trade_analysis: Dict[str, Any]) -> List[str]:
        """🔍 Обнаружение аномалий в сделке"""
        return []
    
    async def _handle_trade_anomalies(self, anomalies: List[str], trade_result: OrderResult) -> None:
        """⚠️ Обработка аномалий сделки"""
        pass
    
    async def _analyze_recent_trends(self) -> Dict[str, str]:
        """📈 Анализ недавних трендов"""
        return {'pnl_trend': 'stable'}
    
    async def _compare_with_previous_period(self, days_back: int) -> Dict[str, Any]:
        """📊 Сравнение с предыдущим периодом"""
        return {'comparison': 'no_change'}
    
    async def _calculate_risk_metrics(self, historical_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """🛡️ Расчет риск-метрик"""
        return {
            'current_drawdown': 0,
            'max_drawdown': 0,
            'daily_volatility': 0,
            'var_95': 0,
            'sharpe_ratio': 0
        }
    
    async def _export_trades_data(self, start_date: datetime, end_date: datetime) -> List[Dict[str, Any]]:
        """📤 Экспорт данных сделок"""
        return []
    
    async def _export_positions_data(self, start_date: datetime, end_date: datetime) -> List[Dict[str, Any]]:
        """📤 Экспорт данных позиций"""
        return []
    
    async def _get_daily_pnl_series(self, start_date: datetime, end_date: datetime) -> List[Dict[str, Any]]:
        """📈 Получение серии дневных P&L"""
        return []
    
    async def _get_performance_metrics_series(self, start_date: datetime, end_date: datetime) -> List[Dict[str, Any]]:
        """📊 Получение серии метрик производительности"""
        return []
    
    async def _save_export_data(self, export_data: Dict[str, Any], format_type: str) -> None:
        """💾 Сохранение экспортированных данных"""
        pass
    
    def _analyze_performance_trends(self, historical_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """📈 Анализ трендов производительности"""
        return {'trend': 'stable'}
    
    async def _publish_report_event(self, report: PerformanceReport) -> None:
        """📡 Публикация события отчета"""
        try:
            event = DomainEvent()
            event.event_type = "performance_report_generated"
            event.source = "analytics_service"
            event.metadata = {
                'report_type': report.report_type.value,
                'period_days': (report.period_end - report.period_start).days,
                'total_trades': report.metrics.total_trades,
                'win_rate': report.metrics.win_rate
            }
            
            await publish_event(event)
            
        except Exception as e:
            self.logger.warning(f"⚠️ Ошибка публикации события отчета: {e}")
    
    async def _publish_trade_analysis_event(self, trade_analysis: Dict[str, Any]) -> None:
        """📡 Публикация события анализа сделки"""
        try:
            event = DomainEvent()
            event.event_type = "trade_analyzed"
            event.source = "analytics_service"
            event.metadata = trade_analysis
            
            await publish_event(event)
            
        except Exception as e:
            self.logger.warning(f"⚠️ Ошибка публикации события анализа сделки: {e}")
