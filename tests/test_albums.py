import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

if importlib.util.find_spec("gamdl") is not None:
    import albums
else:
    albums = None


@unittest.skipIf(albums is None, "run with gamdl's Python for album-helper tests")
class AlbumPlaylistTests(unittest.IsolatedAsyncioTestCase):
    async def test_playlist_is_resolved_without_itunes_album_lookup_or_download(self):
        url = "https://music.apple.com/ca/playlist/mink/pl.u-kv9llgjt7N9NK22"
        api = Mock(storefront="ca")
        api.get_playlist = AsyncMock(return_value={"data": [{
            "attributes": {"name": "mink", "curatorName": "Listener"},
            "relationships": {"tracks": {"data": [{"id": "1"}, {"id": "2"}]}},
        }]})
        with tempfile.TemporaryDirectory() as folder:
            entries = [{"line": url, "url": url}]
            with patch.object(albums, "itunes_get", new_callable=AsyncMock) as lookup, \
                    patch.object(albums.L, "run_gamdl") as download:
                await albums.resolve(entries, api, Path(folder) / "cache.json")
            api.get_playlist.assert_awaited_once_with("pl.u-kv9llgjt7N9NK22")
            lookup.assert_not_called()
            download.assert_not_called()
            self.assertEqual(entries[0]["albums"][0]["url"], url)
            self.assertEqual(entries[0]["albums"][0]["tracks"], 2)

    async def test_unavailable_playlist_stays_missing(self):
        api = Mock(get_playlist=AsyncMock(return_value={"data": []}))
        url = "https://music.apple.com/ca/playlist/mink/pl.u-test"
        entries = [{"line": url, "url": url}]
        with tempfile.TemporaryDirectory() as folder:
            await albums.resolve(entries, api, Path(folder) / "cache.json")
        self.assertEqual(entries[0]["albums"], [])

    async def test_album_links_keep_existing_lookup(self):
        api = Mock(storefront="ca")
        url = "https://music.apple.com/ca/album/123"
        entries = [{"line": url, "url": url}]
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(albums, "itunes_get", new_callable=AsyncMock, return_value=[]) as lookup:
                await albums.resolve(entries, api, Path(folder) / "cache.json")
            lookup.assert_awaited_once_with(albums.ITUNES_LOOKUP_URL, {"id": "123", "country": "ca"})
            self.assertEqual(entries[0]["albums"][0]["url"], url)
