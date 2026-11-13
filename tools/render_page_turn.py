"""Render both page-turn directions from the real widget and synthetic values."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['QT_SCALE_FACTOR'] = '2'

from pathlib import Path
import json
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QApplication
from app import BASE, setup_fonts
from demo import DemoStation, demo_state
from page_turn import PageTurn

application = QApplication([])
setup_fonts(application)
destination = BASE / 'docs' / 'images'
destination.mkdir(parents=True, exist_ok=True)
frames_path = BASE / 'tests' / 'artifacts' / 'page-turn'
frames_path.mkdir(parents=True, exist_ok=True)
canvas = QPixmap(1800, 690)
canvas.fill(QColor('#f3f5f0'))
painter = QPainter(canvas)
painter.setRenderHint(QPainter.RenderHint.Antialiasing)
painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
painter.setFont(QFont('Microsoft YaHei', 14))
painter.setPen(QColor('#458068'))
frame_count = round(PageTurn.DURATION / 20) + 1
frame_times = [round(index * PageTurn.DURATION / (frame_count - 1)) for index in range(frame_count)]
key_frames = [round(fraction * (frame_count - 1)) for fraction in (0, .23, .42, .59, .77, 1)]
with demo_state():
    station = DemoStation()
    station.show()
    application.processEvents()
    for row, direction, name, caption in ((0, 1, 'next', '下一页：右下 ↖ 左上'), (1, -1, 'previous', '上一页：左上 ↘ 右下')):
        station.cycle(direction)
        turn = station.mini.page_turn
        turn.animation.pause()
        painter.drawText(34, row * 330 + 35, caption)
        for index, milliseconds in enumerate(frame_times):
            turn.animation.setCurrentTime(milliseconds)
            if index == frame_count - 1:
                turn.finish()
            application.processEvents()
            frame = station.grab()
            frame.save(str(frames_path / f'{name}-{index:02d}.png'))
            if index in key_frames:
                column = key_frames.index(index)
                painter.drawPixmap(QRectF(10 + column * 298, 55 + row * 330, 282, 245), frame, QRectF(frame.rect()))
        turn.finish()
    station.poll.stop()
    station.clock.stop()
    station.tray.hide()
    station.close()
painter.end()
canvas.save(str(destination / 'page-turn.png'))
(frames_path / 'manifest.json').write_text(json.dumps({'frame_times': frame_times}), encoding='utf-8')
print('Both page turns rendered from isolated demo data.')
