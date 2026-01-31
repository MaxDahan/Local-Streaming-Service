#!/bin/bash

# Find the PID of the python3 http.server running on port 80
PID=$(sudo lsof -t -i :80)

if [ -z "$PID" ]; then
  echo "No http.server process running on port 80."
  exit 0
fi

echo "Stopping http.server process with PID: $PID"
sudo kill $PID

# Wait 3 seconds and force kill if still running
sleep 3
if sudo lsof -i :80 > /dev/null; then
  echo "Process still running, force killing..."
  sudo kill -9 $PID
fi

echo "http.server stopped."

