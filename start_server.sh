#!/bin/bash

BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$BASE_DIR/output"

"$BASE_DIR/src/start_all_streams.sh"

LOGFILE="$BASE_DIR/output/server.log"
PIDFILE="$BASE_DIR/output/server.pid"

# Start server detached from terminal
nohup python3 "$BASE_DIR/src/start_server.py" > "$LOGFILE" 2>&1 &

# Save PID
echo $! > "$PIDFILE"

echo "Server started in background"
echo "PID: $(cat "$PIDFILE")"
echo "Logs: $LOGFILE"
