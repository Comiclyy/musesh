import contextlib
import fcntl
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

import eject


class EjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name)
        self.player = Mock(name='player')
        self.player.name = 'WALKMAN'
        self.player.is_mount.return_value = False
        self.output = io.StringIO()
        self.enterContext(contextlib.redirect_stdout(self.output))
        self.find = self.enterContext(patch.object(eject, 'find_player', return_value=(self.player, 'uuid')))
        self.enterContext(patch.object(eject, 'volume_info', return_value={'VolumeUUID': 'uuid'}))
        self.run = self.enterContext(patch.object(eject.subprocess, 'run',
                                  return_value=Mock(returncode=0, stderr='', stdout='ejected')))

    def test_success_only_after_verified_unmount(self):
        self.assertEqual(eject.eject(self.state), 0)
        self.run.assert_called_once_with(['diskutil', 'eject', str(self.player)],
                                        capture_output=True, text=True, timeout=60)
        self.assertIn('Safe to unplug', self.output.getvalue())

    def test_busy_failure_does_not_report_safe(self):
        self.run.return_value = Mock(returncode=1, stderr='Resource busy', stdout='')
        with self.assertRaisesRegex(ValueError, 'Close files or apps'):
            eject.eject(self.state)
        self.assertNotIn('Safe to unplug', self.output.getvalue())

    def test_still_mounted_does_not_report_safe(self):
        self.player.is_mount.return_value = True
        with self.assertRaisesRegex(ValueError, 'still mounted'):
            eject.eject(self.state)
        self.assertNotIn('Safe to unplug', self.output.getvalue())

    def test_active_push_refused_before_disk_operations(self):
        with (self.state / 'lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(ValueError, 'push is still running'):
                eject.eject(self.state)
        self.find.assert_not_called()
        self.run.assert_not_called()

    def test_changed_identity_refused(self):
        with patch.object(eject, 'volume_info', return_value={'VolumeUUID': 'other'}):
            with self.assertRaisesRegex(ValueError, 'player changed'):
                eject.eject(self.state)
        self.run.assert_not_called()

    def test_missing_player_refused(self):
        self.find.side_effect = ValueError('Connect the configured Walkman')
        with self.assertRaisesRegex(ValueError, 'Connect'):
            eject.eject(self.state)
        self.run.assert_not_called()

    def test_timeout_returns_failure(self):
        with patch.object(eject, 'eject', side_effect=subprocess.TimeoutExpired('diskutil', 60)):
            self.assertEqual(eject.main([]), 1)
        self.assertNotIn('Safe to unplug', self.output.getvalue())
