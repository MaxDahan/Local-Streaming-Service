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
import secrets
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from socketserver import ThreadingMixIn
from threading import Lock
from urllib.parse import urlparse, parse_qs

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
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

# Lightweight presence map for homepage "current users".
PRESENCE_LOCK = Lock()
PRESENCE_TTL_SECONDS = 40
PRESENCE_MAX_ENTRIES = 5000
PRESENCE_CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")
PRESENCE_MAP = {}

# Event-driven viewer counts with TTL fallback (handles dead connections)
VIEWER_LOCK = Lock()
VIEWER_TTL_SECONDS = 90  # drop viewer if no heartbeat within this window
CLIENT_CHANNEL = {}  # {client_id: {"channel_id": str, "ts": int}}
VIEWER_CHANNEL_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

# Global cookie clicker counter
COOKIE_COUNT = 0
COOKIE_LOCK = Lock()
COOKIE_STORAGE_PATH = os.path.join(BASE_DIR, "output", "cookie_count.json")
# Global blunt clicker counter
BLUNT_COUNT = 0
BLUNT_LOCK = Lock()
BLUNT_STORAGE_PATH = os.path.join(BASE_DIR, "output", "blunt_count.json")
FOLDER_RESUME_LOCK = Lock()
FOLDER_RESUME_PATH = os.path.join(BASE_DIR, "output", "folder_resume.json")
FOLDER_RESUME_MAP = {}
# Suggestions board
SUGGESTIONS_LOCK = Lock()
SUGGESTIONS_PATH = os.path.join(BASE_DIR, "output", "suggestions.json")
SUGGESTIONS_LIST = []  # list of dicts: {id, username, text, ts, resolved, resolved_by, resolved_ts}
SUGGESTIONS_NEXT_ID = 1
SUGGESTIONS_MAX = 500
SUGGESTION_MAX_LENGTH = 500
# Favorites
FAVORITES_LOCK = Lock()
FAVORITES_PATH = os.path.join(BASE_DIR, "output", "favorites.json")
FAVORITES_MAP = {}  # dict: {identity: [path, ...]}
AUTH_LOCK = Lock()
USERS_STORAGE_PATH = os.path.join(BASE_DIR, "src", "configurations", "users.json")
SNAKE_SCORES_PATH = os.path.join(BASE_DIR, "output", "snake_scores.json")
AUTH_DB = {"users": {}, "sessions": {}}
RENAME_COOLDOWN_SECONDS = 24 * 60 * 60
AUTH_SESSION_TTL_SECONDS = 30 * 24 * 60 * 60
AUTH_MAX_SESSIONS_PER_USER = 6
THEME_NAME_RE = re.compile(r"^[a-zA-Z0-9._-]{1,64}$")
THEME_VAR_KEY_RE = re.compile(r"^--[a-zA-Z0-9_-]{1,64}$")
THEME_MAX_VARS = 256
THEME_MAX_VALUE_LENGTH = 512
ADMIN_HEALTH_SAMPLE_SECONDS = 2.5
ADMIN_HEALTH_LOCK = Lock()
ADMIN_HEALTH_CACHE = {
    "timestamp": 0.0,
    "payload": {},
}
CPU_SAMPLE_LOCK = Lock()
CPU_SAMPLE_PREV = None


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


def get_cookie_leaderboard(limit=5):
    entries = []
    with AUTH_LOCK:
        users = AUTH_DB.get("users", {})
        for info in users.values():
            if not isinstance(info, dict):
                continue
            username = str(info.get("username") or "").strip()
            if not username:
                continue
            try:
                clicks = max(0, int(info.get("cookie_clicks", 0) or 0))
            except (TypeError, ValueError):
                clicks = 0
            if clicks <= 0:
                continue
            entries.append({"username": username, "clicks": clicks})

    entries.sort(key=lambda item: (-item["clicks"], item["username"].lower()))
    return entries[:max(1, int(limit or 5))]


def load_blunt_count():
    global BLUNT_COUNT
    try:
        with open(BLUNT_STORAGE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        BLUNT_COUNT = max(0, int(data.get("count", 0)))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        BLUNT_COUNT = 0


def save_blunt_count():
    try:
        os.makedirs(os.path.dirname(BLUNT_STORAGE_PATH), exist_ok=True)
        write_json_atomic(BLUNT_STORAGE_PATH, {"count": BLUNT_COUNT})
    except OSError as e:
        print(f"⚠️ Failed to save blunt count: {e}")


def load_suggestions():
    global SUGGESTIONS_LIST, SUGGESTIONS_NEXT_ID
    try:
        with open(SUGGESTIONS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        items = data.get("suggestions", [])
        cleaned = []
        max_id = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                sid = int(item.get("id", 0))
            except (TypeError, ValueError):
                sid = 0
            text = str(item.get("text", "")).strip()
            username = str(item.get("username", "")).strip() or "Anonymous"
            if not text:
                continue
            entry = {
                "id": sid,
                "username": username,
                "text": text,
                "ts": int(item.get("ts", 0) or 0),
                "resolved": bool(item.get("resolved", False)),
                "resolved_by": str(item.get("resolved_by", "") or ""),
                "resolved_ts": int(item.get("resolved_ts", 0) or 0),
            }
            cleaned.append(entry)
            if sid > max_id:
                max_id = sid
        SUGGESTIONS_LIST = cleaned
        SUGGESTIONS_NEXT_ID = max_id + 1
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        SUGGESTIONS_LIST = []
        SUGGESTIONS_NEXT_ID = 1


def save_suggestions():
    try:
        os.makedirs(os.path.dirname(SUGGESTIONS_PATH), exist_ok=True)
        write_json_atomic(SUGGESTIONS_PATH, {"suggestions": SUGGESTIONS_LIST})
    except OSError as e:
        print(f"⚠️ Failed to save suggestions: {e}")


def load_favorites():
    global FAVORITES_MAP
    try:
        with open(FAVORITES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            cleaned = {}
            for k, v in data.items():
                if isinstance(k, str) and isinstance(v, list):
                    cleaned[k] = [str(p) for p in v if isinstance(p, str)]
            FAVORITES_MAP = cleaned
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        FAVORITES_MAP = {}


def save_favorites():
    try:
        os.makedirs(os.path.dirname(FAVORITES_PATH), exist_ok=True)
        with FAVORITES_LOCK:
            snapshot = {k: list(v) for k, v in FAVORITES_MAP.items()}
        write_json_atomic(FAVORITES_PATH, snapshot)
    except OSError as e:
        print(f"⚠️ Failed to save favorites: {e}")


def get_blunt_leaderboard(limit=5):
    entries = []
    with AUTH_LOCK:
        users = AUTH_DB.get("users", {})
        for info in users.values():
            if not isinstance(info, dict):
                continue
            username = str(info.get("username") or "").strip()
            if not username:
                continue
            try:
                hits = max(0, int(info.get("blunt_hits", 0) or 0))
            except (TypeError, ValueError):
                hits = 0
            if hits <= 0:
                continue
            entries.append({"username": username, "hits": hits})

    entries.sort(key=lambda item: (-item["hits"], item["username"].lower()))
    return entries[:max(1, int(limit or 5))]


def load_snake_scores():
    try:
        with open(SNAKE_SCORES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        scores = data.get("scores", {})
        if not isinstance(scores, dict):
            return
        with AUTH_LOCK:
            users = AUTH_DB.get("users", {})
            for user_key, entry in scores.items():
                if not isinstance(entry, dict) or user_key not in users:
                    continue
                try:
                    hs = max(0, int(entry.get("highscore", 0) or 0))
                except (TypeError, ValueError):
                    hs = 0
                try:
                    wins = max(0, int(entry.get("wins", 0) or 0))
                except (TypeError, ValueError):
                    wins = 0
                users[user_key]["snake_highscore"] = max(hs, users[user_key].get("snake_highscore", 0))
                users[user_key]["snake_wins"] = max(wins, users[user_key].get("snake_wins", 0))
    except (OSError, json.JSONDecodeError):
        pass


def save_snake_scores():
    try:
        scores = {}
        with AUTH_LOCK:
            users = AUTH_DB.get("users", {})
            for user_key, info in users.items():
                if not isinstance(info, dict):
                    continue
                try:
                    hs = max(0, int(info.get("snake_highscore", 0) or 0))
                except (TypeError, ValueError):
                    hs = 0
                try:
                    wins = max(0, int(info.get("snake_wins", 0) or 0))
                except (TypeError, ValueError):
                    wins = 0
                if hs > 0 or wins > 0:
                    scores[user_key] = {"highscore": hs, "wins": wins}
        os.makedirs(os.path.dirname(SNAKE_SCORES_PATH), exist_ok=True)
        tmp = SNAKE_SCORES_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps({"scores": scores}, ensure_ascii=False, indent=2))
        os.replace(tmp, SNAKE_SCORES_PATH)
    except OSError as e:
        print(f"Warning: Failed to save snake scores: {e}")


def get_snake_leaderboard(limit=5):
    entries = []
    with AUTH_LOCK:
        users = AUTH_DB.get("users", {})
        for info in users.values():
            if not isinstance(info, dict):
                continue
            username = str(info.get("username") or "").strip()
            if not username:
                continue
            try:
                highscore = max(0, int(info.get("snake_highscore", 0) or 0))
            except (TypeError, ValueError):
                highscore = 0
            if highscore <= 0:
                continue
            try:
                wins = max(0, int(info.get("snake_wins", 0) or 0))
            except (TypeError, ValueError):
                wins = 0
            entries.append({"username": username, "highscore": highscore, "wins": wins})

    entries.sort(key=lambda item: (-item["highscore"], item["username"].lower()))
    return entries[:max(1, int(limit or 5))]


def normalize_folder_key(path):
    if not path:
        return ""
    real = os.path.realpath(path)
    if real.startswith(BASE_DIR):
        return os.path.relpath(real, BASE_DIR)
    return real


def normalize_resume_identity(identity):
    raw = str(identity or "").strip().lower()
    return raw if raw else "guest"


def make_resume_map_key(folder_key, identity):
    return f"{normalize_resume_identity(identity)}::{folder_key}"


def load_folder_resume_map():
    global FOLDER_RESUME_MAP
    try:
        with open(FOLDER_RESUME_PATH, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        payload = {}

    if not isinstance(payload, dict):
        payload = {}

    cleaned = {}
    for key, value in payload.items():
        folder_key = str(key or "").strip()
        if not folder_key:
            continue
        if isinstance(value, dict):
            try:
                idx = max(0, int(value.get("index", 0) or 0))
            except (TypeError, ValueError):
                idx = 0
            cleaned[folder_key] = {
                "index": idx,
                "last_played": float(value.get("last_played", 0) or 0),
                "seek_seconds": max(0.0, float(value.get("seek_seconds", 0) or 0)),
            }
        else:
            try:
                idx = int(value)
            except (TypeError, ValueError):
                continue
            if idx < 0:
                idx = 0
            cleaned[folder_key] = idx

    with FOLDER_RESUME_LOCK:
        FOLDER_RESUME_MAP = cleaned


def save_folder_resume_map():
    with FOLDER_RESUME_LOCK:
        snapshot = dict(FOLDER_RESUME_MAP)
    try:
        os.makedirs(os.path.dirname(FOLDER_RESUME_PATH), exist_ok=True)
        write_json_atomic(FOLDER_RESUME_PATH, snapshot)
    except OSError as e:
        print(f"⚠️ Failed to save folder resume map: {e}")


def get_folder_resume_index(folder_key, identity="guest"):
    if not folder_key:
        return 0
    key = make_resume_map_key(folder_key, identity)
    with FOLDER_RESUME_LOCK:
        val = FOLDER_RESUME_MAP.get(key, 0)
    # Support both legacy int and new dict format
    if isinstance(val, dict):
        return max(0, int(val.get("index", 0) or 0))
    return max(0, int(val or 0))


RECENTLY_PLAYED_LIMIT = 20

def set_folder_resume_index(folder_key, index, identity="guest", seek_seconds=0):
    if not folder_key:
        return
    key = make_resume_map_key(folder_key, identity)
    safe_index = max(0, int(index or 0))
    safe_seek = max(0.0, float(seek_seconds or 0))
    with FOLDER_RESUME_LOCK:
        last_played = time.time()
        FOLDER_RESUME_MAP[key] = {"index": safe_index, "last_played": last_played, "seek_seconds": safe_seek}
    save_folder_resume_map()


def get_folder_resume_seek_seconds(folder_key, identity="guest"):
    if not folder_key:
        return 0.0
    key = make_resume_map_key(folder_key, identity)
    with FOLDER_RESUME_LOCK:
        val = FOLDER_RESUME_MAP.get(key)
    if isinstance(val, dict):
        return max(0.0, float(val.get("seek_seconds", 0) or 0))
    return 0.0


def get_recently_played(identity, limit=5):
    """Return the most recently played folder paths for an identity."""
    prefix = normalize_resume_identity(identity) + "::"
    entries = []
    with FOLDER_RESUME_LOCK:
        for key, val in FOLDER_RESUME_MAP.items():
            if not key.startswith(prefix):
                continue
            folder_key = key[len(prefix):]
            if isinstance(val, dict):
                idx = max(0, int(val.get("index", 0) or 0))
                last_played = float(val.get("last_played", 0) or 0)
            else:
                idx = max(0, int(val or 0))
                last_played = 0.0
            if last_played > 0:
                entries.append({"folder_key": folder_key, "resume_index": idx, "last_played": last_played})
    entries.sort(key=lambda e: -e["last_played"])
    return entries[:max(1, int(limit or 5))]


def normalize_username(username):
    value = re.sub(r"\s+", " ", str(username or "").strip())
    if len(value) < 3 or len(value) > 32:
        return None
    if not re.fullmatch(r"[A-Za-z0-9._-]{3,32}", value):
        return None
    return value


def normalize_theme_payload(raw_theme, raw_vars):
    theme_name = str(raw_theme or "").strip().lower()
    if not theme_name or not THEME_NAME_RE.fullmatch(theme_name):
        return None

    clean_vars = {}
    if isinstance(raw_vars, dict):
        for key, value in raw_vars.items():
            if len(clean_vars) >= THEME_MAX_VARS:
                break
            k = str(key or "").strip()
            v = str(value or "").strip()
            if not k or not v:
                continue
            if not THEME_VAR_KEY_RE.fullmatch(k):
                continue
            if len(v) > THEME_MAX_VALUE_LENGTH:
                continue
            clean_vars[k] = v

    return {
        "name": theme_name,
        "vars": clean_vars,
    }


def prune_auth_sessions_locked(now_ts=None):
    """Prune stale/invalid auth sessions while AUTH_LOCK is held."""
    now = int(now_ts or time.time())
    users = AUTH_DB.setdefault("users", {})
    sessions_map = AUTH_DB.setdefault("sessions", {})

    # First pass: remove broken, orphaned, or expired sessions.
    for token, info in list(sessions_map.items()):
        tok = str(token or "").strip()
        if len(tok) < 16 or not isinstance(info, dict):
            sessions_map.pop(token, None)
            continue
        user_key = str(info.get("user_key") or "").strip().lower()
        if user_key not in users:
            sessions_map.pop(token, None)
            continue
        try:
            last_seen_ts = int(info.get("last_seen_ts") or info.get("created_ts") or 0)
        except (TypeError, ValueError):
            last_seen_ts = 0
        if not last_seen_ts or (now - last_seen_ts) > AUTH_SESSION_TTL_SECONDS:
            sessions_map.pop(token, None)

    # Second pass: cap session count per user by newest activity.
    by_user = {}
    for token, info in sessions_map.items():
        if not isinstance(info, dict):
            continue
        user_key = str(info.get("user_key") or "").strip().lower()
        if not user_key:
            continue
        try:
            sort_ts = int(info.get("last_seen_ts") or info.get("created_ts") or 0)
        except (TypeError, ValueError):
            sort_ts = 0
        by_user.setdefault(user_key, []).append((token, sort_ts))

    for user_key, entries in by_user.items():
        if len(entries) <= AUTH_MAX_SESSIONS_PER_USER:
            continue
        entries.sort(key=lambda item: item[1], reverse=True)
        for token, _ in entries[AUTH_MAX_SESSIONS_PER_USER:]:
            sessions_map.pop(token, None)


def load_auth_db():
    global AUTH_DB
    try:
        with open(USERS_STORAGE_PATH, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        payload = {}

    users = payload.get("users") if isinstance(payload, dict) else {}
    sessions_map = payload.get("sessions") if isinstance(payload, dict) else {}
    if not isinstance(users, dict):
        users = {}
    if not isinstance(sessions_map, dict):
        sessions_map = {}

    clean_users = {}
    for key, info in users.items():
        k = str(key or "").strip().lower()
        if not k or not isinstance(info, dict):
            continue
        username = normalize_username(info.get("username") or key)
        password = str(info.get("password") or "")
        if not username or len(password) < 3:
            continue
        created_ts = int(info.get("created_ts") or int(time.time()))
        last_rename_ts = int(info.get("last_rename_ts") or 0)
        clean_users[k] = {
            "username": username,
            "password": password,
            "created_ts": created_ts,
            "last_rename_ts": last_rename_ts,
            "cookie_clicks": max(0, int(info.get("cookie_clicks", 0) or 0)),
            "blunt_hits": max(0, int(info.get("blunt_hits", 0) or 0)),
            "snake_highscore": max(0, int(info.get("snake_highscore", 0) or 0)),
            "snake_wins": max(0, int(info.get("snake_wins", 0) or 0)),
            "is_admin": bool(info.get("is_admin") or info.get("isAdmin")),
            "enabled": bool(info.get("enabled", True)),
        }
        theme_payload = normalize_theme_payload(info.get("theme"), info.get("theme_vars"))
        if not theme_payload and isinstance(info.get("theme_pref"), dict):
            # Backward/alternate shape support.
            pref = info.get("theme_pref")
            theme_payload = normalize_theme_payload(pref.get("name"), pref.get("vars"))
        if theme_payload:
            clean_users[k]["theme_pref"] = theme_payload

    clean_sessions = {}
    for token, info in sessions_map.items():
        tok = str(token or "").strip()
        if len(tok) < 16 or not isinstance(info, dict):
            continue
        user_key = str(info.get("user_key") or "").strip().lower()
        if user_key not in clean_users:
            continue
        clean_sessions[tok] = {
            "user_key": user_key,
            "created_ts": int(info.get("created_ts") or int(time.time())),
            "last_seen_ts": int(info.get("last_seen_ts") or int(time.time())),
        }

    with AUTH_LOCK:
        AUTH_DB = {"users": clean_users, "sessions": clean_sessions}
        prune_auth_sessions_locked()


def save_auth_db():
    with AUTH_LOCK:
        prune_auth_sessions_locked()
        snapshot = {
            "users": dict(AUTH_DB.get("users", {})),
            "sessions": dict(AUTH_DB.get("sessions", {})),
        }
    try:
        os.makedirs(os.path.dirname(USERS_STORAGE_PATH), exist_ok=True)
        write_json_atomic(USERS_STORAGE_PATH, snapshot)
    except OSError as e:
        print(f"⚠️ Failed to save auth db: {e}")


def auth_get_user_by_token(token):
    tok = str(token or "").strip()
    if not tok:
        return None, None
    with AUTH_LOCK:
        prune_auth_sessions_locked()
        session_info = AUTH_DB.get("sessions", {}).get(tok)
        if not isinstance(session_info, dict):
            return None, None
        user_key = str(session_info.get("user_key") or "").strip().lower()
        user_info = AUTH_DB.get("users", {}).get(user_key)
        if not isinstance(user_info, dict):
            return None, None
        session_info["last_seen_ts"] = int(time.time())
    return user_key, user_info


def auth_is_user_enabled(user_info):
    if not isinstance(user_info, dict):
        return False
    return bool(user_info.get("enabled", True))


def auth_is_user_admin(user_info):
    if not isinstance(user_info, dict):
        return False
    return bool(user_info.get("is_admin") or user_info.get("isAdmin"))


def require_admin_by_token(token):
    user_key, user_info = auth_get_user_by_token(token)
    if not user_key or not isinstance(user_info, dict):
        return None, None
    if not auth_is_user_enabled(user_info):
        return None, None
    if not auth_is_user_admin(user_info):
        return None, None
    return user_key, user_info


def _read_cpu_percent_linux():
    global CPU_SAMPLE_PREV
    try:
        with open("/proc/stat", "r", encoding="utf-8") as f:
            first = f.readline().strip()
    except OSError:
        return None
    if not first.startswith("cpu "):
        return None
    parts = first.split()[1:]
    if len(parts) < 4:
        return None
    try:
        values = [int(x) for x in parts]
    except ValueError:
        return None

    idle = values[3] + (values[4] if len(values) > 4 else 0)
    total = sum(values)
    now = (idle, total)

    with CPU_SAMPLE_LOCK:
        prev = CPU_SAMPLE_PREV
        CPU_SAMPLE_PREV = now

    if not prev:
        return None

    idle_delta = idle - prev[0]
    total_delta = total - prev[1]
    if total_delta <= 0:
        return None
    used = (total_delta - idle_delta) / total_delta * 100.0
    return round(max(0.0, min(100.0, used)), 1)


def _read_memory_stats_linux():
    info = {}
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            for line in f:
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                key = key.strip()
                value = value.strip().split()[0]
                try:
                    info[key] = int(value) * 1024
                except ValueError:
                    continue
    except OSError:
        return None

    total = info.get("MemTotal")
    available = info.get("MemAvailable")
    if not isinstance(total, int) or total <= 0:
        return None
    if not isinstance(available, int):
        free = info.get("MemFree")
        cached = info.get("Cached")
        buffers = info.get("Buffers")
        available = sum(v for v in (free, cached, buffers) if isinstance(v, int))
    used = max(0, total - max(0, int(available or 0)))
    used_pct = round((used / total) * 100.0, 1) if total > 0 else 0.0
    return {
        "total": total,
        "used": used,
        "free": max(0, total - used),
        "usedPercent": used_pct,
    }


def _read_process_rss_bytes_linux():
    try:
        with open("/proc/self/statm", "r", encoding="utf-8") as f:
            parts = f.read().strip().split()
        if len(parts) < 2:
            return 0
        rss_pages = int(parts[1])
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        return max(0, rss_pages * page_size)
    except (OSError, ValueError, TypeError):
        return 0


def _read_disk_stats(path_value):
    target = path_value if path_value and os.path.exists(path_value) else BASE_DIR
    try:
        st = os.statvfs(target)
    except OSError:
        return {
            "path": target,
            "free": None,
            "total": None,
            "usedPercent": None,
        }
    total = st.f_frsize * st.f_blocks
    free = st.f_frsize * st.f_bavail
    used = max(0, total - free)
    used_pct = round((used / total) * 100.0, 1) if total > 0 else None
    return {
        "path": target,
        "free": free,
        "total": total,
        "usedPercent": used_pct,
    }


def get_admin_health_snapshot():
    now = time.time()
    with ADMIN_HEALTH_LOCK:
        if ADMIN_HEALTH_CACHE["payload"] and (now - ADMIN_HEALTH_CACHE["timestamp"]) < ADMIN_HEALTH_SAMPLE_SECONDS:
            return ADMIN_HEALTH_CACHE["payload"]

    cpu_percent = _read_cpu_percent_linux()
    if cpu_percent is None:
        try:
            load_1 = os.getloadavg()[0]
            cores = max(1, os.cpu_count() or 1)
            cpu_percent = round(min(100.0, max(0.0, (load_1 / cores) * 100.0)), 1)
        except OSError:
            cpu_percent = 0.0

    memory = _read_memory_stats_linux() or {
        "total": 0,
        "used": 0,
        "free": 0,
        "usedPercent": 0.0,
    }
    try:
        load_avg = [round(v, 2) for v in os.getloadavg()]
    except OSError:
        load_avg = [0.0, 0.0, 0.0]

    disk = _read_disk_stats(MEDIA_ROOT)

    payload = {
        "cpuPercent": cpu_percent,
        "cpuCores": max(1, os.cpu_count() or 1),
        "memory": memory,
        "loadAvg": load_avg,
        "uptimeSec": max(0, int(time.time() - os.stat("/proc/1").st_ctime)) if os.path.exists("/proc/1") else 0,
        "process": {
            "rss": _read_process_rss_bytes_linux(),
            "heapUsed": 0,
            "heapTotal": 0,
        },
        "disk": disk,
        "hostname": os.uname().nodename if hasattr(os, "uname") else "localhost",
        "platform": os.uname().sysname.lower() if hasattr(os, "uname") else "linux",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "clientPollMs": max(3000, int(CONFIG.get("admin_health", {}).get("client_poll_ms", 5000))) if isinstance(CONFIG.get("admin_health"), dict) else 5000,
    }

    with ADMIN_HEALTH_LOCK:
        ADMIN_HEALTH_CACHE["timestamp"] = now
        ADMIN_HEALTH_CACHE["payload"] = payload
    return payload


def auth_create_session(user_key):
    token = secrets.token_hex(24)
    now = int(time.time())
    with AUTH_LOCK:
        prune_auth_sessions_locked(now)
        AUTH_DB.setdefault("sessions", {})[token] = {
            "user_key": user_key,
            "created_ts": now,
            "last_seen_ts": now,
        }
        prune_auth_sessions_locked(now)
    save_auth_db()
    return token


def auth_remove_session(token):
    tok = str(token or "").strip()
    if not tok:
        return
    with AUTH_LOCK:
        AUTH_DB.get("sessions", {}).pop(tok, None)
    save_auth_db()


def normalize_presence_client_id(raw_value):
    client_id = str(raw_value or "").strip()
    if PRESENCE_CLIENT_ID_RE.fullmatch(client_id):
        return client_id
    return ""


def prune_presence_locked(now_ts=None):
    now = int(now_ts or time.time())
    cutoff = now - PRESENCE_TTL_SECONDS

    for client_id, info in list(PRESENCE_MAP.items()):
        if not isinstance(info, dict):
            PRESENCE_MAP.pop(client_id, None)
            continue
        try:
            last_seen_ts = int(info.get("last_seen_ts") or 0)
        except (TypeError, ValueError):
            last_seen_ts = 0
        if last_seen_ts <= cutoff:
            PRESENCE_MAP.pop(client_id, None)

    overflow = len(PRESENCE_MAP) - PRESENCE_MAX_ENTRIES
    if overflow > 0:
        sorted_entries = sorted(
            PRESENCE_MAP.items(),
            key=lambda item: int((item[1] or {}).get("last_seen_ts") or 0),
        )
        for client_id, _ in sorted_entries[:overflow]:
            PRESENCE_MAP.pop(client_id, None)


def touch_presence(client_id, ip, username="Guest", authenticated=False, user_key=""):
    clean_client_id = normalize_presence_client_id(client_id)
    if not clean_client_id:
        return

    clean_user_key = str(user_key or "").strip().lower()
    is_authenticated = bool(authenticated and clean_user_key)
    if not is_authenticated:
        # Guests are not tracked in online user presence.
        with PRESENCE_LOCK:
            PRESENCE_MAP.pop(clean_client_id, None)
        return

    clean_username = re.sub(r"\s+", " ", str(username or "").strip())[:32] or "Guest"
    now = int(time.time())
    with PRESENCE_LOCK:
        prune_presence_locked(now)
        PRESENCE_MAP[clean_client_id] = {
            "client_id": clean_client_id,
            "ip": str(ip or "").strip(),
            "user_key": clean_user_key,
            "username": clean_username,
            "authenticated": True,
            "last_seen_ts": now,
        }
        prune_presence_locked(now)


def remove_presence(client_id, user_key=""):
    clean_client_id = normalize_presence_client_id(client_id)
    if not clean_client_id:
        return

    clean_user_key = str(user_key or "").strip().lower()
    with PRESENCE_LOCK:
        info = PRESENCE_MAP.get(clean_client_id)
        if not isinstance(info, dict):
            return
        existing_user_key = str(info.get("user_key") or "").strip().lower()
        if clean_user_key and existing_user_key and existing_user_key != clean_user_key:
            return
        PRESENCE_MAP.pop(clean_client_id, None)


def get_presence_snapshot(requester_user_key=""):
    clean_requester_key = str(requester_user_key or "").strip().lower()
    if not clean_requester_key:
        return {
            "requires_login": True,
            "count": 0,
            "users": [],
        }

    now = int(time.time())

    with PRESENCE_LOCK:
        prune_presence_locked(now)
        entries = list(PRESENCE_MAP.values())

    entries.sort(key=lambda info: int(info.get("last_seen_ts") or 0), reverse=True)

    deduped = []
    seen_keys = set()
    for info in entries:
        if not isinstance(info, dict):
            continue
        if not bool(info.get("authenticated")):
            continue

        user_key = str(info.get("user_key") or "").strip().lower()
        username = re.sub(r"\s+", " ", str(info.get("username") or "").strip())[:32]
        if not user_key or not username:
            continue
        if user_key in seen_keys:
            continue
        seen_keys.add(user_key)
        deduped.append({
            "user_key": user_key,
            "username": username,
        })

    users = []
    for info in deduped[:20]:
        users.append({
            "username": info.get("username", ""),
            "is_me": bool(info.get("user_key") == clean_requester_key),
        })

    return {
        "requires_login": False,
        "count": len(deduped),
        "users": users,
    }


def _prune_stale_viewers_locked(now):
    """Remove CLIENT_CHANNEL entries older than VIEWER_TTL_SECONDS. Must be called under VIEWER_LOCK."""
    cutoff = now - VIEWER_TTL_SECONDS
    for cid in list(CLIENT_CHANNEL.keys()):
        if CLIENT_CHANNEL[cid]["ts"] <= cutoff:
            del CLIENT_CHANNEL[cid]


def viewer_join(client_id, channel_id):
    """Join or heartbeat a channel. Updates timestamp on same-channel to keep TTL alive."""
    clean_client_id = str(client_id or "").strip()
    if not clean_client_id or not PRESENCE_CLIENT_ID_RE.fullmatch(clean_client_id):
        return
    clean_channel_id = str(channel_id or "").strip()[:64]
    if not clean_channel_id or not VIEWER_CHANNEL_ID_RE.fullmatch(clean_channel_id):
        return
    now = int(time.time())
    with VIEWER_LOCK:
        _prune_stale_viewers_locked(now)
        existing = CLIENT_CHANNEL.get(clean_client_id)
        if existing and existing["channel_id"] == clean_channel_id:
            # Same channel — just refresh the timestamp (heartbeat)
            existing["ts"] = now
            return
        # Moving to a different channel or joining fresh
        old_channel = existing["channel_id"] if existing else None
        CLIENT_CHANNEL[clean_client_id] = {"channel_id": clean_channel_id, "ts": now}
        if old_channel:
            pass  # count comes from CLIENT_CHANNEL length, not a separate counter


def viewer_leave(client_id):
    """Remove a client from their current channel."""
    clean_client_id = str(client_id or "").strip()
    if not clean_client_id:
        return
    with VIEWER_LOCK:
        CLIENT_CHANNEL.pop(clean_client_id, None)


def get_viewer_counts():
    """Return {channel_id: count} pruning stale entries first."""
    now = int(time.time())
    counts = {}
    with VIEWER_LOCK:
        _prune_stale_viewers_locked(now)
        for entry in CLIENT_CHANNEL.values():
            cid = entry["channel_id"]
            counts[cid] = counts.get(cid, 0) + 1
    return counts


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
    r"\b(?:S(?P<season>\d{1,2})E(?P<episodes>\d{1,2}(?:\s*[-–]?\s*E\d{1,2})*)|(?P<xseason>\d{1,2})x(?P<xepisodes>\d{1,2}(?:\s*[-–]\s*\d{1,2})*))\b",
    re.IGNORECASE,
)

# Matches "episode 3", "season 2 episode 3" spelled out in full
VERBOSE_EPISODE_RE = re.compile(
    r"(?:season\s+\d{1,2}\s+)?episode\s+(\d{1,3})",
    re.IGNORECASE,
)


def natural_sort_key(value):
    """Sort helper that treats digit groups numerically (e.g. Season 10 after Season 9)."""
    text = str(value or "")
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", text)]


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
            (
                f for f in os.listdir(parent)
                if not f.startswith('.') and os.path.isfile(os.path.join(parent, f))
            ),
            key=natural_sort_key,
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
    """Return queue in actual sequential order with is_current flag on the current episode.
    Previous episodes appear before current so the frontend can scroll up to them."""
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

    preview = []
    for list_idx in range(total):
        path = valid_files[list_idx]
        parent_dir = os.path.dirname(path)
        preview.append({
            "position": list_idx + 1,
            "total": total,
            "is_current": list_idx == idx,
            "season_folder": os.path.basename(parent_dir),
            "source_path": os.path.relpath(path, BASE_DIR),
            "display_title": build_display_title(path),
            "current_file": prettify_media_name(
                os.path.basename(path),
                parent=os.path.basename(parent_dir),
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
    return f"E{episode_numbers[0].zfill(2)}"


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
        if parsed.path == "/admin/health/login":
            login_path = os.path.join(BASE_DIR, "public", "admin-health", "login.html")
            if os.path.exists(login_path):
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                with open(login_path, "rb") as f:
                    self.wfile.write(f.read())
                return
            self.send_error(404)
            return
        if parsed.path == "/admin/health":
            qs = parse_qs(parsed.query)
            token = str(qs.get("token", [""])[0]).strip()
            _, admin_info = require_admin_by_token(token)
            if not admin_info:
                self.send_response(302)
                self.send_header("Location", "/admin/health/login")
                self.end_headers()
                return
            dashboard_path = os.path.join(BASE_DIR, "public", "admin-health", "index.html")
            if os.path.exists(dashboard_path):
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                with open(dashboard_path, "rb") as f:
                    self.wfile.write(f.read())
                return
            self.send_error(404)
            return
        if parsed.path == "/js/admin-entry-button.js":
            js_path = os.path.join(BASE_DIR, "public", "js", "admin-entry-button.js")
            if os.path.exists(js_path):
                self.send_response(200)
                self.send_header("Content-Type", "application/javascript")
                self.end_headers()
                with open(js_path, "rb") as f:
                    self.wfile.write(f.read())
                return
            self.send_error(404)
            return
        if parsed.path == "/":
            # Serve index.html from src/
            index_path = os.path.join(BASE_DIR, "src", "index.html")
            if os.path.exists(index_path):
                stat = os.stat(index_path)
                mtime = int(stat.st_mtime)
                etag = f'"{mtime}"'
                from email.utils import formatdate
                last_modified = formatdate(stat.st_mtime, usegmt=True)
                # Support conditional requests (normal refresh = 304, hard refresh = 200)
                client_etag = self.headers.get("If-None-Match", "")
                if client_etag == etag:
                    self.send_response(304)
                    self.send_header("ETag", etag)
                    self.send_header("Cache-Control", "no-cache")
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("ETag", etag)
                self.send_header("Last-Modified", last_modified)
                self.send_header("Cache-Control", "no-cache")
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
        if parsed.path == "/api/auth/me":
            qs = parse_qs(parsed.query)
            token = str(qs.get("token", [""])[0]).strip()
            user_key, user_info = auth_get_user_by_token(token)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            if user_key and isinstance(user_info, dict):
                self.wfile.write(json.dumps({
                    "authenticated": True,
                    "username": user_info.get("username", "Anonymous"),
                }).encode())
            else:
                self.wfile.write(json.dumps({"authenticated": False}).encode())
            return
        if parsed.path == "/api/auth/theme":
            qs = parse_qs(parsed.query)
            token = str(qs.get("token", [""])[0]).strip()
            user_key, user_info = auth_get_user_by_token(token)
            if not user_key or not isinstance(user_info, dict):
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Not authenticated"}).encode())
                return

            pref = user_info.get("theme_pref") if isinstance(user_info.get("theme_pref"), dict) else {}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "ok": True,
                "theme": pref.get("name", ""),
                "vars": pref.get("vars", {}) if isinstance(pref.get("vars"), dict) else {},
            }).encode())
            return
        if parsed.path == "/api/admin/flag":
            qs = parse_qs(parsed.query)
            token = str(qs.get("token", [""])[0]).strip()
            user_key, user_info = auth_get_user_by_token(token)
            is_admin = bool(user_key and auth_is_user_enabled(user_info) and auth_is_user_admin(user_info))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "isAdmin": is_admin,
                "username": user_info.get("username") if isinstance(user_info, dict) else None,
            }).encode())
            return

        if parsed.path == "/api/suggestions":
            qs = parse_qs(parsed.query)
            token = str(qs.get("token", [""])[0]).strip()
            user_key, user_info = auth_get_user_by_token(token)
            is_admin = bool(user_key and auth_is_user_enabled(user_info) and auth_is_user_admin(user_info))
            with SUGGESTIONS_LOCK:
                snapshot = list(SUGGESTIONS_LIST)
            # Non-admins don't see resolved entries
            if not is_admin:
                snapshot = [s for s in snapshot if not s.get("resolved")]
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"suggestions": snapshot, "is_admin": is_admin, "username": str(user_info.get("username") or "") if isinstance(user_info, dict) else ""}).encode())
            return
        if parsed.path == "/api/favorites":
            qs = parse_qs(parsed.query)
            token = str(qs.get("token", [""])[0]).strip()
            user_key, user_info = auth_get_user_by_token(token)
            if not user_key or not auth_is_user_enabled(user_info):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"paths": []}).encode())
                return
            identity = normalize_resume_identity(str(user_info.get("username", user_key) or user_key))
            with FAVORITES_LOCK:
                paths = list(FAVORITES_MAP.get(identity, []))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"paths": paths}).encode())
            return
        if parsed.path == "/api/admin/health":
            qs = parse_qs(parsed.query)
            token = str(qs.get("token", [""])[0]).strip()
            _, admin_info = require_admin_by_token(token)
            if not admin_info:
                self.send_response(403)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Forbidden"}).encode())
                return
            snapshot = get_admin_health_snapshot()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(snapshot).encode())
            return
        if parsed.path == "/api/admin/users":
            qs = parse_qs(parsed.query)
            token = str(qs.get("token", [""])[0]).strip()
            _, admin_info = require_admin_by_token(token)
            if not admin_info:
                self.send_response(403)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Forbidden"}).encode())
                return
            rows = []
            with AUTH_LOCK:
                users_map = AUTH_DB.get("users", {})
                for key in sorted(users_map.keys()):
                    info = users_map.get(key)
                    if not isinstance(info, dict):
                        continue
                    rows.append({
                        "username": str(info.get("username") or key),
                        "isAdmin": bool(info.get("is_admin") or info.get("isAdmin")),
                        "enabled": bool(info.get("enabled", True)),
                        "created_ts": int(info.get("created_ts") or 0),
                        "cookie_clicks": max(0, int(info.get("cookie_clicks", 0) or 0)),
                    })
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"users": rows}).encode())
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
            for name in sorted(os.listdir(full), key=natural_sort_key):
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
        if parsed.path == "/api/browse_recent":
            qs = parse_qs(parsed.query)
            token = str(qs.get("token", [""])[0]).strip()
            user_key, _ = auth_get_user_by_token(token)
            if not user_key:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"entries": []}).encode())
                return
            identity = f"user:{user_key}"
            raw_entries = get_recently_played(identity, limit=RECENTLY_PLAYED_LIMIT)
            result = []
            for entry in raw_entries:
                fk = entry["folder_key"]
                real = safe_path(fk)
                if not real or not os.path.isdir(real):
                    continue
                folder_name = os.path.basename(real)
                # Collect all media files sorted the same way as play_folder
                all_files = []
                for root, _, ns in os.walk(real):
                    for n in ns:
                        if n.lower().endswith((".mp4", ".mkv")):
                            all_files.append(os.path.join(root, n))
                all_files = sorted(all_files, key=natural_sort_key)
                total = len(all_files)
                # Season info for the resume position (resume_idx is 0-based)
                resume_idx = entry["resume_index"]
                season_name = None
                episode_in_season = None
                season_total = None
                if 0 <= resume_idx < total:
                    current_file = all_files[resume_idx]
                    parent_dir = os.path.dirname(current_file)
                    has_seasons = parent_dir != real
                    if has_seasons:
                        season_name = os.path.basename(parent_dir)
                        season_files = [f for f in all_files if os.path.dirname(f) == parent_dir]
                        if current_file in season_files:
                            episode_in_season = season_files.index(current_file) + 1
                        season_total = len(season_files)
                result.append({
                    "folder_key": fk,
                    "folder_name": folder_name,
                    "path": fk,
                    "resume_index": entry["resume_index"],
                    "total": total,
                    "season_name": season_name,
                    "episode_in_season": episode_in_season,
                    "season_total": season_total,
                    "last_played": entry["last_played"],
                })
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"entries": result}).encode())
            return
        if parsed.path == "/api/folder_cover":
            qs = parse_qs(parsed.query)
            rel_path = qs.get("path", [""])[0]
            real = safe_path(rel_path)
            if not real or not os.path.isdir(real):
                self.send_error(404)
                return
            cover_names = ["cover.jpg", "cover.jpeg", "cover.png", "cover.webp",
                           "poster.jpg", "poster.jpeg", "poster.png", "folder.jpg", "folder.png"]
            found = None
            for cn in cover_names:
                candidate = os.path.join(real, cn)
                if os.path.isfile(candidate):
                    found = candidate
                    break
            if not found:
                self.send_error(404)
                return
            ext = os.path.splitext(found)[1].lower()
            mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg",
                    "png": "image/png", "webp": "image/webp"}.get(ext.lstrip("."), "image/jpeg")
            try:
                with open(found, "rb") as f:
                    data = f.read()
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Cache-Control", "public, max-age=3600")
                self.end_headers()
                self.wfile.write(data)
            except OSError:
                self.send_error(404)
            return
        if parsed.path == "/api/cookies":
            qs = parse_qs(parsed.query)
            token = str(qs.get("token", [""])[0]).strip()
            user_key, user_info = auth_get_user_by_token(token)
            with COOKIE_LOCK:
                count = COOKIE_COUNT
            user_clicks = 0
            if user_key and isinstance(user_info, dict):
                try:
                    user_clicks = max(0, int(user_info.get("cookie_clicks", 0) or 0))
                except (TypeError, ValueError):
                    user_clicks = 0
            leaderboard = get_cookie_leaderboard(5)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "count": count,
                "leaderboard": leaderboard,
                "your_clicks": user_clicks,
                "authenticated": bool(user_key),
            }).encode())
            return
        if parsed.path == "/api/blunts":
            qs = parse_qs(parsed.query)
            token = str(qs.get("token", [""])[0]).strip()
            user_key, user_info = auth_get_user_by_token(token)
            with BLUNT_LOCK:
                count = BLUNT_COUNT
            user_hits = 0
            if user_key and isinstance(user_info, dict):
                try:
                    user_hits = max(0, int(user_info.get("blunt_hits", 0) or 0))
                except (TypeError, ValueError):
                    user_hits = 0
            leaderboard = get_blunt_leaderboard(5)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "count": count,
                "leaderboard": leaderboard,
                "your_hits": user_hits,
                "authenticated": bool(user_key),
            }).encode())
            return
        if parsed.path == "/api/snake":
            qs = parse_qs(parsed.query)
            token = str(qs.get("token", [""])[0]).strip()
            user_key, user_info = auth_get_user_by_token(token)
            user_highscore = 0
            user_wins = 0
            if user_key and isinstance(user_info, dict):
                try:
                    user_highscore = max(0, int(user_info.get("snake_highscore", 0) or 0))
                except (TypeError, ValueError):
                    user_highscore = 0
                try:
                    user_wins = max(0, int(user_info.get("snake_wins", 0) or 0))
                except (TypeError, ValueError):
                    user_wins = 0
            leaderboard = get_snake_leaderboard(5)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "leaderboard": leaderboard,
                "your_highscore": user_highscore,
                "your_wins": user_wins,
                "authenticated": bool(user_key),
            }).encode())
            return
        if parsed.path == "/api/chat":
            qs = parse_qs(parsed.query)
            channel = str(qs.get("channel", [""])[0]).strip()
            token = str(qs.get("token", [""])[0]).strip()
            try:
                since_id = int(qs.get("since", ["0"])[0])
            except (TypeError, ValueError):
                since_id = 0

            if not channel:
                self.send_error(400)
                return

            user_key, _ = auth_get_user_by_token(token)
            if not user_key:
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Login required for chat"}).encode())
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

        if parsed.path == "/api/presence":
            qs = parse_qs(parsed.query)
            client_id = normalize_presence_client_id(qs.get("client_id", [""])[0])
            token = str(qs.get("token", [""])[0]).strip()
            user_key, user_info = auth_get_user_by_token(token)

            username = "Guest"
            if user_key and isinstance(user_info, dict):
                username = str(user_info.get("username") or "Guest")

            if client_id:
                touch_presence(
                    client_id=client_id,
                    ip=self.client_address[0],
                    username=username,
                    authenticated=bool(user_key),
                    user_key=user_key,
                )

            snapshot = get_presence_snapshot(user_key)
            snapshot["viewer_counts"] = get_viewer_counts()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(snapshot).encode())
            return

        return super().do_GET()

    def do_POST(self):
        if self.path == "/api/admin/users/update":
            length = int(self.headers.get("Content-Length", 0))
            try:
                raw_body = self.rfile.read(length) if length > 0 else b"{}"
                body = json.loads(raw_body)
            except json.JSONDecodeError:
                self.send_error(400)
                return

            token = str(body.get("token") or "").strip()
            admin_key, admin_info = require_admin_by_token(token)
            if not admin_info:
                self.send_response(403)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Forbidden"}).encode())
                return

            target_username = normalize_username(body.get("username"))
            if not target_username:
                self.send_error(400)
                return
            target_key = target_username.lower()

            password = body.get("password")
            is_admin = body.get("isAdmin")
            enabled = body.get("enabled")

            with AUTH_LOCK:
                users = AUTH_DB.get("users", {})
                current = users.get(target_key)
                if not isinstance(current, dict):
                    self.send_response(404)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": "User not found"}).encode())
                    return

                updated = dict(current)
                if isinstance(is_admin, bool):
                    # Prevent accidentally removing admin role from self.
                    if target_key == admin_key and not is_admin:
                        self.send_response(400)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(json.dumps({"error": "Cannot remove your own admin role"}).encode())
                        return
                    updated["is_admin"] = is_admin
                if isinstance(enabled, bool):
                    # Prevent disabling your own current admin account.
                    if target_key == admin_key and not enabled:
                        self.send_response(400)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(json.dumps({"error": "Cannot disable your own account"}).encode())
                        return
                    updated["enabled"] = enabled
                if isinstance(password, str) and len(password) >= 3:
                    updated["password"] = password
                users[target_key] = updated

            save_auth_db()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True}).encode())
            return

        if self.path == "/api/admin/users/delete":
            length = int(self.headers.get("Content-Length", 0))
            try:
                raw_body = self.rfile.read(length) if length > 0 else b"{}"
                body = json.loads(raw_body)
            except json.JSONDecodeError:
                self.send_error(400)
                return

            token = str(body.get("token") or "").strip()
            admin_key, admin_info = require_admin_by_token(token)
            if not admin_info:
                self.send_response(403)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Forbidden"}).encode())
                return

            target_username = normalize_username(body.get("username"))
            if not target_username:
                self.send_error(400)
                return
            target_key = target_username.lower()

            if target_key == admin_key:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Cannot delete your own active admin account"}).encode())
                return

            with AUTH_LOCK:
                users = AUTH_DB.get("users", {})
                if target_key not in users:
                    self.send_response(404)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": "User not found"}).encode())
                    return

                users.pop(target_key, None)

                # Drop all auth sessions for deleted user.
                sessions_map = AUTH_DB.get("sessions", {})
                for session_token, session_info in list(sessions_map.items()):
                    if not isinstance(session_info, dict):
                        continue
                    if str(session_info.get("user_key") or "").strip().lower() == target_key:
                        sessions_map.pop(session_token, None)

                # Drop any live presence entries tied to deleted user.
                with PRESENCE_LOCK:
                    for client_id, presence in list(PRESENCE_MAP.items()):
                        if not isinstance(presence, dict):
                            continue
                        if str(presence.get("user_key") or "").strip().lower() == target_key:
                            PRESENCE_MAP.pop(client_id, None)

            save_auth_db()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True, "deleted": target_username}).encode())
            return

        if self.path == "/api/admin/reload_users":
            length = int(self.headers.get("Content-Length", 0))
            try:
                raw_body = self.rfile.read(length) if length > 0 else b"{}"
                body = json.loads(raw_body)
            except json.JSONDecodeError:
                self.send_error(400)
                return

            token = str(body.get("token") or "").strip()
            _, admin_info = require_admin_by_token(token)
            if not admin_info:
                self.send_response(403)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Forbidden"}).encode())
                return

            load_auth_db()
            with AUTH_LOCK:
                user_count = len(AUTH_DB.get("users", {}))

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "ok": True,
                "reloaded_users": user_count,
            }).encode())
            return

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

        if self.path.startswith("/api/cookies/click"):
            global COOKIE_COUNT
            parsed = urlparse(self.path)
            qs = parse_qs(parsed.query)
            token = str(qs.get("token", [""])[0]).strip()
            user_key, _ = auth_get_user_by_token(token)
            if not user_key:
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Login required to use cookie clicker"}).encode())
                return

            user_clicks = 0
            with AUTH_LOCK:
                users = AUTH_DB.get("users", {})
                current = users.get(user_key)
                if not isinstance(current, dict):
                    self.send_response(401)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": "Not authenticated"}).encode())
                    return
                updated = dict(current)
                updated["cookie_clicks"] = max(0, int(updated.get("cookie_clicks", 0) or 0)) + 1
                user_clicks = updated["cookie_clicks"]
                users[user_key] = updated

            with COOKIE_LOCK:
                COOKIE_COUNT += 1
                count = COOKIE_COUNT
            try:
                save_cookie_count()
            except OSError:
                pass
            save_auth_db()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"count": count, "your_clicks": user_clicks}).encode())
            return

        if self.path.startswith("/api/blunts/hit"):
            global BLUNT_COUNT
            parsed = urlparse(self.path)
            qs = parse_qs(parsed.query)
            token = str(qs.get("token", [""])[0]).strip()
            user_key, _ = auth_get_user_by_token(token)
            if not user_key:
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Login required to hit the blunt"}).encode())
                return

            user_hits = 0
            with AUTH_LOCK:
                users = AUTH_DB.get("users", {})
                current = users.get(user_key)
                if not isinstance(current, dict):
                    self.send_response(401)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": "Not authenticated"}).encode())
                    return
                updated = dict(current)
                updated["blunt_hits"] = max(0, int(updated.get("blunt_hits", 0) or 0)) + 1
                user_hits = updated["blunt_hits"]
                users[user_key] = updated

            with BLUNT_LOCK:
                BLUNT_COUNT += 1
                count = BLUNT_COUNT
            try:
                save_blunt_count()
            except OSError:
                pass
            save_auth_db()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"count": count, "your_hits": user_hits}).encode())
            return

        if self.path.startswith("/api/snake/score"):
            parsed_snake = urlparse(self.path)
            qs_snake = parse_qs(parsed_snake.query)
            token = str(qs_snake.get("token", [""])[0]).strip()
            user_key, _ = auth_get_user_by_token(token)
            if not user_key:
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Login required to save snake score"}).encode())
                return
            try:
                score = max(0, int(qs_snake.get("score", ["0"])[0]))
            except (TypeError, ValueError):
                score = 0
            won = qs_snake.get("won", ["0"])[0] in ("1", "true", "yes")
            new_highscore = 0
            new_wins = 0
            with AUTH_LOCK:
                users = AUTH_DB.get("users", {})
                current = users.get(user_key)
                if not isinstance(current, dict):
                    self.send_response(401)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": "Not authenticated"}).encode())
                    return
                updated = dict(current)
                old_highscore = max(0, int(updated.get("snake_highscore", 0) or 0))
                if score > old_highscore:
                    updated["snake_highscore"] = score
                new_highscore = max(old_highscore, score)
                if won:
                    updated["snake_wins"] = max(0, int(updated.get("snake_wins", 0) or 0)) + 1
                new_wins = max(0, int(updated.get("snake_wins", 0) or 0))
                users[user_key] = updated
            save_auth_db()
            save_snake_scores()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True, "your_highscore": new_highscore, "your_wins": new_wins}).encode())
            return

        length = int(self.headers.get("Content-Length", 0))
        try:
            raw_body = self.rfile.read(length) if length > 0 else b"{}"
            body = json.loads(raw_body)
        except json.JSONDecodeError:
            self.send_error(400)
            return

        if self.path == "/api/auth/register":
            username = normalize_username(body.get("username"))
            password = str(body.get("password") or "")
            if not username or len(password) < 3:
                self.send_error(400)
                return
            user_key = username.lower()
            with AUTH_LOCK:
                users = AUTH_DB.setdefault("users", {})
                if user_key in users:
                    self.send_response(409)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": "Username already exists"}).encode())
                    return
                users[user_key] = {
                    "username": username,
                    "password": password,
                    "created_ts": int(time.time()),
                    "last_rename_ts": 0,
                    "cookie_clicks": 0,
                    "snake_highscore": 0,
                    "snake_wins": 0,
                }
            save_auth_db()
            token = auth_create_session(user_key)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "ok": True,
                "token": token,
                "username": username,
            }).encode())
            return

        if self.path == "/api/auth/login":
            username = normalize_username(body.get("username"))
            password = str(body.get("password") or "")
            if not username or len(password) < 3:
                self.send_error(400)
                return
            user_key = username.lower()
            with AUTH_LOCK:
                user_info = AUTH_DB.get("users", {}).get(user_key)
            if not isinstance(user_info, dict):
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Invalid username and password"}).encode())
                return
            if not auth_is_user_enabled(user_info):
                self.send_response(403)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "This account is disabled"}).encode())
                return
            if str(user_info.get("password") or "") != password:
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Username exists but password is incorrect"}).encode())
                return
            token = auth_create_session(user_key)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "ok": True,
                "token": token,
                "username": user_info.get("username", username),
            }).encode())
            return

        if self.path == "/api/auth/logout":
            token = str(body.get("token") or "").strip()
            client_id = normalize_presence_client_id(body.get("client_id") or "")
            user_key, _ = auth_get_user_by_token(token)
            if client_id:
                remove_presence(client_id, user_key=user_key)
            auth_remove_session(token)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True}).encode())
            return

        if self.path == "/api/presence/offline":
            client_id = normalize_presence_client_id(body.get("client_id") or "")
            token = str(body.get("token") or "").strip()
            user_key, _ = auth_get_user_by_token(token)
            if client_id:
                remove_presence(client_id, user_key=user_key)
                viewer_leave(client_id)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True}).encode())
            return

        if self.path == "/api/viewer/join":
            client_id = normalize_presence_client_id(body.get("client_id") or "")
            channel_id = str(body.get("channel_id") or "").strip()[:64]
            if client_id and channel_id:
                viewer_join(client_id, channel_id)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"viewer_counts": get_viewer_counts()}).encode())
            return

        if self.path == "/api/viewer/leave":
            client_id = normalize_presence_client_id(body.get("client_id") or "")
            if client_id:
                viewer_leave(client_id)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True}).encode())
            return

        if self.path == "/api/auth/theme":
            token = str(body.get("token") or "").strip()
            theme_name = body.get("theme")
            theme_vars = body.get("vars")

            user_key, user_info = auth_get_user_by_token(token)
            if not user_key or not isinstance(user_info, dict):
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Not authenticated"}).encode())
                return

            normalized_theme = normalize_theme_payload(theme_name, theme_vars)
            if not normalized_theme:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Invalid theme payload"}).encode())
                return

            with AUTH_LOCK:
                users = AUTH_DB.get("users", {})
                current = users.get(user_key)
                if not isinstance(current, dict):
                    self.send_response(401)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": "Not authenticated"}).encode())
                    return
                updated = dict(current)
                updated["theme_pref"] = normalized_theme
                users[user_key] = updated
            save_auth_db()

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True}).encode())
            return

        if self.path == "/api/auth/rename":
            token = str(body.get("token") or "").strip()
            new_username = normalize_username(body.get("new_username"))
            password = str(body.get("password") or "")
            user_key, user_info = auth_get_user_by_token(token)
            if not user_key or not isinstance(user_info, dict):
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Not authenticated"}).encode())
                return
            if not new_username:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Please enter a valid new username (3-32 chars, letters/numbers/._-)"}).encode())
                return
            if len(password) < 3:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Please enter your current password"}).encode())
                return
            if str(user_info.get("password") or "") != password:
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Invalid password"}).encode())
                return

            now = int(time.time())
            old_user_key = user_key
            new_user_key = new_username.lower()
            with AUTH_LOCK:
                users = AUTH_DB.get("users", {})
                current = users.get(old_user_key)
                if not isinstance(current, dict):
                    self.send_response(401)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": "Not authenticated"}).encode())
                    return
                if new_user_key != old_user_key and new_user_key in users:
                    self.send_response(409)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": "Username already exists"}).encode())
                    return
                last_rename = int(current.get("last_rename_ts") or 0)
                if last_rename and (now - last_rename) < RENAME_COOLDOWN_SECONDS:
                    retry_after = RENAME_COOLDOWN_SECONDS - (now - last_rename)
                    self.send_response(429)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "error": "Rename is limited to once every 24 hours",
                        "retry_after_seconds": retry_after,
                    }).encode())
                    return

                updated = dict(current)
                updated["username"] = new_username
                updated["last_rename_ts"] = now
                users.pop(old_user_key, None)
                users[new_user_key] = updated
                for sess in AUTH_DB.get("sessions", {}).values():
                    if isinstance(sess, dict) and str(sess.get("user_key") or "").lower() == old_user_key:
                        sess["user_key"] = new_user_key
            save_auth_db()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True, "username": new_username}).encode())
            return

        if self.path == "/api/auth/change_password":
            token = str(body.get("token") or "").strip()
            current_password = str(body.get("current_password") or "")
            new_password = str(body.get("new_password") or "")
            user_key, user_info = auth_get_user_by_token(token)
            if not user_key or not isinstance(user_info, dict):
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Not authenticated"}).encode())
                return
            if len(current_password) < 3 or len(new_password) < 3:
                self.send_error(400)
                return
            if str(user_info.get("password") or "") != current_password:
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Invalid current password"}).encode())
                return

            with AUTH_LOCK:
                users = AUTH_DB.get("users", {})
                current = users.get(user_key)
                if not isinstance(current, dict):
                    self.send_response(401)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": "Not authenticated"}).encode())
                    return
                updated = dict(current)
                updated["password"] = new_password
                users[user_key] = updated
            save_auth_db()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True}).encode())
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
                "play_mode": session_info.get("play_mode", "single"),
                "folder_key": session_info.get("folder_key", ""),
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
                "play_mode": str(session_meta.get("play_mode") or "single"),
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
            play_mode = str(session_info.get("play_mode") or "shuffle")
            folder_key = str(session_info.get("folder_key") or "")
            resume_identity = str(session_info.get("resume_identity") or f"ip:{ip}")

            valid_files = [p for p in shuffle_files if os.path.isfile(p)]
            if not valid_files:
                self.send_error(404)
                return

            current_idx = int(session_info.get("shuffle_index", 0) or 0)
            next_idx = (current_idx + 1) % len(valid_files)
            next_file = valid_files[next_idx]
            duration_seconds = get_media_duration_seconds(next_file)
            if play_mode == "chronological" and folder_key:
                set_folder_resume_index(folder_key, next_idx, resume_identity)

            playlist_path, slot = start_ffmpeg(
                [next_file],
                slot,
                ip,
                seek_seconds=0,
                duration_seconds=duration_seconds,
                session_meta={
                    "shuffle_files": valid_files,
                    "shuffle_index": next_idx,
                    "play_mode": play_mode,
                    "folder_key": folder_key,
                    "resume_identity": resume_identity,
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
                "play_mode": play_mode,
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
            play_mode = str(session_info.get("play_mode") or "shuffle")
            folder_key = str(session_info.get("folder_key") or "")
            resume_identity = str(session_info.get("resume_identity") or f"ip:{ip}")

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
            if play_mode == "chronological" and folder_key:
                set_folder_resume_index(folder_key, selected_idx, resume_identity)

            playlist_path, slot = start_ffmpeg(
                [selected_file],
                slot,
                ip,
                seek_seconds=0,
                duration_seconds=duration_seconds,
                session_meta={
                    "shuffle_files": valid_files,
                    "shuffle_index": selected_idx,
                    "play_mode": play_mode,
                    "folder_key": folder_key,
                    "resume_identity": resume_identity,
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
                "play_mode": play_mode,
            }).encode())
            return

        if self.path == "/api/save_episode_progress":
            token = str(body.get("token") or "").strip()
            user_key, _ = auth_get_user_by_token(token)
            if not user_key:
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Login required"}).encode())
                return
            ip = self.client_address[0]
            slot = None
            for s, info in sessions.items():
                if info.get("ip") == ip:
                    slot = s
                    break
            if slot is None or slot not in sessions:
                self.send_response(404)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "No active session"}).encode())
                return
            session_info = sessions[slot]
            folder_key = session_info.get("folder_key", "")
            play_mode = session_info.get("play_mode", "")
            if not folder_key or play_mode != "chronological":
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Not in chronological mode"}).encode())
                return
            episode_index = int(session_info.get("shuffle_index", 0) or 0)
            resume_identity = session_info.get("resume_identity", f"ip:{ip}")
            seek_seconds = max(0.0, float(body.get("seek_seconds") or 0))
            set_folder_resume_index(folder_key, episode_index, resume_identity, seek_seconds=seek_seconds)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True}).encode())
            return

        if self.path == "/api/folder_resume_status":
            folder_path = body.get("path")
            real_folder = safe_path(folder_path)
            if not real_folder or not os.path.isdir(real_folder):
                self.send_error(400)
                return

            files = []
            for root, _, names in os.walk(real_folder):
                for n in names:
                    if n.lower().endswith((".mp4", ".mkv")):
                        files.append(os.path.join(root, n))
            files = sorted(files, key=natural_sort_key)
            if not files:
                self.send_error(404)
                return

            token = str(body.get("token") or "").strip()
            user_key, _ = auth_get_user_by_token(token)
            if not user_key:
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Login required for chronological checkpoints"}).encode())
                return

            resume_identity = f"user:{user_key}"
            folder_key = normalize_folder_key(real_folder)
            resume_index = get_folder_resume_index(folder_key, resume_identity)
            if resume_index >= len(files):
                resume_index = 0

            next_file = files[resume_index]
            display_title = build_display_title(next_file)
            resume_seek_seconds = get_folder_resume_seek_seconds(folder_key, resume_identity)

            # Compute season-aware position info
            season_dir = os.path.dirname(next_file)
            season_folder_name = os.path.basename(season_dir)
            # Season folder is distinct from the root folder itself
            has_seasons = season_dir != real_folder
            season_files = [f for f in files if os.path.dirname(f) == season_dir] if has_seasons else []
            episode_in_season = (season_files.index(next_file) + 1) if (has_seasons and next_file in season_files) else None
            season_total = len(season_files) if has_seasons else None

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "next_index": resume_index + 1,
                "total": len(files),
                "source_path": os.path.relpath(next_file, BASE_DIR),
                "display_title": display_title,
                "current_file": prettify_media_name(
                    os.path.basename(next_file),
                    parent=os.path.basename(os.path.dirname(next_file)),
                    episode_index=get_file_index(next_file),
                ),
                "season_folder": season_folder_name if has_seasons else None,
                "episode_in_season": episode_in_season,
                "season_total": season_total,
                "play_mode": "chronological",
                "seek_seconds": resume_seek_seconds,
            }).encode())
            return

        if self.path == "/api/suggestions/add":
            token = str(body.get("token") or "").strip()
            text = str(body.get("text") or "").strip()
            user_key, user_info = auth_get_user_by_token(token)
            if not user_key or not isinstance(user_info, dict):
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Login required to submit suggestions"}).encode())
                return
            if not text:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Suggestion text is required"}).encode())
                return
            text = re.sub(r"\s+", " ", text)[:SUGGESTION_MAX_LENGTH]
            username = str(user_info.get("username") or "Anonymous").strip()
            global SUGGESTIONS_NEXT_ID
            with SUGGESTIONS_LOCK:
                if len(SUGGESTIONS_LIST) >= SUGGESTIONS_MAX:
                    # Remove oldest resolved ones first, then oldest unresolved
                    resolved = [s for s in SUGGESTIONS_LIST if s.get("resolved")]
                    if resolved:
                        SUGGESTIONS_LIST.remove(resolved[0])
                    else:
                        del SUGGESTIONS_LIST[0]
                entry = {
                    "id": SUGGESTIONS_NEXT_ID,
                    "username": username,
                    "text": text,
                    "ts": int(time.time()),
                    "resolved": False,
                    "resolved_by": "",
                    "resolved_ts": 0,
                }
                SUGGESTIONS_NEXT_ID += 1
                SUGGESTIONS_LIST.append(entry)
                snapshot = list(SUGGESTIONS_LIST)
            try:
                save_suggestions()
            except OSError:
                pass
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True, "suggestion": entry}).encode())
            return

        if self.path == "/api/suggestions/resolve":
            token = str(body.get("token") or "").strip()
            sid = int(body.get("id") or 0)
            user_key, user_info = auth_get_user_by_token(token)
            if not user_key or not auth_is_user_enabled(user_info):
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Login required"}).encode())
                return
            is_admin = auth_is_user_admin(user_info)
            username = str(user_info.get("username") or "anonymous").strip()
            with SUGGESTIONS_LOCK:
                target = next((s for s in SUGGESTIONS_LIST if s["id"] == sid), None)
                # Only admin or the suggestion's original author may resolve
                if target and (is_admin or target.get("username") == username):
                    target["resolved"] = not target.get("resolved", False)
                    if target["resolved"]:
                        target["resolved_by"] = username
                        target["resolved_ts"] = int(time.time())
                    else:
                        target["resolved_by"] = ""
                        target["resolved_ts"] = 0
                elif not target:
                    pass  # not found, no-op
                else:
                    self.send_response(403)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": "Not allowed"}).encode())
                    return
                snapshot = list(SUGGESTIONS_LIST)
            try:
                save_suggestions()
            except OSError:
                pass
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True, "suggestions": snapshot}).encode())
            return

        if self.path == "/api/suggestions/delete":
            token = str(body.get("token") or "").strip()
            sid = int(body.get("id") or 0)
            user_key, user_info = auth_get_user_by_token(token)
            if not user_key or not auth_is_user_enabled(user_info):
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Login required"}).encode())
                return
            is_admin = auth_is_user_admin(user_info)
            username = str(user_info.get("username") or "anonymous").strip()
            with SUGGESTIONS_LOCK:
                target = next((s for s in SUGGESTIONS_LIST if s["id"] == sid), None)
                if target and (is_admin or target.get("username") == username):
                    SUGGESTIONS_LIST[:] = [s for s in SUGGESTIONS_LIST if s["id"] != sid]
                elif not target:
                    pass  # not found, no-op
                else:
                    self.send_response(403)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": "Not allowed"}).encode())
                    return
                snapshot = list(SUGGESTIONS_LIST)
            try:
                save_suggestions()
            except OSError:
                pass
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True, "suggestions": snapshot}).encode())
            return

        if self.path == "/api/favorites/toggle":
            token = str(body.get("token") or "").strip()
            path = str(body.get("path") or "").strip()
            user_key, user_info = auth_get_user_by_token(token)
            if not user_key or not auth_is_user_enabled(user_info):
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Login required"}).encode())
                return
            if not path:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "path required"}).encode())
                return
            identity = normalize_resume_identity(str(user_info.get("username", user_key) or user_key))
            with FAVORITES_LOCK:
                current = list(FAVORITES_MAP.get(identity, []))
                if path in current:
                    current.remove(path)
                    favorited = False
                else:
                    current.append(path)
                    favorited = True
                FAVORITES_MAP[identity] = current
            try:
                save_favorites()
            except OSError:
                pass
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"paths": current, "favorited": favorited}).encode())
            return

        if self.path == "/api/remove_recent":
            token = str(body.get("token") or "").strip()
            path = str(body.get("path") or "").strip()
            user_key, user_info = auth_get_user_by_token(token)
            if not user_key or not auth_is_user_enabled(user_info):
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Login required"}).encode())
                return
            if not path:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "path required"}).encode())
                return
            identity = f"user:{user_key}"
            key = make_resume_map_key(path, identity)
            with FOLDER_RESUME_LOCK:
                FOLDER_RESUME_MAP.pop(key, None)
            save_folder_resume_map()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True}).encode())
            return

        if self.path == "/api/play_virtual_channel":
            # Virtual sub-channel: shuffle across multiple named media folders
            folders = body.get("folders")
            if not isinstance(folders, list) or not folders:
                self.send_error(400)
                return
            ip = self.client_address[0]
            files = []
            for folder_name in folders:
                folder_name = str(folder_name).strip()
                if not folder_name:
                    continue
                candidate = os.path.join(MEDIA_ROOT, folder_name)
                real_folder = os.path.realpath(candidate)
                if not real_folder.startswith(MEDIA_ROOT):
                    continue
                if not os.path.isdir(real_folder):
                    continue
                for root, _, names in os.walk(real_folder):
                    for n in names:
                        if n.lower().endswith((".mp4", ".mkv")):
                            files.append(os.path.join(root, n))
            if not files:
                self.send_error(404)
                return
            random.shuffle(files)
            first_file = files[0]
            duration_seconds = get_media_duration_seconds(first_file)
            shuffle_meta = {
                "shuffle_files": files,
                "shuffle_index": 0,
                "play_mode": "shuffle",
                "folder_key": "",
                "resume_identity": f"ip:{ip}",
            }
            playlist_path, slot = start_ffmpeg(
                [first_file],
                get_slot_for_ip(ip),
                ip,
                seek_seconds=0,
                duration_seconds=duration_seconds,
                session_meta=shuffle_meta,
            )
            display_title = build_display_title(first_file)
            queue_preview = build_shuffle_queue_preview(files, 0)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "playlist": f"/on_demand/{slot}/output.m3u8",
                "slot": slot,
                "display_title": display_title,
                "source_path": os.path.relpath(first_file, BASE_DIR),
                "duration_seconds": duration_seconds,
                "current_file": prettify_media_name(os.path.basename(first_file)),
                "episode_index": 1,
                "episode_total": len(files),
                "queue_preview": queue_preview,
                "play_mode": "shuffle",
                "resume_seek_seconds": 0,
            }).encode())
            return

        if self.path == "/api/chat/send":
            channel = str(body.get("channel", "")).strip()
            username = str(body.get("username", "")).strip() or "Anonymous"
            token = str(body.get("token") or "").strip()
            text = str(body.get("text", "")).strip()

            if not channel or not text:
                self.send_error(400)
                return

            user_key, user_info = auth_get_user_by_token(token)
            if not user_key or not isinstance(user_info, dict):
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Login required for chat"}).encode())
                return

            username = str(user_info.get("username") or username)

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
            requested_mode = str(body.get("play_mode") or "shuffle").strip().lower()
            play_mode = "chronological" if requested_mode == "chronological" else "shuffle"
            token = str(body.get("token") or "").strip()
            if play_mode == "chronological":
                user_key, _ = auth_get_user_by_token(token)
                if not user_key:
                    self.send_response(401)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": "Login required for chronological checkpoints"}).encode())
                    return
            files = sorted(files, key=natural_sort_key)
            if play_mode == "shuffle":
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
        start_index = 0
        resume_seek_seconds = 0.0
        if self.path == "/api/play_folder":
            folder_key = normalize_folder_key(real)
            user_key, _ = auth_get_user_by_token(token)
            resume_identity = f"user:{user_key}" if user_key else f"ip:{ip}"
            if play_mode == "chronological":
                resume_index = get_folder_resume_index(folder_key, resume_identity)
                if resume_index >= len(files):
                    resume_index = 0
                start_index = max(0, resume_index)
                resume_seek_seconds = get_folder_resume_seek_seconds(folder_key, resume_identity)
            stream_files = [files[start_index]]
            shuffle_meta = {
                "shuffle_files": files,
                "shuffle_index": start_index,
                "play_mode": play_mode,
                "folder_key": folder_key,
                "resume_identity": resume_identity,
            }
            if play_mode == "chronological":
                set_folder_resume_index(folder_key, start_index, resume_identity, seek_seconds=resume_seek_seconds)

        duration_seconds = get_media_duration_seconds(stream_files[0])
        # play_file can optionally start at a seek position (used by refresh restore)
        play_file_seek = 0.0
        if self.path == "/api/play_file":
            try:
                play_file_seek = max(0.0, float(body.get("seek_seconds", 0) or 0))
            except (TypeError, ValueError):
                pass
        playlist_path, slot = start_ffmpeg(
            stream_files,
            get_slot_for_ip(ip),
            ip,
            seek_seconds=resume_seek_seconds if self.path == "/api/play_folder" else play_file_seek,
            duration_seconds=duration_seconds,
            session_meta=shuffle_meta,
        )

        display_title = build_display_title(stream_files[0])

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        queue_preview = []
        if self.path == "/api/play_folder":
            queue_preview = build_shuffle_queue_preview(files, start_index)
        self.wfile.write(json.dumps({
            "playlist": f"/on_demand/{slot}/output.m3u8",
            "slot": slot,
            "display_title": display_title,
            "source_path": os.path.relpath(stream_files[0], BASE_DIR),
            "duration_seconds": duration_seconds,
            "current_file": prettify_media_name(os.path.basename(stream_files[0]), parent=os.path.basename(os.path.dirname(stream_files[0])), episode_index=get_file_index(stream_files[0])),
            "episode_index": start_index + 1,
            "episode_total": len(files) if self.path == "/api/play_folder" else 1,
            "queue_preview": queue_preview,
            "play_mode": play_mode if self.path == "/api/play_folder" else "single",
            "resume_seek_seconds": resume_seek_seconds if self.path == "/api/play_folder" else play_file_seek,
        }).encode())

if __name__ == "__main__":
    load_cookie_count()
    load_blunt_count()
    load_chat_history()
    load_folder_resume_map()
    load_suggestions()
    load_favorites()
    load_auth_db()
    load_snake_scores()
    # Re-sync global blunt count from per-user hits to fix any historical drift
    with AUTH_LOCK:
        _user_hit_total = sum(
            max(0, int(info.get("blunt_hits", 0) or 0))
            for info in AUTH_DB.get("users", {}).values()
            if isinstance(info, dict)
        )
    with BLUNT_LOCK:
        if BLUNT_COUNT != _user_hit_total:
            print(f"🔧 Syncing blunt count: {BLUNT_COUNT} → {_user_hit_total}")
            BLUNT_COUNT = _user_hit_total
            save_blunt_count()

    def _shutdown_handler(signum, frame):
        print("\n🛑 Shutting down — saving cookie count...")
        save_cookie_count()
        save_blunt_count()
        save_snake_scores()
        save_folder_resume_map()
        save_auth_db()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _shutdown_handler)
    signal.signal(signal.SIGINT, _shutdown_handler)
    atexit.register(save_cookie_count)
    atexit.register(save_blunt_count)
    atexit.register(save_snake_scores)
    atexit.register(save_folder_resume_map)
    atexit.register(save_auth_db)

    os.chdir(BASE_DIR)
    server = ThreadingHTTPServer(("0.0.0.0", 80), Handler)  # binds all interfaces
    print("🚀 Server running on http://0.0.0.0:80 (maxistreams.local)")
    server.serve_forever()
