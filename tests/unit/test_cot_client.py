"""Unit tests for the CFTC Commitments of Traders client (carry's COT
crash-risk filter)."""

from __future__ import annotations

import statistics
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from forex_bot.calendar.cot_client import MIN_WEEKS_FOR_ZSCORE, CotClient


def _row(report_date, long_pos, short_pos, oi):
    return {
        "report_date_as_yyyy_mm_dd": report_date,
        "lev_money_positions_long": str(long_pos),
        "lev_money_positions_short": str(short_pos),
        "open_interest_all": str(oi),
    }


def _mock_client_returning(rows=None, *, raise_error=None):
    """Patch target for `httpx.AsyncClient(...)` used as an async context
    manager, whose `.get(...)` returns a response with the given JSON rows
    (or raises `raise_error` from `.raise_for_status()`)."""
    response = MagicMock()
    if raise_error is not None:
        response.raise_for_status.side_effect = raise_error
    else:
        response.raise_for_status.return_value = None
        response.json.return_value = rows or []

    http_instance = MagicMock()
    http_instance.get = AsyncMock(return_value=response)

    @asynccontextmanager
    async def _ctx(*args, **kwargs):
        yield http_instance

    mock_client_cls = MagicMock(side_effect=_ctx)
    return mock_client_cls


@pytest.mark.asyncio
async def test_unsupported_currency_returns_none_without_http_call():
    with patch("forex_bot.calendar.cot_client.httpx.AsyncClient") as MockClient:
        result = await CotClient().get_crowding("TRY")
        assert result is None
        MockClient.assert_not_called()


@pytest.mark.asyncio
async def test_computes_zscore_from_latest_row():
    # 59 quiet weeks (net = 0.0) followed by one crowded latest week (net = 0.5),
    # rows ordered most-recent-first (matches the API's $order DESC).
    rows = [_row("2026-07-28T00:00:00.000", 750, 250, 1000)]
    rows += [_row(f"2026-{m:02d}-01T00:00:00.000", 500, 500, 1000) for m in range(1, 60)]

    with patch("forex_bot.calendar.cot_client.httpx.AsyncClient", _mock_client_returning(rows)):
        result = await CotClient().get_crowding("AUD", lookback_weeks=60)

    assert result is not None
    assert result.currency == "AUD"
    assert result.n_weeks == 60
    assert result.net_pct_oi == pytest.approx(0.5)

    series = [0.5] + [0.0] * 59
    expected_z = (0.5 - statistics.fmean(series)) / statistics.pstdev(series)
    assert result.z_score == pytest.approx(expected_z)


@pytest.mark.asyncio
async def test_insufficient_history_returns_none():
    rows = [_row(f"2026-{m:02d}-01T00:00:00.000", 500, 500, 1000) for m in range(1, MIN_WEEKS_FOR_ZSCORE)]
    assert len(rows) < MIN_WEEKS_FOR_ZSCORE

    with patch("forex_bot.calendar.cot_client.httpx.AsyncClient", _mock_client_returning(rows)):
        result = await CotClient().get_crowding("ZAR")

    assert result is None


def _varied_rows(n, start=1):
    """n rows with alternating net positioning so variance is non-zero."""
    return [
        _row(f"2026-{((start + m - 2) % 12) + 1:02d}-01T00:00:00.000", 500 + (m % 3) * 10, 500, 1000)
        for m in range(1, n + 1)
    ]


@pytest.mark.asyncio
async def test_zero_open_interest_rows_are_skipped():
    rows = [_row("2026-07-28T00:00:00.000", 100, 0, 0)]  # would divide by zero if kept
    rows += _varied_rows(59)

    with patch("forex_bot.calendar.cot_client.httpx.AsyncClient", _mock_client_returning(rows)):
        result = await CotClient().get_crowding("JPY", lookback_weeks=60)

    # The zero-OI row is dropped, leaving 59 usable weeks — still >= minimum.
    assert result is not None
    assert result.n_weeks == 59


@pytest.mark.asyncio
async def test_malformed_row_is_skipped_not_fatal():
    rows = [{"report_date_as_yyyy_mm_dd": "2026-07-28T00:00:00.000"}]  # missing fields
    rows += _varied_rows(59)

    with patch("forex_bot.calendar.cot_client.httpx.AsyncClient", _mock_client_returning(rows)):
        result = await CotClient().get_crowding("MXN", lookback_weeks=60)

    assert result is not None
    assert result.n_weeks == 59


@pytest.mark.asyncio
async def test_http_failure_returns_none():
    with patch(
        "forex_bot.calendar.cot_client.httpx.AsyncClient",
        _mock_client_returning(raise_error=httpx.ConnectTimeout("timed out")),
    ):
        result = await CotClient().get_crowding("AUD")

    assert result is None


@pytest.mark.asyncio
async def test_zero_variance_history_returns_none():
    rows = [_row(f"2026-{m:02d}-01T00:00:00.000", 500, 500, 1000) for m in range(1, 60)]

    with patch("forex_bot.calendar.cot_client.httpx.AsyncClient", _mock_client_returning(rows)):
        result = await CotClient().get_crowding("ZAR", lookback_weeks=60)

    assert result is None
