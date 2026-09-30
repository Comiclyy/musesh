"""Download whole albums from a plain-text list (see ~/Documents/musesh-albums.txt).

Each line is resolved to Apple Music albums with the public iTunes Search API,
shown for review, then downloaded with gamdl into the same library folder that
library_dl.py uses. Finished albums are remembered, so the list can keep growing.

Run it with the Python inside gamdl's environment (musesh does this for you).
"""

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

import httpx

import library_dl as L
from ui import prompt as tty_input

ITUNES_LOOKUP_URL = "https://itunes.apple.com/lookup"
MB_PER_TRACK = 8  # 256 kbps AAC, ~4 minute song
EDITION_WORDS = re.compile(
    r"\b(remaster(ed)?|deluxe|expanded|edition|anniversary|bonus|version|mono|stereo|reissue)\b", re.I)


def base_album(name):
    """'Loveless (Remastered) - EP' -> 'loveless'. Used to compare and de-duplicate editions."""
    name = re.sub(r"\s+-\s+(EP|Single)$", "", name or "")
    return L.norm(re.sub(r"[\(\[].*?[\)\]]", "", name)) or L.norm(name)


def is_edition(name):
    return bool(EDITION_WORDS.search(name or ""))


def parse_list(path):
    entries = []
    for raw in Path(path).read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("https://"):
            entries.append({"line": line, "url": line})
            continue
        if " - " not in line:
            print(f"  skipping (expected 'Artist - Album'): {line}")
            continue
        artist, album = (s.strip() for s in line.split(" - ", 1))
        eps = album.endswith("+eps")
        album = album.removesuffix("+eps").strip()
        entries.append({"line": line, "artist": artist, "album": album, "all": album == "*", "eps": eps})
    return entries


def album_info(r, storefront):
    return {
        "id": str(r["collectionId"]),
        "name": r["collectionName"],
        "artist": r["artistName"],
        "year": (r.get("releaseDate") or "")[:4],
        "tracks": r.get("trackCount") or 0,
        "url": f"https://music.apple.com/{storefront}/album/{r['collectionId']}",
    }


def artist_key(name):
    """'The Jesus & Mary Chain' and 'The Jesus and Mary Chain' compare equal."""
    return L.norm(re.sub(r"\s*&\s*", " and ", name or ""))


def edition_rank(name, tracks, date):
    """Lower is better: the plain album first, then the shortest edition (not the 44-track deluxe), then the earliest."""
    return (is_edition(name), tracks or 0, date or "")


async def find_artist(api, artist):
    """Apple Music artist ID for a name. Search ranks by popularity, so an exact-name
    match near the top is the well-known act (Placebo the band, not a 1970s namesake)."""
    found = await itunes_get(L.ITUNES_SEARCH_URL, {"term": artist, "entity": "musicArtist",
                                                   "limit": 10, "country": api.storefront})
    exact = [a for a in found if artist_key(a.get("artistName")) == artist_key(artist)]
    return str((exact or found)[0]["artistId"]) if (exact or found) else None


async def find_album(api, artist, album):
    """'Artist - Album': pick the album from that artist's own catalog, preferring the plain edition."""
    artist_id = await find_artist(api, artist)
    if not artist_id:
        return []
    rows = await itunes_get(ITUNES_LOOKUP_URL, {"id": artist_id, "entity": "album", "limit": 200,
                                                "country": api.storefront})
    want, want_base = L.norm(album), base_album(album)
    candidates = [r for r in rows if r.get("wrapperType") == "collection"
                  and (L.norm(r.get("collectionName")) == want or base_album(r.get("collectionName")) == want_base)]
    if not candidates:
        return []
    best = min(candidates, key=lambda r: (is_edition(r["collectionName"]), L.norm(r["collectionName"]) != want,
                                          r.get("trackCount") or 0, r.get("releaseDate") or ""))
    return [album_info(best, api.storefront)]


async def find_discography(api, artist, eps):
    """Every studio album (and optionally EP) by an artist, as listed in Apple Music's
    own "Albums" section - which leaves out live albums, compilations and box sets."""
    artist_id = await find_artist(api, artist)
    if not artist_id:
        return []
    data = (await api.get_artist(artist_id, include="albums", views="full-albums,singles"))["data"][0]
    views = data.get("views", {})
    items = list(views.get("full-albums", {}).get("data", []))
    if eps:
        items += [a for a in views.get("singles", {}).get("data", [])
                  if a["attributes"]["name"].endswith(" - EP")]
    by_base = {}
    for a in items:
        at = a["attributes"]
        key = base_album(at["name"])
        rank = edition_rank(at["name"], at.get("trackCount"), at.get("releaseDate"))
        if key not in by_base or rank < by_base[key][0]:
            by_base[key] = (rank, {
                "id": a["id"], "name": at["name"], "artist": at.get("artistName", artist),
                "year": (at.get("releaseDate") or "")[:4], "tracks": at.get("trackCount") or 0,
                "url": f"https://music.apple.com/{api.storefront}/album/{a['id']}",
            })
    return sorted((v for _, v in by_base.values()), key=lambda a: a["year"])


async def itunes_get(url, params):
    """GET the iTunes API with the same pacing/backoff as library_dl's search."""
    for delay in (30, 60, 120):
        wait = L._last_itunes_request + L.ITUNES_MIN_INTERVAL - L.time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        L._last_itunes_request = L.time.monotonic()
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, params=params)
        if resp.status_code in (403, 429):
            await asyncio.sleep(delay)
            continue
        resp.raise_for_status()
        return resp.json().get("results", [])
    raise RuntimeError("iTunes API still rate limited after retries")


async def resolve(entries, api, cache_path):
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    for i, e in enumerate(entries, 1):
        if e["line"] in cache:
            e["albums"] = cache[e["line"]]
            continue
        print(f"  looking up {i}/{len(entries)}: {e['line']}", flush=True)
        if "url" in e:
            album_id = e["url"].split("?")[0].rstrip("/").rsplit("/", 1)[-1]
            rows = await itunes_get(ITUNES_LOOKUP_URL, {"id": album_id, "country": api.storefront})
            found = [r for r in rows if r.get("wrapperType") == "collection"]
            e["albums"] = [album_info(found[0], api.storefront) if found else
                           {"id": album_id, "name": e["url"], "artist": "", "year": "", "tracks": 0, "url": e["url"]}]
        elif e["all"]:
            e["albums"] = await find_discography(api, e["artist"], e["eps"])
        else:
            e["albums"] = await find_album(api, e["artist"], e["album"])
        if e["albums"]:
            cache[e["line"]] = e["albums"]
            cache_path.write_text(json.dumps(cache, indent=1))


def show(entries, progress):
    total_tracks = 0
    for e in entries:
        if not e["albums"]:
            print(f"\n  NOT FOUND  {e['line']}")
            continue
        print(f"\n  {e['line']}")
        for a in e["albums"]:
            done = " (already downloaded)" if a["url"] in progress.done else ""
            print(f"      {a['year'] or '    '}  {a['name']}  [{a['tracks'] or '?'} tracks]{done}")
            if not done:
                total_tracks += a["tracks"]
    return total_tracks


async def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("list", type=Path, help="album list file")
    p.add_argument("-o", "--output", type=Path, required=True, help="library folder")
    p.add_argument("-c", "--cookies", type=Path, required=True, help="Apple Music cookies.txt")
    p.add_argument("--refresh", action="store_true", help="look everything up again instead of using saved matches")
    p.add_argument("-y", "--yes", action="store_true", help="don't ask before downloading")
    p.add_argument("--review-only", action="store_true", help="look up and show the list, don't download")
    args = p.parse_args()

    out_dir = args.output.expanduser().resolve()
    state_dir = out_dir / L.STATE_DIR
    state_dir.mkdir(parents=True, exist_ok=True)
    cache_path = state_dir / "albums.json"
    if args.refresh:
        cache_path.unlink(missing_ok=True)

    cookies = args.cookies.expanduser().resolve()
    api = await L.login(cookies)  # needed for artists' "Albums" sections, and for downloading
    entries = parse_list(args.list.expanduser())
    print(f"Looking up {len(entries)} lines from {args.list}...")
    await resolve(entries, api, cache_path)

    progress = L.Progress(state_dir)
    tracks = show(entries, progress)
    todo = [a["url"] for e in entries for a in e["albums"] if a["url"] not in progress.done]
    todo = list(dict.fromkeys(todo))  # same album listed twice -> download once
    missing = [e["line"] for e in entries if not e["albums"]]
    print(f"\n{len(todo)} albums to download, about {tracks} tracks / {tracks * MB_PER_TRACK / 1024:.1f} GB"
          + (f"; {len(missing)} line(s) not found" if missing else ""))
    if args.review_only:
        return 0
    if not todo:
        return 1 if missing else 0
    if not args.yes and tty_input("Download them? [Y/n] ").strip().lower() not in ("", "y", "yes"):
        return 1

    L.run_gamdl(todo, state_dir, cookies, out_dir, [], progress)
    left = [u for u in todo if u not in progress.done]
    print(f"\nAlbums: {len(todo) - len(left)} downloaded, {len(left)} left"
          + (" - run 'musesh albums' again to retry them" if left else ""))
    # Non-zero when anything is missing, so callers (musesh align) don't count it as handled.
    return 1 if left or missing else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
