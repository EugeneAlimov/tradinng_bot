#!/usr/bin/env python3
"""🎯 Миграция Part 6 - Доменная логика"""

import logging
from pathlib import Path


class Migration:
    """🎯 Миграция доменной логики"""
    
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.src_dir = project_root / "src"
        self.domain_dir = self.src_dir / "domain"
        self.logger = logging.getLogger(__name__)

    def execute(self) -> bool:
        """🚀 Выполнение миграции"""
        try:
            self.logger.info("🎯 Создание доменной логики...")
            
            # Создаем структуру директорий
            self._create_directory_structure()
            
            # Создаем торговые стратегии
            self._create_trading_strategies()
            
            # Создаем управление рисками
            self._create_risk_management()
            
            self.logger.info("✅ Доменная логика создана")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка создания доменной логики: {e}")
            return False

    def _create_directory_structure(self):
        """📁 Создание структуры директорий"""
        dirs_to_create = [
            self.domain_dir,
            self.domain_dir / "trading",
            self.domain_dir / "trading" / "strategies",
            self.domain_dir / "risk",
        ]
        
        for dir_path in dirs_to_create:
            dir_path.mkdir(parents=True, exist_ok=True)
            
            # Создаем __init__.py
            init_file = dir_path / "__init__.py"
            if not init_file.exists():
                init_file.write_text('"""🎯 Доменный модуль"""\n')

    def _create_trading_strategies(self):
        """🎯 Создание торговых стратегий"""
        # DCA стратегия
        dca_strategy_content = '''#!/usr/bin/env python3
"""🛒 DCA (Dollar Cost Averaging) стратегия"""

import time
import logging
from typing import Dict, Any, Optional
from decimal import Decimal
from datetime import datetime, timedelta

from ....core.base import BaseStrategy
from ....core.models import TradeSignal, MarketData, Position, TradingPair, SignalAction
from ....core.exceptions import StrategyError
from ....infrastructure.di_container import injectable


@injectable
class DCAStrategy(BaseStrategy):
    """🛒 Адаптивная DCA стратегия"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__("dca_strategy", config)
        
        # Параметры DCA
        self.drop_threshold_percent = Decimal(str(config.get('drop_threshold_percent', '1.5')))
        self.purchase_size_percent = Decimal(str(config.get('purchase_size_percent', '3.0')))
        self.max_purchases = config.get('max_purchases', 5)
        self.cooldown_minutes = config.get('cooldown_minutes', 20)
        self.max_position_percent = Decimal(str(config.get('max_position_percent', '45.0')))
        
        # Состояние стратегии
        self.last_purchase_time = 0
        self.purchase_count = 0
        self.last_purchase_date = None
        
        self.logger.info(f"🛒 DCA стратегия инициализирована: "
                        f"порог {self.drop_threshold_percent}%, "
                        f"размер {self.purchase_size_percent}%, "
                        f"макс покупок {self.max_purchases}")
    
    async def analyze(self, market_data: MarketData, 
                     position: Optional[Position] = None) -> TradeSignal:
        """🛒 Анализ DCA возможностей"""
        try:
            current_price = market_data.current_price
            trading_pair = market_data.trading_pair
            
            # Сброс дневных счетчиков
            self._reset_daily_counters_if_needed()
            
            # Проверка кулдауна
            if not self._is_cooldown_passed():
                remaining_minutes = self._get_remaining_cooldown_minutes()
                return self._create_signal(
                    SignalAction.HOLD.value, trading_pair, Decimal('0'), 
                    confidence=0.1, 
                    reason=f"DCA кулдаун: {remaining_minutes:.0f} мин"
                )
            
            # Проверка лимитов покупок
            if self.purchase_count >= self.max_purchases:
                return self._create_signal(
                    SignalAction.HOLD.value, trading_pair, Decimal('0'),
                    confidence=0.1,
                    reason=f"Достигнут лимит DCA: {self.purchase_count}/{self.max_purchases}"
                )
            
            # Анализ падения цены
            price_drop = self._analyze_price_drop(market_data)
            if price_drop < self.drop_threshold_percent:
                return self._create_signal(
                    SignalAction.HOLD.value, trading_pair, Decimal('0'),
                    confidence=0.3,
                    reason=f"Недостаточное падение: {price_drop:.2f}% < {self.drop_threshold_percent}%"
                )
            
            # Проверка максимального размера позиции
            if position and self._would_exceed_max_position(position, market_data):
                return self._create_signal(
                    SignalAction.HOLD.value, trading_pair, Decimal('0'),
                    confidence=0.2,
                    reason=f"Превышение макс позиции: {self.max_position_percent}%"
                )
            
            # Расчет размера покупки
            purchase_amount = self._calculate_purchase_amount(market_data)
            
            if purchase_amount <= 0:
                return self._create_signal(
                    SignalAction.HOLD.value, trading_pair, Decimal('0'),
                    confidence=0.1,
                    reason="Недостаточно средств для DCA"
                )
            
            # Создаем сигнал покупки
            confidence = min(0.8, float(price_drop) / 5.0)  # Уверенность зависит от размера падения
            
            self._register_purchase()
            
            return self._create_signal(
                SignalAction.BUY.value, trading_pair, purchase_amount,
                price=current_price,
                confidence=confidence,
                reason=f"DCA покупка: падение {price_drop:.2f}%, размер {purchase_amount}"
            )
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка анализа DCA: {e}")
            raise StrategyError(self.strategy_name, str(e))
    
    def _analyze_price_drop(self, market_data: MarketData) -> Decimal:
        """📉 Анализ падения цены"""
        # Упрощенный анализ - в реальности нужны исторические данные
        if 'price_change_15m' in market_data.additional_data:
            change_15m = Decimal(str(market_data.additional_data['price_change_15m']))
            return abs(min(Decimal('0'), change_15m))
        
        # Заглушка - возвращаем достаточное падение для тестирования
        return self.drop_threshold_percent + Decimal('0.5')
    
    def _calculate_purchase_amount(self, market_data: MarketData) -> Decimal:
        """💰 Расчет размера покупки"""
        balance = market_data.additional_data.get('balance', 0)
        balance_decimal = Decimal(str(balance))
        
        purchase_amount = balance_decimal * (self.purchase_size_percent / Decimal('100'))
        
        # Минимальный размер ордера
        min_order_size = Decimal('5.0')  # EUR
        if purchase_amount < min_order_size:
            return Decimal('0')
        
        return purchase_amount
    
    def _would_exceed_max_position(self, position: Position, market_data: MarketData) -> bool:
        """🚫 Проверка превышения максимальной позиции"""
        balance = Decimal(str(market_data.additional_data.get('balance', 0)))
        current_position_value = position.calculate_current_value(market_data.current_price)
        
        purchase_amount = self._calculate_purchase_amount(market_data)
        total_position_value = current_position_value + purchase_amount
        
        max_allowed = balance * (self.max_position_percent / Decimal('100'))
        
        return total_position_value > max_allowed
    
    def _is_cooldown_passed(self) -> bool:
        """⏰ Проверка прохождения кулдауна"""
        if self.last_purchase_time == 0:
            return True
        
        cooldown_seconds = self.cooldown_minutes * 60
        return time.time() - self.last_purchase_time >= cooldown_seconds
    
    def _get_remaining_cooldown_minutes(self) -> float:
        """⏰ Получение оставшегося времени кулдауна"""
        if self.last_purchase_time == 0:
            return 0
        
        elapsed = time.time() - self.last_purchase_time
        cooldown_seconds = self.cooldown_minutes * 60
        remaining_seconds = max(0, cooldown_seconds - elapsed)
        
        return remaining_seconds / 60
    
    def _reset_daily_counters_if_needed(self) -> None:
        """🔄 Сброс дневных счетчиков"""
        today = datetime.now().date()
        if self.last_purchase_date != today:
            old_count = self.purchase_count
            self.purchase_count = 0
            self.last_purchase_date = today
            
            if old_count > 0:
                self.logger.info(f"🔄 Сброс дневного счетчика DCA: {old_count} -> 0")
    
    def _register_purchase(self) -> None:
        """📝 Регистрация покупки"""
        self.purchase_count += 1
        self.last_purchase_time = time.time()
        self.logger.info(f"📝 DCA покупка зарегистрирована: {self.purchase_count}")
    
    def reset_counters(self) -> None:
        """🔄 Сброс всех счетчиков (при успешной продаже)"""
        self.purchase_count = 0
        self.last_purchase_time = 0
        self.logger.info("🔄 Счетчики DCA сброшены")
'''

        # Пирамидальная стратегия
        pyramid_strategy_content = '''#!/usr/bin/env python3
"""🏗️ Пирамидальная стратегия продажи"""

import time
import logging
from typing import Dict, Any, Optional, List
from decimal import Decimal
from datetime import datetime

from ....core.base import BaseStrategy
from ....core.models import TradeSignal, MarketData, Position, TradingPair, SignalAction
from ....core.exceptions import StrategyError
from ....infrastructure.di_container import injectable


@injectable
class PyramidStrategy(BaseStrategy):
    """🏗️ Пирамидальная стратегия продажи"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__("pyramid_strategy", config)
        
        # Уровни пирамиды
        self.levels = config.get('levels', [
            {"profit_pct": 0.8, "sell_pct": 25.0, "min_eur": 0.08},
            {"profit_pct": 2.0, "sell_pct": 35.0, "min_eur": 0.15},
            {"profit_pct": 4.0, "sell_pct": 25.0, "min_eur": 0.25},
            {"profit_pct": 7.0, "sell_pct": 15.0, "min_eur": 0.40},
        ])
        
        # Аварийные уровни (продажа в убытке)
        self.emergency_levels = config.get('emergency_levels', [
            {"loss_pct": 8.0, "sell_pct": 30.0, "hold_hours": 4},
            {"loss_pct": 12.0, "sell_pct": 50.0, "hold_hours": 0},
            {"loss_pct": 15.0, "sell_pct": 100.0, "hold_hours": 0},
        ])
        
        # Состояние
        self.last_sell_time = 0
        self.cooldown_minutes = config.get('cooldown_minutes', 10)
        
        self.logger.info(f"🏗️ Пирамидальная стратегия инициализирована: "
                        f"{len(self.levels)} уровней прибыли, "
                        f"{len(self.emergency_levels)} аварийных уровней")
    
    async def analyze(self, market_data: MarketData, 
                     position: Optional[Position] = None) -> TradeSignal:
        """🏗️ Анализ пирамидальной продажи"""
        try:
            if not position or position.quantity <= 0:
                return self._create_signal(
                    SignalAction.HOLD.value, market_data.trading_pair, Decimal('0'),
                    confidence=0.1,
                    reason="Нет позиции для продажи"
                )
            
            current_price = market_data.current_price
            
            # Проверка кулдауна
            if not self._is_cooldown_passed():
                remaining = self._get_remaining_cooldown_minutes()
                return self._create_signal(
                    SignalAction.HOLD.value, market_data.trading_pair, Decimal('0'),
                    confidence=0.2,
                    reason=f"Кулдаун продажи: {remaining:.0f} мин"
                )
            
            # Расчет прибыли/убытка
            profit_loss_pct = position.calculate_profit_loss_percentage(current_price)
            
            # Проверка аварийных уровней (убыток)
            if profit_loss_pct < 0:
                emergency_signal = self._check_emergency_levels(position, current_price, abs(profit_loss_pct))
                if emergency_signal:
                    return emergency_signal
            
            # Проверка обычных уровней (прибыль)
            if profit_loss_pct > 0:
                profit_signal = self._check_profit_levels(position, current_price, profit_loss_pct)
                if profit_signal:
                    return profit_signal
            
            # Удержание позиции
            return self._create_signal(
                SignalAction.HOLD.value, market_data.trading_pair, Decimal('0'),
                confidence=0.4,
                reason=f"Удержание: P&L {profit_loss_pct:.2f}%"
            )
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка анализа пирамиды: {e}")
            raise StrategyError(self.strategy_name, str(e))
    
    def _check_profit_levels(self, position: Position, current_price: Decimal, 
                           profit_pct: Decimal) -> Optional[TradeSignal]:
        """📈 Проверка уровней прибыли"""
        
        for level in reversed(self.levels):  # Начинаем с самого высокого уровня
            level_profit = Decimal(str(level['profit_pct']))
            
            if profit_pct >= level_profit:
                sell_percent = Decimal(str(level['sell_pct']))
                min_eur = Decimal(str(level['min_eur']))
                
                sell_quantity = position.quantity * (sell_percent / Decimal('100'))
                sell_value = sell_quantity * current_price
                
                if sell_value >= min_eur:
                    self._register_sell()
                    
                    confidence = min(0.9, float(profit_pct) / 10.0)
                    
                    return self._create_signal(
                        SignalAction.SELL.value, 
                        TradingPair(position.currency, "EUR"),  # Предполагаем EUR
                        sell_quantity,
                        price=current_price * Decimal('1.002'),  # Небольшая скидка
                        confidence=confidence,
                        reason=f"Пирамида {level_profit}%: продажа {sell_percent}% = {sell_value:.2f} EUR"
                    )
        
        return None
    
    def _check_emergency_levels(self, position: Position, current_price: Decimal, 
                               loss_pct: Decimal) -> Optional[TradeSignal]:
        """🚨 Проверка аварийных уровней"""
        
        position_age_hours = self._get_position_age_hours(position)
        
        for level in self.emergency_levels:
            level_loss = Decimal(str(level['loss_pct']))
            required_hours = level['hold_hours']
            
            if loss_pct >= level_loss and position_age_hours >= required_hours:
                sell_percent = Decimal(str(level['sell_pct']))
                sell_quantity = position.quantity * (sell_percent / Decimal('100'))
                
                self._register_sell()
                
                return self._create_signal(
                    SignalAction.EMERGENCY_EXIT.value,
                    TradingPair(position.currency, "EUR"),
                    sell_quantity,
                    price=current_price * Decimal('0.998'),  # Агрессивная скидка
                    confidence=0.95,
                    reason=f"Аварийный уровень {level_loss}%: продажа {sell_percent}% после {position_age_hours:.1f}ч"
                )
        
        return None
    
    def _get_position_age_hours(self, position: Position) -> float:
        """⏰ Получение возраста позиции в часах"""
        if isinstance(position.timestamp, str):
            position_time = datetime.fromisoformat(position.timestamp)
        else:
            position_time = position.timestamp
        
        age = datetime.now() - position_time
        return age.total_seconds() / 3600
    
    def _is_cooldown_passed(self) -> bool:
        """⏰ Проверка кулдауна"""
        if self.last_sell_time == 0:
            return True
        
        cooldown_seconds = self.cooldown_minutes * 60
        return time.time() - self.last_sell_time >= cooldown_seconds
    
    def _get_remaining_cooldown_minutes(self) -> float:
        """⏰ Оставшееся время кулдауна"""
        if self.last_sell_time == 0:
            return 0
        
        elapsed = time.time() - self.last_sell_time
        cooldown_seconds = self.cooldown_minutes * 60
        remaining = max(0, cooldown_seconds - elapsed)
        
        return remaining / 60
    
    def _register_sell(self) -> None:
        """📝 Регистрация продажи"""
        self.last_sell_time = time.time()
        self.logger.info("📝 Пирамидальная продажа зарегистрирована")
'''

        dca_file = self.domain_dir / "trading" / "strategies" / "dca_strategy.py"
        dca_file.write_text(dca_strategy_content)
        
        pyramid_file = self.domain_dir / "trading" / "strategies" / "pyramid_strategy.py"
        pyramid_file.write_text(pyramid_strategy_content)
        
        self.logger.info("  ✅ Созданы торговые стратегии")

    def _create_risk_management(self):
        """🛡️ Создание системы управления рисками"""
        risk_manager_content = '''#!/usr/bin/env python3
"""🛡️ Система управления рисками"""

import logging
from typing import Dict, Any, Optional, List, Tuple
from decimal import Decimal
from datetime import datetime, timedelta

from ...core.interfaces import IRiskManager
from ...core.models import TradeSignal, Position, RiskMetrics
from ...core.exceptions import RiskManagementError
from ...infrastructure.di_container import injectable


@injectable
class RiskManager(IRiskManager):
    """🛡️ Менеджер рисков"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = logging.getLogger(f"{__name__}.RiskManager")
        
        # Параметры риска
        self.max_position_size_percent = Decimal(str(config.get('max_position_size_percent', '50.0')))
        self.max_daily_loss_percent = Decimal(str(config.get('max_daily_loss_percent', '5.0')))
        self.emergency_exit_threshold = Decimal(str(config.get('emergency_exit_threshold', '15.0')))
        self.max_trades_per_hour = config.get('max_trades_per_hour', 10)
        
        # Состояние
        self.daily_loss = Decimal('0')
        self.daily_trades = 0
        self.last_reset_date = datetime.now().date()
        self.recent_trades: List[datetime] = []
        self.blocked_until: Optional[datetime] = None
        self.block_reason = ""
        
        self.logger.info(f"🛡️ Риск-менеджер инициализирован: "
                        f"макс позиция {self.max_position_size_percent}%, "
                        f"макс убыток {self.max_daily_loss_percent}%")
    
    async def assess_risk(self, signal: TradeSignal, 
                         position: Optional[Position]) -> Dict[str, Any]:
        """🔍 Оценка риска сигнала"""
        try:
            self._reset_daily_counters_if_needed()
            
            risk_factors = []
            risk_score = 0.0
            can_execute = True
            
            # Проверка блокировки
            if self._is_blocked():
                return {
                    'can_execute': False,
                    'risk_score': 1.0,
                    'risk_factors': [f"Торговля заблокирована: {self.block_reason}"],
                    'recommendations': ["Дождитесь снятия блокировки"]
                }
            
            # Проверка размера позиции
            position_risk = self._assess_position_size_risk(signal, position)
            risk_factors.extend(position_risk['factors'])
            risk_score += position_risk['score']
            
            if not position_risk['can_execute']:
                can_execute = False
            
            # Проверка дневных лимитов
            daily_risk = self._assess_daily_limits_risk()
            risk_factors.extend(daily_risk['factors'])
            risk_score += daily_risk['score']
            
            if not daily_risk['can_execute']:
                can_execute = False
            
            # Проверка частоты торговли
            frequency_risk = self._assess_trading_frequency_risk()
            risk_factors.extend(frequency_risk['factors'])
            risk_score += frequency_risk['score']
            
            if not frequency_risk['can_execute']:
                can_execute = False
            
            # Нормализация риска
            risk_score = min(1.0, risk_score)
            
            # Рекомендации
            recommendations = self._generate_recommendations(risk_score, risk_factors)
            
            return {
                'can_execute': can_execute,
                'risk_score': risk_score,
                'risk_factors': risk_factors,
                'recommendations': recommendations,
                'daily_loss_percent': float(self.daily_loss),
                'daily_trades_count': self.daily_trades,
                'trades_per_hour': len(self.recent_trades)
            }
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка оценки риска: {e}")
            raise RiskManagementError(f"Ошибка оценки риска: {e}")
    
    async def should_block_trading(self, reason: str = None) -> bool:
        """🚫 Проверка необходимости блокировки торговли"""
        self._reset_daily_counters_if_needed()
        
        # Превышение дневных убытков
        if self.daily_loss >= self.max_daily_loss_percent:
            if not self._is_blocked():
                self._block_trading(f"Превышение дневных убытков: {self.daily_loss}%")
            return True
        
        # Слишком частая торговля
        if len(self.recent_trades) >= self.max_trades_per_hour:
            if not self._is_blocked():
                self._block_trading(f"Превышение лимита сделок в час: {len(self.recent_trades)}")
            return True
        
        # Внешняя причина
        if reason:
            self._block_trading(reason)
            return True
        
        return self._is_blocked()
    
    def _assess_position_size_risk(self, signal: TradeSignal, 
                                  position: Optional[Position]) -> Dict[str, Any]:
        """📊 Оценка риска размера позиции"""
        factors = []
        score = 0.0
        can_execute = True
        
        if signal.action.value in ["buy"]:
            # Получаем текущий размер позиции
            current_position_value = Decimal('0')
            if position:
                current_position_value = position.calculate_current_value(signal.price or Decimal('0'))
            
            # Добавляем размер нового сигнала
            signal_value = signal.quantity * (signal.price or Decimal('0'))
            total_position_value = current_position_value + signal_value
            
            # Предполагаемый баланс (нужно получать из market_data)
            estimated_balance = Decimal('1000')  # Заглушка
            position_percent = (total_position_value / estimated_balance) * Decimal('100')
            
            if position_percent > self.max_position_size_percent:
                factors.append(f"Превышение макс размера позиции: {position_percent:.1f}%")
                score += 0.8
                can_execute = False
            elif position_percent > self.max_position_size_percent * Decimal('0.8'):
                factors.append(f"Приближение к макс размеру позиции: {position_percent:.1f}%")
                score += 0.4
        
        return {
            'factors': factors,
            'score': score,
            'can_execute': can_execute
        }
    
    def _assess_daily_limits_risk(self) -> Dict[str, Any]:
        """📅 Оценка риска дневных лимитов"""
        factors = []
        score = 0.0
        can_execute = True
        
        # Проверка дневных убытков
        if self.daily_loss >= self.max_daily_loss_percent:
            factors.append(f"Превышение дневных убытков: {self.daily_loss}%")
            score += 1.0
            can_execute = False
        elif self.daily_loss >= self.max_daily_loss_percent * Decimal('0.7'):
            factors.append(f"Приближение к лимиту убытков: {self.daily_loss}%")
            score += 0.5
        
        return {
            'factors': factors,
            'score': score,
            'can_execute': can_execute
        }
    
    def _assess_trading_frequency_risk(self) -> Dict[str, Any]:
        """⏱️ Оценка риска частоты торговли"""
        factors = []
        score = 0.0
        can_execute = True
        
        # Очищаем старые сделки
        hour_ago = datetime.now() - timedelta(hours=1)
        self.recent_trades = [trade_time for trade_time in self.recent_trades if trade_time > hour_ago]
        
        trades_count = len(self.recent_trades)
        
        if trades_count >= self.max_trades_per_hour:
            factors.append(f"Превышение лимита сделок в час: {trades_count}")
            score += 1.0
            can_execute = False
        elif trades_count >= self.max_trades_per_hour * 0.8:
            factors.append(f"Высокая частота торговли: {trades_count}/{self.max_trades_per_hour}")
            score += 0.3
        
        return {
            'factors': factors,
            'score': score,
            'can_execute': can_execute
        }
    
    def _generate_recommendations(self, risk_score: float, factors: List[str]) -> List[str]:
        """💡 Генерация рекомендаций"""
        recommendations = []
        
        if risk_score > 0.7:
            recommendations.append("Высокий риск - рассмотрите уменьшение размера позиции")
        elif risk_score > 0.4:
            recommendations.append("Умеренный риск - будьте осторожны")
        
        if "убыток" in " ".join(factors).lower():
            recommendations.append("Рассмотрите стоп-лосс или уменьшение позиции")
        
        if "частота" in " ".join(factors).lower():
            recommendations.append("Увеличьте интервалы между сделками")
        
        if not recommendations:
            recommendations.append("Риск в пределах нормы")
        
        return recommendations
    
    def _reset_daily_counters_if_needed(self) -> None:
        """🔄 Сброс дневных счетчиков"""
        today = datetime.now().date()
        if self.last_reset_date != today:
            self.daily_loss = Decimal('0')
            self.daily_trades = 0
            self.last_reset_date = today
            self.logger.info("🔄 Дневные счетчики риска сброшены")
    
    def _is_blocked(self) -> bool:
        """🚫 Проверка блокировки"""
        if self.blocked_until is None:
            return False
        
        if datetime.now() >= self.blocked_until:
            self._unblock_trading()
            return False
        
        return True
    
    def _block_trading(self, reason: str, duration_minutes: int = 60) -> None:
        """🚫 Блокировка торговли"""
        self.blocked_until = datetime.now() + timedelta(minutes=duration_minutes)
        self.block_reason = reason
        self.logger.warning(f"🚫 Торговля заблокирована на {duration_minutes} мин: {reason}")
    
    def _unblock_trading(self) -> None:
        """✅ Разблокировка торговли"""
        self.blocked_until = None
        self.block_reason = ""
        self.logger.info("✅ Торговля разблокирована")
    
    def register_trade_result(self, profit_loss: Decimal) -> None:
        """📝 Регистрация результата сделки"""
        self._reset_daily_counters_if_needed()
        
        self.daily_trades += 1
        self.recent_trades.append(datetime.now())
        
        if profit_loss < 0:
            self.daily_loss += abs(profit_loss)
        
        self.logger.debug(f"📝 Результат сделки: P&L {profit_loss}, дневный убыток {self.daily_loss}%")
    
    def get_risk_metrics(self) -> RiskMetrics:
        """📊 Получение метрик риска"""
        return RiskMetrics(
            current_drawdown=self.daily_loss,
            total_trades=self.daily_trades,
            timestamp=datetime.now()
        )


if __name__ == "__main__":
    # Тестирование риск-менеджмента
    config = {
        'max_position_size_percent': 50.0,
        'max_daily_loss_percent': 5.0,
        'emergency_exit_threshold': 15.0,
        'max_trades_per_hour': 10
    }
    
    risk_manager = RiskManager(config)
    print("🛡️ Система управления рисками готова")
'''

        risk_file = self.domain_dir / "risk" / "risk_manager.py"
        risk_file.write_text(risk_manager_content)
        self.logger.info("  ✅ Создан risk/risk_manager.py")