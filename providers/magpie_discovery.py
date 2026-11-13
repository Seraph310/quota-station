"""Bounded, read-only discovery of an existing local Magpie installation."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def _executable(value):
    if not isinstance(value, (str, Path)) or not str(value).strip():
        return None
    path = Path(os.path.expandvars(str(value).strip().strip('"'))).expanduser()
    try:
        expected = 'magpie.exe' if sys.platform == 'win32' else 'magpie'
        if path.is_absolute() and path.name.lower() == expected and path.is_file() and (sys.platform == 'win32' or os.access(path, os.X_OK)):
            return str(path.absolute())
    except OSError:
        pass
    return None


def _running_paths():
    if sys.platform == 'darwin':
        try:
            result = subprocess.run(['/bin/ps', '-axo', 'comm='], capture_output=True, timeout=6)
            if result.returncode or len(result.stdout) > 256 * 1024:
                return []
            return [line.strip() for line in result.stdout.decode('utf-8', errors='replace').splitlines()
                    if Path(line.strip()).name == 'magpie']
        except (OSError, subprocess.SubprocessError):
            return []
    if os.name != 'nt':
        return []
    # A constant command, with no interpolated paths or account data. Only the
    # executable location is read; command lines and credentials are not queried.
    system = Path(os.environ.get('SystemRoot', 'C:/Windows'))
    powershell = system / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    script = ("[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new(); "
              "@(Get-CimInstance Win32_Process -Filter \"Name = 'magpie.exe'\" "
              "| Select-Object -ExpandProperty ExecutablePath) | ConvertTo-Json -Compress")
    try:
        result = subprocess.run([str(powershell), '-NoProfile', '-NonInteractive', '-Command', script],
                                capture_output=True, timeout=6,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode or len(result.stdout) > 64 * 1024:
            return []
        paths = json.loads(result.stdout.decode('utf-8-sig'))
        return paths if isinstance(paths, list) else [paths] if isinstance(paths, str) else []
    except (OSError, ValueError, subprocess.SubprocessError):
        return []


def _registry_paths():
    if os.name != 'nt':
        return []
    import winreg
    paths = []
    uninstall = r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall'
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive, uninstall, 0, winreg.KEY_READ | view) as root:
                    for index in range(min(winreg.QueryInfoKey(root)[0], 2048)):
                        try:
                            with winreg.OpenKey(root, winreg.EnumKey(root, index)) as item:
                                name = winreg.QueryValueEx(item, 'DisplayName')[0]
                                if not isinstance(name, str) or name.strip().casefold() != 'magpie':
                                    continue
                                for key in ('InstallLocation', 'DisplayIcon'):
                                    try:
                                        value = winreg.QueryValueEx(item, key)[0]
                                    except OSError:
                                        continue
                                    if isinstance(value, str):
                                        if key == 'InstallLocation':
                                            paths.append(str(Path(value.strip('"')) / 'magpie.exe'))
                                        else:
                                            prefix, comma, index_text = value.rpartition(',')
                                            icon_path = prefix if comma and index_text.strip().lstrip('+-').isdigit() else value
                                            paths.append(icon_path.strip().strip('"'))
                        except OSError:
                            continue
            except OSError:
                continue
    return paths


def _usual_paths():
    if sys.platform != 'win32':
        return [Path.home() / '.dsh/magpie/backend/current/magpie',
                Path.home() / '.local/bin/magpie', Path('/opt/homebrew/bin/magpie'),
                Path('/usr/local/bin/magpie'),
                Path.home() / 'Library/Application Support/magpie/backend/current/magpie']
    candidates = [Path.home() / '.dsh/magpie/backend/current/magpie.exe']
    for variable, suffixes in (
        ('LOCALAPPDATA', ('magpie/magpie.exe', 'Programs/magpie/magpie.exe')),
        ('ProgramFiles', ('magpie/magpie.exe',)),
        ('ProgramFiles(x86)', ('magpie/magpie.exe',)),
    ):
        root = os.environ.get(variable)
        if root:
            candidates.extend(Path(root) / suffix for suffix in suffixes)
    return candidates


def discover_executable(saved_path=None, *, rediscover=False):
    """Prefer a running install on explicit sync; reuse a valid saved path later."""
    override = os.environ.get('QUOTA_MAGPIE_EXECUTABLE')
    if override:
        path = _executable(override)
        if not path:
            raise RuntimeError('QUOTA_MAGPIE_EXECUTABLE 未指向有效的 Magpie 程序')
        return path
    if not rediscover:
        path = _executable(saved_path)
        if path:
            return path
    for path in _running_paths():
        found = _executable(path)
        if found:
            return found
    commands = ('magpie.exe', 'magpie') if sys.platform == 'win32' else ('magpie',)
    for path in (shutil.which(command) for command in commands):
        found = _executable(path)
        if found:
            return found
    for path in _registry_paths() + _usual_paths() + [saved_path]:
        found = _executable(path)
        if found:
            return found
    return None
