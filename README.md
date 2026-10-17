<div align="center">

<img src="docs/images/logo.svg" width="80" alt="musesh logo" />

# musesh

**Your music library, as files you own.**<br/>
Download from Apple Music and SoundCloud. Keep native audio or make an MP3 copy.

[![macOS](https://img.shields.io/badge/macOS-16171d?style=flat-square&logo=apple&logoColor=white)](docs/setup.md)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-d783e8?style=flat-square&logo=python&logoColor=white)](docs/setup.md)
[![gamdl](https://img.shields.io/badge/Apple%20Music-gamdl-7c5cff?style=flat-square)](https://github.com/glomatico/gamdl)
[![yt-dlp](https://img.shields.io/badge/SoundCloud-yt--dlp-ff5500?style=flat-square)](https://github.com/yt-dlp/yt-dlp)

[Setup](docs/setup.md) · [Commands](docs/commands.md) · [How it works](docs/how-it-works.md) · [Troubleshooting](docs/troubleshooting.md)

<br/>

<img src="docs/images/help.svg" width="860" alt="musesh help: all commands, including SoundCloud and Apple Music links" />

</div>

## Install

```sh
brew install pipx ffmpeg yt-dlp
pipx install gamdl
git clone https://github.com/Comiclyy/musesh.git ~/code/musesh
mkdir -p ~/bin
ln -s ~/code/musesh/musesh ~/bin/musesh
```

Keep `~/bin` on your PATH. See [Setup](docs/setup.md) for cookies and library exports.

## Use

```sh
musesh am "APPLE_MUSIC_URL"  # song or album; alias: apple
musesh sc "SOUNDCLOUD_URL"   # track or album/set; alias: soundcloud
musesh                     # download a Library.xml export
musesh continue            # next library batch
musesh align               # fetch newly added Apple Music songs
musesh mp3                 # MP3 copy to Library or USB
musesh push                # preview and copy new Library MP3s to your Walkman
musesh eject               # safely eject your Walkman when finished (macOS)
musesh prepare             # new songs ready for a Windows player transfer
```

Replace the URL placeholders with share links, or omit them to be prompted.
Apple Music needs a subscription and [cookies](docs/setup.md#apple-music-cookies).
Public SoundCloud links need no login; optional cookies use your account's access.
Preview-only tracks are skipped.

Downloads land in `~/Music/musesh/Incoming`, organized by artist and album.
Finished tracks are remembered. `musesh mp3` keeps tags, artwork and native sources.

To send finished Library MP3s directly to a connected Walkman, run **`musesh push`**.
It lists every proposed song by artist and album, shows sizes and remaining space,
and asks before copying. The first run considers downloads from the last seven
days; older missing music stays alone. Successful copies and songs already on the
player are remembered, so deleting them later does not make push restore them.
`musesh push --dry-run` previews without copying or changing transfer history.
If the USB connection drops during a confirmed push, it logs the disconnect,
watches for the same Walkman, and continues automatically when reconnected.
Press Ctrl-C to stop; the next run remembers completed work.
When finished, run `musesh eject` on macOS and wait for “Safe to unplug”.
For separate Mac/player views and deletions, see [Swinsian setup](docs/swinsian.md).

## Transfer through Windows

Prepare on your Mac; connect the MP3 player only to Windows. After a
[one-time shared-folder setup](docs/windows-transfer.md), use:

```sh
musesh prepare                         # new songs not yet uploaded
musesh prepare 2026-10-16              # a specific day
musesh prepare 2026-10-01..2026-10-16  # an inclusive date range
```

On Windows, run `musesh-transfer.cmd` from the shared folder. It finds your
configured player, copies and verifies queued music, and records successes.
Reruns keep completed work and retry failed songs. Windows needs no Python or
audio conversion tools, and the Mac can be asleep once preparation finishes.

## Manage your collection

| Command | Does |
| --- | --- |
| `musesh albums [list]` | Download Apple Music albums from a text list |
| `musesh library` | Browse artists, albums and file sizes |
| `musesh formats` | Inspect codecs and audio quality |
| `musesh watch` / `status` | Follow downloads and check progress |
| `musesh clean` | Remove empty folders and orphaned lyrics |
| `musesh prune` | Verify MP3 copies, then offer to delete originals |

<img src="docs/images/formats.svg" width="860" alt="musesh formats: file types and audio quality" />

Run `musesh help` for all commands, or read the [command reference](docs/commands.md).
