# Troubleshooting

## Cookies

Apple Music and SoundCloud use **different cookie exports**. Keep them in
separate local files. Never include cookie contents, authorization headers or
signed media URLs when sharing diagnostics.

**"Cookies problem ... Apple rejected the login - the cookies are probably expired"**<br/>
Export them again from [music.apple.com](https://music.apple.com) while
signed in, then run the same command. If you used `musesh` before, update the
path by running `musesh` once (or edit `cookies` in
`~/.config/musesh/settings.json`).
For a direct link, you can instead pass `musesh am "URL" --cookies PATH`.

**"... it has no Apple Music login in it (media-user-token is missing)"**<br/>
The export was made while signed out, or from the wrong site. Sign in at
music.apple.com first.

**"Couldn't reach Apple Music after 4 tries"**<br/>
Loading Apple Music's web page failed repeatedly. That's a network problem,
not your cookies. Check your connection and try again.

**"5 songs in a row failed to download, so stopping here"**<br/>
Almost always cookies that expired mid-run. Export fresh ones and run
`musesh continue`; the 5 songs are retried, not counted as failures.

## Downloads

**How do I resume a direct-link download?**<br/>
Repeat `musesh am "URL"` or `musesh sc "URL"` with the same authentication
options. Finished tracks stay skipped, including files you deliberately
deleted. `musesh continue` resumes Library.xml batches only. Direct links
don't need a Library.xml export.

**An Apple Music song link downloaded the wrong amount of music**<br/>
An album URL with `?i=SONG_ID` selects one song. Remove that query parameter
to request the whole album. Quote the entire URL so your shell keeps its
query string intact. `musesh am "URL" --review-only` shows the selection first.

**An Apple Music link is unavailable in my storefront**<br/>
The downloader uses your account's storefront, even if the link was copied
from another country's page. The catalog ID may not be available there. Use
a link to the edition offered in your own Apple Music account. Artist,
playlist and music-video links aren't accepted by `apple` / `am`.

**It looks frozen, with no gamdl output**<br/>
It's probably looking up the songs your cloud library didn't match. That
step is quiet on purpose (it paces requests to stay under Apple's limits) and
prints a line every 10 songs. `musesh status` shows whether it's running.

**A song failed with "Resource Not Found" (404)**<br/>
The song's ID may be dead because the album was re-released. Library.xml
downloads record it and search again; run `musesh continue`. Direct-link
downloads preserve your exact selection instead: copy a working song or
album link from Apple Music and retry with `musesh am "URL"`.

**A song failed with "license exchange ... -1003"**<br/>
A momentary error from Apple's DRM license server. Run the command again; the
rest of the album is kept and only the missing song is fetched.

**Songs are in `unmatched.csv`**<br/>
Usually uploads that were never on Apple Music (SoundCloud rips and similar),
songs removed from the catalog, or songs not available in your account's
country. For an album, add its `music.apple.com` link to your album list.

**The Mac slept and the download stopped**<br/>
Finished work is kept. Use `musesh continue` for library batches, or repeat
the original direct-link command for Apple Music or SoundCloud. See
[Keeping the Mac awake](setup.md#keeping-the-mac-awake).

**"A download is already running"**<br/>
Only one download runs at a time. Follow it with `musesh watch`, or wait for
it to finish.

## SoundCloud

**"Only a preview is available; skipping it"**<br/>
SoundCloud exposed only preview formats to yt-dlp. musesh doesn't save them
or mark the track complete. A displayed full duration doesn't prove playback
access: try playing beyond 30 seconds in your signed-in browser. If the page
shows **Listen with Go+** or **Unlock every track**, cookies alone won't unlock
it. If full playback works, retry with cookies from that same account/profile:

```sh
musesh sc "URL" --cookies-from-browser vivaldi
# Or use a Netscape-format SoundCloud export:
musesh sc "URL" --cookies ~/Downloads/soundcloud.com_cookies.txt
```

If the downloader still gets a preview, browser playback and API access may
differ. Compare browser-only VPN/proxy settings and ensure the export is fresh.
Don't remove preview checks: they prevent an incomplete file being treated as
a finished song.

**"Browser login cookies could not be decrypted" / "no key found"**<br/>
yt-dlp couldn't read the browser's encrypted cookies, so musesh stops instead
of silently using guest access. Allow the normal macOS Keychain prompt if it
appears, or export only SoundCloud cookies in Netscape format and use
`--cookies PATH`. `--cookies` and `--cookies-from-browser` can't be combined.

**Python 3.9 deprecation or LibreSSL / `NotOpenSSLWarning` messages**<br/>
An old user-site yt-dlp may be using Apple's Python. Install the Homebrew
version with `brew install yt-dlp`, or update it with `brew upgrade yt-dlp`.
musesh prefers Homebrew's executable over older copies on PATH, so no shell
PATH override is needed. `yt-dlp --version` in your shell may still resolve
to an older copy; `/opt/homebrew/bin/yt-dlp --version` checks Apple Silicon's
Homebrew installation directly (`/usr/local/bin/yt-dlp` on Intel).

**A track has the wrong artist or no album**<br/>
SoundCloud metadata can be incomplete. The downloader uses provided artist
metadata, then the uploader; it keeps the title intact. A set's title becomes
the album, while standalone tracks without album metadata use `Unknown Album`.
Edit tags locally if needed; musesh doesn't guess an artist from the title.

**Why isn't everything MP3 already?**<br/>
SoundCloud downloads preserve the best accessible native audio to avoid a
second lossy encode. WAV/AIFF originals become lossless FLAC for tagging and
artwork. Run `musesh mp3` to make the MP3 copy. Existing MP3 sources are copied
as they are; encoding a low-bitrate file at 320 kbps doesn't improve its sound.

## Library folder

**Deleted songs came back**<br/>
Only the full `musesh` downloader does this: re-running it copies your own
files from the Music app again if they're missing. Use `musesh continue` and
`musesh align` for everything after the first download; neither brings back
deleted songs.

**Empty folders everywhere after deleting music**<br/>
`musesh clean`. It also removes the `.lrc` lyric files a deleted song leaves
behind, which are what keep those folders from being empty.

**Songs without an artist are in `Unknown Artist/Unknown Album`**<br/>
They're your own files with no tags. Fix the tags (Swinsian, Meta, Mp3tag)
and move them; musesh never renames your own files.

## MP3

**"No USB drive plugged in"**<br/>
Plug it in and choose *Look again for a USB drive*, or convert to
your `~/Music/musesh/Library` on the Mac instead.

**`prune` refuses: "don't have a good MP3 yet"**<br/>
That's it working. Run `musesh mp3` to convert (or redo) the files it listed,
then `musesh prune` again.

**The time estimate jumps around at the start**<br/>
It's based on the megabytes converted so far, so it settles after the first
few files.

## Walkman transfers and storage

**Push reports “Operation not supported” while publishing a song**<br/>
Current push supports FAT32 publication without requiring hard links. Update
musesh and rerun `musesh push`; verified songs remain remembered and pending
songs are offered again. No need to delete the transfer history.

**The cable disconnects during push**<br/>
Leave the confirmed push running and reconnect the same player. Timestamped
connection messages show it watching and resuming automatically; no new
confirmation is needed for that batch. Ctrl-C stops the watcher. This automatic
watching applies to Mac `push`; the Windows launcher retries on its next run.

**Deleting in Swinsian did not free space**<br/>
“Remove From Library” leaves the file on disk. “Remove and Move To Trash” moves
it into the player's hidden Trash, which still consumes space. See
[Swinsian deletion instructions](swinsian.md#delete-songs-from-the-player).
A built-in player Trash cleanup command is still deferred.

**A player song is missing in Swinsian**<br/>
Check its folder: `RECEIVED` is separate from the watched `MUSIC` folder. Import
or watch it explicitly. Rescan the watched folder after external transfers.

**Ejection fails or says the player is busy**<br/>
Finish transfers, stop playback, and close files or apps using the player.
Stop an active/reconnecting push before running `musesh eject`. It never forces
unmounting, and a failure or timeout does not confirm that unplugging is safe.

## Still stuck

Background runs log to `~/Music/musesh/Incoming/.musesh/*.log`; `musesh watch` shows the
newest known log. Direct Apple Music links write `apple-run.log`; SoundCloud
writes `soundcloud-run.log` even when started in your terminal. Logs live in
your saved Incoming folder if you've changed it. Include relevant error lines
when reporting an issue, with private URLs and authentication data removed.
