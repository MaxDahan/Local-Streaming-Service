#!/usr/bin/env bash

# Determine project root (assumes script is in project root or src/)
BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
PIDFILE="$BASE_DIR/output/server.pid"

# Stop all channel streams
"$BASE_DIR/src/stop_all_streams.sh"

# Stop all on demand streams
"$BASE_DIR/src/stop_on_demand.sh"

SERVER_PIDS="$(pgrep -f "src/start_server.py" | tr '\n' ' ' )"
stopped=0

if [ -f "$PIDFILE" ]; then
    PID=$(cat "$PIDFILE")
    if ps -p "$PID" > /dev/null 2>&1; then
        sudo kill "$PID"
        echo "✅ Server stopped (PID $PID)"
        stopped=1
    else
        echo "⚠️ PID file exists but process not running"
    fi
    rm -f "$PIDFILE"
fi

if [ -n "$SERVER_PIDS" ]; then
    echo "⚠️ Found leftover start_server.py process(es): $SERVER_PIDS"
    sudo kill $SERVER_PIDS
    stopped=1
fi

if [ "$stopped" -eq 0 ]; then
    echo "❌ Server not running"
    exit 1
fi
