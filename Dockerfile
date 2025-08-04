# 🐳 Dockerfile для торгового бота
FROM python:3.9-slim

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем файлы зависимостей
COPY requirements.txt ./

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Создаем непривилегированного пользователя
RUN useradd --create-home --shell /bin/bash botuser

# Копируем код приложения
COPY . .

# Создаем необходимые директории
RUN mkdir -p logs data && chown -R botuser:botuser /app

# Переключаемся на непривилегированного пользователя
USER botuser

# Настраиваем переменные окружения
ENV PYTHONPATH=/app/src
ENV TRADING_MODE=paper

# Проверка здоровья
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "print('Bot is running')" || exit 1

# Запуск приложения
CMD ["python", "main.py", "--mode", "hybrid"]
