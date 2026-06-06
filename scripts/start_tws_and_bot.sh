#!/bin/bash
#
# Starts TWS via IBC, waits for the API socket to be ready,
# then launches the forex trading bot.
#
# Designed to run from cron or systemd before market hours.
# Requires IB credentials in ~/.env_ibc (not committed to git):
#   IB_USERNAME=your_username
#   IB_PASSWORD=your_password
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$HOME/ibc/logs"
BOT_LOG="$LOG_DIR/forex_bot_$(date +%Y%m%d).log"
IBC_CREDS="$HOME/.env_ibc"
IBC_DIR="$HOME/ibc"
API_PORT=7497
MAX_WAIT=180  # seconds to wait for API socket

mkdir -p "$LOG_DIR"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$BOT_LOG"
}

# --- Load IB credentials ---
if [[ ! -f "$IBC_CREDS" ]]; then
    log "ERROR: $IBC_CREDS not found. Create it with:"
    log "  echo 'IB_USERNAME=your_username' > $IBC_CREDS"
    log "  echo 'IB_PASSWORD=your_password' >> $IBC_CREDS"
    log "  chmod 600 $IBC_CREDS"
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
    export TWSUSERID="$IB_USERNAME"
    export TWSPASSWORD="$IB_PASSWORD"
    "$IBC_DIR/twsstart.sh" -inline \
        >> "$LOG_DIR/ibc_$(date +%Y%m%d).log" 2>&1 &
    unset TWSUSERID TWSPASSWORD

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
log "Forex bot started (PID: $BOT_PID)"
log "Bot log: $BOT_LOG"
