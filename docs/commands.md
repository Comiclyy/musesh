# Commands

Every command is interactive where it needs to be: numbered menus with the
default marked, `c` to type or drag in a path, and `[Y/n]` questions. Every
command is safe to stop with **Ctrl-C** and run again; finished work is kept
and skipped.

- [Download](#download): `musesh`, `continue`, `align`, `albums`, `apple` / `am`, `soundcloud` / `sc`
- [Keep an eye on it](#keep-an-eye-on-it): `watch`, `status`, `library`, `formats`
- [Tidy up and take it with you](#tidy-up-and-take-it-with-you): `clean`, `mp3`, `push`, `eject`, `prepare`, `transfer setup`, `prune`, `migrate`

---

## Download

### `musesh apple [URL]` / `musesh am [URL]`

Download an Apple Music song or album directly from its share link. Omitting
the URL prompts for one. These examples are templates; replace their URLs
with your links. Quote links containing query parameters:

```sh
musesh am "https://music.apple.com/ca/song/song-title/123456789"
musesh apple "https://music.apple.com/ca/album/album-title/123456789"
musesh am "https://music.apple.com/ca/album/album-title/123456789?i=987654321"
```

An album link with `?i=...` downloads **only the selected song**. An album link
without it shows the pending track count and asks before downloading; `-y` /
`--yes` skips confirmation. `--review-only` resolves and displays the link
without downloading. Artist, playlist and music-video links aren't supported.

Uses gamdl, your saved Apple Music cookies, and your saved Incoming folder.
Without saved cookies, the newest `*apple*cookie*.txt` export in Downloads is
used if present. Override with `--cookies /path/to/music.apple.com_cookies.txt`.
An active Apple Music subscription is required; no Library.xml is needed.
Catalog access uses your account's storefront, as the library downloader does.

Native audio, tags, artwork and `Artist/Album` organization follow the existing
Apple Music downloader. Run `musesh mp3` afterwards for the MP3 copy. Song IDs
share the existing Apple Music completion records: previously downloaded songs
stay skipped, even after deletion or when supplied in a different country's
share link. Partial album downloads resume at unfinished songs when the same
link is rerun. Albums already marked complete by `musesh albums` stay skipped.
`musesh watch` follows `apple-run.log`; `musesh status` includes completion in
its existing Apple Music count. `musesh continue` still resumes Library.xml
batches; rerun the direct link to resume a direct-link download.

### `musesh soundcloud [URL]` / `musesh sc [URL]`

Download a **public track or album/set** from SoundCloud. Without a URL, it
prompts for one. Quote links so the shell doesn't interpret their query strings:

```sh
musesh sc "https://soundcloud.com/artist/track"
musesh soundcloud "https://soundcloud.com/artist/sets/album"
```

Requires `brew install yt-dlp ffmpeg`. The Homebrew yt-dlp is preferred over
older user-site installations on PATH. No Apple Music setup is needed.
Public downloads need no login. Artist profiles, private links and preview-only
audio are not supported. Album/set downloads show a summary and
ask before starting; unavailable tracks do not prevent the others downloading.

For tracks requiring your SoundCloud account, sign into SoundCloud in your
browser and pass its name (an optional profile is supported):

```sh
musesh sc "https://soundcloud.com/artist/track" --cookies-from-browser vivaldi
# Or use a local Netscape-format SoundCloud cookie export:
musesh sc "https://soundcloud.com/artist/track" --cookies ~/Downloads/soundcloud-cookies.txt
```

These options are mutually exclusive and apply to this invocation only.
Browser access may prompt for macOS Keychain permission. Cookie values are
never printed or saved in musesh settings; explicit exports are copied to a
private temporary jar so the original file stays unchanged. Do not paste
cookies into chat or commit them. A login does not grant access beyond your
account: some full tracks require SoundCloud Go+, and preview-only results
are still skipped. See [yt-dlp's cookie instructions](https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp).
If browser cookies cannot be decrypted (for example, Vivaldi reports “no key
found”), musesh stops and asks for a local Netscape-format export instead.

Files go into your saved Incoming folder (default `~/Music/musesh/Incoming`),
using `Artist/Album/Title.ext`. Albums/sets use the set title and numbered
tracks; individual tracks use their album metadata or `Unknown Album`.
The uploader is used when artist metadata is absent. Available tags and cover
art are embedded, and existing files are never overwritten.

The best accessible native audio is kept: MP3 stays MP3, AAC/Opus stays native,
and lossless audio stays lossless (WAV/AIFF is converted losslessly to FLAC for
tag/artwork support). Creator-enabled originals are preferred when publicly
accessible; streams are used otherwise. Run `musesh mp3` afterwards to make
the MP3 copy, keeping the existing organization and native sources.

Finished track IDs are remembered separately from Apple Music. Repeating a
link, or encountering the same track in another set, skips it even after its
local file was deleted. Failures remain retryable: rerun the same link after
a failure or Ctrl-C. `musesh continue` remains the Apple Music batch command.
Use `musesh status` for the handled count and `musesh watch` for the run log.
If SoundCloud extraction stops working, try `brew upgrade yt-dlp`.

### `musesh`

Downloads the library from a `Library.xml` export, in batches.

- **Your own files** (anything in the export with a file on disk) are copied
  as they are. They are never looked up on Apple Music.
- **Apple Music tracks** are matched to catalog IDs (see
  [How it works](how-it-works.md#matching-songs-to-apple-music)) and downloaded
  as 256 kbps AAC with tags and cover art.
- Tracks that can't be matched are written to `unmatched.csv` in the library
  folder.

Layout: `Artist/Album/01 Title.m4a`, `Compilations/Album/...` for
various-artists albums, and `Artist/Unknown Album/...` for tracks without
album info.

### `musesh continue [N|all]`

Runs the next batch with the choices from last time, without asking anything.

| Form | Does |
| --- | --- |
| `musesh continue` | Next batch, same size as before |
| `musesh continue 100` | Batches of 100 from now on |
| `musesh continue all` | Everything that's left |

### `musesh align`

Keeps the folder up to date with songs you've added in Apple Music since.

1. Export your library again (**File > Library > Export Library...**).
2. `musesh align`, and pick that export.
3. It lists only **truly new** songs. Choose which: Enter for all, `1-5,8`
   for some, or `none`.
4. Choose what to do with them:

   | Choice | Result |
   | --- | --- |
   | Download into the library folder *(default)* | Downloads them now |
   | Download into a drive / another folder | Same, elsewhere |
   | Save the list to a text file | `~/Music/musesh/new-songs-DATE.txt`; offered again next time |
   | Skip for now | Offered again next time |
   | Ignore these for good | Never offered again |

If two or more of the chosen songs come from the same album, it asks once per
album: *Download the whole album? [y/N]*.

"New" means a song this folder has never seen before, so **songs you deleted
from the folder never come back**. Details in
[How it works](how-it-works.md#what-align-considers-new).

### `musesh albums [list]`

Downloads whole albums from a plain-text list (default
`~/Music/musesh/albums.txt`). One entry per line:

```text
# comments start with #
Miles Davis - Kind of Blue                  one album
my bloody valentine - * +eps                every studio album, plus EPs
Sonic Youth - *                             every studio album
https://music.apple.com/ca/album/1446912991 an exact album
https://music.apple.com/ca/playlist/name/PLAYLIST_ID  the tracks in a playlist
```

It looks every line up, shows exactly which album (and edition, year and
track count) it matched, and asks before downloading. Albums already
downloaded are skipped, so the list can keep growing. See
[examples/albums.txt](../examples/albums.txt).

Apple Music playlist links can also be included. Their tracks are downloaded
through gamdl; the link selects the entire playlist, including any other artists
it contains. Private or unavailable playlists are reported as not found.

If a lookup picks the wrong edition, or finds nothing (an artist credited
differently, say), replace the line with the album's `music.apple.com` link.

---

## Keep an eye on it

### `musesh watch`

Follows the newest known download log, including `apple-run.log` for direct
Apple Music links and `soundcloud-run.log` for SoundCloud. Ctrl-C stops
watching, not the download. It watches the saved Incoming folder; direct-link
commands write their logs even when run in your terminal.

### `musesh status`

Where the library and Incoming folders are, their file counts and sizes,
whether a download is running, and how many tracks are unmatched. Apple Music
completion counts include songs and albums from direct links; SoundCloud has
a separate handled-track count. These progress counts remain after deletion
and can differ from the number of files currently on disk.

### `musesh library [--by name|size|songs] [folder] [band...]`

An overview of the collection as a tree: every band with its number of
albums, songs and total size, and its albums underneath with their song
count, size and format.

```text
  Playboi Carti                      10 albums    123 songs  782 MB           5 partial
    Die Lit                                     11/19 songs   76 MB  MP3 320  partial
    Whole Lotta Red                                24 songs  148 MB  MP3 320
    Whole Lotta Red V1 (Unreleased)                56 songs  359 MB  MP3 128-320 +VBR mixed
```

| Form | Shows |
| --- | --- |
| `musesh library` | Everything, bands A to Z (a leading "The" is ignored) |
| `musesh library --by size` | Biggest bands first (and biggest albums first within each) |
| `musesh library --by songs` | Bands with the most songs first |
| `musesh library sonic` | Only bands whose name contains "sonic" |
| `musesh library ~/Some/Folder` | Another folder, like the MP3 copy on a USB drive |

- **Names come from the files' tags** (album artist, then artist), so songs
  in `Compilations/` or with untidy folder names still land under the right
  band. Untagged files fall back to their folder names. Capitalisation
  differences ("Nettspend" / "nettspend") are merged.
- **Partial albums** are flagged when you have fewer songs than the album's
  track-count tag says, e.g. `11/19 songs  partial`, or `partial, 1/2 discs`
  when whole discs are missing. Albums without track-count tags (most of your
  own files) are never flagged.
- **Format** is one label per album: `AAC 256`, `MP3 320`, `MP3 128-320 mixed`
  when bitrates differ, and so on.
- **Default folder:** your library, or the MP3 folder once you've run
  `musesh prune` into it (that's where the collection lives then).

Tags are cached in `~/.cache/musesh/library.json`; a first run over ~1,500
songs takes under a second, later runs about a tenth of that.

### `musesh formats [all|diff] [folder]`

A report on file formats and quality, read from each file's header (nothing
is decoded). The default folder is your library; give another, like the MP3
copy on a USB drive, at the end.

| Form | Shows |
| --- | --- |
| `musesh formats` | One line per distinct format, with file count, size and share |
| `musesh formats all` | Every file, one per line |
| `musesh formats diff` | Only files that aren't in the library's most common format |

Columns, separated by `|`: type (`M4A`, `MP3`, `FLAC`, ...; `DRM` for
copy-protected files), codec (`AAC LC`, `HE-AAC`, `ALAC`, `MP3`, `FLAC`,
`PCM`...), bitrate, `CBR`/`VBR` for MP3, sample rate, bit depth (lossless
only), channels, lossless or lossy, and size. Empty columns are hidden. Long
output opens in a pager (`q` or Ctrl-C to quit).

Results are cached in `~/.cache/musesh/formats.json`, so repeat runs only
read new or changed files.

---

## Tidy up and take it with you

### `musesh clean`

After deleting music (in Swinsian, Finder, anywhere), removes the folders it
left empty, including leftover `.lrc` lyric files whose song is gone. It
lists what it will remove and asks first. It never touches the hidden `.musesh/` folders.

### `musesh mp3 [folder]`

Mirrors the library as **320 kbps MP3**, keeping the folder layout, tags and
cover art. Your library is only read, never changed.

- **Where:** a plugged-in USB drive is the default (`<drive>/Music`). With no
  drive it converts `Incoming/` into your `Library/`, and offers "look again"
  once you plug one in. `musesh mp3 ~/Some/Folder` skips the question.
- **Re-runs are cheap.** Each existing MP3 is checked by reading its header:

  | Found in the MP3 folder | Action |
  | --- | --- |
  | A 320 kbps MP3 of the right length | skipped (up to date) |
  | An MP3 at another bitrate, or cut short | redone |
  | Half-written files from a stopped run, non-MP3 audio | deleted |
  | An MP3 whose song is gone from the library | listed, and you're asked (default: keep) |

- MP3s already in your library are **copied as they are**; re-encoding a
  128 kbps MP3 at 320 only makes it bigger.
- Each file prints as it finishes, with a counter and a time-left estimate
  (based on the megabytes left, so long songs don't throw it off).

### `musesh eject`

Safely eject the configured Walkman on macOS:

```sh
musesh eject
```

Detects the same player as `push`, refuses while a push is running (including
waiting for reconnection), and uses normal macOS ejection to flush pending
writes. Busy volumes are not forced off. Close files or apps using the player
and retry if ejection fails. “Safe to unplug” appears only after successful
ejection and verification that the volume is no longer mounted. This does not
empty the player's Trash. Other copy operations should finish before ejecting.

### `musesh push`

Copy new MP3s from your local Library directly to the connected Walkman:

```sh
musesh mp3              # convert downloads into the local Library first
musesh push             # show every proposed addition, then ask before copying
musesh push --dry-run   # preview without copying or recording anything
```

The preview groups **every song** by artist and album, with individual and album
sizes, a total, and free space before and after. Enter cancels; only `y` or `yes`
starts copying. There is no automatic-confirmation flag.

- **First run:** use download/addition dates from the last seven days. Older
  Library files are remembered as excluded, even when absent from the player.
  These are the dates preserved through conversion, not tag-edit timestamps.
  For older files without recorded dates, file creation time is the approximation
  (modification time if creation time is unavailable).
- **Later runs:** pick up new additions after that initial cutoff and retry
  unfinished work, even if it has since aged beyond seven days. The cutoff does
  not advance past failed songs.
- **Deletions stay deleted:** successful copies and pre-existing player paths are
  remembered. Removing them in Swinsian, Finder, or on Windows does not make push
  restore them. Editing a handled Library song does not queue it again either.
  Before the first confirmed push, there is no transfer history: a recent song
  already deleted from the player cannot be distinguished from one never copied.
  Review that first list and cancel if it contains music you do not want.
- **MP3s are copied as they are.** Native sources stay in Incoming, Library files
  stay on the Mac, and existing player music is never overwritten or removed.
- **Interrupted USB copies:** hidden temporary files are verified before becoming
  visible MP3s. Completed songs are recorded one at a time; rerunning resumes the
  rest after a stopped process. During a confirmed transfer, disconnection pauses
  the copy and starts watching for the same player's volume UUID. Timestamped
  `DISCONNECTED`, `WATCHING`, and `RECONNECTED` messages show connection status,
  including a waiting reminder every ten seconds. Reconnecting automatically
  retries the unfinished song without another prompt, even if macOS changes its
  mount path. Verified songs stay skipped, different players are ignored, and
  songs downloaded during the pause are left for a future preview. USB I/O errors
  also trigger this pause-and-watch flow. **Ctrl-C** stops watching; a later
  `musesh push` can resume the saved pending work with a new confirmation.
- **Live progress:** each song shows its position in the batch and full path. In
  a terminal, a progress bar shows percentage, bytes, speed, and time remaining,
  followed by flushing and verification phases. A song is marked finished only
  after verification and saving its transfer history. Redirected output keeps
  readable per-song status lines.
- **Insufficient space:** the complete preview is still shown, then push stops
  without copying if the proposed batch will not fit with a small safety reserve.

The usual destination is `/Volumes/WALKMAN/MUSIC`; the configured player's UUID
is remembered so another drive is not chosen by accident. Advanced overrides are
`--library /path/to/MP3s` and `--player /Volumes/Player` (the player must be a
writable external mount). Per-player history lives in `~/Music/musesh/.push/`;
keep it to retain the deletion protection. The preview-only mode leaves that
history unchanged.

`push` writes through the Mac's USB connection. Use `musesh prepare` and the
Windows launcher when that connection is unstable. The two workflows currently
keep separate transfer histories; push checks existing player paths but cannot
infer earlier Windows transfers that were subsequently deleted.

### `musesh prepare [day|start..end]`

Prepare MP3s on the Mac and publish them into your Windows shared folder:

```sh
musesh prepare                         # new songs not yet successfully uploaded
musesh prepare 2026-10-16              # songs added on one day
musesh prepare 2026-10-01..2026-10-16  # inclusive range
```

The default starts tracking from setup time; earlier music is available through
explicit dates. Dates mean addition to musesh, in the Mac's local timezone,
and survive MP3 conversion. Existing files use creation time (or modification
time where creation time is unavailable), so historical dates are approximate.
Edited tags do not reset an already recorded addition date.

Run `musesh-transfer.cmd` on Windows to upload all pending batches without
prompts. Windows success receipts determine what has been uploaded. Preparation
alone never acknowledges a song. Repeat preparation or transfer to retry failures.

### `musesh transfer setup <shared-folder>`

One-time setup for the [Windows transfer workflow](windows-transfer.md):

```sh
musesh transfer setup /Volumes/MuseshTransfer
```

The folder must already be mounted and writable. Setup installs the Windows
launcher and saves the handoff location. It uses the saved Incoming folder and
local Library folders. For a custom collection, add `--source /path/to/music`
(repeat for multiple folders). Earlier sources take precedence over later ones
when both contain the same relative song path. Repeating setup preserves the
original tracking start time.

### `musesh prune [folder]`

After `musesh mp3`: frees the space the originals take, once it is safe to.
It never runs by itself.

1. **Verifies every non-MP3 original** in the library has an MP3 in the MP3
   folder that is 320 kbps, the right length, and **decodes cleanly from start
   to finish**.
2. **If anything fails, nothing is deleted.** It lists the problems, removes
   any broken MP3s so the next `musesh mp3` redoes them, and stops.
3. **If everything passes,** it shows the space to be freed and asks you to
   type `delete`. Then it removes the originals and the folders they leave
   empty. Your own MP3s stay. A typo just asks again (three tries); Enter
   cancels.

Verification results are remembered in `<mp3 folder>/.musesh/verified.json`.
MP3s that passed and haven't changed since (and whose originals haven't
either) aren't decoded again, so after a cancelled or stopped prune the next
one goes straight to the question.

Pruned songs are recorded in `<mp3 folder>/.musesh/`, so later `musesh mp3`
runs never mistake their MP3s for orphans.

> [!CAUTION]
> Pruning can't be undone. Apple Music songs can be downloaded again with
> musesh; your own files can't, unless you have them elsewhere.

### `musesh migrate`

Moves an older setup into `~/Music/musesh`, once:

| Old | New |
| --- | --- |
| `~/Music/Library Download MP3` | `~/Music/musesh/Library` |
| `~/Music/Library Download` | `~/Music/musesh/Incoming` |
| `.../unmatched.csv` | `~/Music/musesh/unmatched.csv` |
| `~/Documents/musesh-albums.txt` | `~/Music/musesh/albums.txt` |
| `~/Documents/musesh-new-songs-*.txt` | `~/Music/musesh/new-songs-*.txt` |
| hidden `.library-dl/` | hidden `.musesh/` (all progress kept) |
| `~/.config/musesh/last-run.json` | `~/.config/musesh/settings.json` |

It lists every move and asks first. Everything is a rename on the same disk,
so it's instant and nothing is copied or downloaded again. Anything already in
the new place is left alone. Other commands remind you to run it while the old
folders are still around.
