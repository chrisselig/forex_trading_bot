#!/bin/bash
#
# Starts TWS via IBC, waits for the API socket to be ready,
# then launches the forex trading bot.
#
# Designed to run from cron or systemd before market hours.
# Requires IB credentials in .env:
#   IB_USERNAME=your_username
#   IB_PASSWORD=your_password
#
# Cron schedule (MT = America/Edmonton):
#   Mon-Fri 5:00 AM MT (7:00 AM ET) — before US events (earliest 8:15 AM ET)
#   Sunday  3:00 PM MT (5:00 PM ET) — forex market open, for Monday AEST AU events
#
# The script is idempotent: if TWS and the bot are already running, it exits cleanly.
#
# Usage:
#   ./start_tws_and_bot.sh          # Normal start (skips if already running)
#   ./start_tws_and_bot.sh --fresh  # Kill everything and start from scratch
#   ./start_tws_and_bot.sh --stop   # Kill everything and exit
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$HOME/ibc/logs"
BOT_LOG="$LOG_DIR/forex_bot_$(date +%Y%m%d).log"
IBC_CREDS="$PROJECT_DIR/.env"
IBC_DIR="$HOME/ibc"
API_PORT=7497
MAX_WAIT=180  # seconds to wait for API socket

mkdir -p "$LOG_DIR"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$BOT_LOG"
}

stop_all() {
    log "Stopping forex bot..."
    pkill -9 -f "forex-bot run" 2>/dev/null && log "Forex bot killed" || log "No forex bot running"

    log "Stopping TWS/IBC..."
    pkill -9 -f "java.*jts" 2>/dev/null && log "TWS killed" || log "No TWS running"
    pkill -9 -f "ibcstart" 2>/dev/null || true

    sleep 2

    # Verify everything is stopped
    if pgrep -f "forex-bot run" >/dev/null 2>&1; then
        log "WARNING: Forex bot still running after kill"
    fi
    if ss -tlnp 2>/dev/null | grep -q ":${API_PORT}"; then
        log "WARNING: Port $API_PORT still in use after kill"
    fi
    log "All processes stopped"
}

# --- Handle command flags ---
case "${1:-}" in
    --stop)
        stop_all
        exit 0
        ;;
    --fresh)
        log "Fresh start requested — killing existing processes..."
        stop_all
        ;;
esac

# --- Load IB credentials ---
if [[ ! -f "$IBC_CREDS" ]]; then
    log "ERROR: $IBC_CREDS not found. Add IB_USERNAME and IB_PASSWORD to your .env file."
    exit 1
fi
source "$IBC_CREDS"

if [[ -z "${IB_USERNAME:-}" || -z "${IB_PASSWORD:-}" ]]; then
    log "ERROR: IB_USERNAME and IB_PASSWORD must be set in $IBC_CREDS"
    exit 1
fi

# --- Check if TWS is already running ---
if ss -tlnp 2>/dev/null | grep -q ":${API_PORT}"; then
    log "TWS API already listening on port $API_PORT, skipping TWS launch"
else
    # Kill any stale TWS/IBC processes
    pkill -f "java.*jts" 2>/dev/null || true
    sleep 2

    log "Starting TWS via IBC..."
    export DISPLAY="${DISPLAY:-:0}"

    # Write credentials into IBC config (file is chmod 600)
    sed -i "s/^IbLoginId=.*/IbLoginId=$IB_USERNAME/" "$IBC_DIR/config.ini"
    sed -i "s/^IbPassword=.*/IbPassword=$IB_PASSWORD/" "$IBC_DIR/config.ini"

    "$IBC_DIR/twsstart.sh" -inline \
        >> "$LOG_DIR/ibc_$(date +%Y%m%d).log" 2>&1 &

    # Wait for API socket to come up
    log "Waiting for TWS API on port $API_PORT (up to ${MAX_WAIT}s)..."
    elapsed=0
    while ! ss -tlnp 2>/dev/null | grep -q ":${API_PORT}"; do
        sleep 5
        elapsed=$((elapsed + 5))
        if [[ $elapsed -ge $MAX_WAIT ]]; then
            log "ERROR: TWS API not available after ${MAX_WAIT}s. Check IBC logs."
            exit 1
        fi
    done
    log "TWS API is listening on port $API_PORT (took ${elapsed}s)"

    # Give TWS time to finish initialization (dismiss dialogs, load data)
    log "Waiting 15s for TWS to finish initializing..."
    sleep 15
fi

# --- Start the forex bot ---
# Check if bot is already running
if pgrep -f "forex-bot run" >/dev/null 2>&1; then
    log "Forex bot is already running, skipping bot launch"
    exit 0
fi

log "Starting forex trading bot..."
source "$HOME/anaconda3/etc/profile.d/conda.sh"
conda activate forex-bot
cd "$PROJECT_DIR"
nohup forex-bot run >> "$BOT_LOG" 2>&1 &
BOT_PID=$!

# Verify bot started successfully
sleep 5
if ps -p $BOT_PID >/dev/null 2>&1; then
    log "Forex bot started (PID: $BOT_PID)"
else
    log "ERROR: Forex bot failed to start. Check $BOT_LOG"
    exit 1
fi
log "Bot log: $BOT_LOG"
