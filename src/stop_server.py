#!/usr/bin/env python3
import os
import signal
import sys

PID_FILE = "server.pid"

if not os.path.exists(PID_FILE):
    print("❌ server.pid not found. Server may not be running.")
    sys.exit(1)

with open(PID_FILE) as f:
    pid = int(f.read().strip())

try:
    os.kill(pid, signal.SIGTERM)
    print(f"🛑 Server stopped (PID {pid})")
except ProcessLookupError:
    print("⚠️ Process not found, removing stale PID file")

os.remove(PID_FILE)
