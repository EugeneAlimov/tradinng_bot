import pytest
import sys
from pathlib import Path
from decimal import Decimal

src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

@pytest.mark.unit
def test_mock_config_validation(mock_config):
    """Тест валидации мок конфигурации"""
    # Позитивный тест
    assert mock_config.validate() is True
    
    # Негативный тест - короткий API ключ
    mock_config.exchange.api_key = "short"
    with pytest.raises(ValueError, match="API key слишком короткий"):
        mock_config.validate()

@pytest.mark.unit
def test_trading_config(mock_config):
    """Тест торговых настроек"""
    assert mock_config.trading.position_size_percent == Decimal("6.0")
    assert mock_config.trading.max_position_size_percent == Decimal("50.0")
    assert mock_config.trading.stop_loss_percent == Decimal("15.0")

@pytest.mark.unit
def test_exchange_config(mock_config):
    """Тест настроек биржи"""
    assert mock_config.exchange.api_key == "test_api_key_12345"
    assert mock_config.exchange.api_secret == "test_api_secret_67890"
    assert "exmo.com" in mock_config.exchange.base_url

@pytest.mark.unit
def test_config_types(mock_config):
    """Тест типов данных в конфигурации"""
    assert isinstance(mock_config.trading.position_size_percent, Decimal)
    assert isinstance(mock_config.trading.stop_loss_percent, Decimal)
    assert isinstance(mock_config.exchange.api_key, str)
