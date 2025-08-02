# simple_analytics.py
"""📊 Упрощенная система аналитики для торгового бота"""

import json
import time
import os
from datetime import datetime
from typing import Dict, Any
import logging


class SimpleAnalytics:
    """📊 Простая аналитика без сложных зависимостей"""
    
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
            'dca_blocks': 0
        }
        
        self.logger.info("📊 SimpleAnalytics инициализирована")
    
    def record_trade(self, trade_type: str, quantity: float, price: float, 
                    pair: str, strategy: str, profit_loss: float = 0.0) -> None:
        """📊 Запись сделки"""
        
        self.session_stats['trades_executed'] += 1
        self.session_stats['total_pnl'] += profit_loss
        
        if profit_loss > 0:
            self.session_stats['profitable_trades'] += 1
        
        self.logger.info(f"📊 Сделка записана: {trade_type} {quantity:.6f} {pair}")
        if profit_loss != 0:
            self.logger.info(f"   💰 P&L: {profit_loss:.4f} EUR")
    
    def update_balance(self, current_balance: float) -> None:
        """💰 Обновление баланса для расчета просадки"""
        
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
    
    def get_session_summary(self) -> Dict[str, Any]:
        """📋 Получение сводки текущей сессии"""
        
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
            'trades_per_hour': round(trades / max(uptime_hours, 0.1), 2)
        }
    
    def log_performance_summary(self) -> None:
        """📊 Логирование сводки производительности"""
        
        summary = self.get_session_summary()
        
        self.logger.info("📊 СВОДКА ПРОИЗВОДИТЕЛЬНОСТИ:")
        self.logger.info(f"   ⏱️ Время работы: {summary['uptime_hours']} часов")
        self.logger.info(f"   🔄 Циклов: {summary['cycles_completed']}")
        self.logger.info(f"   📈 Сделок: {summary['trades_executed']}")
        self.logger.info(f"   ✅ Успешных: {summary['profitable_trades']}")
        self.logger.info(f"   📊 Успешность: {summary['success_rate_percent']}%")
        self.logger.info(f"   💰 P&L: {summary['total_pnl']} EUR")
        self.logger.info(f"   📉 Макс просадка: {summary['max_drawdown_percent']}%")
        self.logger.info(f"   🚨 Аварийные выходы: {summary['emergency_exits']}")
        self.logger.info(f"   🛡️ DCA блокировки: {summary['dca_blocks']}")
