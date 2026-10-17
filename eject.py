"""Safely eject the configured Walkman on macOS."""

import argparse
import fcntl
import subprocess
import sys

from push import STATE, find_player, volume_info
from ui import note, ok, warn


def eject(state_dir=STATE):
    state_dir.mkdir(parents=True, exist_ok=True)
    # Share push's lock, including while it waits for a disconnected player.
    with (state_dir / 'lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('A push is still running. Stop it before ejecting the Walkman.') from None
        player, identity = find_player(state_dir)
        if volume_info(player)['VolumeUUID'] != identity:
            raise ValueError('The connected player changed. Try ejecting again.')
        note(f'Ejecting {player.name}…')
        # Normal diskutil eject flushes pending writes and refuses busy volumes.
        # Never use a forced unmount or kill apps holding the player open.
        result = subprocess.run(['diskutil', 'eject', str(player)],
                                capture_output=True, text=True, timeout=60)
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()
            raise ValueError('Could not eject the Walkman. Close files or apps using it and try again.'
                             + (f'\n{detail}' if detail else ''))
        if player.is_mount():
            raise ValueError('The player is still mounted. Ejection could not be verified; do not unplug yet.')
        ok('Walkman ejected. Safe to unplug.')
    return 0


def main(argv=None):
    argparse.ArgumentParser(prog='musesh eject', description=__doc__).parse_args(argv)
    try:
        return eject()
    except subprocess.TimeoutExpired:
        warn('Ejection timed out; safe removal was not confirmed. Check the player before unplugging.')
        return 1
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        warn(str(exc))
        return 1
    except KeyboardInterrupt:
        warn('Ejection interrupted; safe removal was not confirmed.')
        return 130


if __name__ == '__main__':
    sys.exit(main())
