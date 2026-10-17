import contextlib
import datetime as dt
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import music_dates
import transfer as tr


class TransferTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / "Incoming"
        self.library = self.root / "Library"
        self.share = self.root / "Share"
        self.share.mkdir()
        self.state = self.root / "state"
        self.patches = [patch.object(tr, "STATE", self.state), patch.object(tr, "ROOT", self.root)]
        for p in self.patches:
            p.start()
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
        tr.setup(self.share, [self.source, self.library])
        self.config = json.loads((self.state / "settings.json").read_text())

    def tearDown(self):
        self.output.__exit__(None, None, None)
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    def song(self, name="Artist/Album/Song.mp3", date=None, root=None, content=b"music"):
        root = root or self.source
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        music_dates.added_at(path, root, date if date is not None else self.config["baseline"] + 1)
        return path

    def manifests(self):
        return [json.loads(p.read_text()) for p in (self.share / "batches").glob("*/manifest.json")
                if not p.parent.name.startswith(".")]

    def receipt(self, item):
        tr.save_json(self.share / "receipts" / (item["id"] + ".json"),
                     {"version": 1, "id": item["id"]})

    def test_default_excludes_baseline_and_explicit_date_includes_old_music(self):
        old = self.config["baseline"] - 86400
        self.song("Old/Album/Old.mp3", old)
        self.song()
        self.assertEqual(len(list(tr.selected(self.config, None))), 1)
        day = dt.datetime.fromtimestamp(old).date()
        self.assertEqual(list(tr.selected(self.config, (day, day)))[0][0].name, "Old.mp3")

    def test_date_range_includes_both_days_but_not_adjacent_day(self):
        for day in (1, 2, 3):
            self.song(f"Album/{day}.mp3", dt.datetime(2026, 10, day, 12).timestamp())
        rows = list(tr.selected(self.config, tr.dates("2026-10-01..2026-10-02")))
        self.assertEqual([r[0].name for r in rows], ["1.mp3", "2.mp3"])
        for bad in ("2026-13-01", "2026-10-02..2026-10-01", "x", "2026-01-01..x..x"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                tr.dates(bad)

    def test_repeated_prepare_deduplicates_and_only_receipts_acknowledge(self):
        self.song()
        tr.prepare()
        first = self.manifests()[0]
        self.assertEqual(len(first["files"]), 1)
        self.assertFalse(list((self.share / "receipts").iterdir()))
        tr.prepare()
        self.assertEqual(len(self.manifests()), 1)
        self.receipt(first["files"][0])
        tr.prepare()
        self.assertFalse(self.manifests())
        self.assertTrue((self.source / "Artist/Album/Song.mp3").exists())

    def test_partial_receipts_keep_failed_songs_queued(self):
        self.song("Album/One.mp3")
        self.song("Album/Two.mp3", content=b"two")
        tr.prepare()
        batch = self.manifests()[0]
        self.receipt(batch["files"][0])
        tr.prepare()
        self.assertEqual(len(self.manifests()), 1)
        self.assertEqual(len(list((self.share / "receipts").glob("*.json"))), 1)

    def test_network_unavailable_retains_local_batch_and_retry_publishes(self):
        self.song()
        offline = self.root / "Offline"
        self.share.rename(offline)
        with self.assertRaisesRegex(ValueError, "unavailable"):
            tr.prepare()
        self.assertEqual(len(list((self.state / "pending").glob("*/manifest.json"))), 1)
        offline.rename(self.share)
        tr.prepare()
        self.assertEqual(len(self.manifests()), 1)
        self.assertFalse(list((self.state / "pending").iterdir()))

    def test_interrupted_network_copy_never_publishes_partial_batch(self):
        self.song()
        real_copy = shutil.copyfile

        def fail_share(src, dst, *args, **kwargs):
            if str(dst).startswith(str(self.share)):
                Path(dst).write_bytes(b"partial")
                raise OSError("disconnected")
            return real_copy(src, dst, *args, **kwargs)

        with patch.object(tr.shutil, "copyfile", side_effect=fail_share):
            with self.assertRaises(OSError):
                tr.prepare()
        self.assertFalse(self.manifests())
        tr.publish(self.config)
        self.assertEqual(len(self.manifests()), 1)
        batch = self.manifests()[0]
        item = batch["files"][0]
        self.assertEqual(tr.digest(self.share / "batches" / batch["batch_id"] / "music" / item["path"]), item["sha256"])

    def test_case_and_sanitization_collisions_have_stable_distinct_paths(self):
        self.song("Album/A:B.mp3")
        self.song("Album/A?B.mp3")
        rows = list(tr.selected(self.config, None))
        targets = [r[3].as_posix() for r in rows]
        self.assertEqual(len(set(p.casefold() for p in targets)), 2)
        self.assertTrue(all(":" not in p and "?" not in p for p in targets))
        # Selection dates must never change the target name for the same song.
        day = dt.datetime.fromtimestamp(rows[0][2]).date()
        self.assertEqual(targets, [r[3].as_posix() for r in tr.selected(self.config, (day, day))])
        self.assertEqual(tr.windows_path(Path("CON/PRN.mp3")), "_CON/_PRN.mp3")
        self.assertLess(len(tr.windows_path(Path("x" * 200 + ".mp3"))), 70)

    def test_incoming_takes_precedence_over_converted_library(self):
        source = self.song()
        self.song(root=self.library, content=b"old conversion")
        rows = list(tr.selected(self.config, None))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], source)

    def test_later_filename_collision_does_not_change_an_uploaded_path(self):
        first = self.song("Album/A:B.mp3")
        original_target = list(tr.selected(self.config, None))[0][3]
        self.song("Album/A?B.mp3")
        rows = list(tr.selected(self.config, None))
        targets = {r[0]: r[3] for r in rows}
        self.assertEqual(targets[first], original_target)
        self.assertEqual(len(set(p.as_posix().casefold() for p in targets.values())), 2)

    def test_two_native_sources_with_same_output_fail_without_publishing(self):
        self.song("Album/Song.m4a")
        self.song("Album/Song.flac")
        with self.assertRaisesRegex(ValueError, "Two source files"):
            tr.prepare()
        self.assertFalse(self.manifests())

    def test_incomplete_local_batch_is_ignored_on_retry(self):
        incomplete = self.state / "pending" / "interrupted"
        incomplete.mkdir(parents=True)
        (incomplete / "part").write_bytes(b"partial")
        tr.prepare()
        self.assertFalse(incomplete.exists())

    def test_corrupt_network_copy_is_not_published(self):
        self.song()
        real_copy = shutil.copyfile

        def corrupt_share(src, dst, *args, **kwargs):
            result = real_copy(src, dst, *args, **kwargs)
            if str(dst).startswith(str(self.share)):
                Path(dst).write_bytes(b"corrupt")
            return result

        with patch.object(tr.shutil, "copyfile", side_effect=corrupt_share):
            with self.assertRaisesRegex(ValueError, "verification failed"):
                tr.prepare()
        self.assertFalse(self.manifests())
        self.assertEqual(len(list((self.state / "pending").glob("*/manifest.json"))), 1)

    def test_concurrent_prepare_is_rejected(self):
        import fcntl
        with (self.state / "lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(tr.main(["prepare"]), 1)

    def test_state_partials_hidden_files_and_symlinks_are_not_music(self):
        self.song(".musesh/work.mp3")
        self.song("Album/.hidden.mp3")
        self.song("Album/Song.part.mp3")
        real = self.song()
        (self.source / "link.mp3").symlink_to(real)
        self.assertEqual(list(music_dates.inventory(self.source)), [real])

    def test_recorded_addition_date_survives_metadata_edits(self):
        path = self.song(date=100)
        path.write_bytes(b"new tags")
        self.assertEqual(music_dates.added_at(path, self.source, 200), 100)

    def test_repeated_setup_preserves_baseline_and_installs_launchers(self):
        tr.setup(self.share, [self.source])
        config = json.loads((self.state / "settings.json").read_text())
        self.assertEqual(config["baseline"], self.config["baseline"])
        self.assertTrue((self.share / "musesh-transfer.cmd").is_file())
        self.assertTrue((self.share / "musesh-transfer.ps1").is_file())
        with self.assertRaises(ValueError):
            tr.setup(self.source, [self.source])

    def test_source_changes_do_not_publish_inconsistent_batch(self):
        path = self.song()
        original = tr.mp3_copy

        def modifying(src, dest):
            original(src, dest)
            path.write_bytes(b"changed while preparing")

        with patch.object(tr, "mp3_copy", side_effect=modifying):
            with self.assertRaisesRegex(ValueError, "Source changed"):
                tr.prepare()
        self.assertFalse(self.manifests())

    @unittest.skipUnless(shutil.which("ffmpeg") and tr.GAMDL_PYTHON.exists(), "ffmpeg/gamdl environment required")
    def test_real_native_conversion_and_addition_date_propagation(self):
        source = self.source / "Artist/Album/Tone.wav"
        source.parent.mkdir(parents=True)
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.2",
                        str(source)], check=True)
        music_dates.added_at(source, self.source, self.config["baseline"] + 1)
        tr.prepare()
        item = self.manifests()[0]["files"][0]
        self.assertGreater(item["size"], 0)
        self.assertTrue(item["path"].endswith(".mp3"))
        # A second preparation must reuse the conversion, not invoke ffmpeg.
        with patch.object(tr.subprocess, "run", side_effect=AssertionError("converted twice")):
            tr.prepare()
        script = ("from pathlib import Path; import mp3; "
                  "from music_dates import added_at; "
                  f"src=Path({str(source)!r}); root=Path({str(self.source)!r}); "
                  f"dest=Path({str(self.library / 'Tone.mp3')!r}); dst=Path({str(self.library)!r}); "
                  "assert mp3.run_job('convert', src, dest, root, dst) is None; "
                  "assert added_at(src,root)==added_at(dest,dst)")
        subprocess.run([str(tr.GAMDL_PYTHON), "-c", script], cwd=tr.HERE, check=True)


if __name__ == "__main__":
    unittest.main()
