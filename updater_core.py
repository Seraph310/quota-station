"""Verified release downloads and an independent, rollback-capable installer."""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import plistlib
import re
import shutil
import ssl
import stat
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile

import certifi

from runtime_paths import resource_root, user_data_root

REPO = 'Seraph310/quota-station'
API = f'https://api.github.com/repos/{REPO}/releases/latest'
RELEASES = f'https://github.com/{REPO}/releases'
MAX_PACKAGE = 400 * 1024 * 1024
MAX_UNPACKED = 1500 * 1024 * 1024


class UpdateError(RuntimeError):
    pass


class Cancelled(UpdateError):
    pass


def version_tuple(value):
    match = re.fullmatch(r'v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)', str(value))
    if not match:
        raise UpdateError('版本信息格式不正确')
    return tuple(map(int, match.groups()))


def platform_key():
    machine = platform.machine().lower()
    if sys.platform == 'win32' and machine in ('amd64', 'x86_64'):
        return 'windows-x64', '.zip'
    if sys.platform == 'darwin' and machine in ('arm64', 'aarch64', 'x86_64', 'amd64'):
        return ('macos-arm64' if machine in ('arm64', 'aarch64') else 'macos-x64'), '.dmg'
    raise UpdateError('当前系统暂不支持自动升级')


def parse_release(payload, current, target=None):
    if not isinstance(payload, dict) or payload.get('draft') or payload.get('prerelease'):
        raise UpdateError('未找到正式发布版本')
    tag = payload.get('tag_name', '')
    version = '.'.join(map(str, version_tuple(tag)))
    key, extension = target or platform_key()
    name = f'QuotaStation-{version}-{key}{extension}'
    assets = payload.get('assets', [])
    matches = [item for item in assets if isinstance(item, dict) and item.get('name') == name]
    if len(matches) != 1:
        raise UpdateError('这个版本尚未提供当前系统的安装包')
    asset = matches[0]
    url = asset.get('browser_download_url')
    expected = f'https://github.com/{REPO}/releases/download/v{version}/{name}'
    digest = asset.get('digest', '')
    size = asset.get('size')
    if (url != expected or asset.get('state') != 'uploaded'
            or not re.fullmatch(r'sha256:[a-fA-F0-9]{64}', str(digest))
            or type(size) is not int or not 0 < size <= MAX_PACKAGE):
        raise UpdateError('安装包信息或校验值不完整，暂不升级')
    return {'version': version, 'newer': version_tuple(version) > version_tuple(current),
            'name': name, 'url': url, 'sha256': digest[7:].lower(), 'size': size,
            'notes': str(payload.get('body') or '')[:16000], 'platform': key}


def _allowed_url(url):
    parsed = urllib.parse.urlsplit(url)
    return (parsed.scheme == 'https' and not parsed.username and not parsed.password
            and parsed.port in (None, 443) and parsed.hostname in
            ('api.github.com', 'github.com', 'release-assets.githubusercontent.com',
             'objects.githubusercontent.com', 'github-releases.githubusercontent.com'))


class _GithubRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, new_url):
        if not _allowed_url(new_url):
            raise UpdateError('下载跳转地址不属于 GitHub')
        return super().redirect_request(request, file, code, message, headers, new_url)


def open_url(url):
    if not _allowed_url(url):
        raise UpdateError('更新地址不正确')
    context = ssl.create_default_context(cafile=certifi.where())
    opener = urllib.request.build_opener(_GithubRedirect(), urllib.request.HTTPSHandler(context=context))
    request = urllib.request.Request(url, headers={'User-Agent': 'QuotaStation-Updater',
                                                  'Accept': 'application/vnd.github+json'})
    try:
        return opener.open(request, timeout=25)
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 429):
            raise UpdateError('GitHub 暂时限制了查询次数，请稍后再试') from None
        raise UpdateError(f'GitHub 暂时无法连接（{exc.code}），请稍后重试') from None
    except (OSError, urllib.error.URLError):
        raise UpdateError('无法连接 GitHub，请检查网络后重试') from None


def check_release(current):
    with open_url(API) as response:
        raw = response.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        raise UpdateError('更新信息过大')
    try:
        return parse_release(json.loads(raw), current)
    except (ValueError, TypeError, KeyError):
        raise UpdateError('无法解析 GitHub 更新信息') from None


def cancelled(event):
    if event and event.is_set():
        raise Cancelled('已取消更新')


def download(release, destination, progress, cancel=None):
    path = Path(destination)
    part = path.with_suffix(path.suffix + '.part')
    digest, count = hashlib.sha256(), 0
    try:
        with open_url(release['url']) as response, part.open('xb') as output:
            while True:
                cancelled(cancel)
                chunk = response.read(128 * 1024)
                if not chunk:
                    break
                count += len(chunk)
                if count > release['size'] or count > MAX_PACKAGE:
                    raise UpdateError('下载大小与发布信息不一致')
                digest.update(chunk)
                output.write(chunk)
                progress(round(count * 100 / release['size']), '正在下载')
        if count != release['size'] or digest.hexdigest() != release['sha256']:
            raise UpdateError('安装包校验失败，当前版本未改变，请重试')
        part.replace(path)
    finally:
        part.unlink(missing_ok=True)
    return path


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.part')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def executable(root):
    root = Path(root)
    return root / ('QuotaStation.exe' if sys.platform == 'win32' else 'Contents/MacOS/QuotaStation')


def installation():
    if not getattr(sys, 'frozen', False):
        if sys.platform == 'win32':
            return user_data_root() / 'app/QuotaStation'
        return Path.home() / 'Applications/Quota Station.app'
    binary = Path(sys.executable).resolve()
    if sys.platform == 'win32':
        return binary.parent
    bundle = next((path for path in binary.parents if path.suffix == '.app'), None)
    if not bundle or '/AppTranslocation/' in str(bundle) or str(bundle).startswith('/Volumes/'):
        raise UpdateError('请先把小站拖入 Applications，再检查更新')
    return bundle


def clean_environment():
    env = os.environ.copy()
    for key in list(env):
        if key.startswith('_PYI_') or key in ('PYTHONHOME', 'PYTHONPATH', 'QT_PLUGIN_PATH',
                                             'QT_QPA_PLATFORM_PLUGIN_PATH', 'DYLD_LIBRARY_PATH'):
            env.pop(key, None)
    env['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
    return env


def spawn(command, **kwargs):
    # External tools/new versions must not inherit the old PyInstaller DLL path.
    frozen_windows = sys.platform == 'win32' and getattr(sys, 'frozen', False)
    if frozen_windows:
        ctypes.windll.kernel32.SetDllDirectoryW(None)
    try:
        return subprocess.Popen(command, env=clean_environment(),
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), **kwargs)
    finally:
        if frozen_windows:
            ctypes.windll.kernel32.SetDllDirectoryW(str(sys._MEIPASS))


def copy_program(source, destination):
    source, destination = Path(source), Path(destination)
    destination.mkdir()
    if sys.platform == 'win32':
        shutil.copy2(source / 'QuotaStation.exe', destination / 'QuotaStation.exe')
        shutil.copytree(source / '_internal', destination / '_internal')
    else:
        # ditto preserves framework symlinks and code-signature resources.
        result = spawn(['/usr/bin/ditto', str(source / 'Contents'), str(destination / 'Contents')])
        if result.wait(timeout=180):
            raise UpdateError('无法复制应用程序')


def unpack_zip(archive, destination):
    destination = Path(destination)
    with zipfile.ZipFile(archive) as package:
        entries = package.infolist()
        if sum(item.file_size for item in entries) > MAX_UNPACKED or len(entries) > 15000:
            raise UpdateError('安装包解压大小异常')
        names = set()
        for item in entries:
            path = PurePosixPath(item.filename)
            name = item.filename.casefold()
            if (not path.parts or path.parts[0] != 'QuotaStation' or '..' in path.parts
                    or '\\' in item.filename or ':' in item.filename or path.is_absolute()
                    or stat.S_ISLNK(item.external_attr >> 16) or name in names):
                raise UpdateError('安装包目录不正确')
            names.add(name)
        package.extractall(destination)
    root = destination / 'QuotaStation'
    if not (root / 'QuotaStation.exe').is_file() or not (root / '_internal').is_dir():
        raise UpdateError('安装包缺少程序文件')
    return root


def stage_package(package, stage, job_dir, version):
    if sys.platform == 'win32':
        root = unpack_zip(package, job_dir / 'unpacked')
        shutil.copytree(root, stage)
    else:
        mount = job_dir / 'mount'
        mount.mkdir()
        process = spawn(['/usr/bin/hdiutil', 'attach', '-readonly', '-nobrowse', '-mountpoint', str(mount), str(package)],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if process.wait(timeout=90):
            raise UpdateError('无法打开下载的安装包')
        try:
            bundle = mount / 'Quota Station.app'
            with (bundle / 'Contents/Info.plist').open('rb') as stream:
                info = plistlib.load(stream)
            if info.get('CFBundleIdentifier') != 'io.github.Seraph310.QuotaStation' or info.get('CFBundleShortVersionString') != version:
                raise UpdateError('安装包身份或版本不匹配')
            if spawn(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(bundle)],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).wait(timeout=60):
                raise UpdateError('应用签名校验失败')
            copy_program(bundle, stage)
        finally:
            spawn(['/usr/bin/hdiutil', 'detach', str(mount)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).wait(timeout=45)


def prepare_update(release, progress, cancel=None):
    target = installation().resolve()
    if target == target.parent or target.is_symlink():
        raise UpdateError('安装位置不正确')
    token = uuid.uuid4().hex
    job_dir = user_data_root().resolve() / 'updates' / token
    stage = target.parent / f'.{target.name}.new-{token}'
    backup = target.parent / f'.{target.name}.old-{token}'
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        stage.mkdir()  # Probe the actual installation volume before downloading.
        stage.rmdir()
    except OSError:
        raise UpdateError('当前安装目录不可写，请把程序移到你有写入权限的目录') from None
    if shutil.disk_usage(target.parent).free < MAX_UNPACKED:
        raise UpdateError('升级需要至少 1.5 GB 可用空间')
    job_dir.mkdir(parents=True)
    job = {'id': token, 'target': str(target), 'stage': str(stage), 'backup': str(backup),
           'version': release['version'], 'parent_pid': os.getpid(), 'ready_timeout': 45,
           'data_dir': str(user_data_root().resolve()), 'source_root': '',
           'fallback': [str(executable(target))], 'launch_args': []}
    try:
        package = download(release, job_dir / release['name'], progress, cancel)
        progress(-1, '正在准备升级')
        cancelled(cancel)
        stage_package(package, stage, job_dir, release['version'])
        cancelled(cancel)
        if getattr(sys, 'frozen', False):
            runner = job_dir / ('runner' if sys.platform == 'win32' else 'Runner.app')
            copy_program(installation(), runner)
            job['helper'] = [str(executable(runner)), '--apply-update', str(job_dir / 'job.json')]
        else:
            job['source_root'] = str(resource_root())
            job['fallback'] = [sys.executable, str(resource_root() / 'app.py')]
            job['helper'] = [sys.executable, str(resource_root() / 'updater_core.py'), '--apply-update', str(job_dir / 'job.json')]
        cancelled(cancel)
        write_json(job_dir / 'job.json', job)
        return job_dir / 'job.json'
    except Exception:
        # Only remove our newly allocated staging paths, never an installation.
        if stage.parent == target.parent and stage.name == f'.{target.name}.new-{token}' and stage.exists():
            shutil.rmtree(stage)
        shutil.rmtree(job_dir, ignore_errors=True)
        raise


def validate_job(job_file):
    job_file = Path(job_file).resolve()
    job = json.loads(job_file.read_text('utf-8'))
    token = job['id']
    target, stage, backup = (Path(job[key]) for key in ('target', 'stage', 'backup'))
    if (not re.fullmatch('[0-9a-f]{32}', token) or job_file.name != 'job.json'
            or job_file.parent != Path(job['data_dir']).resolve() / 'updates' / token
            or not target.is_absolute() or target != target.resolve() or target == target.parent
            or stage != target.parent / f'.{target.name}.new-{token}'
            or backup != target.parent / f'.{target.name}.old-{token}'
            or stage.is_symlink() or backup.is_symlink() or target.is_symlink()
            or job_file.is_relative_to(target) or not executable(stage).is_file()
            or type(job['parent_pid']) is not int or job['parent_pid'] < 0):
        raise UpdateError('更新任务路径校验失败')
    version_tuple(job['version'])
    return job


def migrate_source_state(job_file):
    job = validate_job(job_file)
    if not job['source_root']:
        return
    source, destination = Path(job['source_root']), Path(job['data_dir'])
    for relative in ('state/settings.json', 'state/sources.json', 'state/balances.json'):
        old, new = source / relative, destination / relative
        if old.is_file() and old.resolve() != new.resolve():
            if new.exists():
                saved = Path(job_file).parent / 'previous-settings' / relative
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(new, saved)
            new.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(old, new)


def discard_update(job_file):
    """Cancel only our validated, unused staging directory; never touch the app."""
    try:
        job = validate_job(job_file)
        directory = Path(job_file).resolve().parent
        marker = directory / 'helper-ready.json'
        if marker.exists() and process_alive(json.loads(marker.read_text('utf-8'))['pid']):
            return
        shutil.rmtree(Path(job['stage']))
        shutil.rmtree(directory)
    except (OSError, ValueError, KeyError, UpdateError):
        pass


def launch_update(job_file):
    job = validate_job(job_file)
    migrate_source_state(job_file)
    process = spawn(job['helper'], cwd=str(Path(job_file).parent),
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    marker = Path(job_file).parent / 'helper-ready.json'
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if marker.is_file() and process.poll() is None:
            return process
        if process.poll() is not None:
            raise UpdateError('升级助手未能启动，当前版本未改变')
        time.sleep(0.1)
    process.terminate()
    process.wait(timeout=10)
    raise UpdateError('升级助手启动超时，当前版本未改变')


def process_alive(pid):
    if pid <= 0:
        return False
    if sys.platform == 'win32':
        kernel = ctypes.windll.kernel32
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def move_directory(source, destination):
    for attempt in range(20):
        try:
            Path(source).rename(destination)
            return
        except OSError:
            if attempt == 19:
                raise
            time.sleep(0.25)


def mark_ready(path, version):
    path = Path(path).resolve()
    expected = user_data_root().resolve() / 'updates'
    if path.name != 'ready.json' or path.parent.parent != expected or not re.fullmatch('[0-9a-f]{32}', path.parent.name):
        raise UpdateError('更新确认路径不正确')
    write_json(path, {'version': version, 'pid': os.getpid()})


def apply_job(job_file):
    job = validate_job(job_file)
    directory = Path(job_file).resolve().parent
    target, stage, backup = (Path(job[key]) for key in ('target', 'stage', 'backup'))
    ready = directory / 'ready.json'
    ready.unlink(missing_ok=True)
    process, swapped, saved = None, False, False
    result = {'version': job['version'], 'status': 'error', 'message': '', 'target': str(target), 'id': job['id']}
    write_json(directory / 'helper-ready.json', {'pid': os.getpid()})
    try:
        deadline = time.monotonic() + 60
        while process_alive(job['parent_pid']):
            if time.monotonic() > deadline:
                raise UpdateError('旧版本尚未退出，更新已停止')
            time.sleep(0.2)
        if backup.exists():
            raise UpdateError('备份目录已存在，更新已停止')
        if target.exists():
            move_directory(target, backup)
            saved = True
        move_directory(stage, target)
        swapped = True
        process = spawn([str(executable(target)), *job['launch_args'], '--update-ready', str(ready)], cwd=str(target))
        deadline = time.monotonic() + max(1, min(90, job['ready_timeout']))
        while time.monotonic() < deadline:
            if ready.is_file():
                receipt = json.loads(ready.read_text('utf-8'))
                if receipt.get('version') == job['version'] and receipt.get('pid') == process.pid:
                    result.update(status='success', message='升级完成', pid=process.pid)
                    break
            if process.poll() is not None:
                raise UpdateError('新版本未能正常启动')
            time.sleep(0.2)
        else:
            raise UpdateError('新版本启动超时')
    except Exception as exc:
        if process is not None and process.poll() is None:
            process.terminate()  # Only the new process started by this helper.
            process.wait(timeout=15)
        if swapped:
            move_directory(target, stage)
        if saved:
            move_directory(backup, target)
        result['message'] = '升级未完成，已保留原版本。' + (str(exc) if isinstance(exc, UpdateError) else '无法替换程序文件，请关闭占用它的窗口后重试。')
    write_json(directory / 'result.json', result)
    write_json(Path(job['data_dir']) / 'updates/last-result.json', result)
    if result['status'] == 'error' and not process_alive(job['parent_pid']):
        spawn(job['fallback'], cwd=str(Path(job['fallback'][0]).parent))
    if result['status'] == 'success' and job['source_root'] and sys.platform == 'win32':
        script = resource_root() / 'updater_shortcut.ps1'
        spawn([str(Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'),
               '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(script), '-JobFile', str(job_file)],
              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).wait(timeout=20)
    return 0 if result['status'] == 'success' else 1


if __name__ == '__main__' and len(sys.argv) == 3 and sys.argv[1] == '--apply-update':
    raise SystemExit(apply_job(sys.argv[2]))
