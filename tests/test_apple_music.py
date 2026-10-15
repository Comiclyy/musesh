import contextlib
import io
import runpy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import apple_music as apple


class LinkTests(unittest.TestCase):
    def test_album_share_song_selection_and_tracking(self):
        self.assertEqual(apple.parse_link("https://music.apple.com/ca/album/album-name/123?i=456&ls=1"), ("ca", "song", "456"))
        self.assertEqual(apple.parse_link("https://music.apple.com/us/song/title/456?ls=1"), ("us", "song", "456"))
        self.assertEqual(apple.parse_link("https://music.apple.com/ca/album/123"), ("ca", "album", "123"))

    def test_invalid_or_unsupported_links(self):
        for url in ("https://music.apple.com.evil/us/song/123", "https://user@music.apple.com/us/song/123",
                    "https://music.apple.com/us/artist/name/123", "https://music.apple.com/us/playlist/list/pl.123",
                    "https://music.apple.com/us/album/name/123?i=", "https://music.apple.com/us/album/name/123?i=1&i=2",
                    "https://music.apple.com/us/album/name/123?i=no", "file:///us/song/123"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                apple.parse_link(url)

    def test_cli_alias_and_saved_cookies(self):
        cli = runpy.run_path(str(Path(apple.__file__).with_name("musesh")), run_name="musesh_test")
        command = cli["COMMANDS"]["apple"]
        self.assertIs(command, cli["COMMANDS"]["am"])
        with tempfile.TemporaryDirectory() as folder:
            cookie = Path(folder) / "cookies.txt"
            cookie.touch()
            with patch.dict(command.__globals__, load_last=lambda: {"cookies": str(cookie), "output": folder},
                            download_running=lambda: False, VENV_PYTHON=cookie), \
                    patch("sys.argv", ["musesh", "am", "https://music.apple.com/us/song/456"]), patch("os.execv") as execute:
                command()
                self.assertEqual(execute.call_args.args[1][2:], ["--output", folder, "--cookies", str(cookie),
                                                                "https://music.apple.com/us/song/456"])


class DownloadTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.out = Path(self.temp.name)
        self.progress = SimpleNamespace(done=set())
        self.progress.mark_done = self.progress.done.add
        self.api = SimpleNamespace(storefront="ca", get_song=AsyncMock(return_value={"data": [
            {"id": "456", "attributes": {"name": "Song", "artistName": "Band"}}]}),
            get_album=AsyncMock(return_value={"data": [{"id": "123", "attributes": {"name": "Album", "artistName": "Band"},
                "relationships": {"tracks": {"data": [{"id": "456", "type": "songs"}, {"id": "789", "type": "songs"}]}}}]}),
            _amp_request=AsyncMock())
        def download(urls, state, cookies, out, extra, progress):
            progress.done.update(urls)
        self.library = SimpleNamespace(state_dir_for=lambda out: out, Progress=lambda state: self.progress,
                                       login=AsyncMock(return_value=self.api), run_gamdl=Mock(side_effect=download))

    def tearDown(self):
        self.temp.cleanup()

    async def run_link(self, url, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return await apple.download_link(url, self.out, self.out / "cookies.txt", library=self.library, **kwargs)

    async def test_song_link_uses_account_storefront_and_shared_tracking(self):
        self.assertEqual(await self.run_link("https://music.apple.com/us/album/name/123?i=456"), 0)
        self.api.get_song.assert_awaited_once_with("456")
        self.api.get_album.assert_not_called()
        self.assertEqual(self.library.run_gamdl.call_args.args[0], ["https://music.apple.com/ca/song/456"])

    async def test_finished_song_stays_skipped_across_countries_after_deletion(self):
        self.progress.done.add("https://music.apple.com/us/song/456")
        self.assertEqual(await self.run_link("https://music.apple.com/ca/song/name/456"), 0)
        self.library.login.assert_not_called()
        self.library.run_gamdl.assert_not_called()

    async def test_album_skips_done_songs_and_records_completion(self):
        self.progress.done.add("https://music.apple.com/us/song/456")
        self.assertEqual(await self.run_link("https://music.apple.com/us/album/123", assume_yes=True), 0)
        self.assertEqual(self.library.run_gamdl.call_args.args[0], ["https://music.apple.com/ca/song/789"])
        self.assertIn("https://music.apple.com/ca/album/123", self.progress.done)

    async def test_partial_album_is_retryable_and_not_marked_complete(self):
        self.library.run_gamdl.side_effect = lambda *args: self.progress.done.add("https://music.apple.com/ca/song/456")
        self.assertEqual(await self.run_link("https://music.apple.com/us/album/123", assume_yes=True), 1)
        self.assertNotIn("https://music.apple.com/ca/album/123", self.progress.done)
        self.library.run_gamdl.reset_mock()
        await self.run_link("https://music.apple.com/us/album/123", assume_yes=True)
        self.assertEqual(self.library.run_gamdl.call_args.args[0], ["https://music.apple.com/ca/song/789"])

    async def test_album_review_and_decline_do_not_download_or_record(self):
        await self.run_link("https://music.apple.com/us/album/123", review_only=True)
        with patch.object(apple, "prompt", return_value="n"):
            await self.run_link("https://music.apple.com/us/album/123")
        self.library.run_gamdl.assert_not_called()
        self.assertEqual(self.progress.done, set())

    async def test_album_pagination_skips_videos_and_deduplicates(self):
        item = self.api.get_album.return_value["data"][0]
        item["relationships"]["tracks"]["next"] = "/v1/catalog/ca/albums/123/tracks?offset=2"
        self.api._amp_request.return_value = {"data": [{"id": "999", "type": "songs"},
                                                       {"id": "456", "type": "songs"}, {"id": "888", "type": "music-videos"}]}
        await self.run_link("https://music.apple.com/us/album/123", assume_yes=True)
        self.assertEqual(len(self.library.run_gamdl.call_args.args[0]), 3)

    async def test_unexpected_pagination_never_receives_credentials(self):
        item = self.api.get_album.return_value["data"][0]
        item["relationships"]["tracks"]["next"] = "https://evil.example/tracks"
        with self.assertRaises(ValueError):
            await self.run_link("https://music.apple.com/us/album/123", assume_yes=True)
        self.api._amp_request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
