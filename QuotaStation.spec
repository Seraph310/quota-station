# Build on each target OS; PyInstaller is not a cross-compiler.
from pathlib import Path
import sys

root = Path(SPECPATH)
sys.path.insert(0, str(root))
from version import __version__

mac = sys.platform == 'darwin'
assets = root / 'build' / 'assets'
datas = [(str(path), 'providers/qoder_runtime')
         for path in (root / 'providers/qoder_runtime').glob('*.mjs')]
datas.append((str(assets / 'licenses'), 'licenses'))
analysis = Analysis(
    [str(root / 'launcher.py')], pathex=[str(root)], binaries=[], datas=datas,
    hiddenimports=['providers.' + name for name in
                   ('codex_provider', 'qoder_provider', 'workbuddy_provider', 'magpie_provider')],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['tkinter', 'pytest', 'tests'], noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz, analysis.scripts, [], exclude_binaries=True, name='QuotaStation',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False, icon=str(assets / ('icon.icns' if mac else 'icon.ico')),
    version=None if mac else str(assets / 'version.txt'),
)
collection = COLLECT(exe, analysis.binaries, analysis.datas, strip=False, upx=False, name='QuotaStation')
if mac:
    app = BUNDLE(collection, name='Quota Station.app', icon=str(assets / 'icon.icns'),
                 bundle_identifier='io.github.Seraph310.QuotaStation',
                 info_plist={'CFBundleName': '额度小站', 'CFBundleDisplayName': '额度小站',
                             'CFBundleShortVersionString': __version__, 'CFBundleVersion': __version__,
                             'NSHighResolutionCapable': True, 'LSUIElement': True})
