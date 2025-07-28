# trailing_stop.py - ОБНОВЛЕННАЯ ВЕРСИЯ с быстрым исполнением

from typing import Optional, Tuple, Dict, Any
from datetime import datetime
import logging
import json
import os
import time

# Используем TYPE_CHECKING для избежания циклических импортов
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


class TrailingState:
    """📊 Состояние trailing stop позиции"""

    def __init__(self, entry_price: float, total_quantity: float, remaining_quantity: float):
        self.entry_price = entry_price
        self.total_quantity = total_quantity
        self.remaining_quantity = remaining_quantity

        self.status = "waiting"  # waiting, trailing
        self.peak_price = entry_price
        self.current_price = entry_price
        self.partial_sell_done = False
        self.created_at = datetime.now()
        self.last_update = datetime.now()

    def to_dict(self) -> Dict[str, Any]:
        """Сериализация в словарь"""
        return {
            'entry_price': self.entry_price,
            'total_quantity': self.total_quantity,
            'remaining_quantity': self.remaining_quantity,
            'status': self.status,
            'peak_price': self.peak_price,
            'current_price': self.current_price,
            'partial_sell_done': self.partial_sell_done,
            'created_at': self.created_at.isoformat(),
            'last_update': self.last_update.isoformat()
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TrailingState':
        """Десериализация из словаря"""
        instance = cls(
            entry_price=data['entry_price'],
            total_quantity=data['total_quantity'],
            remaining_quantity=data['remaining_quantity']
        )

        instance.status = data.get('status', 'waiting')
        instance.peak_price = data.get('peak_price', instance.entry_price)
        instance.current_price = data.get('current_price', instance.entry_price)
        instance.partial_sell_done = data.get('partial_sell_done', False)

        try:
            instance.created_at = datetime.fromisoformat(data['created_at'])
            instance.last_update = datetime.fromisoformat(data['last_update'])
        except:
            instance.created_at = datetime.now()
            instance.last_update = datetime.now()

        return instance


class TrailingStopManager:
    """🎯 Менеджер скользящих стопов с быстрым исполнением"""

    def __init__(self, data_dir: str = 'data'):
        self.logger = logging.getLogger(__name__)
        self.data_dir = data_dir
        self.state_file = os.path.join(data_dir, 'trailing_stops.json')

        # 🚀 УЛУЧШЕННЫЕ настройки trailing stop
        self.trailing_percent = 0.005  # 0.5% от пика
        self.activation_profit = 0.012  # Активируем при +1.2%
        self.partial_sell_percent = 0.70  # 🔧 УВЕЛИЧЕНО до 70% вместо 30%

        # 🆕 НОВЫЕ настройки для быстрого исполнения
        self.min_order_size_doge = 5.0  # Минимум 5 DOGE для ордера
        self.aggressive_sell_discount = 0.002  # 0.2% скидка для быстрой продажи
        self.double_check_enabled = True  # Двойная проверка перед продажей
        self.double_check_delay = 0.1  # 100ms задержка для проверки

        # Состояние для каждой валюты
        self.positions: Dict[str, TrailingState] = {}

        # Создаем директорию и загружаем состояние
        os.makedirs(data_dir, exist_ok=True)
        self.load_state()

        self.logger.info("🎯 TrailingStopManager инициализирован (FAST EXECUTION)")
        self.logger.info(f"   Trailing: {self.trailing_percent * 100:.1f}% от пика")
        self.logger.info(f"   Активация: {self.activation_profit * 100:.1f}%")
        self.logger.info(f"   Частичная продажа: {self.partial_sell_percent * 100:.0f}%")
        self.logger.info(f"   Агрессивная скидка: {self.aggressive_sell_discount * 100:.1f}%")

    def load_state(self) -> None:
        """📂 Загрузка состояния из файла"""
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    data = json.load(f)

                for currency, state_data in data.items():
                    self.positions[currency] = TrailingState.from_dict(state_data)

                self.logger.info(f"📂 Загружено {len(self.positions)} trailing позиций")
            else:
                self.logger.info("📂 Файл состояния не найден, начинаем с пустого")

        except Exception as e:
            self.logger.error(f"❌ Ошибка загрузки состояния: {e}")
            self.positions = {}

    def save_state(self) -> None:
        """💾 Сохранение состояния в файл"""
        try:
            data = {}
            for currency, state in self.positions.items():
                data[currency] = state.to_dict()

            with open(self.state_file, 'w') as f:
                json.dump(data, f, indent=2)

        except Exception as e:
            self.logger.error(f"❌ Ошибка сохранения состояния: {e}")

    def update_position(self, currency: str, current_price: float, entry_price: float,
                        total_quantity: float, get_fresh_price_callback=None) -> Tuple[bool, float, str]:
        """🔄 Обновление trailing stop позиции с коллбэком для свежей цены"""

        profit_percent = (current_price - entry_price) / entry_price

        # Инициализируем позицию если нет
        if currency not in self.positions:
            self.positions[currency] = TrailingState(
                entry_price=entry_price,
                total_quantity=total_quantity,
                remaining_quantity=total_quantity
            )

        state = self.positions[currency]

        # Обновляем состояние
        state.current_price = current_price
        state.last_update = datetime.now()

        self.logger.info(f"🎯 Trailing анализ {currency}:")
        self.logger.info(f"   Текущая цена: {current_price:.8f}")
        self.logger.info(f"   Прибыль: {profit_percent * 100:+.2f}%")
        self.logger.info(f"   Статус: {state.status}")
        self.logger.info(f"   Остается: {state.remaining_quantity:.4f}")

        # 🚀 УЛУЧШЕННАЯ логика trailing stop
        should_sell, sell_quantity, reason = self._process_trailing_logic_fast(
            state, current_price, profit_percent, get_fresh_price_callback
        )

        if should_sell:
            # Обновляем состояние после продажи
            state.remaining_quantity -= sell_quantity

            if state.remaining_quantity <= 0.001:  # Позиция закрыта
                del self.positions[currency]
                self.logger.info(f"🏁 Trailing позиция {currency} полностью закрыта")

        # Сохраняем состояние
        self.save_state()

        return should_sell, sell_quantity, reason

    def _process_trailing_logic_fast(self, state: TrailingState, current_price: float,
                                     profit_percent: float, get_fresh_price_callback=None) -> Tuple[bool, float, str]:
        """🚀 БЫСТРАЯ логика trailing stop с двойной проверкой"""

        # Этап 1: Частичная продажа при достижении цели
        if (state.status == "waiting" and
                profit_percent >= self.activation_profit and
                not state.partial_sell_done):

            sell_quantity = state.total_quantity * self.partial_sell_percent

            # 🔧 ПРОВЕРКА минимального размера ордера
            if sell_quantity < self.min_order_size_doge:
                self.logger.warning(f"⚠️ Частичная продажа {sell_quantity:.2f} < минимума {self.min_order_size_doge}")
                self.logger.info(f"💡 Переходим сразу к trailing всей позиции")

                # Переходим к trailing всей позиции
                state.status = "trailing"
                state.peak_price = current_price
                # НЕ помечаем partial_sell_done = True

                return False, 0.0, "Размер частичной продажи слишком мал, используем только trailing"

            # Обычная частичная продажа
            state.status = "trailing"
            state.partial_sell_done = True
            state.peak_price = current_price

            self.logger.info(f"🎯 ЧАСТИЧНАЯ ПРОДАЖА АКТИВИРОВАНА!")
            self.logger.info(f"   Прибыль: {profit_percent * 100:.2f}%")
            self.logger.info(f"   Продаем: {sell_quantity:.4f} ({self.partial_sell_percent * 100:.0f}%)")

            # 🚀 Возвращаем команду для агрессивной продажи
            return True, sell_quantity, f"AGGRESSIVE_SELL:{current_price:.8f}:Частичная продажа при +{profit_percent * 100:.1f}%"

        # Этап 2: Trailing stop для оставшейся позиции
        if state.status == "trailing":

            # Обновляем пик
            if current_price > state.peak_price:
                old_peak = state.peak_price
                state.peak_price = current_price

                self.logger.info(f"📈 Новый пик: {old_peak:.8f} → {state.peak_price:.8f}")

            # Проверяем trailing stop
            trailing_stop_price = state.peak_price * (1 - self.trailing_percent)
            distance_from_peak = (state.peak_price - current_price) / state.peak_price * 100

            self.logger.info(f"🎯 Trailing мониторинг:")
            self.logger.info(f"   Пик: {state.peak_price:.8f}")
            self.logger.info(f"   Стоп: {trailing_stop_price:.8f}")
            self.logger.info(f"   Дистанция от пика: {distance_from_peak:.2f}%")

            if current_price <= trailing_stop_price:

                # 🔍 ДВОЙНАЯ ПРОВЕРКА с свежей ценой
                if self.double_check_enabled and get_fresh_price_callback:
                    self.logger.info(f"🔍 Двойная проверка trailing stop...")
                    time.sleep(self.double_check_delay)

                    fresh_price = get_fresh_price_callback()
                    if fresh_price and fresh_price > 0:
                        fresh_stop_price = state.peak_price * (1 - self.trailing_percent)
                        fresh_distance = (state.peak_price - fresh_price) / state.peak_price * 100

                        self.logger.info(f"   Свежая цена: {fresh_price:.8f}")
                        self.logger.info(f"   Свежий стоп: {fresh_stop_price:.8f}")
                        self.logger.info(f"   Свежая дистанция: {fresh_distance:.2f}%")

                        if fresh_price > fresh_stop_price:
                            self.logger.info(f"❌ Отменено: цена восстановилась")
                            return False, 0.0, "Trailing stop отменен - цена восстановилась"

                        # Используем свежую цену для расчета
                        current_price = fresh_price
                        distance_from_peak = fresh_distance

                sell_quantity = state.remaining_quantity

                self.logger.info(f"🚨 TRAILING STOP СРАБОТАЛ!")
                self.logger.info(f"   Продаем остаток: {sell_quantity:.4f}")

                # 🚀 Возвращаем команду для максимально агрессивной продажи
                return True, sell_quantity, f"MARKET_SELL:{current_price:.8f}:Trailing stop: пик {state.peak_price:.6f}, падение {distance_from_peak:.1f}%"

        return False, 0.0, "Trailing продолжается"

    def calculate_adaptive_sell_price(self, current_price: float, order_type: str = "normal") -> float:
        """📊 Адаптивный расчет цены продажи"""

        if order_type == "AGGRESSIVE_SELL":
            # Частичная продажа - умеренная агрессивность
            discount = 0.001  # 0.1%
        elif order_type == "MARKET_SELL":
            # Trailing stop - максимальная агрессивность
            discount = self.aggressive_sell_discount  # 0.2%
        else:
            # Обычная продажа
            discount = 0.0002  # 0.02%

        return current_price * (1 - discount)

    def reset_position(self, currency: str) -> None:
        """🔄 Сброс trailing позиции"""
        if currency in self.positions:
            del self.positions[currency]
            self.save_state()
            self.logger.info(f"🔄 Trailing позиция {currency} сброшена")

    def get_status(self, currency: str) -> Dict[str, Any]:
        """📊 Получение статуса trailing позиции"""
        if currency not in self.positions:
            return {'active': False}

        state = self.positions[currency]
        return {
            'active': True,
            'status': state.status,
            'entry_price': state.entry_price,
            'peak_price': state.peak_price,
            'current_price': state.current_price,
            'total_quantity': state.total_quantity,
            'remaining_quantity': state.remaining_quantity,
            'partial_sell_done': state.partial_sell_done,
            'trailing_stop_price': state.peak_price * (1 - self.trailing_percent) if state.peak_price else 0
        }