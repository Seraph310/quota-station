"""Release trust boundaries, failed downloads and reversible install transactions."""
import hashlib
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import zipfile

import updater_core as update


def release_payload(version='0.4.1'):
    name = f'QuotaStation-{version}-windows-x64.zip'
    return {'tag_name': 'v' + version, 'draft': False, 'prerelease': False, 'body': 'Changes',
            'assets': [{'name': name, 'browser_download_url': f'https://github.com/{update.REPO}/releases/download/v{version}/{name}',
                        'size': 4, 'state': 'uploaded', 'digest': 'sha256:' + hashlib.sha256(b'test').hexdigest()}]}


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def release(self, payload=None):
        return update.parse_release(payload or release_payload(), '0.4.0', ('windows-x64', '.zip'))

    def test_version_comparison_and_exact_platform_asset(self):
        self.assertTrue(self.release(release_payload('0.10.0'))['newer'])
        self.assertFalse(self.release(release_payload('0.3.0'))['newer'])
        with self.assertRaises(update.UpdateError):
            update.parse_release(release_payload(), '0.4.0', ('macos-arm64', '.dmg'))

    def test_untrusted_or_incomplete_release_is_rejected(self):
        for field, value in [('tag_name', 'v0.4.1-beta'), ('draft', True), ('prerelease', True)]:
            item = release_payload()
            item[field] = value
            with self.subTest(field=field), self.assertRaises(update.UpdateError):
                self.release(item)
        for field, value in [('digest', None), ('size', -1), ('size', update.MAX_PACKAGE + 1),
                             ('browser_download_url', 'https://evil.example/app.zip')]:
            item = release_payload()
            item['assets'][0][field] = value
            with self.subTest(field=field), self.assertRaises(update.UpdateError):
                self.release(item)

    def test_download_checksum_size_and_cancellation_leave_no_partial_file(self):
        destination = self.root / 'app.zip'
        with patch.object(update, 'open_url', return_value=io.BytesIO(b'test')):
            update.download(self.release(), destination, Mock())
        self.assertEqual(destination.read_bytes(), b'test')
        destination.unlink()
        for data in (b'bad!', b'tes', b'test-extra'):
            with patch.object(update, 'open_url', return_value=io.BytesIO(data)), self.assertRaises(update.UpdateError):
                update.download(self.release(), destination, Mock())
            self.assertFalse(destination.exists())
            self.assertFalse(destination.with_suffix('.zip.part').exists())
        event = threading.Event()
        event.set()
        with patch.object(update, 'open_url', return_value=io.BytesIO(b'test')), self.assertRaises(update.Cancelled):
            update.download(self.release(), destination, Mock(), event)
        self.assertFalse(destination.with_suffix('.zip.part').exists())

    def test_redirect_cannot_escape_github_or_downgrade_to_http(self):
        for url in ('http://github.com/file', 'https://github.com.evil.example/file',
                    'https://user:password@github.com/file', 'https://example.com/file'):
            self.assertFalse(update._allowed_url(url))
        self.assertTrue(update._allowed_url('https://release-assets.githubusercontent.com/download?signature=x'))

    def test_zip_traversal_symlink_and_duplicate_paths_are_rejected(self):
        for name in ('QuotaStation/../../escape', '/escape', 'Other/app.exe',
                     'QuotaStation/C:evil', 'QuotaStation\\evil'):
            package = self.root / 'bad.zip'
            with zipfile.ZipFile(package, 'w') as archive:
                archive.writestr(name, 'bad')
            with self.subTest(name=name), self.assertRaises(update.UpdateError):
                update.unpack_zip(package, self.root / 'out')
            self.assertFalse((self.root / 'escape').exists())
        for symbolic in (False, True):
            package = self.root / 'bad.zip'
            with zipfile.ZipFile(package, 'w') as archive:
                entry = zipfile.ZipInfo('QuotaStation/link')
                if symbolic:
                    entry.external_attr = 0o120777 << 16
                archive.writestr(entry, '/outside')
                if not symbolic:
                    archive.writestr('quotastation/LINK', 'duplicate')
            with self.assertRaises(update.UpdateError):
                update.unpack_zip(package, self.root / 'out')

    def make_job(self):
        token = 'a' * 32
        data = self.root / 'data'
        directory = data / 'updates' / token
        target = self.root / 'apps/QuotaStation'
        stage = target.parent / f'.{target.name}.new-{token}'
        backup = target.parent / f'.{target.name}.old-{token}'
        for root, content in ((target, 'old'), (stage, 'new')):
            binary = update.executable(root)
            binary.parent.mkdir(parents=True)
            binary.write_text(content)
        settings = data / 'state/settings.json'
        settings.parent.mkdir(parents=True)
        settings.write_text('user settings')
        job = {'id': token, 'target': str(target), 'stage': str(stage), 'backup': str(backup),
               'data_dir': str(data), 'source_root': '', 'version': '0.4.1', 'parent_pid': 0,
               'fallback': [str(update.executable(target))], 'launch_args': [], 'ready_timeout': 1}
        update.write_json(directory / 'job.json', job)
        return directory, job, settings

    def test_successful_install_keeps_user_data_and_previous_program(self):
        directory, job, settings = self.make_job()
        process = Mock(pid=321, poll=Mock(return_value=None))
        def launch(*_args, **_kwargs):
            update.write_json(directory / 'ready.json', {'version': '0.4.1', 'pid': 321})
            return process
        with patch.object(update, 'spawn', side_effect=launch):
            self.assertEqual(update.apply_job(directory / 'job.json'), 0)
        self.assertEqual(update.executable(job['target']).read_text(), 'new')
        self.assertEqual(update.executable(job['backup']).read_text(), 'old')
        self.assertEqual(settings.read_text(), 'user settings')

    def test_failed_start_rolls_back_and_relaunches_original(self):
        directory, job, settings = self.make_job()
        process = Mock(pid=321, poll=Mock(return_value=1))
        with patch.object(update, 'spawn', return_value=process) as launch:
            self.assertEqual(update.apply_job(directory / 'job.json'), 1)
        self.assertEqual(update.executable(job['target']).read_text(), 'old')
        self.assertEqual(update.executable(job['stage']).read_text(), 'new')
        self.assertEqual(launch.call_args.args[0], job['fallback'])
        self.assertEqual(settings.read_text(), 'user settings')

    def test_failed_replacement_restores_backup(self):
        directory, job, _ = self.make_job()
        original = update.move_directory
        def move(source, destination):
            if Path(source) == Path(job['stage']):
                raise PermissionError('locked')
            original(source, destination)
        with patch.object(update, 'move_directory', side_effect=move), patch.object(update, 'spawn'):
            self.assertEqual(update.apply_job(directory / 'job.json'), 1)
        self.assertEqual(update.executable(job['target']).read_text(), 'old')

    def test_unresponsive_original_is_never_killed_or_replaced(self):
        directory, job, _ = self.make_job()
        with patch.object(update, 'process_alive', return_value=True), \
             patch.object(update.time, 'monotonic', side_effect=[0, 61]), patch.object(update, 'spawn') as launch:
            self.assertEqual(update.apply_job(directory / 'job.json'), 1)
        launch.assert_not_called()
        self.assertEqual(update.executable(job['target']).read_text(), 'old')

    def test_invalid_job_cannot_move_unrelated_directories(self):
        directory, job, _ = self.make_job()
        job['backup'] = str(self.root / 'unrelated')
        update.write_json(directory / 'job.json', job)
        with self.assertRaises(update.UpdateError):
            update.apply_job(directory / 'job.json')
        self.assertEqual(update.executable(job['target']).read_text(), 'old')

    def test_source_migration_copies_only_app_state_and_backs_up_previous_settings(self):
        directory, job, settings = self.make_job()
        source = self.root / 'checkout'
        (source / 'state').mkdir(parents=True)
        (source / 'state/settings.json').write_text('chosen sources')
        (source / 'state/runtime.json').write_text('old process')
        job['source_root'] = str(source)
        update.write_json(directory / 'job.json', job)
        update.migrate_source_state(directory / 'job.json')
        self.assertEqual(settings.read_text(), 'chosen sources')
        self.assertEqual((directory / 'previous-settings/state/settings.json').read_text(), 'user settings')
        self.assertFalse((Path(job['data_dir']) / 'state/runtime.json').exists())


if __name__ == '__main__':
    unittest.main()
