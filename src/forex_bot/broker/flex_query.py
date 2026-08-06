from __future__ import annotations

import asyncio
from datetime import datetime
from xml.etree import ElementTree

import httpx
from loguru import logger

from forex_bot.models.interest import InterestAccrualRow

# IB's documented two-step Flex Web Service: SendRequest kicks off statement
# generation and returns a reference code; GetStatement is polled with that
# code until the statement is ready (IB replies with a <FlexStatementResponse>
# wrapper and Status != Success while still generating; the raw report XML
# comes back with no such wrapper once it's done).
_SEND_REQUEST_URL = "https://gdcdyn.interactivebrokers.com/Universal/servlet/FlexStatementService.SendRequest"
_GET_STATEMENT_URL = "https://gdcdyn.interactivebrokers.com/Universal/servlet/FlexStatementService.GetStatement"
_REQUEST_TIMEOUT_S = 30.0

# The Flex Query in Account Management must have Date Format = "yyyy-MM-dd".
_DATE_FORMAT = "%Y-%m-%d"

# IB includes a synthetic "BASE_SUMMARY" row alongside the real per-currency
# rows — it's just the sum of that day's other currency rows already
# converted to the account base currency, not a real currency. Including it
# would double-count when summing across currencies for a grand total.
_SYNTHETIC_CURRENCIES = {"BASE_SUMMARY"}


class FlexQueryClient:
    """Pulls the "Interest Accruals" Flex Query report configured in IBKR
    Account Management. The report's date Period and "Breakout by Day"
    setting are configured on the query itself, not overridden per-request."""

    def __init__(self, token: str, query_id: str) -> None:
        self._token = token
        self._query_id = query_id

    async def fetch_interest_accruals(
        self, *, max_attempts: int = 30, retry_interval_s: float = 60.0
    ) -> list[InterestAccrualRow]:
        """Runs the full SendRequest -> poll GetStatement cycle and returns
        every parsed interest accrual row. Raises TimeoutError if the
        statement never becomes ready within the retry budget."""
        ref_code = await self._send_request()
        for attempt in range(1, max_attempts + 1):
            xml_text = await self._get_statement(ref_code)
            if xml_text is not None:
                return _parse_interest_accruals(xml_text)
            if attempt < max_attempts:
                await asyncio.sleep(retry_interval_s)
        raise TimeoutError(
            f"Flex statement not ready after {max_attempts} attempts "
            f"({max_attempts * retry_interval_s:.0f}s)"
        )

    async def _send_request(self) -> str:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_S) as client:
            response = await client.get(
                _SEND_REQUEST_URL, params={"t": self._token, "q": self._query_id, "v": "3"}
            )
            response.raise_for_status()
        root = ElementTree.fromstring(response.text)
        status = root.findtext("Status")
        if status != "Success":
            error = root.findtext("ErrorMessage") or "unknown error"
            raise RuntimeError(f"Flex SendRequest failed: {error}")
        ref_code = root.findtext("ReferenceCode")
        if not ref_code:
            raise RuntimeError("Flex SendRequest succeeded but returned no ReferenceCode")
        return ref_code

    async def _get_statement(self, ref_code: str) -> str | None:
        """Returns the raw report XML, or None if the statement is still
        being generated (caller should retry)."""
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_S) as client:
            response = await client.get(
                _GET_STATEMENT_URL, params={"t": self._token, "q": ref_code, "v": "3"}
            )
            response.raise_for_status()
        if "FlexStatementResponse" in response.text:
            root = ElementTree.fromstring(response.text)
            status = root.findtext("Status")
            if status == "Success":
                return response.text
            error = root.findtext("ErrorMessage") or status or "not ready"
            logger.debug(f"Flex statement not ready yet: {error}")
            return None
        return response.text


def _parse_interest_accruals(xml_text: str) -> list[InterestAccrualRow]:
    root = ElementTree.fromstring(xml_text)
    rows: list[InterestAccrualRow] = []
    for el in root.iter("InterestAccrualsCurrency"):
        currency = el.get("currency")
        from_date = el.get("fromDate")
        to_date = el.get("toDate")
        amount = el.get("interestAccrued")
        if not currency or not from_date or not to_date or amount is None:
            continue
        if currency in _SYNTHETIC_CURRENCIES:
            continue
        try:
            rows.append(
                InterestAccrualRow(
                    currency=currency,
                    from_date=datetime.strptime(from_date, _DATE_FORMAT),
                    to_date=datetime.strptime(to_date, _DATE_FORMAT),
                    amount_cad=float(amount),
                )
            )
        except (ValueError, TypeError) as e:
            logger.warning(f"Skipping malformed interest accrual row: {e}")
    return rows
