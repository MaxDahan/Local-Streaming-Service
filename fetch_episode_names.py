#!/usr/bin/env python3
"""
fetch_episode_names.py
======================
Fetches correct episode names from TVMaze for every show in your media library
and writes a per-show  episode_names.json  sidecar (used by the server for
display names).  Optionally renames the actual .mp4 files to match.

JSON sidecar location:
    <media_root>/<ShowName>/episode_names.json

Usage:
    python3 fetch_episode_names.py                       # fetch/update all shows (dry-run)
    python3 fetch_episode_names.py "South Park"          # single show (dry-run)
    python3 fetch_episode_names.py --apply               # write JSON sidecars for all shows
    python3 fetch_episode_names.py --apply --rename      # write sidecars AND rename .mp4 files
    python3 fetch_episode_names.py "Rick and Morty" --apply --rename
    python3 fetch_episode_names.py --force               # re-fetch even if sidecar already exists

Flags:
    --apply     Write episode_names.json sidecar files (default: dry-run only)
    --rename    Also rename .mp4 files to match TVMaze titles (requires --apply)
    --force     Re-fetch TVMaze even if sidecar already exists
"""

import os
import sys
import re
import json
import time
import urllib.request
import urllib.parse
import urllib.error
import argparse

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _load_media_roots():
    config_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "src", "configurations", "config.json")
    try:
        with open(config_path) as f:
            cfg = json.load(f)
        roots = cfg.get("media_roots")
        if isinstance(roots, list) and roots:
            return [r for r in roots if isinstance(r, str) and r.strip()]
        legacy = cfg.get("media_root")
        if legacy and legacy != "null":
            base = os.path.dirname(os.path.realpath(__file__))
            return [legacy if os.path.isabs(legacy) else os.path.join(base, legacy)]
    except Exception:
        pass
    return [os.path.join(os.path.dirname(os.path.realpath(__file__)), "media", "converted")]

MEDIA_ROOTS = _load_media_roots()

# Same name overrides as fetch_covers.py
TVMAZE_OVERRIDES = {
    "12 oz. Mouse":                         "12 oz Mouse",
    "Aaahh Real Monsters":                  "Aaahh!!! Real Monsters",
    "A Pup Named Scooby-Doo":               "A Pup Named Scooby-Doo",
    "Be Cool Scooby-Doo":                   "Be Cool Scooby-Doo",
    "Bill and Teds Excellent Adventures":   "Bill & Ted's Excellent Adventures",
    "Bobs Burgers":                         "Bob's Burgers",
    "Codename Kids Next Door":              "Codename: Kids Next Door",
    "Dexters Laboratory":                   "Dexter's Laboratory",
    "Dragonball Z":                         "Dragon Ball Z",
    "DuckTales":                            "DuckTales",
    "Ed Edd n Eddy":                        "Ed, Edd n Eddy",
    "El Tigre":                             "El Tigre: The Adventures of Manny Rivera",
    "Fairly OddParents":                    "The Fairly OddParents",
    "Golden Boy":                           "Golden Boy",
    "He-Man":                               "He-Man and the Masters of the Universe",
    "Hey Arnold":                           "Hey Arnold!",
    "Home Movies":                          "Home Movies",
    "How Its Made":                         "How It's Made",
    "Its Always Sunny":                     "It's Always Sunny in Philadelphia",
    "Kung-Fu Panda":                        "Kung Fu Panda: Legends of Awesomeness",
    "Lobo":                                 "Lobo",
    "Mac Miller Show":                      "Mac Miller and the Most Dope Family",
    "MAD":                                  "MAD",
    "Max Headroom":                         "Max Headroom",
    "Midnight Gospel":                      "The Midnight Gospel",
    "Moral Orel":                           "Moral Orel",
    "Neon Genesis Evangelion":              "Neon Genesis Evangelion",
    "Ninjago":                              "Ninjago: Masters of Spinjitzu",
    "Rockos Modern Life":                   "Rocko's Modern Life",
    "Robot Chicken":                        "Robot Chicken",
    "Sailor Moon":                          "Sailor Moon",
    "Samurai Champloo":                     "Samurai Champloo",
    "Samurai Jack":                         "Samurai Jack",
    "Scooby Doo Mystery Incorporated":      "Scooby-Doo! Mystery Incorporated",
    "Scooby-Doo Where Are You":             "Scooby-Doo, Where Are You!",
    "Shivering Truth":                      "The Shivering Truth",
    "Solar Opposites":                      "Solar Opposites",
    "Space Dandy":                          "Space Dandy",
    "Space Ghost Coast To Coast":           "Space Ghost Coast to Coast",
    "Star Wars Clone Wars":                 "Star Wars: Clone Wars",
    "Star Wars The Clone Wars":             "Star Wars: The Clone Wars",
    "Star Wars Tales of the Jedi":          "Star Wars: Tales of the Jedi",
    "Star Wars Visions":                    "Star Wars: Visions",
    "The 13 Ghosts of Scooby-Doo":          "The 13 Ghosts of Scooby-Doo",
    "The Big Lez Show":                     "The Big Lez Show",
    "The Brak Show":                        "The Brak Show",
    "The Cleveland Show":                   "The Cleveland Show",
    "The Eric Andre Show":                  "The Eric Andre Show",
    "The Grim Adventures of Billy and Mandy": "The Grim Adventures of Billy & Mandy",
    "The Maxx":                             "The Maxx",
    "The New Adventures Of Superman":       "The New Adventures of Superman",
    "The New Scooby-Doo":                   "The New Scooby-Doo Movies",
    "The Oblongs":                          "The Oblongs",
    "The Whitest Kids U Know":              "The Whitest Kids U' Know",
    "Todd McFarlanes Spawn":                "Todd McFarlane's Spawn",
    "Trailer Park Boys The Animated Series": "Trailer Park Boys: The Animated Series",
    "Through The Wormhole":                 "Through the Wormhole",
    # YouTube / non-TV creators — no TVMaze entry
    "Brave Wilderness":                     None,
    "Brick Technology":                     None,
    "Faze":                                 None,
    "Kurzgesagt":                           None,
    "Liquid Television":                    None,
    "MetaNerdz Lore":                       None,
    "Primitive Unique Tool":                None,
    "The Stupendous Wave":                  None,
    "Toms Language Files":                  None,
    "Trippy Visuals":                       None,
    "Vintage Cartoons":                     None,
    "Vsauce":                               None,
    "You Laugh You Lose":                   None,
}

# Folders that are not TV shows — skip entirely
SKIP_FOLDERS = {
    "Movies", "Movies - 420", "Movies - Action", "Movies - Anime",
    "Movies - Comedy", "Movies - Crime", "Movies - Documentaries",
    "Movies - Horror", "Movies - Kids", "Movies - Sci-Fi", "Movies - Western",
    "Music-Videos", "Trailers",
}

RATE_LIMIT_DELAY = 0.25   # seconds between TVMaze requests

# Direct TVMaze ID overrides — bypasses search entirely for shows where
# singlesearch returns the wrong entry (wrong season count, wrong version, etc.)
TVMAZE_ID_OVERRIDES = {
    "Avatar The Last Airbender": 555,   # singlesearch returns 38753 (2024 Netflix version); 555 = original 2005 Nickelodeon show
}

# Characters not allowed in filenames
_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*]')

def sanitize(name):
    """Strip characters forbidden in filenames, trim trailing dots/spaces."""
    return _UNSAFE_CHARS.sub("", name).strip(" .")


# ---------------------------------------------------------------------------
# TVMaze helpers
# ---------------------------------------------------------------------------

def tvmaze_search_show(query):
    """Return (tvmaze_id, show_name) from TVMaze for query, or (None, None)."""
    url = "https://api.tvmaze.com/singlesearch/shows?q=" + urllib.parse.quote(query)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return data["id"], data["name"]
    except urllib.error.HTTPError as e:
        if e.code != 404:
            print(f"  TVMaze HTTP error ({e.code}) for '{query}'")
    except Exception as e:
        print(f"  TVMaze error for '{query}': {e}")
    return None, None


def tvmaze_get_episodes(tvmaze_id):
    """Return list of episode dicts from TVMaze for a show id."""
    url = f"https://api.tvmaze.com/shows/{tvmaze_id}/episodes"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"  TVMaze episodes error: {e}")
    return []


# ---------------------------------------------------------------------------
# Filename parsing
# ---------------------------------------------------------------------------

# Patterns to detect SxxExx in filenames
SXXEXX_RE = re.compile(r"[Ss](\d{1,2})[Ee](\d{1,3})")
# Fallback: standalone Exx (no season prefix) — only if SXXEXX_RE didn't match
EXX_RE    = re.compile(r"\bE(\d{1,3})\b", re.IGNORECASE)

# Detects episode titles of the form "Book X: Y - Chapter Z: W" (Avatar, etc.)
# The part before " - " becomes a season label; the part after is the real episode title.
_BOOK_CHAPTER_RE = re.compile(r'^(.+?)\s+-\s+((?:Chapter|Part)\s+.+)$', re.IGNORECASE)

def _split_book_chapter(title):
    """Return (book_label, chapter_title) if the TVMaze title follows the
    'Book X: Y - Chapter Z: W' pattern, otherwise return (None, title)."""
    m = _BOOK_CHAPTER_RE.match(title)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return None, title


def parse_season_episode(filename):
    """Return (season, episode) as ints from filename, or (None, None).
    Season may be None for flat Exx files.
    """
    m = SXXEXX_RE.search(filename)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = EXX_RE.search(filename)
    if m:
        return None, int(m.group(1))   # flat episode, assume season 1
    return None, None


def collect_video_files(show_folder):
    """Return sorted list of .mp4 filenames (relative) from the show folder tree."""
    videos = []
    for root, dirs, files in os.walk(show_folder):
        dirs.sort()
        for fname in sorted(files):
            if fname.lower().endswith(".mp4"):
                rel = os.path.relpath(os.path.join(root, fname), show_folder)
                videos.append(rel)
    return videos


# ---------------------------------------------------------------------------
# Core processing
# ---------------------------------------------------------------------------

def process_show(show_name, show_folder, force=False, apply=False, rename=False):
    out_path = os.path.join(show_folder, "episode_names.json")

    if show_name in SKIP_FOLDERS:
        print(f"  ⏭  Skipped (not a TV show folder)")
        return "skipped"

    # Check override — None means explicitly skip
    if show_name in TVMAZE_OVERRIDES and TVMAZE_OVERRIDES[show_name] is None:
        print(f"  ⏭  Skipped (non-TV folder, no TVMaze entry expected)")
        return "skipped"

    if os.path.exists(out_path) and not force:
        print(f"  ⏭  Skipped (episode_names.json exists; use --force to re-fetch)")
        return "skipped"

    # Find on TVMaze — check direct ID override first, then fall back to search
    if show_name in TVMAZE_ID_OVERRIDES:
        tvmaze_id = TVMAZE_ID_OVERRIDES[show_name]
        url = f"https://api.tvmaze.com/shows/{tvmaze_id}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                tvmaze_name = data.get("name", str(tvmaze_id))
        except Exception as e:
            print(f"  ❌ Could not fetch TVMaze ID {tvmaze_id}: {e}")
            return "failed"
        time.sleep(RATE_LIMIT_DELAY)
    else:
        query = TVMAZE_OVERRIDES.get(show_name, show_name)
        tvmaze_id, tvmaze_name = tvmaze_search_show(query)
        time.sleep(RATE_LIMIT_DELAY)
        if tvmaze_id is None:
            print(f"  ❌ Not found on TVMaze (query: '{query}')")
            return "failed"

    print(f"  Found: '{tvmaze_name}' (ID {tvmaze_id})")

    # Fetch all episodes
    episodes = tvmaze_get_episodes(tvmaze_id)
    time.sleep(RATE_LIMIT_DELAY)

    if not episodes:
        print(f"  ❌ No episodes returned from TVMaze")
        return "failed"

    # Build seasons dict
    seasons = {}
    for ep in episodes:
        s = str(ep.get("season", "?"))
        e = str(ep.get("number", "?"))
        title = ep.get("name") or ""
        if s not in seasons:
            seasons[s] = {}
        seasons[s][e] = title

    # Detect season labels (e.g. "Book One: Water" for Avatar season 1).
    # If every episode in a season shares a common book-style prefix, record it.
    season_labels = {}
    for s_num, eps in seasons.items():
        prefixes = set()
        for ep_title in eps.values():
            if ep_title:
                prefix, _ = _split_book_chapter(ep_title)
                if prefix:
                    prefixes.add(prefix)
        if len(prefixes) == 1 and len(eps) > 0:
            season_labels[s_num] = prefixes.pop()

    # Match local video files → episode titles
    video_files = collect_video_files(show_folder)
    files_map = {}
    unmatched = []
    for rel_path in video_files:
        fname = os.path.basename(rel_path)
        s, e = parse_season_episode(fname)
        if e is not None:
            # season defaults to 1 for flat Exx files
            effective_s = s if s is not None else 1
            title = (seasons.get(str(effective_s), {}) or {}).get(str(e))
            if title:
                # Strip book prefix (e.g. "Book One: Water - ") → keep only the chapter part
                _, chapter_title = _split_book_chapter(title)
                files_map[rel_path] = chapter_title
            else:
                files_map[rel_path] = None
                unmatched.append(rel_path)
        else:
            files_map[rel_path] = None       # no episode tag in name
            unmatched.append(rel_path)

    matched = sum(1 for v in files_map.values() if v is not None)
    total   = len(files_map)
    print(f"  Seasons: {len(seasons)}  |  Episodes in DB: {sum(len(v) for v in seasons.values())}")
    print(f"  Local files: {total}  |  Matched: {matched}  |  Unmatched: {total - matched}")

    if unmatched:
        for f in unmatched[:5]:
            print(f"    ⚠  {f}")
        if len(unmatched) > 5:
            print(f"    ... and {len(unmatched) - 5} more")

    result = {
        "show": show_name,
        "tvmaze_id": tvmaze_id,
        "tvmaze_name": tvmaze_name,
        "seasons": seasons,
        "season_labels": season_labels,
        "files": files_map,
    }

    if not apply:
        print(f"  🔍 Dry-run: would write {out_path}")
        if rename:
            _preview_renames(show_folder, files_map)
    else:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"  ✅ Wrote {out_path}")
        if rename:
            _apply_renames(show_folder, files_map)

    return "ok"


def _build_rename_pairs(show_folder, files_map):
    """Yield (old_path, new_path) for files that need renaming."""
    for rel_path, display_name in files_map.items():
        if not display_name:
            continue
        old_path = os.path.join(show_folder, rel_path)
        if not os.path.exists(old_path):
            continue
        new_name = sanitize(display_name) + ".mp4"
        new_path = os.path.join(os.path.dirname(old_path), new_name)
        if old_path != new_path:
            yield old_path, new_path


def _preview_renames(show_folder, files_map):
    pairs = list(_build_rename_pairs(show_folder, files_map))
    if not pairs:
        return
    print(f"  📄 Would rename {len(pairs)} file(s):")
    for old, new in pairs[:5]:
        print(f"      {os.path.basename(old)}")
        print(f"    → {os.path.basename(new)}")
    if len(pairs) > 5:
        print(f"    ... and {len(pairs) - 5} more")


def _apply_renames(show_folder, files_map):
    pairs = list(_build_rename_pairs(show_folder, files_map))
    renamed = 0
    for old, new in pairs:
        if os.path.exists(new):
            print(f"  ⚠  SKIP (target exists): {os.path.basename(new)}")
            continue
        try:
            os.rename(old, new)
            print(f"  ✅ Renamed: {os.path.basename(old)} → {os.path.basename(new)}")
            renamed += 1
        except Exception as exc:
            print(f"  ❌ Error renaming {os.path.basename(old)}: {exc}")
    if renamed:
        print(f"  Renamed {renamed}/{len(pairs)} files.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Fetch episode names from TVMaze for all shows.")
    parser.add_argument("show", nargs="?", help="Optional: name of a single show folder to process")
    parser.add_argument("--apply",  action="store_true", help="Write episode_names.json sidecar files (default: dry-run)")
    parser.add_argument("--rename", action="store_true", help="Also rename .mp4 files to match TVMaze titles (requires --apply)")
    parser.add_argument("--force",  action="store_true", help="Re-fetch even if episode_names.json exists")
    args = parser.parse_args()

    if not args.apply:
        print("🔍 DRY-RUN MODE — no files will be written or renamed. Pass --apply to commit.\n")
    elif args.rename:
        print("⚠️  APPLY + RENAME MODE — JSON sidecars WILL be written and .mp4 files WILL be renamed.\n")
    else:
        print("⚠️  APPLY MODE — JSON sidecars WILL be written.\n")

    # Collect shows
    seen = set()
    all_shows = []
    for media_root in MEDIA_ROOTS:
        if not os.path.isdir(media_root):
            print(f"Warning: media root not found: {media_root}")
            continue
        for name in sorted(os.listdir(media_root)):
            if name.startswith(".") or name in seen:
                continue
            folder = os.path.join(media_root, name)
            if not os.path.isdir(folder):
                continue
            seen.add(name)
            all_shows.append((name, folder))

    all_shows.sort(key=lambda x: x[0].lower())

    # Filter to single show if requested
    if args.show:
        all_shows = [(n, f) for n, f in all_shows if n.lower() == args.show.lower()]
        if not all_shows:
            print(f"Show '{args.show}' not found in media roots.")
            sys.exit(1)

    print(f"Processing {len(all_shows)} show folder(s)...\n")

    counters = {"ok": 0, "skipped": 0, "failed": 0}

    for show_name, show_folder in all_shows:
        print(f"[{show_name}]")
        result = process_show(show_name, show_folder, force=args.force, apply=args.apply, rename=args.rename)
        counters[result] = counters.get(result, 0) + 1

    print("\n" + "=" * 50)
    print(f"✅ Written:  {counters['ok']}")
    print(f"⏭  Skipped: {counters['skipped']}")
    print(f"❌ Failed:  {counters['failed']}")


if __name__ == "__main__":
    main()
