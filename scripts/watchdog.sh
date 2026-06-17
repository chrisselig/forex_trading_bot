#!/bin/bash
#
# Bot watchdog — restarts the forex bot if its scheduler has frozen.
#
# Checks whether the bot log file has been updated in the last STALE_MINUTES.
# Health checks log every 5 min, so 10 min staleness means 2 missed health checks.
#
# If the bot is alive but stale, kills and restarts it. TWS is left alone
# (stop losses / take profits are server-side IB orders and survive a bot restart).
#
# Cron: */5 * * * * (every 5 minutes)
# Worst-case recovery: 15 min (10 min stale threshold + 5 min cron interval)
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$HOME/ibc/logs"
BOT_LOG="$LOG_DIR/forex_bot_$(date +%Y%m%d).log"
WATCHDOG_LOG="$LOG_DIR/watchdog.log"
STALE_MINUTES=10

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [watchdog] $*" >> "$WATCHDOG_LOG"
}

# --- Is the bot even running? ---
if ! pgrep -f "forex-bot run" >/dev/null 2>&1; then
    # Bot is not running — not our job to start it (that's start_tws_and_bot.sh)
    exit 0
fi

# --- Does the log file exist? ---
if [[ ! -f "$BOT_LOG" ]]; then
    log "WARNING: Bot is running but log file $BOT_LOG does not exist"
    exit 0
fi

# --- Is the log stale? ---
last_modified=$(stat -c %Y "$BOT_LOG" 2>/dev/null || echo 0)
now=$(date +%s)
age_seconds=$(( now - last_modified ))
age_minutes=$(( age_seconds / 60 ))

if [[ $age_minutes -lt $STALE_MINUTES ]]; then
    # Bot is healthy — log file updated recently
    exit 0
fi

# --- Bot is frozen: kill and restart ---
log "FROZEN: Bot log stale for ${age_minutes}m (threshold: ${STALE_MINUTES}m). Restarting bot..."

BOT_PID=$(pgrep -f "forex-bot run" | head -1)
kill -9 "$BOT_PID" 2>/dev/null
log "Killed frozen bot (PID: $BOT_PID)"
sleep 3

# Verify it's dead
if pgrep -f "forex-bot run" >/dev/null 2>&1; then
    log "ERROR: Bot still running after SIGKILL"
    exit 1
fi

# Restart the bot (TWS should still be up — server-side orders are safe)
source "$HOME/anaconda3/etc/profile.d/conda.sh"
conda activate forex-bot
cd "$PROJECT_DIR"

# Use today's log (may have rolled over at midnight)
BOT_LOG="$LOG_DIR/forex_bot_$(date +%Y%m%d).log"
PYTHONUNBUFFERED=1 nohup forex-bot run >> "$BOT_LOG" 2>&1 &
NEW_PID=$!

sleep 5
if ps -p $NEW_PID >/dev/null 2>&1; then
    log "Bot restarted successfully (PID: $NEW_PID)"
else
    log "ERROR: Bot failed to restart. Check $BOT_LOG"
    exit 1
fi
