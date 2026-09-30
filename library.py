"""Library overview: bands, their albums, song counts, sizes, formats and partial albums.

  library.py <folder> [--by name|size|songs] [filter words...]

Band and album names come from each file's tags (album artist, then artist), falling
back to the Artist/Album folder names for untagged files. Tags are read on several
threads and cached in ~/.cache/musesh/library.json, so repeat runs only read new or
changed files. Run with the Python inside gamdl's environment (it has mutagen).
"""

import argparse
import json
import os
import re
import shutil
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import mutagen

sys.path.insert(0, str(Path(__file__).resolve().parent))
import formats  # noqa: E402  (format probing, pager)
from ui import accent, bold, die, dim, heading, note, tilde, yellow  # noqa: E402

CACHE = Path.home() / ".cache" / "musesh" / "library.json"
CACHE_VERSION = 1


# ---------------------------------------------------------------------------
# Reading files
# ---------------------------------------------------------------------------

def first(tags, key):
    try:
        v = tags.get(key)
    except Exception:
        return ""
    return (v[0] if isinstance(v, list) and v else v or "").strip() if v else ""


def number_pair(text):
    """'3/12' -> (3, 12); '3' -> (3, 0); '' -> (0, 0)."""
    m = re.match(r"\s*(\d+)?\s*(?:/\s*(\d+))?", text or "")
    return (int(m.group(1) or 0), int(m.group(2) or 0)) if m else (0, 0)


def read(path):
    info = formats.probe(path)  # type, codec, bitrate, size ...
    try:
        tags = mutagen.File(path, easy=True) or {}
    except Exception:
        tags = {}
    track, tracks = number_pair(first(tags, "tracknumber"))
    disc, discs = number_pair(first(tags, "discnumber"))
    return {"size": info["size"], "format": format_label(info),
            "albumartist": first(tags, "albumartist"), "artist": first(tags, "artist"),
            "album": first(tags, "album"), "track": track, "tracks": tracks,
            "disc": disc or 1, "discs": discs}


def format_label(info):
    """Short quality label, e.g. 'AAC 256', 'MP3 320', 'MP3 VBR', 'ALAC 24-bit'."""
    if "error" in info:
        return "unreadable"
    codec = {"AAC LC": "AAC", "HE-AAC": "HE-AAC", "HE-AAC v2": "HE-AAC"}.get(info["codec"], info["codec"])
    if info.get("lossless"):
        return f"{codec} {info['bits']}-bit" if info.get("bits") and info["bits"] != 16 else codec
    if info.get("mode") in ("VBR", "ABR"):
        return f"{codec} VBR"
    kbps = formats.nominal_kbps(info["bitrate"])
    return f"{codec} {kbps}" if kbps else codec


def read_many(paths):
    return [(str(p), read(p)) for p in paths]


def scan(root):
    files = sorted(p for p in root.rglob("*")
                   if p.suffix.lower() in formats.AUDIO_EXTS and p.is_file()
                   and not {".library-dl", ".musesh"} & set(p.relative_to(root).parts))
    try:
        cache = json.loads(CACHE.read_text())
        if cache.get("_version") != CACHE_VERSION:
            cache = {}
    except (OSError, ValueError):
        cache = {}
    results, todo = {}, []
    for p in files:
        st = p.stat()
        hit = cache.get(str(p))
        if hit and hit[0] == st.st_mtime and hit[1] == st.st_size:
            results[str(p)] = hit[2]
        else:
            todo.append(p)
    if todo:
        chunks = [todo[i:i + 50] for i in range(0, len(todo), 50)]
        pool = ThreadPoolExecutor(max_workers=min(16, (os.cpu_count() or 4) * 2))
        try:
            got = [r for chunk in pool.map(read_many, chunks) for r in chunk]
        except KeyboardInterrupt:
            pool.shutdown(wait=False, cancel_futures=True)
            raise
        pool.shutdown()
        for path, info in got:
            st = Path(path).stat()
            cache[path] = [st.st_mtime, st.st_size, info]
            results[path] = info
        prefix = str(root) + os.sep
        for path in [k for k in cache if k.startswith(prefix) and k not in results]:
            del cache[path]
        cache["_version"] = CACHE_VERSION
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(cache))
    return [(Path(p), results[str(p)]) for p in files], len(todo)


# ---------------------------------------------------------------------------
# Grouping
# ---------------------------------------------------------------------------

def names_for(path, root, info):
    """(band, album) from tags, falling back to the Artist/Album folders."""
    parts = path.relative_to(root).parts
    folder_band = parts[0] if len(parts) >= 3 else ""
    folder_album = parts[-2] if len(parts) >= 2 else ""
    band = info["albumartist"] or info["artist"]
    if not band and folder_band not in ("", "Unknown Artist", "Compilations"):
        band = folder_band
    album = info["album"] or ("" if folder_album == "Unknown Album" else folder_album)
    return band or "Unknown Artist", album or "Unknown Album"


def sort_key_name(name):
    """Alphabetical, ignoring case, accents and a leading 'The '."""
    return re.sub(r"^the\s+", "", formats_norm(name))


def formats_norm(s):
    import unicodedata
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().casefold().strip()


def build(files, root):
    """Group by band and album, ignoring differences in capitalisation ('Nettspend' vs
    'nettspend'); each group is shown under its most common spelling."""
    groups = defaultdict(lambda: defaultdict(list))
    spellings = defaultdict(Counter)
    for path, info in files:
        band, album = names_for(path, root, info)
        bkey, akey = formats_norm(band), (formats_norm(band), formats_norm(album))
        spellings[bkey][band] += 1
        spellings[akey][album] += 1
        groups[bkey][akey].append(info)
    return {spellings[bkey].most_common(1)[0][0]:
            {spellings[akey].most_common(1)[0][0]: songs for akey, songs in albums.items()}
            for bkey, albums in groups.items()}


def mixed_label(labels):
    """'MP3 128', 'MP3 320' -> 'MP3 128-320 mixed'; different codecs -> 'mixed: AAC 256, MP3 320'."""
    codecs = {l.rsplit(" ", 1)[0] for l in labels}
    rates = sorted(int(l.rsplit(" ", 1)[1]) for l in labels if l.rsplit(" ", 1)[-1].isdigit())
    vbr = any(l.endswith(" VBR") for l in labels)
    if len(codecs) == 1 and rates and len(rates) + vbr == len(labels):
        span = f"{rates[0]}-{rates[-1]}" if len(rates) > 1 else str(rates[0])
        return f"{codecs.pop()} {span}{' +VBR' if vbr else ''} mixed"
    return "mixed: " + ", ".join(labels)


def album_stats(songs):
    have = len(songs)
    size = sum(s["size"] for s in songs)
    labels = sorted({s["format"] for s in songs})
    fmt = labels[0] if len(labels) == 1 else mixed_label(labels)
    # Expected songs: per-disc track totals from the tags. Without any track totals the
    # album's size is unknown, so it's never called partial.
    per_disc = {}
    for s in songs:
        if s["tracks"]:
            per_disc[s["disc"]] = max(per_disc.get(s["disc"], 0), s["tracks"])
    discs = max((s["discs"] for s in songs), default=0)
    expected = None
    if per_disc and (not discs or len(per_disc) >= discs):
        expected = sum(per_disc.values())
    elif per_disc and discs > len(per_disc):
        expected = -discs  # whole discs missing: the total is unknown, but it's partial
    partial = expected is not None and (expected < 0 or have < expected)
    return {"songs": have, "size": size, "format": fmt, "expected": expected, "partial": partial,
            "discs_have": len(per_disc), "discs": discs}


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def size_label(n):
    return f"{n / 1024 ** 3:.1f} GB" if n >= 1024 ** 3 else f"{n / 1024 ** 2:.0f} MB"


def plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def songs_label(st):
    if st["partial"] and st["expected"] and st["expected"] > 0:
        return f"{st['songs']}/{st['expected']} songs"
    return plural(st["songs"], "song")


def render(bands, root, by, total_files, total_size):
    rows = []  # (kind, name, albums, songs, size, fmt, flag)
    band_list = []
    for band, albums in bands.items():
        stats = {album: album_stats(songs) for album, songs in albums.items()}
        band_list.append((band, stats, sum(s["songs"] for s in stats.values()), sum(s["size"] for s in stats.values())))

    if by == "size":
        band_list.sort(key=lambda b: (-b[3], sort_key_name(b[0])))
    elif by == "songs":
        band_list.sort(key=lambda b: (-b[2], sort_key_name(b[0])))
    else:
        band_list.sort(key=lambda b: sort_key_name(b[0]))

    partial_total = 0
    for band, stats, songs, size in band_list:
        partials = sum(1 for s in stats.values() if s["partial"])
        partial_total += partials
        album_word = plural(len(stats), "album")
        rows.append(("band", band, album_word, plural(songs, "song"), size_label(size), "",
                     f"{partials} partial" if partials else ""))
        order = sorted(stats.items(), key=lambda a: (-a[1]["size"], sort_key_name(a[0]))) if by == "size" else \
            sorted(stats.items(), key=lambda a: (-a[1]["songs"], sort_key_name(a[0]))) if by == "songs" else \
            sorted(stats.items(), key=lambda a: sort_key_name(a[0]))
        for album, st in order:
            flag = ""
            if st["partial"]:
                flag = f"partial, {st['discs_have']}/{st['discs']} discs" if st["expected"] < 0 else "partial"
            rows.append(("album", album, "", songs_label(st), size_label(st["size"]), st["format"], flag))

    n_albums = sum(len(s) for _, s, _, _ in band_list)
    heading(f"Library in {tilde(root)}")
    note(f"{plural(len(band_list), 'band')}, {plural(n_albums, 'album')}, {plural(total_files, 'song')}, "
         f"{size_label(total_size)}" + (f"  -  {partial_total} partial album(s)" if partial_total else ""))
    print()
    if not rows:
        return []

    term = shutil.get_terminal_size((160, 40)).columns
    w_albums = max(len(r[2]) for r in rows)
    w_songs = max(len(r[3]) for r in rows)
    w_size = max(len(r[4]) for r in rows)
    w_fmt = min(max(len(r[5]) for r in rows), 28)
    fixed = w_albums + w_songs + w_size + w_fmt + 12 + 14
    longest = max(len(r[1]) + (2 if r[0] == "album" else 0) for r in rows)
    w_name = max(min(longest, term - fixed, 44), 16)  # long album titles are trimmed with …

    def fit(text, width):
        return text if len(text) <= width else text[:width - 1] + "…"

    lines = []
    for kind, name, albums, songs, size, fmt, flag in rows:
        if kind == "band":
            if lines:
                lines.append("")
            label = fit(name, w_name).ljust(w_name)
            lines.append(f"  {accent(bold(label))}  {dim(albums.rjust(w_albums))}  {songs.rjust(w_songs)}  "
                         f"{bold(size.rjust(w_size))}  {' ' * w_fmt}  {yellow(flag) if flag else ''}".rstrip())
        else:
            label = ("  " + fit(name, w_name - 2)).ljust(w_name)
            song_txt = songs.rjust(w_songs)
            lines.append(f"  {label}  {' ' * w_albums}  {yellow(song_txt) if flag else dim(song_txt)}  "
                         f"{dim(size.rjust(w_size))}  {dim(fit(fmt, w_fmt).ljust(w_fmt))}  "
                         f"{yellow(flag) if flag else ''}".rstrip())
    return lines


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", type=Path)
    ap.add_argument("--by", choices=("name", "size", "songs"), default="name")
    ap.add_argument("filter", nargs="*", help="only bands whose name contains these words")
    a = ap.parse_args()
    root = a.folder.expanduser().resolve()
    if not root.is_dir():
        die(f"Not a folder: {tilde(root)}")

    files, read_count = scan(root)
    if not files:
        die(f"No music in {tilde(root)}")
    bands = build(files, root)
    if a.filter:
        words = [formats_norm(w) for w in a.filter]
        bands = {b: albums for b, albums in bands.items() if all(w in formats_norm(b) for w in words)}
        if not bands:
            die(f"No band matching {' '.join(a.filter)!r}")
    shown = [info for albums in bands.values() for songs in albums.values() for info in songs]
    lines = render(bands, root, a.by, len(shown), sum(i["size"] for i in shown))
    if read_count:
        note(f"(read tags from {read_count} new or changed file(s); later runs use the cache)")
        print()
    formats.show(lines)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n  {dim('stopped')}")
        sys.exit(130)
    except BrokenPipeError:
        sys.stderr.close()
        sys.exit(0)
