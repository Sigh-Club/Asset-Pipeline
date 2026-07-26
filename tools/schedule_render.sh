#!/bin/bash
# schedule_render.sh — Launch queued renders when machine is idle.
# Use with cron, at, systemd timers, or run manually.
#
# Examples:
#   # Run at 2am via `at`:
#   at 02:00 -f tools/schedule_render.sh
#
#   # Run daily at 1am via cron:
#   0 1 * * * /path/to/asset-pipeline/tools/schedule_render.sh
#
#   # Run now if queue has items:
#   bash tools/schedule_render.sh
#
#   # Run immediately and snooze system sleep for duration:
#   bash tools/schedule_render.sh --no-sleep
#
#   # Run with low CPU priority (yield to interactive tasks):
#   bash tools/schedule_render.sh --nice
#
#   # Run in fast mode (16 samples):
#   bash tools/schedule_render.sh --fast

set -e

# --- Configuration ---
cd "$(dirname "$0")/.."
PROJECT_ROOT=$(pwd)
QUEUE_FILE="$PROJECT_ROOT/output/render_queue.json"
LOG_FILE="$PROJECT_ROOT/output/schedule_render.log"
LOCK_FILE="$PROJECT_ROOT/output/.render.lock"

FAST=""
NICE=""

# --- Parse args ---
for arg in "$@"; do
    case "$arg" in
        --fast) FAST="--fast" ;;
        --nice) NICE="nice -n 19" ;;
        --no-sleep) NO_SLEEP=1 ;;
        --help)
            echo "Usage: $0 [--fast] [--nice] [--no-sleep]"
            echo ""
            echo "  --fast      16 Cycles samples instead of 32"
            echo "  --nice      Low CPU priority (yield to interactive tasks)"
            echo "  --no-sleep  Prevent system sleep while rendering"
            exit 0
            ;;
    esac
done

# --- Lock file to prevent overlapping runs ---
if [ -f "$LOCK_FILE" ]; then
    LOCK_PID=$(cat "$LOCK_FILE")
    if kill -0 "$LOCK_PID" 2>/dev/null; then
        echo "[$(date)] Render already running (PID $LOCK_PID). Exiting." | tee -a "$LOG_FILE"
        exit 0
    fi
    echo "[$(date)] Stale lock file removed (PID $LOCK_PID no longer running)." | tee -a "$LOG_FILE"
fi
echo $$ > "$LOCK_FILE"
trap 'rm -f "$LOCK_FILE"' EXIT

# --- Check queue ---
if [ ! -f "$QUEUE_FILE" ]; then
    echo "[$(date)] No queue file found. Nothing to render." | tee -a "$LOG_FILE"
    exit 0
fi

QUEUED_COUNT=$(python3 -c "
import json
try:
    q = json.load(open('$QUEUE_FILE'))
    print(sum(1 for j in q if j.get('status') == 'queued'))
except: print(0)
")

if [ "$QUEUED_COUNT" -eq 0 ]; then
    echo "[$(date)] No queued renders. Exiting." | tee -a "$LOG_FILE"
    exit 0
fi

echo "" | tee -a "$LOG_FILE"
echo "==========================================" | tee -a "$LOG_FILE"
echo "[$(date)] Starting scheduled render run" | tee -a "$LOG_FILE"
echo "  Queue: $QUEUED_COUNT items pending" | tee -a "$LOG_FILE"
echo "  Mode:  ${FAST:-standard}" | tee -a "$LOG_FILE"
echo "==========================================" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

# --- Prevent system sleep (if inhibit command available) ---
if [ -z "$NO_SLEEP" ] && command -v systemd-inhibit &>/dev/null; then
    # Wrap with systemd-inhibit to prevent sleep during renders
    exec systemd-inhibit --what=sleep --why="Rendering game assets" -- \
        $NICE python3 -m tools.render_queue run $FAST 2>&1 | tee -a "$LOG_FILE"
else
    $NICE python3 -m tools.render_queue run $FAST 2>&1 | tee -a "$LOG_FILE"
fi

RESULT=${PIPESTATUS[0]}

echo "" | tee -a "$LOG_FILE"
echo "==========================================" | tee -a "$LOG_FILE"
echo "[$(date)] Render run complete (exit: $RESULT)" | tee -a "$LOG_FILE"
echo "==========================================" | tee -a "$LOG_FILE"

# --- If any renders succeeded, offer to pack ---
DONE_COUNT=$(python3 -c "
import json
try:
    q = json.load(open('$QUEUE_FILE'))
    print(sum(1 for j in q if j.get('status') == 'done' and j.get('result') == 'pass'))
except: print(0)
")

if [ "$DONE_COUNT" -gt 0 ]; then
    echo "" | tee -a "$LOG_FILE"
    echo "  $DONE_COUNT renders completed successfully." | tee -a "$LOG_FILE"
    echo "  Run to pack atlases:" | tee -a "$LOG_FILE"
    echo "    PIPELINE_VERSION=v0.4.0 python3 tools/batch_pipeline.py" | tee -a "$LOG_FILE"
fi

exit $RESULT
