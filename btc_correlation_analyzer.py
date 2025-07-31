# btc_correlation_analyzer.py
"""
₿ ПАТЧ 3: Анализатор корреляции с BTC
Предотвращает торговлю во время нестабильности BTC
"""

import time
import logging
from typing import Dict, Any, List, Tuple, Optional
from collections import deque
import requests


class BTCCorrelationAnalyzer:
    """₿ Анализатор корреляции и влияния BTC на DOGE"""
    
    def __init__(self, config, api_service):
        self.config = config
        self.api_service = api_service
        self.logger = logging.getLogger(__name__)
        
        # 📊 Буферы для анализа
        self.btc_prices = deque(maxlen=30)     # Последние 30 точек BTC
        self.doge_prices = deque(maxlen=30)    # Последние 30 точек DOGE
        self.price_update_interval = 300       # 5 минут между обновлениями
        self.last_update_time = 0
        
        # 🚨 Пороги для блокировки торговли
        self.BTC_HIGH_VOLATILITY_THRESHOLD = 0.03  # 3% волатильность BTC
        self.BTC_CRASH_THRESHOLD = 0.05            # 5% падение BTC
        self.BTC_PUMP_THRESHOLD = 0.04             # 4% рост BTC
        
        # 📈 Состояние BTC
        self.btc_status = {
            'trend': 'unknown',
            'volatility': 0.0,
            'last_change': 0.0,
            'allow_trading': True,
            'block_reason': ''
        }
        
        self.logger.info("₿ BTCCorrelationAnalyzer инициализирован")
        self.logger.info(f"   📊 Волатильность блокировка: {self.BTC_HIGH_VOLATILITY_THRESHOLD*100:.0f}%")
        self.logger.info(f"   📉 Крах блокировка: {self.BTC_CRASH_THRESHOLD*100:.0f}%")
    
    def update_btc_analysis(self) -> None:
        """📊 Обновление анализа BTC"""
        
        current_time = time.time()
        if current_time - self.last_update_time < self.price_update_interval:
            return  # Еще рано обновлять
        
        try:
            # Получаем цену BTC
            btc_price = self._get_btc_price()
            if btc_price is None:
                self.logger.warning("⚠️ Не удалось получить цену BTC")
                return
            
            # Получаем текущую цену DOGE
            doge_price = self._get_current_doge_price()
            if doge_price is None:
                self.logger.warning("⚠️ Не удалось получить цену DOGE")
                return
            
            # Добавляем в буферы
            self.btc_prices.append({
                'price': btc_price,
                'timestamp': current_time
            })
            
            self.doge_prices.append({
                'price': doge_price,
                'timestamp': current_time
            })
            
            # Анализируем только если есть достаточно данных
            if len(self.btc_prices) >= 3:
                self._analyze_btc_impact()
            
            self.last_update_time = current_time
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка обновления BTC анализа: {e}")
    
    def can_trade_with_btc_conditions(self, operation_type: str = 'buy') -> Tuple[bool, str]:
        """₿ Проверка возможности торговли с учетом состояния BTC"""
        
        # Обновляем анализ если нужно
        self.update_btc_analysis()
        
        if not self.btc_status['allow_trading']:
            return False, f"BTC блокировка: {self.btc_status['block_reason']}"
        
        # Дополнительные проверки для разных операций
        if operation_type == 'buy':
            # Для покупок более строгие условия
            if self.btc_status['trend'] == 'bearish_strong':
                return False, "Сильный медвежий тренд BTC - покупки заблокированы"
            
            if self.btc_status['volatility'] > self.BTC_HIGH_VOLATILITY_THRESHOLD:
                return False, f"Высокая волатильность BTC: {self.btc_status['volatility']*100:.1f}%"
        
        elif operation_type == 'dca':
            # Для DCA еще более строгие условия
            if self.btc_status['last_change'] < -0.02:  # BTC падает больше 2%
                return False, f"BTC падает: {self.btc_status['last_change']*100:.1f}% - DCA заблокирована"
            
            if self.btc_status['trend'] in ['bearish', 'bearish_strong']:
                return False, "Медвежий тренд BTC - DCA заблокирована"
        
        return True, "BTC условия позволяют торговлю"
    
    def _get_btc_price(self) -> Optional[float]:
        try:
            btc_eur_pair = f"BTC_{self.config.CURRENCY_2}"  # BTC_EUR

            #используем get_current_price
            btc_price = self.api_service.get_current_price(btc_eur_pair)
            if btc_price and btc_price > 0:
                return btc_price

            # Если не получилось, используем внешний источник
            return self._get_btc_price_external()

        except Exception as e:
            self.logger.error(f"❌ Ошибка получения цены BTC: {e}")
            return self._get_btc_price_external()

    def _get_btc_price_external(self) -> Optional[float]:
        """₿ Получение цены BTC из внешнего источника"""
        
        try:
            # Используем CoinGecko API (бесплатный)
            response = requests.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": "bitcoin", "vs_currencies": "eur"},
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                return float(data['bitcoin']['eur'])
                
        except Exception as e:
            self.logger.warning(f"⚠️ Ошибка внешнего API для BTC: {e}")
        
        return None
    
    def _get_current_doge_price(self) -> Optional[float]:
        """🐕 Получение текущей цены DOGE"""

        try:
            pair = f"{self.config.CURRENCY_1}_{self.config.CURRENCY_2}"

            # ИСПРАВЛЕНО: используем get_current_price вместо get_ticker
            doge_price = self.api_service.get_current_price(pair)
            if doge_price and doge_price > 0:
                return doge_price

        except Exception as e:
            self.logger.error(f"❌ Ошибка получения цены DOGE: {e}")

        return None
    
    def _analyze_btc_impact(self) -> None:
        """📊 Анализ влияния BTC на торговые решения"""
        
        if len(self.btc_prices) < 3:
            return
        
        # Берем последние данные
        latest_btc = self.btc_prices[-1]['price']
        prev_btc = self.btc_prices[-2]['price']
        older_btc = self.btc_prices[-3]['price']
        
        # Рассчитываем изменения
        short_change = (latest_btc - prev_btc) / prev_btc
        long_change = (latest_btc - older_btc) / older_btc
        
        # Рассчитываем волатильность (стандартное отклонение последних изменений)
        if len(self.btc_prices) >= 5:
            recent_prices = [p['price'] for p in list(self.btc_prices)[-5:]]
            changes = [(recent_prices[i] - recent_prices[i-1]) / recent_prices[i-1] 
                      for i in range(1, len(recent_prices))]
            volatility = self._calculate_std_dev(changes)
        else:
            volatility = abs(short_change)
        
        # Определяем тренд
        if long_change > 0.02:
            trend = 'bullish_strong'
        elif long_change > 0.005:
            trend = 'bullish'
        elif long_change < -0.02:
            trend = 'bearish_strong'
        elif long_change < -0.005:
            trend = 'bearish'
        else:
            trend = 'sideways'
        
        # Обновляем статус
        self.btc_status.update({
            'trend': trend,
            'volatility': volatility,
            'last_change': short_change,
            'allow_trading': True,
            'block_reason': ''
        })
        
        # Проверяем условия блокировки
        if volatility > self.BTC_HIGH_VOLATILITY_THRESHOLD:
            self.btc_status['allow_trading'] = False
            self.btc_status['block_reason'] = f"Высокая волатильность: {volatility*100:.1f}%"
        
        elif short_change < -self.BTC_CRASH_THRESHOLD:
            self.btc_status['allow_trading'] = False
            self.btc_status['block_reason'] = f"Крах BTC: {short_change*100:.1f}%"
        
        elif short_change > self.BTC_PUMP_THRESHOLD:
            self.btc_status['allow_trading'] = False
            self.btc_status['block_reason'] = f"Памп BTC: {short_change*100:.1f}%"
        
        # Логируем состояние
        self.logger.info(f"₿ BTC АНАЛИЗ:")
        self.logger.info(f"   💰 Цена: {latest_btc:.0f} EUR")
        self.logger.info(f"   📊 Тренд: {trend}")
        self.logger.info(f"   📈 Изменение: {short_change*100:.2f}%")
        self.logger.info(f"   🌊 Волатильность: {volatility*100:.2f}%")
        self.logger.info(f"   🎯 Торговля: {'✅ РАЗРЕШЕНА' if self.btc_status['allow_trading'] else '🚫 ЗАБЛОКИРОВАНА'}")
        
        if not self.btc_status['allow_trading']:
            self.logger.warning(f"   🚨 Причина блокировки: {self.btc_status['block_reason']}")
    
    def _calculate_std_dev(self, values: List[float]) -> float:
        """📊 Расчет стандартного отклонения"""
        if len(values) < 2:
            return 0.0
        
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        return variance ** 0.5
    
    def get_btc_status(self) -> Dict[str, Any]:
        """📊 Получение текущего статуса BTC"""
        return self.btc_status.copy()
    
    def force_update_btc_analysis(self) -> None:
        """🔄 Принудительное обновление анализа BTC"""
        self.last_update_time = 0  # Сбрасываем таймер
        self.update_btc_analysis()