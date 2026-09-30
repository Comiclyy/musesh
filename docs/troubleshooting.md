# Troubleshooting

## Cookies

**"Cookies problem ... Apple rejected the login - the cookies are probably expired"**<br/>
Export them again from [music.apple.com](https://music.apple.com) while
signed in, then run the same command. If you used `musesh` before, update the
path by running `musesh` once (or edit `cookies` in
`~/.config/musesh/last-run.json`).

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

**It looks frozen, with no gamdl output**<br/>
It's probably looking up the songs your cloud library didn't match. That
step is quiet on purpose (it paces requests to stay under Apple's limits) and
prints a line every 10 songs. `musesh status` shows whether it's running.

**A song failed with "Resource Not Found" (404)**<br/>
The song's ID is dead, usually because the album was re-released. musesh
records it and searches for the current version automatically; run
`musesh continue`.

**A song failed with "license exchange ... -1003"**<br/>
A momentary error from Apple's DRM license server. Run the command again; the
rest of the album is kept and only the missing song is fetched.

**Songs are in `unmatched.csv`**<br/>
Usually uploads that were never on Apple Music (SoundCloud rips and similar),
songs removed from the catalog, or songs not available in your account's
country. For an album, add its `music.apple.com` link to your album list.

**The Mac slept and the download stopped**<br/>
Nothing is lost: `musesh continue`. To stop it happening, see
[Keeping the Mac awake](setup.md#keeping-the-mac-awake).

**"A download is already running"**<br/>
Only one download runs at a time. Follow it with `musesh watch`, or wait for
it to finish.

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
`~/Music/Library Download MP3` on the Mac instead.

**`prune` refuses: "don't have a good MP3 yet"**<br/>
That's it working. Run `musesh mp3` to convert (or redo) the files it listed,
then `musesh prune` again.

**The time estimate jumps around at the start**<br/>
It's based on the megabytes converted so far, so it settles after the first
few files.

## Still stuck

Background runs log to `<library>/.library-dl/*.log`; `musesh watch` shows the
newest one. Include the last lines of it when reporting an issue.
