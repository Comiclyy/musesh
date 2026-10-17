"""Copy new Library MP3s to a connected Walkman, preserving deliberate deletions."""

import argparse
import ctypes
import datetime as dt
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import sqlite3
import subprocess
import sys
import textwrap
import time
import uuid
from collections import defaultdict
from contextlib import closing

from music_dates import inventory
from transfer import digest, save_json, windows_path
from ui import accent, bold, cyan, dim, green, heading, note, ok, prompt, summary, warn

ROOT = Path.home() / "Music" / "musesh"
STATE = ROOT / ".push"
RECENT_DAYS = 7
RESERVE = 8 * 1024 * 1024
USB_ERRORS = {errno.EIO, errno.ENXIO, errno.ENODEV, errno.ESTALE, errno.EBADF}


class PlayerDisconnected(ValueError):
    """The current copy must be retried against the same mounted player."""


def connection_log(message):
    print(f"  {dim(dt.datetime.now().strftime('%H:%M:%S'))} {message}", flush=True)


class ConnectionWatcher:
    """Watch for the approved volume UUID, including a changed mount path."""

    def __init__(self, player, identity):
        self.player, self.identity = player, identity
        self.device = player.stat().st_dev

    def ensure_connected(self):
        try:
            if self.player.is_mount() and self.player.stat().st_dev == self.device:
                return
        except OSError:
            pass
        raise PlayerDisconnected("Walkman disconnected.")

    def wait(self, index, count, row):
        connection_log(f"DISCONNECTED · paused at song {index}/{count}: {row['key']}")
        connection_log("WATCHING · reconnect the same Walkman; this batch will continue automatically. Ctrl-C to stop.")
        heartbeat = time.monotonic()
        rejected = set()
        while True:
            # Also backs off when a cable reports I/O errors before unmounting.
            time.sleep(2)
            try:
                candidates = list(dict.fromkeys([self.player, *sorted(Path('/Volumes').iterdir())]))
            except OSError:
                candidates = [self.player]
            for candidate in candidates:
                if candidate == Path('/') or not candidate.is_mount():
                    continue
                try:
                    info = volume_info(candidate)
                    if info['VolumeUUID'] != self.identity:
                        if candidate == self.player or candidate.name.startswith('WALKMAN'):
                            key = (str(candidate), info['VolumeUUID'])
                            if key not in rejected:
                                connection_log(f"IGNORED · {candidate.name} is a different player; still waiting for your Walkman.")
                                rejected.add(key)
                        continue
                    # A mount can reappear before its filesystem is ready.
                    with os.scandir(candidate) as entries:
                        next(entries, None)
                    self.device = candidate.stat().st_dev
                except (OSError, ValueError, subprocess.SubprocessError):
                    continue
                self.player = candidate
                connection_log(f"RECONNECTED · {candidate} · continuing song {index}/{count} automatically.")
                return candidate
            if time.monotonic() - heartbeat >= 10:
                connection_log("WATCHING · Walkman not ready yet; waiting for reconnection…")
                heartbeat = time.monotonic()


class UploadProgress:
    def __init__(self, index, count, row):
        self.index, self.count, self.row = index, count, row
        self.started = time.monotonic()
        self.last_update = 0
        self.last_stage = None
        self.width = 0
        self.terminal = sys.stdout.isatty()
        print(f"\n  {cyan(f'{index}/{count}')} {bold(row['key'])}", flush=True)

    def update(self, stage, done, total):
        now = time.monotonic()
        changed = stage != self.last_stage
        if not changed and done != total and now - self.last_update < 0.1:
            return
        self.last_update, self.last_stage = now, stage
        if not self.terminal:
            if changed:
                print(f"    {stage} · {size_label(total)}", flush=True)
            return
        fraction = min(1, done / total) if total else 1
        filled = int(18 * fraction)
        rate = done / max(now - self.started, 0.001)
        eta = max(0, int((total - done) / rate)) if rate else 0
        bar = "█" * filled + "░" * (18 - filled)
        text = (f"    {bar} {fraction:4.0%}  {size_label(done)} / {size_label(total)}"
                f"  {stage}")
        if stage == "copying" and rate:
            text += f" · {size_label(rate)}/s · {eta}s left"
        columns = max(30, shutil.get_terminal_size((88, 24)).columns - 1)
        text = text[:columns]
        self.width = max(self.width, len(text))
        print("\r" + text.ljust(self.width), end="", flush=True)

    def finish(self, success):
        if self.terminal:
            print("\r" + " " * self.width + "\r", end="", flush=True)
        if success:
            print(f"    {green('✓')} verified and saved · {size_label(self.row['size'])}", flush=True)
        else:
            print("    ! unfinished — kept pending for the next push", flush=True)

    def pause(self):
        if self.terminal:
            print("\r" + " " * self.width + "\r", end="", flush=True)
        print("    ⏸ upload paused; finished songs are saved", flush=True)


def size_label(size):
    return f"{size / 1e9:.2f} GB" if size >= 1e9 else f"{size / 1e6:.1f} MB"


def source_files(library):
    """Read durable download dates without changing the library during a preview."""
    database = library / ".musesh" / "added.sqlite3"
    dates = {}
    if database.exists():
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
            dates = dict(db.execute("SELECT path, added FROM additions"))
    files = {}
    for source in sorted(inventory(library)):
        if source.suffix.lower() != ".mp3":
            continue
        stat = source.stat()
        relative = source.relative_to(library).as_posix()
        files[relative] = {"source": source, "size": stat.st_size,
                           "added": dates.get(relative, getattr(stat, "st_birthtime", stat.st_mtime)),
                           "stamp": (stat.st_size, stat.st_mtime_ns)}
    return files


def volume_info(path):
    result = subprocess.run(["diskutil", "info", "-plist", str(path)], capture_output=True, check=True, timeout=5)
    info = plistlib.loads(result.stdout)
    if (not info.get("VolumeUUID") or info.get("Internal", True) or not info.get("WritableVolume")
            or Path(info.get("MountPoint", "/")) != path or not path.is_mount()):
        raise ValueError("The player must be a mounted, writable external volume.")
    return info


def find_player(state_dir, requested=None):
    config_path = state_dir / "player.json"
    config = json.loads(config_path.read_text()) if config_path.exists() else None
    if requested:
        candidates = [requested.expanduser().resolve()]
    elif config:
        saved = Path(config["mount"])
        candidates = [saved] if saved.is_mount() else sorted(Path("/Volumes").iterdir())
    else:
        candidates = [Path("/Volumes/WALKMAN")]
    found = []
    for path in candidates:
        if not path.is_mount() or path == Path("/"):
            continue
        try:
            info = volume_info(path)
        except subprocess.CalledProcessError as exc:
            if requested or path.name == "WALKMAN":
                raise ValueError("Could not inspect the Walkman volume. Reconnect it and try again.") from exc
            continue
        except ValueError:
            continue
        if not config or info["VolumeUUID"] == config["uuid"]:
            found.append((path, info))
    if len(found) != 1:
        raise ValueError("Connect the configured Walkman and try again; no unique matching player was found.")
    player, info = found[0]
    return player, info["VolumeUUID"]


def destination(player, relative):
    relative = Path(relative)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ValueError("Invalid destination in push history.")
    target = player / "MUSIC" / relative
    # Do not follow a link to another volume or to the Mac library.
    for parent in [player / "MUSIC", *target.relative_to(player / "MUSIC").parents]:
        check = parent if parent.is_absolute() else player / "MUSIC" / parent
        if check.is_symlink():
            raise ValueError(f"Linked player folders are not supported: {check}")
    if target.is_symlink():
        raise ValueError(f"Linked player files are not supported: {target}")
    return target


def plan(files, player, state):
    records = state["songs"]
    claimed = {r["target"].casefold() for r in records.values()}
    handled_hashes = {r.get("sha256") for r in records.values() if r["status"] == "handled"}
    rows = []
    for key, file in files.items():
        record = records.get(key)
        if record and record["status"] != "pending":
            continue
        if record is None:
            target = windows_path(Path(key))
            if target.casefold() in claimed:
                target = target[:-4] + " [" + hashlib.sha256(key.encode()).hexdigest()[:12] + "].mp3"
            if target.casefold() in claimed:
                raise ValueError(f"Destination collision: {key}")
            claimed.add(target.casefold())
            record = {"target": target, "status": "pending",
                      "temp": ".musesh-push-" + uuid.uuid4().hex + ".part"}
            records[key] = record
            if file["added"] < state["cutoff"]:
                record["status"] = "older"
                continue
        target = destination(player, record["target"])
        if target.exists() and not record.get("sha256"):
            # Pre-existing paths belong to the user. Remember them without
            # replacing, repairing, or re-adding them after later deletion.
            record.update(status="handled", sha256=digest(file["source"]))
            handled_hashes.add(record["sha256"])
            continue
        sha = digest(file["source"])
        if sha in handled_hashes:
            record.update(status="handled", sha256=sha)
            continue
        record["sha256"] = sha
        rows.append({**file, "key": key, "record": record})
    return rows


def preview(rows, library, player, state, free):
    total = sum(row["size"] for row in rows)
    groups = defaultdict(list)
    for row in rows:
        parts = Path(row["key"]).parts
        artist = parts[0] if len(parts) > 1 else "Unfiled"
        album = "/".join(parts[1:-1]) if len(parts) > 2 else "Singles"
        groups[(artist, album)].append(row)
    heading("Push to Walkman")
    summary([("from", library), ("to", player / "MUSIC"),
             ("to add", f"{len(rows)} songs · {len(groups)} albums · {size_label(total)}"),
             ("free now", size_label(free)),
             ("free afterward", f"about {size_label(max(0, free - total))}")])
    cutoff = dt.datetime.fromtimestamp(state["cutoff"]).strftime("%b %d, %Y at %H:%M")
    note(f"Tracking additions since {cutoff}. Previously handled songs stay skipped after deletion.")
    if not rows:
        print()
        ok("No new songs to add.")
        return
    width = max(46, min(100, shutil.get_terminal_size((88, 24)).columns))
    print("\n  " + dim("─" * (width - 4)))
    previous_artist = None
    for (artist, album), songs in sorted(groups.items(), key=lambda item: tuple(s.casefold() for s in item[0])):
        if artist != previous_artist:
            print(f"\n  {bold(artist)}")
            previous_artist = artist
        subtotal = sum(song["size"] for song in songs)
        print(f"    {cyan(album)}  {dim(f'{len(songs)} songs · {size_label(subtotal)}')}")
        for song in songs:
            name = Path(song["key"]).stem
            lines = textwrap.wrap(name, width=width - 23) or [name]
            print(f"      {lines[0]:<{width - 23}}  {dim(size_label(song['size']).rjust(10))}")
            for line in lines[1:]:
                print("      " + line)
    print("\n  " + dim("─" * (width - 4)))
    print(f"  {green(str(len(rows)) + ' songs')} · {bold(size_label(total))}\n")


def publish_exclusive(temporary, target):
    """Publish a verified file atomically without overwriting a concurrent file."""
    try:
        os.link(temporary, target)
    except OSError as exc:
        if exc.errno not in {errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP, errno.ENOSYS, errno.EXDEV}:
            raise
        if sys.platform != "darwin":
            raise ValueError("This filesystem does not support safe file publication.") from exc
        # FAT32 cannot hard-link. macOS renamex_np(RENAME_EXCL) provides an
        # atomic rename which fails if the destination already exists.
        libc = ctypes.CDLL(None, use_errno=True)
        rename = libc.renamex_np
        rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        if rename(os.fsencode(temporary), os.fsencode(target), 0x00000004):
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error), str(target))
    else:
        temporary.unlink()


def copy_song(row, player, ensure_connected, progress=None):
    record = row["record"]
    source = row["source"]
    update = progress or (lambda stage, done, total: None)
    update("copying", 0, row["size"])
    stat = source.stat()
    if (stat.st_size, stat.st_mtime_ns) != row["stamp"]:
        raise ValueError(f"Source changed after the preview: {row['key']}. Run push again.")
    ensure_connected()
    target = destination(player, record["target"])
    if target.exists():
        update("verifying", row["size"], row["size"])
        if digest(target) != record["sha256"]:
            raise ValueError(f"A different file already exists: {record['target']}; left untouched.")
        ensure_connected()
        return
    if shutil.disk_usage(player).free < row["size"] + 1024 * 1024:
        raise ValueError("The Walkman is full. Finished songs are remembered; remaining songs stay pending.")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(record["temp"])
    if temporary.is_symlink():
        raise ValueError("The temporary destination is a symbolic link; stopped.")
    try:
        with source.open("rb") as incoming, temporary.open("wb") as outgoing:
            done = 0
            while block := incoming.read(1024 * 1024):
                ensure_connected()
                outgoing.write(block)
                done += len(block)
                update("copying", done, row["size"])
            update("flushing", done, row["size"])
            outgoing.flush()
            os.fsync(outgoing.fileno())
        ensure_connected()
        update("verifying", done, row["size"])
        if temporary.stat().st_size != row["size"] or digest(temporary) != record["sha256"]:
            raise ValueError(f"Copy verification failed: {row['key']}")
        ensure_connected()
        publish_exclusive(temporary, target)
        ensure_connected()
    except OSError as exc:
        # A disappearing FAT volume can report I/O errors before the mount
        # disappears from /Volumes. Preserve pending history in either case.
        ensure_connected()
        if exc.errno in USB_ERRORS:
            raise PlayerDisconnected("USB transfer interrupted.") from exc
        raise
    finally:
        # Never touch a new volume mounted at the same path after a disconnect.
        try:
            ensure_connected()
        except (OSError, ValueError):
            pass
        else:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                # Cleanup must not mask the original disconnect. The recorded
                # temporary name is reused and cleaned up on the next attempt.
                pass


def run(library, player, player_id, state_dir, dry_run=False, now=None, ensure_connected=None, reconnect=None):
    library, player = library.resolve(), player.resolve()
    if not library.is_dir():
        raise ValueError(f"MP3 Library not found: {library}. Run musesh mp3 first.")
    if library == player or player in library.parents or library in player.parents:
        raise ValueError("The local MP3 Library and player must be separate folders.")
    now = time.time() if now is None else now
    state_path = state_dir / (hashlib.sha256(player_id.encode()).hexdigest() + ".json")
    state = json.loads(state_path.read_text()) if state_path.exists() else {
        "version": 1, "player": player_id, "cutoff": now - RECENT_DAYS * 86400, "songs": {}}
    if state.get("version") != 1 or state.get("player") != player_id:
        raise ValueError("Unsupported push history; stopped without touching player music.")
    if ensure_connected is None:
        watcher = ConnectionWatcher(player, player_id)
        ensure_connected = watcher.ensure_connected
        reconnect = watcher.wait

    ensure_connected()
    files = source_files(library)
    rows = plan(files, player, state)
    free = shutil.disk_usage(player).free
    preview(rows, library, player, state, free)
    if dry_run:
        note("Preview only: no files copied and no push history changed.")
        return 0
    if not rows:
        save_json(state_path, state)
        save_json(state_dir / "player.json", {"uuid": player_id, "mount": str(player)})
        return 0
    required = sum(row["size"] for row in rows) + RESERVE
    if required > free:
        warn(f"Not enough room: need {size_label(required)} including a small safety reserve. Nothing copied.")
        return 1
    if prompt(f"{accent('?')} Add these {len(rows)} songs to the Walkman? {dim('[y/N]')} ").strip().lower() not in ("y", "yes"):
        note("Cancelled. Nothing copied and push history unchanged.")
        return 0
    # Persist pending work BEFORE copying, then acknowledge each verified song.
    # No timestamp cursor advances past a failed song.
    save_json(state_path, state)
    save_json(state_dir / "player.json", {"uuid": player_id, "mount": str(player)})
    connection_log(f"CONNECTED · {player} · watching USB connection during the confirmed batch.")
    for index, row in enumerate(rows, 1):
        while True:
            progress = UploadProgress(index, len(rows), row)
            try:
                try:
                    copy_song(row, player, ensure_connected, progress.update)
                except OSError as exc:
                    # Include errors before copy_song opens its temporary file,
                    # such as checking the free space on a disappearing mount.
                    ensure_connected()
                    if exc.errno in USB_ERRORS:
                        raise PlayerDisconnected("USB transfer interrupted.") from exc
                    raise
            except PlayerDisconnected:
                if reconnect is None:
                    progress.finish(False)
                    raise
                progress.pause()
                player = reconnect(index, len(rows), row)
                save_json(state_dir / "player.json", {"uuid": player_id, "mount": str(player)})
                continue
            except BaseException:
                progress.finish(False)
                raise
            break
        try:
            row["record"]["status"] = "handled"
            row["record"]["uploaded_at"] = time.time()
            save_json(state_path, state)
        except BaseException:
            progress.finish(False)
            raise
        progress.finish(True)
    print()
    ok(f"Added {len(rows)} songs ({size_label(sum(row['size'] for row in rows))}).")
    note("Deleting these from the Walkman later will not make push add them again.")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="musesh push", description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="show every proposed addition without copying or recording anything")
    parser.add_argument("--library", type=Path, default=ROOT / "Library", help="local MP3 Library folder")
    parser.add_argument("--player", type=Path, help="mounted external player volume (normally detected automatically)")
    args = parser.parse_args(argv)
    try:
        player, identity = find_player(STATE, args.player)
        if args.dry_run:
            return run(args.library.expanduser(), player, identity, STATE, dry_run=True)
        STATE.mkdir(parents=True, exist_ok=True)
        with (STATE / "lock").open("w") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError("Another push is already running.") from None
            return run(args.library.expanduser(), player, identity, STATE)
    except (OSError, ValueError, sqlite3.Error, subprocess.SubprocessError) as exc:
        warn(str(exc))
        return 1
    except (KeyboardInterrupt, EOFError):
        note("Stopped. Finished songs are remembered; rerun push to resume.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
