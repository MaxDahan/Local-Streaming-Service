#!/bin/bash

./start_all_streams.sh

LOGFILE="server.log"
PIDFILE="server.pid"

# Start server detached from terminal
nohup sudo python3 start_server.py > "$LOGFILE" 2>&1 &

# Save PID
echo $! > "$PIDFILE"

echo "Server started in background"
echo "PID: $(cat $PIDFILE)"
echo "Logs: $LOGFILE"
