#!/usr/bin/env python3
import os
import signal
import sys
import subprocess

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PID_FILE = os.path.join(BASE_DIR, "output", "server.pid")
ON_DEMAND_DIR = os.path.join(BASE_DIR, "on_demand")

# Load configuration
CONFIG_FILE = os.path.join(BASE_DIR, "src/configurations/config.json")
with open(CONFIG_FILE) as f:
    config = json.load(f)
MAX_SESSIONS = config.get("max_sessions", 5) # default to 5 if not found

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

# ------------------ Clean up on_demand sessions ------------------
for slot in range(1, MAX_SESSIONS + 1):
    folder = os.path.join(ON_DEMAND_DIR, str(slot))
    if not os.path.exists(folder):
        continue

    # Kill any ffmpeg processes for this slot
    for proc in subprocess.run(["pgrep", "-f", folder], capture_output=True, text=True).stdout.splitlines():
        try:
            os.kill(int(proc), signal.SIGKILL)
            print(f"🛑 Killed FFmpeg process {proc} in slot {slot}")
        except Exception:
            pass

    # Remove temporary HLS files
    for f in os.listdir(folder):
        path = os.path.join(folder, f)
        try:
            os.remove(path)
        except Exception:
            pass
