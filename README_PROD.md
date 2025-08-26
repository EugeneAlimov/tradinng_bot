# Production Pipeline (CLI-first)

## Быстрый старт
```bash
# Убедись, что корень проекта в PYTHONPATH
export PYTHONPATH=.

# Health check
python tools/immediate_actions.py --health

# День 1: полный sweep + анализ
python tools/immediate_actions.py --day1

# День 2: robustness + walk-forward + анализ
python tools/immediate_actions.py --day2

# День 3: создать конфиг для paper и подготовиться к тесту
python tools/immediate_actions.py --day3

# Тестовый paper трейдинг с авто-стопом через 60 минут
python tools/immediate_actions.py --paper-test --minutes 60
