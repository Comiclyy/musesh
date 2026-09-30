"""Mirror a music folder as 320 kbps MP3s, keeping the Artist/Album layout, tags and cover art.

  mp3.py <library folder> <mp3 folder> [--jobs N] [--yes]

Re-running is cheap: MP3s that already match are skipped (checked by reading their
headers, not just by name), MP3s in the wrong format are redone, and leftovers from
interrupted runs or other formats are cleaned up. MP3s in your library are copied as
they are - re-encoding them at 320 kbps would only make them bigger.

Run with the Python inside gamdl's environment (it has mutagen); musesh does this.
"""

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import mutagen

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ui import bold, cyan, die, dim, green, heading, note, ok, prompt, red, summary, tilde, warn, yellow  # noqa: E402

TARGET_KBPS = 320
SOURCE_EXTS = {".m4a", ".mp3", ".flac", ".wav", ".aif", ".aiff", ".ogg", ".opus", ".aac"}
LEFTOVER_AUDIO = SOURCE_EXTS | {".m4p"}
STATE_DIR = ".library-dl"
LENGTH_TOLERANCE = 2.0  # seconds; a shorter MP3 means an interrupted conversion
# In the MP3 folder: MP3s whose original was deleted by --prune (so they are not "orphans").
PRUNED_RECORD = Path(".musesh") / "pruned-originals.txt"


def pruned_mp3s(dst_root):
    record = dst_root / PRUNED_RECORD
    return {dst_root / line for line in record.read_text().splitlines() if line} if record.exists() else set()


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------

def length_of(path):
    try:
        f = mutagen.File(path)
        return f.info.length if f else 0
    except Exception:
        return 0


def dest_matches(src, dest):
    """True if dest is already the right MP3 for src."""
    if not dest.exists():
        return False
    if src.suffix.lower() == ".mp3":
        # Library MP3s are copied as-is; same size means it's the same file.
        return dest.stat().st_size == src.stat().st_size
    try:
        f = mutagen.File(dest)
    except Exception:
        return False
    if f is None or type(f).__name__ != "MP3":
        return False
    kbps = f.info.bitrate / 1000
    if abs(kbps - TARGET_KBPS) > 8 or int(getattr(f.info, "bitrate_mode", 1)) not in (0, 1):  # CBR
        return False
    return abs(f.info.length - length_of(src)) <= LENGTH_TOLERANCE


def plan(src_root, dst_root):
    sources = sorted(p for p in src_root.rglob("*")
                     if p.suffix.lower() in SOURCE_EXTS and STATE_DIR not in p.relative_to(src_root).parts
                     and p.is_file())
    protected = sorted(p for p in src_root.rglob("*.m4p"))
    jobs, up_to_date = [], 0
    wanted = set()
    for src in sources:
        dest = (dst_root / src.relative_to(src_root)).with_suffix(".mp3")
        wanted.add(dest)
        if dest_matches(src, dest):
            up_to_date += 1
        elif src.suffix.lower() == ".mp3":
            jobs.append(("copy", src, dest))
        else:
            jobs.append(("redo" if dest.exists() else "convert", src, dest))

    partials, wrong_format, orphans = [], [], []
    kept_on_purpose = pruned_mp3s(dst_root)
    if dst_root.exists():
        for p in dst_root.rglob("*"):
            if not p.is_file() or ".musesh" in p.relative_to(dst_root).parts or p in kept_on_purpose:
                continue
            name = p.name.lower()
            if name.endswith(".part.mp3"):
                partials.append(p)
            elif p.suffix.lower() in LEFTOVER_AUDIO and p.suffix.lower() != ".mp3":
                wrong_format.append(p)
            elif p.suffix.lower() == ".mp3" and p not in wanted:
                orphans.append(p)
    return jobs, up_to_date, protected, partials, wrong_format, sorted(orphans)


# ---------------------------------------------------------------------------
# Work
# ---------------------------------------------------------------------------

ACTIVE = set()  # temp files being written, removed if the run is stopped
ACTIVE_LOCK = threading.Lock()


def run_job(action, src, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    if action == "copy":
        shutil.copy2(src, dest)
        return None
    tmp = dest.with_name(dest.stem + ".part.mp3")
    with ACTIVE_LOCK:
        ACTIVE.add(tmp)
    cmd = ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(src),
           "-map", "0:a", "-map", "0:v?", "-c:a", "libmp3lame", "-b:a", f"{TARGET_KBPS}k",
           "-c:v", "copy", "-disposition:v", "attached_pic",
           "-map_metadata", "0", "-id3v2_version", "3", str(tmp)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            tmp.unlink(missing_ok=True)
            return (r.stderr.strip().splitlines() or ["ffmpeg failed"])[-1][:100]
        tmp.replace(dest)
        return None
    finally:
        with ACTIVE_LOCK:
            ACTIVE.discard(tmp)


def clock(seconds):
    seconds = int(max(seconds, 0))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h{m:02d}m" if h else f"{m}:{s:02d}"


LABELS = {"convert": green("converted"), "redo": yellow("redone   "), "copy": cyan("copied   "),
          "fail": red("failed   ")}


def run(src_root, dst_root, jobs_n, assume_yes=False):
    src_root, dst_root = src_root.resolve(), dst_root.resolve()
    if not src_root.is_dir():
        die(f"Not a folder: {tilde(src_root)}")
    if dst_root == src_root or src_root in dst_root.parents:
        die("The MP3 folder can't be the library folder or inside it.")
    if not shutil.which("ffmpeg"):
        die("ffmpeg isn't installed. Install it with: brew install ffmpeg")

    heading(f"320 kbps MP3 copy of {tilde(src_root)}")
    note("checking what's already there...")
    jobs, up_to_date, protected, partials, wrong_format, orphans = plan(src_root, dst_root)
    count = {a: sum(1 for j in jobs if j[0] == a) for a in ("convert", "redo", "copy")}
    rows = [("destination", tilde(dst_root)),
            ("up to date", f"{up_to_date} {dim('(skipped)')}"),
            ("to convert", str(count["convert"])),
            ("to redo", f"{count['redo']} {dim('(MP3 there but wrong bitrate or incomplete)')}"),
            ("to copy", f"{count['copy']} {dim('(already MP3 in your library)')}")]
    if partials or wrong_format:
        rows.append(("to clean up", f"{len(partials) + len(wrong_format)} "
                                    f"{dim('(unfinished conversions and non-MP3 audio)')}"))
    summary(rows)
    if protected:
        warn(f"{len(protected)} copy-protected .m4p file(s) can't be converted and are skipped.")

    for p in partials + wrong_format:
        p.unlink(missing_ok=True)
    if partials or wrong_format:
        ok(f"Removed {len(partials) + len(wrong_format)} leftover file(s).")

    if orphans:
        print(f"\n  {bold(len(orphans))} MP3(s) here have no matching song in the library any more "
              f"{dim('(deleted from the library since the last conversion?)')}")
        for p in orphans[:8]:
            print(f"    {dim('-')} {p.relative_to(dst_root)}")
        if len(orphans) > 8:
            note(f"  ... and {len(orphans) - 8} more")
        if not assume_yes and sys.stdin.isatty():
            ans = prompt(f"{yellow('?')} Delete them from the MP3 folder too? {dim('[y/N]')} ").strip().lower()
            if ans.startswith("y"):
                for p in orphans:
                    p.unlink(missing_ok=True)
                ok(f"Removed {len(orphans)} MP3(s).")
        else:
            note("left in place (run interactively to be asked about removing them)")

    if not jobs:
        print()
        ok("Everything is already converted.")
        return 0

    total_bytes = sum(src.stat().st_size for _, src, _ in jobs)
    width = len(str(len(jobs)))
    print()
    done = failed = done_bytes = 0
    start = time.monotonic()
    pool = ThreadPoolExecutor(max_workers=jobs_n)
    futures = {pool.submit(run_job, *job): job for job in jobs}
    try:
        for fut in as_completed(futures):
            action, src, dest = futures[fut]
            error = fut.result()
            done += 1
            done_bytes += src.stat().st_size
            elapsed = time.monotonic() - start
            rate = done_bytes / elapsed if elapsed > 0 else 0
            left = clock((total_bytes - done_bytes) / rate) if rate and done < len(jobs) else "0:00"
            counter = dim(f"{str(done).rjust(width)}/{len(jobs)}")
            eta = dim(f"{left} left")
            rel = dest.relative_to(dst_root)
            if error:
                failed += 1
                print(f"  {counter}  {LABELS['fail']}  {rel}  {red(error)}")
            else:
                print(f"  {counter}  {LABELS[action]}  {rel}  {eta}")
    except KeyboardInterrupt:
        pool.shutdown(wait=False, cancel_futures=True)
        with ACTIVE_LOCK:
            for tmp in list(ACTIVE):
                tmp.unlink(missing_ok=True)
        print(f"\n  {dim('stopped - run it again to carry on; finished files are kept')}")
        return 130
    pool.shutdown()

    print()
    took = clock(time.monotonic() - start)
    if failed:
        warn(f"{done - failed} done, {failed} failed, in {took}. Run it again to retry the failed ones.")
        return 1
    ok(f"{done} file(s) done in {took}. {up_to_date + done} MP3s in {tilde(dst_root)}.")
    return 0


# ---------------------------------------------------------------------------
# Prune: delete originals once every one of them is verified as converted
# ---------------------------------------------------------------------------

def decodes_cleanly(path):
    """Decode the whole MP3 and discard the audio: catches corrupt or truncated files."""
    r = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-map", "0:a", "-f", "null", "-"],
                       capture_output=True, text=True)
    return r.returncode == 0 and not r.stderr.strip()


class VerifiedCache:
    """MP3s that passed prune's checks, keyed by path, with the size/mtime of the MP3 and its
    original at that moment. Any change to either means it gets checked again."""

    def __init__(self, dst_root):
        self.root = dst_root
        self.path = dst_root / ".musesh" / "verified.json"
        try:
            self.entries = json.loads(self.path.read_text())
        except (OSError, ValueError):
            self.entries = {}

    @staticmethod
    def _stamp(src, dest):
        s, d = src.stat(), dest.stat()
        return [d.st_mtime, d.st_size, s.st_mtime, s.st_size]

    def still_good(self, src, dest):
        key = str(dest.relative_to(self.root))
        try:
            return key in self.entries and self.entries[key] == self._stamp(src, dest)
        except OSError:
            return False

    def mark(self, src, dest):
        self.entries[str(dest.relative_to(self.root))] = self._stamp(src, dest)

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.entries))
        tmp.replace(self.path)


def verify(src, dest):
    """None if dest is a good MP3 of src, otherwise the reason it isn't."""
    if not dest.exists():
        return "no MP3"
    if not dest_matches(src, dest):
        return "wrong bitrate or length"
    if not decodes_cleanly(dest):
        return "MP3 doesn't play cleanly"
    return None


def prune(src_root, dst_root, jobs_n):
    src_root, dst_root = src_root.resolve(), dst_root.resolve()
    for d, what in ((src_root, "library"), (dst_root, "MP3 folder")):
        if not d.is_dir():
            die(f"The {what} {tilde(d)} doesn't exist.")
    if not shutil.which("ffmpeg"):
        die("ffmpeg isn't installed. Install it with: brew install ffmpeg")

    originals = sorted(p for p in src_root.rglob("*")
                       if p.suffix.lower() in SOURCE_EXTS - {".mp3"} and p.is_file()
                       and STATE_DIR not in p.relative_to(src_root).parts)
    heading(f"Remove originals from {tilde(src_root)} once converted")
    summary([("MP3 folder", tilde(dst_root)),
             ("originals", f"{len(originals)} non-MP3 file(s), "
                           f"{sum(p.stat().st_size for p in originals) / 1024 ** 3:.2f} GB")])
    if not originals:
        print()
        ok("No non-MP3 originals left - nothing to remove.")
        return 0

    pairs = [(src, (dst_root / src.relative_to(src_root)).with_suffix(".mp3")) for src in originals]

    # MP3s that passed before and haven't changed since (nor has their original) don't need
    # decoding again - so a cancelled or mistyped prune doesn't cost a full re-check.
    cache = VerifiedCache(dst_root)
    todo = [(s, d) for s, d in pairs if not cache.still_good(s, d)]
    reused = len(pairs) - len(todo)
    problems, checked = [], 0
    live = sys.stdout.isatty()
    print()
    if reused:
        note(f"{reused} MP3(s) already verified and unchanged - not checked again")
    pool = ThreadPoolExecutor(max_workers=jobs_n)
    futures = {pool.submit(verify, s, d): (s, d) for s, d in todo}
    try:
        for fut in as_completed(futures):
            checked += 1
            src, dest = futures[fut]
            reason = fut.result()
            if reason:
                problems.append((src, reason))
            else:
                cache.mark(src, dest)
            if checked % 50 == 0:
                cache.save()
            if live:
                print(f"\r  {dim('verifying')} {checked}/{len(todo)}"
                      f"{('  ' + red(str(len(problems)) + ' problem(s)')) if problems else ''}   ",
                      end="", flush=True)
    except KeyboardInterrupt:
        pool.shutdown(wait=False, cancel_futures=True)
        cache.save()
        print(f"\n  {dim('stopped - nothing was deleted; what was verified so far is remembered')}")
        return 130
    pool.shutdown()
    cache.save()
    if todo:
        print(f"\r  {dim('verified')} {len(todo)}/{len(todo)}" + " " * 30)

    if problems:
        print()
        warn(f"{len(problems)} original(s) don't have a good MP3 yet, so nothing was deleted:")
        for src, reason in sorted(problems)[:20]:
            print(f"    {dim('-')} {src.relative_to(src_root)}  {red(reason)}")
        if len(problems) > 20:
            note(f"  ... and {len(problems) - 20} more")
        # A corrupt MP3 has the right header and length, so 'musesh mp3' would think it's fine.
        # Remove it so the next conversion run redoes it.
        broken = [(dst_root / s.relative_to(src_root)).with_suffix(".mp3") for s, r in problems if "play" in r]
        for b in broken:
            b.unlink(missing_ok=True)
        if broken:
            note(f"Removed {len(broken)} broken MP3(s) so they get converted again.")
        note("Run 'musesh mp3' to convert them, then 'musesh prune' again.")
        return 1

    size = sum(s.stat().st_size for s, _ in pairs)
    print()
    ok(f"All {len(pairs)} originals have a verified 320 kbps MP3 in {tilde(dst_root)}.")
    print(f"\n  Deleting them frees {bold(f'{size / 1024 ** 3:.2f} GB')}. "
          f"{red('This cannot be undone')} {dim('(you can re-download Apple Music songs with musesh)')}.")
    for attempt in range(3):
        answer = prompt(f"{yellow('?')} Type {bold('delete')} to remove the {len(pairs)} originals "
                        f"{dim('(Enter to cancel)')}: ").strip().lower()
        if answer == "delete":
            break
        if answer in ("", "n", "no", "cancel", "q"):
            note("Nothing deleted. The verification is remembered, so the next prune goes straight to this question.")
            return 1
        if attempt < 2:
            note(f"that wasn't 'delete' ({answer!r}) - try again, or press Enter to cancel")
    else:
        note("Nothing deleted. The verification is remembered, so the next prune goes straight to this question.")
        return 1

    record = dst_root / PRUNED_RECORD
    record.parent.mkdir(parents=True, exist_ok=True)
    with open(record, "a") as f:
        for src, dest in pairs:
            f.write(f"{dest.relative_to(dst_root)}\n")  # recorded first, so a crash never orphans an MP3
    for src, _ in pairs:
        src.unlink(missing_ok=True)

    # Remove folders the deletions emptied (Finder's .DS_Store doesn't count as contents).
    removed_dirs = 0
    for d in sorted((d for d in src_root.rglob("*") if d.is_dir() and STATE_DIR not in d.relative_to(src_root).parts),
                    key=lambda d: len(d.parts), reverse=True):
        if all(c.name == ".DS_Store" for c in d.iterdir()):
            (d / ".DS_Store").unlink(missing_ok=True)
            d.rmdir()
            removed_dirs += 1
    ok(f"Removed {len(pairs)} originals ({size / 1024 ** 3:.2f} GB) and {removed_dirs} emptied folder(s). "
       f"Your MP3s are in {tilde(dst_root)}.")
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("library", type=Path)
    p.add_argument("mp3_folder", type=Path)
    p.add_argument("--jobs", type=int, default=os.cpu_count() or 4, help="conversions at once")
    p.add_argument("-y", "--yes", action="store_true", help="don't ask about removing orphaned MP3s (keeps them)")
    p.add_argument("--prune", action="store_true",
                   help="verify every original has a good MP3, then (after typing 'delete') remove the originals")
    args = p.parse_args()
    if args.prune:
        return prune(args.library.expanduser(), args.mp3_folder.expanduser(), args.jobs)
    return run(args.library.expanduser(), args.mp3_folder.expanduser(), args.jobs, args.yes)


if __name__ == "__main__":
    # ffmpeg shares the terminal's Ctrl-C; this process handles it and cleans up.
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print(f"\n  {dim('stopped')}")
        sys.exit(130)
