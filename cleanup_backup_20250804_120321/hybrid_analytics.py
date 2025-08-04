import json
import time
import os
from datetime import datetime
from typing import Dict, Any
import logging

class HybridAnalytics:
    """📊 Гибридная система аналитики"""

    def __init__(self, data_dir: str = 'data'):
        self.data_dir = data_dir
        self.analytics_dir = os.path.join(data_dir, 'analytics')
        self.logger = logging.getLogger(__name__)

        # Создаем директории
        os.makedirs(self.analytics_dir, exist_ok=True)

        # Данные сессии
        self.session_stats = {
            'start_time': time.time(),
            'cycles_completed': 0,
            'trades_executed': 0,
            'profitable_trades': 0,
            'total_pnl': 0.0,
            'max_balance': 0.0,
            'max_drawdown': 0.0,
            'emergency_exits': 0,
            'dca_blocks': 0,
            'trend_blocks': 0
        }

        # Расширенная аналитика
        self.advanced_analytics = None
        self._try_initialize_advanced()

        self.logger.info("📊 HybridAnalytics инициализирована")

    def _try_initialize_advanced(self):
        """🔧 Попытка инициализации расширенной аналитики"""
        try:
            from analytics_system import TradingAnalytics
            self.advanced_analytics = TradingAnalytics()
            self.logger.info("📈 Расширенная аналитика подключена")
        except ImportError:
            self.logger.info("📊 Используется только простая аналитика")

    def record_trade(self, trade_type: str, quantity: float, price: float, 
                    pair: str, strategy: str, profit_loss: float = 0.0) -> None:
        """📊 Запись сделки"""

        self.session_stats['trades_executed'] += 1
        self.session_stats['total_pnl'] += profit_loss

        if profit_loss > 0:
            self.session_stats['profitable_trades'] += 1

        # Расширенная аналитика (если доступна)
        if self.advanced_analytics:
            try:
                self.advanced_analytics.record_trade(
                    trade_type, quantity, price, pair, strategy, profit_loss
                )
            except Exception as e:
                self.logger.error(f"❌ Ошибка расширенной аналитики: {e}")

        self.logger.info(f"📊 Сделка записана: {trade_type} {quantity:.6f} {pair}")

    def update_balance(self, current_balance: float) -> None:
        """💰 Обновление баланса"""

        if current_balance > self.session_stats['max_balance']:
            self.session_stats['max_balance'] = current_balance

        # Рассчитываем просадку
        if self.session_stats['max_balance'] > 0:
            drawdown = (self.session_stats['max_balance'] - current_balance) / self.session_stats['max_balance']
            self.session_stats['max_drawdown'] = max(self.session_stats['max_drawdown'], drawdown)

    def update_cycle_stats(self, cycle_result: Dict[str, Any]) -> None:
        """🔄 Обновление статистики цикла"""

        self.session_stats['cycles_completed'] += 1

        if cycle_result.get('emergency_exit'):
            self.session_stats['emergency_exits'] += 1

        if cycle_result.get('dca_blocked'):
            self.session_stats['dca_blocks'] += 1

        if cycle_result.get('trend_blocked'):
            self.session_stats['trend_blocks'] += 1

    def get_session_summary(self) -> Dict[str, Any]:
        """📋 Получение сводки сессии"""

        uptime_hours = (time.time() - self.session_stats['start_time']) / 3600
        trades = self.session_stats['trades_executed']
        profitable = self.session_stats['profitable_trades']
        success_rate = (profitable / trades * 100) if trades > 0 else 0

        return {
            'uptime_hours': round(uptime_hours, 2),
            'cycles_completed': self.session_stats['cycles_completed'],
            'trades_executed': trades,
            'profitable_trades': profitable,
            'success_rate_percent': round(success_rate, 1),
            'total_pnl': round(self.session_stats['total_pnl'], 4),
            'max_drawdown_percent': round(self.session_stats['max_drawdown'] * 100, 2),
            'emergency_exits': self.session_stats['emergency_exits'],
            'dca_blocks': self.session_stats['dca_blocks'],
            'trend_blocks': self.session_stats['trend_blocks']
        }

    def log_performance_summary(self) -> None:
        """📊 Логирование сводки производительности"""

        summary = self.get_session_summary()

        self.logger.info("📊 ГИБРИДНАЯ СВОДКА ПРОИЗВОДИТЕЛЬНОСТИ:")
        self.logger.info(f"   ⏱️ Время работы: {summary['uptime_hours']} часов")
        self.logger.info(f"   🔄 Циклов: {summary['cycles_completed']}")
        self.logger.info(f"   📈 Сделок: {summary['trades_executed']}")
        self.logger.info(f"   ✅ Успешных: {summary['profitable_trades']}")
        self.logger.info(f"   📊 Успешность: {summary['success_rate_percent']}%")
        self.logger.info(f"   💰 P&L: {summary['total_pnl']} EUR")
        self.logger.info(f"   🚨 Аварийные выходы: {summary['emergency_exits']}")
        self.logger.info(f"   🛡️ DCA блокировки: {summary['dca_blocks']}")
        self.logger.info(f"   🧠 Trend блокировки: {summary['trend_blocks']}")

# Для обратной совместимости
SimpleAnalytics = HybridAnalytics

if __name__ == "__main__":
    analytics = HybridAnalytics()
    print("📊 Гибридная аналитика инициализирована")
