import statistics
from typing import List, Tuple, Optional
from datetime import datetime, timedelta
from collections import deque
import time
import logging
from config import TradingConfig


class RiskManager:
    def __init__(self, config: TradingConfig):
        self.config = config
        self.logger = logging.getLogger(__name__)

        # 📊 Дневная статистика
        self.daily_pnl = 0.0
        self.trades_today = deque(maxlen=100)  # Ограничиваем размер
        self.last_reset_date = datetime.now().date()

        # 🛡️ Активные стоп-лоссы
        self.active_stop_losses = {}  # {currency: {'price': float, 'quantity': float}}

        # 📈 Статистика торговли
        self.total_trades = 0
        self.profitable_trades = 0
        self.total_profit = 0.0
        self.max_drawdown = 0.0
        self.peak_balance = 0.0

        self.logger.info("🛡️ Риск-менеджер инициализирован")

    def maybe_reset_daily_pnl(self):
        """🌅 Сброс дневной статистики в полночь"""
        current_date = datetime.now().date()

        if current_date != self.last_reset_date:
            self.logger.info(f"🌅 Новый день: сброс дневной статистики")
            self.logger.info(f"   Вчерашний P&L: {self.daily_pnl:.4f}")
            self.logger.info(
                f"   Сделок вчера: {len([t for t in self.trades_today if datetime.fromtimestamp(t['timestamp']).date() == self.last_reset_date])}")

            # Архивируем вчерашние данные
            yesterday_trades = [t for t in self.trades_today if
                                datetime.fromtimestamp(t['timestamp']).date() == self.last_reset_date]
            if yesterday_trades:
                self._log_daily_summary(yesterday_trades, self.daily_pnl)

            # Сбрасываем дневные счетчики
            self.daily_pnl = 0.0
            self.last_reset_date = current_date

            # Удаляем старые сделки (оставляем только за последние 7 дней)
            week_ago = datetime.now() - timedelta(days=7)
            self.trades_today = deque([
                t for t in self.trades_today
                if datetime.fromtimestamp(t['timestamp']) > week_ago
            ], maxlen=100)

    def _log_daily_summary(self, trades: List, pnl: float):
        """📊 Логирование дневной сводки"""
        if not trades:
            return

        buy_trades = [t for t in trades if t.get('type') == 'buy']
        sell_trades = [t for t in trades if t.get('type') == 'sell']
        profitable = [t for t in trades if t.get('pnl', 0) > 0]

        self.logger.info(f"📊 ДНЕВНАЯ СВОДКА:")
        self.logger.info(f"   💰 P&L: {pnl:.4f}")
        self.logger.info(f"   📈 Сделок: {len(trades)} (покупок: {len(buy_trades)}, продаж: {len(sell_trades)})")
        self.logger.info(
            f"   ✅ Прибыльных: {len(profitable)}/{len(trades)} ({len(profitable) / len(trades) * 100:.1f}%)")

    def calculate_volatility(self, prices: List[float]) -> float:
        """📊 Расчет волатильности цен"""
        if len(prices) < 2:
            return 0.0

        returns = []
        for i in range(1, len(prices)):
            if prices[i - 1] > 0:  # Защита от деления на ноль
                returns.append((prices[i] - prices[i - 1]) / prices[i - 1])

        return statistics.stdev(returns) if len(returns) > 1 else 0.0

    def calculate_dynamic_spread(self, volatility: float) -> float:
        """📈 Динамический спред на основе волатильности"""
        base_spread = self.config.BASE_PROFIT_MARKUP
        volatility_multiplier = min(3.0, max(1.0, volatility * 100))

        dynamic_spread = base_spread * volatility_multiplier
        return max(self.config.MIN_SPREAD, dynamic_spread)

    def can_open_position(self, position_size: float, balance: float) -> bool:
        """🛡️ Проверка возможности открытия позиции"""
        # Сброс дневной статистики если нужно
        self.maybe_reset_daily_pnl()

        # Проверка размера позиции
        max_position_value = balance * self.config.MAX_POSITION_SIZE
        if position_size > max_position_value:
            self.logger.warning(f"❌ Размер позиции {position_size:.2f} превышает лимит {max_position_value:.2f}")
            return False

        # Проверка дневных потерь
        daily_loss_limit = balance * self.config.MAX_DAILY_LOSS
        if self.daily_pnl < -daily_loss_limit:
            self.logger.warning(f"❌ Превышен лимит дневных потерь: {self.daily_pnl:.4f} < -{daily_loss_limit:.4f}")
            return False

        # Проверка количества сделок за день
        today_trades = [
            t for t in self.trades_today
            if datetime.fromtimestamp(t['timestamp']).date() == datetime.now().date()
        ]

        if hasattr(self.config, 'MAX_TRADES_PER_DAY'):
            if len(today_trades) >= self.config.MAX_TRADES_PER_DAY:
                self.logger.warning(f"❌ Превышен лимит сделок в день: {len(today_trades)}")
                return False

        return True

    def set_stop_loss(self, currency: str, entry_price: float, quantity: float, order_type: str):
        """🛑 Установка стоп-лосса"""
        stop_price = self.calculate_stop_loss(entry_price, order_type)

        self.active_stop_losses[currency] = {
            'price': stop_price,
            'quantity': quantity,
            'entry_price': entry_price,
            'order_type': order_type,
            'created': time.time()
        }

        loss_percent = self.config.STOP_LOSS_PERCENT * 100
        self.logger.info(f"🛑 Установлен стоп-лосс для {currency}:")
        self.logger.info(f"   Цена входа: {entry_price:.8f}")
        self.logger.info(f"   Стоп-лосс: {stop_price:.8f} (-{loss_percent:.1f}%)")
        self.logger.info(f"   Количество: {quantity:.6f}")

    def check_stop_losses(self, current_price: float, currency: str) -> Tuple[bool, str]:
        """🔍 Проверка стоп-лоссов"""
        if currency not in self.active_stop_losses:
            return False, ""

        stop_info = self.active_stop_losses[currency]
        stop_price = stop_info['price']
        entry_price = stop_info['entry_price']
        order_type = stop_info['order_type']

        # Проверяем условие стоп-лосса
        should_trigger = False

        if order_type == 'buy':  # Для длинной позиции
            if current_price <= stop_price:
                should_trigger = True
        else:  # Для короткой позиции (если будет)
            if current_price >= stop_price:
                should_trigger = True

        if should_trigger:
            loss_percent = abs((current_price - entry_price) / entry_price * 100)
            reason = f"Стоп-лосс сработал: цена {current_price:.8f} <= {stop_price:.8f} (убыток {loss_percent:.2f}%)"

            # Удаляем стоп-лосс после срабатывания
            del self.active_stop_losses[currency]

            self.logger.warning(f"🚨 {reason}")
            return True, reason

        return False, ""

    def calculate_stop_loss(self, entry_price: float, order_type: str) -> float:
        """🛑 Расчет цены стоп-лосса"""
        if order_type == 'buy':
            return entry_price * (1 - self.config.STOP_LOSS_PERCENT)
        else:
            return entry_price * (1 + self.config.STOP_LOSS_PERCENT)

    def update_daily_pnl(self, pnl: float, trade_info: dict = None):
        """📊 Обновление дневного P&L"""
        self.maybe_reset_daily_pnl()

        self.daily_pnl += pnl
        self.total_profit += pnl
        self.total_trades += 1

        if pnl > 0:
            self.profitable_trades += 1

        # Записываем сделку
        trade_record = {
            'pnl': pnl,
            'timestamp': time.time(),
            'type': trade_info.get('type') if trade_info else 'unknown'
        }

        if trade_info:
            trade_record.update(trade_info)

        self.trades_today.append(trade_record)

        # Обновляем статистику максимальной просадки
        if hasattr(self, 'current_balance'):
            if self.current_balance > self.peak_balance:
                self.peak_balance = self.current_balance

            drawdown = (self.peak_balance - self.current_balance) / self.peak_balance
            if drawdown > self.max_drawdown:
                self.max_drawdown = drawdown

        self.logger.info(f"📊 Обновлен P&L: {pnl:+.4f}, дневной итог: {self.daily_pnl:+.4f}")

    def get_risk_metrics(self) -> dict:
        """📊 Получение метрик риска"""
        success_rate = (self.profitable_trades / max(1, self.total_trades)) * 100

        today_trades = [
            t for t in self.trades_today
            if datetime.fromtimestamp(t['timestamp']).date() == datetime.now().date()
        ]

        return {
            'daily_pnl': self.daily_pnl,
            'total_trades': self.total_trades,
            'profitable_trades': self.profitable_trades,
            'success_rate': success_rate,
            'total_profit': self.total_profit,
            'max_drawdown': self.max_drawdown * 100,
            'trades_today': len(today_trades),
            'active_stop_losses': len(self.active_stop_losses)
        }

    def log_risk_summary(self):
        """📊 Логирование сводки по рискам"""
        metrics = self.get_risk_metrics()

        self.logger.info("📊 СВОДКА ПО РИСКАМ:")
        self.logger.info(f"   💰 Дневной P&L: {metrics['daily_pnl']:+.4f}")
        self.logger.info(f"   📈 Сделок всего: {metrics['total_trades']}")
        self.logger.info(f"   ✅ Успешность: {metrics['success_rate']:.1f}%")
        self.logger.info(f"   📉 Макс. просадка: {metrics['max_drawdown']:.2f}%")
        self.logger.info(f"   🛑 Активных стоп-лоссов: {metrics['active_stop_losses']}")

    def should_reduce_risk(self) -> Tuple[bool, str]:
        """⚠️ Определение необходимости снижения рисков"""
        reasons = []

        # Проверка дневных потерь
        if self.daily_pnl < -0.01:  # Больше 1% дневных потерь
            reasons.append(f"дневные потери {self.daily_pnl * 100:.1f}%")

        # Проверка серии убытков
        recent_trades = list(self.trades_today)[-5:]  # Последние 5 сделок
        if len(recent_trades) >= 3:
            losses = [t for t in recent_trades if t.get('pnl', 0) < 0]
            if len(losses) >= 3:
                reasons.append(f"серия из {len(losses)} убыточных сделок")

        # Проверка максимальной просадки
        if self.max_drawdown > 0.05:  # Больше 5% просадки
            reasons.append(f"просадка {self.max_drawdown * 100:.1f}%")

        if reasons:
            return True, f"Рекомендуется снизить риски: {', '.join(reasons)}"

        return False, ""

    def emergency_stop_check(self, current_balance: float) -> Tuple[bool, str]:
        """🚨 Проверка экстренной остановки"""
        self.current_balance = current_balance

        # Критические потери за день
        if self.daily_pnl < -current_balance * 0.1:  # Больше 10% дневных потерь
            return True, f"КРИТИЧЕСКИЕ дневные потери: {self.daily_pnl * 100:.1f}%"

        # Критическая просадка
        if self.max_drawdown > 0.15:  # Больше 15% просадки
            return True, f"КРИТИЧЕСКАЯ просадка: {self.max_drawdown * 100:.1f}%"

        return False, ""

    def cleanup_old_stop_losses(self, max_age_hours: int = 24):
        """🧹 Очистка старых стоп-лоссов"""
        current_time = time.time()
        expired = []

        for currency, stop_info in self.active_stop_losses.items():
            age_hours = (current_time - stop_info['created']) / 3600
            if age_hours > max_age_hours:
                expired.append(currency)

        for currency in expired:
            del self.active_stop_losses[currency]
            self.logger.info(f"🧹 Удален устаревший стоп-лосс для {currency}")

    def calculate_position_risk(self, entry_price: float, current_price: float, quantity: float) -> dict:
        """📊 Расчет риска позиции"""
        unrealized_pnl = (current_price - entry_price) * quantity
        unrealized_percent = (current_price - entry_price) / entry_price * 100

        risk_to_stop_loss = entry_price * self.config.STOP_LOSS_PERCENT * quantity

        return {
            'unrealized_pnl': unrealized_pnl,
            'unrealized_percent': unrealized_percent,
            'risk_to_stop_loss': risk_to_stop_loss,
            'risk_percent': self.config.STOP_LOSS_PERCENT * 100
        }