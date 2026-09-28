"""Render our own Qt widgets offscreen from the verified display cache for QA."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PySide6.QtWidgets import QApplication
from app import Station, BASE, icon, setup_fonts

app = QApplication([])
setup_fonts(app)
station = Station(offline=True)
station.save_settings = lambda: None
out = BASE / 'qa'
out.mkdir(exist_ok=True)
station.show()
for shape in ('card', 'ball'):
    station.shape = shape
    station.collapse()
    app.processEvents()
    station.grab().save(str(out / (shape + '.png')))
station.expand()
app.processEvents()
station.grab().save(str(out / 'note.png'))
icon().pixmap(128, 128).save(str(BASE / 'icon.ico'), 'ICO')
station.tray.hide()
print('Rendered native Qt card, ball and note into qa/')
