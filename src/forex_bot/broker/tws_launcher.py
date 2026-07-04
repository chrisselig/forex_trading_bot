from __future__ import annotations

import asyncio
import socket
from pathlib import Path

from loguru import logger

# Default script path relative to project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_DEFAULT_SCRIPT = str(_PROJECT_ROOT / "scripts" / "restart_tws_only.sh")

# Timeouts
_ENSURE_TIMEOUT_SECONDS = 210
_POLL_INTERVAL_SECONDS = 5


def is_tws_listening(port: int = 7497, host: str = "127.0.0.1") -> bool:
    """Check if TWS API port is accepting connections via a TCP socket probe.

    Synchronous — for scripts and tests. Inside the event loop use
    is_tws_listening_async, which does not block the loop for the probe
    timeout.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(2)
            result = sock.connect_ex((host, port))
            return result == 0
    except OSError:
        return False


async def is_tws_listening_async(port: int = 7497, host: str = "127.0.0.1") -> bool:
    """Non-blocking TWS port probe for use inside the event loop."""
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=2.0
        )
        writer.close()
        await writer.wait_closed()
        return True
    except (TimeoutError, OSError):
        return False


async def ensure_tws_running(
    port: int = 7497,
    script_path: str = _DEFAULT_SCRIPT,
) -> bool:
    """Start TWS via restart_tws_only.sh if it's not already listening.

    Returns True if TWS is listening after the call (already up or successfully started).
    Returns False if the script fails or times out.
    """
    if await is_tws_listening_async(port):
        logger.debug(f"TWS already listening on port {port}")
        return True

    logger.warning(f"TWS not listening on port {port}, launching cold-start via {script_path}")

    try:
        proc = await asyncio.create_subprocess_exec(
            "bash", script_path, str(port),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        logger.error(f"TWS restart script not found: {script_path}")
        return False

    # Drain stdout/stderr continuously and reap the process when it exits.
    # Without this, a chatty startup script fills the 64KB pipe buffer,
    # blocks on write mid-startup, and the cold-start "times out" for a
    # reason invisible in the logs.
    drain_task = asyncio.create_task(proc.communicate())
    drain_task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)

    # Poll for port readiness while subprocess runs (timeout _ENSURE_TIMEOUT_SECONDS)
    elapsed = 0
    while elapsed < _ENSURE_TIMEOUT_SECONDS:
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)
        elapsed += _POLL_INTERVAL_SECONDS

        if await is_tws_listening_async(port):
            logger.info(f"TWS is now listening on port {port} after {elapsed}s")
            return True

        # If the script already exited with error, bail early
        if proc.returncode is not None and proc.returncode != 0:
            stdout, stderr = await drain_task
            logger.error(
                f"TWS restart script exited with code {proc.returncode}: "
                f"stdout={stdout.decode()[-500:]}, stderr={stderr.decode()[-500:]}"
            )
            return False

    logger.error(f"TWS cold-start timed out after {_ENSURE_TIMEOUT_SECONDS}s")
    # Don't kill the script — TWS may still be starting up
    return False
