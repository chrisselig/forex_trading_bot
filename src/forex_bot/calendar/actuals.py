from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from loguru import logger

from forex_bot.models.events import EconomicEvent


class Transform(StrEnum):
    """How a raw FRED observation (or pair of observations) becomes an actual."""

    LEVEL = "level"  # report the latest value as-is (assumed to be a percent)
    MOM_PCT = "mom_pct"  # % change vs. the prior observation
    YOY_PCT = "yoy_pct"  # % change vs. the observation ~12 periods back
    MOM_DIFF_K = "mom_diff_k"  # raw diff vs. prior observation, already in thousands
    LEVEL_K = "level_k"  # latest value divided by 1000, e.g. claims in K


class Frequency(StrEnum):
    """FRED release cadence — drives the freshness guard below."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"


# Freshness window: how many days *before* the event's scheduled_at the
# latest FRED observation's period date is allowed to be, before we treat it
# as "not released yet" and refuse to use it (never store a stale
# previous-period value as this event's actual).
#
# DAILY (Fed funds target range) is not a periodic index release — it's a
# point-in-time level that only changes when the FOMC votes to change it.
# A new target range takes effect the business day AFTER the announcement,
# so daily series are resolved forward by _daily_level (first observation
# dated after the event day), not by this backward-looking window; the
# DAILY entry only caps how far after the event that observation may be.
_FRESHNESS_WINDOW_DAYS: dict[Frequency, int] = {
    Frequency.DAILY: 10,
    Frequency.WEEKLY: 14,
    Frequency.MONTHLY: 45,
    Frequency.QUARTERLY: 120,
}


@dataclass(frozen=True)
class SeriesMapping:
    series_id: str
    transform: Transform
    frequency: Frequency
    decimals: int = 1


# Title -> FRED mapping. Keys are the lowercased/stripped title as it comes
# back from Forex Factory — either the canonical `name` in
# config/events.yaml or one of its `aliases` (exact-equality matching only,
# per project convention — never substring).
#
# Every entry here is a USD-country event. Forex Factory (and this codebase's
# own config) reuses generic titles like "CPI y/y" for other countries (e.g.
# South Africa's CPI release is also literally titled "CPI y/y" in
# config/events.yaml, country="ZAR"), so `lookup_mapping` additionally gates
# every lookup on event.country == "USD" before consulting this table. That
# is what correctly excludes SARB / TCMB / BOJ / RBA / Australia CPI /
# Australia Employment events — they have no FRED source and must fall
# through to "no mapping" so the scheduler stops polling for them
# immediately instead of burning all 12 attempts.
#
# ISM Manufacturing PMI is listed explicitly with a `None` value: FRED's
# manufacturing PMI proxy (NAPM) was discontinued, so there genuinely is no
# public FRED substitute. This is deliberate ("known title, no source") as
# opposed to a title we've simply never heard of — both currently resolve to
# "no mapping" for the scheduler's purposes, but keeping the entry documents
# that the omission was a decision, not an oversight.
_TITLE_MAP: dict[str, SeriesMapping | None] = {
    # --- Non-Farm Employment Change (NFP) ---
    "non-farm employment change": SeriesMapping("PAYEMS", Transform.MOM_DIFF_K, Frequency.MONTHLY, 0),
    "nfp": SeriesMapping("PAYEMS", Transform.MOM_DIFF_K, Frequency.MONTHLY, 0),
    "non-farm payrolls": SeriesMapping("PAYEMS", Transform.MOM_DIFF_K, Frequency.MONTHLY, 0),
    "nonfarm payrolls": SeriesMapping("PAYEMS", Transform.MOM_DIFF_K, Frequency.MONTHLY, 0),
    # --- Unemployment Rate (not currently an active trading target — see
    # config/events.yaml, "REDUNDANT — same release as NFP" — but the FRED
    # mapping costs nothing to keep for future use / manual lookups) ---
    "unemployment rate": SeriesMapping("UNRATE", Transform.LEVEL, Frequency.MONTHLY, 1),
    # --- CPI ---
    "cpi m/m": SeriesMapping("CPIAUCSL", Transform.MOM_PCT, Frequency.MONTHLY, 1),
    "consumer price index": SeriesMapping("CPIAUCSL", Transform.MOM_PCT, Frequency.MONTHLY, 1),
    "cpi y/y": SeriesMapping("CPIAUCSL", Transform.YOY_PCT, Frequency.MONTHLY, 1),
    "core cpi m/m": SeriesMapping("CPILFESL", Transform.MOM_PCT, Frequency.MONTHLY, 1),
    # --- Federal Funds Rate / FOMC ---
    # DFEDTARU (target range upper bound, daily/real-time) — NOT the
    # configured FEDFUNDS series, which is a lagged monthly average and
    # would silently report last month's average level for today's decision.
    "federal funds rate": SeriesMapping("DFEDTARU", Transform.LEVEL, Frequency.DAILY, 2),
    "fomc": SeriesMapping("DFEDTARU", Transform.LEVEL, Frequency.DAILY, 2),
    "fed interest rate decision": SeriesMapping("DFEDTARU", Transform.LEVEL, Frequency.DAILY, 2),
    "fomc statement": SeriesMapping("DFEDTARU", Transform.LEVEL, Frequency.DAILY, 2),
    # --- PPI ---
    # PPIFIS (Final Demand, the modern headline PPI) rather than the legacy
    # PPIACO configured in events.yaml for other purposes.
    "ppi m/m": SeriesMapping("PPIFIS", Transform.MOM_PCT, Frequency.MONTHLY, 1),
    "producer price index": SeriesMapping("PPIFIS", Transform.MOM_PCT, Frequency.MONTHLY, 1),
    "ppi": SeriesMapping("PPIFIS", Transform.MOM_PCT, Frequency.MONTHLY, 1),
    # --- GDP ---
    # A191RL1Q225SBEA (real GDP, % change annualized, as-reported) rather
    # than the configured "GDP" series, which is a dollar level and would
    # need last quarter's dollar level subtracted/annualized to be
    # meaningful — not what FF displays as the "actual".
    "gdp q/q": SeriesMapping("A191RL1Q225SBEA", Transform.LEVEL, Frequency.QUARTERLY, 1),
    "gross domestic product": SeriesMapping("A191RL1Q225SBEA", Transform.LEVEL, Frequency.QUARTERLY, 1),
    "advance gdp": SeriesMapping("A191RL1Q225SBEA", Transform.LEVEL, Frequency.QUARTERLY, 1),
    "preliminary gdp": SeriesMapping("A191RL1Q225SBEA", Transform.LEVEL, Frequency.QUARTERLY, 1),
    "final gdp": SeriesMapping("A191RL1Q225SBEA", Transform.LEVEL, Frequency.QUARTERLY, 1),
    # --- Core PCE Price Index ---
    "core pce price index m/m": SeriesMapping("PCEPILFE", Transform.MOM_PCT, Frequency.MONTHLY, 1),
    "pce": SeriesMapping("PCEPILFE", Transform.MOM_PCT, Frequency.MONTHLY, 1),
    "personal consumption expenditures": SeriesMapping("PCEPILFE", Transform.MOM_PCT, Frequency.MONTHLY, 1),
    "pce price index": SeriesMapping("PCEPILFE", Transform.MOM_PCT, Frequency.MONTHLY, 1),
    # --- Unemployment Claims (weekly) ---
    "unemployment claims": SeriesMapping("ICSA", Transform.LEVEL_K, Frequency.WEEKLY, 0),
    "initial claims": SeriesMapping("ICSA", Transform.LEVEL_K, Frequency.WEEKLY, 0),
    "initial jobless claims": SeriesMapping("ICSA", Transform.LEVEL_K, Frequency.WEEKLY, 0),
    "jobless claims": SeriesMapping("ICSA", Transform.LEVEL_K, Frequency.WEEKLY, 0),
    # --- Retail Sales ---
    # Headline: RSAFS (Advance Retail Sales: Retail Trade and Food
    # Services). Core (ex motor vehicle & parts): RSFSXMV — verified to
    # exist on FRED ("Advance Retail Sales: Retail Trade and Food Services,
    # Excluding Motor Vehicle and Parts Dealers").
    "retail sales m/m": SeriesMapping("RSAFS", Transform.MOM_PCT, Frequency.MONTHLY, 1),
    "retail sales": SeriesMapping("RSAFS", Transform.MOM_PCT, Frequency.MONTHLY, 1),
    "advance retail sales": SeriesMapping("RSAFS", Transform.MOM_PCT, Frequency.MONTHLY, 1),
    "core retail sales m/m": SeriesMapping("RSFSXMV", Transform.MOM_PCT, Frequency.MONTHLY, 1),
    "core retail sales": SeriesMapping("RSFSXMV", Transform.MOM_PCT, Frequency.MONTHLY, 1),
    # --- ISM Manufacturing PMI: no FRED source (NAPM discontinued) ---
    "ism manufacturing pmi": None,
    "ism manufacturing": None,
    "ism pmi": None,
    "manufacturing pmi": None,
}

# Lazily-constructed singleton so importing this module never requires
# FRED_API_KEY to be set. Reset to None on failure so a later call (e.g.
# after the operator fixes .env and restarts) can retry.
_fred_client = None


def _get_fred_client():
    """Return a cached FredClient, or None if it can't be constructed."""
    global _fred_client
    if _fred_client is not None:
        return _fred_client
    try:
        from forex_bot.calendar.fred_client import FredClient

        _fred_client = FredClient()
    except (ImportError, ValueError) as e:
        logger.warning(f"FRED actuals resolver unavailable: {e}")
        return None
    return _fred_client


def lookup_mapping(title: str, country: str) -> SeriesMapping | None:
    """Synchronous, network-free lookup of the FRED mapping for an event.

    Returns None if there is no FRED source for this title/country — either
    because the title is genuinely unknown to this resolver, or because it's
    a known title with no FRED substitute (e.g. ISM Manufacturing PMI). The
    scheduler uses this to skip polling entirely for events with no possible
    source, without ever touching the network.
    """
    if country != "USD":
        return None
    return _TITLE_MAP.get(title.strip().lower())


def _period_index(dt: datetime, frequency: Frequency) -> int:
    """Return a monotonically increasing period index (months or quarters)."""
    if frequency == Frequency.QUARTERLY:
        quarter = (dt.month - 1) // 3
        return dt.year * 4 + quarter
    return dt.year * 12 + dt.month


def _daily_level(observations: list[dict], event_date: datetime) -> float | None:
    """Resolve a point-in-time daily series (DFEDTARU) for an event.

    A new fed funds target range takes effect the business day AFTER the
    FOMC announcement, so the observation dated on (or before) the decision
    day still carries the PRE-decision rate. Take the first observation
    dated after the event day instead, and treat the event as not released
    until one exists — the recurring backfill pass picks it up the next day.
    """
    event_day = event_date.replace(hour=0, minute=0, second=0, microsecond=0)
    max_days = _FRESHNESS_WINDOW_DAYS[Frequency.DAILY]
    for obs in observations:
        if obs["date"] > event_day:
            if (obs["date"] - event_day).days > max_days:
                return None
            return obs["value"]
    return None


def _is_fresh(obs_date: datetime, event_date: datetime, frequency: Frequency) -> bool:
    """Freshness guard: refuse to use an observation that predates the event
    by more than the frequency's window, and — for monthly/quarterly series
    — refuse one that isn't from the period we'd expect this event to cover.
    """
    window = _FRESHNESS_WINDOW_DAYS[frequency]
    age_days = (event_date - obs_date).days
    if age_days < 0 or age_days > window:
        return False

    if frequency in (Frequency.MONTHLY, Frequency.QUARTERLY):
        diff = _period_index(event_date, frequency) - _period_index(obs_date, frequency)
        # e.g. a July CPI release covers June (diff=1); GDP-style
        # reporting lags are allowed up to diff=2.
        if diff not in (1, 2):
            return False

    return True


def _mom_pct(observations: list[dict]) -> float | None:
    if len(observations) < 2:
        return None
    latest = observations[-1]["value"]
    prior = observations[-2]["value"]
    if prior == 0:
        return None
    return (latest - prior) / abs(prior) * 100


def _yoy_pct(observations: list[dict]) -> float | None:
    if len(observations) < 13:
        return None
    latest = observations[-1]["value"]
    year_ago = observations[-13]["value"]
    if year_ago == 0:
        return None
    return (latest - year_ago) / abs(year_ago) * 100


def _mom_diff_k(observations: list[dict]) -> float | None:
    if len(observations) < 2:
        return None
    return observations[-1]["value"] - observations[-2]["value"]


def _apply_transform(observations: list[dict], mapping: SeriesMapping) -> float | None:
    if mapping.transform == Transform.LEVEL:
        return observations[-1]["value"]
    if mapping.transform == Transform.LEVEL_K:
        return observations[-1]["value"] / 1000.0
    if mapping.transform == Transform.MOM_PCT:
        return _mom_pct(observations)
    if mapping.transform == Transform.YOY_PCT:
        return _yoy_pct(observations)
    if mapping.transform == Transform.MOM_DIFF_K:
        return _mom_diff_k(observations)
    return None


def _format(value: float, mapping: SeriesMapping) -> str:
    if mapping.transform in (Transform.LEVEL_K, Transform.MOM_DIFF_K):
        return f"{value:.{mapping.decimals}f}K"
    return f"{value:.{mapping.decimals}f}%"


async def resolve_actual(event: EconomicEvent) -> str | None:
    """Resolve an event's actual value via FRED.

    Returns a formatted string matching Forex Factory display conventions
    (e.g. "0.3%", "227K", "4.50%"), or None if there is no mapping, FRED is
    unavailable, or the release simply hasn't shown up in FRED yet. This
    function never raises — every failure mode logs and returns None so the
    scheduler can safely reschedule and try again later.
    """
    mapping = lookup_mapping(event.title, event.country)
    if mapping is None:
        return None

    fred = _get_fred_client()
    if fred is None:
        return None

    try:
        observations = await asyncio.to_thread(fred.get_series, mapping.series_id)
    except Exception as e:
        logger.warning(f"FRED fetch failed for {mapping.series_id} ({event.title}): {e}")
        return None

    if not observations:
        logger.info(f"No FRED observations yet for {mapping.series_id} ({event.title})")
        return None

    observations = sorted(observations, key=lambda o: o["date"])

    if mapping.frequency == Frequency.DAILY:
        value = _daily_level(observations, event.scheduled_at)
        if value is None:
            logger.info(
                f"No post-event FRED observation yet for {event.title} "
                f"({mapping.series_id}, event {event.scheduled_at}) — "
                f"treating as not released"
            )
            return None
        return _format(value, mapping)

    latest_date = observations[-1]["date"]

    if not _is_fresh(latest_date, event.scheduled_at, mapping.frequency):
        logger.info(
            f"FRED observation for {event.title} ({mapping.series_id}, "
            f"period {latest_date.date()}) not yet current for event on "
            f"{event.scheduled_at} — treating as not released"
        )
        return None

    try:
        value = _apply_transform(observations, mapping)
    except (IndexError, ZeroDivisionError) as e:
        logger.warning(f"Failed to compute actual for {event.title} ({mapping.series_id}): {e}")
        return None

    if value is None:
        logger.info(f"Not enough FRED history to compute actual for {event.title} ({mapping.series_id})")
        return None

    return _format(value, mapping)
