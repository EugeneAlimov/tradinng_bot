# dca_limiter.py
"""🛡️ Ограничитель DCA покупок для предотвращения бесконечного усреднения"""

import time
import logging
from datetime import datetime
from typing import Dict, Any, Tuple


class DCALimiter:
    """🛡️ Умный ограничитель DCA покупок"""
    
    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # 🛡️ Лимиты DCA
        self.MAX_DCA_PER_DAY = getattr(config, 'DCA_MAX_PER_DAY', 5)
        self.MAX_CONSECUTIVE_DCA = getattr(config, 'DCA_MAX_CONSECUTIVE', 3)
        self.MIN_DCA_INTERVAL_MINUTES = getattr(config, 'DCA_MIN_INTERVAL_MINUTES', 30)
        self.LOSS_BLOCK_THRESHOLD = getattr(config, 'DCA_LOSS_BLOCK_THRESHOLD', 0.08)
        
        # 📊 Отслеживание DCA
        self.daily_dca_count = 0
        self.consecutive_dca_count = 0
        self.last_dca_date = None
        self.last_dca_time = 0
        self.last_successful_sell_time = 0
        
        # 🚫 Состояние блокировки
        self.is_blocked = False
        self.block_reason = ""
        self.block_until = 0
        
        self.logger.info("🛡️ DCALimiter инициализирован")
        self.logger.info(f"   📊 Макс DCA в день: {self.MAX_DCA_PER_DAY}")
        self.logger.info(f"   🔗 Макс подряд: {self.MAX_CONSECUTIVE_DCA}")
    
    def can_execute_dca(self, current_price: float, position_data: Dict[str, Any], 
                       balance: float) -> Tuple[bool, str]:
        """🛡️ Основная проверка возможности выполнения DCA"""
        
        try:
            # Сброс дневных счетчиков
            self._reset_daily_counters_if_needed()
            
            # Проверка временной блокировки
            if self._is_temporarily_blocked():
                return False, f"Временная блокировка: {self.block_reason}"
            
            # 1. Проверка дневного лимита
            if self.daily_dca_count >= self.MAX_DCA_PER_DAY:
                self._set_block("Достигнут дневной лимит DCA", 24*3600)
                return False, f"Дневной лимит: {self.daily_dca_count}/{self.MAX_DCA_PER_DAY}"
            
            # 2. Проверка последовательных DCA
            if self.consecutive_dca_count >= self.MAX_CONSECUTIVE_DCA:
                self._set_block("Слишком много DCA подряд", 4*3600)
                return False, f"Лимит подряд: {self.consecutive_dca_count}/{self.MAX_CONSECUTIVE_DCA}"
            
            # 3. Проверка интервала между DCA
            if self._get_minutes_since_last_dca() < self.MIN_DCA_INTERVAL_MINUTES:
                remaining_minutes = self.MIN_DCA_INTERVAL_MINUTES - self._get_minutes_since_last_dca()
                return False, f"Кулдаун: {remaining_minutes:.0f} мин"
            
            # 4. Проверка убытка позиции
            if position_data and position_data.get('quantity', 0) > 0:
                avg_price = position_data.get('avg_price', 0)
                if avg_price > 0:
                    loss_percentage = (avg_price - current_price) / avg_price
                    if loss_percentage > self.LOSS_BLOCK_THRESHOLD:
                        self._set_block(f"Убыток {loss_percentage*100:.1f}% превышает порог", 2*3600)
                        return False, f"Блокировка по убытку: {loss_percentage*100:.1f}%"
            
            return True, "Все проверки пройдены"
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка проверки DCA лимитов: {e}")
            return False, f"Ошибка проверки: {str(e)}"
    
    def register_dca_success(self, price: float, quantity: float) -> None:
        """📊 Регистрация успешной DCA"""
        
        self.daily_dca_count += 1
        self.consecutive_dca_count += 1
        self.last_dca_time = time.time()
        
        self.logger.info(f"📊 DCA зарегистрирована:")
        self.logger.info(f"   📊 Дневной счетчик: {self.daily_dca_count}")
        self.logger.info(f"   🔗 Подряд: {self.consecutive_dca_count}")
    
    def register_successful_sell(self) -> None:
        """✅ Регистрация успешной продажи - сбрасывает счетчики"""
        
        self.consecutive_dca_count = 0
        self.last_successful_sell_time = time.time()
        
        # Снимаем блокировку если она была по убытку
        if self.is_blocked and "убыток" in self.block_reason.lower():
            self._clear_block()
        
        self.logger.info(f"✅ Успешная продажа: DCA счетчик подряд сброшен")
    
    def _reset_daily_counters_if_needed(self) -> None:
        """🔄 Сброс дневных счетчиков при смене дня"""
        
        today = datetime.now().date()
        if self.last_dca_date != today:
            old_count = self.daily_dca_count
            self.daily_dca_count = 0
            self.last_dca_date = today
            
            if old_count > 0:
                self.logger.info(f"🔄 Дневной счетчик DCA сброшен: {old_count} -> 0")
    
    def _get_minutes_since_last_dca(self) -> float:
        """⏰ Получение минут с последней DCA"""
        if self.last_dca_time == 0:
            return float('inf')
        return (time.time() - self.last_dca_time) / 60
    
    def _set_block(self, reason: str, duration_seconds: int) -> None:
        """🚫 Установка временной блокировки"""
        
        self.is_blocked = True
        self.block_reason = reason
        self.block_until = time.time() + duration_seconds
        
        self.logger.warning(f"🚫 DCA ЗАБЛОКИРОВАНА: {reason}")
    
    def _clear_block(self) -> None:
        """✅ Снятие блокировки"""
        
        if self.is_blocked:
            self.is_blocked = False
            self.block_reason = ""
            self.block_until = 0
            self.logger.info(f"✅ Блокировка DCA снята")
    
    def _is_temporarily_blocked(self) -> bool:
        """🚫 Проверка временной блокировки"""
        
        if not self.is_blocked:
            return False
        
        if time.time() >= self.block_until:
            self._clear_block()
            return False
        
        return True
    
    def get_dca_status(self) -> Dict[str, Any]:
        """📊 Получение статуса DCA лимитера"""
        
        self._reset_daily_counters_if_needed()
        
        return {
            'system_active': True,
            'is_blocked': self.is_blocked,
            'block_reason': self.block_reason,
            'daily_dca_count': self.daily_dca_count,
            'consecutive_dca_count': self.consecutive_dca_count,
            'max_daily_dca': self.MAX_DCA_PER_DAY,
            'max_consecutive_dca': self.MAX_CONSECUTIVE_DCA,
            'minutes_since_last_dca': round(self._get_minutes_since_last_dca(), 1)
        }
