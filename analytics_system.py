import json
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
import os
from dataclasses import dataclass
import logging


@dataclass
class TradeAnalysis:
    """Результат анализа сделки"""
    profit_loss: float
    profit_percent: float
    hold_time: timedelta
    entry_price: float
    exit_price: float
    quantity: float
    fees: float
    net_profit: float


class TradingAnalytics:
    """📊 Система аналитики для торгового бота"""

    def __init__(self, data_dir: str = 'data'):
        self.data_dir = data_dir
        self.logger = logging.getLogger(__name__)

        # Создаем директории для аналитики
        self.analytics_dir = os.path.join(data_dir, 'analytics')
        self.reports_dir = os.path.join(data_dir, 'reports')
        self.charts_dir = os.path.join(data_dir, 'charts')

        for dir_path in [self.analytics_dir, self.reports_dir, self.charts_dir]:
            os.makedirs(dir_path, exist_ok=True)

        self.logger.info("📊 Система аналитики инициализирована")

    def collect_runtime_stats(self, bot_instance) -> Dict:
        """📈 Сбор статистики во время работы бота"""
        try:
            stats = {
                'timestamp': datetime.now().isoformat(),
                'uptime_hours': (datetime.now().timestamp() - bot_instance.start_time) / 3600,
                'cycles_completed': getattr(bot_instance, 'cycle_count', 0),
                'total_trades': getattr(bot_instance, 'total_trades', 0),
                'profitable_trades': getattr(bot_instance, 'profitable_trades', 0),
                'error_count': getattr(bot_instance, 'error_count', 0),
                'consecutive_errors': getattr(bot_instance, 'consecutive_errors', 0),
                'avg_cycle_time': getattr(bot_instance, 'avg_cycle_time', 0),
                'last_successful_cycle': getattr(bot_instance, 'last_successful_cycle', 0),
            }

            # Добавляем риск-метрики
            if hasattr(bot_instance, 'risk_manager'):
                risk_metrics = bot_instance.risk_manager.get_risk_metrics()
                stats.update({
                    'daily_pnl': risk_metrics.get('daily_pnl', 0),
                    'max_drawdown': risk_metrics.get('max_drawdown', 0),
                    'active_stop_losses': risk_metrics.get('active_stop_losses', 0)
                })

            # Добавляем информацию о позициях
            if hasattr(bot_instance, 'position_manager'):
                positions = bot_instance.position_manager.get_position_summary()
                stats['positions'] = positions

            # Сохраняем статистику
            stats_file = os.path.join(self.analytics_dir, f"runtime_stats_{datetime.now().strftime('%Y%m%d')}.json")
            self._append_to_json_file(stats_file, stats)

            return stats

        except Exception as e:
            self.logger.error(f"❌ Ошибка сбора статистики: {e}")
            return {}

    def analyze_trades_performance(self, days_back: int = 14) -> Dict:
        """📈 Анализ производительности сделок"""
        try:
            # Загружаем историю сделок
            trades_file = os.path.join(self.data_dir, 'trades_history.json')
            if not os.path.exists(trades_file):
                self.logger.warning("📝 Файл истории сделок не найден")
                return {}

            with open(trades_file, 'r', encoding='utf-8') as f:
                trades_history = json.load(f)

            # Фильтруем по времени
            cutoff_date = datetime.now() - timedelta(days=days_back)
            recent_trades = [
                trade for trade in trades_history
                if datetime.fromisoformat(trade['timestamp']) > cutoff_date
            ]

            if not recent_trades:
                self.logger.info("📝 Нет сделок за указанный период")
                return {}

            # Анализируем сделки
            analysis = self._analyze_trade_pairs(recent_trades)

            # Генерируем отчет
            report = {
                'period_days': days_back,
                'total_trades': len(recent_trades),
                'analysis_date': datetime.now().isoformat(),
                'completed_round_trips': len(analysis),
                'performance_metrics': self._calculate_performance_metrics(analysis),
                'time_analysis': self._analyze_trading_times(recent_trades),
                'detailed_trades': [
                    {
                        'entry_time': trade.entry_time,
                        'exit_time': trade.exit_time,
                        'profit_percent': trade.profit_percent,
                        'hold_time_hours': trade.hold_time.total_seconds() / 3600,
                        'net_profit': trade.net_profit
                    } for trade in analysis
                ]
            }

            # Сохраняем отчет
            report_file = os.path.join(self.reports_dir,
                                       f"trades_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
            with open(report_file, 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=2, ensure_ascii=False)

            self.logger.info(f"📊 Анализ сделок сохранен: {report_file}")
            return report

        except Exception as e:
            self.logger.error(f"❌ Ошибка анализа сделок: {e}")
            return {}

    def _analyze_trade_pairs(self, trades: List[Dict]) -> List[TradeAnalysis]:
        """🔄 Анализ пар сделок (покупка-продажа)"""
        analysis = []
        open_positions = {}  # {currency: [buy_trades]}

        for trade in sorted(trades, key=lambda x: x['timestamp']):
            currency = trade.get('pair', 'UNKNOWN').split('_')[0]

            if trade['type'] == 'buy':
                # Открываем позицию
                if currency not in open_positions:
                    open_positions[currency] = []
                open_positions[currency].append(trade)

            elif trade['type'] == 'sell' and currency in open_positions:
                # Закрываем позицию (FIFO)
                if open_positions[currency]:
                    buy_trade = open_positions[currency].pop(0)

                    # Анализируем пару
                    trade_analysis = self._analyze_trade_pair(buy_trade, trade)
                    if trade_analysis:
                        analysis.append(trade_analysis)

        return analysis

    def _analyze_trade_pair(self, buy_trade: Dict, sell_trade: Dict) -> Optional[TradeAnalysis]:
        """🔍 Анализ пары покупка-продажа"""
        try:
            entry_time = datetime.fromisoformat(buy_trade['timestamp'])
            exit_time = datetime.fromisoformat(sell_trade['timestamp'])

            entry_price = float(buy_trade['price'])
            exit_price = float(sell_trade['price'])
            quantity = min(float(buy_trade['quantity']), float(sell_trade['quantity']))

            # Рассчитываем прибыль
            gross_profit = (exit_price - entry_price) * quantity
            fees = float(buy_trade.get('commission', 0)) + float(sell_trade.get('commission', 0))
            net_profit = gross_profit - fees

            profit_percent = (exit_price - entry_price) / entry_price * 100
            hold_time = exit_time - entry_time

            return TradeAnalysis(
                profit_loss=gross_profit,
                profit_percent=profit_percent,
                hold_time=hold_time,
                entry_price=entry_price,
                exit_price=exit_price,
                quantity=quantity,
                fees=fees,
                net_profit=net_profit,
                entry_time=entry_time.isoformat(),
                exit_time=exit_time.isoformat()
            )

        except Exception as e:
            self.logger.error(f"❌ Ошибка анализа пары сделок: {e}")
            return None

    def _calculate_performance_metrics(self, trades: List[TradeAnalysis]) -> Dict:
        """📊 Расчет метрик производительности"""
        if not trades:
            return {}

        profits = [trade.net_profit for trade in trades]
        profit_percents = [trade.profit_percent for trade in trades]
        hold_times = [trade.hold_time.total_seconds() / 3600 for trade in trades]

        profitable_trades = [p for p in profits if p > 0]
        losing_trades = [p for p in profits if p < 0]

        return {
            'total_net_profit': sum(profits),
            'average_profit_per_trade': np.mean(profits),
            'win_rate': len(profitable_trades) / len(trades) * 100,
            'profit_factor': sum(profitable_trades) / abs(sum(losing_trades)) if losing_trades else float('inf'),
            'average_profit_percent': np.mean(profit_percents),
            'max_profit': max(profits),
            'max_loss': min(profits),
            'average_hold_time_hours': np.mean(hold_times),
            'sharpe_ratio': self._calculate_sharpe_ratio(profit_percents),
            'max_consecutive_wins': self._max_consecutive_wins(profits),
            'max_consecutive_losses': self._max_consecutive_losses(profits),
            'volatility': np.std(profit_percents),
            'best_trade_percent': max(profit_percents),
            'worst_trade_percent': min(profit_percents)
        }

    def _calculate_sharpe_ratio(self, returns: List[float]) -> float:
        """📈 Расчет коэффициента Шарпа"""
        if not returns or len(returns) < 2:
            return 0

        mean_return = np.mean(returns)
        std_return = np.std(returns)

        return (mean_return / std_return) if std_return > 0 else 0

    def _max_consecutive_wins(self, profits: List[float]) -> int:
        """🏆 Максимальное количество побед подряд"""
        max_wins = current_wins = 0
        for profit in profits:
            if profit > 0:
                current_wins += 1
                max_wins = max(max_wins, current_wins)
            else:
                current_wins = 0
        return max_wins

    def _max_consecutive_losses(self, profits: List[float]) -> int:
        """📉 Максимальное количество потерь подряд"""
        max_losses = current_losses = 0
        for profit in profits:
            if profit < 0:
                current_losses += 1
                max_losses = max(max_losses, current_losses)
            else:
                current_losses = 0
        return max_losses

    def _analyze_trading_times(self, trades: List[Dict]) -> Dict:
        """⏰ Анализ времени торговли"""
        try:
            df = pd.DataFrame(trades)
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df['hour'] = df['timestamp'].dt.hour
            df['day_of_week'] = df['timestamp'].dt.dayofweek
            df['is_profitable'] = df.apply(lambda x: x.get('net_profit', 0) > 0, axis=1)

            # Анализ по часам
            hourly_stats = df.groupby('hour').agg({
                'type': 'count',
                'is_profitable': ['sum', 'mean']
            }).round(2)

            # Анализ по дням недели
            daily_stats = df.groupby('day_of_week').agg({
                'type': 'count',
                'is_profitable': ['sum', 'mean']
            }).round(2)

            return {
                'most_active_hours': hourly_stats.nlargest(3, ('type', 'count')).index.tolist(),
                'most_profitable_hours': hourly_stats.nlargest(3, ('is_profitable', 'mean')).index.tolist(),
                'most_active_days': daily_stats.nlargest(3, ('type', 'count')).index.tolist(),
                'hourly_distribution': hourly_stats.to_dict(),
                'daily_distribution': daily_stats.to_dict()
            }

        except Exception as e:
            self.logger.error(f"❌ Ошибка анализа времени: {e}")
            return {}

    def generate_daily_report(self) -> Dict:
        """📋 Генерация дневного отчета"""
        try:
            # Собираем статистику за сегодня
            today = datetime.now().date()
            stats_file = os.path.join(self.analytics_dir, f"runtime_stats_{today.strftime('%Y%m%d')}.json")

            daily_stats = []
            if os.path.exists(stats_file):
                with open(stats_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        try:
                            daily_stats.append(json.loads(line.strip()))
                        except:
                            continue

            if not daily_stats:
                return {'status': 'no_data', 'date': today.isoformat()}

            # Анализируем дневную активность
            latest_stats = daily_stats[-1]
            first_stats = daily_stats[0] if len(daily_stats) > 1 else latest_stats

            report = {
                'date': today.isoformat(),
                'uptime_hours': latest_stats.get('uptime_hours', 0),
                'total_cycles': latest_stats.get('cycles_completed', 0),
                'trades_made': latest_stats.get('total_trades', 0) - first_stats.get('total_trades', 0),
                'profitable_trades': latest_stats.get('profitable_trades', 0) - first_stats.get('profitable_trades', 0),
                'daily_pnl': latest_stats.get('daily_pnl', 0),
                'errors_today': latest_stats.get('error_count', 0) - first_stats.get('error_count', 0),
                'avg_cycle_time': latest_stats.get('avg_cycle_time', 0),
                'positions': latest_stats.get('positions', {}),
                'max_drawdown': latest_stats.get('max_drawdown', 0),
                'active_stop_losses': latest_stats.get('active_stop_losses', 0)
            }

            # Рассчитываем производительность
            if report['trades_made'] > 0:
                report['win_rate'] = (report['profitable_trades'] / report['trades_made']) * 100
                report['avg_profit_per_trade'] = report['daily_pnl'] / report['trades_made']
            else:
                report['win_rate'] = 0
                report['avg_profit_per_trade'] = 0

            # Сохраняем дневной отчет
            report_file = os.path.join(self.reports_dir, f"daily_report_{today.strftime('%Y%m%d')}.json")
            with open(report_file, 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=2, ensure_ascii=False)

            self.logger.info(f"📋 Дневной отчет сохранен: {report_file}")
            return report

        except Exception as e:
            self.logger.error(f"❌ Ошибка генерации дневного отчета: {e}")
            return {'status': 'error', 'error': str(e)}

    def create_performance_charts(self, days_back: int = 14):
        """📊 Создание графиков производительности"""
        try:
            # Анализ сделок
            analysis = self.analyze_trades_performance(days_back)
            if not analysis or not analysis.get('detailed_trades'):
                self.logger.warning("📊 Недостаточно данных для графиков")
                return

            # Настройка стиля
            plt.style.use('seaborn-v0_8')
            fig, axes = plt.subplots(2, 2, figsize=(15, 10))
            fig.suptitle(f'Анализ торговли за {days_back} дней', fontsize=16)

            trades_df = pd.DataFrame(analysis['detailed_trades'])
            trades_df['entry_time'] = pd.to_datetime(trades_df['entry_time'])

            # График 1: Кумулятивная прибыль
            trades_df['cumulative_profit'] = trades_df['net_profit'].cumsum()
            axes[0, 0].plot(trades_df['entry_time'], trades_df['cumulative_profit'], linewidth=2)
            axes[0, 0].set_title('Кумулятивная прибыль')
            axes[0, 0].set_ylabel('Прибыль (EUR)')
            axes[0, 0].grid(True, alpha=0.3)

            # График 2: Распределение прибыли
            axes[0, 1].hist(trades_df['profit_percent'], bins=20, alpha=0.7, edgecolor='black')
            axes[0, 1].set_title('Распределение прибыли (%)')
            axes[0, 1].set_xlabel('Прибыль (%)')
            axes[0, 1].set_ylabel('Количество сделок')
            axes[0, 1].grid(True, alpha=0.3)

            # График 3: Время удержания позиций
            axes[1, 0].scatter(trades_df['hold_time_hours'], trades_df['profit_percent'], alpha=0.6)
            axes[1, 0].set_title('Время удержания vs Прибыль')
            axes[1, 0].set_xlabel('Время удержания (часы)')
            axes[1, 0].set_ylabel('Прибыль (%)')
            axes[1, 0].grid(True, alpha=0.3)

            # График 4: Прибыль по времени суток
            trades_df['hour'] = trades_df['entry_time'].dt.hour
            hourly_profit = trades_df.groupby('hour')['profit_percent'].mean()
            axes[1, 1].bar(hourly_profit.index, hourly_profit.values)
            axes[1, 1].set_title('Средняя прибыль по часам')
            axes[1, 1].set_xlabel('Час дня')
            axes[1, 1].set_ylabel('Средняя прибыль (%)')
            axes[1, 1].grid(True, alpha=0.3)

            plt.tight_layout()

            # Сохраняем график
            chart_file = os.path.join(self.charts_dir,
                                      f"performance_chart_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
            plt.savefig(chart_file, dpi=300, bbox_inches='tight')
            plt.close()

            self.logger.info(f"📊 График сохранен: {chart_file}")

        except Exception as e:
            self.logger.error(f"❌ Ошибка создания графиков: {e}")

    def _append_to_json_file(self, filename: str, data: Dict):
        """📝 Добавление данных в JSON файл"""
        try:
            with open(filename, 'a', encoding='utf-8') as f:
                f.write(json.dumps(data, ensure_ascii=False) + '\n')
        except Exception as e:
            self.logger.error(f"❌ Ошибка записи в файл {filename}: {e}")

    def get_summary_stats(self, days_back: int = 7) -> Dict:
        """📊 Получение сводной статистики"""
        try:
            # Анализируем сделки
            trades_analysis = self.analyze_trades_performance(days_back)

            # Дневной отчет
            daily_report = self.generate_daily_report()

            # Формируем сводку
            summary = {
                'period_days': days_back,
                'generated_at': datetime.now().isoformat(),
                'daily_summary': daily_report,
                'trades_performance': trades_analysis.get('performance_metrics', {}),
                'time_analysis': trades_analysis.get('time_analysis', {}),
                'recommendations': self._generate_recommendations(trades_analysis)
            }

            return summary

        except Exception as e:
            self.logger.error(f"❌ Ошибка получения сводной статистики: {e}")
            return {}

    def _generate_recommendations(self, analysis: Dict) -> List[str]:
        """💡 Генерация рекомендаций на основе анализа"""
        recommendations = []

        if not analysis or not analysis.get('performance_metrics'):
            return ["Недостаточно данных для анализа"]

        metrics = analysis['performance_metrics']

        # Анализ успешности
        win_rate = metrics.get('win_rate', 0)
        if win_rate < 50:
            recommendations.append(f"⚠️ Низкая успешность ({win_rate:.1f}%) - пересмотреть стратегию входа")
        elif win_rate > 70:
            recommendations.append(f"✅ Отличная успешность ({win_rate:.1f}%) - стратегия работает хорошо")

        # Анализ прибыли
        avg_profit = metrics.get('average_profit_per_trade', 0)
        if avg_profit < 0:
            recommendations.append("🚨 Средняя сделка убыточна - срочно пересмотреть параметры")
        elif avg_profit > 0.01:
            recommendations.append("💰 Хорошая прибыльность сделок - можно увеличить размер позиций")

        # Анализ времени удержания
        avg_hold_time = metrics.get('average_hold_time_hours', 0)
        if avg_hold_time > 24:
            recommendations.append("⏰ Долгое время удержания - рассмотреть более активную стратегию")
        elif avg_hold_time < 1:
            recommendations.append("⚡ Очень быстрые сделки - возможно слишком агрессивные настройки")

        # Анализ волатильности
        volatility = metrics.get('volatility', 0)
        if volatility > 5:
            recommendations.append("🌊 Высокая волатильность результатов - улучшить риск-менеджмент")

        return recommendations if recommendations else ["📊 Статистика выглядит стабильно"]


# Интеграция с основным ботом
def integrate_analytics_to_bot():
    """🔧 Интеграция аналитики в основной бот"""
    integration_code = '''
    # Добавить в bot.py в класс TradingBot:

    def __init__(self):
        # ... существующий код ...

        # Добавляем систему аналитики
        from analytics_system import TradingAnalytics
        self.analytics = TradingAnalytics()

        # Счетчики для аналитики
        self.last_analytics_update = time.time()
        self.analytics_interval = 300  # 5 минут

    def execute_trade_cycle(self):
        # ... существующий код цикла ...

        # Периодический сбор статистики
        current_time = time.time()
        if current_time - self.last_analytics_update > self.analytics_interval:
            self.analytics.collect_runtime_stats(self)
            self.last_analytics_update = current_time

            # Каждый час создаем графики
            if self.cycle_count % 450 == 0:  # 450 циклов * 8 сек ≈ 1 час
                self.analytics.create_performance_charts(days_back=7)

    def shutdown(self):
        # ... существующий код ...

        # Финальный отчет при завершении
        try:
            final_stats = self.analytics.get_summary_stats(days_back=14)
            self.logger.info("📊 ФИНАЛЬНАЯ АНАЛИТИКА:")

            if 'trades_performance' in final_stats:
                metrics = final_stats['trades_performance']
                self.logger.info(f"   💰 Общая прибыль: {metrics.get('total_net_profit', 0):.4f} EUR")
                self.logger.info(f"   📊 Успешность: {metrics.get('win_rate', 0):.1f}%")
                self.logger.info(f"   📈 Коэффициент Шарпа: {metrics.get('sharpe_ratio', 0):.2f}")

            for rec in final_stats.get('recommendations', []):
                self.logger.info(f"   💡 {rec}")

        except Exception as e:
            self.logger.error(f"❌ Ошибка финальной аналитики: {e}")
    '''

    return integration_code


if __name__ == "__main__":
    # Пример использования
    analytics = TradingAnalytics()

    # Анализ за последние 7 дней
    summary = analytics.get_summary_stats(days_back=7)
    print("📊 Сводная статистика:")
    print(json.dumps(summary, indent=2, ensure_ascii=False))

    # Создание графиков
    analytics.create_performance_charts(days_back=14)

    print("\n🔧 Для интеграции с ботом используйте:")
    print(integrate_analytics_to_bot())
