#!/usr/bin/env bash
# Sends a Telegram reminder to update static_events.yaml with next quarter's dates.
# Scheduled via crontab: 0 9 1 1,4,7,10 *

set -euo pipefail

# Load Telegram credentials from .env
ENV_FILE="$(dirname "$0")/../.env"
TELEGRAM_BOT_TOKEN=$(grep '^TELEGRAM_BOT_TOKEN=' "$ENV_FILE" | cut -d= -f2- | tr -d '[:space:]')
TELEGRAM_CHAT_ID=$(grep '^TELEGRAM_CHAT_ID=' "$ENV_FILE" | cut -d= -f2- | tr -d '[:space:]')

MESSAGE="📅 *Quarterly Reminder*

Update \`config/static_events.yaml\` with next quarter's event dates:

• SARB Rate Decisions — [resbank.co.za](https://www.resbank.co.za/en/home/publications/scheduled-publications)
• South Africa CPI — Stats SA release calendar
• TCMB Rate Decisions — [tcmb.gov.tr](https://www.tcmb.gov.tr/wps/wcm/connect/EN/TCMB+EN/Main+Menu/Announcements/Press+Releases)
• BOJ Policy Rate — [boj.or.jp](https://www.boj.or.jp/en/mopo/mpmdeci/index.htm)

File: \`config/static_events.yaml\`"

curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  -d chat_id="${TELEGRAM_CHAT_ID}" \
  -d text="${MESSAGE}" \
  -d parse_mode="Markdown" \
  -d disable_web_page_preview="true" > /dev/null
