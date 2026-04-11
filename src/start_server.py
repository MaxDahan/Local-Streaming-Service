#!/usr/bin/env python3
import os
import re
import json
import subprocess
import random
from http.server import HTTPServer, SimpleHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs

BASE_DIR = os.path.abspath(os.getcwd())
CONFIG_PATH = os.path.join(BASE_DIR, "src", "configurations", "config.json")


def load_config():
    config = {
        "max_sessions": 5,
        "media_root": os.path.join(BASE_DIR, "media", "converted"),
        "title_cleanup_config": os.path.join("src", "configurations", "title_cleanup.json"),
    }
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            config.update(loaded)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return config


def resolve_config_path(path_value, fallback):
    candidate = path_value or fallback
    return candidate if os.path.isabs(candidate) else os.path.join(BASE_DIR, candidate)


def load_title_cleanup_rules(path):
    rules = {
        "strip_bracketed": True,
        "noise_phrases": [
            "1080p", "720p", "480p", "2160p",
            "bluray", "blu ray", "brrip", "br rip",
            "webrip", "web rip", "webdl", "web dl",
            "hdrip", "hd rip", "dvdrip", "dvd rip", "remux",
            "x264", "x265", "h264", "h265", "hevc",
            "10bit", "8bit", "aac", "ac3", "dts",
            "rarbg", "yts", "etrg", "tgx", "proper", "repack", "internal",
        ],
    }
    try:
        with open(path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            if isinstance(loaded.get("strip_bracketed"), bool):
                rules["strip_bracketed"] = loaded["strip_bracketed"]
            noise_phrases = loaded.get("noise_phrases")
            if isinstance(noise_phrases, list):
                cleaned_phrases = [str(item).strip() for item in noise_phrases if str(item).strip()]
                if cleaned_phrases:
                    rules["noise_phrases"] = cleaned_phrases
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return rules


CONFIG = load_config()
MEDIA_ROOT = os.path.realpath(CONFIG.get("media_root", os.path.join(BASE_DIR, "media", "converted")))
ON_DEMAND_DIR = os.path.join(BASE_DIR, "on_demand")
try:
    MAX_SESSIONS = int(CONFIG.get("max_sessions", 5))
except (TypeError, ValueError):
    MAX_SESSIONS = 5

TITLE_RULES_PATH = resolve_config_path(
    CONFIG.get("title_cleanup_config"),
    os.path.join("src", "configurations", "title_cleanup.json"),
)
TITLE_RULES = load_title_cleanup_rules(TITLE_RULES_PATH)

# Ensure session folders exist
os.makedirs(ON_DEMAND_DIR, exist_ok=True)
for i in range(1, MAX_SESSIONS + 1):
    os.makedirs(os.path.join(ON_DEMAND_DIR, str(i)), exist_ok=True)

# Session management: { slot_number: {"ip": str, "ffmpeg": Popen} }
sessions = {}
ip_queue = []  # FIFO queue of IPs


def build_phrase_pattern(phrase):
    parts = [re.escape(part) for part in re.split(r"[\s._-]+", phrase.strip()) if part]
    if not parts:
        return None
    return re.compile(r"\b" + r"[\s._-]*".join(parts) + r"\b", re.IGNORECASE)


NOISE_PHRASE_PATTERNS = []
for phrase in TITLE_RULES.get("noise_phrases", []):
    pattern = build_phrase_pattern(phrase)
    if pattern is not None:
        NOISE_PHRASE_PATTERNS.append(pattern)


EPISODE_MARKER_RE = re.compile(
    r"\b(?:S(?P<season>\d{1,2})E(?P<episodes>\d{1,2}(?:\s*(?:-|–|E)\s*E?\d{1,2})*)|(?P<xseason>\d{1,2})x(?P<xepisodes>\d{1,2}(?:\s*[-–]\s*\d{1,2})*))\b",
    re.IGNORECASE,
)

# Matches "episode 3", "season 2 episode 3" spelled out in full
VERBOSE_EPISODE_RE = re.compile(
    r"(?:season\s+\d{1,2}\s+)?episode\s+(\d{1,3})",
    re.IGNORECASE,
)


def _show_words(s):
    """Tokenize a string into lowercase words, splitting on non-alnum and CamelCase."""
    s = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', s)
    return re.findall(r'[a-z0-9]+', s.lower())


def _strip_show_prefix(normalized, parent):
    """Strip leading show-name prefix from a normalized filename (fuzzy, word-based)."""
    p_words = _show_words(parent)
    n_words = _show_words(normalized)
    if not p_words or n_words[:len(p_words)] != p_words:
        return normalized
    sep = r"[\s._-]*"
    word_pat = sep.join(re.escape(w) for w in p_words)
    return re.sub(r"(?i)^" + word_pat + r"[\s._-]*[-–:]?[\s._-]*", "", normalized).strip()


def get_file_index(path):
    """Return the 1-based sorted position of a file within its parent directory."""
    parent = os.path.dirname(path)
    name = os.path.basename(path)
    try:
        siblings = sorted(
            f for f in os.listdir(parent)
            if not f.startswith('.') and os.path.isfile(os.path.join(parent, f))
        )
        return siblings.index(name) + 1
    except (ValueError, OSError):
        return None


def safe_path(path):
    real = os.path.realpath(os.path.join(BASE_DIR, path))
    if not real.startswith(MEDIA_ROOT):
        return None
    return real


def clean_title_fragment(text):
    cleaned = text or ""
    if TITLE_RULES.get("strip_bracketed", True):
        cleaned = re.sub(r"[\[\(\{].*?[\]\)\}]", " ", cleaned)
    for pattern in NOISE_PHRASE_PATTERNS:
        cleaned = pattern.sub(" ", cleaned)
    cleaned = cleaned.replace("–", "-")
    cleaned = re.sub(r"\s*[-:]\s*", " - ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -_.")
    return cleaned


def format_episode_label(match):
    raw_episodes = match.group("episodes") or match.group("xepisodes") or ""
    episode_numbers = re.findall(r"\d{1,2}", raw_episodes)
    if not episode_numbers:
        return match.group(0).upper()
    return "-".join(f"E{number.zfill(2)}" for number in episode_numbers)


def prettify_media_name(name, parent=None, episode_index=None):
    stem = os.path.splitext(name)[0]
    normalized = clean_title_fragment(re.sub(r"[._]+", " ", stem))

    if parent:
        normalized = _strip_show_prefix(normalized, parent)

    match = EPISODE_MARKER_RE.search(normalized)
    if match:
        episode_label = format_episode_label(match)
        title_tail = clean_title_fragment(normalized[match.end():])
        return f"{episode_label} - {title_tail}" if title_tail else episode_label

    v_match = VERBOSE_EPISODE_RE.search(normalized)
    if v_match:
        ep_num = int(v_match.group(1))
        tail = clean_title_fragment(normalized[v_match.end():])
        return f"E{ep_num:02d}" + (f" - {tail}" if tail else "")

    if episode_index is not None:
        return f"E{episode_index:02d} - {normalized}" if normalized else f"E{episode_index:02d}"

    return normalized


def build_display_title(path, root=MEDIA_ROOT):
    rel_path = os.path.relpath(path, root)
    parts = []
    current = root
    prev_part = None

    for part in rel_path.split(os.sep):
        current = os.path.join(current, part)
        if os.path.isdir(current):
            parts.append(part)
            prev_part = part
        else:
            idx = get_file_index(current)
            parts.append(prettify_media_name(part, parent=prev_part, episode_index=idx))

    return " / ".join(part for part in parts if part)


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

    # Keep the full on-demand playlist/segments for the active session so the
    # viewer can seek backward through already-generated content. When the user
    # switches streams, stop_session()/cleanup_folder() clears everything.
    proc = subprocess.Popen([
        "ffmpeg", "-nostdin", "-re",
        "-f", "concat", "-safe", "0",
        "-i", concat_file,
        "-c", "copy",
        "-f", "hls",
        "-hls_time", "2",
        "-hls_list_size", "0",
        "-hls_playlist_type", "event",
        "-hls_flags", "program_date_time+append_list",
        "-hls_segment_filename", segment_pattern,
        playlist_path
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    sessions[slot] = {"ip": ip, "ffmpeg": proc}

    if ip not in ip_queue:
        ip_queue.append(ip)

    return playlist_path, slot

class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    """HTTP server with threading to handle multiple requests concurrently"""
    pass

class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            # Serve index.html from src/
            index_path = os.path.join(BASE_DIR, "src", "index.html")
            if os.path.exists(index_path):
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                with open(index_path, "rb") as f:
                    self.wfile.write(f.read())
                return
            else:
                self.send_error(404)
                return
        if parsed.path == "/api/config":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "media_root": os.path.relpath(MEDIA_ROOT, BASE_DIR),
                "max_sessions": MAX_SESSIONS
            }).encode())
            return
        if parsed.path == "/api/list":
            qs = parse_qs(parsed.query)
            rel_path = qs.get("path", [""])[0]
            full = safe_path(rel_path)
            if not full or not os.path.isdir(full):
                self.send_error(400)
                return

            items = []
            file_count = 0
            for name in sorted(os.listdir(full)):
                if name.startswith("."):
                    continue
                p = os.path.join(full, name)
                item_type = "folder" if os.path.isdir(p) else "file"
                if item_type == "file":
                    file_count += 1
                items.append({
                    "name": name,
                    "display_name": name if item_type == "folder" else prettify_media_name(name, parent=os.path.basename(full)),
                    "display_title": build_display_title(p),
                    "path": os.path.relpath(p, BASE_DIR),
                    "type": item_type,
                })

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(items).encode())
            return

        return super().do_GET()

    def do_POST(self):
        if self.path == "/api/stop_session":
            ip = self.client_address[0]
            for slot, info in list(sessions.items()):
                if info.get("ip") == ip:
                    stop_session(slot)
                    break
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "stopped"}).encode())
            return

        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            self.send_error(400)
            return

        path = body.get("path")
        real = safe_path(path)

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

        display_title = build_display_title(files[0])

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({
            "playlist": f"/on_demand/{slot}/output.m3u8",
            "slot": slot,
            "display_title": display_title,
            "current_file": prettify_media_name(os.path.basename(files[0]), parent=os.path.basename(os.path.dirname(files[0])), episode_index=get_file_index(files[0]))
        }).encode())

if __name__ == "__main__":
    os.chdir(BASE_DIR)
    server = ThreadingHTTPServer(("0.0.0.0", 80), Handler)  # binds all interfaces
    print("🚀 Server running on http://0.0.0.0:80 (maxistreams.local)")
    server.serve_forever()
