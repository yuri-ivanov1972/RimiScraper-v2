#!/bin/bash
# Combined Startup Script for Reserved VM
# Runs both Streamlit UI and background worker with auto-restart

set -e  # Exit on error during startup phase

echo "=========================================="
echo "Rimi Product Scraper - Combined Startup"
echo "=========================================="
echo "Started at: $(date)"
echo ""

# Create logs directory
mkdir -p logs

# Crash log file
CRASH_LOG="logs/crash_history.log"
STREAMLIT_LOG="logs/streamlit.log"

# Configuration
STREAMLIT_HOST="${STREAMLIT_HOST:-0.0.0.0}"
STREAMLIT_PORT="${STREAMLIT_PORT:-5000}"
STREAMLIT_HEALTH_URL="http://127.0.0.1:${STREAMLIT_PORT}/_stcore/health"
STREAMLIT_STARTUP_TIMEOUT="${STREAMLIT_STARTUP_TIMEOUT:-120}"
MAX_RAPID_RESTARTS=5       # Max restarts within rapid window before longer pause
RAPID_RESTART_WINDOW=300   # 5 minutes - if crashes happen faster, it's a rapid loop
INITIAL_DELAY=30           # Initial restart delay
MAX_DELAY=600              # Max restart delay (10 minutes)
LONG_PAUSE=1800            # 30 minute pause after max rapid restarts

# Function to log crashes
log_crash() {
    local exit_code=$1
    local restart_count=$2
    local delay=$3
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Worker crashed with exit code $exit_code (restart #$restart_count, delay ${delay}s)" >> "$CRASH_LOG"
}

cleanup() {
    if [ -n "${WORKER_PID:-}" ] && kill -0 "$WORKER_PID" 2>/dev/null; then
        echo "Stopping worker (PID: $WORKER_PID)..."
        kill "$WORKER_PID" 2>/dev/null || true
        wait "$WORKER_PID" 2>/dev/null || true
    fi
    if [ -n "${STREAMLIT_PID:-}" ] && kill -0 "$STREAMLIT_PID" 2>/dev/null; then
        echo "Stopping Streamlit (PID: $STREAMLIT_PID)..."
        kill "$STREAMLIT_PID" 2>/dev/null || true
        wait "$STREAMLIT_PID" 2>/dev/null || true
    fi
}

trap cleanup EXIT
trap 'exit 0' TERM INT

# Start Streamlit in background
echo "Starting Streamlit UI on ${STREAMLIT_HOST}:${STREAMLIT_PORT}..."
PYTHONUNBUFFERED=1 streamlit run main.py \
    --server.address "$STREAMLIT_HOST" \
    --server.port "$STREAMLIT_PORT" \
    --server.headless true \
    --browser.gatherUsageStats false \
    > >(tee -a "$STREAMLIT_LOG") 2>&1 &
STREAMLIT_PID=$!
echo "Streamlit started (PID: $STREAMLIT_PID)"

# Wait until Streamlit is actually serving requests, not merely still running.
echo "Waiting up to ${STREAMLIT_STARTUP_TIMEOUT}s for ${STREAMLIT_HEALTH_URL}..."
STREAMLIT_READY=0
for ((elapsed=0; elapsed<STREAMLIT_STARTUP_TIMEOUT; elapsed+=2)); do
    if curl --silent --fail --max-time 2 "$STREAMLIT_HEALTH_URL" >/dev/null; then
        STREAMLIT_READY=1
        break
    fi
    if ! kill -0 "$STREAMLIT_PID" 2>/dev/null; then
        echo "Streamlit exited before becoming healthy."
        break
    fi
    sleep 2
done

if [ "$STREAMLIT_READY" -ne 1 ]; then
    echo "Streamlit failed to become healthy within ${STREAMLIT_STARTUP_TIMEOUT}s."
    echo "Last 100 lines from ${STREAMLIT_LOG}:"
    tail -n 100 "$STREAMLIT_LOG" 2>/dev/null || true
    exit 1
fi

echo "Streamlit health check passed."

# Used by validation to exercise the exact deployment web startup without
# launching the production worker.
if [ "${STARTUP_HEALTHCHECK_ONLY:-0}" = "1" ]; then
    echo "Startup health-check-only mode completed successfully."
    exit 0
fi

echo ""
echo "Starting worker with built-in scheduler (with auto-restart)..."
echo "Worker will:"
echo "  - Process any queued jobs immediately"
echo "  - Queue all categories daily at 2:00 AM Latvia time"
echo "  - Generate reports at 6:00 AM Latvia time"
echo "  - Auto-restart on crash (with exponential backoff)"
echo ""

# Disable set -e for the restart loop (we handle exits manually)
set +e

# Initialize restart tracking
RESTART_COUNT=0
RAPID_RESTART_COUNT=0
LAST_RESTART_TIME=0
CURRENT_DELAY=$INITIAL_DELAY

# Run worker in infinite restart loop with backoff
while true; do
    RESTART_COUNT=$((RESTART_COUNT + 1))
    CURRENT_TIME=$(date +%s)
    
    # Check if this is a rapid restart (crash within window)
    if [ $LAST_RESTART_TIME -gt 0 ]; then
        TIME_SINCE_LAST=$((CURRENT_TIME - LAST_RESTART_TIME))
        if [ $TIME_SINCE_LAST -lt $RAPID_RESTART_WINDOW ]; then
            RAPID_RESTART_COUNT=$((RAPID_RESTART_COUNT + 1))
            # Exponential backoff
            CURRENT_DELAY=$((CURRENT_DELAY * 2))
            if [ $CURRENT_DELAY -gt $MAX_DELAY ]; then
                CURRENT_DELAY=$MAX_DELAY
            fi
        else
            # Reset if stable for a while
            RAPID_RESTART_COUNT=0
            CURRENT_DELAY=$INITIAL_DELAY
        fi
    fi
    
    # If too many rapid restarts, take a long pause
    if [ $RAPID_RESTART_COUNT -ge $MAX_RAPID_RESTARTS ]; then
        echo ""
        echo "=========================================="
        echo "WARNING: Too many rapid restarts ($RAPID_RESTART_COUNT)"
        echo "Taking a ${LONG_PAUSE}s pause to prevent crash loop"
        echo "Check logs for persistent errors"
        echo "=========================================="
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] LONG PAUSE: Too many rapid restarts ($RAPID_RESTART_COUNT), waiting ${LONG_PAUSE}s" >> "$CRASH_LOG"
        sleep $LONG_PAUSE
        RAPID_RESTART_COUNT=0
        CURRENT_DELAY=$INITIAL_DELAY
    fi
    
    LAST_RESTART_TIME=$CURRENT_TIME
    
    if [ $RESTART_COUNT -gt 1 ]; then
        echo ""
        echo "=========================================="
        echo "RESTARTING WORKER (attempt #$RESTART_COUNT)"
        echo "Restart at: $(date)"
        echo "Rapid restart count: $RAPID_RESTART_COUNT"
        echo "=========================================="
        echo ""
    fi
    
    # Run the worker with scheduler
    python worker_with_scheduler.py --production --chunk-size 15 --max-workers 3 --heartbeat-interval 30 &
    WORKER_PID=$!
    wait "$WORKER_PID"
    EXIT_CODE=$?
    WORKER_PID=""
    
    # Log the crash
    echo ""
    echo "[$(date)] Worker exited with code $EXIT_CODE"
    log_crash $EXIT_CODE $RESTART_COUNT $CURRENT_DELAY
    
    # Wait before restart
    echo "Waiting ${CURRENT_DELAY}s before restart..."
    sleep $CURRENT_DELAY
done
