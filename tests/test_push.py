import contextlib
import ctypes
import errno
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import music_dates
import push


class PushTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.library = self.root / "Library"
        self.player = self.root / "WALKMAN"
        self.state = self.root / "state"
        self.library.mkdir()
        (self.player / "MUSIC").mkdir(parents=True)
        self.now = time.time()

    def tearDown(self):
        self.temp.cleanup()

    def song(self, relative="Artist/Album/01 New.mp3", age=60, data=b"new audio"):
        path = self.library / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        music_dates.added_at(path, self.library, self.now - age)
        return path

    def run_push(self, answer="y", **kwargs):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), patch.object(push, "prompt", return_value=answer) as prompt:
            result = push.run(self.library, self.player, "player-id", self.state,
                              now=self.now, ensure_connected=lambda: None, **kwargs)
        return result, output.getvalue(), prompt

    def history(self):
        paths = [p for p in self.state.glob("*.json") if p.name != "player.json"]
        return json.loads(paths[0].read_text())

    def test_first_push_only_new_downloads_and_complete_preview_before_confirmation(self):
        recent = self.song()
        self.song("Artist/Album/02 Second.mp3", data=b"second")
        old = self.song("Old Artist/Old Album/01 Deleted.mp3", age=20 * 86400)
        output = io.StringIO()

        def confirm(text):
            preview = output.getvalue()
            self.assertIn("Artist", preview)
            self.assertIn("Album", preview)
            self.assertIn("01 New", preview)
            self.assertIn("02 Second", preview)
            self.assertIn("free afterward", preview)
            self.assertFalse(list((self.player / "MUSIC").rglob("*.mp3")))
            self.assertFalse(self.state.exists())
            return "y"

        with contextlib.redirect_stdout(output), patch.object(push, "prompt", side_effect=confirm):
            self.assertEqual(push.run(self.library, self.player, "player-id", self.state,
                                      now=self.now, ensure_connected=lambda: None), 0)
        self.assertEqual((self.player / "MUSIC" / recent.relative_to(self.library)).read_bytes(), recent.read_bytes())
        self.assertFalse((self.player / "MUSIC" / old.relative_to(self.library)).exists())

    def test_deleted_pushed_song_is_never_restored_even_after_metadata_change(self):
        source = self.song()
        self.run_push()
        target = self.player / "MUSIC" / source.relative_to(self.library)
        target.unlink()
        source.write_bytes(b"updated tags and audio")
        _, output, prompt = self.run_push()
        self.assertFalse(target.exists())
        self.assertIn("No new songs", output)
        prompt.assert_not_called()

    def test_preexisting_player_song_is_remembered_and_not_restored_after_delete(self):
        source = self.song()
        target = self.player / "MUSIC" / source.relative_to(self.library)
        target.parent.mkdir(parents=True)
        target.write_bytes(b"the player's own version")
        self.run_push()
        self.assertEqual(target.read_bytes(), b"the player's own version")
        target.unlink()
        self.run_push()
        self.assertFalse(target.exists())

    def test_cancel_and_dry_run_leave_player_and_history_unchanged(self):
        self.song()
        self.run_push(answer="n")
        self.assertFalse(self.state.exists())
        self.assertFalse(list((self.player / "MUSIC").rglob("*.mp3")))
        _, output, prompt = self.run_push(dry_run=True)
        self.assertIn("Preview only", output)
        prompt.assert_not_called()
        self.assertFalse(self.state.exists())

    def test_pending_song_remains_retryable_after_window_expires(self):
        self.song("Artist/Album/01 One.mp3")
        self.song("Artist/Album/02 Two.mp3", data=b"two")
        original = push.copy_song

        def fail_second(row, *args):
            if row["key"].endswith("Two.mp3"):
                raise OSError("unplugged")
            return original(row, *args)

        with patch.object(push, "copy_song", side_effect=fail_second):
            with self.assertRaises(OSError):
                self.run_push()
        states = [r["status"] for r in self.history()["songs"].values()]
        self.assertEqual(states, ["handled", "pending"])
        self.now += 30 * 86400
        self.run_push()
        self.assertEqual(len(list((self.player / "MUSIC").rglob("*.mp3"))), 2)

    def test_new_additions_after_initial_push_are_detected(self):
        self.song()
        self.run_push()
        self.song("Another Artist/New Album/New.mp3", data=b"newer")
        _, output, _ = self.run_push()
        self.assertIn("Another Artist", output)
        self.assertNotIn("01 New.mp3", output)
        self.assertEqual(len(list((self.player / "MUSIC").rglob("*.mp3"))), 2)

    def test_renamed_handled_file_does_not_duplicate_on_player(self):
        source = self.song()
        self.run_push()
        source.rename(source.with_name("Renamed.mp3"))
        _, output, _ = self.run_push()
        self.assertIn("No new songs", output)
        self.assertEqual(len(list((self.player / "MUSIC").rglob("*.mp3"))), 1)

    def test_insufficient_space_copies_nothing_and_does_not_ask_to_start(self):
        self.song()
        with patch.object(push.shutil, "disk_usage", return_value=Mock(free=0)):
            result, output, prompt = self.run_push()
        self.assertEqual(result, 1)
        self.assertIn("Not enough room", output)
        self.assertFalse(self.state.exists())
        prompt.assert_not_called()

    def test_source_change_after_preview_stops_transfer(self):
        source = self.song()

        def confirm(_):
            source.write_bytes(b"changed during the preview")
            return "y"

        with contextlib.redirect_stdout(io.StringIO()), patch.object(push, "prompt", side_effect=confirm):
            with self.assertRaisesRegex(ValueError, "Source changed"):
                push.run(self.library, self.player, "player-id", self.state,
                         now=self.now, ensure_connected=lambda: None)
        self.assertFalse(list((self.player / "MUSIC").rglob("*.mp3")))

    def test_interrupted_copy_never_publishes_partial_mp3(self):
        self.song(data=b"x" * (3 * 1024 * 1024))
        check = Mock(side_effect=[None, None, None, ValueError("disconnected"), ValueError("disconnected")])
        with contextlib.redirect_stdout(io.StringIO()), patch.object(push, "prompt", return_value="y"):
            with self.assertRaisesRegex(ValueError, "disconnected"):
                push.run(self.library, self.player, "player-id", self.state,
                         now=self.now, ensure_connected=check)
        self.assertFalse(list((self.player / "MUSIC").rglob("*.mp3")))
        self.run_push()
        self.assertEqual(len(list((self.player / "MUSIC").rglob("*.mp3"))), 1)
        self.assertFalse(list((self.player / "MUSIC").rglob("*.part")))

    def test_crash_after_publication_before_receipt_recovers_without_overwrite(self):
        self.song()
        original = push.save_json

        def fail_receipt(path, data):
            if "songs" in data and any(r["status"] == "handled" for r in data["songs"].values()):
                raise OSError("receipt write failed")
            return original(path, data)

        with patch.object(push, "save_json", side_effect=fail_receipt):
            with self.assertRaises(OSError):
                self.run_push()
        self.run_push()
        self.assertEqual(len(list((self.player / "MUSIC").rglob("*.mp3"))), 1)
        self.assertEqual(next(iter(self.history()["songs"].values()))["status"], "handled")

    def test_byte_progress_reports_copy_flush_and_verification(self):
        self.song(data=b"x" * (3 * 1024 * 1024))
        rows = push.plan(push.source_files(self.library), self.player, {"cutoff": 0, "songs": {}})
        updates = Mock()
        push.copy_song(rows[0], self.player, lambda: None, updates)
        stages = [call.args[0] for call in updates.call_args_list]
        copied = [call.args[1] for call in updates.call_args_list if call.args[0] == "copying"]
        self.assertEqual(copied, [0, 1024 * 1024, 2 * 1024 * 1024, 3 * 1024 * 1024])
        self.assertIn("flushing", stages)
        self.assertEqual(stages[-1], "verifying")

    def test_usb_io_error_leaves_song_pending_with_clear_retry_message(self):
        self.song()
        with patch.object(push, "publish_exclusive", side_effect=OSError(errno.EIO, "Input/output error")):
            with self.assertRaisesRegex(push.PlayerDisconnected, "USB transfer interrupted"):
                self.run_push()
        self.assertEqual(next(iter(self.history()["songs"].values()))["status"], "pending")
        self.assertFalse(list((self.player / "MUSIC").rglob("*.mp3")))
        self.run_push()
        self.assertEqual(len(list((self.player / "MUSIC").rglob("*.mp3"))), 1)

    def test_disconnect_after_rename_is_recovered_without_duplicate_copy(self):
        self.song()
        published = False
        original = push.publish_exclusive

        def publish(*args):
            nonlocal published
            original(*args)
            published = True

        def connected():
            if published:
                raise push.PlayerDisconnected("disconnected")

        with patch.object(push, "publish_exclusive", side_effect=publish), \
                patch.object(push, "prompt", return_value="y"), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(push.PlayerDisconnected):
                push.run(self.library, self.player, "player-id", self.state,
                         now=self.now, ensure_connected=connected)
        self.assertEqual(next(iter(self.history()["songs"].values()))["status"], "pending")
        with patch.object(push, "publish_exclusive", side_effect=AssertionError("copied twice")):
            self.run_push()
        self.assertEqual(next(iter(self.history()["songs"].values()))["status"], "handled")

    def test_live_progress_and_completion_are_visible(self):
        row = {"key": "Artist/Album/Song.mp3", "size": 4 * 1024 * 1024}

        class Terminal(io.StringIO):
            def isatty(self):
                return True

        output = Terminal()
        with contextlib.redirect_stdout(output):
            progress = push.UploadProgress(2, 10, row)
            progress.update("copying", 2 * 1024 * 1024, row["size"])
            progress.update("verifying", row["size"], row["size"])
            progress.finish(True)
        text = output.getvalue()
        self.assertIn("2/10", text)
        self.assertIn("Song.mp3", text)
        self.assertIn("50%", text)
        self.assertIn("verifying", text)
        self.assertIn("verified and saved", text)

    def test_auto_reconnect_retries_only_unfinished_song_and_confirms_once(self):
        self.song("Artist/Album/01 One.mp3", data=b"one")
        self.song("Artist/Album/02 Two.mp3", data=b"two")
        original = push.copy_song
        attempts = []
        failed = False

        def flaky(row, *args):
            nonlocal failed
            attempts.append(row["key"])
            if row["key"].endswith("Two.mp3") and not failed:
                failed = True
                raise push.PlayerDisconnected("cable dropped")
            return original(row, *args)

        reconnect = Mock(return_value=self.player)
        with patch.object(push, "copy_song", side_effect=flaky):
            result, output, confirm = self.run_push(reconnect=reconnect)
        self.assertEqual(result, 0)
        confirm.assert_called_once()
        reconnect.assert_called_once()
        self.assertEqual(attempts, ["Artist/Album/01 One.mp3", "Artist/Album/02 Two.mp3", "Artist/Album/02 Two.mp3"])
        self.assertIn("upload paused", output)
        self.assertEqual(len(list((self.player / "MUSIC").rglob("*.mp3"))), 2)

    def test_reconnect_at_new_mount_path_keeps_the_approved_batch(self):
        self.song()
        original = push.copy_song
        disconnected = False
        new_mount = self.root / "WALKMAN 1"

        def flaky(row, *args):
            nonlocal disconnected
            if not disconnected:
                disconnected = True
                raise push.PlayerDisconnected("disconnected")
            return original(row, *args)

        def reconnect(*_):
            self.player.rename(new_mount)
            # New downloads during a pause were not in the approved preview.
            self.song("Other/New.mp3", data=b"not approved")
            return new_mount

        with patch.object(push, "copy_song", side_effect=flaky):
            _, _, confirm = self.run_push(reconnect=reconnect)
        confirm.assert_called_once()
        self.assertEqual(len(list((new_mount / "MUSIC").rglob("*.mp3"))), 1)
        self.assertFalse((new_mount / "MUSIC/Other/New.mp3").exists())
        self.assertEqual(json.loads((self.state / "player.json").read_text())["mount"], str(new_mount))

    def test_watcher_logs_waiting_rejects_other_player_and_detects_reconnect(self):
        other = self.root / "WALKMAN-OTHER"
        other.mkdir()
        watcher = push.ConnectionWatcher(self.player, "correct-id")
        attempts = 0

        def info(path):
            nonlocal attempts
            if path == other:
                return {"VolumeUUID": "wrong-id"}
            attempts += 1
            if attempts == 1:
                raise OSError("not ready")
            return {"VolumeUUID": "correct-id"}

        output = io.StringIO()
        with patch.object(push.Path, "is_mount", return_value=True), \
                patch.object(push.Path, "iterdir", return_value=iter([other, self.player])), \
                patch.object(push, "volume_info", side_effect=info), \
                patch.object(push.time, "sleep") as sleep, \
                patch.object(push.time, "monotonic", side_effect=[0, 11, 12]), \
                contextlib.redirect_stdout(output):
            result = watcher.wait(2, 3, {"key": "Artist/Album/Song.mp3"})
        self.assertEqual(result, self.player)
        self.assertEqual(sleep.call_count, 2)
        for message in ("DISCONNECTED", "WATCHING", "IGNORED", "RECONNECTED", "automatically"):
            self.assertIn(message, output.getvalue())

    def test_ctrl_c_during_reconnect_leaves_pending_history(self):
        self.song()
        with patch.object(push, "copy_song", side_effect=push.PlayerDisconnected("dropped")):
            with self.assertRaises(KeyboardInterrupt):
                self.run_push(reconnect=Mock(side_effect=KeyboardInterrupt))
        self.assertEqual(next(iter(self.history()["songs"].values()))["status"], "pending")

    def test_stable_safe_names_with_source_collisions(self):
        self.song("Artist/Album/A:B.mp3", data=b"one")
        self.song("Artist/Album/A?B.mp3", data=b"two")
        self.run_push()
        targets = list((self.player / "MUSIC").rglob("*.mp3"))
        self.assertEqual(len(targets), 2)
        self.assertEqual({p.read_bytes() for p in targets}, {b"one", b"two"})
        self.assertTrue(all(":" not in p.name and "?" not in p.name for p in targets))

    def test_symlink_destination_cannot_write_outside_player(self):
        self.song()
        (self.player / "MUSIC" / "Artist").symlink_to(self.library, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "Linked player folders"):
            self.run_push()

    def test_exclusive_publication_preserves_existing_destination(self):
        temporary = self.root / "temporary"
        target = self.root / "existing"
        temporary.write_bytes(b"new")
        target.write_bytes(b"original")
        with self.assertRaises(FileExistsError):
            push.publish_exclusive(temporary, target)
        self.assertEqual(target.read_bytes(), b"original")

    @unittest.skipUnless(sys.platform == "darwin", "macOS FAT32 publication fallback")
    def test_fat32_fallback_renames_without_overwriting(self):
        # macOS FAT32 reports ENOTSUP (45), distinct from EOPNOTSUPP (102).
        for error in {errno.ENOTSUP, errno.EOPNOTSUPP}:
            with self.subTest(errno=error):
                temporary = self.root / f"temporary-{error}"
                target = self.root / f"target-{error}"
                temporary.write_bytes(b"new")
                with patch.object(push.os, "link", side_effect=OSError(error, "FAT32")):
                    push.publish_exclusive(temporary, target)
                    self.assertEqual(target.read_bytes(), b"new")
                    temporary.write_bytes(b"other")
                    with self.assertRaises(FileExistsError):
                        push.publish_exclusive(temporary, target)
                self.assertEqual(target.read_bytes(), b"new")

    def test_mount_identity_is_required(self):
        with patch.object(push.subprocess, "run", return_value=Mock(stdout=b"not a plist")):
            with self.assertRaises(Exception):
                push.volume_info(self.player)
        with patch.object(push.Path, "is_mount", return_value=False):
            with self.assertRaisesRegex(ValueError, "Connect the configured Walkman"):
                push.find_player(self.state)


if __name__ == "__main__":
    unittest.main()
