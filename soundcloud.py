"""Public SoundCloud tracks and albums/sets, downloaded through yt-dlp.

Uses only the standard library; no Apple Music configuration is required.
"""

import argparse
import errno
import fcntl
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from ui import die, heading, note, summary, tilde
from ui import prompt

AUDIO_EXTS = {".m4a", ".mp3", ".flac", ".wav", ".aif", ".aiff", ".ogg", ".opus", ".aac"}
RESERVED = {"sets", "tracks", "albums", "popular-tracks", "reposts", "likes"}


def find_ytdlp():
    # Older user-site scripts can precede Homebrew on PATH and use Apple's Python.
    for candidate in (Path("/opt/homebrew/bin/yt-dlp"), Path("/usr/local/bin/yt-dlp")):
        if candidate.is_file() and candidate.stat().st_mode & 0o111:
            return str(candidate)
    return shutil.which("yt-dlp")


def public_url(value):
    """Accept tracks/sets and SoundCloud short links, never profile-wide feeds."""
    p = urlsplit(value.strip())
    host = (p.hostname or "").lower()
    parts = p.path.strip("/").split("/")
    if p.scheme not in ("http", "https") or p.username or p.password or p.port:
        raise ValueError("Give a public https://soundcloud.com/artist/track or /artist/sets/album link.")
    if host in ("on.soundcloud.com", "snd.sc"):
        valid = len(parts) == 1 and bool(parts[0])
    elif host in ("soundcloud.com", "www.soundcloud.com", "m.soundcloud.com"):
        valid = (len(parts) == 2 and parts[1] not in RESERVED) or (
            len(parts) == 3 and parts[1] == "sets")
    else:
        valid = False
    if not valid:
        raise ValueError("Only public SoundCloud track and album/set links are supported, not profiles or private links.")
    return urlunsplit(("https", host, p.path.rstrip("/"), "", ""))


def safe_name(value, fallback):
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f\x7f]', "_", str(value or "").strip()).strip(". ")
    # Bound bytes as well as characters for macOS filenames.
    return name.encode("utf-8")[:120].decode("utf-8", errors="ignore") or fallback


def track_tags(info, album=None, index=None, total=None):
    info = dict(info)
    artist = info.get("artist") or ", ".join(info.get("artists") or []) or info.get("uploader") or "Unknown Artist"
    title = info.get("track") or info.get("title") or "Unknown Track"
    info.update(artist=artist, artists=[artist], track=title, title=title,
                album=album or info.get("album") or "Unknown Album")
    if index is not None:
        info["track_number"] = index
    if total is not None:
        info["track_count"] = total
    return info


def target_path(out, info, ext, done):
    folder = out / safe_name(info["artist"], "Unknown Artist") / safe_name(info["album"], "Unknown Album")
    number = info.get("track_number")
    prefix = f"{int(number):02d} " if number else ""
    stem = prefix + safe_name(info["title"], "Unknown Track")
    dest = folder / (stem + ext)
    used = {out / path for path in done.values()}
    if dest.exists() or dest in used:
        dest = folder / (stem + f" [sc-{info['id']}]" + ext)
    if dest.exists() or dest in used:
        raise ValueError(f"Refusing to overwrite {tilde(dest)}")
    return dest


class Downloader:
    def __init__(self, out, executable, auth_args=()):
        self.out = out
        self.state = out / ".musesh"
        self.state.mkdir(parents=True, exist_ok=True)
        self.lock = (self.state / "soundcloud.lock").open("a")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            die("A SoundCloud download is already running for this folder.")
        self.logfile = (self.state / "soundcloud-run.log").open("a", buffering=1)
        self.record = self.state / "soundcloud-done.json"
        self.done = json.loads(self.record.read_text()) if self.record.exists() else {}
        self.base = [executable, "--ignore-config", "--no-cache-dir", "--socket-timeout", "30",
                     "--retries", "3", "--fragment-retries", "3", "--abort-on-unavailable-fragments", *auth_args]
        self.authenticated = bool(auth_args)
        self.browser_auth = "--cookies-from-browser" in auth_args

    def log(self, message):
        print(message, flush=True)
        self.logfile.write(message + "\n")

    def metadata(self, url, flat=False):
        args = [*self.base, "--skip-download", "--dump-single-json"]
        args += ["--flat-playlist"] if flat else ["--no-playlist"]
        result = subprocess.run([*args, "--", url], capture_output=True, text=True)
        if result.stderr.strip():
            self.log(result.stderr.strip())
        if self.browser_auth and any(message in result.stderr.lower() for message in (
                "cannot decrypt", "find-generic-password failed", "failed to decrypt")):
            raise ValueError("Browser login cookies could not be decrypted. Export SoundCloud cookies in Netscape format "
                             "to a local file, then run again with --cookies /path/to/soundcloud-cookies.txt. "
                             "Do not paste cookie contents into chat.")
        if result.returncode:
            raise ValueError("SoundCloud metadata could not be read. Check the link/network and update yt-dlp (brew upgrade yt-dlp).")
        info = json.loads(result.stdout)
        if not isinstance(info, dict):
            raise ValueError("SoundCloud returned no track metadata.")
        extractor = str(info.get("extractor_key") or info.get("ie_key") or "").lower()
        if not extractor.startswith("soundcloud"):
            raise ValueError("The link did not resolve to SoundCloud.")
        if info.get("_type") == "playlist" and extractor != "soundcloudset":
            raise ValueError("Only tracks and albums/sets are supported, not artist feeds.")
        return info

    def download(self, info):
        track_id = str(info["id"])
        if not track_id.isdigit():
            raise ValueError("SoundCloud returned an invalid track ID.")
        work = self.state / "soundcloud-work" / track_id
        work.mkdir(parents=True, exist_ok=True)
        work.chmod(0o700)
        source = work / "info.json"
        source.write_text(json.dumps(info))
        source.chmod(0o600)
        result_file = work / "result.txt"
        result_file.unlink(missing_ok=True)
        # Keep native codecs; ExtractAudio remuxes AAC into M4A where needed.
        cmd = [*self.base, "--load-info-json", str(source), "-f", "download/bestaudio/best",
               "--extract-audio", "--audio-format", "wav>flac/aiff>flac/aif>flac/best", "--embed-metadata", "--embed-thumbnail",
               "--convert-thumbnails", "jpg", "--no-simulate", "--newline",
               "-o", str(work / "audio.%(ext)s"),
               "--print-to-file", "after_move:%(filepath)j", str(result_file)]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            for line in proc.stdout:
                self.log(line.rstrip())
            code = proc.wait()
        except BaseException:
            proc.terminate()
            proc.wait()
            raise
        finally:
            proc.stdout.close()
        if code or not result_file.exists():
            raise ValueError("Download or metadata processing failed; run the same link again to retry.")
        audio = Path(json.loads(result_file.read_text().splitlines()[-1])).resolve()
        if audio.parent != work.resolve() or audio.suffix.lower() not in AUDIO_EXTS or not audio.is_file():
            raise ValueError("Downloaded format is not supported by musesh mp3.")
        probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
                                "stream=codec_name", "-of", "json", str(audio)], capture_output=True, text=True)
        if probe.returncode or not json.loads(probe.stdout).get("streams") or not audio.stat().st_size:
            raise ValueError("Downloaded audio could not be verified; it has not been marked complete.")
        dest = target_path(self.out, info, audio.suffix, self.done)
        dest.parent.mkdir(parents=True, exist_ok=True)
        # Hard-link publication is atomic and refuses to overwrite an existing file.
        try:
            dest.hardlink_to(audio)
        except OSError as exc:
            if exc.errno not in (errno.EPERM, errno.EOPNOTSUPP, errno.ENOSYS, errno.EXDEV):
                raise
            # FAT/exFAT destinations do not support hard links. Exclusive creation
            # still protects existing music; remove our new file if copying fails.
            with dest.open("xb") as output:
                try:
                    with audio.open("rb") as source_audio:
                        shutil.copyfileobj(source_audio, output)
                except BaseException:
                    dest.unlink(missing_ok=True)
                    raise
        self.done[track_id] = str(dest.relative_to(self.out))
        temporary = self.record.with_suffix(".tmp")
        try:
            temporary.write_text(json.dumps(self.done, indent=2))
            temporary.replace(self.record)
        except OSError:
            self.done.pop(track_id, None)
            dest.unlink()
            raise
        shutil.rmtree(work, ignore_errors=True)
        self.log(f"Saved: {tilde(dest)}")

    def run(self, url):
        self.log(f"SoundCloud: {url}")
        root = self.metadata(url, flat=True)
        is_set = root.get("_type") == "playlist"
        entries = root.get("entries", []) if is_set else [root]
        if not entries:
            raise ValueError("This album/set has no accessible tracks.")
        album = (root.get("album") or root.get("title")) if is_set else None
        heading(album or root.get("title") or "SoundCloud")
        summary([("tracks", len(entries)), ("into", tilde(self.out)),
                 ("audio", "best available native audio; use musesh mp3 for an MP3 copy")])
        if is_set and not prompt("Download this album/set? [Y/n] ").strip().lower() in ("", "y", "yes"):
            return 0
        saved = skipped = failed = 0
        for index, entry in enumerate(entries, 1):
            if not entry:
                failed += 1
                self.log(f"Track {index}: unavailable")
                continue
            track_id = str(entry.get("id", ""))
            if track_id in self.done:
                skipped += 1
                self.log(f"Skipped: {entry.get('title') or track_id} (already handled)")
                continue
            try:
                link = entry.get("webpage_url") or entry.get("url") or url
                info = self.metadata(link)
                if str(info.get("id")) in self.done:
                    skipped += 1
                    continue
                if not self.authenticated and info.get("availability") in ("private", "premium_only", "subscriber_only", "needs_auth"):
                    raise ValueError("This track requires account access. Try --cookies-from-browser vivaldi or --cookies PATH.")
                info["formats"] = [f for f in info.get("formats", [])
                                   if "preview" not in str(f.get("format_id", "")).lower()]
                if not info["formats"]:
                    hint = (" SoundCloud returned only preview formats to yt-dlp despite the supplied login cookies; "
                            "full browser playback may differ." if self.authenticated else
                            " Try --cookies-from-browser vivaldi or --cookies PATH for account access.")
                    raise ValueError("Only a preview is available; skipping it." + hint)
                self.download(track_tags(info, album, index if is_set else None, len(entries) if is_set else None))
                saved += 1
            except (ValueError, OSError) as exc:
                failed += 1
                self.log(f"Failed: {entry.get('title') or track_id}: {exc}")
        self.log(f"SoundCloud finished: {saved} saved, {skipped} skipped, {failed} failed.")
        if saved:
            note("Run musesh mp3 to make an MP3 copy. Native sources are kept in Incoming.")
        return 1 if failed else 0


def main():
    parser = argparse.ArgumentParser(prog="musesh soundcloud", description=__doc__)
    parser.add_argument("url", nargs="?", help="public SoundCloud track or album/set URL")
    parser.add_argument("-o", "--output", type=Path, default=Path.home() / "Music/musesh/Incoming",
                        help=argparse.SUPPRESS)
    auth = parser.add_mutually_exclusive_group()
    auth.add_argument("--cookies-from-browser", metavar="BROWSER", help="use local browser login, e.g. vivaldi or vivaldi:PROFILE")
    auth.add_argument("--cookies", type=Path, metavar="PATH", help="local Netscape-format SoundCloud cookies file")
    args = parser.parse_args()
    try:
        url = public_url(args.url or prompt("SoundCloud track or album link: "))
        executable = find_ytdlp()
        if not executable:
            die("yt-dlp isn't installed. Install it with: brew install yt-dlp")
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            die("ffmpeg/ffprobe aren't installed. Install them with: brew install ffmpeg")
        # yt-dlp may update its cookie jar. Copy explicit cookies so the user's
        # exported file remains untouched; temporary credentials never enter state.
        with tempfile.TemporaryDirectory(prefix="musesh-soundcloud-auth-") as private:
            auth_args = []
            if args.cookies:
                source = args.cookies.expanduser().resolve()
                if not source.is_file():
                    die("SoundCloud cookies file not found. Give the path to your local Netscape-format export.")
                cookie_copy = Path(private) / "cookies.txt"
                shutil.copyfile(source, cookie_copy)
                cookie_copy.chmod(0o600)
                auth_args = ["--cookies", str(cookie_copy)]
            elif args.cookies_from_browser:
                auth_args = ["--cookies-from-browser", args.cookies_from_browser]
            return Downloader(args.output.expanduser().resolve(), executable, auth_args).run(url)
    except (ValueError, OSError) as exc:
        die(str(exc))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError):
        note("stopped; run the same link again to resume")
        sys.exit(130)
