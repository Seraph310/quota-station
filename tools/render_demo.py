"""Create public preview assets from isolated synthetic data, not live caches."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['QT_SCALE_FACTOR'] = '2'

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QApplication
from app import BASE, setup_fonts
from demo import DemoStation, demo_state

application = QApplication([])
setup_fonts(application)
destination = BASE / 'docs' / 'images'
destination.mkdir(parents=True, exist_ok=True)
with demo_state():
    station = DemoStation()
    station.show()
    for shape in ('card', 'ball'):
        station.shape = shape
        station.collapse()
        application.processEvents()
        station.grab().save(str(destination / (shape + '.png')))
    station.shape = 'card'
    station.expand()
    application.processEvents()
    station.grab().save(str(destination / 'note.png'))
    station.poll.stop()
    station.clock.stop()
    station.tray.hide()
    station.hide()

canvas = QPixmap(1440, 860)
canvas.fill(QColor('#f3f5f0'))
painter = QPainter(canvas)
painter.setRenderHint(QPainter.RenderHint.Antialiasing)
painter.setPen(QColor('#34483b'))
painter.setFont(QFont('Microsoft YaHei', 32, QFont.Weight.Bold))
painter.drawText(74, 100, '额度小站')
painter.setPen(QColor('#6d796b'))
painter.setFont(QFont('Microsoft YaHei', 15))
painter.drawText(77, 148, '留一点余量，从容做事')
painter.setPen(QColor('#778475'))
painter.setFont(QFont('Microsoft YaHei', 12))
painter.drawText(77, 193, 'Codex  /  Qoder  /  WorkBuddy')

def put(name, x, y, width):
    pixmap = QPixmap(str(destination / name))
    height = width * pixmap.height() / pixmap.width()
    painter.drawPixmap(QRectF(x, y, width, height), pixmap, QRectF(pixmap.rect()))

put('card.png', 70, 275, 276)
put('ball.png', 380, 275, 262)
put('note.png', 770, 78, 563)
painter.setFont(QFont('Microsoft YaHei', 14))
painter.setPen(QColor('#455849'))
painter.drawText(105, 592, '小卡片')
painter.drawText(442, 592, '悬浮球')
painter.setFont(QFont('Microsoft YaHei', 12))
painter.setPen(QColor('#748171'))
painter.drawText(77, 659, '单击切换  ·  双击展开  ·  折角缩放')
painter.drawText(77, 699, '每 5 分钟自动刷新，失败时保留上次余额')
painter.setFont(QFont('Microsoft YaHei', 10))
painter.drawText(77, 792, '界面为真实程序渲染；图中数值均为虚构演示数据。')
painter.end()
canvas.save(str(destination / 'overview.png'))
print('Public demo previews rendered without reading live account data.')
