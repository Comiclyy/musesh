# Browse the connected Walkman in Swinsian

Swinsian can play and edit files directly on the mounted player. This setup uses
one Swinsian library with separate Smart Playlists for the Mac and player.
The main Library view still contains both copies; use the Smart Playlists to
avoid seeing them together. Player tracks are available while it is connected.

## Import and watch the player

1. For the initial import, disable copying newly added files into Swinsian's
   library folder under **Settings > Library**.
2. Use **File > Add Files to Library** to import `/Volumes/WALKMAN/MUSIC`.
   Watching a folder alone does not import all existing tracks.
3. Add that same folder under **Settings > Watched Folders**, selecting
   **Just Add Tracks**. Enable removing tracks from the library when files
   disappear and rescanning tags when files change.
4. After an external transfer, use **Rescan** if new tracks have not appeared.

Substitute your player's actual mount and music directory if different.

## Separate collection views

Create these Smart Playlists using the player's volume path:

- **Walkman Collection:** match **Any** rule, with
  **File Path contains `/Volumes/WALKMAN/`**.
- **Main Collection:** match **None** of the rules, with
  **File Path contains `/Volumes/WALKMAN/`**.

These views update from Swinsian's indexed tracks. They do not make additional
copies, and removing a song from a playlist alone does not delete its file.

## Delete songs from the player

In a Smart Playlist, Swinsian's ordinary Remove Tracks action may be disabled.
Use **Cmd+Option+Shift+Delete** to invoke library removal, then choose
**Remove and Move To Trash** to remove the actual player file.
**Remove From Library** alone only removes the database entry.

The current user's Mac also has a Swinsian-only Karabiner mapping from
**Cmd+Delete** to that longer shortcut. This is a local configuration, not a
shortcut installed by musesh. Other Macs need their own configuration.

Trashed player files still consume player storage until permanently deleted.
Inspect and clear only the player's Trash; Finder's global Empty Trash can
also affect other disks. A musesh Trash-cleanup tool remains a roadmap item.
Terminal access to the protected Trash can be denied even when Finder can
inspect it. An access error does not mean the Trash is empty.

## Missing songs and artist entries

Only watched/imported folders appear. Sony sample or received tracks can live
in `/Volumes/WALKMAN/RECEIVED`, outside `MUSIC`. Import and watch that directory
as well if you want those tracks in Swinsian. The volume-path Smart Playlist
rules above include them once imported.

Collaboration tags such as Artist `fakemink & ok` can appear as separate artist
entries on the player even when Album Artist is `fakemink`. Automatic main-artist
tagging of player copies is proposed, not implemented; current transfers retain
the source tags.

## Finish safely

Stop playback from the player, finish copy operations, then run `musesh eject`
on the Mac. If the player is busy, close apps/files using it and retry. Windows
transfers use Windows' normal safe-removal procedure.
