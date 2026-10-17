# musesh documentation

musesh downloads an Apple Music library or individual Apple Music and SoundCloud
links into one collection. It keeps native audio, reports file formats and
quality, and makes an MP3 copy for your library or a USB drive.

It is a small set of Python scripts driven by one command, `musesh`.
Apple Music downloading uses [gamdl](https://github.com/glomatico/gamdl),
SoundCloud uses [yt-dlp](https://github.com/yt-dlp/yt-dlp), and MP3 encoding
uses [ffmpeg](https://ffmpeg.org).

| Page | Read it when... |
| --- | --- |
| [Setup](setup.md) | You're installing it, or your cookies stopped working. |
| [Commands](commands.md) | You want every command, argument and prompt in one place. |
| [Windows transfer](windows-transfer.md) | You want one-command transfers from Windows. |
| [Swinsian](swinsian.md) | You want separate Mac/player views and file deletion. |
| [Roadmap](../ROADMAP.md) | You want deferred ideas and implementation status. |
| [How it works](how-it-works.md) | You want the moving parts: matching, state files, safety rules. |
| [Troubleshooting](troubleshooting.md) | Something failed, stalled, or isn't where you expected. |

## At a glance

```
  Music app                        music.apple.com
      |                                   |
      | File > Export Library             | cookies.txt
      v                                   v
  Library.xml ---> musesh ---> match to catalog IDs ---> gamdl ---> Artist/Album/*.m4a
                     |          (your cloud library,
                     |           then search)
                     |
                     +--> albums list  -----------------> whole albums
                     +--> apple / am URL ----------------> Apple Music song or album
                     +--> soundcloud / sc URL --> yt-dlp -> SoundCloud track or set
                     +--> align        -----------------> only new songs
                     +--> formats      -----------------> what's on disk, and how good
                     +--> mp3 / prune  -----------------> 320 kbps MP3 copy (USB or folder)
```

## Start with a link

```sh
musesh am "APPLE_MUSIC_URL"
musesh sc "SOUNDCLOUD_URL"
musesh mp3
```

Replace the placeholders with share links. Apple Music needs a subscription
and Apple Music cookies; it doesn't need a Library.xml for direct links.
Public SoundCloud downloads need no login. For account access, use
`--cookies-from-browser vivaldi` or `--cookies PATH`; previews stay skipped.
See [Setup](setup.md) for installation and cookie exports, and
[Commands](commands.md#download) for album prompts, retries and flags.

## Send new music to the player

After converting downloads into the local Library:

```sh
musesh push      # review recent additions, confirm once, copy and verify
musesh eject     # safely remove the player on macOS
```

Push logs song-by-song progress and automatically resumes the confirmed batch
when the same player reconnects. Completed transfers remain remembered after
player deletions. For the first-run selection window and other details, see
[the command reference](commands.md#musesh-push). For an unreliable Mac USB
connection, use the [Windows workflow](windows-transfer.md).

## Where things live

Everything musesh owns is in one folder:

```text
~/Music/musesh/
  Library/          your collection (MP3s once converted)
  Incoming/         new downloads, waiting for 'musesh mp3'
  albums.txt        your album list
  unmatched.csv     tracks not found on Apple Music
```

- `~/.config/musesh/settings.json`: your saved choices (export, cookies, folders, batch size).
- A hidden `.musesh/` folder inside `Incoming/` and `Library/` holds progress, catalog
  matches and what's been seen. Don't delete it.

Upgrading from the old layout (`~/Music/Library Download` and `Library Download MP3`)?
Run `musesh migrate` once; it moves everything over.
