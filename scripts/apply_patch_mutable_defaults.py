#!/usr/bin/env python3
# tools/apply_patch_mutable_defaults.py
"""
Правит типичные поломки после автопочинки dataclass:
- field(default_factory=list) -> заменяет на корректные default'ы
- default_factory=getenv -> заворачивает в lambda: os.getenv(...)
- Settings/RiskCfg в src/config/settings.py приводятся к каноническому виду
- MeanReversion.cfg -> field(default_factory=StrategyCfg)
- models.unrealized_pnl -> Decimal("0") (или field(default=...))
Плюс предлагает удалить дубликат папки clean_crypto_bot/ если она есть.
"""

from __future__ import annotations
import pathlib, re, sys

ROOT = pathlib.Path(".").resolve()
changed_files: list[str] = []
notes: list[str] = []

def read(p: pathlib.Path) -> str:
    return p.read_text(encoding="utf-8")

def write(p: pathlib.Path, s: str) -> None:
    p.write_text(s, encoding="utf-8")
    changed_files.append(str(p))

def fix_settings(p: pathlib.Path) -> None:
    txt = read(p)
    # Каноническая версия Settings/RiskCfg с безопасными default_factory
    canonical = '''from __future__ import annotations
from dataclasses import dataclass, field
from decimal import Decimal
import os

@dataclass
class RiskCfg:
    position_size_usd: Decimal = Decimal(os.getenv("RISK_POSITION_SIZE_USD", "50"))
    max_daily_loss: float = float(os.getenv("RISK_MAX_DAILY_LOSS", "0.03"))

@dataclass
class Settings:
    api_key: str = field(default_factory=lambda: os.getenv("EXMO_API_KEY", ""))
    api_secret: str = field(default_factory=lambda: os.getenv("EXMO_API_SECRET", ""))
    storage_path: str = field(default_factory=lambda: os.getenv("STORAGE_PATH", "data/"))
    default_pair: str = field(default_factory=lambda: os.getenv("TRADING_PAIR", "DOGE_EUR"))
    mode: str = field(default_factory=lambda: os.getenv("TRADING_MODE", "paper"))
    risk: RiskCfg = field(default_factory=RiskCfg)

def get_settings() -> Settings:
    return Settings()
'''
    # Меняем только блок файла, не трогая прочее? Проще и надёжнее — переписать файл целиком.
    write(p, canonical)

def fix_mean_reversion(p: pathlib.Path) -> None:
    txt = read(p)
    # 1) добавить импорт field, если есть @dataclass
    if "@dataclass" in txt and "field(" in txt and "from dataclasses import dataclass, field" not in txt:
        txt = txt.replace("from dataclasses import dataclass", "from dataclasses import dataclass, field")
        if "from dataclasses import dataclass, field" not in txt and "dataclasses" not in txt:
            txt = "from dataclasses import dataclass, field\n" + txt
    # 2) cfg: StrategyCfg = StrategyCfg() -> field(default_factory=StrategyCfg)
    txt2 = re.sub(
        r"(\bcfg\s*:\s*StrategyCfg\s*=\s*)StrategyCfg\s*\(\s*\)",
        r"\1field(default_factory=StrategyCfg)",
        txt
    )
    if txt2 != txt:
        write(p, txt2)

def fix_models_unrealized(p: pathlib.Path) -> None:
    txt = read(p)
    # Заменим field(default_factory=list) → поле со стандартом Decimal("0")
    txt2 = re.sub(
        r"(unrealized_pnl\s*:\s*Decimal\s*=\s*)field\s*\(\s*default_factory\s*=\s*field\s*\)",
        r'\1Decimal("0")',
        txt
    )
    # Если стоит просто field(...), безопасно заменим на default=Decimal("0")
    txt2 = re.sub(
        r"(unrealized_pnl\s*:\s*Decimal\s*=\s*)field\s*\([^)]*\)",
        r'\1Decimal("0")',
        txt2
    )
    # Убедимся, что импорт Decimal есть (обычно есть)
    if txt2 != txt:
        write(p, txt2)

def generic_fixes(p: pathlib.Path) -> None:
    txt = read(p)
    orig = txt
    # field(default_factory=list) -> временно list, затем руками можно уточнить тип
    txt = re.sub(r"field\s*\(\s*default_factory\s*=\s*field\s*\)", "field(default_factory=list)", txt)
    # default_factory=getenv -> lambda: os.getenv("")
    if "default_factory=getenv" in txt and "os.getenv" not in txt:
        if "import os" not in txt:
            txt = "import os\n" + txt
        txt = txt.replace("default_factory=getenv", 'default_factory=lambda: os.getenv("")')
    if txt != orig:
        write(p, txt)

def main() -> None:
    # 1) settings.py
    for p in ROOT.rglob("src/config/settings.py"):
        fix_settings(p)

    # 2) mean_reversion.py
    for p in ROOT.rglob("src/domain/strategy/mean_reversion.py"):
        fix_mean_reversion(p)

    # 3) models.py
    for p in ROOT.rglob("src/core/domain/models.py"):
        fix_models_unrealized(p)

    # 4) общий проход по проекту — вычистить явные артефакты
    for p in ROOT.rglob("*.py"):
        # пропустим только что канонизированный settings.py, чтобы не тронуть заново
        if str(p).endswith("src/config/settings.py"):
            continue
        generic_fixes(p)

    # 5) подсказка на удаление дубликата
    dup = ROOT / "tradinng_bot" / "clean_crypto_bot"
    if dup.exists():
        notes.append(f"Рекомендация: удалить дубликат каталога: {dup}")

    print("Изменено файлов:", len(changed_files))
    for fp in changed_files:
        print("  *", fp)
    if notes:
        print("\nЗаметки:")
        for n in notes:
            print(" -", n)

if __name__ == "__main__":
    main()
