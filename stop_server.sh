#!/bin/bash

./stop_all_streams.sh

PIDFILE="server.pid"

if [ ! -f "$PIDFILE" ]; then
    echo "Server not running (no PID file found)"
    exit 1
fi

PID=$(cat "$PIDFILE")

if ps -p $PID > /dev/null; then
    sudo kill $PID
    echo "Server stopped (PID $PID)"
else
    echo "Process not found, cleaning up PID file"
fi

rm -f "$PIDFILE"
