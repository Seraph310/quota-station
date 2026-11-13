"""Build and smoke-test redistributable Windows/macOS apps on their native OS."""
from __future__ import annotations

import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from version import __version__


def run(*command, **kwargs):
    subprocess.run([str(item) for item in command], check=True, **kwargs)


def prepare_assets():
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    from app import icon
    qt = QApplication.instance() or QApplication([])
    assets = ROOT / 'build/assets'
    assets.mkdir(parents=True, exist_ok=True)
    image = assets / 'icon.png'
    assert icon(256).pixmap(256, 256).save(str(image))
    png = image.read_bytes()
    # ICO supports a PNG image entry on all supported Windows versions.
    (assets / 'icon.ico').write_bytes(struct.pack('<HHH', 0, 1, 1) +
        struct.pack('<BBBBHHII', 0, 0, 0, 0, 1, 32, len(png), 22) + png)
    if sys.platform == 'darwin':
        iconset = assets / 'QuotaStation.iconset'
        iconset.mkdir(exist_ok=True)
        for size in (16, 32, 128, 256, 512):
            for multiplier, suffix in ((1, ''), (2, '@2x')):
                pixels = size * multiplier
                assert icon(pixels).pixmap(pixels, pixels).save(str(iconset / f'icon_{size}x{size}{suffix}.png'))
        run('iconutil', '-c', 'icns', '-o', assets / 'icon.icns', iconset)
    version_tuple = tuple(map(int, __version__.split('.'))) + (0,)
    strings = {'CompanyName': 'Seraph310', 'FileDescription': '额度小站 · Quota Station',
               'FileVersion': __version__, 'ProductVersion': __version__,
               'ProductName': 'Quota Station', 'OriginalFilename': 'QuotaStation.exe'}
    fields = ','.join(f'StringStruct({key!r}, {value!r})' for key, value in strings.items())
    (assets / 'version.txt').write_text(
        f'VSVersionInfo(ffi=FixedFileInfo(filevers={version_tuple!r}, prodvers={version_tuple!r}, '
        'mask=0x3f, flags=0, OS=0x40004, fileType=1, subtype=0, date=(0, 0)), '
        f'kids=[StringFileInfo([StringTable("040904B0", [{fields}])]), '
        'VarFileInfo([VarStruct("Translation", [1033, 1200])])])', encoding='utf-8')
    licenses = assets / 'licenses'
    licenses.mkdir(exist_ok=True)
    (licenses / 'THIRD_PARTY_NOTICES.txt').write_text(
        'Quota Station bundles Python, PySide6/Qt, shiboken6, cryptography and their runtime dependencies.\n'
        'Python: https://www.python.org/psf/license/\n'
        'PySide6/Qt: https://doc.qt.io/qtforpython-6/licenses.html\n'
        'PySide6/Qt source and LGPL information: https://code.qt.io/ and https://www.qt.io/licensing/open-source-lgpl-obligations\n'
        'cryptography: https://github.com/pyca/cryptography\n'
        'PyInstaller bootloader exception: https://pyinstaller.org/en/stable/license.html\n'
        'Libraries are dynamically loaded from the distributed app folder; replacement libraries must be ABI-compatible.\n',
        encoding='utf-8')
    for name in ('PySide6', 'PySide6_Essentials', 'PySide6_Addons', 'shiboken6', 'cryptography', 'pyinstaller'):
        distribution = importlib.metadata.distribution(name)
        for relative in distribution.files or []:
            if '..' in relative.parts:
                continue
            if any(part.lower() in ('licenses', 'license', 'copying') or part.upper().startswith(('LICENSE', 'COPYING'))
                   for part in relative.parts):
                source = Path(distribution.locate_file(relative))
                if source.is_file():
                    target = licenses / name / Path(*relative.parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
    python_license = Path(sys.base_prefix) / 'LICENSE.txt'
    if python_license.is_file():
        shutil.copy2(python_license, licenses / 'Python-LICENSE.txt')
    return assets


def main():
    if sys.platform not in ('win32', 'darwin'):
        raise SystemExit('Build on Windows or macOS; cross-compilation is not supported.')
    if os.environ.get('GITHUB_REF_TYPE') == 'tag' and os.environ.get('GITHUB_REF_NAME') != 'v' + __version__:
        raise SystemExit('The release tag must match version.py.')
    # These are the only build/output directories PyInstaller may replace.
    for name in ('build', 'dist'):
        assert (ROOT / name).resolve().is_relative_to(ROOT)
    assets = prepare_assets()
    build_env = os.environ.copy()
    build_env.pop('PYTHONHOME', None)
    build_env.pop('PYTHONPATH', None)
    build_env['PYINSTALLER_CONFIG_DIR'] = str(ROOT / 'build/pyinstaller-cache')
    if sys.platform == 'win32':
        # Do not collect unrelated same-name DLLs from developer tools on PATH
        # (for example Poppler's incompatible icuuc.dll instead of Windows ICU).
        system = Path(os.environ.get('SystemRoot', 'C:/Windows'))
        build_env['PATH'] = os.pathsep.join(map(str, (Path(sys.executable).parent, Path(sys.base_prefix),
                                                    system / 'System32', system)))
    run(sys.executable, '-m', 'PyInstaller', '--clean', '--noconfirm', '--distpath', ROOT / 'dist',
        '--workpath', ROOT / 'build/pyinstaller', ROOT / 'QuotaStation.spec', cwd=ROOT, env=build_env)
    mac = sys.platform == 'darwin'
    binary = ROOT / ('dist/Quota Station.app/Contents/MacOS/QuotaStation' if mac else 'dist/QuotaStation/QuotaStation.exe')
    evidence = ROOT / 'build/smoke'
    evidence.mkdir(exist_ok=True)
    report_file = evidence / 'report.json'
    if report_file.exists():
        report_file.unlink()
    run(binary, '--smoke-test', evidence, timeout=120, env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'})
    report = json.loads(report_file.read_text('utf-8'))
    assert report['success'] and report['frozen'] and report['state_isolated']
    assert report['version'] == __version__
    assert report['native_sources'] == ([0] if mac else [0, 1, 2])
    arch = platform.machine().lower()
    arch = 'arm64' if arch in ('arm64', 'aarch64') else 'x64'
    destination = ROOT / 'dist/release'
    destination.mkdir(exist_ok=True)
    stem = f'QuotaStation-{__version__}-{"macos" if mac else "windows"}-{arch}'
    if mac:
        bundle = ROOT / 'dist/Quota Station.app'
        run('codesign', '--verify', '--deep', '--strict', bundle)
        with tempfile.TemporaryDirectory(prefix='quota-station-dmg-') as temporary:
            staging = Path(temporary)
            shutil.copytree(bundle, staging / bundle.name, symlinks=True)
            (staging / 'Applications').symlink_to('/Applications', target_is_directory=True)
            shutil.copy2(ROOT / 'docs/DOWNLOAD.md', staging / '先读我.txt')
            run('hdiutil', 'create', '-volname', 'Quota Station', '-srcfolder', staging,
                '-ov', '-format', 'UDZO', destination / (stem + '.dmg'))
    else:
        folder = ROOT / 'dist/QuotaStation'
        shutil.copy2(ROOT / 'docs/DOWNLOAD.md', folder / '先读我.txt')
        with zipfile.ZipFile(destination / (stem + '.zip'), 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(folder.rglob('*')):
                if path.is_file():
                    archive.write(path, Path('QuotaStation') / path.relative_to(folder))
    print(json.dumps({'version': __version__, 'platform': sys.platform, 'architecture': arch,
                      'smoke_test': 'passed', 'artifact': str(destination / (stem + ('.dmg' if mac else '.zip')))}))


if __name__ == '__main__':
    main()
