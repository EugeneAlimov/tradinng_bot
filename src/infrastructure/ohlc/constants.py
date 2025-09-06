"""
Constants for OHLC data processing
"""
from typing import List

# Required columns for OHLC data
REQUIRED_COLS: List[str] = ["timestamp", "open", "high", "low", "close", "volume"]
MIN_COLS: List[str] = REQUIRED_COLS
_MIN_COLS: List[str] = REQUIRED_COLS  # Legacy compatibility
