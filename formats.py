"""Audio format report for a music folder: codec, bitrate, sample rate, bit depth, channels, size.

  formats.py [summary|all|diff] [folder]

Only file headers are read (no decoding), on several threads, and results are cached in
~/.cache/musesh/formats.json, so repeat runs only look at new or changed files.
Run with the Python inside gamdl's environment (it has mutagen); musesh does this.
"""

import json
import os
import shutil
import signal
import subprocess
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import mutagen

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ui import COLOR, accent, bold, cyan, die, dim, green, heading, note, tilde, yellow  # noqa: E402

AUDIO_EXTS = {".m4a", ".m4p", ".mp3", ".flac", ".wav", ".aif", ".aiff", ".ogg", ".opus", ".aac"}
CACHE = Path.home() / ".cache" / "musesh" / "formats.json"
STANDARD_KBPS = (32, 48, 64, 96, 112, 128, 160, 192, 224, 256, 320)
LOSSLESS_CODECS = {"ALAC", "FLAC", "PCM"}


# ---------------------------------------------------------------------------
# Probing (runs in worker processes)
# ---------------------------------------------------------------------------

def probe(path):
    """Header-only facts about one file. Never raises; unreadable files get an 'error'."""
    p = Path(path)
    info = {"type": p.suffix.lower().lstrip(".").upper(), "size": p.stat().st_size}
    try:
        f = mutagen.File(p)
    except Exception as e:  # corrupt or truncated file
        return {**info, "error": str(e)[:60]}
    if f is None:
        return {**info, "error": "not a recognised audio file"}
    i = f.info
    kind = type(f).__name__
    codec, mode, encoder = "?", "", ""
    if kind == "MP4":
        codec = {"alac": "ALAC", "mp4a.40.2": "AAC LC", "mp4a.40.5": "HE-AAC", "mp4a.40.29": "HE-AAC v2",
                 "ac-3": "AC-3", "ec-3": "E-AC-3"}.get(getattr(i, "codec", ""), getattr(i, "codec_description", "?"))
    elif kind == "MP3":
        codec = f"MP3 L{i.layer}" if getattr(i, "layer", 3) != 3 else "MP3"
        mode = {1: "CBR", 2: "VBR", 3: "ABR"}.get(int(getattr(i, "bitrate_mode", 0)), "CBR")
        encoder = " ".join(x for x in (i.encoder_info, i.encoder_settings) if x)
    elif kind == "FLAC":
        codec = "FLAC"
    elif kind in ("WAVE", "AIFF"):
        codec = "PCM"
    elif kind == "OggVorbis":
        codec = "Vorbis"
    elif kind == "OggOpus":
        codec = "Opus"
    else:
        codec = kind
    lossless = codec in LOSSLESS_CODECS
    return {**info,
            "codec": codec, "lossless": lossless, "mode": mode, "encoder": encoder,
            "bitrate": int(getattr(i, "bitrate", 0) or 0),
            "rate": int(getattr(i, "sample_rate", 0) or 0),
            "bits": int(getattr(i, "bits_per_sample", 0) or 0) if lossless else 0,
            "channels": int(getattr(i, "channels", 0) or 0),
            "protected": p.suffix.lower() == ".m4p"}


def probe_many(paths):
    return [(str(p), probe(p)) for p in paths]


def scan(root):
    """Probe every audio file under root, reusing cached results for unchanged files."""
    files = sorted(p for p in root.rglob("*")
                   if p.suffix.lower() in AUDIO_EXTS and ".library-dl" not in p.parts and p.is_file())
    try:
        cache = json.loads(CACHE.read_text())
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
        # Header reads mostly wait on the disk, so threads overlap them well; unlike worker
        # processes they also stop cleanly on Ctrl-C.
        chunks = [todo[i:i + 50] for i in range(0, len(todo), 50)]
        pool = ThreadPoolExecutor(max_workers=min(16, (os.cpu_count() or 4) * 2))
        try:
            probed = [r for chunk in pool.map(probe_many, chunks) for r in chunk]
        except KeyboardInterrupt:
            pool.shutdown(wait=False, cancel_futures=True)
            raise
        pool.shutdown()
        for path, info in probed:
            st = Path(path).stat()
            cache[path] = [st.st_mtime, st.st_size, info]
            results[path] = info
        # Drop entries for files under this folder that no longer exist.
        prefix = str(root) + os.sep
        for path in [k for k in cache if k.startswith(prefix) and k not in results]:
            del cache[path]
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(cache))
    return [(Path(path), results[path]) for path in map(str, files)], len(todo)


# ---------------------------------------------------------------------------
# Presentation
# ---------------------------------------------------------------------------

def nominal_kbps(bps):
    """AAC/MP3 headers report e.g. 256000 or 259341; show the standard rate it was encoded at."""
    kbps = bps / 1000
    return min(STANDARD_KBPS, key=lambda s: abs(s - kbps)) if kbps else 0


def bitrate_label(info, exact=False):
    if info.get("lossless"):
        return f"{round(info['bitrate'] / 1000)} kbps" if exact and info["bitrate"] else "lossless"
    kbps = nominal_kbps(info["bitrate"])
    if info.get("mode") in ("VBR", "ABR"):
        # VBR averages vary per song: group them to the nearest 32 kbps, show the real average per file.
        return f"~{round(info['bitrate'] / 1000)} kbps" if exact else f"~{round(info['bitrate'] / 32000) * 32} kbps"
    return f"{kbps} kbps" if kbps else "?"


def rate_label(hz):
    return f"{hz / 1000:g} kHz" if hz else "?"


def channels_label(n):
    return {1: "mono", 2: "stereo"}.get(n, f"{n} ch" if n else "?")


def size_label(n):
    return f"{n / 1024 ** 3:.2f} GB" if n >= 1024 ** 3 else f"{n / 1024 ** 2:.1f} MB"


def signature(info):
    """What makes two files 'the same format' for grouping."""
    if "error" in info:
        return ("unreadable",)
    return (info["type"], info["codec"], bitrate_label(info), info.get("mode", ""), info["rate"],
            info["bits"], info["channels"], info.get("protected", False))


def fields(info, exact=True):
    """The | separated values for one file or one group."""
    if "error" in info:
        return [info["type"], "unreadable", info["error"], "", "", "", "", ""]
    quality = "lossless" if info["lossless"] else "lossy"
    return [info["type"] + (" DRM" if info.get("protected") else ""),
            info["codec"],
            bitrate_label(info, exact=exact),
            info.get("mode") or ("" if info["lossless"] else "CBR" if info["type"] == "MP3" else ""),
            rate_label(info["rate"]),
            f"{info['bits']}-bit" if info["bits"] else "",
            channels_label(info["channels"]),
            quality]


TYPE_COLORS = {"M4A": cyan, "M4P": yellow, "MP3": yellow, "FLAC": green, "WAV": green, "AIFF": green, "AIF": green}


def colorize(col, value, info):
    if not COLOR or not value:
        return value
    if col == 0:
        return TYPE_COLORS.get(info.get("type"), accent)(value)
    if col == 1:
        return bold(value)
    if col == 7:
        return green(value) if value == "lossless" else dim(value)
    if value == "unreadable":
        return yellow(value)
    return value


def table(rows, lead_header=None, lead_align="left"):
    """rows: [(lead, [values...], info, trail)] -> aligned lines with ' | ' between values.
    The lead column (path or count) is fitted to the terminal width, cutting from the left."""
    # Drop columns that are empty on every row (e.g. bit depth when nothing is lossless).
    keep = [c for c in range(max(len(r[1]) for r in rows)) if any(r[1][c] for r in rows)]
    col_of = {new: old for new, old in enumerate(keep)}
    rows = [(lead, [values[c] for c in keep], info, trail) for lead, values, info, trail in rows]
    ncols = len(keep)
    widths = [max(len(r[1][c]) for r in rows) for c in range(ncols)]
    trail_w = max(len(r[3]) for r in rows)
    sep = f" {dim('|')} "
    fixed = sum(widths) + 3 * (ncols + 1) + trail_w
    term = shutil.get_terminal_size((160, 40)).columns
    lead_w = max(min(max(len(r[0]) for r in rows), term - fixed - 2), 12)
    lines = []
    for lead, values, info, trail in rows:
        if len(lead) > lead_w:
            lead = "…" + lead[-(lead_w - 1):]
        lead_txt = lead.rjust(lead_w) if lead_align == "right" else lead.ljust(lead_w)
        cells = [colorize(col_of[c], values[c].ljust(widths[c]), info) if values[c] else " " * widths[c]
                 for c in range(ncols)]
        lead_txt = accent(lead_txt) if lead_align == "right" else dim(lead_txt)
        lines.append(f"  {lead_txt}{sep}{sep.join(cells)}{sep}{dim(trail.rjust(trail_w))}")
    return lines


def show(lines):
    """Print, through a pager when it won't fit on screen."""
    text = "\n".join(lines) + "\n"
    rows = shutil.get_terminal_size((160, 40)).lines
    if sys.stdout.isatty() and text.count("\n") > rows - 2 and shutil.which("less"):
        # Ctrl-C goes to the whole process group: -K makes less quit on it (as does q),
        # and Python ignores it meanwhile so it doesn't die mid-pipe with a traceback.
        previous = signal.signal(signal.SIGINT, signal.SIG_IGN)
        try:
            subprocess.run(["less", "-RFXK"], input=text.encode())
        except BrokenPipeError:
            pass
        finally:
            signal.signal(signal.SIGINT, previous)
    else:
        sys.stdout.write(text)


def main():
    args = sys.argv[1:]
    mode = args.pop(0) if args and args[0] in ("summary", "all", "diff") else "summary"
    root = Path(args[0]).expanduser().resolve() if args else None
    if root is None or not root.is_dir():
        die(f"Not a folder: {args[0] if args else '(none given)'}")

    files, probed = scan(root)
    if not files:
        die(f"No audio files in {tilde(root)}")
    total = sum(i["size"] for _, i in files)
    groups = Counter(signature(i) for _, i in files)
    example = {}
    sizes = Counter()
    for _, i in files:
        example.setdefault(signature(i), i)
        sizes[signature(i)] += i["size"]
    common, common_n = groups.most_common(1)[0]

    out = []
    heading(f"Formats in {tilde(root)}")
    note(f"{len(files)} files, {size_label(total)}, {len(groups)} distinct format(s)"
         + (f"  -  read {probed} new/changed file(s)" if probed else "  -  all from cache"))
    print()

    if mode == "summary":
        rows = []
        for sig, n in groups.most_common():
            share = f"{n / len(files):.0%}"
            rows.append((f"{n} file{'s' if n != 1 else ''}", fields(example[sig], exact=False), example[sig],
                         f"{size_label(sizes[sig])}  {share}"))
        out += table(rows, lead_align="right")
        out += ["", "  " + dim("musesh formats all  -  every file     musesh formats diff  -  only the odd ones out")]
    else:
        pick = files if mode == "all" else [(p, i) for p, i in files if signature(i) != common]
        if mode == "diff":
            c = example[common]
            print(f"  {dim('most common:')} {bold(' '.join(v for v in fields(c, exact=False) if v))}"
                  f"  {dim(f'({common_n} files)')}")
            if not pick:
                print(f"\n  {green('✓')} every file is in that format")
                return
            print(f"  {dim('files in any other format:')} {bold(len(pick))}\n")
            pick.sort(key=lambda pi: (signature(pi[1]), str(pi[0])))
        rows = [(tilde(p.relative_to(root)), fields(i), i, size_label(i["size"])) for p, i in pick]
        out += table(rows)
    show(out)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n  {dim('stopped')}")
        sys.exit(130)
    except BrokenPipeError:  # e.g. piped into `head`
        sys.stderr.close()
        sys.exit(0)
