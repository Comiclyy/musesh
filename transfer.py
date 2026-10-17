"""Prepare local MP3 batches for an unattended Windows player transfer."""

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid
import unicodedata

from music_dates import added_at, inventory

ROOT = Path.home() / "Music" / "musesh"
STATE = ROOT / ".transfer"
HERE = Path(__file__).resolve().parent
GAMDL_PYTHON = Path.home() / ".local/pipx/venvs/gamdl/bin/python"


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    try:
        tmp.write_text(json.dumps(value, indent=2), encoding="utf-8")
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def windows_path(relative):
    parts = []
    for part in relative.parts:
        part = unicodedata.normalize("NFC", part)
        part = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", part).rstrip(" .") or "_"
        if re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", part):
            part = "_" + part
        # Keep room for the temporary/conflict suffix on common player filesystems.
        if len(part.encode("utf-8")) > 72 or len(part) > 48:
            suffix = Path(part).suffix
            tag = hashlib.sha256(part.encode()).hexdigest()[:12]
            prefix = part[:28].encode()[:45].decode("utf-8", "ignore")
            part = prefix + "-" + tag + suffix
        parts.append(part)
    return "/".join(parts)


def dates(value):
    if value is None:
        return None
    pieces = value.split("..")
    if len(pieces) not in (1, 2):
        raise ValueError("Use YYYY-MM-DD or YYYY-MM-DD..YYYY-MM-DD.")
    start = dt.date.fromisoformat(pieces[0])
    end = dt.date.fromisoformat(pieces[-1])
    if start > end:
        raise ValueError("The end date must be on or after the start date.")
    return start, end


def receipts(share):
    result = set()
    for path in (share / "receipts").glob("*.json"):
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        if value.get("version") != 1 or not isinstance(value.get("id"), str):
            raise ValueError(f"Invalid transfer receipt: {path}")
        result.add(value["id"])
    return result


def setup(share, sources):
    share = share.expanduser().resolve()
    if not share.is_dir():
        raise ValueError("Mount the Windows shared folder first, then give its existing path.")
    config = STATE / "settings.json"
    if config.exists():
        previous = json.loads(config.read_text())
        baseline = previous["baseline"]
    else:
        baseline = time.time()
    if not sources:
        settings_path = Path.home() / ".config/musesh/settings.json"
        settings = json.loads(settings_path.read_text()) if settings_path.exists() else {}
        sources = [Path(settings.get("output", ROOT / "Incoming")), ROOT / "Library"]
        extra = Path(settings.get("mp3_dir", ROOT / "Library"))
        if extra not in sources and not str(extra).startswith("/Volumes/"):
            sources.append(extra)
    sources = list(dict.fromkeys(p.expanduser().resolve() for p in sources))
    for source in sources:
        if source == share or source in share.parents or share in source.parents:
            raise ValueError("The shared folder and music sources must be separate folders.")
        for path in inventory(source):
            added_at(path, source)
    for name in ("musesh-transfer.cmd", "musesh-transfer.ps1"):
        tmp = share / (name + ".tmp")
        shutil.copyfile(HERE / "windows" / name, tmp)
        tmp.replace(share / name)
    (share / "batches").mkdir(exist_ok=True)
    (share / "receipts").mkdir(exist_ok=True)
    save_json(config, {"version": 1, "share": str(share), "baseline": baseline,
                       "sources": [str(p) for p in sources]})
    print(f"Saved Windows handoff: {share}")
    print("Existing music is excluded from automatic selection; explicit dates can include it.")
    print("Historical addition dates use file creation time (mtime if unavailable).")
    print("On Windows, once: musesh-transfer.cmd setup E:  (use your player's drive)")
    print("After that: musesh-transfer.cmd")


def selected(config, interval):
    chosen = {}
    for source in map(Path, config["sources"]):
        for path in sorted(inventory(source)):
            relative = path.relative_to(source).with_suffix(".mp3")
            key = relative.as_posix()
            date = added_at(path, source)
            if key in chosen:
                # Incoming is authoritative; Library may be its converted copy.
                if chosen[key][1] == source:
                    raise ValueError(f"Two source files map to {relative}; rename one before preparing.")
                continue
            chosen[key] = (path, source, date, relative)
    mapping_file = STATE / "paths.json"
    mapping = json.loads(mapping_file.read_text()) if mapping_file.exists() else {}
    claimed = {target.casefold(): key for key, target in mapping.items()}
    for key, (_, _, _, relative) in chosen.items():
        if key in mapping:
            continue
        target = windows_path(relative)
        if target.casefold() in claimed:
            tag = hashlib.sha256(key.encode()).hexdigest()[:12]
            target = target[:-4] + " [" + tag + "].mp3"
        if target.casefold() in claimed:
            raise ValueError(f"Windows filename collision: {relative}. Rename the conflicting song.")
        mapping[key] = target
        claimed[target.casefold()] = key
    save_json(mapping_file, mapping)
    for key, (path, source, date, relative) in chosen.items():
        day = dt.datetime.fromtimestamp(date).date()
        if interval:
            include = interval[0] <= day <= interval[1]
        else:
            include = date > config["baseline"]
        if include:
            yield path, source, date, Path(mapping[key])


def mp3_copy(src, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.suffix.lower() == ".mp3":
        shutil.copyfile(src, dest)
    else:
        fingerprint = digest(src)
        cache = STATE / "cache" / (fingerprint + ".mp3")
        if cache.exists():
            shutil.copyfile(cache, dest)
            return
        # Use the existing conversion implementation and its gamdl dependencies.
        python = GAMDL_PYTHON if GAMDL_PYTHON.exists() else Path(sys.executable)
        code = ("import sys; from pathlib import Path; import mp3; "
                "error = mp3.run_job('convert', Path(sys.argv[1]), Path(sys.argv[2])); "
                "sys.exit(error or 0)")
        subprocess.run([str(python), "-c", code, str(src), str(dest)], cwd=HERE, check=True)
        if digest(src) != fingerprint:
            raise ValueError(f"Source changed during conversion: {src}. Run prepare again.")
        cache.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(dest, cache.with_suffix(".tmp"))
        cache.with_suffix(".tmp").replace(cache)


def prepare(value=None):
    interval = dates(value)
    config_path = STATE / "settings.json"
    if not config_path.exists():
        raise ValueError("First run: musesh transfer setup /Volumes/YourWindowsShare")
    config = json.loads(config_path.read_text())
    batch_id = uuid.uuid4().hex
    local = STATE / "pending" / batch_id
    local.mkdir(parents=True)
    files, used = [], set()
    try:
        for src, source, date, relative in selected(config, interval):
            before = src.stat()
            target = relative.as_posix()
            if target.casefold() in used:
                raise ValueError(f"Windows filename collision: {relative}. Rename the conflicting song.")
            used.add(target.casefold())
            dest = local / "music" / target
            mp3_copy(src, dest)
            after = src.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ValueError(f"Source changed during preparation: {src}. Run prepare again.")
            sha = digest(dest)
            item_id = hashlib.sha256((target.casefold() + "\0" + sha).encode()).hexdigest()
            files.append({"id": item_id, "path": target, "sha256": sha,
                          "size": dest.stat().st_size, "added_at": date})
        if files:
            save_json(local / "manifest.json", {"version": 1, "batch_id": batch_id, "files": files})
        else:
            shutil.rmtree(local)
    except BaseException:
        shutil.rmtree(local)
        raise
    print(f"Prepared {len(files)} song(s) locally.")
    publish(config)


def publish(config):
    share = Path(config["share"])
    if not share.is_dir() or not (share / "batches").is_dir():
        raise ValueError("Windows share unavailable. Prepared files are kept; reconnect and run musesh prepare again.")
    acknowledged = receipts(share)
    # Fully acknowledged batches can be removed from the Windows inbox; receipts
    # persist. Never remove any music from the player or the original collection.
    for batch in (share / "batches").iterdir():
        if batch.name.startswith(".") or not batch.is_dir():
            continue
        manifest = json.loads((batch / "manifest.json").read_text(encoding="utf-8"))
        if all(item["id"] in acknowledged for item in manifest["files"]):
            shutil.rmtree(batch)
    queued = set()
    for path in (share / "batches").glob("*/manifest.json"):
        if not path.parent.name.startswith("."):
            queued.update(f["id"] for f in json.loads(path.read_text())["files"] if f["id"] not in acknowledged)
    sent = 0
    for local in sorted((STATE / "pending").glob("*")):
        if not (local / "manifest.json").exists():
            # A killed preparation never published this batch; selected sources
            # are still available to a subsequent preparation.
            shutil.rmtree(local)
            continue
        manifest = json.loads((local / "manifest.json").read_text())
        items = [f for f in manifest["files"] if f["id"] not in acknowledged | queued]
        if items:
            stage = share / "batches" / (".upload-" + local.name)
            final = share / "batches" / local.name
            if stage.exists():
                shutil.rmtree(stage)
            stage.mkdir()
            for item in items:
                src, dest = local / "music" / item["path"], stage / "music" / item["path"]
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, dest)
                if digest(dest) != item["sha256"]:
                    raise ValueError(f"Network copy verification failed: {item['path']}. Retry musesh prepare.")
            save_json(stage / "manifest.json", {**manifest, "files": items})
            stage.rename(final)
            queued.update(f["id"] for f in items)
            sent += len(items)
        shutil.rmtree(local)
    print(f"Published {sent} song(s); {len(queued)} queued on Windows. Connect the player and run musesh-transfer.cmd.")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="musesh transfer", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    setup_parser = sub.add_parser("setup", prog="musesh transfer setup", help="one-time Windows shared-folder setup")
    setup_parser.add_argument("share", type=Path)
    setup_parser.add_argument("--source", type=Path, action="append", help="custom source folder (repeatable)")
    prep = sub.add_parser("prepare", prog="musesh prepare", help="new, unuploaded songs; optionally a day or date range")
    prep.add_argument("date", nargs="?", help="YYYY-MM-DD or YYYY-MM-DD..YYYY-MM-DD")
    args = parser.parse_args(argv)
    STATE.mkdir(parents=True, exist_ok=True)
    # macOS-side preparation and publishing must not race each other.
    import fcntl
    with (STATE / "lock").open("w") as lock:
        try:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError("Another preparation is running. Wait for it to finish and retry.") from None
            if args.command == "setup":
                setup(args.share, args.source)
            else:
                prepare(args.date)
        except (OSError, ValueError, subprocess.CalledProcessError) as exc:
            print(f"Transfer: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
