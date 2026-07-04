"""Unit tests for the FRED-backed event actuals resolver.

Never hits the network — FredClient/fredapi are always mocked.
"""

from __future__ import annotations

import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch

from forex_bot.calendar import actuals
from forex_bot.calendar.actuals import (
    Frequency,
    SeriesMapping,
    Transform,
    lookup_mapping,
    resolve_actual,
)
from forex_bot.models.events import EconomicEvent


@pytest.fixture(autouse=True)
def reset_fred_client_cache():
    """The resolver caches a FredClient singleton at module scope — reset it
    around every test so mocks/failures in one test never leak into another.
    """
    actuals._fred_client = None
    yield
    actuals._fred_client = None


def _obs(date: datetime, value: float) -> dict:
    return {"date": date, "value": value}


def _mock_fred(observations: list[dict]) -> MagicMock:
    """A MagicMock standing in for a FredClient instance."""
    fred = MagicMock()
    fred.get_series = MagicMock(return_value=observations)
    return fred


def _patched_fred(observations: list[dict]):
    """Patch _get_fred_client to return a mock FredClient with fixed data."""
    return patch.object(actuals, "_get_fred_client", return_value=_mock_fred(observations))


def _event(title: str, scheduled_at: datetime, country: str = "USD", event_id: int = 1) -> EconomicEvent:
    return EconomicEvent(id=event_id, title=title, country=country, scheduled_at=scheduled_at)


class TestLookupMapping:
    def test_known_title_matches(self):
        assert lookup_mapping("Non-Farm Employment Change", "USD") is not None
        assert lookup_mapping("NFP", "USD") is not None

    def test_exact_equality_not_substring(self):
        """Project convention: aliases match exactly, never via substring."""
        assert lookup_mapping("Flash Manufacturing PMI", "USD") is None

    def test_unknown_title_returns_none(self):
        assert lookup_mapping("Some Totally Unrelated Release", "USD") is None

    def test_ism_manufacturing_pmi_known_but_unsupported(self):
        """ISM PMI is explicitly listed with no FRED source (NAPM discontinued)."""
        assert lookup_mapping("ISM Manufacturing PMI", "USD") is None
        # It's present in the table (documented decision), just maps to None.
        assert "ism manufacturing pmi" in actuals._TITLE_MAP

    def test_non_usd_country_gated_out(self):
        """South Africa's CPI release is also literally titled 'CPI y/y' —
        must never be routed through the US CPIAUCSL mapping."""
        assert lookup_mapping("CPI y/y", "USD") is not None
        assert lookup_mapping("CPI y/y", "ZAR") is None

    def test_sarb_tcmb_boj_rba_have_no_mapping(self):
        for title, country in [
            ("SARB Interest Rate Decision", "ZAR"),
            ("TCMB Interest Rate Decision", "TRY"),
            ("BOJ Policy Rate", "JPY"),
            ("RBA Rate Decision", "AUD"),
            ("Australia CPI", "AUD"),
            ("Australia Employment", "AUD"),
        ]:
            assert lookup_mapping(title, country) is None


class TestTransforms:
    @pytest.mark.asyncio
    async def test_level_format(self):
        """Federal Funds Rate (DFEDTARU) — LEVEL, 'X.XX%'.

        A new target range takes effect the day AFTER the FOMC announcement,
        so the resolver must use the first observation dated after the event
        day — never the decision-day (pre-decision) value.
        """
        event = _event("Federal Funds Rate", datetime(2026, 7, 5, 18, 0))
        obs = [
            _obs(datetime(2026, 7, 5), 4.50),  # decision day: still the old rate
            _obs(datetime(2026, 7, 6), 4.25),  # effective date: the new rate
        ]
        with _patched_fred(obs):
            result = await resolve_actual(event)
        assert result == "4.25%"

    @pytest.mark.asyncio
    async def test_level_not_yet_effective_returns_none(self):
        """No observation after the decision day yet → not released; the
        pre-decision rate must never be stored as the actual."""
        event = _event("Federal Funds Rate", datetime(2026, 7, 5, 18, 0))
        obs = [
            _obs(datetime(2026, 7, 4), 4.50),
            _obs(datetime(2026, 7, 5), 4.50),  # decision day itself: old rate
        ]
        with _patched_fred(obs):
            result = await resolve_actual(event)
        assert result is None

    @pytest.mark.asyncio
    async def test_mom_pct_format(self):
        """CPI m/m — MOM_PCT, 'X.X%'."""
        event = _event("CPI m/m", datetime(2026, 7, 10))
        obs = [
            _obs(datetime(2026, 5, 1), 320.0),
            _obs(datetime(2026, 6, 1), 321.0),
        ]
        with _patched_fred(obs):
            result = await resolve_actual(event)
        expected = (321.0 - 320.0) / 320.0 * 100
        assert result == f"{expected:.1f}%"

    @pytest.mark.asyncio
    async def test_yoy_pct_format(self):
        """CPI y/y — YOY_PCT, uses the observation ~12 periods back."""
        event = _event("CPI y/y", datetime(2026, 7, 10))
        base_value = 300.0
        # Build 13 consecutive monthly observations ending June 2026.
        obs = []
        year, month = 2025, 6
        for i in range(13):
            obs.append(_obs(datetime(year, month, 1), base_value + i * 2))
            month += 1
            if month > 12:
                month = 1
                year += 1
        with _patched_fred(obs):
            result = await resolve_actual(event)
        latest = obs[-1]["value"]
        year_ago = obs[-13]["value"]
        expected = (latest - year_ago) / abs(year_ago) * 100
        assert result == f"{expected:.1f}%"

    @pytest.mark.asyncio
    async def test_mom_diff_k_positive(self):
        """Non-Farm Employment Change — MOM_DIFF_K, e.g. '227K'."""
        event = _event("Non-Farm Employment Change", datetime(2026, 7, 3))
        obs = [
            _obs(datetime(2026, 5, 1), 160000.0),
            _obs(datetime(2026, 6, 1), 160227.0),
        ]
        with _patched_fred(obs):
            result = await resolve_actual(event)
        assert result == "227K"

    @pytest.mark.asyncio
    async def test_mom_diff_k_negative(self):
        """Negative payroll diffs must format with a leading minus, e.g. '-20K'."""
        event = _event("Non-Farm Employment Change", datetime(2026, 7, 3))
        obs = [
            _obs(datetime(2026, 5, 1), 160000.0),
            _obs(datetime(2026, 6, 1), 159980.0),
        ]
        with _patched_fred(obs):
            result = await resolve_actual(event)
        assert result == "-20K"

    @pytest.mark.asyncio
    async def test_level_k_format(self):
        """Unemployment Claims (ICSA) — LEVEL_K, e.g. '227K'."""
        event = _event("Unemployment Claims", datetime(2026, 7, 9))
        obs = [_obs(datetime(2026, 7, 2), 227000.0)]
        with _patched_fred(obs):
            result = await resolve_actual(event)
        assert result == "227K"


class TestFreshnessGuard:
    @pytest.mark.asyncio
    async def test_stale_monthly_observation_returns_none(self):
        """A monthly observation from 3+ months before the event (wrong
        period, e.g. still last quarter's print) must never be reported."""
        event = _event("CPI m/m", datetime(2026, 7, 10))
        obs = [
            _obs(datetime(2026, 3, 1), 318.0),
            _obs(datetime(2026, 4, 1), 319.0),
        ]
        with _patched_fred(obs):
            result = await resolve_actual(event)
        assert result is None

    @pytest.mark.asyncio
    async def test_stale_daily_observation_returns_none(self):
        """A daily-frequency observation far older than the window is stale."""
        event = _event("Federal Funds Rate", datetime(2026, 7, 5))
        obs = [_obs(datetime(2026, 6, 1), 4.50)]  # 34 days old, > 10-day window
        with _patched_fred(obs):
            result = await resolve_actual(event)
        assert result is None

    @pytest.mark.asyncio
    async def test_fresh_quarterly_gdp_observation_accepted(self):
        """GDP allows up to a 2-quarter lag (advance-estimate style reporting)."""
        event = _event("GDP q/q", datetime(2026, 7, 30))
        obs = [_obs(datetime(2026, 4, 1), 2.8)]
        with _patched_fred(obs):
            result = await resolve_actual(event)
        assert result == "2.8%"

    @pytest.mark.asyncio
    async def test_future_observation_rejected(self):
        """An observation dated after the event is nonsensical — reject it."""
        event = _event("CPI m/m", datetime(2026, 7, 10))
        obs = [
            _obs(datetime(2026, 7, 1), 320.0),
            _obs(datetime(2026, 8, 1), 321.0),
        ]
        with _patched_fred(obs):
            result = await resolve_actual(event)
        assert result is None


class TestNoMappingAndNoNetwork:
    @pytest.mark.asyncio
    async def test_unknown_title_never_touches_fred(self):
        event = _event("Some Totally Unrelated Release", datetime(2026, 7, 10))
        with patch.object(actuals, "_get_fred_client") as mock_get_client:
            result = await resolve_actual(event)
        mock_get_client.assert_not_called()
        assert result is None

    @pytest.mark.asyncio
    async def test_missing_api_key_returns_none_without_raising(self):
        event = _event("CPI m/m", datetime(2026, 7, 10))
        with patch("forex_bot.calendar.fred_client.FredClient", side_effect=ValueError("FRED_API_KEY is required")):
            result = await resolve_actual(event)
        assert result is None

    @pytest.mark.asyncio
    async def test_fred_network_error_returns_none(self):
        event = _event("CPI m/m", datetime(2026, 7, 10))
        fred = MagicMock()
        fred.get_series = MagicMock(side_effect=ConnectionError("network down"))
        with patch.object(actuals, "_get_fred_client", return_value=fred):
            result = await resolve_actual(event)
        assert result is None

    @pytest.mark.asyncio
    async def test_no_observations_returns_none(self):
        event = _event("CPI m/m", datetime(2026, 7, 10))
        with _patched_fred([]):
            result = await resolve_actual(event)
        assert result is None


class TestSeriesMappingShape:
    def test_mapping_is_series_mapping_instance(self):
        mapping = lookup_mapping("Non-Farm Employment Change", "USD")
        assert isinstance(mapping, SeriesMapping)
        assert mapping.series_id == "PAYEMS"
        assert mapping.transform == Transform.MOM_DIFF_K
        assert mapping.frequency == Frequency.MONTHLY
