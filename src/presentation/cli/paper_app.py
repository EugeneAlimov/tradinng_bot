# src/presentation/cli/paper_app.py
"""
Обёртка для paper-режима.
- Импортирует основное CLI: src.presentation.cli.app
- Принудительно добавляет команду: trade-live --mode paper
- Сохраняет все остальные флаги пользователя как есть
- Имеет main(), который возвращает вызываемый объект (для твоего теста assert callable(main()))
"""

from __future__ import annotations

import sys
from typing import List

from src.presentation.cli import app as app_cli  # используем наше ядро


def _strip_mode(argv: List[str]) -> List[str]:
    """Удаляем любые пользовательские --mode XYZ, чтобы не конфликтовало с paper."""
    out: List[str] = []
    skip_next = False
    for i, a in enumerate(argv):
        if skip_next:
            skip_next = False
            continue
        if a == "--mode":
            # пропустить сам флаг и его значение
            skip_next = True
            continue
        if a.startswith("--mode="):
            # пропустить целиком
            continue
        # не позволяем пользователю самому подставить подкоманду
        if a == "trade-live":
            # пропускаем, мы сами добавим правильную подкоманду
            continue
        out.append(a)
    return out


def run(argv: List[str] | None = None) -> int:
    """
    Реальный раннер. Пример:
      python -m src.presentation.cli.paper_app --strategy ema_adx ... (любые флаги)
    """
    user_argv = list(sys.argv[1:] if argv is None else argv)
    forwarded = ["trade-live", "--mode", "paper"] + _strip_mode(user_argv)
    # Передаём в общее ядро CLI
    return app_cli._run_cli(forwarded)


def main():
    """
    Совместимость с твоим тестом:
      python -c "from src.presentation.cli.paper_app import main; assert callable(main())"
    main() возвращает вызываемый объект (функцию), но сам запуск — по желанию.
    """
    return run


if __name__ == "__main__":
    sys.exit(run())
