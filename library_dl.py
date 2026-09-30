"""Download every track in an Apple Music Library.xml export into one folder.

- Local files referenced by the XML are copied as-is.
- Apple Music tracks are resolved to catalog IDs via your cloud library
  (falling back to catalog search) and downloaded with gamdl.
- Optionally converts the result to 320 kbps MP3.

Run it with the Python inside gamdl's environment (see the `library-dl` wrapper).
"""

import argparse
import asyncio
import csv
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import time
import unicodedata
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import logging

import httpx
import structlog
from gamdl.api import AppleMusicApi

# gamdl logs every API response at debug level; keep only warnings and up.
structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING))

DURATION_TOLERANCE_MS = 3000
SEARCH_CONCURRENCY = 1
STATE_DIR = ".library-dl"


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").casefold()
    return re.sub(r"[^0-9a-z]+", "", s)


def base_title(s):
    """Title without bracketed parts, e.g. 'Song (feat. X) [Remix]' -> 'Song'."""
    return norm(re.sub(r"[\(\[].*?[\)\]]", "", s or ""))


def safe_name(s, fallback):
    s = re.sub(r'[\\/:*?"<>|]', "_", (s or "").strip()).strip(". ")
    return s[:120] or fallback


def log(msg):
    print(msg, flush=True)


# ---------------------------------------------------------------------------
# Library.xml
# ---------------------------------------------------------------------------

def load_xml_tracks(xml_path):
    with open(xml_path, "rb") as f:
        tracks = plistlib.load(f)["Tracks"].values()
    local, remote = [], []
    for t in tracks:
        path = None
        if t.get("Location"):
            path = urllib.parse.unquote(urllib.parse.urlparse(t["Location"]).path)
        if path and os.path.exists(path):
            local.append((t, path))
        else:
            remote.append(t)
    return local, remote


def copy_local(local, out_dir):
    copied = skipped = 0
    for t, src in local:
        artist = t.get("Album Artist") or t.get("Artist")
        dest_dir = out_dir / safe_name(artist, "Unknown Artist") / safe_name(t.get("Album"), "Unknown Album")
        dest = dest_dir / os.path.basename(src)
        if dest.exists() and dest.stat().st_size == os.path.getsize(src):
            skipped += 1
            continue
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        copied += 1
    log(f"Local files: {copied} copied, {skipped} already present")


# ---------------------------------------------------------------------------
# Matching Apple Music tracks to catalog IDs
# ---------------------------------------------------------------------------

async def fetch_cloud_library(api):
    songs, offset = [], 0
    while True:
        page = await api.get_library_songs(limit=100, offset=offset)
        data = page.get("data", [])
        songs.extend(data)
        log(f"  cloud library: {len(songs)} songs fetched")
        if not page.get("next") or not data:
            return songs
        offset += len(data)


def index_cloud(songs):
    by_key, by_title = {}, {}
    for s in songs:
        a = s.get("attributes", {})
        catalog_id = (a.get("playParams") or {}).get("catalogId")
        if not catalog_id:
            continue  # uploaded / non-catalog song
        entry = (catalog_id, a.get("durationInMillis") or 0)
        by_key.setdefault((norm(a.get("name")), norm(a.get("artistName"))), []).append(entry)
        by_title.setdefault(norm(a.get("name")), []).append(entry)
    return by_key, by_title


def closest(entries, duration, tolerance):
    if not entries:
        return None
    best = min(entries, key=lambda e: abs(e[1] - duration))
    if not duration or abs(best[1] - duration) <= tolerance:
        return best[0]
    return None


def match_in_cloud(t, by_key, by_title):
    name, artist, dur = norm(t.get("Name")), norm(t.get("Artist")), t.get("Total Time") or 0
    return (
        closest(by_key.get((name, artist)), dur, 10_000)
        or closest(by_title.get(name), dur, DURATION_TOLERANCE_MS)
    )


def score_candidate(t, a):
    score = 0
    if norm(a.get("name")) == norm(t.get("Name")):
        score += 3
    elif base_title(a.get("name")) == base_title(t.get("Name")):
        score += 1.5
    else:
        return 0
    xa, ca = norm(t.get("Artist")), norm(a.get("artistName"))
    if xa and ca and (xa in ca or ca in xa):
        score += 2
    if norm(a.get("albumName")) == norm(t.get("Album")):
        score += 1
    diff = abs((a.get("durationInMillis") or 0) - (t.get("Total Time") or 0))
    if diff <= DURATION_TOLERANCE_MS:
        score += 3
    elif diff <= 10_000:
        score += 1
    return score


ITUNES_SEARCH_URL = "https://itunes.apple.com/search"
ITUNES_MIN_INTERVAL = 3.2  # the public iTunes Search API allows roughly 20 requests a minute
_last_itunes_request = 0.0


async def itunes_search(api, query):
    """Search songs with the public iTunes Search API.

    The logged-in AMP search endpoint rate-limits hard (429s for minutes at a time),
    so searches go through this separate, predictable endpoint instead. Results are
    converted to the AMP attribute shape that score_candidate expects.
    """
    global _last_itunes_request
    params = {"term": query, "entity": "song", "limit": 15, "country": api.storefront}
    for delay in (30, 60, 120, 120):
        wait = _last_itunes_request + ITUNES_MIN_INTERVAL - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        _last_itunes_request = time.monotonic()
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(ITUNES_SEARCH_URL, params=params)
        if resp.status_code in (403, 429):
            await asyncio.sleep(delay)
            continue
        resp.raise_for_status()
        return [
            {
                "id": str(r["trackId"]),
                "attributes": {
                    "name": r.get("trackName"),
                    "artistName": r.get("artistName"),
                    "albumName": r.get("collectionName"),
                    "durationInMillis": r.get("trackTimeMillis"),
                },
            }
            for r in resp.json().get("results", [])
            if r.get("kind") == "song"
        ]
    raise RuntimeError("iTunes search still rate limited after retries")


async def search_catalog(api, t, dead_ids=frozenset()):
    term = f"{t.get('Name', '')} {t.get('Artist', '')}".strip()
    for query in (term, re.sub(r"[\(\[].*?[\)\]]", "", term)):
        try:
            results = await itunes_search(api, query)
        except Exception as e:
            log(f"  search failed for {term!r}: {e}")
            return None
        candidates = [c for c in results if c["id"] not in dead_ids]
        best = max(candidates, key=lambda c: score_candidate(t, c["attributes"]), default=None)
        if best and score_candidate(t, best["attributes"]) >= 6:
            return best["id"]
    return ""  # searched, not in the catalog


class Matches:
    """Persistent ID -> catalog ID cache. "" means searched and not in the catalog,
    so re-runs don't search it again."""

    def __init__(self, state_dir):
        self.path = state_dir / "matches.json"
        self.ids = json.loads(self.path.read_text()) if self.path.exists() else {}

    def save(self):
        self.path.write_text(json.dumps(self.ids, indent=1))

    def drop(self, dead_ids):
        """Forget matches pointing at dead catalog IDs so those tracks get searched again."""
        for pid, cid in list(self.ids.items()):
            if cid in dead_ids:
                del self.ids[pid]
        self.save()

    def unresolved(self, remote):
        return [t for t in remote if t["Persistent ID"] not in self.ids]

    def split(self, remote):
        matched = {t["Persistent ID"]: self.ids[t["Persistent ID"]] for t in remote if self.ids.get(t["Persistent ID"])}
        unmatched = [t for t in remote if not self.ids.get(t["Persistent ID"])]
        return matched, unmatched


async def match_cloud(api, remote, matches, dead_ids):
    todo = matches.unresolved(remote)
    if not todo:
        return
    log("Fetching your Apple Music cloud library...")
    by_key, by_title = index_cloud(await fetch_cloud_library(api))
    found = 0
    for t in todo:
        catalog_id = match_in_cloud(t, by_key, by_title)
        if catalog_id and catalog_id not in dead_ids:
            matches.ids[t["Persistent ID"]] = catalog_id
            found += 1
    matches.save()
    log(f"Matched {found} of {len(todo)} new tracks via your cloud library")


async def search_remaining(api, remote, matches, dead_ids):
    todo = matches.unresolved(remote)
    if not todo:
        return 0
    log(f"Searching the Apple Music catalog for {len(todo)} tracks not in your cloud library "
        "(slow: Apple rate-limits searches)...")
    sem = asyncio.Semaphore(SEARCH_CONCURRENCY)
    done = found = error_streak = 0

    async def search_one(t):
        nonlocal done, found, error_streak
        async with sem:
            catalog_id = await search_catalog(api, t, dead_ids)
        done += 1
        if catalog_id is None:  # search error; try again next run
            error_streak += 1
            if error_streak >= FAILURE_STREAK_LIMIT:
                matches.save()
                sys.exit(f"{FAILURE_STREAK_LIMIT} searches in a row failed, so stopping here; "
                         f"progress is saved.\nIf this keeps happening the cookies may be expired. {COOKIE_HELP}")
        else:
            error_streak = 0
            matches.ids[t["Persistent ID"]] = catalog_id
            found += bool(catalog_id)
        if done % 10 == 0 or done == len(todo):
            log(f"  searched {done}/{len(todo)}, found {found}")
            matches.save()

    await asyncio.gather(*(search_one(t) for t in todo))
    matches.save()
    return found


def write_unmatched(unmatched, path):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Name", "Artist", "Album", "Kind"])
        for t in unmatched:
            w.writerow([t.get("Name"), t.get("Artist"), t.get("Album"), t.get("Kind")])


# ---------------------------------------------------------------------------
# Downloading with gamdl
# ---------------------------------------------------------------------------

ANSI = re.compile(r"\x1b\[[0-9;]*m")
MAX_FAILURES = 2
FAILURE_STREAK_LIMIT = 5


class Progress:
    """Which song URLs finished, and how often each one has failed."""

    def __init__(self, state_dir):
        self.done_path = state_dir / "done.txt"
        self.fail_path = state_dir / "failures.json"
        self.gone_path = state_dir / "gone.txt"
        self.done = set(self.done_path.read_text().split()) if self.done_path.exists() else set()
        self.failures = json.loads(self.fail_path.read_text()) if self.fail_path.exists() else {}
        # Catalog IDs Apple answers with 404 (usually an album re-released under a new ID)
        self.gone = set(self.gone_path.read_text().split()) if self.gone_path.exists() else set()

    def mark_gone(self, url):
        catalog_id = url.rsplit("/", 1)[-1]
        if catalog_id not in self.gone:
            self.gone.add(catalog_id)
            with open(self.gone_path, "a") as f:
                f.write(catalog_id + "\n")

    def mark_done(self, url):
        if url not in self.done:
            self.done.add(url)
            with open(self.done_path, "a") as f:
                f.write(url + "\n")

    def mark_failed(self, url):
        self.failures[url] = self.failures.get(url, 0) + 1
        self.fail_path.write_text(json.dumps(self.failures, indent=1))


def run_gamdl(batch, state_dir, cookies, out_dir, gamdl_args, progress):
    """Run gamdl on a batch, streaming its output and recording per-URL results."""
    batch_path = state_dir / "batch.txt"
    batch_path.write_text("\n".join(batch) + "\n")
    # -n: ignore ~/.gamdl/config.ini so stale settings from older gamdl versions can't break the run
    # --no-synced-lyrics: don't write a .lrc lyrics file next to every song
    cmd = ["gamdl", "-n", "--no-synced-lyrics", "-r", str(batch_path), "-c", str(cookies), "-o", str(out_dir), *gamdl_args]
    log("Running: " + " ".join(cmd))

    current, current_failed, current_gone, buf = None, False, False, ""
    # Failures are held back until a later song succeeds. A long unbroken run of
    # failures means something global broke (usually expired cookies), and those
    # songs shouldn't count against their retry limit.
    failed_streak = []

    def finish_current():
        if not current:
            return
        if current_gone:
            # Not a real failure: the ID is dead. It gets re-looked-up by search.
            progress.mark_gone(current)
            log(f"  {current} no longer exists on Apple Music; will search for the current version")
        elif current_failed:
            failed_streak.append(current)
            if len(failed_streak) >= FAILURE_STREAK_LIMIT:
                proc.terminate()
                proc.wait()
                sys.exit(f"\n{FAILURE_STREAK_LIMIT} songs in a row failed to download, so stopping here; "
                         f"they will be retried next run.\nThe usual cause is expired cookies. {COOKIE_HELP}")
        else:
            for url in failed_streak:
                progress.mark_failed(url)
            failed_streak.clear()
            progress.mark_done(current)

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        while chunk := proc.stdout.read1(65536):
            sys.stdout.buffer.write(chunk)
            sys.stdout.flush()
            buf += chunk.decode("utf-8", "replace")
            *lines, buf = buf.split("\n")
            for line in map(ANSI.sub, [""] * len(lines), lines):
                if m := re.search(r'Processing "(https://[^"]+)"', line):
                    finish_current()
                    current, current_failed, current_gone = m.group(1), False, False
                elif "Status code: 404" in line:
                    current_gone = True
                elif "Error downloading" in line or "Error processing" in line:
                    current_failed = True
                elif "Finished with" in line:
                    finish_current()
                    current = None
    finally:
        code = proc.wait()
    if current and code == 0:
        finish_current()
    for url in failed_streak:  # a short streak at the very end: count it normally
        progress.mark_failed(url)
    if code != 0:
        log(f"gamdl exited with code {code}; re-run to continue where it stopped.")


# ---------------------------------------------------------------------------
# MP3 conversion
# ---------------------------------------------------------------------------

def convert_to_mp3(out_dir, mp3_dir, jobs):
    """--mp3 / --convert-only: handled by mp3.py (skips matching files, redoes wrong ones, shows progress)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import mp3
    mp3.run(out_dir, mp3_dir, jobs, assume_yes=True)


# ---------------------------------------------------------------------------

COOKIE_HELP = ("Re-export cookies.txt (Netscape format) from music.apple.com while logged in, "
               "e.g. with the 'Get cookies.txt LOCALLY' browser extension.")


async def login(cookies):
    """Check the cookies before doing anything else; exit with a clear message if they don't work."""
    for attempt in range(1, 5):
        try:
            api = await AppleMusicApi.create_from_netscape_cookies(str(cookies))
            break
        except Exception as e:
            text = str(e)
            if "does not look like a Netscape" in text:
                why = "that file isn't a Netscape-format cookies file."
            elif "media-user-token" in text:
                why = "it has no Apple Music login in it (media-user-token is missing)."
            elif "Status code" in text:
                why = f"Apple rejected the login - the cookies are probably expired ({text})."
            else:
                # Fetching Apple Music's web page (for its access token) sometimes fails
                # for a moment; that isn't a cookies problem, so retry it.
                if attempt < 4:
                    log(f"  Apple Music didn't respond ({text}); retrying...")
                    await asyncio.sleep(5 * attempt)
                    continue
                sys.exit(f"Couldn't reach Apple Music after 4 tries ({text}). Check your internet and try again.")
            sys.exit(f"Cookies problem with {cookies}: {why}\n{COOKIE_HELP}")
    if not api.active_subscription:
        sys.exit(f"The cookies in {cookies} log in, but not to an active Apple Music subscription.\n{COOKIE_HELP}")
    log(f"Logged in to Apple Music (storefront: {api.storefront})")
    return api


async def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("xml", type=Path, nargs="?", help="Library.xml exported from Music (File > Library > Export Library...)")
    p.add_argument("-o", "--output", type=Path, default=Path("~/Music/Library Download").expanduser(),
                   help="output folder (default: ~/Music/Library Download)")
    p.add_argument("-c", "--cookies", type=Path, default=Path("cookies.txt"),
                   help="Netscape cookies.txt exported from music.apple.com while logged in")
    p.add_argument("--mp3", action="store_true",
                   help="also convert everything to 320 kbps MP3 in '<output> MP3'")
    p.add_argument("--mp3-dir", type=Path,
                   help="where to write MP3s (default: '<output> MP3'), e.g. a USB stick")
    p.add_argument("--convert-only", action="store_true",
                   help="skip copying/downloading and just convert the output folder to MP3")
    p.add_argument("--jobs", type=int, default=os.cpu_count() or 4, help="parallel MP3 conversions")
    p.add_argument("--skip-download", action="store_true",
                   help="only copy local files and resolve IDs; don't run gamdl")
    p.add_argument("-b", "--batch", type=int,
                   help="only download the next N songs this run (re-run for the next batch)")
    p.add_argument("--limit", type=int, help="only process the first N Apple Music tracks (for testing)")
    p.epilog = "Arguments after '--' are passed to gamdl, e.g. -- --song-codec-priority alac"
    argv = sys.argv[1:]
    gamdl_args = argv[argv.index("--") + 1:] if "--" in argv else []
    args = p.parse_args(argv[: argv.index("--")] if "--" in argv else argv)

    out_dir = args.output.expanduser().resolve()
    mp3_dir = args.mp3_dir.expanduser().resolve() if args.mp3_dir else out_dir.with_name(out_dir.name + " MP3")
    if args.convert_only:
        convert_to_mp3(out_dir, mp3_dir, args.jobs)
        return

    if not args.xml:
        p.error("the Library.xml path is required unless --convert-only is used")
    state_dir = out_dir / STATE_DIR
    state_dir.mkdir(parents=True, exist_ok=True)
    cookies = args.cookies.expanduser().resolve()
    if not cookies.exists():
        sys.exit(f"Cookies file not found: {cookies}")

    local, remote = load_xml_tracks(args.xml.expanduser())
    if args.limit:
        remote = remote[: args.limit]
    log(f"{len(local)} local files, {len(remote)} Apple Music tracks")

    api = await login(cookies)
    copy_local(local, out_dir)
    matches = Matches(state_dir)
    progress = Progress(state_dir)
    matches.drop(progress.gone)
    await match_cloud(api, remote, matches, progress.gone)

    def pending():
        matched, _ = matches.split(remote)
        urls = sorted({f"https://music.apple.com/{api.storefront}/song/{cid}" for cid in matched.values()})
        remaining = [u for u in urls if u not in progress.done and progress.failures.get(u, 0) < MAX_FAILURES]
        return urls, remaining

    def summary():
        urls, remaining = pending()
        unresolved = len(matches.unresolved(remote))
        given_up = sum(1 for u in urls if u not in progress.done and progress.failures.get(u, 0) >= MAX_FAILURES)
        log(f"Songs: {sum(u in progress.done for u in urls)} downloaded, {len(remaining)} ready to download, "
            f"{given_up} failed {MAX_FAILURES}x, {unresolved} still to look up, "
            f"{len(remote) - len(urls) - unresolved} not on Apple Music")
        return remaining

    remaining = summary()
    budget = args.batch or len(remaining) + len(matches.unresolved(remote))

    # Download what's already matched first, so searching never holds up downloads.
    batch = remaining[:budget]
    if not args.skip_download and batch:
        log(f"Downloading {len(batch)} songs")
        run_gamdl(batch, state_dir, cookies, out_dir, gamdl_args, progress)
        budget -= len(batch)

    # Then look up the tracks that weren't in the cloud library (slow), and fill the rest of the batch.
    matches.drop(progress.gone)  # anything that 404'd in this batch gets searched now
    if budget > 0 and await search_remaining(api, remote, matches, progress.gone):
        batch = pending()[1][:budget]
        if not args.skip_download and batch:
            log(f"Downloading {len(batch)} songs found by search")
            run_gamdl(batch, state_dir, cookies, out_dir, gamdl_args, progress)

    write_unmatched(matches.split(remote)[1], out_dir / "unmatched.csv")
    if summary() and args.batch:
        log("Run again for the next batch.")

    if args.mp3:
        convert_to_mp3(out_dir, mp3_dir, args.jobs)

    log("Done.")


if __name__ == "__main__":
    asyncio.run(main())
