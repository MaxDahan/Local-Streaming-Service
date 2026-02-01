#!/bin/bash

./src/start_all_streams.sh

LOGFILE="output/server.log"
PIDFILE="output/server.pid"

# Start server detached from terminal
nohup sudo python3 src/start_server.py > "$LOGFILE" 2>&1 &

# Save PID
echo $! > "$PIDFILE"

echo "Server started in background"
echo "PID: $(cat $PIDFILE)"
echo "Logs: $LOGFILE"
