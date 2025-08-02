import logging
import time
from typing import Tuple, Dict, Any
from datetime import datetime, timedelta


class RiskManager:
    """🛡️ Менеджер рисков"""
    
    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # Статистика рисков
        self.daily_losses = 0.0
        self.last_reset_date = datetime.now().date()
        self.total_trades_today = 0
        self.error_count = 0
        
        self.logger.info("🛡️ Риск-менеджер инициализирован")
    
    def can_open_position(self, position_size: float, balance: float) -> bool:
        """✅ Проверка возможности открытия позиции"""
        
        try:
            # Проверка размера позиции
            if position_size > balance * self.config.POSITION_SIZE:
                self.logger.warning(f"⚠️ Размер позиции {position_size:.2f} превышает лимит")
                return False
            
            # Проверка минимального баланса
            if balance < 5.0:  # Минимум 5 EUR
                self.logger.warning(f"⚠️ Недостаточный баланс: {balance:.2f} EUR")
                return False
            
            # Проверка дневных потерь
            self._reset_daily_stats_if_needed()
            
            if self.daily_losses > balance * self.config.STOP_LOSS_PERCENT:
                self.logger.warning(f"⚠️ Достигнут лимит дневных потерь: {self.daily_losses:.2f} EUR")
                return False
            
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка проверки позиции: {e}")
            return False
    
    def emergency_stop_check(self, balance: float) -> Tuple[bool, str]:
        """🚨 Проверка условий экстренной остановки"""
        
        try:
            # Сброс дневной статистики
            self._reset_daily_stats_if_needed()
            
            # Проверка дневных потерь
            max_daily_loss = balance * self.config.STOP_LOSS_PERCENT
            if self.daily_losses >= max_daily_loss:
                return True, f"Дневные потери {self.daily_losses:.2f} >= лимита {max_daily_loss:.2f}"
            
            # Проверка количества ошибок
            if self.error_count >= 10:
                return True, f"Слишком много ошибок: {self.error_count}"
            
            # Проверка минимального баланса
            if balance < 1.0:
                return True, f"Критически низкий баланс: {balance:.2f} EUR"
            
            return False, "Все проверки пройдены"
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка проверки экстренной остановки: {e}")
            return True, f"Ошибка проверки: {str(e)}"
    
    def register_trade_result(self, profit_loss: float):
        """📊 Регистрация результата сделки"""
        
        try:
            self._reset_daily_stats_if_needed()
            
            self.total_trades_today += 1
            
            if profit_loss < 0:
                self.daily_losses += abs(profit_loss)
                self.logger.info(f"📉 Зарегистрирован убыток: {profit_loss:.4f} EUR")
                self.logger.info(f"   Общие потери за день: {self.daily_losses:.4f} EUR")
            else:
                self.logger.info(f"📈 Зарегистрирована прибыль: {profit_loss:.4f} EUR")
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка регистрации сделки: {e}")
    
    def register_error(self):
        """❌ Регистрация ошибки"""
        self.error_count += 1
        
        if self.error_count >= 5:
            self.logger.warning(f"⚠️ Количество ошибок: {self.error_count}")
    
    def reset_error_count(self):
        """✅ Сброс счетчика ошибок"""
        self.error_count = 0
    
    def _reset_daily_stats_if_needed(self):
        """🔄 Сброс дневной статистики при смене дня"""
        today = datetime.now().date()
        
        if today != self.last_reset_date:
            self.daily_losses = 0.0
            self.total_trades_today = 0
            self.last_reset_date = today
            self.logger.info("🔄 Дневная статистика сброшена")
    
    def get_risk_metrics(self) -> Dict[str, Any]:
        """📊 Получение метрик рисков"""
        self._reset_daily_stats_if_needed()
        
        return {
            'daily_losses': self.daily_losses,
            'total_trades_today': self.total_trades_today,
            'error_count': self.error_count,
            'last_reset_date': self.last_reset_date.isoformat()
        }
