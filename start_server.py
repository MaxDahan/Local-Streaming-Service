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
PLAYLIST = os.path.join(ON_DEMAND_DIR, "output.m3u8")
SEGMENT_PATTERN = os.path.join(ON_DEMAND_DIR, "seg_%03d.ts")

os.makedirs(ON_DEMAND_DIR, exist_ok=True)
ffmpeg_process = None

def safe_path(path):
    """Prevent path traversal outside MEDIA_ROOT"""
    real = os.path.realpath(os.path.join(BASE_DIR, path))
    if not real.startswith(MEDIA_ROOT):
        return None
    return real

def cleanup_hls():
    """Remove old .ts and .m3u8 files"""
    for f in os.listdir(ON_DEMAND_DIR):
        if f.endswith(".ts") or f.endswith(".m3u8") or f.endswith(".txt"):
            try:
                os.remove(os.path.join(ON_DEMAND_DIR, f))
            except Exception as e:
                print("⚠️ Failed to remove:", f, e)

def start_ffmpeg(file_list):
    global ffmpeg_process

    if not file_list:
        print("⚠️ No files provided to stream!")
        return

    cleanup_hls()

    concat_file = os.path.join(ON_DEMAND_DIR, "playlist.txt")
    with open(concat_file, "w") as f:
        for path in file_list:
            # FFmpeg needs absolute paths
            f.write(f"file '{os.path.abspath(path)}'\n")

    # Kill previous FFmpeg if still running
    if ffmpeg_process and ffmpeg_process.poll() is None:
        ffmpeg_process.kill()

    # Run FFmpeg to generate HLS
    ffmpeg_process = subprocess.Popen([
        "ffmpeg", "-nostdin", "-re",
        "-f", "concat", "-safe", "0",
        "-i", concat_file,
        "-c", "copy",
        "-f", "hls",
        "-hls_time", "6",
        "-hls_list_size", "30",
        "-hls_flags", "program_date_time",
        "-hls_segment_filename", SEGMENT_PATTERN,
        PLAYLIST
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    print("▶️ Started FFmpeg for on-demand streaming")

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
                if name.startswith("."):
                    continue
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
        body = json.loads(self.rfile.read(length))
        path = body.get("path")

        real = safe_path(path)
        if not real:
            self.send_error(400)
            return

        files = []

        if self.path == "/api/play_file":
            if os.path.isfile(real):
                files = [real]

        elif self.path == "/api/play_folder":
            # Recursively collect all .mp4 or .mkv files
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

        start_ffmpeg(files)

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({
            "playlist": "/on_demand/output.m3u8"
        }).encode())

if __name__ == "__main__":
    os.chdir(BASE_DIR)
    server = HTTPServer(("0.0.0.0", 8000), Handler)
    print("🚀 Server running on http://0.0.0.0:8000")
    server.serve_forever()
