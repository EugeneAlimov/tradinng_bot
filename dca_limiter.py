# dca_limiter.py
"""
🛡️ ПАТЧ 2: Ограничитель DCA покупок
Предотвращает бесконечное усреднение убыточных позиций
"""

import time
import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta


class DCALimiter:
    """🛡️ Умный ограничитель DCA операций"""
    
    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # 🛡️ Лимиты DCA
        self.MAX_CONSECUTIVE_DCA = 3        # Максимум 3 DCA подряд
        self.MAX_DCA_PER_DAY = 5           # Максимум 5 DCA в день
        self.MIN_INTERVAL_BETWEEN_DCA = 1800  # 30 минут между DCA
        self.MAX_POSITION_SIZE_WITH_DCA = 0.65  # 65% депозита максимум
        
        # 📚 История DCA операций
        self.dca_history = []
        self.last_dca_time = 0
        
        # 🚨 Блокировка при плохих условиях
        self.blocked_until = 0
        self.block_reason = ""
        
        self.logger.info("🛡️ DCALimiter инициализирован")
        self.logger.info(f"   📊 Максимум подряд: {self.MAX_CONSECUTIVE_DCA}")
        self.logger.info(f"   📅 Максимум в день: {self.MAX_DCA_PER_DAY}")
        self.logger.info(f"   ⏰ Интервал: {self.MIN_INTERVAL_BETWEEN_DCA//60} минут")
    
    def can_execute_dca(self, current_price: float, position_data: Dict[str, Any],
                       balance_info: Dict[str, Any]) -> Tuple[bool, str]:
        """🛡️ Проверка возможности выполнения DCA"""
        
        # 🚨 Проверка временной блокировки
        if time.time() < self.blocked_until:
            remaining = (self.blocked_until - time.time()) / 60
            return False, f"DCA заблокирован: {self.block_reason} (осталось {remaining:.0f}мин)"
        
        # ⏰ Проверка минимального интервала
        time_since_last = time.time() - self.last_dca_time
        if time_since_last < self.MIN_INTERVAL_BETWEEN_DCA:
            remaining = (self.MIN_INTERVAL_BETWEEN_DCA - time_since_last) / 60
            return False, f"Слишком рано для DCA (осталось {remaining:.0f}мин)"
        
        # 📊 Проверка количества подряд идущих DCA
        consecutive_count = self._count_consecutive_dca()
        if consecutive_count >= self.MAX_CONSECUTIVE_DCA:
            return False, f"Достигнут лимит DCA подряд: {consecutive_count}/{self.MAX_CONSECUTIVE_DCA}"
        
        # 📅 Проверка дневного лимита
        daily_count = self._count_daily_dca()
        if daily_count >= self.MAX_DCA_PER_DAY:
            return False, f"Достигнут дневной лимит DCA: {daily_count}/{self.MAX_DCA_PER_DAY}"
        
        # 💰 Проверка размера позиции
        if position_data and 'quantity' in position_data:
            current_position_value = position_data['quantity'] * current_price
            total_balance = balance_info.get('total_value', 0)
            
            if total_balance > 0:
                position_percentage = current_position_value / total_balance
                if position_percentage >= self.MAX_POSITION_SIZE_WITH_DCA:
                    return False, f"Позиция слишком большая: {position_percentage*100:.1f}% >= {self.MAX_POSITION_SIZE_WITH_DCA*100:.0f}%"
        
        # 📈 Проверка тренда (если есть убыток > 8%, блокируем DCA)
        if position_data and 'avg_price' in position_data:
            avg_price = position_data['avg_price']
            loss_percent = (current_price - avg_price) / avg_price
            
            if loss_percent <= -0.08:  # Убыток больше 8%
                # Временная блокировка на 2 часа
                self._block_dca_temporarily(2 * 3600, f"Большой убыток: {loss_percent*100:.1f}%")
                return False, f"DCA заблокирован из-за большого убытка: {loss_percent*100:.1f}%"
        
        return True, "DCA разрешена"
    
    def register_dca_execution(self, price: float, quantity: float, 
                              result: str = "success") -> None:
        """📝 Регистрация выполненной DCA операции"""
        
        dca_record = {
            'timestamp': time.time(),
            'price': price,
            'quantity': quantity,
            'result': result,
            'datetime': datetime.now().isoformat()
        }
        
        self.dca_history.append(dca_record)
        self.last_dca_time = time.time()
        
        # Чистим старые записи (старше 7 дней)
        cutoff_time = time.time() - (7 * 24 * 3600)
        self.dca_history = [r for r in self.dca_history if r['timestamp'] > cutoff_time]
        
        self.logger.info(f"📝 DCA зарегистрирована: {quantity:.6f} по {price:.8f}")
        self.logger.info(f"   📊 Подряд: {self._count_consecutive_dca()}/{self.MAX_CONSECUTIVE_DCA}")
        self.logger.info(f"   📅 За день: {self._count_daily_dca()}/{self.MAX_DCA_PER_DAY}")
    
    def register_successful_sell(self) -> None:
        """✅ Регистрация успешной продажи (сбрасывает счетчики)"""
        
        # Добавляем маркер успешной продажи
        sell_record = {
            'timestamp': time.time(),
            'type': 'successful_sell',
            'datetime': datetime.now().isoformat()
        }
        
        self.dca_history.append(sell_record)
        
        # Снимаем временные блокировки при успешной продаже
        if time.time() < self.blocked_until:
            self.logger.info("✅ Блокировка DCA снята из-за успешной продажи")
            self.blocked_until = 0
            self.block_reason = ""
        
        self.logger.info("✅ Успешная продажа зарегистрирована, счетчики DCA сброшены")
    
    def _count_consecutive_dca(self) -> int:
        """📊 Подсчет подряд идущих DCA операций"""
        
        if not self.dca_history:
            return 0
        
        consecutive = 0
        # Идем с конца истории
        for record in reversed(self.dca_history):
            if record.get('type') == 'successful_sell':
                break  # Прерываем на успешной продаже
            elif 'quantity' in record and record.get('result') == 'success':
                consecutive += 1
            else:
                break
        
        return consecutive
    
    def _count_daily_dca(self) -> int:
        """📅 Подсчет DCA операций за сегодня"""
        
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_timestamp = today_start.timestamp()
        
        daily_count = 0
        for record in self.dca_history:
            if (record['timestamp'] >= today_timestamp and 
                'quantity' in record and 
                record.get('result') == 'success'):
                daily_count += 1
        
        return daily_count
    
    def _block_dca_temporarily(self, duration_seconds: int, reason: str) -> None:
        """🚨 Временная блокировка DCA"""
        
        self.blocked_until = time.time() + duration_seconds
        self.block_reason = reason
        
        hours = duration_seconds / 3600
        self.logger.warning(f"🚨 DCA заблокирована на {hours:.1f}ч: {reason}")
    
    def get_dca_status(self) -> Dict[str, Any]:
        """📊 Текущий статус DCA лимитера"""
        
        status = {
            'consecutive_dca': self._count_consecutive_dca(),
            'max_consecutive': self.MAX_CONSECUTIVE_DCA,
            'daily_dca': self._count_daily_dca(),
            'max_daily': self.MAX_DCA_PER_DAY,
            'is_blocked': time.time() < self.blocked_until,
            'block_reason': self.block_reason if time.time() < self.blocked_until else "",
            'time_since_last_dca': time.time() - self.last_dca_time,
            'min_interval': self.MIN_INTERVAL_BETWEEN_DCA
        }
        
        if status['is_blocked']:
            status['block_remaining_minutes'] = (self.blocked_until - time.time()) / 60
        
        return status