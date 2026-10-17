"""Durable local addition dates, carried from native audio to MP3 copies."""

import sqlite3
import time
from pathlib import Path
from contextlib import closing


def added_at(path, root, timestamp=None):
    path, root = Path(path), Path(root)
    state = root / ".musesh"
    state.mkdir(parents=True, exist_ok=True)
    # Existing collections predate tracking: creation time is the best local
    # approximation. mtime is the fallback on filesystems without birthtime.
    stat = path.stat()
    date = timestamp if timestamp is not None else getattr(stat, "st_birthtime", stat.st_mtime)
    with closing(sqlite3.connect(state / "added.sqlite3", timeout=30)) as db, db:
        db.execute("CREATE TABLE IF NOT EXISTS additions (path TEXT PRIMARY KEY, added REAL NOT NULL)")
        key = path.relative_to(root).as_posix()
        db.execute("INSERT OR IGNORE INTO additions VALUES (?, ?)", (key, date))
        return db.execute("SELECT added FROM additions WHERE path = ?", (key,)).fetchone()[0]


def record_new(path, root):
    return added_at(path, root, time.time())


def inventory(root):
    root = Path(root)
    extensions = {".mp3", ".m4a", ".flac", ".wav", ".aif", ".aiff", ".ogg", ".opus", ".aac"}
    if root.is_dir():
        for path in root.rglob("*"):
            if (path.is_file() and not path.is_symlink() and path.suffix.lower() in extensions
                    and not any(p.startswith(".") for p in path.relative_to(root).parts)
                    and not path.name.endswith(".part.mp3")):
                yield path
