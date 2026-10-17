# Transfer to your MP3 player through Windows

The Mac downloads and converts music. Windows stores prepared batches locally
and copies them to the player with one command, without prompts. This supports
players that appear as a drive letter; MTP-only devices are not supported.

The Mac preparation workflow has automated test coverage. The Windows launcher
still needs an end-to-end smoke test on a real Windows computer with a player.

## One-time setup

1. On Windows, create a local folder such as `C:\MuseshTransfer`. Share it on
   your home network as `MuseshTransfer`, giving your account read/write access.
   Use a short local path; the prepared music must live on the Windows disk.
2. On your Mac, use Finder's **Go > Connect to Server** to connect to
   `smb://WINDOWS-PC/MuseshTransfer`, replacing `WINDOWS-PC` with the Windows
   computer's name or local IP address. Sign in with the account allowed to
   access the share. The folder normally mounts at `/Volumes/MuseshTransfer`.
3. On the Mac, run:

   ```sh
   musesh transfer setup /Volumes/MuseshTransfer
   ```

   Substitute the actual mounted path if it differs. This installs both Windows
   launcher files into the share and records the initial collection dates.
4. Connect the player to Windows. Open a terminal in `C:\MuseshTransfer` and run:

   ```powershell
   .\musesh-transfer.cmd setup E:
   ```

   Replace `E:` with the player's drive letter. The destination defaults to
   `Music`. If your player needs another folder, supply it once:

   ```powershell
   .\musesh-transfer.cmd setup E: "Your Music Folder"
   ```

   Setup remembers the volume serial number and writes a small identity marker
   to the player. A different drive letter next time is fine. Use a separate
   handoff folder for a different player. No Python, ffmpeg, or administrator
   terminal is needed on Windows.

## Everyday use

After downloading your music, run on the Mac:

```sh
musesh prepare
```

This selects songs added **after setup** that Windows has not successfully
uploaded. It converts native audio to 320 kbps MP3, preserves existing MP3s,
tags and artwork, and sends ready files to the Windows disk. Unchanged native
files reuse their cached conversion on later preparations.

To include songs from a particular day or inclusive date range instead:

```sh
musesh prepare 2026-10-16
musesh prepare 2026-10-01..2026-10-16
```

Dates are when music was added locally, interpreted in the Mac's local timezone.
Conversion and tag edits preserve recorded dates. For files that existed before
date tracking, creation time is an approximation; modification time is used if
the filesystem has no creation timestamp. Explicit dates can select pre-setup
music too. Songs already acknowledged by this player stay skipped.

Wait for the publish summary. Then on Windows, connect the player and run:

```powershell
.\musesh-transfer.cmd
```

All ready batches are processed. The Mac and network connection are no longer
needed during this step. Only complete batches are visible to the launcher.
Files are copied temporarily, checked against their SHA-256 hashes, and renamed
into place. Existing identical songs are skipped; different music at the same
path is preserved and the new song gets a hash suffix. Unrelated files are never
removed. Use Windows' usual safe-eject procedure after the command finishes.

## Browse the connected player in Swinsian

See [Swinsian setup](swinsian.md) for separate Main Collection and Walkman
Collection views, automatic folder watching, deletion shortcuts, and hidden
Trash behavior. This works whenever the player is connected to the Mac.
On macOS, finish with `musesh eject`; on Windows use normal safe removal.

## Interrupted work and troubleshooting

- **Windows asleep or share unavailable:** locally prepared batches stay on the
  Mac. Reconnect the share in Finder and rerun `musesh prepare` to publish them.
- **Interrupted network copy:** an unfinished batch stays hidden from the
  Windows launcher. Rerun preparation; publishing retries the batch.
- **Player disconnected or full:** transfer exits with an error and keeps pending
  songs. Reconnect or free space and rerun the same Windows command.
- **Partial success:** each verified song immediately gets a receipt. Completed
  songs stay acknowledged; failed songs remain queued. Preparation alone does
  not mark anything uploaded.
- **No player or more than one matching player:** the launcher exits without
  choosing a destination. Connect only the configured player and retry.
- **Two native files map to the same MP3 path:** preparation reports the conflict.
  Rename one source file before trying again. Case and Windows filename
  sanitization collisions are given stable distinguishing suffixes.
- **Inspect errors:** Windows writes `transfer.log` inside the handoff folder and
  returns a nonzero exit code when something fails.

State lives in `~/Music/musesh/.transfer` on the Mac: settings, cached MP3
conversions, and pending local batches. Addition dates live in each source
folder's `.musesh/added.sqlite3`. Keep Windows' `receipts` and
`windows-settings.json`: they record the configured player and uploaded songs.
Acknowledged Windows batches are cleaned up on a later Mac preparation; the
original music and player files stay intact. The conversion cache can be deleted
to reclaim Mac disk space; native audio will be converted again when needed.
