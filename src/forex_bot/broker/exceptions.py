class ForexBotError(Exception):
    """Base exception for the forex trading bot."""


class ConnectionError(ForexBotError):
    """Failed to connect to IB Gateway/TWS."""


class OrderError(ForexBotError):
    """Order placement or management failed."""


class ContractError(ForexBotError):
    """Invalid or unresolvable contract."""


class DataError(ForexBotError):
    """Market data request failed."""
