#!/bin/bash
#
# Restarts TWS via IBC without touching the forex bot process.
#
# Called by the bot's tws_launcher module when TWS is detected as dead
# (e.g., after the nightly ~9:45 PM MT disconnect) before an overnight event.
#
# Sources .env for IB credentials, kills stale TWS/IBC Java processes,
# writes credentials into config.ini, and starts TWS via IBC.
#
# Exit codes:
#   0 - TWS API port is listening
#   1 - Timeout waiting for TWS API port
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$HOME/ibc/logs"
IBC_CREDS="$PROJECT_DIR/.env"
IBC_DIR="$HOME/ibc"
API_PORT="${1:-7497}"
MAX_WAIT=180  # seconds to wait for API socket

mkdir -p "$LOG_DIR"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [restart_tws] $*" | tee -a "$LOG_DIR/ibc_$(date +%Y%m%d).log"
}

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

# --- Kill stale TWS/IBC processes (NOT the forex bot) ---
log "Killing stale TWS/IBC processes..."
pkill -9 -f "java.*jts" 2>/dev/null && log "Stale TWS killed" || log "No stale TWS found"
pkill -9 -f "ibcstart" 2>/dev/null || true
sleep 2

# Verify port is clear
if ss -tlnp 2>/dev/null | grep -q ":${API_PORT}"; then
    log "WARNING: Port $API_PORT still in use after kill, waiting..."
    sleep 5
fi

# --- Start TWS via IBC ---
log "Starting TWS via IBC..."
export DISPLAY="${DISPLAY:-:0}"

# Write credentials into IBC config (file is chmod 600)
sed -i "s/^IbLoginId=.*/IbLoginId=$IB_USERNAME/" "$IBC_DIR/config.ini"
sed -i "s/^IbPassword=.*/IbPassword=$IB_PASSWORD/" "$IBC_DIR/config.ini"

"$IBC_DIR/twsstart.sh" -inline \
    >> "$LOG_DIR/ibc_$(date +%Y%m%d).log" 2>&1 &

# --- Wait for API socket to come up ---
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

log "TWS restart complete."
exit 0
