#!/usr/bin/env python3
"""🔄 Адаптеры для интеграции старых компонентов"""

import sys
import os
import time
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from typing import Dict, Any, Optional
from decimal import Decimal

class LegacyBotAdapter:
    """Адаптер для старого бота"""

    def __init__(self, use_hybrid: bool = True):
        self.use_hybrid = use_hybrid
        self._old_bot = None

    def get_old_bot(self):
        """Получение экземпляра старого бота"""
        if self._old_bot is None:
            try:
                if self.use_hybrid:
                    from hybrid_bot import HybridTradingBot
                    self._old_bot = HybridTradingBot()
                else:
                    from bot import TradingBot
                    self._old_bot = TradingBot()
            except ImportError as e:
                print(f"⚠️ Не удалось импортировать старый бот: {e}")
                # Fallback на базовый бот
                try:
                    from bot import TradingBot
                    self._old_bot = TradingBot()
                except ImportError:
                    raise ImportError("Не удалось импортировать ни один из старых ботов")

        return self._old_bot

    async def run_trading_cycle(self) -> Dict[str, Any]:
        """Запуск торгового цикла"""
        try:
            old_bot = self.get_old_bot()

            # Если у старого бота есть метод execute_cycle
            if hasattr(old_bot, 'execute_cycle'):
                return await old_bot.execute_cycle()

            # Если есть strategy_manager
            elif hasattr(old_bot, 'strategy_manager'):
                market_data = self._collect_market_data(old_bot)
                return old_bot.strategy_manager.execute_cycle(market_data)

            else:
                return {'success': False, 'reason': 'Неизвестный интерфейс старого бота'}

        except Exception as e:
            return {'success': False, 'reason': f'Ошибка адаптера: {e}'}

    def _collect_market_data(self, bot) -> Dict[str, Any]:
        """Сбор рыночных данных из старого бота"""
        try:
            if hasattr(bot, '_collect_market_data'):
                return bot._collect_market_data()
            else:
                # Базовый набор данных
                return {
                    'current_price': 0.18,  # Заглушка
                    'balance': 1000.0,
                    'timestamp': time.time()
                }
        except Exception:
            return {}

class StrategyAdapter:
    """Адаптер для старых стратегий"""

    def __init__(self):
        self._strategies = {}

    def load_old_strategies(self):
        """Загрузка старых стратегий"""
        try:
            # Пытаемся загрузить старые стратегии
            from strategies import StrategyManager
            from config import TradingConfig

            config = TradingConfig()
            self._strategies['legacy'] = StrategyManager(config, None, None)

        except ImportError as e:
            print(f"⚠️ Не удалось загрузить старые стратегии: {e}")

    async def execute_strategy(self, strategy_name: str, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """Выполнение стратегии"""
        if strategy_name in self._strategies:
            try:
                return self._strategies[strategy_name].execute_cycle(market_data)
            except Exception as e:
                return {'success': False, 'reason': f'Ошибка стратегии: {e}'}

        return {'success': False, 'reason': f'Стратегия {strategy_name} не найдена'}
