class TradingError(Exception):
    pass


class ConfigError(TradingError):
    pass


class ExecutionError(TradingError):
    pass
