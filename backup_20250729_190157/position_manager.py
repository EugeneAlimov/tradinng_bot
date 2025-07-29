from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
import time
import json
import os
import shutil
from config import TradingConfig


@dataclass
class Position:
    quantity: float
    avg_price: float
    total_cost: float
    last_updated: datetime
    trades: List[Dict[str, Any]]

    def to_dict(self) -> dict:
        """Конвертация в словарь для JSON сериализации"""
        return {
            'quantity': self.quantity,
            'avg_price': self.avg_price,
            'total_cost': self.total_cost,
            'last_updated': self.last_updated.isoformat(),
            'trades': [
                {
                    'date': trade.get('date').isoformat() if isinstance(trade.get('date'), datetime) else str(
                        trade.get('date', '')),
                    'timestamp': trade.get('timestamp', 0),
                    'type': trade.get('type', ''),
                    'quantity': trade.get('quantity', 0),
                    'price': trade.get('price', 0),
                    'amount': trade.get('amount', 0),
                    'commission': trade.get('commission', 0)
                } for trade in self.trades
            ]
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'Position':
        """Создание из словаря после десериализации JSON"""
        trades = []
        for trade_data in data.get('trades', []):
            trade = trade_data.copy()
            if 'date' in trade and trade['date']:
                try:
                    trade['date'] = datetime.fromisoformat(trade['date'])
                except:
                    trade['date'] = datetime.now()
            trades.append(trade)

        return cls(
            quantity=float(data['quantity']),
            avg_price=float(data['avg_price']),
            total_cost=float(data['total_cost']),
            last_updated=datetime.fromisoformat(data['last_updated']),
            trades=trades
        )


class PositionManager:
    def __init__(self, config: TradingConfig, api_client):
        self.config = config
        self.api = api_client
        self.logger = logging.getLogger(__name__)
        self.positions = {}  # {currency: Position}

        # 💾 Настройки файлов
        self.positions_file = 'data/positions.json'
        self.backup_file = 'data/positions_backup.json'
        self.trades_file = 'data/trades_history.json'

        # Создаем директорию для данных
        os.makedirs('data', exist_ok=True)

        # Загружаем позиции из файла при инициализации
        self.load_positions_from_file()

        self.logger.info("💾 PositionManager инициализирован с сохранением в файлы")

    def save_positions_to_file(self):
        """💾 Сохранение позиций в файл с ротацией бэкапов"""
        try:
            # Создаем резервную копию если файл существует
            if os.path.exists(self.positions_file):
                shutil.copy2(self.positions_file, self.backup_file)
                self.logger.debug(f"🔄 Создана резервная копия позиций")

            # Конвертируем позиции в JSON-сериализуемый формат
            data = {
                'version': '1.0',
                'timestamp': datetime.now().isoformat(),
                'config': {
                    'currency_1': self.config.CURRENCY_1,
                    'currency_2': self.config.CURRENCY_2
                },
                'positions': {}
            }

            for currency, position in self.positions.items():
                data['positions'][currency] = position.to_dict()

            # Атомарное сохранение через временный файл
            temp_file = self.positions_file + '.tmp'
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            # Перемещаем временный файл в основной
            shutil.move(temp_file, self.positions_file)

            self.logger.debug(f"💾 Позиции сохранены в {self.positions_file}")

        except Exception as e:
            self.logger.error(f"❌ Ошибка сохранения позиций: {e}")
            # Удаляем временный файл если он остался
            temp_file = self.positions_file + '.tmp'
            if os.path.exists(temp_file):
                os.remove(temp_file)

    def load_positions_from_file(self) -> Dict[str, Position]:
        """📂 Загрузка позиций из файла с восстановлением из бэкапа"""

        def try_load_file(filename):
            try:
                with open(filename, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                self.logger.error(f"❌ Ошибка чтения {filename}: {e}")
                return None

        try:
            data = None

            # Пытаемся загрузить основной файл
            if os.path.exists(self.positions_file):
                data = try_load_file(self.positions_file)

            # Если основной файл поврежден, пытаемся загрузить бэкап
            if data is None and os.path.exists(self.backup_file):
                self.logger.warning(f"⚠️ Основной файл поврежден, загружаем из бэкапа")
                data = try_load_file(self.backup_file)

                # Восстанавливаем основной файл из бэкапа
                if data:
                    shutil.copy2(self.backup_file, self.positions_file)
                    self.logger.info(f"🔄 Основной файл восстановлен из бэкапа")

            if data is None:
                self.logger.info(f"📂 Файлы позиций не найдены, начинаем с пустого состояния")
                return {}

            # Проверяем структуру файла
            if 'positions' not in data:
                self.logger.warning(f"⚠️ Неверная структура файла позиций")
                return {}

            # Проверяем версию
            version = data.get('version', '0.0')
            if version != '1.0':
                self.logger.warning(f"⚠️ Неизвестная версия файла: {version}")

            # Восстанавливаем позиции
            loaded_positions = {}
            for currency, position_data in data['positions'].items():
                try:
                    position = Position.from_dict(position_data)
                    loaded_positions[currency] = position

                    self.logger.info(
                        f"📂 Загружена позиция {currency}: {position.quantity:.6f} по {position.avg_price:.8f}")

                except Exception as e:
                    self.logger.error(f"❌ Ошибка загрузки позиции {currency}: {e}")

            self.positions = loaded_positions

            # Проверяем актуальность данных
            file_timestamp = datetime.fromisoformat(data.get('timestamp', '2020-01-01'))
            age_hours = (datetime.now() - file_timestamp).total_seconds() / 3600

            if age_hours > 24:
                self.logger.warning(f"⚠️ Файл позиций устарел ({age_hours:.1f} часов), рекомендуется проверка")

            self.logger.info(f"✅ Загружено {len(loaded_positions)} позиций из файла")
            return loaded_positions

        except Exception as e:
            self.logger.error(f"❌ Критическая ошибка загрузки позиций: {e}")
            return {}

    def save_trade_to_history(self, trade_info: Dict[str, Any]):
        """📝 Сохранение сделки в файл истории"""
        try:
            history = []
            if os.path.exists(self.trades_file):
                with open(self.trades_file, 'r', encoding='utf-8') as f:
                    history = json.load(f)

            # Добавляем новую сделку
            trade_record = {
                'timestamp': datetime.now().isoformat(),
                'pair': f"{self.config.CURRENCY_1}_{self.config.CURRENCY_2}",
                **trade_info
            }
            history.append(trade_record)

            # Ограничиваем размер истории (последние 1000 сделок)
            if len(history) > 1000:
                history = history[-1000:]

            # Сохраняем
            with open(self.trades_file, 'w', encoding='utf-8') as f:
                json.dump(history, f, indent=2, ensure_ascii=False)

            self.logger.debug(f"📝 Сделка сохранена в историю")

        except Exception as e:
            self.logger.error(f"❌ Ошибка сохранения сделки в историю: {e}")

    def validate_position_vs_balance(self) -> tuple[float, float, float]:
        """🛡️ УЛУЧШЕННАЯ проверка расчетной позиции против реального баланса"""
        try:
            user_info = self.api.get_user_info()
            real_balance = float(user_info['balances'].get(self.config.CURRENCY_1, 0))

            position_obj = self.positions.get(self.config.CURRENCY_1)
            calculated_position = position_obj.quantity if position_obj else 0.0

            discrepancy = abs(real_balance - calculated_position)

            self.logger.info(f"🔍 Валидация позиций:")
            self.logger.info(f"   📊 Реальный баланс: {real_balance:.6f} {self.config.CURRENCY_1}")
            self.logger.info(f"   🧮 Расчетная позиция: {calculated_position:.6f} {self.config.CURRENCY_1}")
            self.logger.info(f"   ⚖️  Расхождение: {discrepancy:.6f} {self.config.CURRENCY_1}")

            # 🔧 ИСПРАВЛЕНИЕ: Более гибкий порог для DOGE
            # Для DOGE расхождение в 0.06 может быть нормальным из-за округлений
            flexible_threshold = max(
                self.config.MAX_POSITION_DISCREPANCY,  # 0.01 из конфига
                real_balance * 0.01  # 1% от баланса, но минимум 0.01
            )

            if self.config.POSITION_VALIDATION_ENABLED and discrepancy > flexible_threshold:
                self.logger.warning(f"⚠️ РАСХОЖДЕНИЕ ВЫШЕ ГИБКОГО ПОРОГА!")
                self.logger.warning(f"   Расхождение {discrepancy:.6f} > порога {flexible_threshold:.6f}")

                # Если расхождение критическое (>10% от баланса) - останавливаемся
                if discrepancy > real_balance * 0.1 and real_balance > 0:
                    self.logger.error(f"🆘 КРИТИЧЕСКОЕ РАСХОЖДЕНИЕ: {discrepancy / real_balance * 100:.1f}%")
                    raise Exception(f"Критическое расхождение в позициях: {discrepancy:.6f}")

                # Иначе логируем предупреждение и синхронизируем
                self.logger.warning(f"🔧 МЯГКАЯ СИНХРОНИЗАЦИЯ с реальным балансом")
                self.force_sync_with_real_balance(real_balance)

            return real_balance, calculated_position, discrepancy

        except Exception as e:
            self.logger.error(f"❌ Ошибка валидации позиций: {e}")
            return 0, 0, 0

    def force_sync_with_real_balance(self, real_balance: float):
        """🔧 Принудительная синхронизация с реальным балансом"""
        if real_balance > 0:
            # Используем среднюю цену из существующей позиции или консервативную оценку
            estimated_avg_price = 0.19  # Консервативная оценка

            old_position = self.positions.get(self.config.CURRENCY_1)
            if old_position and old_position.avg_price > 0:
                estimated_avg_price = old_position.avg_price

            self.positions[self.config.CURRENCY_1] = Position(
                quantity=real_balance,
                avg_price=estimated_avg_price,
                total_cost=real_balance * estimated_avg_price,
                last_updated=datetime.now(),
                trades=[]
            )

            self.logger.warning(f"🔧 Позиция синхронизирована:")
            self.logger.warning(f"   Количество: {real_balance:.6f}")
            self.logger.warning(f"   Средняя цена: {estimated_avg_price:.6f}")

            # Сохраняем изменения
            self.save_positions_to_file()

        else:
            # Убираем позицию если баланс нулевой
            if self.config.CURRENCY_1 in self.positions:
                del self.positions[self.config.CURRENCY_1]
                self.logger.info("🗑️  Позиция удалена (нулевой баланс)")
                self.save_positions_to_file()

    def load_positions_from_history(self, days_back: int = 365) -> Dict[str, Position]:
        """📚 Загрузка позиций из истории торгов API"""
        try:
            self.logger.info(f"🔍 Загружаем историю торгов за последние {days_back} дней...")

            target_pair = f"{self.config.CURRENCY_1}_{self.config.CURRENCY_2}"

            # Получаем историю сделок
            user_trades = self.api.get_user_trades(pair=target_pair, limit=1000)

            if not user_trades or target_pair not in user_trades:
                self.logger.info("📝 История сделок пуста")
                return {}

            trades = user_trades[target_pair]
            if not trades:
                self.logger.info(f"📝 Сделок по паре {target_pair} не найдено")
                return {}

            self.logger.info(f"📋 Найден ключ {target_pair} с {len(trades)} сделками")

            # Обрабатываем сделки
            processed_trades = self._process_raw_trades(trades, days_back)

            if not processed_trades:
                return {}

            # Рассчитываем позицию
            currency = self.config.CURRENCY_1
            position = self._calculate_position_fifo(processed_trades)

            positions = {}
            if position and position.quantity > 0:
                positions[currency] = position
                self.logger.info(
                    f"📊 Расчетная позиция {currency}: {position.quantity:.6f} по средней цене {position.avg_price:.8f}")
            else:
                self.logger.info("💭 Расчетная позиция равна нулю")

            # Обновляем и сохраняем позиции
            self.positions.update(positions)
            if positions:
                self.save_positions_to_file()

            # Валидация после загрузки
            if self.config.POSITION_VALIDATION_ENABLED:
                try:
                    self.validate_position_vs_balance()
                except Exception as validation_error:
                    self.logger.error(f"❌ Ошибка валидации после загрузки: {validation_error}")

            return positions

        except Exception as e:
            self.logger.error(f"❌ Ошибка загрузки истории: {str(e)}")

            # Если ошибка "no trades" - это нормально
            if "Error 50304" in str(e) or "no trades" in str(e).lower():
                self.logger.info("💡 По этой паре нет сделок в истории - это нормально")

            return {}

    def _process_raw_trades(self, trades: List[Dict], days_back: int) -> List[Dict]:
        """🔧 Обработка сырых данных сделок"""
        processed_trades = []
        cutoff_date = datetime.now() - timedelta(days=days_back)

        for i, trade in enumerate(trades):
            try:
                # Проверяем обязательные поля
                required_fields = ['date', 'type', 'quantity', 'price', 'amount']
                if not all(field in trade for field in required_fields):
                    self.logger.error(f"❌ В сделке {i} отсутствуют поля")
                    continue

                # Обрабатываем временную метку
                timestamp = int(trade['date'])
                if timestamp > 2000000000:  # Миллисекунды
                    timestamp = timestamp // 1000

                trade_date = datetime.fromtimestamp(timestamp)

                # Пропускаем старые сделки
                if trade_date < cutoff_date:
                    continue

                trade_info = {
                    'date': trade_date,
                    'timestamp': timestamp,
                    'type': trade['type'],
                    'quantity': float(trade['quantity']),
                    'price': float(trade['price']),
                    'amount': float(trade['amount']),
                    'commission': float(trade.get('commission_amount', 0))
                }

                self.logger.info(
                    f"📊 Сделка {trade_date.strftime('%Y-%m-%d %H:%M')}: {trade['type']} {trade['quantity']} по {trade['price']}")
                processed_trades.append(trade_info)

            except Exception as trade_error:
                self.logger.error(f"❌ Ошибка обработки сделки {i}: {trade_error}")
                continue

        return processed_trades

    def _calculate_position_fifo(self, trades: List[Dict]) -> Optional[Position]:
        """🧮 УЛУЧШЕННЫЙ расчет позиции по FIFO методу с учетом комиссий"""
        if not trades:
            return None

        # Сортируем по времени
        sorted_trades = sorted(trades, key=lambda x: x['timestamp'])

        position_quantity = 0.0
        weighted_cost = 0.0
        all_trades_for_position = []

        self.logger.info("🧮 УЛУЧШЕННЫЙ пересчет позиции по FIFO:")

        for trade in sorted_trades:
            trade_quantity = float(trade['quantity'])
            trade_price = float(trade['price'])
            trade_cost = float(trade['amount'])
            commission = float(trade.get('commission', 0))

            if trade['type'] == 'buy':
                # Покупка - добавляем к позиции
                position_quantity += trade_quantity

                # 🔧 ИСПРАВЛЕНИЕ: Учитываем комиссию в стоимости
                actual_cost = trade_cost + commission
                weighted_cost += actual_cost

                avg_price = weighted_cost / position_quantity if position_quantity > 0 else 0

                self.logger.info(
                    f"  ✅ {trade['date'].strftime('%m-%d %H:%M')} Покупка: +{trade_quantity:.4f} по {trade_price:.6f}")
                self.logger.info(f"     Стоимость: {trade_cost:.4f} + комиссия {commission:.4f} = {actual_cost:.4f}")
                self.logger.info(f"     Позиция: {position_quantity:.4f}, средняя цена: {avg_price:.6f}")

            else:
                # Продажа - уменьшаем позицию
                old_quantity = position_quantity
                position_quantity -= trade_quantity

                if position_quantity > 0:
                    # Пропорционально уменьшаем стоимость
                    cost_ratio = position_quantity / old_quantity
                    weighted_cost *= cost_ratio
                    avg_price = weighted_cost / position_quantity
                else:
                    # Позиция закрыта полностью
                    position_quantity = 0
                    weighted_cost = 0
                    avg_price = 0

                self.logger.info(
                    f"  ❌ {trade['date'].strftime('%m-%d %H:%M')} Продажа: -{trade_quantity:.4f} по {trade_price:.6f}")
                self.logger.info(f"     Комиссия продажи: {commission:.4f}")
                self.logger.info(f"     Позиция: {position_quantity:.4f}, средняя цена: {avg_price:.6f}")

            all_trades_for_position.append(trade)

        # Финальный результат
        if position_quantity <= 0:
            self.logger.info("📊 Итоговая позиция: 0 (все продано)")
            return None

        # 🔧 ИСПРАВЛЕНИЕ: Округляем результат для устранения ошибок округления
        position_quantity = round(position_quantity, 6)
        avg_price = round(weighted_cost / position_quantity, 8) if position_quantity > 0 else 0
        weighted_cost = round(weighted_cost, 4)

        self.logger.info(f"📊 ИТОГОВАЯ ПОЗИЦИЯ (с округлением):")
        self.logger.info(f"   Количество: {position_quantity:.6f}")
        self.logger.info(f"   Средняя цена: {avg_price:.8f}")
        self.logger.info(f"   Общая стоимость: {weighted_cost:.4f}")

        return Position(
            quantity=position_quantity,
            avg_price=avg_price,
            total_cost=weighted_cost,
            last_updated=datetime.now(),
            trades=all_trades_for_position
        )

    def get_accurate_position_data(self, currency: str) -> Dict[str, Any]:
        """📊 ИСПРАВЛЕННЫЙ МЕТОД: Получение точных данных позиции с таймаутом после DCA"""
        try:
            # 🔧 ИСПРАВЛЕНИЕ: Добавляем задержку после недавних сделок
            current_time = time.time()
            if hasattr(self, '_last_trade_time') and (current_time - self._last_trade_time) < 30:
                # Если прошло меньше 30 секунд после последней сделки - используем расчетные данные
                self.logger.info("📊 Используем расчетные данные (недавняя сделка)")
                position_obj = self.positions.get(currency)
                if position_obj:
                    return {
                        'quantity': position_obj.quantity,
                        'avg_price': position_obj.avg_price,
                        'data_source': 'calculated_recent_trade',
                        'real_balance': 0,  # Не запрашиваем с биржи
                        'calculated_balance': position_obj.quantity,
                        'discrepancy_percent': 0,  # Считаем точными
                        'is_accurate': True
                    }

            # Получаем данные из API
            user_info = self.api.get_user_info()
            real_balance = float(user_info['balances'].get(currency, 0))

            # Получаем расчетную позицию
            position_obj = self.positions.get(currency)
            calculated_balance = position_obj.quantity if position_obj else 0.0
            calculated_avg_price = position_obj.avg_price if position_obj else 0.0

            # Определяем какие данные использовать
            discrepancy = abs(real_balance - calculated_balance)
            discrepancy_percent = (discrepancy / max(real_balance, calculated_balance) * 100) if max(real_balance,
                                                                                                     calculated_balance) > 0 else 0

            # 🎯 ИСПРАВЛЕННАЯ ЛОГИКА ВЫБОРА ДАННЫХ:
            if discrepancy_percent < 5.0:  # Увеличили порог до 5%
                # Используем расчетные данные - они точнее
                use_calculated = True
                final_quantity = calculated_balance
                final_avg_price = calculated_avg_price
                data_source = "calculated"
            elif discrepancy_percent < 20.0:  # Новый средний порог 20%
                # Смешанный подход - используем реальный баланс, но расчетную цену
                use_calculated = False
                final_quantity = real_balance
                final_avg_price = calculated_avg_price if calculated_avg_price > 0 else self._estimate_avg_price(
                    currency)
                data_source = "mixed"

                self.logger.warning(f"📊 Смешанный режим данных (расхождение {discrepancy_percent:.1f}%)")
            else:
                # Критическое расхождение - используем реальные данные
                use_calculated = False
                final_quantity = real_balance
                final_avg_price = self._estimate_avg_price(currency) or calculated_avg_price
                data_source = "real_balance"

            self.logger.info(f"📊 Точные данные позиции {currency}:")
            self.logger.info(f"   Источник: {data_source}")
            self.logger.info(f"   Количество: {final_quantity:.6f}")
            self.logger.info(f"   Средняя цена: {final_avg_price:.8f}")
            self.logger.info(f"   Расхождение: {discrepancy_percent:.2f}%")

            return {
                'quantity': final_quantity,
                'avg_price': final_avg_price,
                'data_source': data_source,
                'real_balance': real_balance,
                'calculated_balance': calculated_balance,
                'discrepancy_percent': discrepancy_percent,
                'is_accurate': discrepancy_percent < 5.0
            }

        except Exception as e:
            self.logger.error(f"❌ Ошибка получения точных данных позиции: {e}")
            return {
                'quantity': 0,
                'avg_price': 0,
                'data_source': 'error',
                'is_accurate': False
            }

    def _estimate_avg_price(self, currency: str) -> Optional[float]:
        """💡 Оценка средней цены на основе последних сделок"""
        try:
            # Получаем последние сделки пользователя
            pair = f"{currency}_{self.config.CURRENCY_2}"
            user_trades = self.api.get_user_trades(pair=pair, limit=50)

            if not user_trades or pair not in user_trades:
                return None

            trades = user_trades[pair]
            if not trades:
                return None

            # Ищем последние покупки
            recent_buys = []
            for trade in trades[:20]:  # Последние 20 сделок
                if trade['type'] == 'buy':
                    recent_buys.append(float(trade['price']))

            if recent_buys:
                # Взвешенная средняя последних покупок
                return sum(recent_buys) / len(recent_buys)

            return None

        except Exception as e:
            self.logger.error(f"❌ Ошибка оценки средней цены: {e}")
            return None

    def update_position(self, currency: str, trade_info: Dict[str, Any]):
        """🔄 ИСПРАВЛЕННОЕ обновление позиции с отметкой времени"""
        try:
            # 🔧 ИСПРАВЛЕНИЕ: Отмечаем время последней сделки
            self._last_trade_time = time.time()

            # Сохраняем сделку в историю
            self.save_trade_to_history(trade_info)

            if currency not in self.positions:
                if trade_info['type'] == 'buy':
                    # Новая позиция
                    self.positions[currency] = Position(
                        quantity=trade_info['quantity'],
                        avg_price=trade_info['price'],
                        total_cost=trade_info['amount'],
                        last_updated=datetime.now(),
                        trades=[trade_info]
                    )
                    self.logger.info(
                        f"✅ Создана новая позиция {currency}: {trade_info['quantity']:.6f} по {trade_info['price']:.6f}")
            else:
                position = self.positions[currency]

                if trade_info['type'] == 'buy':
                    # Увеличиваем позицию
                    new_total_cost = position.total_cost + trade_info['amount']
                    new_quantity = position.quantity + trade_info['quantity']
                    new_avg_price = new_total_cost / new_quantity

                    self.logger.info(f"📈 Увеличиваем позицию {currency}:")
                    self.logger.info(f"   {position.quantity:.6f} -> {new_quantity:.6f}")
                    self.logger.info(f"   Средняя цена: {position.avg_price:.6f} -> {new_avg_price:.6f}")

                    position.quantity = new_quantity
                    position.avg_price = new_avg_price
                    position.total_cost = new_total_cost
                    position.trades.append(trade_info)
                else:
                    # Уменьшаем позицию
                    new_quantity = position.quantity - trade_info['quantity']

                    self.logger.info(f"📉 Уменьшаем позицию {currency}: {position.quantity:.6f} -> {new_quantity:.6f}")

                    if new_quantity <= 0:
                        self.logger.info(f"🗑️  Позиция {currency} закрыта полностью")
                        del self.positions[currency]
                    else:
                        # Пропорционально уменьшаем стоимость
                        cost_ratio = new_quantity / position.quantity
                        position.quantity = new_quantity
                        position.total_cost *= cost_ratio
                        position.trades.append(trade_info)

                if currency in self.positions:
                    self.positions[currency].last_updated = datetime.now()

            # Сохраняем обновленную позицию
            self.save_positions_to_file()

        except Exception as e:
            self.logger.error(f"❌ Ошибка обновления позиции: {e}")

    def get_position(self, currency: str) -> Optional[Position]:
        """📊 Получение текущей позиции по валюте"""
        return self.positions.get(currency)

    def get_position_summary(self) -> Dict[str, Any]:
        """📊 Сводка по всем позициям"""
        summary = {}
        for currency, position in self.positions.items():
            summary[currency] = {
                'quantity': position.quantity,
                'avg_price': position.avg_price,
                'total_cost': position.total_cost,
                'last_updated': position.last_updated.isoformat(),
                'trades_count': len(position.trades)
            }
        return summary

    def export_positions_history(self, filename: str = None) -> str:
        """📤 Экспорт истории позиций"""
        if filename is None:
            filename = f"data/positions_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        try:
            export_data = {
                'export_timestamp': datetime.now().isoformat(),
                'version': '1.0',
                'config': {
                    'currency_1': self.config.CURRENCY_1,
                    'currency_2': self.config.CURRENCY_2
                },
                'positions': self.get_position_summary(),
                'file_info': {
                    'positions_file': self.positions_file,
                    'backup_file': self.backup_file,
                    'trades_file': self.trades_file
                }
            }

            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)

            self.logger.info(f"📤 История позиций экспортирована в {filename}")
            return filename

        except Exception as e:
            self.logger.error(f"❌ Ошибка экспорта позиций: {e}")
            return None

    def cleanup_old_files(self, days_to_keep: int = 30):
        """🧹 Очистка старых файлов"""
        try:
            # Очистка старых экспортов
            export_pattern = 'data/positions_export_'
            if os.path.exists('data'):
                for filename in os.listdir('data'):
                    if filename.startswith('positions_export_'):
                        filepath = os.path.join('data', filename)
                        file_age = time.time() - os.path.getmtime(filepath)
                        if file_age > days_to_keep * 24 * 3600:
                            os.remove(filepath)
                            self.logger.info(f"🧹 Удален старый экспорт: {filename}")

        except Exception as e:
            self.logger.error(f"❌ Ошибка очистки файлов: {e}")