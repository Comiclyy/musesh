# Commands

Every command is interactive where it needs to be: numbered menus with the
default marked, `c` to type or drag in a path, and `[Y/n]` questions. Every
command is safe to stop with **Ctrl-C** and run again; finished work is kept
and skipped.

- [Download](#download): `musesh`, `continue`, `align`, `albums`
- [Keep an eye on it](#keep-an-eye-on-it): `watch`, `status`, `formats`
- [Tidy up and take it with you](#tidy-up-and-take-it-with-you): `clean`, `mp3`, `prune`

---

## Download

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
   | Save the list to a text file | `~/Documents/musesh-new-songs-DATE.txt`; offered again next time |
   | Skip for now | Offered again next time |
   | Ignore these for good | Never offered again |

If two or more of the chosen songs come from the same album, it asks once per
album: *Download the whole album? [y/N]*.

"New" means a song this folder has never seen before, so **songs you deleted
from the folder never come back**. Details in
[How it works](how-it-works.md#what-align-considers-new).

### `musesh albums [list]`

Downloads whole albums from a plain-text list (default
`~/Documents/musesh-albums.txt`). One entry per line:

```text
# comments start with #
Miles Davis - Kind of Blue                  one album
my bloody valentine - * +eps                every studio album, plus EPs
Sonic Youth - *                             every studio album
https://music.apple.com/ca/album/1446912991 an exact album
```

It looks every line up, shows exactly which album (and edition, year and
track count) it matched, and asks before downloading. Albums already
downloaded are skipped, so the list can keep growing. See
[examples/albums.txt](../examples/albums.txt).

If a lookup picks the wrong edition, or finds nothing (an artist credited
differently, say), replace the line with the album's `music.apple.com` link.

---

## Keep an eye on it

### `musesh watch`

Follows the log of a download running in the background, live. Ctrl-C stops
watching, not the download.

### `musesh status`

Where the library is, how many songs are downloaded, whether a download is
running, and how many tracks are unmatched.

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
lists what it will remove and asks first. It never touches `.library-dl/`.

### `musesh mp3 [folder]`

Mirrors the library as **320 kbps MP3**, keeping the folder layout, tags and
cover art. Your library is only read, never changed.

- **Where:** a plugged-in USB drive is the default (`<drive>/Music`). With no
  drive it offers `~/Music/Library Download MP3`, and "look again" once you
  plug one in. `musesh mp3 ~/Some/Folder` skips the question.
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
