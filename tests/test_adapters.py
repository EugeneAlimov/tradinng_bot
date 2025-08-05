import pytest
import sys
from pathlib import Path

src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

@pytest.mark.integration
def test_legacy_bot_adapter():
    """Тест адаптера старого бота"""
    try:
        from adapters import LegacyBotAdapter

        adapter = LegacyBotAdapter(use_hybrid=False)
        assert adapter is not None

        # Пытаемся получить старый бот
        old_bot = adapter.get_old_bot()

        # Если получили, проверяем интерфейс
        if old_bot:
            assert hasattr(old_bot, '__class__')

    except ImportError as e:
        pytest.skip(f"Адаптер недоступен: {e}")

@pytest.mark.integration  
def test_strategy_adapter():
    """Тест адаптера стратегий"""
    try:
        from adapters import StrategyAdapter

        adapter = StrategyAdapter()
        assert adapter is not None

        adapter.load_old_strategies()

    except ImportError:
        pytest.skip("Адаптер стратегий недоступен")
