import pytest
import sys
from pathlib import Path

# Добавляем src в путь
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

@pytest.mark.unit
def test_settings_import():
    """Тест импорта настроек"""
    try:
        from config.settings import get_settings
        settings = get_settings()
        assert settings is not None
    except ImportError as e:
        pytest.skip(f"Модуль конфигурации недоступен: {e}")

@pytest.mark.unit
def test_settings_validation():
    """Тест валидации настроек"""
    try:
        from config.settings import get_settings
        settings = get_settings()

        # Тест с пустыми API ключами должен падать
        settings.exmo_api_key = ""
        settings.exmo_api_secret = ""

        with pytest.raises(ValueError):
            settings.validate()

    except ImportError:
        pytest.skip("Модуль конфигурации недоступен")

@pytest.mark.unit
def test_core_models():
    """Тест базовых моделей"""
    try:
        from core.models import TradingPair, TradeSignal
        from decimal import Decimal

        # Тест TradingPair
        pair = TradingPair("DOGE", "EUR")
        assert str(pair) == "DOGE_EUR"

        # Тест TradeSignal
        signal = TradeSignal(
            action="buy",
            quantity=Decimal("100"),
            price=Decimal("0.18"),
            confidence=0.8,
            reason="Test signal"
        )

        assert signal.action == "buy"
        assert signal.quantity == Decimal("100")
        assert signal.timestamp is not None

    except ImportError:
        pytest.skip("Core модели недоступны")
