"""
🔇 Умная система логирования для крипто-бота
Подавляет повторяющиеся сообщения и спам
"""

import logging
import time
import re
from typing import Dict
from datetime import datetime

class SmartLogger:
    """🧠 Умный логгер с фильтрацией спама"""

    def __init__(self, logger_name: str):
        self.logger = logging.getLogger(logger_name)
        self.last_logged = {}
        self.message_counts = {}
        self.last_aggregation = time.time()

    def info_if_changed(self, key: str, message: str, threshold: float = 0.01):
        """📊 Логируем только при значительных изменениях"""
        current_time = time.time()

        # Извлекаем численные значения
        try:
            numbers = re.findall(r'-?\\d+\\.?\\d*', message)
            if numbers:
                current_value = float(numbers[-1])

                if key in self.last_logged:
                    last_value = self.last_logged[key]['value']
                    if abs(current_value - last_value) < threshold:
                        return  # Изменение незначительное

                self.last_logged[key] = {
                    'value': current_value,
                    'time': current_time
                }
        except:
            pass

        self.logger.info(message)

    def count_message(self, message_type: str):
        """📊 Подсчет повторяющихся сообщений"""
        self.message_counts[message_type] = self.message_counts.get(message_type, 0) + 1

        # Отчет каждые 5 минут
        if time.time() - self.last_aggregation > 300:
            self._log_aggregated_counts()
            self.last_aggregation = time.time()

    def _log_aggregated_counts(self):
        """📋 Агрегированная отчетность"""
        if not self.message_counts:
            return

        total = sum(self.message_counts.values())
        if total > 20:  # Логируем только если было много событий
            self.logger.info(f"📊 За 5 мин: {total} технических событий")

            # Показываем только самые частые
            for msg_type, count in sorted(self.message_counts.items(),
                                        key=lambda x: x[1], reverse=True)[:3]:
                if count > 10:
                    self.logger.info(f"   • {msg_type}: {count}")

        self.message_counts.clear()

    def debug_throttled(self, message: str, throttle_seconds: int = 60):
        """🐛 Debug с ограничением частоты"""
        message_hash = hash(message)
        current_time = time.time()

        if message_hash in self.last_logged:
            if current_time - self.last_logged[message_hash]['time'] < throttle_seconds:
                return

        self.last_logged[message_hash] = {'time': current_time}
        self.logger.debug(message)

class QuietRateLimiter:
    """🔇 Тихий rate limiter"""

    def __init__(self, original_rate_limiter):
        self.rate_limiter = original_rate_limiter
        self.smart_logger = SmartLogger("rate_limiter")
        self.wait_counts = {}
        self.last_report = time.time()

    def wait_if_needed(self, request_type: str) -> float:
        """⏳ Ожидание с минимальным логированием"""
        wait_time = self.rate_limiter.wait_if_needed(request_type)

        if wait_time > 0:
            self.wait_counts[request_type] = self.wait_counts.get(request_type, 0) + 1

            # Логируем только долгие ожидания
            if wait_time > 2.0:
                self.smart_logger.logger.warning(
                    f"⏳ Долгое ожидание {request_type}: {wait_time:.1f}с"
                )

        # Периодический отчет
        if time.time() - self.last_report > 300:
            self._report_wait_stats()
            self.last_report = time.time()

        return wait_time

    def _report_wait_stats(self):
        """📊 Отчет по ожиданиям"""
        if not self.wait_counts:
            return

        total_waits = sum(self.wait_counts.values())
        if total_waits > 50:
            self.smart_logger.logger.info(
                f"⏳ Rate limit за 5 мин: {total_waits} ожиданий"
            )
            self.wait_counts.clear()

def setup_optimized_logging():
    """🔧 Настройка оптимизированного логирования"""
    import logging.handlers

    # Основной лог с ротацией
    main_handler = logging.handlers.RotatingFileHandler(
        'trading_bot.log',
        maxBytes=10*1024*1024,  # 10MB
        backupCount=3
    )
    main_handler.setLevel(logging.INFO)

    # Debug лог на 1 день
    debug_handler = logging.handlers.TimedRotatingFileHandler(
        'debug.log',
        when='D',
        interval=1,
        backupCount=1
    )
    debug_handler.setLevel(logging.DEBUG)

    # Console handler для важных сообщений
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)

    # Форматирование
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    main_handler.setFormatter(formatter)
    debug_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    # Применяем к root логгеру
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.handlers.clear()
    root_logger.addHandler(main_handler)
    root_logger.addHandler(debug_handler)
    root_logger.addHandler(console_handler)

    print("✅ Оптимизированное логирование настроено")

# Патчи для существующих классов
def patch_existing_logger(bot_instance):
    """🔧 Патч существующего логгера бота"""

    # Заменяем обычный логгер на умный
    if hasattr(bot_instance, 'logger'):
        bot_instance.smart_logger = SmartLogger(bot_instance.__class__.__name__)

        # Сохраняем оригинальные методы
        original_info = bot_instance.logger.info
        original_debug = bot_instance.logger.debug

        # Перехватываем частые сообщения
        def smart_info(message, *args, **kwargs):
            if "Rate limit" in str(message):
                bot_instance.smart_logger.count_message("rate_limit")
                return
            elif "P&L:" in str(message):
                bot_instance.smart_logger.info_if_changed("pnl", str(message), 0.01)
                return
            elif "Цена:" in str(message):
                bot_instance.smart_logger.info_if_changed("price", str(message), 0.005)
                return

            original_info(message, *args, **kwargs)

        def smart_debug(message, *args, **kwargs):
            bot_instance.smart_logger.debug_throttled(str(message))

        # Заменяем методы
        bot_instance.logger.info = smart_info
        bot_instance.logger.debug = smart_debug

if __name__ == "__main__":
    # Тестирование
    setup_optimized_logging()

    smart_logger = SmartLogger("test")

    print("🧪 Тест умного логгера...")

    # Тестируем фильтрацию
    for i in range(10):
        smart_logger.info_if_changed("price", f"Цена: 0.189{i%2}")  # Только 2 лога
        smart_logger.count_message("rate_limit")  # Будет агрегировано

    print("✅ Тест завершен")
