"""Tests for TWS cold-start launcher."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from forex_bot.broker.tws_launcher import (
    ensure_tws_running,
    is_tws_listening,
)
from forex_bot.models.events import EconomicEvent, EventImpact


# ---------------------------------------------------------------------------
# is_tws_listening
# ---------------------------------------------------------------------------


def test_is_tws_listening_up():
    """Port probe returns True when connection succeeds."""
    with patch("forex_bot.broker.tws_launcher.socket.socket") as mock_socket:
        sock_instance = MagicMock()
        mock_socket.return_value.__enter__ = MagicMock(return_value=sock_instance)
        mock_socket.return_value.__exit__ = MagicMock(return_value=False)
        sock_instance.connect_ex.return_value = 0

        assert is_tws_listening(7497) is True
        sock_instance.connect_ex.assert_called_once_with(("127.0.0.1", 7497))


def test_is_tws_listening_down():
    """Port probe returns False when connection is refused."""
    with patch("forex_bot.broker.tws_launcher.socket.socket") as mock_socket:
        sock_instance = MagicMock()
        mock_socket.return_value.__enter__ = MagicMock(return_value=sock_instance)
        mock_socket.return_value.__exit__ = MagicMock(return_value=False)
        sock_instance.connect_ex.return_value = 111  # ECONNREFUSED

        assert is_tws_listening(7497) is False


def test_is_tws_listening_os_error():
    """Port probe returns False on OSError."""
    with patch("forex_bot.broker.tws_launcher.socket.socket") as mock_socket:
        mock_socket.return_value.__enter__ = MagicMock(
            side_effect=OSError("Network unreachable")
        )
        mock_socket.return_value.__exit__ = MagicMock(return_value=False)

        assert is_tws_listening(7497) is False


# ---------------------------------------------------------------------------
# ensure_tws_running
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ensure_tws_already_running():
    """If TWS is already listening, no subprocess is called."""
    with patch("forex_bot.broker.tws_launcher.is_tws_listening", return_value=True):
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            result = await ensure_tws_running(7497)
            assert result is True
            mock_exec.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_tws_starts_successfully():
    """TWS is down, subprocess runs, port comes up."""
    call_count = 0

    def port_check(port, host="127.0.0.1"):
        nonlocal call_count
        call_count += 1
        # First call (guard): down. Second call (poll): up.
        return call_count > 1

    mock_proc = AsyncMock()
    mock_proc.returncode = None
    mock_proc.stdout = AsyncMock()
    mock_proc.stderr = AsyncMock()

    with (
        patch("forex_bot.broker.tws_launcher.is_tws_listening", side_effect=port_check),
        patch("asyncio.create_subprocess_exec", return_value=mock_proc),
        patch("forex_bot.broker.tws_launcher.asyncio.sleep", new_callable=AsyncMock),
    ):
        result = await ensure_tws_running(7497)
        assert result is True


@pytest.mark.asyncio
async def test_ensure_tws_timeout():
    """TWS never comes up — returns False after timeout."""
    mock_proc = AsyncMock()
    mock_proc.returncode = None
    mock_proc.stdout = AsyncMock()
    mock_proc.stderr = AsyncMock()

    with (
        patch("forex_bot.broker.tws_launcher.is_tws_listening", return_value=False),
        patch("asyncio.create_subprocess_exec", return_value=mock_proc),
        patch("forex_bot.broker.tws_launcher.asyncio.sleep", new_callable=AsyncMock),
    ):
        result = await ensure_tws_running(7497)
        assert result is False


@pytest.mark.asyncio
async def test_ensure_tws_script_not_found():
    """Returns False if restart script doesn't exist."""
    with patch("forex_bot.broker.tws_launcher.is_tws_listening", return_value=False):
        result = await ensure_tws_running(7497, script_path="/nonexistent/script.sh")
        assert result is False


# ---------------------------------------------------------------------------
# _tws_ensure job (via JobManager)
# ---------------------------------------------------------------------------


def _make_job_manager(**overrides):
    """Create a minimal JobManager for testing _tws_ensure."""
    from forex_bot.scheduler.jobs import JobManager

    defaults = {
        "scheduler": MagicMock(),
        "execution_engine": MagicMock(),
        "pricing": MagicMock(),
        "event_store": MagicMock(),
        "strategy_registry": MagicMock(),
        "monitor": MagicMock(),
        "client": MagicMock(),
        "settings": MagicMock(),
        "notifier": None,
    }
    defaults.update(overrides)
    defaults["settings"].broker.port = 7497
    return JobManager(**defaults)


def _make_event():
    return EconomicEvent(
        id=99,
        title="South Africa CPI",
        country="ZAR",
        impact=EventImpact.HIGH,
        scheduled_at=datetime.now(UTC) + timedelta(hours=1),
    )


@pytest.mark.asyncio
async def test_tws_ensure_job_skips_when_running():
    """_tws_ensure does nothing if TWS is already up."""
    jm = _make_job_manager()
    event = _make_event()

    with patch("forex_bot.scheduler.jobs.is_tws_listening", return_value=True):
        with patch("forex_bot.scheduler.jobs.ensure_tws_running") as mock_ensure:
            await jm._tws_ensure(event)
            mock_ensure.assert_not_called()


@pytest.mark.asyncio
async def test_tws_ensure_job_cold_starts():
    """_tws_ensure triggers cold-start when TWS is down."""
    notifier = AsyncMock()
    jm = _make_job_manager(notifier=notifier)
    event = _make_event()

    with (
        patch("forex_bot.scheduler.jobs.is_tws_listening", return_value=False),
        patch("forex_bot.scheduler.jobs.ensure_tws_running", new_callable=AsyncMock, return_value=True),
    ):
        await jm._tws_ensure(event)
        # Telegram alerts should have been sent (cold-start + success)
        assert notifier.send_raw.call_count == 2
