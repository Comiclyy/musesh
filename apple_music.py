"""Download Apple Music song and album links with the existing gamdl workflow."""

import argparse
import asyncio
import contextlib
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from ui import heading, note, summary, tilde
from ui import prompt


def parse_link(value):
    """An album share link with ?i= selects a song, never the whole album."""
    parsed = urlsplit(value.strip())
    parts = parsed.path.strip("/").split("/")
    if (parsed.scheme not in ("http", "https") or parsed.hostname != "music.apple.com"
            or parsed.username or parsed.password or parsed.port or len(parts) not in (3, 4)
            or not re.fullmatch(r"[a-zA-Z]{2}", parts[0]) or parts[1] not in ("song", "album")
            or not re.fullmatch(r"[0-9]+", parts[-1])):
        raise ValueError("Give an Apple Music song or album link from https://music.apple.com; artist and playlist links aren't supported.")
    country, kind, catalog_id = parts[0].lower(), parts[1], parts[-1]
    selected = parse_qs(parsed.query, keep_blank_values=True).get("i")
    if selected is not None:
        if len(selected) != 1 or not re.fullmatch(r"[0-9]+", selected[0]):
            raise ValueError("The Apple Music song ID (?i=...) must be a single numeric ID.")
        kind, catalog_id = "song", selected[0]
    return country, kind, catalog_id


def canonical(country, kind, catalog_id):
    return f"https://music.apple.com/{country}/{kind}/{catalog_id}"


def completed(done):
    result = set()
    for url in done:
        try:
            _, kind, catalog_id = parse_link(url)
            result.add((kind, catalog_id))
        except ValueError:
            pass
    return result


async def album_songs(api, album):
    page = album.get("relationships", {}).get("tracks", {})
    songs, seen_pages = [], set()
    while True:
        songs.extend(t for t in page.get("data", []) if t.get("type") == "songs")
        next_page = page.get("next")
        if not next_page:
            return list(dict.fromkeys(str(t["id"]) for t in songs))
        # Catalog pagination comes from gamdl's authenticated API client. Never
        # send credentials to an absolute or unrelated URL from a response.
        if not next_page.startswith(f"/v1/catalog/{api.storefront}/albums/{album['id']}/tracks?") or next_page in seen_pages:
            raise ValueError("Apple Music returned an unexpected album track page; download stopped.")
        seen_pages.add(next_page)
        page = await api._amp_request(next_page)


async def download_link(value, out, cookies, assume_yes=False, review_only=False, library=None):
    country, kind, catalog_id = parse_link(value)
    if library is None:
        import library_dl as library
    state = library.state_dir_for(out)
    progress = library.Progress(state)
    handled = completed(progress.done)
    if (kind, catalog_id) in handled:
        note("Already handled; skipped (including files you deleted).")
        return 0
    api = await library.login(cookies)
    # Match the downloader's account storefront, just like library.xml downloads.
    country = api.storefront
    data = await (api.get_song(catalog_id) if kind == "song" else api.get_album(catalog_id))
    items = data.get("data", [])
    if not items:
        raise ValueError("This link isn't available in your Apple Music storefront.")
    item = items[0]
    attrs = item.get("attributes", {})
    song_ids = [catalog_id] if kind == "song" else await album_songs(api, item)
    if not song_ids:
        raise ValueError("This album has no downloadable songs.")
    pending = [sid for sid in song_ids if ("song", sid) not in handled]
    urls = [canonical(country, "song", sid) for sid in pending]
    heading(attrs.get("name", "Apple Music"))
    summary([("artist", attrs.get("artistName", "Unknown Artist")), ("type", kind),
             ("tracks", len(song_ids)), ("already handled", len(song_ids) - len(pending)),
             ("to download", len(pending)), ("into", tilde(out))])
    if review_only:
        return 0
    if urls and kind == "album" and not assume_yes and prompt("Download this album? [Y/n] ").strip().lower() not in ("", "y", "yes"):
        return 0
    if urls:
        library.run_gamdl(urls, state, cookies, out, [], progress)
    finished = completed(progress.done)
    left = [sid for sid in song_ids if ("song", sid) not in finished]
    if not left and kind == "album":
        progress.mark_done(canonical(country, kind, catalog_id))
    print(f"Apple Music: {len(pending) - len(left)} downloaded, {len(song_ids) - len(pending)} skipped, {len(left)} left.")
    if left:
        note("Run the same link again to retry unfinished songs.")
    else:
        note("Run musesh mp3 to make an MP3 copy; the native audio is kept in Incoming.")
    return 1 if left else 0


class Tee:
    """Keep run_gamdl's binary progress output and text summaries in one log."""
    def __init__(self, stream, log):
        self.stream, self.log = stream, log
        if hasattr(stream, "buffer"):
            self.buffer = Tee(stream.buffer, log.buffer)

    def write(self, value):
        self.log.write(value)
        return self.stream.write(value)

    def flush(self):
        self.log.flush()
        self.stream.flush()


def main():
    parser = argparse.ArgumentParser(prog="musesh apple", description=__doc__)
    parser.add_argument("url", nargs="?", help="Apple Music song or album URL")
    parser.add_argument("-c", "--cookies", type=Path, help="Apple Music Netscape cookies (defaults to saved settings)")
    parser.add_argument("-y", "--yes", action="store_true", help="download albums without confirmation")
    parser.add_argument("--review-only", action="store_true", help="show the link and pending tracks without downloading")
    parser.add_argument("--output", type=Path, default=Path.home() / "Music/musesh/Incoming", help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        url = args.url or prompt("Apple Music song or album link: ")
        parse_link(url)
        if not args.cookies or not args.cookies.expanduser().is_file():
            parser.error("No Apple Music cookies file found. Pass --cookies /path/to/music.apple.com_cookies.txt or run musesh to save one.")
        out = args.output.expanduser().resolve()
        state = out / ".musesh"
        state.mkdir(parents=True, exist_ok=True)
        with (state / "apple-run.log").open("a", buffering=1) as log:
            with contextlib.redirect_stdout(Tee(sys.stdout, log)):
                return asyncio.run(download_link(url, out, args.cookies.expanduser().resolve(), args.yes, args.review_only))
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Apple Music: {exc}\n")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError):
        note("stopped; run the same link again to resume")
        sys.exit(130)
