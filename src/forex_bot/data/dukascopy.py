"""Nightly Dukascopy data download job.

Runs the existing download_dukascopy.py script with --skip-existing
to incrementally fetch 1-min data for any new events.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from loguru import logger

SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "download_dukascopy.py"


async def download_new_event_data() -> bool:
    """Download Dukascopy data for any events not yet in the CSVs.

    Returns True if the download succeeded (exit code 0).
    """
    python = sys.executable
    cmd = [python, str(SCRIPT_PATH), "--skip-existing", "--timeframe", "1min"]

    logger.info(f"Nightly Dukascopy download starting: {' '.join(cmd)}")

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode == 0:
        logger.info(f"Nightly Dukascopy download completed successfully")
        if stdout:
            for line in stdout.decode().strip().splitlines()[-5:]:
                logger.debug(f"  {line}")
        return True

    logger.error(
        f"Nightly Dukascopy download failed (exit {proc.returncode}): "
        f"{stderr.decode().strip()[-500:]}"
    )
    return False
