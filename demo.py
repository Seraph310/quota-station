"""An offline, isolated UI demo: never reads real profiles or quota caches."""
from contextlib import contextmanager
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time

from PySide6.QtWidgets import QApplication
import app as station_app


@contextmanager
def demo_state():
    previous = station_app.STATE
    with TemporaryDirectory(prefix='quota-station-demo-') as directory:
        station_app.STATE = Path(directory)
        now = time.time()
        snapshots = {
            '0': {'name': 'Codex', 'balance': 78, 'unit': '%', 'subtitle': '本周剩余'},
            '1': {'name': 'Qoder', 'balance': 620, 'unit': 'Credits', 'subtitle': '可用 Credits 合计'},
            '2': {'name': 'WorkBuddy', 'balance': 1280.5, 'unit': '积分', 'subtitle': '剩余积分'},
        }
        for item in snapshots.values():
            item.update(updated_at=now, reset_at=None,
                        details=[{'label': '数据来源', 'value': '虚构演示数据，不对应任何真实账号'}])
        (station_app.STATE / 'balances.json').write_text(json.dumps(snapshots), encoding='utf-8')
        try:
            yield
        finally:
            station_app.STATE = previous


class DemoStation(station_app.Station):
    def __init__(self):
        super().__init__(offline=True)
        self.setWindowTitle('额度小站 · 演示')

    def render(self):
        super().render()
        self.mini.unit.setText('演示数据')
        for _, _, _, right, _ in self.rows:
            right.setText('演示数据')
        self.last_updated.setText('演示模式 · 不连接账号')
        self.refresh_button.setText('演示')
        self.refresh_button.setEnabled(False)
        self.tray.setToolTip('额度小站 · 演示模式')


def main():
    application = QApplication(sys.argv[:1])
    station_app.setup_fonts(application)
    application.setQuitOnLastWindowClosed(False)
    with demo_state():
        station = DemoStation()
        station.show()
        if '--expanded' in sys.argv:
            station.expand()
        code = application.exec()
        station.poll.stop()
        station.clock.stop()
        station.tray.hide()
        return code


if __name__ == '__main__':
    raise SystemExit(main())
