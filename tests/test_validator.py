# tests/test_validator.py
from decimal import Decimal
from src.infrastructure.exchange.validator import ExchangeDataValidator, ValidationError

def test_ticker_epsilon_spread_ok():
    v = ExchangeDataValidator
    tk = {"bid": "1.00000000", "ask": "1.00000000", "last": "1.0", "volume": "10", "high": "1.1", "low": "0.9", "pair": "DOGE_EUR"}
    t = v.validate_ticker(tk)
    assert isinstance(t.volume_24h, Decimal)

def test_candle_invalid_range_skipped(caplog):
    v = ExchangeDataValidator
    out = v.validate_candles([{"open": "2", "high": "1", "low": "3", "close": "2", "volume": "1", "timestamp": 1}])
    assert out == []
