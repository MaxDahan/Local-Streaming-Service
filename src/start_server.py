#!/usr/bin/env python3
import os
import json
import subprocess
import random
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# -------------------- Configuration --------------------
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
WEB_ROOT = os.path.join(BASE_DIR, "src")  # Serve index.html and images from here
MEDIA_ROOT = os.path.join(BASE_DIR, "media", "converted")
ON_DEMAND_DIR = os.path.join(BASE_DIR, "on_demand")
CHANNELS_DIR = os.path.join(BASE_DIR, "channels")

# Load configuration
CONFIG_FILE = os.path.join(BASE_DIR, "src/configurations/config.json")
with open(CONFIG_FILE) as f:
    config = json.load(f)
MAX_SESSIONS = config.get("max_sessions", 5)  # default to 5 if not found

# Ensure on_demand session folders exist
os.makedirs(ON_DEMAND_DIR, exist_ok=True)
for i in range(1, MAX_SESSIONS + 1):
    os.makedirs(os.path.join(ON_DEMAND_DIR, str(i)), exist_ok=True)

# -------------------- Session Management --------------------
# { slot_number: {"ip": str, "ffmpeg": Popen, "last_heartbeat": float} }
sessions = {}
ip_queue = []  # FIFO queue of IPs

HEARTBEAT_TIMEOUT = 120  # seconds without heartbeat to stop session

# -------------------- Helpers --------------------
def safe_path(path):
    """Resolve a path relative to BASE_DIR and ensure it stays inside MEDIA_ROOT."""
    real = os.path.realpath(os.path.join(BASE_DIR, path))
    if not real.startswith(MEDIA_ROOT):
        return None
    return real

def cleanup_folder(slot):
    folder = os.path.join(ON_DEMAND_DIR, str(slot))
    for f in os.listdir(folder):
        try:
            os.remove(os.path.join(folder, f))
        except Exception as e:
            print("⚠️ Failed to remove:", f, e)

def stop_session(slot):
    if slot in sessions:
        proc = sessions[slot].get("ffmpeg")
        if proc:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
        cleanup_folder(slot)
        sessions[slot]["last_heartbeat"] = 0  # mark as stopped
        print(f"🛑 Session {slot} stopped.")
        del sessions[slot]

def get_slot_for_ip(ip):
    """Assign a slot number for a given IP (FIFO if full)."""
    global ip_queue, sessions

    # Already has a slot?
    for slot, info in sessions.items():
        if info.get("ip") == ip:
            return slot

    # Find first empty slot
    for slot in range(1, MAX_SESSIONS + 1):
        if slot not in sessions:
            return slot

    # All slots taken: evict oldest IP
    old_ip = ip_queue.pop(0)
    old_slot = None
    for slot, info in sessions.items():
        if info.get("ip") == old_ip:
            old_slot = slot
            break
    if old_slot:
        stop_session(old_slot)
    return old_slot

def start_ffmpeg(file_list, slot, ip):
    if not file_list:
        print("⚠️ No files provided to stream!")
        return None

    folder = os.path.join(ON_DEMAND_DIR, str(slot))
    os.makedirs(folder, exist_ok=True)
    cleanup_folder(slot)

    concat_file = os.path.join(folder, "playlist.txt")
    with open(concat_file, "w") as f:
        for path in file_list:
            f.write(f"file '{os.path.abspath(path)}'\n")

    playlist_path = os.path.join(folder, "output.m3u8")
    segment_pattern = os.path.join(folder, "seg_%03d.ts")

    proc = subprocess.Popen([
        "ffmpeg", "-nostdin", "-re",
        "-f", "concat", "-safe", "0",
        "-i", concat_file,
        "-c", "copy",
        "-f", "hls",
        "-hls_time", "6",
        "-hls_list_size", "30",
        "-hls_flags", "program_date_time",
        "-hls_segment_filename", segment_pattern,
        playlist_path
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    sessions[slot] = {"ip": ip, "ffmpeg": proc, "last_heartbeat": time.time()}
    if ip not in ip_queue:
        ip_queue.append(ip)

    return playlist_path, slot

def cleanup_idle_sessions():
    """Stop sessions that haven't sent a heartbeat recently."""
    now = time.time()
    for slot in list(sessions.keys()):
        last = sessions[slot].get("last_heartbeat", 0)
        if now - last > HEARTBEAT_TIMEOUT:
            print(f"⏱️ Session {slot} timed out due to inactivity.")
            stop_session(slot)

# -------------------- HTTP Handler --------------------
class Handler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        """Serve static files from src/, channels/, or on_demand/"""
        if path.startswith("/channels/"):
            return os.path.join(CHANNELS_DIR, path[len("/channels/"):])
        elif path.startswith("/on_demand/"):
            return os.path.join(ON_DEMAND_DIR, path[len("/on_demand/"):])
        elif path == "/channels.json":
            return os.path.join(BASE_DIR, "channels.json")
        return os.path.join(WEB_ROOT, path.lstrip("/"))

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/list":
            qs = parse_qs(parsed.query)
            rel_path = qs.get("path", [""])[0]
            full = safe_path(rel_path)
            if not full or not os.path.isdir(full):
                self.send_error(400)
                return

            items = []
            for name in sorted(os.listdir(full)):
                if name.startswith("."): continue
                p = os.path.join(full, name)
                items.append({
                    "name": name,
                    "path": os.path.relpath(p, BASE_DIR),
                    "type": "folder" if os.path.isdir(p) else "file"
                })

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(items).encode())
            return

        return super().do_GET()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            self.send_error(400)
            return

        ip = self.client_address[0]

        # --- STOP SESSION ---
        if self.path == "/api/stop_session":
            user_slot = body.get("slot")
            if user_slot and user_slot in sessions:
                stop_session(user_slot)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "stopped"}).encode())
            return

        # --- HEARTBEAT ---
        if self.path == "/api/heartbeat":
            slot = body.get("slot")
            if slot and slot in sessions:
                sessions[slot]["last_heartbeat"] = time.time()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok"}).encode())
            return

        # --- PLAY FILE / PLAY FOLDER ---
        path = body.get("path")
        if not path and self.path != "/api/play_folder":
            self.send_error(400)
            return

        real = safe_path(path) if path else None

        files = []
        if self.path == "/api/play_file" and real and os.path.isfile(real):
            files = [real]
        elif self.path == "/api/play_folder":
            folder_path = os.path.join(BASE_DIR, path)
            for root, _, names in os.walk(folder_path):
                for n in names:
                    if n.lower().endswith((".mp4", ".mkv")):
                        files.append(os.path.join(root, n))
            random.shuffle(files)
        else:
            self.send_error(404)
            return

        if not files:
            self.send_error(404)
            return

        playlist_path, slot = start_ffmpeg(files, get_slot_for_ip(ip), ip)

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({
            "playlist": f"/on_demand/{slot}/output.m3u8",
            "slot": slot
        }).encode())

# -------------------- Run server --------------------
if __name__ == "__main__":
    os.chdir(WEB_ROOT)
    server = HTTPServer(("0.0.0.0", 80), Handler)
    print("🚀 MAXISTREAMS server running on http://0.0.0.0:80")

    try:
        while True:
            server.handle_request()
            cleanup_idle_sessions()
    except KeyboardInterrupt:
        print("\n🛑 Server stopped manually.")
        for slot in list(sessions.keys()):
            stop_session(slot)
