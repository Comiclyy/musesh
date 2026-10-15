# Setup

## What you need

- **macOS** with [Homebrew](https://brew.sh). (The scripts are plain Python and
  would mostly work elsewhere, but paths, `caffeinate` and USB detection assume
  a Mac.)
- **Python 3.10+** and **ffmpeg** (including ffprobe).
- **pipx + gamdl** for Apple Music downloads and the `mp3`, `prune`, `formats`
  and `library` helpers.
- **yt-dlp** for SoundCloud downloads.
- An **active Apple Music subscription** and Apple Music cookies for Apple
  Music downloads. Public SoundCloud downloads need neither.
- About as much free disk space as your library: roughly **8 MB per song** at
  256 kbps AAC. `musesh` warns before starting if a folder looks too small.

## 1. Install

```sh
brew install pipx ffmpeg yt-dlp
pipx install gamdl
git clone https://github.com/Comiclyy/musesh.git ~/code/musesh
ln -s ~/code/musesh/musesh ~/bin/musesh
```

Any folder on your `PATH` works instead of `~/bin`. Check it:

```sh
musesh help
```

musesh runs the Apple Music and library-management helpers with the Python
inside gamdl's pipx environment (`~/.local/pipx/venvs/gamdl`), so they can use
gamdl, `httpx` and `mutagen`. The SoundCloud helper uses standard-library
Python and a separate yt-dlp executable. It prefers `/opt/homebrew/bin/yt-dlp`
or `/usr/local/bin/yt-dlp` over older user-site copies on PATH.

## 2. Download from a link

Replace the example URLs below with your share links. Keep them quoted,
especially when they contain `?` or `&`.

### Apple Music

An export of your library isn't needed for direct song or album links.
First [export your Apple Music cookies](#apple-music-cookies), then run:

```sh
musesh am "https://music.apple.com/ca/song/song-title/123456789"
musesh apple "https://music.apple.com/ca/album/album-title/123456789"
```

`apple` and `am` are aliases. Omit the URL to be prompted. An album link with
`?i=SONG_ID` selects only that song; without it, musesh offers the whole album.
Use `--review-only` to inspect a link without downloading, or `-y` to accept
an album without the confirmation prompt.

### SoundCloud

```sh
musesh sc "https://soundcloud.com/artist/track"
musesh soundcloud "https://soundcloud.com/artist/sets/album"
```

`soundcloud` and `sc` are aliases. They accept public tracks and albums/sets,
and prompt for a link when one is omitted. Public downloads need no login;
you can skip all Apple Music setup for SoundCloud-only downloading. Keep
gamdl installed if you want to use `musesh mp3` or the library-report helpers.

For account access, sign into SoundCloud in your browser, then choose one:

```sh
musesh sc "SOUNDCLOUD_URL" --cookies-from-browser vivaldi
musesh sc "SOUNDCLOUD_URL" --cookies ~/Downloads/soundcloud.com_cookies.txt
```

The file option needs a **Netscape-format cookie export from soundcloud.com**.
Use it if browser extraction fails with a Keychain/decryption error. Keep
Apple Music and SoundCloud exports separate. These SoundCloud login options
apply to the current command only; they aren't saved in settings.

Only full accessible audio is downloaded. A Go+ badge or full duration on a
track page doesn't prove it can play fully: check playback in your signed-in
browser. Cookie login does not add subscription access, and musesh skips
preview-only results.

### Files and MP3 copies

Both services download into your saved Incoming folder, default
`~/Music/musesh/Incoming`, using the existing artist/album organization.
SoundCloud keeps the best available native codec; Apple Music uses the
existing gamdl settings. Make the MP3 copy afterwards:

```sh
musesh mp3
```

This offers your local Library or a USB drive, keeps tags and artwork, and
leaves the Incoming sources in place. Existing MP3s are copied without another
lossy encode. Repeat a direct-link command to resume it; `musesh continue`
is for Library.xml batches.

## Apple Music cookies

musesh logs in to Apple Music the way your browser does, using its cookies:

1. Open [music.apple.com](https://music.apple.com) and sign in.
2. Export the cookies for that site in **Netscape format**, for example with
   the *Get cookies.txt LOCALLY* browser extension.
3. Save the file as `~/Downloads/music.apple.com_cookies.txt`.

Direct Apple Music links use your saved cookie path, then look for the newest
`*apple*cookie*.txt` file in Downloads when no saved file exists. To choose a
different export for one command, use `musesh am "URL" --cookies /path/to/export.txt`.
The full-library setup offers cookie files in its menus and saves your choice.

Cookies expire after a while. When they do, musesh stops with a message
saying so; export them again and run the same command.

> [!NOTE]
> The cookies file logs in as you. Keep it private, and don't commit it
> anywhere.

## 3. Download a full Apple Music library

This path needs both the Apple Music cookies above and a **Library.xml**.
In the Music app, choose **File > Library > Export Library...** and save it
in `~/Documents`, `~/Desktop`, `~/Downloads` or `~/Music`. Filenames containing
"library" are offered in the menus, newest first. Then run:

```sh
musesh
```

It asks four things (Enter takes the default each time):

1. **Which library export** to use.
2. **Which cookies file.**
3. **Where downloads should go.** Default `~/Music/musesh/Incoming`; plugged-in
   drives are offered too, with their free space. Run `musesh mp3` afterwards
   to convert them into your collection in `~/Music/musesh/Library`.
4. **How many songs this run.** Default 200. Run `musesh continue` for the
   next batch, or `musesh continue all` to do the rest in one go.

Your choices are saved, so from then on `musesh continue` needs no answers.
Export your library again whenever you want `musesh align` to see newly
added songs. Both direct-link commands reuse the saved Incoming folder.

## Keeping the Mac awake

A full library takes a while. Keep the Mac from sleeping while the lid is
open:

```sh
caffeinate -ims musesh continue
```

Closing the lid sleeps a MacBook regardless of `caffeinate`. To let a
download finish with the lid shut (plugged in, on a hard surface), turn sleep
off until musesh is done; it turns itself back on:

```sh
sudo -b sh -c 'pmset -a disablesleep 1; sleep 60; while pgrep -f "library_dl.py|albums.py|apple_music.py|soundcloud.py" >/dev/null; do sleep 30; done; pmset -a disablesleep 0'
```

If you need sleep back early: `sudo pmset -a disablesleep 0`.
