#!/usr/bin/env bash

# Determine project root (assumes script is in project root or src/)
BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
PIDFILE="$BASE_DIR/output/server.pid"

# Stop all channel streams
"$BASE_DIR/src/stop_all_streams.sh"

# Stop all on demand streams
"$BASE_DIR/src/stop_on_demand.sh"

if [ ! -f "$PIDFILE" ]; then
    echo "❌ Server not running (no PID file found)"
    exit 1
fi

PID=$(cat "$PIDFILE")

if ps -p "$PID" > /dev/null 2>&1; then
    sudo kill "$PID"
    echo "✅ Server stopped (PID $PID)"
else
    echo "⚠️ Process not found, cleaning up PID file"
fi

rm -f "$PIDFILE"
