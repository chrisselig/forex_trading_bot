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
}


def make_forex_contract(pair: str) -> Forex:
    """Create an IB Forex contract from a pair string like 'EURUSD'."""
    pair = pair.upper().replace("/", "").replace("_", "")
    if len(pair) != 6:
        raise ContractError(f"Invalid forex pair: {pair}")
    return Forex(pair)


def get_pip_size(pair: str) -> float:
    """Return the pip size for a given forex pair."""
    pair = pair.upper().replace("/", "").replace("_", "")
    return PIP_SIZES.get(pair, 0.0001)
