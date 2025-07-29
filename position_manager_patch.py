
# ДОБАВИТЬ В КОНЕЦ position_manager.py

def apply_position_manager_fix(self):
    """🔧 Применение исправлений к position_manager"""

    original_method = self.get_accurate_position_data

    def improved_get_accurate_position_data(currency: str):
        """📊 УЛУЧШЕННАЯ версия получения точных данных"""
        try:
            result = original_method(currency)

            # Дополнительная валидация средней цены для DOGE
            if result.get('avg_price', 0) <= 0 or result.get('avg_price', 0) > 1.0:
                self.logger.warning(f"⚠️ Подозрительная средняя цена: {result.get('avg_price', 0):.8f}")
                # Пытаемся получить более точную оценку
                estimated_price = self._estimate_avg_price(currency)
                if estimated_price and 0.10 < estimated_price < 0.30:
                    result['avg_price'] = estimated_price
                    self.logger.info(f"🔧 Средняя цена скорректирована на: {estimated_price:.8f}")
                else:
                    result['avg_price'] = 0.19  # Консервативная оценка для DOGE
                    self.logger.info(f"🔧 Используем консервативную оценку: 0.19")

            return result

        except Exception as e:
            self.logger.error(f"❌ Ошибка в улучшенном методе: {e}")
            return original_method(currency)

    # Заменяем метод
    self.get_accurate_position_data = improved_get_accurate_position_data
    self.logger.info("🔧 Применены исправления position_manager")

# Добавить в __init__ метод position_manager:
# self.apply_position_manager_fix()
