"""Render the real source picker with isolated synthetic accounts."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['QT_SCALE_FACTOR'] = '2'

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from app import BASE, setup_fonts
from demo import DemoStation, demo_state

application = QApplication([])
setup_fonts(application)
destination = BASE / 'docs' / 'images'
destination.mkdir(parents=True, exist_ok=True)
with demo_state():
    station = DemoStation()
    station.set_source_visible(0, False)
    for key, meta in station.sources.items():
        if meta['origin'] == 'Magpie' and meta['provider'] in ('codex', 'codearts', 'deepseek'):
            station.set_source_visible(key, True)
    station.show()
    station.expand()
    application.processEvents()
    station.grab().save(str(destination / 'selected-quotas.png'))
    station.show_sources()
    station.source_picker.resize(480, 800)
    application.processEvents()
    station.source_picker.grab().save(str(destination / 'sources.png'))
    station.source_picker.details_button.setChecked(True)
    application.processEvents()
    station.source_picker.grab().save(str(destination / 'magpie-sync.png'))
    station.source_picker.close()
    station.poll.stop()
    station.clock.stop()
    station.tray.hide()
    station.close()
print('Source selection previews rendered with synthetic accounts.')
