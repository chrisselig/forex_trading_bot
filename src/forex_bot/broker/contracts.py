from __future__ import annotations

from ib_async import Forex

from forex_bot.broker.exceptions import ContractError

# Pip sizes per pair (most pairs use 0.0001, JPY pairs use 0.01)
PIP_SIZES: dict[str, float] = {
    "EURUSD": 0.0001,
    "GBPUSD": 0.0001,
    "USDCAD": 0.0001,
    "AUDUSD": 0.0001,
    "NZDUSD": 0.0001,
    "USDCHF": 0.0001,
    "USDJPY": 0.01,
    "EURJPY": 0.01,
    "GBPJPY": 0.01,
    "USDZAR": 0.0001,
    "USDTRY": 0.0001,
    "USDMXN": 0.0001,
    "AUDJPY": 0.01,
    "NZDJPY": 0.01,
}


def make_forex_contract(pair: str) -> Forex:
    """Create an IB Forex contract from a pair string like 'EURUSD'."""
    pair = pair.upper().replace("/", "").replace("_", "")
    if len(pair) != 6:
        raise ContractError(f"Invalid forex pair: {pair}")
    return Forex(pair)


def make_fxconv_contract(pair: str) -> Forex:
    """Create an IB FXCONV contract for currency conversion orders.

    FXCONV has no minimum order size (unlike IDEALPRO's 25,000 unit minimum),
    making it suitable for small position sizes like carry trades on small accounts.
    Tradeoff: no bracket orders — stop losses must be software-monitored.
    """
    pair = pair.upper().replace("/", "").replace("_", "")
    if len(pair) != 6:
        raise ContractError(f"Invalid forex pair: {pair}")
    return Forex(pair, exchange="FXCONV")


def get_pip_size(pair: str) -> float:
    """Return the pip size for a given forex pair."""
    pair = pair.upper().replace("/", "").replace("_", "")
    return PIP_SIZES.get(pair, 0.0001)


# IB minimum price increments (half-pip for most pairs)
TICK_SIZES: dict[str, float] = {
    "USDJPY": 0.005,
    "EURJPY": 0.005,
    "GBPJPY": 0.005,
    "CADJPY": 0.005,
}
_DEFAULT_TICK = 0.00005  # Half-pip for non-JPY pairs


def get_tick_size(pair: str) -> float:
    """Return the IB minimum price increment for a given forex pair."""
    pair = pair.upper().replace("/", "").replace("_", "")
    return TICK_SIZES.get(pair, _DEFAULT_TICK)


def get_quote_currency(pair: str) -> str:
    """Return the quote currency (last 3 chars) of a forex pair."""
    pair = pair.upper().replace("/", "").replace("_", "")
    return pair[3:6]


def round_to_tick(price: float, pair: str) -> float:
    """Round a price to the nearest valid tick for the given pair."""
    tick = get_tick_size(pair)
    return round(round(price / tick) * tick, 10)
