#!/usr/bin/env bash
# Quarterly download of Dukascopy data for all non-US event groups.
# Scheduled via crontab: 0 9 1 1,4,7,10 *
# Downloads 1-min and 5-min bars for SARB, SA CPI, TCMB, BOJ, BOC, etc.

set -euo pipefail

PYTHON="$HOME/anaconda3/envs/forex-bot/bin/python"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DOWNLOAD_SCRIPT="$SCRIPT_DIR/download_dukascopy.py"
LOG_DIR="$HOME/ibc/logs"

echo "$(date '+%Y-%m-%d %H:%M:%S') — Starting quarterly Dukascopy download"

# Download all groups (US events are included by default, non-US via --group)
"$PYTHON" "$DOWNLOAD_SCRIPT" --group south_africa,turkey,japan,canada 2>&1 | tee -a "$LOG_DIR/dukascopy_download.log"

echo "$(date '+%Y-%m-%d %H:%M:%S') — Quarterly Dukascopy download complete"

# Send Telegram notification when done
ENV_FILE="$SCRIPT_DIR/../.env"
TELEGRAM_BOT_TOKEN=$(grep '^TELEGRAM_BOT_TOKEN=' "$ENV_FILE" | cut -d= -f2- | tr -d '[:space:]')
TELEGRAM_CHAT_ID=$(grep '^TELEGRAM_CHAT_ID=' "$ENV_FILE" | cut -d= -f2- | tr -d '[:space:]')

curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  -d chat_id="${TELEGRAM_CHAT_ID}" \
  -d text="✅ Quarterly Dukascopy data download complete. Also update config/static_events.yaml with next quarter's event dates." \
  -d disable_web_page_preview="true" > /dev/null
