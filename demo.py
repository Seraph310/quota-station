"""An offline, isolated UI demo: never reads real profiles or quota caches."""
from contextlib import contextmanager
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time

from PySide6.QtWidgets import QApplication
import app as station_app
from providers.magpie_provider import normalize


def demo_sources():
    return normalize([
        {'provider': 'codex', 'name': 'Codex', 'kind': 'subscription',
         'user': 'celia@example.test', 'plan': 'Pro Lite',
         'windows': [{'name': '7 days', 'remaining': 86}]},
        {'provider': 'codearts', 'name': 'CodeArts', 'kind': 'subscription',
         'user': 'demo-codearts', 'alias': '158****0000', 'plan': '体验版',
         'windows': [{'name': '总积分', 'remaining': 80, 'limit': 5700, 'amount': 1140, 'unit': 'credits'}]},
        {'provider': 'deepseek', 'name': 'DeepSeek', 'kind': 'balance', 'balance': '¥28.60'},
        {'provider': 'kiro', 'name': 'Kiro', 'kind': 'subscription',
         'user': 'personal@example.test', 'plan': 'Kiro Free',
         'windows': [{'name': 'Credits', 'remaining': 64, 'limit': 50, 'amount': 18, 'unit': 'credits'}]},
        {'provider': 'kiro', 'name': 'Kiro', 'kind': 'subscription',
         'user': 'work@example.test', 'plan': 'Kiro Free',
         'windows': [{'name': 'Credits', 'remaining': 100, 'limit': 50, 'unit': 'credits'}]},
        {'provider': 'jiuzhan', 'name': 'Jiuzhan', 'kind': 'balance', 'balance': '$12.50'},
    ])


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
        self.magpie_connection = {'executable': 'C:/Users/Demo/.dsh/magpie/backend/current/magpie.exe',
                                  'port': 3425, 'version': '演示', 'transport': 'gateway',
                                  'synced_at': time.time(), 'source_count': 6, 'readable_count': 6}
        self.receive_sources(demo_sources(), '')
        self.setWindowTitle('额度小站 · 演示')

    def show_sources(self):
        super().show_sources()
        self.source_picker.setWindowTitle('额度小站 · 显示来源（演示数据）')

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
        if '--sources' in sys.argv:
            station.show_sources()
        code = application.exec()
        station.poll.stop()
        station.clock.stop()
        station.tray.hide()
        return code


if __name__ == '__main__':
    raise SystemExit(main())
