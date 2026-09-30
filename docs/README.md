# musesh documentation

musesh turns an Apple Music library into ordinary files on disk: it downloads
the songs, keeps the folder in step with new additions, reports on file
formats and quality, and makes an MP3 copy for places that only play MP3.

It is a small set of Python scripts driven by one command, `musesh`. The
actual downloading is done by [gamdl](https://github.com/glomatico/gamdl);
MP3 encoding by [ffmpeg](https://ffmpeg.org).

| Page | Read it when... |
| --- | --- |
| [Setup](setup.md) | You're installing it, or your cookies stopped working. |
| [Commands](commands.md) | You want every command, argument and prompt in one place. |
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
                     +--> align        -----------------> only new songs
                     +--> formats      -----------------> what's on disk, and how good
                     +--> mp3 / prune  -----------------> 320 kbps MP3 copy (USB or folder)
```

Everything a command needs to remember lives in two places:

- `~/.config/musesh/last-run.json`: your last choices (export, cookies, folders, batch size).
- `<library>/.library-dl/`: download progress, catalog matches, what's been seen.
