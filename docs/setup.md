# Setup

## What you need

- **macOS** with [Homebrew](https://brew.sh). (The scripts are plain Python and
  would mostly work elsewhere, but paths, `caffeinate` and USB detection assume
  a Mac.)
- An **active Apple Music subscription**.
- **Python 3.10+**, **pipx** and **ffmpeg**.
- About as much free disk space as your library: roughly **8 MB per song** at
  256 kbps AAC. `musesh` warns before starting if a folder looks too small.

## 1. Install

```sh
brew install pipx ffmpeg
pipx install gamdl
git clone https://github.com/Comiclyy/musesh.git ~/code/musesh
ln -s ~/code/musesh/musesh ~/bin/musesh
```

Any folder on your `PATH` works instead of `~/bin`. Check it:

```sh
musesh help
```

musesh runs its helper scripts with the Python inside gamdl's pipx
environment (`~/.local/pipx/venvs/gamdl`), so it can use gamdl, `httpx` and
`mutagen` without installing anything else.

## 2. Export your library

In the Music app: **File > Library > Export Library...** and save it
somewhere musesh looks: `~/Documents`, `~/Desktop`, `~/Downloads` or `~/Music`.
Any filename containing "library" is offered in the menus, newest first.

Export again whenever you want `musesh align` to see newly added songs.

## 3. Export your Apple Music cookies

musesh logs in to Apple Music the way your browser does, using its cookies:

1. Open [music.apple.com](https://music.apple.com) and sign in.
2. Export the cookies for that site in **Netscape format**, for example with
   the *Get cookies.txt LOCALLY* browser extension.
3. Save the file anywhere; `~/Downloads` is fine. musesh offers files named
   like `*cookies*.txt` in its menus.

Cookies expire after a while. When they do, musesh stops with a message
saying so; export them again and run the same command.

> [!NOTE]
> The cookies file logs in as you. Keep it private, and don't commit it
> anywhere.

## 4. First download

```sh
musesh
```

It asks four things (Enter takes the default each time):

1. **Which library export** to use.
2. **Which cookies file.**
3. **Where the library should go.** Default `~/Music/Library Download`; plugged-in
   drives are offered too, with their free space.
4. **How many songs this run.** Default 200. Run `musesh continue` for the
   next batch, or `musesh continue all` to do the rest in one go.

Your choices are saved, so from then on `musesh continue` needs no answers.

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
sudo -b sh -c 'pmset -a disablesleep 1; sleep 60; while pgrep -f "library_dl.py|albums.py" >/dev/null; do sleep 30; done; pmset -a disablesleep 0'
```

If you need sleep back early: `sudo pmset -a disablesleep 0`.
