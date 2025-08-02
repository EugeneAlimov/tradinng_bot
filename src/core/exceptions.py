#!/usr/bin/env python3
"""🚨 Кастомные исключения торговой системы"""

class TradingSystemError(Exception):
    """Базовое исключение торговой системы"""
    pass

class ConfigurationError(TradingSystemError):
    """Ошибка конфигурации"""
    pass

class APIError(TradingSystemError):
    """Ошибка API"""
    pass

class PositionError(TradingSystemError):
    """Ошибка позиции"""
    pass

class StrategyError(TradingSystemError):
    """Ошибка стратегии"""
    pass
