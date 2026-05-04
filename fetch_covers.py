#!/usr/bin/env python3
"""
Download cover art for show folders missing a cover image.
Uses TVMaze API (free, no key) as primary source.
"""

import os
import sys
import time
import json
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


def download_image(url, dest_path):
    """Download an image from url to dest_path. Returns True on success."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
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
    except Exception as e:
        print(f"  Download error from {url}: {e}")
    return False


def main():
    # Collect all show folders across all media roots
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
        if not get_existing_cover(folder):
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
    print(f"✅ Success: {success} / {len(missing)}")
    if failed:
        print(f"❌ Failed ({len(failed)}):")
        for f in failed:
            print(f"   - {f}")


if __name__ == "__main__":
    main()
