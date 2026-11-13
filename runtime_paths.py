"""Keep packaged app resources separate from writable, per-user settings."""
from __future__ import annotations

import os
from pathlib import Path
import sys


def resource_root():
    return Path(__file__).resolve().parent


def data_root():
    override = os.environ.get('QUOTA_STATION_DATA_DIR')
    if override:
        path = Path(override).expanduser()
        if not path.is_absolute():
            raise ValueError('QUOTA_STATION_DATA_DIR must be an absolute path')
        return path
    if not getattr(sys, 'frozen', False):
        return resource_root()
    if sys.platform == 'win32':
        return Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData/Local') / 'QuotaStation'
    if sys.platform == 'darwin':
        return Path.home() / 'Library/Application Support/QuotaStation'
    return Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share') / 'quota-station'


def native_source_keys():
    return [0, 1, 2] if sys.platform == 'win32' else [0]


def cli_environment():
    environment = os.environ.copy()
    if sys.platform == 'darwin':
        # Finder does not inherit interactive shell PATH additions.
        extra = ['/opt/homebrew/bin', '/usr/local/bin', str(Path.home() / '.local/bin')]
        environment['PATH'] = os.pathsep.join(dict.fromkeys(environment.get('PATH', '').split(os.pathsep) + extra))
    return environment
