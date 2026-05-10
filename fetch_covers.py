#!/usr/bin/env python3
"""
Download cover art for show folders and individual movie files missing a cover image.

Shows:  Uses TVMaze API (free, no key needed).
Movies: Uses Wikipedia PageImages API (free, no key needed).
        Covers are saved as sidecar images next to each .mp4 file, or as
        cover.jpg inside movie subfolders.

Usage:
    python3 fetch_covers.py              # shows + movies
    python3 fetch_covers.py --shows      # shows only
    python3 fetch_covers.py --movies     # movies only
    python3 fetch_covers.py --force      # re-download even if cover exists
"""

import os
import sys
import time
import json
import re
import argparse
import urllib.request
import urllib.parse
import urllib.error

import json as _json

def _load_media_roots():
    config_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "src", "configurations", "config.json")
    try:
        with open(config_path) as _f:
            cfg = _json.load(_f)
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
CONVERTED_DIR = MEDIA_ROOTS[0]  # primary root for backward-compat

# Movie genre folders (case-insensitive match on folder name)
MOVIE_GENRE_FOLDERS = {
    "movies", "movies - 420", "movies - action", "movies - anime",
    "movies - comedy", "movies - crime", "movies - documentaries",
    "movies - horror", "movies - kids", "movies - sci-fi", "movies - western",
    "trailers",
}

# Regex to extract title and optional year from filenames and folder names:
#   "Movie - Title (Year).mp4"  or  "YYYY - Title"  or  "YYYY Title"
MOVIE_NAME_RE = re.compile(
    r'^(?:Movie\s*[-\u2013]\s*)?(.*?)\s*(?:\((\d{4})\))?\s*$',
    re.IGNORECASE,
)
# Leading-year folder names: "1993 - Super Mario Bros" or "2017 War for ..."
FOLDER_YEAR_RE = re.compile(r'^(\d{4})\s*[-\u2013]?\s*(.+)$')

# Shows that won't be on TVMaze — map to a direct search query or skip
TVMAZE_OVERRIDES = {
    "12 oz. Mouse":                    "12 oz Mouse",
    "Aaahh Real Monsters":             "Aaahh!!! Real Monsters",
    "A Pup Named Scooby-Doo":          "A Pup Named Scooby-Doo",
    "Be Cool Scooby-Doo":              "Be Cool Scooby-Doo",
    "Bill and Teds Excellent Adventures": "Bill & Ted's Excellent Adventures",
    "Bobs Burgers":                    "Bob's Burgers",
    "Codename Kids Next Door":         "Codename: Kids Next Door",
    "Dexters Laboratory":              "Dexter's Laboratory",
    "Dragonball Z":                    "Dragon Ball Z",
    "DuckTales":                       "DuckTales",
    "Ed Edd n Eddy":                   "Ed, Edd n Eddy",
    "El Tigre":                        "El Tigre: The Adventures of Manny Rivera",
    "Fairly OddParents":               "The Fairly OddParents",
    "Golden Boy":                      "Golden Boy",
    "He-Man":                          "He-Man and the Masters of the Universe",
    "Hey Arnold":                      "Hey Arnold!",
    "Home Movies":                     "Home Movies",
    "How Its Made":                    "How It's Made",
    "Kung-Fu Panda":                   "Kung Fu Panda: Legends of Awesomeness",
    "Liquid Television":               "Liquid Television",
    "Lobo":                            "Lobo",
    "Mac Miller Show":                 "The Mac Miller Judging You Show",
    "MAD":                             "MAD",
    "Max Headroom":                    "Max Headroom",
    "Midnight Gospel":                 "The Midnight Gospel",
    "Moral Orel":                      "Moral Orel",
    "Neon Genesis Evangelion":         "Neon Genesis Evangelion",
    "Ninjago":                         "Ninjago: Masters of Spinjitzu",
    "Robot Chicken":                   "Robot Chicken",
    "Sailor Moon":                     "Sailor Moon",
    "Samurai Champloo":                "Samurai Champloo",
    "Samurai Jack":                    "Samurai Jack",
    "Shivering Truth":                 "The Shivering Truth",
    "Solar Opposites":                 "Solar Opposites",
    "Space Ghost Coast To Coast":      "Space Ghost Coast to Coast",
    "The Big Lez Show":                "The Big Lez Show",
    "The Brak Show":                   "The Brak Show",
    "The Cleveland Show":              "The Cleveland Show",
    "The Maxx":                        "The Maxx",
    "The Oblongs":                     "The Oblongs",
    "Todd McFarlanes Spawn":           "Todd McFarlane's Spawn",
    "Trailer Park Boys The Animated Series": "Trailer Park Boys: The Animated Series",
}

# Folders that are categories, not shows — skip TVMaze and use a static image or skip
SKIP_TVMAZE = {"Movies", "Music-Videos", "Trailers", "Trippy Visuals", "Vintage Cartoons"}

# For category folders, try these Wikipedia/common image URLs (or set to None to skip)
DIRECT_URLS = {
    "Movies":         None,
    "Music-Videos":   None,
    "Trailers":       None,
    "Trippy Visuals": None,
    "Vintage Cartoons": None,
}


def tmdb_search(title, year=None, api_key=None):
    # Kept as stub for backward compat — Wikipedia is now the default.
    return wikipedia_movie_image(title, year=year)


_WIKI_UA = "FetchCovers/1.0 (maxistreams-private-server; python3)"
# Terms that indicate a Wikipedia page is NOT a movie
_NON_FILM_TERMS = frozenset([
    "soundtrack", "score", "album", "discography", "book", "novel",
    "video game", "game", "franchise", "series", "television", "tv series",
    "logo", "svg",
])


def wikipedia_movie_image(title, year=None, _retry=0):
    """Return a poster/image URL for a movie using Wikipedia REST API.

    Step 1: /w/rest.php/v1/search/page  — lightweight, finds page key + description
    Step 2: /api/rest_v1/page/summary/{key} — returns main page thumbnail
    Two requests total, much lighter than action=query pageimages.
    """
    query = f"{title} {year} film" if year else f"{title} film"
    search_url = "https://en.wikipedia.org/w/rest.php/v1/search/page?" + urllib.parse.urlencode({
        "q": query, "limit": 5,
    })
    try:
        req = urllib.request.Request(search_url, headers={"User-Agent": _WIKI_UA})
        with urllib.request.urlopen(req, timeout=15) as resp:
            candidates = json.loads(resp.read()).get("pages", [])

        if not candidates:
            return None

        # Prefer pages whose description mentions "film" or matches the year
        def score(page):
            desc  = (page.get("description") or "").lower()
            ptitle = (page.get("title") or "").lower()
            # Penalise non-film pages heavily
            if any(t in ptitle for t in _NON_FILM_TERMS): return -10
            if any(t in desc  for t in _NON_FILM_TERMS): return -5
            s = 0
            if "film" in desc: s += 3
            if year and year in desc: s += 2
            if "animated" in desc: s += 1
            return s

        candidates.sort(key=score, reverse=True)

        for page in candidates[:3]:
            key = urllib.parse.quote(page["key"], safe="")
            surl = f"https://en.wikipedia.org/api/rest_v1/page/summary/{key}"
            req2 = urllib.request.Request(surl, headers={"User-Agent": _WIKI_UA})
            with urllib.request.urlopen(req2, timeout=15) as resp2:
                data = json.loads(resp2.read())
            thumb = data.get("thumbnail") or data.get("originalimage")
            if thumb:
                src = thumb.get("source", "")
                if src:
                    src = re.sub(r'/(\d+)px-', '/500px-', src)
                    return src

        return None

    except urllib.error.HTTPError as e:
        if e.code == 429 and _retry < 3:
            wait = 20 * (2 ** _retry)
            print(f"  Rate-limited (429), waiting {wait}s...")
            time.sleep(wait)
            return wikipedia_movie_image(title, year=year, _retry=_retry + 1)
        print(f"  Wikipedia error for '{title}': HTTP {e.code}")
    except Exception as e:
        print(f"  Wikipedia error for '{title}': {e}")
    return None


def get_existing_cover(folder):
    for fname in os.listdir(folder):
        if fname.lower().startswith("cover."):
            return os.path.join(folder, fname)
    return None


def tvmaze_search(query):
    """Return the original image URL from TVMaze for a show query, or None."""
    url = "https://api.tvmaze.com/singlesearch/shows?q=" + urllib.parse.quote(query)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            img = data.get("image")
            if img:
                return img.get("original") or img.get("medium")
    except Exception as e:
        print(f"  TVMaze error for '{query}': {e}")
    return None


def download_image(url, dest_path, _retry=0):
    """Download an image from url to dest_path. Returns final path on success."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _WIKI_UA})
        with urllib.request.urlopen(req, timeout=20) as resp:
            content = resp.read()
            content_type = resp.headers.get("Content-Type", "")
        if not content:
            return False
        # Determine extension from content-type or URL
        if "jpeg" in content_type or "jpg" in content_type:
            ext = ".jpg"
        elif "png" in content_type:
            ext = ".png"
        elif "webp" in content_type:
            ext = ".webp"
        elif url.lower().endswith(".png"):
            ext = ".png"
        elif url.lower().endswith(".webp"):
            ext = ".webp"
        else:
            ext = ".jpg"
        final_path = dest_path + ext
        with open(final_path, "wb") as f:
            f.write(content)
        return final_path
    except urllib.error.HTTPError as e:
        if e.code == 429 and _retry < 3:
            wait = 30 * (2 ** _retry)
            print(f"  Image CDN rate-limited, waiting {wait}s...")
            time.sleep(wait)
            return download_image(url, dest_path, _retry=_retry + 1)
        print(f"  Download error from {url}: {e}")
    except Exception as e:
        print(f"  Download error from {url}: {e}")
    return False


def main():
    parser = argparse.ArgumentParser(description="Fetch cover art for shows and movies.")
    parser.add_argument("--shows",  action="store_true", help="Only process show folders")
    parser.add_argument("--movies", action="store_true", help="Only process movie files/folders")
    parser.add_argument("--force",  action="store_true", help="Re-download even if cover already exists")
    args = parser.parse_args()
    do_shows  = not args.movies  # default: do both
    do_movies = not args.shows   # default: do both
    # ── Shows section ────────────────────────────────────────────────────────
    if do_shows:
        seen = set()
        all_shows = []
        for media_root in MEDIA_ROOTS:
            if not os.path.isdir(media_root):
                continue
            for show in sorted(os.listdir(media_root)):
                if show in seen:
                    continue
                seen.add(show)
                all_shows.append((show, media_root))
        all_shows.sort(key=lambda x: x[0])

        missing = []
        for show, media_root in all_shows:
            folder = os.path.join(media_root, show)
            if not os.path.isdir(folder):
                continue
            if show.lower() in MOVIE_GENRE_FOLDERS:
                continue  # movie genre folders handled separately
            if not args.force and get_existing_cover(folder):
                continue
            missing.append((show, media_root))

        print(f"Found {len(missing)} shows missing cover art.\n")

        success = 0
        failed = []

        for show, media_root in missing:
            folder = os.path.join(media_root, show)
            dest_base = os.path.join(folder, "cover")

            print(f"[{show}]")

            # Check if it's a category folder
            if show in SKIP_TVMAZE:
                direct = DIRECT_URLS.get(show)
                if direct:
                    result = download_image(direct, dest_base)
                    if result:
                        print(f"  ✅ Downloaded from direct URL -> {os.path.basename(result)}")
                        success += 1
                        continue
                print(f"  ⏭  Skipped (category folder, no direct URL set)")
                failed.append(show)
                continue

            # Look up on TVMaze
            query = TVMAZE_OVERRIDES.get(show, show)
            img_url = tvmaze_search(query)

            if not img_url:
                print(f"  ❌ Not found on TVMaze (query: '{query}')")
                failed.append(show)
                time.sleep(0.5)
                continue

            result = download_image(img_url, dest_base)
            if result:
                print(f"  ✅ {os.path.basename(result)}  ({img_url})")
                success += 1
            else:
                print(f"  ❌ Download failed: {img_url}")
                failed.append(show)

            time.sleep(0.3)  # be polite to the API

        print(f"\n{'='*50}")
        print(f"✅ Shows success: {success} / {len(missing)}")
        if failed:
            print(f"❌ Failed ({len(failed)}):")
            for f in failed:
                print(f"   - {f}")

    # ── Movies section ───────────────────────────────────────────────────────
    if do_movies:
        print(f"\n{'='*50}")
        print("Scanning movie folders and files...\n")
        # Each entry: (dest_base_path, title, year)
        # dest_base_path: stem for flat files, or folder/cover for subfolders
        movie_missing = []
        for media_root in MEDIA_ROOTS:
            if not os.path.isdir(media_root):
                continue
            for folder_name in sorted(os.listdir(media_root)):
                if folder_name.lower() not in MOVIE_GENRE_FOLDERS:
                    continue
                genre_folder = os.path.join(media_root, folder_name)
                if not os.path.isdir(genre_folder):
                    continue
                for entry in sorted(os.listdir(genre_folder)):
                    entry_path = os.path.join(genre_folder, entry)
                    if os.path.isdir(entry_path):
                        # Movie subfolder (e.g. "Movies/1993 - Super Mario Bros/")
                        dest_base = os.path.join(entry_path, "cover")
                        if not args.force and any(os.path.isfile(os.path.join(entry_path, f"cover{e}") ) for e in (".jpg", ".jpeg", ".png", ".webp")):
                            continue
                        fm = FOLDER_YEAR_RE.match(entry)
                        if fm:
                            year, title = fm.group(1), fm.group(2).strip()
                        else:
                            year, title = None, entry
                        movie_missing.append((dest_base, title, year))
                    elif entry.lower().endswith(".mp4"):
                        # Flat .mp4 file (e.g. "Movies - Action/Die Hard (1988).mp4")
                        stem = os.path.splitext(entry_path)[0]
                        if not args.force and any(os.path.isfile(stem + e) for e in (".jpg", ".jpeg", ".png", ".webp")):
                            continue
                        fm = MOVIE_NAME_RE.match(os.path.splitext(entry)[0])
                        if fm:
                            title = fm.group(1).strip()
                            year  = fm.group(2) or None
                        else:
                            title = os.path.splitext(entry)[0]
                            year  = None
                        movie_missing.append((stem, title, year))

        print(f"Found {len(movie_missing)} movies missing cover art.\n")
        m_success = 0
        m_failed  = []
        for dest_base, title, year in movie_missing:
            print(f"[{title}{' (' + year + ')' if year else ''}]")
            poster_url = wikipedia_movie_image(title, year=year)
            if not poster_url:
                print(f"  ❌ Not found on Wikipedia")
                m_failed.append(title)
                time.sleep(0.5)
                continue
            result = download_image(poster_url, dest_base)
            if result:
                print(f"  ✅ {os.path.basename(result)}")
                m_success += 1
            else:
                print(f"  ❌ Download failed")
                m_failed.append(title)
            time.sleep(0.5)

        print(f"\n{'='*50}")
        print(f"✅ Movies success: {m_success} / {len(movie_missing)}")
        if m_failed:
            print(f"❌ Failed ({len(m_failed)}):")
            for f in m_failed:
                print(f"   - {f}")


if __name__ == "__main__":
    main()
