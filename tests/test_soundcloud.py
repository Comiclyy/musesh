import contextlib
import errno
import io
import json
import runpy
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import soundcloud as sc


class SoundCloudTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.dl = sc.Downloader(self.root / "Incoming", sc.find_ytdlp() or "yt-dlp")

    def tearDown(self):
        self.dl.logfile.close()
        self.dl.lock.close()
        self.temp.cleanup()

    def test_share_tracking_removed(self):
        self.assertEqual(sc.public_url("https://soundcloud.com/band/song?si=abc&utm_source=test"),
                         "https://soundcloud.com/band/song")
        self.assertEqual(sc.public_url("https://on.soundcloud.com/abcd?si=abc"), "https://on.soundcloud.com/abcd")

    def test_only_public_track_and_set_links(self):
        for url in ("https://example.com/a/b", "https://soundcloud.com/band", "https://soundcloud.com/band/tracks",
                    "https://soundcloud.com/band/sets", "https://soundcloud.com/band/song/s-secret",
                    "https://soundcloud.com.evil/a/b", "file:///tmp/music", "https://user@soundcloud.com/a/b"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                sc.public_url(url)
        self.assertEqual(sc.public_url("https://soundcloud.com/band/sets/album"),
                         "https://soundcloud.com/band/sets/album")

    def test_fallback_tags_and_safe_names(self):
        tags = sc.track_tags({"id": "42", "title": "Luna (Apartment Demo)", "uploader": "Smashing Pumpkins"})
        self.assertEqual((tags["artist"], tags["album"]), ("Smashing Pumpkins", "Unknown Album"))
        self.assertEqual(sc.safe_name("../../a:b\n", "x"), "_.._a_b")
        self.assertLessEqual(len(sc.safe_name("音" * 120, "x").encode()), 120)

    def test_album_order_and_collision(self):
        tags = sc.track_tags({"id": "42", "title": "Song", "artists": ["Band"]}, "Album", 2, 10)
        dest = sc.target_path(self.dl.out, tags, ".m4a", {})
        self.assertEqual(str(dest.relative_to(self.dl.out)), "Band/Album/02 Song.m4a")
        dest.parent.mkdir(parents=True)
        dest.write_text("existing")
        other = sc.target_path(self.dl.out, tags, ".m4a", {})
        self.assertEqual(other.name, "02 Song [sc-42].m4a")
        other.touch()
        with self.assertRaises(ValueError):
            sc.target_path(self.dl.out, tags, ".m4a", {})
        self.assertEqual(dest.read_text(), "existing")

    def test_deleted_finished_track_stays_skipped(self):
        self.dl.done = {"42": "Band/Album/deleted.mp3"}
        with patch.object(self.dl, "metadata", return_value={"id": "42", "title": "Song"}), \
                patch.object(self.dl, "download") as download, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.dl.run("https://soundcloud.com/band/song"), 0)
            download.assert_not_called()

    def test_album_partial_failure_and_repeated_track(self):
        album = {"_type": "playlist", "title": "Album", "entries": [
            {"id": "1", "url": "one"}, {"id": "2", "url": "two"}, {"id": "1", "url": "one"}]}
        info = {"id": "1", "title": "Song", "uploader": "Band", "formats": [{"format_id": "http_mp3"}]}
        def save(tags):
            self.assertEqual((tags["album"], tags["track_number"], tags["track_count"]), ("Album", 1, 3))
            self.dl.done[tags["id"]] = "saved.mp3"
        with patch.object(self.dl, "metadata", side_effect=[album, info, ValueError("Unavailable")]), \
                patch.object(self.dl, "download", side_effect=save) as download, \
                patch.object(sc, "prompt", return_value=""), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.dl.run("album"), 1)
            self.assertEqual(download.call_count, 1)
            self.assertNotIn("2", self.dl.done)

    def test_previews_excluded(self):
        info = {"id": "1", "title": "Song", "formats": [{"format_id": "hls_preview"}]}
        with patch.object(self.dl, "metadata", return_value=info), \
                patch.object(self.dl, "download") as download, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.dl.run("track"), 1)
            download.assert_not_called()

    def test_profile_redirect_rejected(self):
        result = subprocess.CompletedProcess([], 0, json.dumps({"extractor_key": "SoundcloudUser", "_type": "playlist"}), "")
        with patch.object(sc.subprocess, "run", return_value=result), self.assertRaises(ValueError):
            self.dl.metadata("https://on.soundcloud.com/abcd", flat=True)

    def test_cli_alias_uses_saved_folder_without_apple_credentials(self):
        cli = runpy.run_path(str(Path(sc.__file__).with_name("musesh")), run_name="musesh_test")
        command = cli["COMMANDS"]["sc"]
        self.assertIs(command, cli["COMMANDS"]["soundcloud"])
        with patch.dict(command.__globals__, load_last=lambda: {"output": str(self.root)}, download_running=lambda: False), \
                patch.object(sc.sys, "argv", ["musesh", "sc", "https://soundcloud.com/band/song"]), \
                patch("os.execv") as execute:
            command()
            args = execute.call_args.args[1]
            self.assertEqual(args[2:], ["--output", str(self.root), "https://soundcloud.com/band/song"])

    def test_homebrew_preferred_over_legacy_path(self):
        with patch.object(Path, "is_file", return_value=True), \
                patch.object(Path, "stat", return_value=Mock(st_mode=0o755)):
            self.assertEqual(sc.find_ytdlp(), "/opt/homebrew/bin/yt-dlp")
        with patch.object(Path, "is_file", return_value=False), \
                patch.object(sc.shutil, "which", return_value="/custom/yt-dlp"):
            self.assertEqual(sc.find_ytdlp(), "/custom/yt-dlp")

    def test_browser_auth_reaches_metadata_and_download(self):
        self.dl.base += ["--cookies-from-browser", "vivaldi"]
        self.dl.authenticated = True
        info = {"id": "42", "title": "Song", "availability": "premium_only",
                "extractor_key": "Soundcloud", "formats": [{"format_id": "http_aac"}]}
        result = subprocess.CompletedProcess([], 0, json.dumps(info), "")
        with patch.object(sc.subprocess, "run", return_value=result) as invoke:
            self.dl.metadata("https://soundcloud.com/band/song")
            args = invoke.call_args.args[0]
            self.assertEqual(args[args.index("--cookies-from-browser") + 1], "vivaldi")
        with patch.object(self.dl, "metadata", return_value=info), patch.object(self.dl, "download") as download, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.dl.run("track"), 0)
            download.assert_called_once()

    def test_explicit_cookie_export_is_copied_and_unchanged(self):
        cookies = self.root / "export.txt"
        original = "# Netscape HTTP Cookie File\n.soundcloud.com\tTRUE\t/\tTRUE\t0\toauth_token\ttest-only\n"
        cookies.write_text(original)
        def check_auth(out, executable, auth_args):
            self.assertEqual(auth_args[0], "--cookies")
            copy = Path(auth_args[1])
            self.assertNotEqual(copy, cookies)
            self.assertEqual(copy.read_text(), original)
            self.assertEqual(copy.stat().st_mode & 0o777, 0o600)
            copy.write_text("updated jar")
            return Mock(run=Mock(return_value=0))
        with patch.object(sc.sys, "argv", ["soundcloud.py", "https://soundcloud.com/band/song", "--cookies", str(cookies)]), \
                patch.object(sc, "find_ytdlp", return_value="yt-dlp"), \
                patch.object(sc.shutil, "which", return_value="tool"), \
                patch.object(sc, "Downloader", side_effect=check_auth) as downloader:
            self.assertEqual(sc.main(), 0)
            temporary = Path(downloader.call_args.args[2][1])
        self.assertFalse(temporary.exists())
        self.assertEqual(cookies.read_text(), original)

    def test_browser_decryption_failure_does_not_silently_use_guest_access(self):
        self.dl.browser_auth = True
        result = subprocess.CompletedProcess([], 0, json.dumps({"extractor_key": "Soundcloud", "id": "42"}),
                                             "WARNING: cannot decrypt v10 cookies: no key found")
        with patch.object(sc.subprocess, "run", return_value=result), contextlib.redirect_stdout(io.StringIO()), \
                self.assertRaisesRegex(ValueError, "--cookies /path/to/soundcloud-cookies.txt"):
            self.dl.metadata("https://soundcloud.com/band/song")

    def test_failed_processing_does_not_record_completion(self):
        child = Mock(stdout=io.StringIO("download failed\n"))
        child.wait.return_value = 1
        tags = sc.track_tags({"id": "42", "title": "Song", "uploader": "Band"})
        with patch.object(sc.subprocess, "Popen", return_value=child), \
                contextlib.redirect_stdout(io.StringIO()), self.assertRaises(ValueError):
            self.dl.download(tags)
        self.assertFalse(self.dl.record.exists())
        self.assertEqual(self.dl.done, {})
        self.assertTrue((self.dl.state / "soundcloud-work/42/info.json").exists())

    def test_interruption_stops_child_and_does_not_record_completion(self):
        child = Mock(stdout=io.StringIO("progress\n"))
        tags = sc.track_tags({"id": "42", "title": "Song"})
        with patch.object(sc.subprocess, "Popen", return_value=child), \
                patch.object(self.dl, "log", side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            self.dl.download(tags)
        child.terminate.assert_called_once()
        child.wait.assert_called_once()
        self.assertFalse(self.dl.record.exists())

    @unittest.skipUnless(shutil.which("yt-dlp") and shutil.which("ffmpeg") and shutil.which("ffprobe"), "requires audio tools")
    def test_real_download_processing_and_completion_offline(self):
        artwork = self.root / "cover.jpg"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=red:size=32x32",
                        "-frames:v", "1", str(artwork)], check=True)
        self.dl.base.append("--enable-file-urls")  # fixtures only; never enabled in production
        for index, (ext, codec, output_ext) in enumerate([
                ("m4a", "aac", "m4a"), ("mp3", "mp3", "mp3"), ("opus", "opus", "opus"),
                ("wav", "pcm_s16le", "flac"), ("flac", "flac", "flac")], 1):
            with self.subTest(ext=ext):
                source = self.root / ("source." + ext)
                subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                                str(source)], check=True)
                track_id = str(40 + index)
                tags = sc.track_tags({"id": track_id, "title": ext, "uploader": "Band", "extractor": "soundcloud",
                                      "extractor_key": "Soundcloud", "webpage_url": "https://soundcloud.com/band/song",
                                      "thumbnails": [{"url": artwork.as_uri(), "id": "cover"}],
                                      "formats": [{"format_id": "native", "url": source.as_uri(), "ext": ext,
                                                   "vcodec": "none", "acodec": codec}]}, "Album", index, 5)
                with contextlib.redirect_stdout(io.StringIO()), contextlib.ExitStack() as stack:
                    if ext == "wav":
                        stack.enter_context(patch.object(Path, "hardlink_to", side_effect=OSError(errno.EOPNOTSUPP, "exFAT")))
                    self.dl.download(tags)
                dest = self.dl.out / self.dl.done[track_id]
                self.assertEqual(dest.suffix, "." + output_ext)
                self.assertTrue(dest.is_file())
                self.assertIn(track_id, json.loads(self.dl.record.read_text()))
                probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format_tags:stream=codec_name:stream_tags",
                                        "-of", "json", str(dest)], capture_output=True, text=True, check=True)
                data = json.loads(probe.stdout)
                self.assertEqual(data["streams"][0]["codec_name"], "flac" if ext == "wav" else codec)
                tags_out = data.get("format", {}).get("tags", {}) or data["streams"][0].get("tags", {})
                tags_out = {k.lower(): v for k, v in tags_out.items()}
                self.assertEqual(tags_out["artist"], "Band")
                self.assertEqual(tags_out["album"], "Album")
                self.assertTrue(len(data["streams"]) > 1 or "metadata_block_picture" in tags_out)
        gamdl_python = Path.home() / ".local/pipx/venvs/gamdl/bin/python"
        if gamdl_python.exists():
            mirror = self.root / "MP3"
            result = subprocess.run([str(gamdl_python), str(Path(sc.__file__).with_name("mp3.py")),
                                     str(self.dl.out), str(mirror), "--yes"], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(len(list(mirror.rglob("*.mp3"))), 5)



if __name__ == "__main__":
    unittest.main()
