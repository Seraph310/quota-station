"""No real process, registry, or installation is inspected by these tests."""
import os
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch

from providers import magpie_discovery as discovery


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        filename = 'magpie.exe' if sys.platform == 'win32' else 'magpie'
        self.old = self.root / 'old' / filename
        self.current = self.root / 'custom install' / filename
        for path in (self.old, self.current):
            path.parent.mkdir()
            path.touch()
            path.chmod(0o755)
        for target, value in (('_running_paths', []), ('_registry_paths', []), ('_usual_paths', [])):
            mocked = patch.object(discovery, target, return_value=value)
            mocked.start()
            self.addCleanup(mocked.stop)
        environment = patch.dict(os.environ, {'QUOTA_MAGPIE_EXECUTABLE': ''})
        environment.start()
        self.addCleanup(environment.stop)
        path = patch.object(discovery.shutil, 'which', return_value=None)
        path.start()
        self.addCleanup(path.stop)

    def test_manual_sync_follows_running_install_in_custom_directory(self):
        with patch.object(discovery, '_running_paths', return_value=[str(self.current)]):
            found = discovery.discover_executable(str(self.old), rediscover=True)
            self.assertEqual(Path(found), self.current)

    def test_background_refresh_reuses_saved_path_without_process_scan(self):
        with patch.object(discovery, '_running_paths') as processes:
            self.assertEqual(Path(discovery.discover_executable(str(self.current))), self.current)
            processes.assert_not_called()

    def test_removed_saved_path_falls_back_to_registered_install(self):
        with patch.object(discovery, '_registry_paths', return_value=[str(self.current)]):
            found = discovery.discover_executable(str(self.root / 'missing/magpie.exe'))
            self.assertEqual(Path(found), self.current)

    def test_standard_install_detected_without_path_or_running_app(self):
        with patch.object(discovery, '_usual_paths', return_value=[self.current]):
            self.assertEqual(Path(discovery.discover_executable()), self.current)

    def test_path_location_is_validated_and_scripts_are_not_executed(self):
        with patch.object(discovery.shutil, 'which', return_value=str(self.current)):
            self.assertEqual(Path(discovery.discover_executable()), self.current)
        script = self.root / 'magpie.cmd'
        script.touch()
        with patch.object(discovery.shutil, 'which', return_value=str(script)):
            self.assertIsNone(discovery.discover_executable())

    def test_invalid_override_does_not_silently_select_another_install(self):
        with patch.dict(os.environ, {'QUOTA_MAGPIE_EXECUTABLE': str(self.root / 'absent.exe')}):
            with self.assertRaises(RuntimeError):
                discovery.discover_executable()

    def test_absent_install_is_not_faked(self):
        self.assertIsNone(discovery.discover_executable())
