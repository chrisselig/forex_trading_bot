"""Tests for event alias collision prevention."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from forex_bot.calendar.parser import validate_alias_uniqueness
from forex_bot.config import EventTarget
from forex_bot.models.events import EconomicEvent, EventImpact


# ---------------------------------------------------------------------------
# 1. Real events.yaml must have no cross-country alias collisions
# ---------------------------------------------------------------------------


def test_no_duplicate_aliases_across_countries():
    """Load real events.yaml and assert no alias maps to multiple countries."""
    from forex_bot.config import get_settings

    settings = get_settings()
    targets = settings.events.target_events

    alias_map: dict[str, set[str]] = {}
    for target in targets:
        country = target.country or "unknown"
        keys = [target.name.lower().strip()]
        for alias in target.aliases:
            keys.append(alias.lower().strip())
        for key in keys:
            alias_map.setdefault(key, set()).add(country)

    collisions = {k: v for k, v in alias_map.items() if len(v) > 1}
    assert not collisions, f"Cross-country alias collisions found: {collisions}"


# ---------------------------------------------------------------------------
# 2. Startup validator raises on intentionally bad config
# ---------------------------------------------------------------------------


def test_startup_validator_catches_collision():
    """validate_alias_uniqueness raises ValueError on cross-country duplicates."""
    targets = [
        EventTarget(
            name="Employment Change",
            aliases=["Jobs Data"],
            country="CAD",
            pairs=["USDCAD"],
        ),
        EventTarget(
            name="Australia Employment",
            aliases=["Employment Change"],  # collides with CAD canonical name
            country="AUD",
            pairs=["AUDUSD"],
        ),
    ]
    with pytest.raises(ValueError, match="Ambiguous event aliases"):
        validate_alias_uniqueness(targets)


def test_startup_validator_allows_unique_aliases():
    """validate_alias_uniqueness passes when all aliases are unique per country."""
    targets = [
        EventTarget(
            name="Non-Farm Employment Change",
            aliases=["NFP"],
            country="USD",
            pairs=["USDZAR"],
        ),
        EventTarget(
            name="Australia Employment",
            aliases=["AU Employment Change"],
            country="AUD",
            pairs=["AUDUSD"],
        ),
    ]
    # Should not raise
    validate_alias_uniqueness(targets)


# ---------------------------------------------------------------------------
# 3. _lookup_target_pairs respects country
# ---------------------------------------------------------------------------


def test_lookup_target_pairs_respects_country():
    """A CAD event titled 'Employment Change' must NOT match an AUD target."""
    from forex_bot.scheduler.jobs import JobManager

    au_target = EventTarget(
        name="Australia Employment",
        aliases=["Employment Change"],
        country="AUD",
        pairs=["AUDUSD"],
    )

    mock_settings = MagicMock()
    mock_settings.events.target_events = [au_target]

    jm = JobManager.__new__(JobManager)
    jm._settings = mock_settings

    cad_event = EconomicEvent(
        id=99,
        title="Employment Change",
        country="CAD",
        impact=EventImpact.HIGH,
        scheduled_at=datetime.now(UTC) + timedelta(hours=1),
    )

    pairs = jm._lookup_target_pairs(cad_event)
    assert pairs == [], f"Expected no pairs for CAD event, got {pairs}"


def test_lookup_target_pairs_matches_same_country():
    """An AUD event titled 'Employment Change' SHOULD match the AUD target."""
    from forex_bot.scheduler.jobs import JobManager

    au_target = EventTarget(
        name="Australia Employment",
        aliases=["Employment Change"],
        country="AUD",
        pairs=["AUDUSD"],
    )

    mock_settings = MagicMock()
    mock_settings.events.target_events = [au_target]

    jm = JobManager.__new__(JobManager)
    jm._settings = mock_settings

    aud_event = EconomicEvent(
        id=100,
        title="Employment Change",
        country="AUD",
        impact=EventImpact.HIGH,
        scheduled_at=datetime.now(UTC) + timedelta(hours=1),
    )

    pairs = jm._lookup_target_pairs(aud_event)
    assert pairs == ["AUDUSD"]
