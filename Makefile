# 🛠️ Makefile для торгового бота

.PHONY: help install test lint format clean run

help: ## Показать помощь
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Установить зависимости
	pip install -r requirements.txt
	pip install -r requirements-dev.txt

test: ## Запустить тесты
	pytest tests/ -v

test-unit: ## Запустить только unit тесты
	pytest tests/unit/ -v -m unit

test-integration: ## Запустить только integration тесты
	pytest tests/integration/ -v -m integration

test-coverage: ## Запустить тесты с покрытием
	pytest tests/ --cov=src --cov-report=html --cov-report=term-missing

lint: ## Проверить код линтерами
	flake8 src/ tests/
	black --check src/ tests/

format: ## Отформатировать код
	black src/ tests/
	isort src/ tests/

clean: ## Очистить временные файлы
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
	rm -rf .pytest_cache/
	rm -rf htmlcov/
	rm -rf .coverage

run: ## Запустить бота в paper режиме
	python main.py --mode paper

validate: ## Проверить конфигурацию
	python main.py --validate

diagnostic: ## Запустить диагностику
	python scripts/diagnostic.py

stats: ## Показать торговую статистику
	python scripts/analyze_trading_stats.py --days 30

docker-build: ## Собрать Docker образ
	docker build -t doge-trading-bot:latest .

docker-run: ## Запустить в Docker
	docker-compose up -d

setup-dev: ## Настроить среду разработки
	python -m venv venv
	@echo "✅ Виртуальная среда создана"
	@echo "Активируйте: source venv/bin/activate (Linux/Mac) или venv\Scripts\activate (Windows)"
	@echo "Затем запустите: make install"
