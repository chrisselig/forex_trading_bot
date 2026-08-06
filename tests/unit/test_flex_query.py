"""Unit tests for the IB Flex Web Service client (real interest accrual data)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from forex_bot.broker.flex_query import FlexQueryClient

_SEND_SUCCESS = """<FlexStatementResponse>
<Status>Success</Status>
<ReferenceCode>123456789</ReferenceCode>
<Url>https://example.com</Url>
</FlexStatementResponse>"""

_SEND_FAILURE = """<FlexStatementResponse>
<Status>Fail</Status>
<ErrorCode>1003</ErrorCode>
<ErrorMessage>Token expired</ErrorMessage>
</FlexStatementResponse>"""

_NOT_READY = """<FlexStatementResponse>
<Status>Warn</Status>
<ErrorCode>1019</ErrorCode>
<ErrorMessage>Statement generation in progress</ErrorMessage>
</FlexStatementResponse>"""

_INTEREST_XML = """<FlexQueryResponse>
<FlexStatements>
<FlexStatement>
<InterestAccruals>
<InterestAccrualsCurrency currency="USD" fromDate="2026-07-01" toDate="2026-07-01" interestAccrued="1.2345" startingAccrualBalance="0" endingAccrualBalance="1.2345" accrualReversal="0" />
<InterestAccrualsCurrency currency="TRY" fromDate="2026-07-01" toDate="2026-07-01" interestAccrued="5.6789" startingAccrualBalance="0" endingAccrualBalance="5.6789" accrualReversal="0" />
<InterestAccrualsCurrency currency="ZAR" fromDate="2026-07-01" toDate="2026-07-01" startingAccrualBalance="0" endingAccrualBalance="0" accrualReversal="0" />
<InterestAccrualsCurrency currency="BASE_SUMMARY" fromDate="2026-07-01" toDate="2026-07-01" interestAccrued="6.9134" startingAccrualBalance="0" endingAccrualBalance="6.9134" accrualReversal="0" />
</InterestAccruals>
</FlexStatement>
</FlexStatements>
</FlexQueryResponse>"""


def _mock_client_sequence(*responses):
    """Patch target for `httpx.AsyncClient(...)`, returning each response
    text in `responses` on successive `.get()` calls."""
    mock_responses = []
    for text in responses:
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.text = text
        mock_responses.append(response)

    http_instance = MagicMock()
    http_instance.get = AsyncMock(side_effect=mock_responses)

    @asynccontextmanager
    async def _ctx(*args, **kwargs):
        yield http_instance

    return MagicMock(side_effect=_ctx)


@pytest.mark.asyncio
async def test_send_request_failure_raises():
    with patch(
        "forex_bot.broker.flex_query.httpx.AsyncClient", _mock_client_sequence(_SEND_FAILURE)
    ):
        with pytest.raises(RuntimeError, match="Token expired"):
            await FlexQueryClient("bad-token", "999").fetch_interest_accruals()


@pytest.mark.asyncio
async def test_get_statement_retries_until_ready():
    with patch(
        "forex_bot.broker.flex_query.httpx.AsyncClient",
        _mock_client_sequence(_SEND_SUCCESS, _NOT_READY, _INTEREST_XML),
    ):
        with patch("forex_bot.broker.flex_query.asyncio.sleep", new=AsyncMock()):
            rows = await FlexQueryClient("t", "q").fetch_interest_accruals(
                max_attempts=3, retry_interval_s=0
            )

    assert len(rows) == 2  # ZAR row has no interestAccrued attr, skipped
    assert {r.currency for r in rows} == {"USD", "TRY"}


@pytest.mark.asyncio
async def test_parses_interest_accrued_field_and_date_format():
    with patch(
        "forex_bot.broker.flex_query.httpx.AsyncClient",
        _mock_client_sequence(_SEND_SUCCESS, _INTEREST_XML),
    ):
        rows = await FlexQueryClient("t", "q").fetch_interest_accruals()

    usd = next(r for r in rows if r.currency == "USD")
    assert usd.amount_cad == pytest.approx(1.2345)
    assert usd.from_date.isoformat() == "2026-07-01T00:00:00"
    assert usd.to_date.isoformat() == "2026-07-01T00:00:00"


@pytest.mark.asyncio
async def test_base_summary_pseudo_currency_is_excluded():
    with patch(
        "forex_bot.broker.flex_query.httpx.AsyncClient",
        _mock_client_sequence(_SEND_SUCCESS, _INTEREST_XML),
    ):
        rows = await FlexQueryClient("t", "q").fetch_interest_accruals()

    assert "BASE_SUMMARY" not in {r.currency for r in rows}


@pytest.mark.asyncio
async def test_never_ready_raises_timeout_error():
    with patch(
        "forex_bot.broker.flex_query.httpx.AsyncClient",
        _mock_client_sequence(_SEND_SUCCESS, _NOT_READY, _NOT_READY),
    ):
        with patch("forex_bot.broker.flex_query.asyncio.sleep", new=AsyncMock()):
            with pytest.raises(TimeoutError):
                await FlexQueryClient("t", "q").fetch_interest_accruals(
                    max_attempts=2, retry_interval_s=0
                )
