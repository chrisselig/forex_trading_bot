"""Unit tests for contract helpers."""

import pytest
from forex_bot.broker.contracts import make_forex_contract, get_pip_size
from forex_bot.broker.exceptions import ContractError


def test_make_contract_basic():
    contract = make_forex_contract("EURUSD")
    assert contract.pair() == "EURUSD"


def test_make_contract_with_slash():
    contract = make_forex_contract("EUR/USD")
    assert contract.pair() == "EURUSD"


def test_make_contract_lowercase():
    contract = make_forex_contract("eurusd")
    assert contract.pair() == "EURUSD"


def test_make_contract_invalid():
    with pytest.raises(ContractError):
        make_forex_contract("EUR")


def test_pip_size_standard():
    assert get_pip_size("EURUSD") == 0.0001


def test_pip_size_jpy():
    assert get_pip_size("USDJPY") == 0.01


def test_pip_size_unknown():
    assert get_pip_size("ABCDEF") == 0.0001
