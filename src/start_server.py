#!/usr/bin/env python3
import os
import re
import json
import hashlib
import signal
import atexit
import subprocess
import random
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
from socketserver import ThreadingMixIn
from threading import Lock
from urllib.parse import urlparse, parse_qs

BASE_DIR = os.path.abspath(os.getcwd())
CONFIG_PATH = os.path.join(BASE_DIR, "src", "configurations", "config.json")


def markdown_to_html(markdown_text):
    """Convert basic markdown to HTML"""
    html = []
    lines = markdown_text.split('\n')
    in_code_block = False
    code_lines = []
    in_list = False
    list_items = []
    
    for line in lines:
        # Code blocks
        if line.startswith('```'):
            if in_code_block:
                html.append('<pre><code>' + '\n'.join(code_lines).replace('<', '&lt;').replace('>', '&gt;') + '</code></pre>')
                code_lines = []
                in_code_block = False
            else:
                in_code_block = True
            continue
        
        if in_code_block:
            code_lines.append(line)
            continue
        
        # Headings
        heading_match = re.match(r'^(#{1,6})\s+(.+)$', line)
        if heading_match:
            if in_list:
                html.append('<ul>' + ''.join(f'<li>{item}</li>' for item in list_items) + '</ul>')
                in_list = False
                list_items = []
            level = len(heading_match.group(1))
            text = heading_match.group(2)
            html.append(f'<h{level}>{text}</h{level}>')
            continue
        
        # Horizontal rules
        if re.match(r'^-{3,}$', line) or re.match(r'^\*{3,}$', line):
            if in_list:
                html.append('<ul>' + ''.join(f'<li>{item}</li>' for item in list_items) + '</ul>')
                in_list = False
                list_items = []
            html.append('<hr />')
            continue
        
        # Lists
        list_match = re.match(r'^[-*+]\s+(.+)$', line)
        if list_match:
            text = list_match.group(1)
            # Apply inline formatting
            text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
            text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
            text = re.sub(r'`(.+?)`', r'<code>\1</code>', text)
            list_items.append(text)
            in_list = True
            continue
        
        # Empty lines
        if not line.strip():
            if in_list:
                html.append('<ul>' + ''.join(f'<li>{item}</li>' for item in list_items) + '</ul>')
                in_list = False
                list_items = []
            elif html and not html[-1].startswith('<'):
                html.append('')
            continue
        
        # Regular paragraphs
        if in_list:
            html.append('<ul>' + ''.join(f'<li>{item}</li>' for item in list_items) + '</ul>')
            in_list = False
            list_items = []
        
        # Apply inline formatting
        text = line
        text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
        text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
        text = re.sub(r'`(.+?)`', r'<code>\1</code>', text)
        text = re.sub(r'\[(.+?)\]\((.+?)\)', r'<a href="\2" target="_blank">\1</a>', text)
        html.append(f'<p>{text}</p>')
    
    # Close any remaining list
    if in_list:
        html.append('<ul>' + ''.join(f'<li>{item}</li>' for item in list_items) + '</ul>')
    
    return '\n'.join(html)


def load_config():
    config = {
        "max_sessions": 5,
        "media_root": os.path.join(BASE_DIR, "media", "converted"),
        "title_cleanup_config": os.path.join("src", "configurations", "title_cleanup.json"),
        "themes": {
            "default": "default",
            "available": [
                "default", "volcano", "space", "dinosaur", "beach", "csgo", "pokemon"
            ],
        },
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
MEDIA_DURATION_CACHE = {}

# In-memory channel chat: {channel_id: [message, ...]}
CHAT_MAX_PER_CHANNEL = 2000
CHAT_MESSAGES = {}
CHAT_NEXT_ID = 1
CHAT_LOCK = Lock()
CHAT_STORAGE_DIR = os.path.join(BASE_DIR, "output", "chat_history", "channels")

# Global cookie clicker counter
COOKIE_COUNT = 0
COOKIE_LOCK = Lock()
COOKIE_STORAGE_PATH = os.path.join(BASE_DIR, "output", "cookie_count.json")


def load_cookie_count():
    global COOKIE_COUNT
    try:
        with open(COOKIE_STORAGE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        COOKIE_COUNT = max(0, int(data.get("count", 0)))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        COOKIE_COUNT = 0


def save_cookie_count():
    try:
        os.makedirs(os.path.dirname(COOKIE_STORAGE_PATH), exist_ok=True)
        write_json_atomic(COOKIE_STORAGE_PATH, {"count": COOKIE_COUNT})
    except OSError as e:
        print(f"⚠️ Failed to save cookie count: {e}")


def chat_file_path(channel):
    channel_text = str(channel or "").strip()
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "_", channel_text).strip("._-") or "channel"
    slug = slug[:64]
    digest = hashlib.sha1(channel_text.encode("utf-8")).hexdigest()[:12]
    return os.path.join(CHAT_STORAGE_DIR, f"{slug}__{digest}.json")


def write_json_atomic(path, payload):
    temp_path = f"{path}.tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(temp_path, path)


def persist_channel_chat(channel, messages):
    os.makedirs(CHAT_STORAGE_DIR, exist_ok=True)
    clipped = list(messages[-CHAT_MAX_PER_CHANNEL:])
    write_json_atomic(chat_file_path(channel), {
        "channel": channel,
        "messages": clipped,
    })


def load_chat_history():
    global CHAT_MESSAGES, CHAT_NEXT_ID

    os.makedirs(CHAT_STORAGE_DIR, exist_ok=True)
    loaded = {}
    max_id = 0

    for filename in sorted(os.listdir(CHAT_STORAGE_DIR)):
        if not filename.endswith(".json"):
            continue
        path = os.path.join(CHAT_STORAGE_DIR, filename)
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue

        channel = str(payload.get("channel", "")).strip()
        raw_messages = payload.get("messages", [])
        if not channel or not isinstance(raw_messages, list):
            continue

        cleaned = []
        for raw in raw_messages:
            if not isinstance(raw, dict):
                continue

            try:
                message_id = int(raw.get("id", 0))
            except (TypeError, ValueError):
                continue
            if message_id <= 0:
                continue

            username = re.sub(r"\s+", " ", str(raw.get("username", "") or "Anonymous").strip())[:32] or "Anonymous"
            text = re.sub(r"\s+", " ", str(raw.get("text", "") or "").strip())[:500]
            if not text:
                continue

            try:
                ts = int(raw.get("ts", int(time.time())))
            except (TypeError, ValueError):
                ts = int(time.time())

            cleaned.append({
                "id": message_id,
                "channel": channel,
                "username": username,
                "text": text,
                "ts": ts,
            })
            if message_id > max_id:
                max_id = message_id

        if cleaned:
            cleaned.sort(key=lambda m: m.get("id", 0))
            loaded[channel] = cleaned[-CHAT_MAX_PER_CHANNEL:]

    with CHAT_LOCK:
        CHAT_MESSAGES = loaded
        CHAT_NEXT_ID = max_id + 1 if max_id > 0 else 1


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


def get_media_duration_seconds(path):
    """Return duration in seconds from ffprobe, or None when unavailable."""
    if not path or not os.path.isfile(path):
        return None

    cached = MEDIA_DURATION_CACHE.get(path)
    if isinstance(cached, (int, float)) and cached > 0:
        return float(cached)

    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=6,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    if result.returncode != 0:
        return None

    try:
        duration = float((result.stdout or "").strip())
    except (TypeError, ValueError):
        return None

    if duration <= 0:
        return None

    MEDIA_DURATION_CACHE[path] = duration
    return duration


def get_total_duration_seconds(file_list):
    """Return total duration in seconds for a list of media files, or None."""
    if not file_list:
        return None

    total = 0.0
    for path in file_list:
        duration = get_media_duration_seconds(path)
        if duration is None:
            return None
        total += duration

    return total if total > 0 else None


def build_shuffle_queue_preview(shuffle_files, current_index, preview_count=None):
    """Return compact current+upcoming queue preview for shuffled folders."""
    if not isinstance(shuffle_files, list) or not shuffle_files:
        return []

    valid_files = [p for p in shuffle_files if isinstance(p, str) and os.path.isfile(p)]
    if not valid_files:
        return []

    total = len(valid_files)
    try:
        idx = int(current_index)
    except (TypeError, ValueError):
        idx = 0
    idx = max(0, min(total - 1, idx))

    if preview_count is None:
        window = total
    else:
        window = min(max(1, int(preview_count)), total)
    preview = []
    for offset in range(window):
        list_idx = (idx + offset) % total
        path = valid_files[list_idx]
        preview.append({
            "position": list_idx + 1,
            "total": total,
            "is_current": offset == 0,
            "wrapped": (idx + offset) >= total,
            "source_path": os.path.relpath(path, BASE_DIR),
            "display_title": build_display_title(path),
            "current_file": prettify_media_name(
                os.path.basename(path),
                parent=os.path.basename(os.path.dirname(path)),
                episode_index=get_file_index(path),
            ),
        })
    return preview


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

def start_ffmpeg(file_list, slot, ip, seek_seconds=0, duration_seconds=None, session_meta=None):
    if not file_list:
        print("⚠️ No files provided to stream!")
        return None

    if slot in sessions and "ffmpeg" in sessions[slot]:
        proc = sessions[slot]["ffmpeg"]
        if proc and proc.poll() is None:
            proc.kill()

    cleanup_folder(slot)

    folder = os.path.join(ON_DEMAND_DIR, str(slot))
    playlist_path = os.path.join(folder, "output.m3u8")
    segment_pattern = os.path.join(folder, "seg_%03d.ts")
    seek_seconds = max(0, float(seek_seconds or 0))

    # Keep the full on-demand playlist/segments for the active session so the
    # viewer can seek backward through already-generated content. When the user
    # switches streams, stop_session()/cleanup_folder() clears everything.
    ffmpeg_cmd = ["ffmpeg", "-nostdin"]

    if len(file_list) == 1:
        if seek_seconds > 0:
            ffmpeg_cmd.extend(["-ss", f"{seek_seconds:.3f}"])
        ffmpeg_cmd.extend(["-i", os.path.abspath(file_list[0])])
    else:
        concat_file = os.path.join(folder, "playlist.txt")
        with open(concat_file, "w") as f:
            for path in file_list:
                f.write(f"file '{os.path.abspath(path)}'\n")
        ffmpeg_cmd.extend([
            "-f", "concat", "-safe", "0",
            "-i", concat_file,
        ])
        if seek_seconds > 0:
            ffmpeg_cmd.extend(["-ss", f"{seek_seconds:.3f}"])

    ffmpeg_cmd.extend([
        "-c", "copy",
        "-f", "hls",
        "-hls_time", "2",
        "-hls_list_size", "0",
        "-hls_playlist_type", "event",
        "-hls_flags", "program_date_time",
        "-hls_segment_filename", segment_pattern,
        playlist_path,
    ])

    proc = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    session_record = {
        "ip": ip,
        "ffmpeg": proc,
        "files": list(file_list),
        "current_file": file_list[0] if file_list else None,
        "seek_seconds": seek_seconds,
        "duration_seconds": duration_seconds,
    }
    if isinstance(session_meta, dict):
        session_record.update(session_meta)
    sessions[slot] = session_record

    if ip not in ip_queue:
        ip_queue.append(ip)

    return playlist_path, slot


def read_hls_playlist_state(slot):
    folder = os.path.join(ON_DEMAND_DIR, str(slot))
    playlist_path = os.path.join(folder, "output.m3u8")
    try:
        with open(playlist_path, "r", encoding="utf-8", errors="ignore") as handle:
            content = handle.read()
    except OSError:
        return {
            "buffered_seconds": 0.0,
            "has_endlist": False,
        }

    durations = [float(value) for value in re.findall(r"#EXTINF:([0-9]+(?:\.[0-9]+)?)", content)]
    return {
        "buffered_seconds": sum(durations),
        "has_endlist": "#EXT-X-ENDLIST" in content,
    }

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
            themes_config = CONFIG.get("themes") if isinstance(CONFIG.get("themes"), dict) else {
                "default": "default",
                "available": [],
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "media_root": os.path.relpath(MEDIA_ROOT, BASE_DIR),
                "max_sessions": MAX_SESSIONS,
                "themes": themes_config,
            }).encode())
            return
        if parsed.path == "/api/buffer_status":
            ip = self.client_address[0]
            slot = None
            for s, info in sessions.items():
                if info.get("ip") == ip:
                    slot = s
                    break
            if slot is None:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "buffered_seconds": 0, "total_seconds": 0,
                    "base_offset": 0, "is_complete": True,
                }).encode())
                return
            playlist_state = read_hls_playlist_state(slot)
            buffered_seconds = playlist_state["buffered_seconds"]
            proc = sessions[slot].get("ffmpeg")
            is_complete = (proc is None or proc.poll() is not None) and playlist_state["has_endlist"]
            base_offset = float(sessions[slot].get("seek_seconds") or 0)
            total_seconds = float(sessions[slot].get("duration_seconds") or 0)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "buffered_seconds": buffered_seconds,
                "total_seconds": total_seconds,
                "base_offset": base_offset,
                "is_complete": is_complete,
            }).encode())
            return
        if parsed.path == "/api/patchnotes":
            patchnotes_path = os.path.join(BASE_DIR, "src", "PATCHNOTES.md")
            if os.path.exists(patchnotes_path):
                try:
                    with open(patchnotes_path, "r", encoding="utf-8") as f:
                        markdown_content = f.read()
                    html_content = markdown_to_html(markdown_content)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"html": html_content}).encode())
                except Exception as e:
                    self.send_error(500)
            else:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"html": "<p>No patch notes available</p>"}).encode())
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
        if parsed.path == "/api/cookies":
            with COOKIE_LOCK:
                count = COOKIE_COUNT
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"count": count}).encode())
            return
        if parsed.path == "/api/chat":
            qs = parse_qs(parsed.query)
            channel = str(qs.get("channel", [""])[0]).strip()
            try:
                since_id = int(qs.get("since", ["0"])[0])
            except (TypeError, ValueError):
                since_id = 0

            if not channel:
                self.send_error(400)
                return

            with CHAT_LOCK:
                channel_messages = CHAT_MESSAGES.get(channel, [])
                if since_id > 0:
                    messages = [m for m in channel_messages if m.get("id", 0) > since_id]
                else:
                    messages = channel_messages[-200:]

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"messages": messages}).encode())
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

        if self.path == "/api/cookies/click":
            global COOKIE_COUNT
            with COOKIE_LOCK:
                COOKIE_COUNT += 1
                count = COOKIE_COUNT
            try:
                save_cookie_count()
            except OSError:
                pass
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"count": count}).encode())
            return

        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            self.send_error(400)
            return

        if self.path == "/api/seek_file":
            ip = self.client_address[0]
            slot = None
            for candidate_slot, info in sessions.items():
                if info.get("ip") == ip:
                    slot = candidate_slot
                    break

            if slot is None:
                self.send_error(409)
                return

            session_info = sessions.get(slot, {})
            source_path = body.get("path")
            seek_seconds_raw = body.get("seek_seconds", 0)
            try:
                seek_seconds = max(0, float(seek_seconds_raw))
            except (TypeError, ValueError):
                self.send_error(400)
                return

            files = []
            real = None
            if source_path:
                real = safe_path(source_path)
                if not real or not os.path.isfile(real):
                    self.send_error(400)
                    return
                files = [real]
            else:
                current_file = session_info.get("current_file")
                if isinstance(current_file, str) and os.path.isfile(current_file):
                    files = [current_file]

            if not files:
                self.send_error(400)
                return

            duration_seconds = session_info.get("duration_seconds")
            if duration_seconds is None:
                duration_seconds = get_total_duration_seconds(files) if len(files) > 1 else get_media_duration_seconds(files[0])

            session_meta = {
                "shuffle_files": session_info.get("shuffle_files"),
                "shuffle_index": session_info.get("shuffle_index", 0),
            }
            playlist_path, slot = start_ffmpeg(
                files,
                slot,
                ip,
                seek_seconds=seek_seconds,
                duration_seconds=duration_seconds,
                session_meta=session_meta,
            )
            if not playlist_path:
                self.send_error(500)
                return

            first_file = files[0]
            display_title = build_display_title(first_file)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            queue_preview = []
            if isinstance(session_meta.get("shuffle_files"), list):
                queue_preview = build_shuffle_queue_preview(
                    session_meta.get("shuffle_files"),
                    session_meta.get("shuffle_index", 0),
                )
            self.wfile.write(json.dumps({
                "playlist": f"/on_demand/{slot}/output.m3u8",
                "slot": slot,
                "seek_seconds": seek_seconds,
                "display_title": display_title,
                "source_path": os.path.relpath(first_file, BASE_DIR),
                "duration_seconds": duration_seconds,
                "current_file": prettify_media_name(os.path.basename(first_file), parent=os.path.basename(os.path.dirname(first_file)), episode_index=get_file_index(first_file)),
                "episode_index": int(session_meta.get("shuffle_index", 0)) + 1 if isinstance(session_meta.get("shuffle_files"), list) and session_meta.get("shuffle_files") else 1,
                "episode_total": len(session_meta.get("shuffle_files") or files),
                "queue_preview": queue_preview,
            }).encode())
            return

        if self.path == "/api/next_episode":
            ip = self.client_address[0]
            slot = None
            for candidate_slot, info in sessions.items():
                if info.get("ip") == ip:
                    slot = candidate_slot
                    break

            if slot is None:
                self.send_error(409)
                return

            session_info = sessions.get(slot, {})
            shuffle_files = session_info.get("shuffle_files")
            if not isinstance(shuffle_files, list) or not shuffle_files:
                self.send_error(400)
                return

            valid_files = [p for p in shuffle_files if os.path.isfile(p)]
            if not valid_files:
                self.send_error(404)
                return

            current_idx = int(session_info.get("shuffle_index", 0) or 0)
            next_idx = (current_idx + 1) % len(valid_files)
            next_file = valid_files[next_idx]
            duration_seconds = get_media_duration_seconds(next_file)

            playlist_path, slot = start_ffmpeg(
                [next_file],
                slot,
                ip,
                seek_seconds=0,
                duration_seconds=duration_seconds,
                session_meta={
                    "shuffle_files": valid_files,
                    "shuffle_index": next_idx,
                },
            )
            if not playlist_path:
                self.send_error(500)
                return

            display_title = build_display_title(next_file)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            queue_preview = build_shuffle_queue_preview(valid_files, next_idx)
            self.wfile.write(json.dumps({
                "playlist": f"/on_demand/{slot}/output.m3u8",
                "slot": slot,
                "display_title": display_title,
                "source_path": os.path.relpath(next_file, BASE_DIR),
                "duration_seconds": duration_seconds,
                "current_file": prettify_media_name(os.path.basename(next_file), parent=os.path.basename(os.path.dirname(next_file)), episode_index=get_file_index(next_file)),
                "episode_index": next_idx + 1,
                "episode_total": len(valid_files),
                "wrapped": next_idx == 0 and len(valid_files) > 1,
                "queue_preview": queue_preview,
            }).encode())
            return

        if self.path == "/api/play_queue_episode":
            ip = self.client_address[0]
            slot = None
            for candidate_slot, info in sessions.items():
                if info.get("ip") == ip:
                    slot = candidate_slot
                    break

            if slot is None:
                self.send_error(409)
                return

            session_info = sessions.get(slot, {})
            shuffle_files = session_info.get("shuffle_files")
            if not isinstance(shuffle_files, list) or not shuffle_files:
                self.send_error(400)
                return

            valid_files = [p for p in shuffle_files if os.path.isfile(p)]
            if not valid_files:
                self.send_error(404)
                return

            queue_position_raw = body.get("queue_position")
            try:
                queue_position = int(queue_position_raw)
            except (TypeError, ValueError):
                self.send_error(400)
                return

            if queue_position < 1 or queue_position > len(valid_files):
                self.send_error(400)
                return

            selected_idx = queue_position - 1
            selected_file = valid_files[selected_idx]
            duration_seconds = get_media_duration_seconds(selected_file)

            playlist_path, slot = start_ffmpeg(
                [selected_file],
                slot,
                ip,
                seek_seconds=0,
                duration_seconds=duration_seconds,
                session_meta={
                    "shuffle_files": valid_files,
                    "shuffle_index": selected_idx,
                },
            )
            if not playlist_path:
                self.send_error(500)
                return

            display_title = build_display_title(selected_file)
            queue_preview = build_shuffle_queue_preview(valid_files, selected_idx)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "playlist": f"/on_demand/{slot}/output.m3u8",
                "slot": slot,
                "display_title": display_title,
                "source_path": os.path.relpath(selected_file, BASE_DIR),
                "duration_seconds": duration_seconds,
                "current_file": prettify_media_name(os.path.basename(selected_file), parent=os.path.basename(os.path.dirname(selected_file)), episode_index=get_file_index(selected_file)),
                "episode_index": selected_idx + 1,
                "episode_total": len(valid_files),
                "queue_preview": queue_preview,
            }).encode())
            return

        if self.path == "/api/chat/send":
            channel = str(body.get("channel", "")).strip()
            username = str(body.get("username", "")).strip() or "Anonymous"
            text = str(body.get("text", "")).strip()

            if not channel or not text:
                self.send_error(400)
                return

            username = re.sub(r"\s+", " ", username)[:32]
            text = re.sub(r"\s+", " ", text)[:500]

            global CHAT_NEXT_ID
            with CHAT_LOCK:
                entry = {
                    "id": CHAT_NEXT_ID,
                    "channel": channel,
                    "username": username,
                    "text": text,
                    "ts": int(time.time()),
                }
                CHAT_NEXT_ID += 1
                bucket = CHAT_MESSAGES.setdefault(channel, [])
                bucket.append(entry)
                if len(bucket) > CHAT_MAX_PER_CHANNEL:
                    del bucket[:-CHAT_MAX_PER_CHANNEL]
                bucket_snapshot = list(bucket)

            try:
                persist_channel_chat(channel, bucket_snapshot)
            except OSError as e:
                print(f"⚠️ Failed to persist chat for channel '{channel}': {e}")

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True, "message": entry}).encode())
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
        shuffle_meta = None
        stream_files = files
        if self.path == "/api/play_folder":
            stream_files = [files[0]]
            shuffle_meta = {
                "shuffle_files": files,
                "shuffle_index": 0,
            }

        duration_seconds = get_media_duration_seconds(stream_files[0])
        playlist_path, slot = start_ffmpeg(
            stream_files,
            get_slot_for_ip(ip),
            ip,
            duration_seconds=duration_seconds,
            session_meta=shuffle_meta,
        )

        display_title = build_display_title(files[0])

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        queue_preview = []
        if self.path == "/api/play_folder":
            queue_preview = build_shuffle_queue_preview(files, 0)
        self.wfile.write(json.dumps({
            "playlist": f"/on_demand/{slot}/output.m3u8",
            "slot": slot,
            "display_title": display_title,
            "source_path": os.path.relpath(files[0], BASE_DIR),
            "duration_seconds": duration_seconds,
            "current_file": prettify_media_name(os.path.basename(files[0]), parent=os.path.basename(os.path.dirname(files[0])), episode_index=get_file_index(files[0])),
            "episode_index": 1,
            "episode_total": len(files) if self.path == "/api/play_folder" else 1,
            "queue_preview": queue_preview,
        }).encode())

if __name__ == "__main__":
    load_cookie_count()
    load_chat_history()

    def _shutdown_handler(signum, frame):
        print("\n🛑 Shutting down — saving cookie count...")
        save_cookie_count()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _shutdown_handler)
    signal.signal(signal.SIGINT, _shutdown_handler)
    atexit.register(save_cookie_count)

    os.chdir(BASE_DIR)
    server = ThreadingHTTPServer(("0.0.0.0", 80), Handler)  # binds all interfaces
    print("🚀 Server running on http://0.0.0.0:80 (maxistreams.local)")
    server.serve_forever()
