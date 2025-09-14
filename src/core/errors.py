# src/core/errors.py
class CoreError(Exception):
    """Base domain error."""


class DataError(CoreError):
    """Data/IO related error."""


class ConfigError(CoreError):
    """Configuration error."""


class ExecutionError(CoreError):
    """Broker/execution error."""
