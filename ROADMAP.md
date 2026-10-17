# musesh roadmap

This file preserves future ideas and working context across chats. **The items
below are deferred proposals unless explicitly marked implemented, not approved
implementation plans. Each deferred feature still needs its own detailed plan
before implementation begins.** Recording an
idea here does not authorize building it or running it against the player.

## Working context

- Music is downloaded into `~/Music/musesh/Incoming` and converted into the local
  MP3 collection at `~/Music/musesh/Library`.
- The player is a Sony Walkman NW-S780 series. Its usual Mac mount is
  `/Volumes/WALKMAN`, with music under `MUSIC`.
- The Mac's USB connection/cable is unreliable. A Windows preparation and
  transfer workflow exists, though the Windows launcher still needs a real
  Windows/player smoke test.
- `musesh push` now previews every proposed addition, grouped by artist and
  album with storage totals, and asks for confirmation before copying. It
  remembers handled songs so deleting them from the Walkman does not restore
  them on the next push. Its first-run window is seven days; it cannot infer
  deletions made before tracking began.
- Once a push batch is confirmed, it watches for disconnects, logs connection
  status, and automatically resumes that same batch when the same player
  reconnects. Copies are verified and unfinished songs remain pending.
- Direct push history is stored in `~/Music/musesh/.push/`. The Windows handoff
  uses separate history under `~/Music/musesh/.transfer/` and the Windows share.
- Swinsian has **Main Collection** and **Walkman Collection** Smart Playlists
  that exclude/include `/Volumes/WALKMAN/`. The player's `MUSIC` folder is
  watched in **Just Add Tracks** mode, without copying its songs onto the Mac.
- Deleting player tracks through Swinsian's **Remove and Move To Trash** moves
  them into the Walkman's hidden Trash. They continue consuming player storage
  until those trashed files are permanently deleted. macOS blocked terminal
  access to this protected folder during troubleshooting; Finder could access
  it. A scan must not silently interpret access-denied folders as empty.
- Prefer background work; the user does not want app windows repeatedly opened
  or brought forward when that can be avoided.

## Deferred features

### Storage usage rankings

Show what occupies the most player storage, with artist grouping and sorting,
song counts, and useful album-level breakdowns. A top-20 artist table was useful
in the current workflow. A detailed plan should settle tag-based artist grouping
versus folder grouping, handling compilations, sorting options, and how this
fits with the existing `library` and `formats` commands.

### Walkman hidden Trash cleanup

Provide an easy way to inspect and clear **only the connected player's hidden
Trash**, reclaiming space after Swinsian deletions. Preview the affected files
and reclaimable space, distinguish player Trash from the Mac's Trash, and
confirm before permanent deletion. The plan must address macOS access
restrictions, correct player identification, disconnects, and verifying the
space reclaimed. Do not assume a global **Empty Trash** action is appropriate.

### Deeper storage analysis

Explain **why** storage is being used, beyond ranking song sizes. The user
specifically wants findings at the level of “downloaded or embedded lyrics for
these songs occupy this much space.” Measure the contribution rather than
assuming lyrics are significant.

Potential categories to evaluate in the detailed plan:

- Embedded lyrics and other tags versus separate `.lrc` or text files.
- Embedded artwork, oversized artwork, and separate cover images.
- Audio data, bitrate/format choices, and possible space savings with tradeoffs.
- Duplicate audio, multiple editions, and redundant copies.
- Hidden Trash, unfinished transfers, and non-music files or bundled installers.
- Filesystem allocation overhead and any storage that could not be inspected.

Present measured findings and understandable potential savings. Analysis and
cleanup should have clearly defined boundaries; no automatic tag stripping,
re-encoding, or deletion is specified by this roadmap.

### Safe player eject — implemented on macOS

`musesh eject` now detects the configured player, shares the push lock to refuse
ejection during active or reconnecting pushes, and requests normal macOS
ejection. It reports “safe to unplug” only after successful ejection and checking
the mount is gone. Busy volumes are never forcibly unmounted. It does not empty
Trash. Windows support and integration into the transfer workflow remain future
planning topics. Finish other copy operations before ejecting.

### General revitalization and simplification

Review the overall tool: everyday tasks currently require too many separate
commands. Plan simpler workflows for selecting/downloading music, preparing
MP3s, reviewing additions, transferring, checking storage, and safely ejecting.
Keep meaningful previews and confirmation while reducing repeated setup and
unnecessary command switching. Existing deletion protection and reconnect
behavior should be considered when planning compatibility.

### Main-artist grouping on the player

Optionally group collaborations under their main artist in the Walkman's artist
menu. For example, a track credited to `fakemink & ok` could appear under
`fakemink` on the player. Preserve original Mac-library tags and full collaborator
credits. Plan how Album Artist is used, missing tags, true Various Artists
compilations, explicit exceptions, existing player files, and transfer hashes
and history. Do not blindly split artist names on commas or ampersands.
This has been investigated but is not implemented.

### Project website

Create a website for musesh. This is a deferred idea, not authorization to build
or publish yet. Plan the audience, content, design, documentation/download links,
hosting, maintenance, and publishing workflow before implementation. No stack,
domain, or hosting provider has been chosen.

## Before starting any of these

When returning to this roadmap, **remind the user that we should make a more
detailed plan first**. Confirm priorities and write a plan for each feature (or
an explicitly agreed group of features), covering:

- Intended behavior, scope, and a simple command/user experience.
- Integration with current commands and transfer history.
- Player identification, disconnect/reconnect behavior, and failure handling.
- Storage measurement accuracy and any destructive-operation confirmations.
- Tests, acceptance criteria, and compatibility or migration needs.

No priority order, delivery dates, or final command names beyond the implemented
`musesh eject` have been agreed.
