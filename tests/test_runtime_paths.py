"""Packaged paths and platform-specific source discovery, without live profiles."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import runtime_paths as paths
from providers import codex_provider, magpie_discovery


class RuntimePathTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        environment = patch.dict(os.environ, {'QUOTA_STATION_DATA_DIR': '', 'QUOTA_CODEX_EXECUTABLE': '',
                                              'LOCALAPPDATA': str(self.root / 'local')})
        environment.start()
        self.addCleanup(environment.stop)

    def test_source_checkout_keeps_existing_state_location(self):
        with patch.object(paths.sys, 'frozen', False, create=True):
            self.assertEqual(paths.data_root(), paths.resource_root())

    def test_frozen_windows_state_is_outside_the_program_folder(self):
        with patch.object(paths.sys, 'frozen', True, create=True), patch.object(paths.sys, 'platform', 'win32'):
            self.assertEqual(paths.data_root(), self.root / 'local/QuotaStation')
            self.assertNotEqual(paths.data_root(), paths.resource_root())

    def test_frozen_mac_uses_application_support_and_only_supported_native_sources(self):
        with patch.object(paths.sys, 'frozen', True, create=True), patch.object(paths.sys, 'platform', 'darwin'), \
             patch.object(paths.Path, 'home', return_value=self.root):
            self.assertEqual(paths.data_root(), self.root / 'Library/Application Support/QuotaStation')
            self.assertEqual(paths.native_source_keys(), [0])
        with patch.object(paths.sys, 'platform', 'win32'):
            self.assertEqual(paths.native_source_keys(), [0, 1, 2])

    def test_explicit_data_directory_must_be_absolute(self):
        with patch.dict(os.environ, {'QUOTA_STATION_DATA_DIR': str(self.root / 'custom')}):
            self.assertEqual(paths.data_root(), self.root / 'custom')
        with patch.dict(os.environ, {'QUOTA_STATION_DATA_DIR': 'relative'}), self.assertRaises(ValueError):
            paths.data_root()

    def test_finder_environment_can_find_homebrew_cli_without_replacing_path(self):
        with patch.object(paths.sys, 'platform', 'darwin'), patch.dict(os.environ, {'PATH': '/usr/bin'}):
            value = paths.cli_environment()['PATH'].split(os.pathsep)
            self.assertEqual(value[0], '/usr/bin')
            self.assertIn('/opt/homebrew/bin', value)
            self.assertIn('/usr/local/bin', value)

    def test_codex_and_magpie_accept_executable_mac_cli_without_exe_suffix(self):
        codex = self.root / 'codex'
        magpie = self.root / 'magpie'
        for file in (codex, magpie):
            file.touch()
            file.chmod(0o755)
        with patch.object(paths.sys, 'platform', 'darwin'), \
             patch.dict(os.environ, {'QUOTA_CODEX_EXECUTABLE': str(codex)}):
            self.assertEqual(codex_provider._find_executable(), codex)
            self.assertEqual(Path(magpie_discovery._executable(magpie)), magpie)
            self.assertIsNone(magpie_discovery._executable(codex))


if __name__ == '__main__':
    unittest.main()
