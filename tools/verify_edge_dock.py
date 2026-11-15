"""Brief native Windows check with synthetic data; never sends desktop input."""
from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

if sys.platform != 'win32':
    raise SystemExit('This native focus check requires Windows.')
os.environ.pop('QT_QPA_PLATFORM', None)
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from app import setup_fonts
from demo import DemoStation, demo_state


def main():
    destination = ROOT / 'tests/artifacts/edge-dock-native'
    destination.mkdir(parents=True, exist_ok=True)
    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = ctypes.c_void_p
    user32.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    foreground = user32.GetForegroundWindow()
    application = QApplication([])
    application.setQuitOnLastWindowClosed(False)
    setup_fonts(application)
    samples = []
    with demo_state(), patch.object(QSystemTrayIcon, 'show', lambda _self: None):
        station = DemoStation()
        station.poll.stop()
        station.clock.stop()
        station.set_mini_scale(0.8)
        try:
            for side in ('left', 'right'):
                station.docking.dock(side, application.primaryScreen(), center_y=350)
                station.show()
                for mode in ('bar', 'peek', 'tucked'):
                    if mode == 'peek':
                        station.docking.peek()
                    elif mode == 'tucked':
                        station.docking.tuck()
                    QTest.qWait(120)
                    style = user32.GetWindowLongPtrW(int(station.winId()), -20)
                    current = user32.GetForegroundWindow()
                    sample = {'side': side, 'mode': mode,
                              'geometry': list(station.geometry().getRect()),
                              'foreground_unchanged': current == foreground,
                              'native_no_activate': bool(style & 0x08000000),
                              'qt_no_focus': bool(station.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus)}
                    samples.append(sample)
                    assert station.grab().save(str(destination / f'{side}-{mode}.png'))
            report = {'success': all(item['foreground_unchanged'] and item['native_no_activate']
                                     and item['qt_no_focus'] for item in samples),
                      'platform': application.platformName(), 'samples': samples,
                      'state_isolated': True, 'desktop_input_sent': False}
            (destination / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        finally:
            station.tray.hide()
            station.close()
    assert report['success'], 'Check tests/artifacts/edge-dock-native/report.json'
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
