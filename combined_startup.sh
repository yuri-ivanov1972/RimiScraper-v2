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

# Configuration
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

# Start Streamlit in background
echo "Starting Streamlit UI on port 5000..."
streamlit run main.py --server.port 5000 > logs/streamlit.log 2>&1 &
STREAMLIT_PID=$!
echo "Streamlit started (PID: $STREAMLIT_PID)"

# Wait for Streamlit to initialize
sleep 5

# Check if Streamlit is running
if kill -0 $STREAMLIT_PID 2>/dev/null; then
    echo "✓ Streamlit is running"
else
    echo "✗ Streamlit failed to start, check logs/streamlit.log"
    exit 1
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
    python worker_with_scheduler.py --production --chunk-size 15 --max-workers 3 --heartbeat-interval 30
    EXIT_CODE=$?
    
    # Log the crash
    echo ""
    echo "[$(date)] Worker exited with code $EXIT_CODE"
    log_crash $EXIT_CODE $RESTART_COUNT $CURRENT_DELAY
    
    # Wait before restart
    echo "Waiting ${CURRENT_DELAY}s before restart..."
    sleep $CURRENT_DELAY
done
