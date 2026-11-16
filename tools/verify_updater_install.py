"""Install a frozen app over an isolated copy and verify its real startup receipt."""
import argparse
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import updater_core as core
from version import __version__


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    bundle = args.binary.resolve().parent if sys.platform == 'win32' else args.binary.resolve().parents[2]
    report = {'success': False, 'version': __version__, 'platform': sys.platform}
    new_pid = None
    with tempfile.TemporaryDirectory(prefix='quota-update-test-') as directory:
        root = Path(directory).resolve()
        data, token = root / 'data', uuid.uuid4().hex
        os.environ['QUOTA_STATION_DATA_DIR'] = str(data)
        os.environ['QT_QPA_PLATFORM'] = 'offscreen'
        target = root / ('QuotaStation' if sys.platform == 'win32' else 'Quota Station.app')
        stage = root / f'.{target.name}.new-{token}'
        backup = root / f'.{target.name}.old-{token}'
        job_dir = data / 'updates' / token
        job_dir.mkdir(parents=True)
        runner = job_dir / ('runner' if sys.platform == 'win32' else 'Runner.app')
        for destination in (target, stage, runner):
            core.copy_program(bundle, destination)
        (target / 'old-version.marker').touch()
        settings = {'shape': 'ball', 'mini_scale': 1.2, 'visible_sources': [0], 'language': 'en'}
        core.write_json(data / 'state/settings.json', settings)
        job = {'id': token, 'target': str(target), 'stage': str(stage), 'backup': str(backup),
               'version': __version__, 'data_dir': str(data), 'source_root': '', 'parent_pid': 0,
               'ready_timeout': 45, 'launch_args': ['--offline'], 'fallback': [str(core.executable(target)), '--offline']}
        core.write_json(job_dir / 'job.json', job)
        try:
            helper = core.spawn([str(core.executable(runner)), '--apply-update', str(job_dir / 'job.json')], cwd=str(job_dir))
            code = helper.wait(timeout=100)
            result = json.loads((job_dir / 'result.json').read_text('utf-8'))
            new_pid = result.get('pid')
            assert code == 0 and result['status'] == 'success', result
            assert core.process_alive(new_pid)
            assert json.loads((data / 'state/settings.json').read_text('utf-8')) == settings
            assert (backup / 'old-version.marker').is_file()
            assert not (target / 'old-version.marker').exists()
            assert not stage.exists()
            report.update(success=True, settings_preserved=True, backup_preserved=True,
                          frozen_helper=True, new_app_started=True, language_preserved=True)
        finally:
            if new_pid and core.process_alive(new_pid):
                os.kill(new_pid, signal.SIGTERM)
                for _ in range(50):
                    if not core.process_alive(new_pid):
                        break
                    time.sleep(0.1)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
