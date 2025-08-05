from typing import Optional, List, Dict, Any, Tuple
from decimal import Decimal
from datetime import datetime, timedelta
import logging
from dataclasses import dataclass, field
from enum import Enum
import json
import statistics

# Импорты из Core слоя
try:
    from ...core.interfaces import IAnalyticsService
    from ...core.models import Trade, Position, TradeSignal, OrderResult, TradingSession
    from ...core.exceptions import TradingSystemError, DataError, ValidationError
    from ...core.events import DomainEvent, publish_event
    from ...config.settings import get_current_config
except ImportError:
    # Fallback для случая если Core слой еще не готов
    class IAnalyticsService: pass
    class Trade: pass
    class Position: pass
    class TradeSignal: pass
    class OrderResult: pass
    class TradingSession: pass
    class TradingSystemError(Exception): pass
    class DataError(Exception): pass
    class ValidationError(Exception): pass
    class DomainEvent: pass
    def publish_event(event): pass
    def get_current_config(): return None


# ================= ТИПЫ АНАЛИТИКИ =================

class ReportType(Enum):
    """📊 Типы отчетов"""
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    PERFORMANCE = "performance"
    RISK = "risk"
    STRATEGY = "strategy"
    POSITION = "position"
    CUSTOM = "custom"


class MetricType(Enum):
    """📈 Типы метрик"""
    RETURN = "return"
    VOLATILITY = "volatility"
    DRAWDOWN = "drawdown"
    SHARPE_RATIO = "sharpe_ratio"
    WIN_RATE = "win_rate"
    PROFIT_FACTOR = "profit_factor"
    AVERAGE_TRADE = "average_trade"
    TRADE_FREQUENCY = "trade_frequency"


@dataclass
class TradeAnalysis:
    """📈 Анализ сделки"""
    trade_id: str
    pair: str
    strategy: str
    entry_time: datetime
    exit_time: Optional[datetime]
    duration_minutes: Optional[float]
    pnl: Decimal
    pnl_percent: float
    quantity: Decimal
    entry_price: Decimal
    exit_price: Optional[Decimal]
    commission: Decimal
    is_winner: bool
    risk_reward_ratio: Optional[float]

    @property
    def duration_hours(self) -> Optional[float]:
        """Длительность в часах"""
        return self.duration_minutes / 60 if self.duration_minutes else None


@dataclass
class PerformanceMetrics:
    """📊 Метрики производительности"""
    period_start: datetime
    period_end: datetime
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl: Decimal = Decimal('0')
    gross_profit: Decimal = Decimal('0')
    gross_loss: Decimal = Decimal('0')
    max_profit: Decimal = Decimal('0')
    max_loss: Decimal = Decimal('0')
    average_profit: Decimal = Decimal('0')
    average_loss: Decimal = Decimal('0')
    total_commission: Decimal = Decimal('0')
    max_drawdown: Decimal = Decimal('0')
    current_drawdown: Decimal = Decimal('0')
    consecutive_wins: int = 0
    consecutive_losses: int = 0
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0

    @property
    def win_rate(self) -> float:
        """Процент выигрышных сделок"""
        return (self.winning_trades / self.total_trades * 100) if self.total_trades > 0 else 0.0

    @property
    def profit_factor(self) -> float:
        """Коэффициент прибыльности"""
        return float(self.gross_profit / abs(self.gross_loss)) if self.gross_loss != 0 else 0.0

    @property
    def average_trade(self) -> Decimal:
        """Средняя прибыль на сделку"""
        return self.total_pnl / self.total_trades if self.total_trades > 0 else Decimal('0')

    @property
    def risk_reward_ratio(self) -> float:
        """Соотношение риск/прибыль"""
        if self.average_loss == 0:
            return 0.0
        return float(self.average_profit / abs(self.average_loss))


@dataclass
class StrategyPerformance:
    """🎯 Производительность стратегии"""
    strategy_name: str
    metrics: PerformanceMetrics
    signal_count: int = 0
    execution_rate: float = 0.0
    average_confidence: float = 0.0
    best_pair: Optional[str] = None
    worst_pair: Optional[str] = None
    trades_by_pair: Dict[str, int] = field(default_factory=dict)


@dataclass
class RiskMetrics:
    """🛡️ Метрики рисков"""
    value_at_risk_5: Decimal = Decimal('0')      # VaR 5%
    value_at_risk_1: Decimal = Decimal('0')      # VaR 1%
    expected_shortfall: Decimal = Decimal('0')    # Expected Shortfall
    maximum_drawdown: Decimal = Decimal('0')      # Максимальная просадка
    sharpe_ratio: float = 0.0                    # Коэффициент Шарпа
    sortino_ratio: float = 0.0                   # Коэффициент Сортино
    calmar_ratio: float = 0.0                    # Коэффициент Калмара
    beta: float = 0.0                            # Бета к рынку
    correlation_to_market: float = 0.0           # Корреляция с рынком


# ================= ОСНОВНОЙ СЕРВИС =================

class AnalyticsService(IAnalyticsService):
    """📊 Сервис торговой аналитики"""

    def __init__(self):
        # Хранилище данных
        self.trades: List[TradeAnalysis] = []
        self.positions_history: List[Position] = []
        self.signals_history: List[TradeSignal] = []

        # Кэш метрик
        self.metrics_cache: Dict[str, Tuple[datetime, Any]] = {}
        self.cache_ttl = timedelta(minutes=5)

        # Настройки
        self.max_history_days = 365
        self.benchmark_returns: List[float] = []  # Для расчета бета

        # Логирование
        self.logger = logging.getLogger(__name__)

        self.logger.info("📊 AnalyticsService инициализирован")

    # ================= ОСНОВНЫЕ МЕТОДЫ ИНТЕРФЕЙСА =================

    async def record_trade(self, trade: Trade) -> None:
        """📝 Запись сделки"""

        try:
            # Создаем анализ сделки
            trade_analysis = TradeAnalysis(
                trade_id=trade.id,
                pair=str(trade.pair),
                strategy=trade.strategy_name or "unknown",
                entry_time=trade.timestamp,
                exit_time=None,  # Будет обновлено при закрытии
                duration_minutes=None,
                pnl=Decimal('0'),  # Будет рассчитано при закрытии
                pnl_percent=0.0,
                quantity=trade.quantity,
                entry_price=trade.price,
                exit_price=None,
                commission=trade.commission,
                is_winner=False,
                risk_reward_ratio=None
            )

            # Добавляем в хранилище
            self.trades.append(trade_analysis)

            # Ограничиваем размер истории
            self._limit_history()

            # Очищаем кэш метрик
            self._clear_metrics_cache()

            self.logger.debug(f"📝 Записана сделка: {trade.id}")

        except Exception as e:
            self.logger.error(f"❌ Ошибка записи сделки: {e}")

    async def calculate_performance(
        self,
        period_days: int = 30
    ) -> Dict[str, Union[float, int]]:
        """📈 Расчет производительности"""

        try:
            cache_key = f"performance_{period_days}"
            cached_result = self._get_from_cache(cache_key)
            if cached_result:
                return cached_result

            # Получаем сделки за период
            end_date = datetime.now()
            start_date = end_date - timedelta(days=period_days)

            period_trades = [
                trade for trade in self.trades
                if start_date <= trade.entry_time <= end_date
            ]

            if not period_trades:
                return {
                    'total_trades': 0,
                    'win_rate': 0.0,
                    'total_pnl': 0.0,
                    'profit_factor': 0.0,
                    'average_trade': 0.0,
                    'max_drawdown': 0.0
                }

            # Рассчитываем метрики
            metrics = self._calculate_performance_metrics(period_trades, start_date, end_date)

            result = {
                'total_trades': metrics.total_trades,
                'winning_trades': metrics.winning_trades,
                'losing_trades': metrics.losing_trades,
                'win_rate': metrics.win_rate,
                'total_pnl': float(metrics.total_pnl),
                'gross_profit': float(metrics.gross_profit),
                'gross_loss': float(metrics.gross_loss),
                'profit_factor': metrics.profit_factor,
                'average_trade': float(metrics.average_trade),
                'max_profit': float(metrics.max_profit),
                'max_loss': float(metrics.max_loss),
                'max_drawdown': float(metrics.max_drawdown),
                'total_commission': float(metrics.total_commission),
                'risk_reward_ratio': metrics.risk_reward_ratio
            }

            # Кэшируем результат
            self._cache_result(cache_key, result)

            return result

        except Exception as e:
            self.logger.error(f"❌ Ошибка расчета производительности: {e}")
            return {}

    async def generate_report(
        self,
        report_type: str,
        period_days: int = 7
    ) -> Dict[str, Any]:
        """📋 Генерация отчета"""

        try:
            report_type_enum = ReportType(report_type)

            if report_type_enum == ReportType.DAILY:
                return await self._generate_daily_report()
            elif report_type_enum == ReportType.WEEKLY:
                return await self._generate_weekly_report()
            elif report_type_enum == ReportType.MONTHLY:
                return await self._generate_monthly_report()
            elif report_type_enum == ReportType.PERFORMANCE:
                return await self._generate_performance_report(period_days)
            elif report_type_enum == ReportType.STRATEGY:
                return await self._generate_strategy_report(period_days)
            elif report_type_enum == ReportType.RISK:
                return await self._generate_risk_report(period_days)
            else:
                return await self._generate_custom_report(period_days)

        except Exception as e:
            self.logger.error(f"❌ Ошибка генерации отчета {report_type}: {e}")
            return {'error': str(e)}

    async def get_trading_statistics(self) -> Dict[str, Any]:
        """📊 Получение торговой статистики"""

        try:
            cache_key = "trading_statistics"
            cached_result = self._get_from_cache(cache_key)
            if cached_result:
                return cached_result

            total_trades = len(self.trades)
            if total_trades == 0:
                return {
                    'total_trades': 0,
                    'active_since': None,
                    'average_trades_per_day': 0,
                    'most_traded_pair': None,
                    'best_strategy': None,
                    'trading_days': 0
                }

            # Основная статистика
            first_trade = min(self.trades, key=lambda t: t.entry_time)
            last_trade = max(self.trades, key=lambda t: t.entry_time)

            trading_period = (last_trade.entry_time - first_trade.entry_time).days
            trading_days = max(trading_period, 1)

            # Анализ по парам
            pair_counts = {}
            for trade in self.trades:
                pair_counts[trade.pair] = pair_counts.get(trade.pair, 0) + 1

            most_traded_pair = max(pair_counts.items(), key=lambda x: x[1]) if pair_counts else None

            # Анализ по стратегиям
            strategy_performance = {}
            for trade in self.trades:
                if trade.strategy not in strategy_performance:
                    strategy_performance[trade.strategy] = {'trades': 0, 'pnl': Decimal('0')}
                strategy_performance[trade.strategy]['trades'] += 1
                strategy_performance[trade.strategy]['pnl'] += trade.pnl

            best_strategy = None
            if strategy_performance:
                best_strategy = max(
                    strategy_performance.items(),
                    key=lambda x: x[1]['pnl']
                )[0]

            result = {
                'total_trades': total_trades,
                'active_since': first_trade.entry_time.isoformat(),
                'trading_days': trading_days,
                'average_trades_per_day': round(total_trades / trading_days, 2),
                'most_traded_pair': most_traded_pair[0] if most_traded_pair else None,
                'most_traded_pair_count': most_traded_pair[1] if most_traded_pair else 0,
                'best_strategy': best_strategy,
                'total_strategies': len(strategy_performance),
                'unique_pairs': len(pair_counts),
                'last_trade_time': last_trade.entry_time.isoformat()
            }

            self._cache_result(cache_key, result)
            return result

        except Exception as e:
            self.logger.error(f"❌ Ошибка получения статистики: {e}")
            return {}

    async def export_data(
        self,
        format_type: str,
        date_from: datetime,
        date_to: datetime
    ) -> str:
        """💾 Экспорт данных"""

        try:
            # Фильтруем данные по периоду
            filtered_trades = [
                trade for trade in self.trades
                if date_from <= trade.entry_time <= date_to
            ]

            if format_type.lower() == 'json':
                return await self._export_to_json(filtered_trades)
            elif format_type.lower() == 'csv':
                return await self._export_to_csv(filtered_trades)
            else:
                raise ValidationError(f"Неподдерживаемый формат: {format_type}")

        except Exception as e:
            self.logger.error(f"❌ Ошибка экспорта данных: {e}")
            raise DataError(f"Ошибка экспорта: {e}")

    # ================= ГЕНЕРАЦИЯ ОТЧЕТОВ =================

    async def _generate_daily_report(self) -> Dict[str, Any]:
        """📅 Дневной отчет"""

        today = datetime.now().date()
        today_start = datetime.combine(today, datetime.min.time())
        today_end = datetime.combine(today, datetime.max.time())

        today_trades = [
            trade for trade in self.trades
            if today_start <= trade.entry_time <= today_end
        ]

        metrics = self._calculate_performance_metrics(
            today_trades, today_start, today_end
        )

        return {
            'report_type': 'daily',
            'date': today.isoformat(),
            'summary': {
                'total_trades': metrics.total_trades,
                'win_rate': metrics.win_rate,
                'total_pnl': float(metrics.total_pnl),
                'profit_factor': metrics.profit_factor,
                'max_profit': float(metrics.max_profit),
                'max_loss': float(metrics.max_loss),
                'commission_paid': float(metrics.total_commission)
            },
            'trades': [self._trade_to_dict(trade) for trade in today_trades[-10:]]  # Последние 10
        }

    async def _generate_performance_report(self, period_days: int) -> Dict[str, Any]:
        """📈 Отчет по производительности"""

        end_date = datetime.now()
        start_date = end_date - timedelta(days=period_days)

        period_trades = [
            trade for trade in self.trades
            if start_date <= trade.entry_time <= end_date
        ]

        metrics = self._calculate_performance_metrics(period_trades, start_date, end_date)
        risk_metrics = self._calculate_risk_metrics(period_trades)

        # Анализ по дням
        daily_pnl = self._calculate_daily_pnl(period_trades, start_date, end_date)

        return {
            'report_type': 'performance',
            'period': f"{start_date.date()} to {end_date.date()}",
            'performance_metrics': {
                'total_trades': metrics.total_trades,
                'win_rate': metrics.win_rate,
                'profit_factor': metrics.profit_factor,
                'total_pnl': float(metrics.total_pnl),
                'average_trade': float(metrics.average_trade),
                'max_drawdown': float(metrics.max_drawdown),
                'consecutive_wins': metrics.max_consecutive_wins,
                'consecutive_losses': metrics.max_consecutive_losses
            },
            'risk_metrics': {
                'sharpe_ratio': risk_metrics.sharpe_ratio,
                'sortino_ratio': risk_metrics.sortino_ratio,
                'maximum_drawdown': float(risk_metrics.maximum_drawdown),
                'value_at_risk_5': float(risk_metrics.value_at_risk_5)
            },
            'daily_pnl': daily_pnl,
            'best_trades': [
                self._trade_to_dict(trade) for trade in
                sorted(period_trades, key=lambda t: t.pnl, reverse=True)[:5]
            ],
            'worst_trades': [
                self._trade_to_dict(trade) for trade in
                sorted(period_trades, key=lambda t: t.pnl)[:5]
            ]
        }

    async def _generate_strategy_report(self, period_days: int) -> Dict[str, Any]:
        """🎯 Отчет по стратегиям"""

        end_date = datetime.now()
        start_date = end_date - timedelta(days=period_days)

        period_trades = [
            trade for trade in self.trades
            if start_date <= trade.entry_time <= end_date
        ]

        # Группируем по стратегиям
        strategy_trades = {}
        for trade in period_trades:
            if trade.strategy not in strategy_trades:
                strategy_trades[trade.strategy] = []
            strategy_trades[trade.strategy].append(trade)

        # Анализируем каждую стратегию
        strategy_performance = {}
        for strategy_name, trades in strategy_trades.items():
            metrics = self._calculate_performance_metrics(trades, start_date, end_date)
            strategy_performance[strategy_name] = {
                'total_trades': metrics.total_trades,
                'win_rate': metrics.win_rate,
                'total_pnl': float(metrics.total_pnl),
                'profit_factor': metrics.profit_factor,
                'average_trade': float(metrics.average_trade),
                'best_trade': float(metrics.max_profit),
                'worst_trade': float(metrics.max_loss)
            }

        # Сортируем по прибыльности
        sorted_strategies = sorted(
            strategy_performance.items(),
            key=lambda x: x[1]['total_pnl'],
            reverse=True
        )

        return {
            'report_type': 'strategy',
            'period': f"{start_date.date()} to {end_date.date()}",
            'strategy_performance': dict(sorted_strategies),
            'summary': {
                'total_strategies': len(strategy_performance),
                'most_profitable': sorted_strategies[0][0] if sorted_strategies else None,
                'least_profitable': sorted_strategies[-1][0] if sorted_strategies else None,
                'total_trades': sum(perf['total_trades'] for perf in strategy_performance.values()),
                'combined_pnl': sum(perf['total_pnl'] for perf in strategy_performance.values())
            }
        }

    # ================= ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ =================

    def _calculate_performance_metrics(
        self,
        trades: List[TradeAnalysis],
        start_date: datetime,
        end_date: datetime
    ) -> PerformanceMetrics:
        """📊 Расчет метрик производительности"""

        metrics = PerformanceMetrics(
            period_start=start_date,
            period_end=end_date
        )

        if not trades:
            return metrics

        metrics.total_trades = len(trades)

        # Основная статистика
        profits = []
        losses = []
        current_streak = 0
        current_streak_type = None

        for trade in trades:
            metrics.total_pnl += trade.pnl
            metrics.total_commission += trade.commission

            if trade.is_winner:
                metrics.winning_trades += 1
                metrics.gross_profit += trade.pnl
                profits.append(float(trade.pnl))

                if current_streak_type == 'win':
                    current_streak += 1
                else:
                    metrics.max_consecutive_wins = max(metrics.max_consecutive_wins, current_streak)
                    current_streak = 1
                    current_streak_type = 'win'

                if trade.pnl > metrics.max_profit:
                    metrics.max_profit = trade.pnl
            else:
                metrics.losing_trades += 1
                metrics.gross_loss += trade.pnl  # pnl уже отрицательный
                losses.append(float(trade.pnl))

                if current_streak_type == 'loss':
                    current_streak += 1
                else:
                    metrics.max_consecutive_losses = max(metrics.max_consecutive_losses, current_streak)
                    current_streak = 1
                    current_streak_type = 'loss'

                if trade.pnl < metrics.max_loss:
                    metrics.max_loss = trade.pnl

        # Финализируем streak счетчики
        if current_streak_type == 'win':
            metrics.max_consecutive_wins = max(metrics.max_consecutive_wins, current_streak)
        else:
            metrics.max_consecutive_losses = max(metrics.max_consecutive_losses, current_streak)

        # Средние значения
        if profits:
            metrics.average_profit = Decimal(str(statistics.mean(profits)))
        if losses:
            metrics.average_loss = Decimal(str(statistics.mean(losses)))

        # Максимальная просадка (упрощенный расчет)
        running_pnl = Decimal('0')
        peak = Decimal('0')
        max_dd = Decimal('0')

        for trade in sorted(trades, key=lambda t: t.entry_time):
            running_pnl += trade.pnl
            if running_pnl > peak:
                peak = running_pnl

            current_dd = peak - running_pnl
            if current_dd > max_dd:
                max_dd = current_dd

        metrics.max_drawdown = max_dd

        return metrics

    def _calculate_risk_metrics(self, trades: List[TradeAnalysis]) -> RiskMetrics:
        """🛡️ Расчет метрик рисков"""

        risk_metrics = RiskMetrics()

        if not trades:
            return risk_metrics

        # Извлекаем доходности
        returns = [float(trade.pnl_percent) / 100 for trade in trades if trade.pnl_percent != 0]

        if len(returns) < 2:
            return risk_metrics

        # Основные статистики
        mean_return = statistics.mean(returns)
        std_return = statistics.stdev(returns)

        # Коэффициент Шарпа (упрощенный, без risk-free rate)
        if std_return > 0:
            risk_metrics.sharpe_ratio = mean_return / std_return

        # Value at Risk (5% и 1%)
        sorted_returns = sorted(returns)
        n = len(sorted_returns)

        if n >= 20:  # Минимум для VaR
            var_5_index = int(n * 0.05)
            var_1_index = int(n * 0.01)

            risk_metrics.value_at_risk_5 = Decimal(str(abs(sorted_returns[var_5_index])))
            risk_metrics.value_at_risk_1 = Decimal(str(abs(sorted_returns[var_1_index])))

        # Максимальная просадка
        cumulative_returns = []
        cumulative = 1.0
        for ret in returns:
            cumulative *= (1 + ret)
            cumulative_returns.append(cumulative)

        peak = 1.0
        max_drawdown = 0.0

        for cum_ret in cumulative_returns:
            if cum_ret > peak:
                peak = cum_ret

            drawdown = (peak - cum_ret) / peak
            if drawdown > max_drawdown:
                max_drawdown = drawdown

        risk_metrics.maximum_drawdown = Decimal(str(max_drawdown))

        return risk_metrics

    def _calculate_daily_pnl(
        self,
        trades: List[TradeAnalysis],
        start_date: datetime,
        end_date: datetime
    ) -> Dict[str, float]:
        """📅 Расчет дневного P&L"""

        daily_pnl = {}
        current_date = start_date.date()
        end_date_only = end_date.date()

        # Инициализируем все дни нулями
        while current_date <= end_date_only:
            daily_pnl[current_date.isoformat()] = 0.0
            current_date += timedelta(days=1)

        # Суммируем P&L по дням
        for trade in trades:
            trade_date = trade.entry_time.date().isoformat()
            if trade_date in daily_pnl:
                daily_pnl[trade_date] += float(trade.pnl)

        return daily_pnl

    def _trade_to_dict(self, trade: TradeAnalysis) -> Dict[str, Any]:
        """📤 Конвертация сделки в словарь"""

        return {
            'trade_id': trade.trade_id,
            'pair': trade.pair,
            'strategy': trade.strategy,
            'entry_time': trade.entry_time.isoformat(),
            'duration_minutes': trade.duration_minutes,
            'pnl': float(trade.pnl),
            'pnl_percent': trade.pnl_percent,
            'quantity': float(trade.quantity),
            'entry_price': float(trade.entry_price),
            'commission': float(trade.commission),
            'is_winner': trade.is_winner
        }

    async def _export_to_json(self, trades: List[TradeAnalysis]) -> str:
        """📄 Экспорт в JSON"""

        export_data = {
            'export_date': datetime.now().isoformat(),
            'total_trades': len(trades),
            'trades': [self._trade_to_dict(trade) for trade in trades]
        }

        return json.dumps(export_data, indent=2, ensure_ascii=False)

    async def _export_to_csv(self, trades: List[TradeAnalysis]) -> str:
        """📊 Экспорт в CSV"""

        if not trades:
            return "No trades to export"

        # CSV заголовки
        headers = [
            'trade_id', 'pair', 'strategy', 'entry_time', 'duration_minutes',
            'pnl', 'pnl_percent', 'quantity', 'entry_price', 'commission', 'is_winner'
        ]

        csv_lines = [','.join(headers)]

        # Добавляем данные
        for trade in trades:
            row = [
                trade.trade_id,
                trade.pair,
                trade.strategy,
                trade.entry_time.isoformat(),
                str(trade.duration_minutes or ''),
                str(trade.pnl),
                str(trade.pnl_percent),
                str(trade.quantity),
                str(trade.entry_price),
                str(trade.commission),
                str(trade.is_winner)
            ]
            csv_lines.append(','.join(row))

        return '\n'.join(csv_lines)

    # ================= КЭШИРОВАНИЕ И УТИЛИТЫ =================

    def _get_from_cache(self, key: str) -> Optional[Any]:
        """📖 Получение из кэша"""

        if key in self.metrics_cache:
            cached_time, cached_data = self.metrics_cache[key]
            if datetime.now() - cached_time < self.cache_ttl:
                return cached_data

        return None

    def _cache_result(self, key: str, data: Any) -> None:
        """💾 Кэширование результата"""

        self.metrics_cache[key] = (datetime.now(), data)

        # Ограничиваем размер кэша
        if len(self.metrics_cache) > 50:
            # Удаляем самые старые записи
            oldest_keys = sorted(
                self.metrics_cache.keys(),
                key=lambda k: self.metrics_cache[k][0]
            )[:10]

            for old_key in oldest_keys:
                del self.metrics_cache[old_key]

    def _clear_metrics_cache(self) -> None:
        """🧹 Очистка кэша метрик"""

        self.metrics_cache.clear()

    def _limit_history(self) -> None:
        """📏 Ограничение размера истории"""

        cutoff_date = datetime.now() - timedelta(days=self.max_history_days)

        # Удаляем старые сделки
        self.trades = [
            trade for trade in self.trades
            if trade.entry_time > cutoff_date
        ]

        # Удаляем старые позиции
        self.positions_history = [
            pos for pos in self.positions_history
            if pos.updated_at > cutoff_date
        ]

    async def _generate_weekly_report(self) -> Dict[str, Any]:
        """📅 Недельный отчет"""

        end_date = datetime.now()
        start_date = end_date - timedelta(days=7)

        week_trades = [
            trade for trade in self.trades
            if start_date <= trade.entry_time <= end_date
        ]

        metrics = self._calculate_performance_metrics(week_trades, start_date, end_date)

        # Анализ по дням недели
        daily_stats = {}
        for i in range(7):
            day_start = start_date + timedelta(days=i)
            day_end = day_start + timedelta(days=1)
            day_trades = [
                trade for trade in week_trades
                if day_start <= trade.entry_time < day_end
            ]

            daily_stats[day_start.strftime('%A')] = {
                'trades': len(day_trades),
                'pnl': float(sum(trade.pnl for trade in day_trades))
            }

        return {
            'report_type': 'weekly',
            'period': f"{start_date.date()} to {end_date.date()}",
            'summary': {
                'total_trades': metrics.total_trades,
                'win_rate': metrics.win_rate,
                'total_pnl': float(metrics.total_pnl),
                'profit_factor': metrics.profit_factor,
                'average_daily_trades': metrics.total_trades / 7
            },
            'daily_breakdown': daily_stats,
            'top_pairs': self._get_top_trading_pairs(week_trades, 5)
        }

    async def _generate_monthly_report(self) -> Dict[str, Any]:
        """📅 Месячный отчет"""

        end_date = datetime.now()
        start_date = end_date - timedelta(days=30)

        month_trades = [
            trade for trade in self.trades
            if start_date <= trade.entry_time <= end_date
        ]

        metrics = self._calculate_performance_metrics(month_trades, start_date, end_date)

        # Анализ по неделям
        weekly_stats = {}
        for week in range(4):
            week_start = start_date + timedelta(weeks=week)
            week_end = week_start + timedelta(weeks=1)
            week_trades = [
                trade for trade in month_trades
                if week_start <= trade.entry_time < week_end
            ]

            weekly_stats[f'Week {week + 1}'] = {
                'trades': len(week_trades),
                'pnl': float(sum(trade.pnl for trade in week_trades)),
                'win_rate': (
                    sum(1 for trade in week_trades if trade.is_winner) /
                    len(week_trades) * 100
                ) if week_trades else 0
            }

        return {
            'report_type': 'monthly',
            'period': f"{start_date.date()} to {end_date.date()}",
            'summary': {
                'total_trades': metrics.total_trades,
                'win_rate': metrics.win_rate,
                'total_pnl': float(metrics.total_pnl),
                'profit_factor': metrics.profit_factor,
                'max_drawdown': float(metrics.max_drawdown),
                'average_weekly_trades': metrics.total_trades / 4
            },
            'weekly_breakdown': weekly_stats,
            'performance_trend': self._calculate_performance_trend(month_trades)
        }

    async def _generate_risk_report(self, period_days: int) -> Dict[str, Any]:
        """🛡️ Отчет по рискам"""

        end_date = datetime.now()
        start_date = end_date - timedelta(days=period_days)

        period_trades = [
            trade for trade in self.trades
            if start_date <= trade.entry_time <= end_date
        ]

        risk_metrics = self._calculate_risk_metrics(period_trades)

        # Анализ распределения убытков
        losses = [float(trade.pnl) for trade in period_trades if trade.pnl < 0]

        loss_distribution = {}
        if losses:
            loss_ranges = [
                (-float('inf'), -1000), (-1000, -500), (-500, -100),
                (-100, -50), (-50, -10), (-10, 0)
            ]

            for min_loss, max_loss in loss_ranges:
                count = sum(1 for loss in losses if min_loss <= loss < max_loss)
                range_key = f"{min_loss}_{max_loss}".replace('-inf', 'below')
                loss_distribution[range_key] = count

        return {
            'report_type': 'risk',
            'period': f"{start_date.date()} to {end_date.date()}",
            'risk_metrics': {
                'maximum_drawdown': float(risk_metrics.maximum_drawdown),
                'value_at_risk_5': float(risk_metrics.value_at_risk_5),
                'value_at_risk_1': float(risk_metrics.value_at_risk_1),
                'sharpe_ratio': risk_metrics.sharpe_ratio,
                'sortino_ratio': risk_metrics.sortino_ratio
            },
            'loss_analysis': {
                'total_losses': len(losses),
                'average_loss': statistics.mean(losses) if losses else 0,
                'max_loss': min(losses) if losses else 0,
                'loss_distribution': loss_distribution
            },
            'risk_recommendations': self._generate_risk_recommendations(risk_metrics)
        }

    async def _generate_custom_report(self, period_days: int) -> Dict[str, Any]:
        """📊 Пользовательский отчет"""

        # Комбинированный отчет с основными метриками
        performance = await self.calculate_performance(period_days)
        statistics_data = await self.get_trading_statistics()

        end_date = datetime.now()
        start_date = end_date - timedelta(days=period_days)

        period_trades = [
            trade for trade in self.trades
            if start_date <= trade.entry_time <= end_date
        ]

        return {
            'report_type': 'custom',
            'period': f"{start_date.date()} to {end_date.date()}",
            'performance_summary': performance,
            'trading_statistics': statistics_data,
            'trade_analysis': {
                'most_profitable_trade': self._get_best_trade(period_trades),
                'least_profitable_trade': self._get_worst_trade(period_trades),
                'average_trade_duration': self._get_average_duration(period_trades),
                'trading_frequency': len(period_trades) / max(period_days, 1)
            },
            'recommendations': self._generate_trading_recommendations(period_trades)
        }

    def _get_top_trading_pairs(self, trades: List[TradeAnalysis], limit: int) -> List[Dict[str, Any]]:
        """🏆 Топ торговых пар"""

        pair_stats = {}
        for trade in trades:
            if trade.pair not in pair_stats:
                pair_stats[trade.pair] = {'trades': 0, 'pnl': Decimal('0')}

            pair_stats[trade.pair]['trades'] += 1
            pair_stats[trade.pair]['pnl'] += trade.pnl

        sorted_pairs = sorted(
            pair_stats.items(),
            key=lambda x: x[1]['pnl'],
            reverse=True
        )[:limit]

        return [
            {
                'pair': pair,
                'trades': stats['trades'],
                'pnl': float(stats['pnl'])
            }
            for pair, stats in sorted_pairs
        ]

    def _calculate_performance_trend(self, trades: List[TradeAnalysis]) -> List[Dict[str, Any]]:
        """📈 Тренд производительности"""

        if not trades:
            return []

        # Сортируем по времени
        sorted_trades = sorted(trades, key=lambda t: t.entry_time)

        # Разбиваем на периоды (по 7 дней)
        periods = []
        current_period_start = sorted_trades[0].entry_time
        period_trades = []

        for trade in sorted_trades:
            if (trade.entry_time - current_period_start).days >= 7:
                if period_trades:
                    periods.append({
                        'start_date': current_period_start.date().isoformat(),
                        'trades': len(period_trades),
                        'pnl': float(sum(t.pnl for t in period_trades)),
                        'win_rate': sum(1 for t in period_trades if t.is_winner) / len(period_trades) * 100
                    })

                current_period_start = trade.entry_time
                period_trades = []

            period_trades.append(trade)

        # Добавляем последний период
        if period_trades:
            periods.append({
                'start_date': current_period_start.date().isoformat(),
                'trades': len(period_trades),
                'pnl': float(sum(t.pnl for t in period_trades)),
                'win_rate': sum(1 for t in period_trades if t.is_winner) / len(period_trades) * 100
            })

        return periods

    def _get_best_trade(self, trades: List[TradeAnalysis]) -> Optional[Dict[str, Any]]:
        """🏆 Лучшая сделка"""

        if not trades:
            return None

        best_trade = max(trades, key=lambda t: t.pnl)
        return self._trade_to_dict(best_trade)

    def _get_worst_trade(self, trades: List[TradeAnalysis]) -> Optional[Dict[str, Any]]:
        """💸 Худшая сделка"""

        if not trades:
            return None

        worst_trade = min(trades, key=lambda t: t.pnl)
        return self._trade_to_dict(worst_trade)

    def _get_average_duration(self, trades: List[TradeAnalysis]) -> Optional[float]:
        """⏱️ Средняя длительность сделки"""

        durations = [t.duration_minutes for t in trades if t.duration_minutes is not None]

        return statistics.mean(durations) if durations else None

    def _generate_risk_recommendations(self, risk_metrics: RiskMetrics) -> List[str]:
        """💡 Рекомендации по рискам"""

        recommendations = []

        if risk_metrics.maximum_drawdown > Decimal('0.15'):  # 15%
            recommendations.append("Высокая просадка - рассмотрите уменьшение размеров позиций")

        if risk_metrics.sharpe_ratio < 0.5:
            recommendations.append("Низкий коэффициент Шарпа - улучшите соотношение риск/доходность")

        if risk_metrics.value_at_risk_5 > Decimal('0.05'):  # 5%
            recommendations.append("Высокий VaR - пересмотрите стратегии управления рисками")

        if not recommendations:
            recommendations.append("Риск-профиль в пределах нормы")

        return recommendations

    def _generate_trading_recommendations(self, trades: List[TradeAnalysis]) -> List[str]:
        """💡 Торговые рекомендации"""

        recommendations = []

        if not trades:
            return ["Недостаточно данных для рекомендаций"]

        # Анализ win rate
        win_rate = sum(1 for t in trades if t.is_winner) / len(trades) * 100

        if win_rate < 40:
            recommendations.append("Низкий винрейт - пересмотрите критерии входа в позицию")
        elif win_rate > 70:
            recommendations.append("Высокий винрейт - возможно, стоит увеличить размеры позиций")

        # Анализ прибыльности
        total_pnl = sum(t.pnl for t in trades)

        if total_pnl < 0:
            recommendations.append("Отрицательная прибыльность - требуется пересмотр стратегий")

        # Анализ частоты торговли
        if len(trades) < 10:
            recommendations.append("Низкая торговая активность - рассмотрите более активные стратегии")

        if not recommendations:
            recommendations.append("Торговые показатели в норме, продолжайте текущие стратегии")

        return recommendations

    # ================= ДОПОЛНИТЕЛЬНЫЕ МЕТОДЫ =================

    def add_position_snapshot(self, position: Position) -> None:
        """📸 Добавление снимка позиции"""

        try:
            self.positions_history.append(position)
            self._limit_history()

        except Exception as e:
            self.logger.error(f"❌ Ошибка добавления снимка позиции: {e}")

    def add_signal_record(self, signal: TradeSignal) -> None:
        """📝 Запись торгового сигнала"""

        try:
            self.signals_history.append(signal)

            # Ограничиваем историю сигналов
            if len(self.signals_history) > 10000:
                self.signals_history = self.signals_history[-5000:]

        except Exception as e:
            self.logger.error(f"❌ Ошибка записи сигнала: {e}")

    def get_service_statistics(self) -> Dict[str, Any]:
        """📊 Статистика сервиса"""

        return {
            'trades_stored': len(self.trades),
            'positions_snapshots': len(self.positions_history),
            'signals_recorded': len(self.signals_history),
            'cache_entries': len(self.metrics_cache),
            'cache_hit_rate': 'N/A',  # Можно добавить отслеживание
            'oldest_trade': (
                min(self.trades, key=lambda t: t.entry_time).entry_time.isoformat()
                if self.trades else None
            ),
            'newest_trade': (
                max(self.trades, key=lambda t: t.entry_time).entry_time.isoformat()
                if self.trades else None
            ),
            'max_history_days': self.max_history_days
        }
