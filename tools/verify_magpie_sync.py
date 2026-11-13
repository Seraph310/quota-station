"""One real read-only sync through the actual button, in an isolated Qt instance.

Never edits the running station's settings or publishes an extra desktop window.
The local report contains connection metadata and counts, not account identities.
"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

import json
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import app

application = QApplication([])
app.setup_fonts(application)
with tempfile.TemporaryDirectory(prefix='quota-magpie-sync-') as directory, \
     patch.object(app, 'STATE', Path(directory)), \
     patch.object(app.QSystemTrayIcon, 'show', lambda _self: None):
    station = app.Station(offline=True)
    station.poll.stop()
    station.clock.stop()
    station.show_sources()
    selected = list(station.visible_sources)
    station.offline = False
    station.render()
    QTest.mouseClick(station.source_picker.refresh_button, Qt.MouseButton.LeftButton)
    deadline = time.monotonic() + 60
    while station.magpie_busy and time.monotonic() < deadline:
        QTest.qWait(50)
    if station.magpie_busy:
        raise RuntimeError('Sync did not complete within 60 seconds')
    if station.magpie_error:
        raise RuntimeError(station.magpie_error)
    saved = json.loads((app.STATE / 'settings.json').read_text('utf-8'))
    assert selected == station.visible_sources == saved['visible_sources']
    assert saved['magpie_connection'] == station.magpie_connection
    station.source_picker.details_button.setChecked(True)
    assert station.magpie_connection.get('executable') in station.source_picker.connection_details.text()
    report = {'success': True, 'button_label': station.source_picker.refresh_button.text(),
              'message': station.source_picker.status.text(),
              'selection_preserved': True, 'connection': station.magpie_connection}
    station.source_picker.close()
    station.tray.hide()
    station.close()
destination = app.BASE / 'tests' / 'magpie_sync_verification.json'
destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(report, ensure_ascii=True))
