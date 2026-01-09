#!/usr/bin/env python3
import os
import json
import subprocess
import random
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

BASE_DIR = os.path.abspath(os.getcwd())
MEDIA_ROOT = os.path.join(BASE_DIR, "media", "converted")
ON_DEMAND_DIR = os.path.join(BASE_DIR, "on_demand")
MAX_SESSIONS = 5

# Ensure session folders exist
os.makedirs(ON_DEMAND_DIR, exist_ok=True)
for i in range(1, MAX_SESSIONS + 1):
    os.makedirs(os.path.join(ON_DEMAND_DIR, str(i)), exist_ok=True)

# Session management: { slot_number: {"ip": str, "ffmpeg": Popen} }
sessions = {}
ip_queue = []  # FIFO queue of IPs

def safe_path(path):
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
    """Kill FFmpeg and clean folder"""
    if slot in sessions:
        proc = sessions[slot].get("ffmpeg")
        if proc and proc.poll() is None:
            proc.kill()
        cleanup_folder(slot)
        del sessions[slot]

def get_slot_for_ip(ip):
    """Assign a slot number for a given IP (FIFO if full)"""
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

    if slot in sessions and "ffmpeg" in sessions[slot]:
        proc = sessions[slot]["ffmpeg"]
        if proc and proc.poll() is None:
            proc.kill()

    cleanup_folder(slot)

    folder = os.path.join(ON_DEMAND_DIR, str(slot))
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

    sessions[slot] = {"ip": ip, "ffmpeg": proc}

    if ip not in ip_queue:
        ip_queue.append(ip)

    return playlist_path, slot

class Handler(SimpleHTTPRequestHandler):
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

        path = body.get("path")
        real = safe_path(path)

        if self.path == "/api/stop_session":
            ip = self.client_address[0]
            for slot, info in sessions.items():
                if info.get("ip") == ip:
                    stop_session(slot)
                    break
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "stopped"}).encode())
            return

        if not real:
            self.send_error(400)
            return

        files = []
        if self.path == "/api/play_file" and os.path.isfile(real):
            files = [real]
        elif self.path == "/api/play_folder":
            for root, _, names in os.walk(real):
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

        ip = self.client_address[0]
        playlist_path, slot = start_ffmpeg(files, get_slot_for_ip(ip), ip)

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({
            "playlist": f"/on_demand/{slot}/output.m3u8",
            "slot": slot
        }).encode())

if __name__ == "__main__":
    os.chdir(BASE_DIR)
    server = HTTPServer(("0.0.0.0", 80), Handler)  # binds all interfaces
    print("🚀 Server running on http://0.0.0.0:80 (maxistreams.local)")
    server.serve_forever()
