"""Reproducible bilingual README assets, rendered only from synthetic data."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['QT_SCALE_FACTOR'] = '2'

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QApplication
from app import BASE, setup_fonts, icon
from demo import DemoStation, demo_state
from i18n import tr


def main():
    qt = QApplication([])
    setup_fonts(qt)
    destination = BASE / 'docs/images'
    destination.mkdir(parents=True, exist_ok=True)
    assert icon(256).pixmap(256, 256).save(str(destination / 'app-icon.png'))
    for language in ('zh-CN', 'en'):
        shots = {}
        with demo_state(language):
            station = DemoStation()
            try:
                station.show()
                for shape in ('card', 'ball'):
                    station.set_shape(shape)
                    station.collapse()
                    qt.processEvents()
                    shots[shape] = station.grab()
                station.set_shape('card')
                station.docking.dock('right', qt.primaryScreen())
                qt.processEvents()
                shots['dock'] = station.grab()
                station.docking.undock()
                station.expand()
                qt.processEvents()
                # The offscreen virtual monitor can be tiny at 2x DPI. Show the
                # complete three-row note in the public preview, without scrolling.
                station.row_scroll.setFixedHeight(station.row_scroll.widget().sizeHint().height())
                station.layout().activate()
                qt.processEvents()
                shots['expanded'] = station.grab()
                for key, source in station.sources.items():
                    if source['origin'] == 'Magpie' and source['provider'] in ('codearts', 'deepseek'):
                        station.set_source_visible(key, True)
                station.show_sources()
                station.source_picker.resize(480, 680)
                qt.processEvents()
                assert station.source_picker.grab().save(str(destination / f'sources-{language}.png'))
            finally:
                if station.source_picker:
                    station.source_picker.close()
                station.poll.stop()
                station.clock.stop()
                station.tray.hide()
                station.close()

        english = language == 'en'
        canvas = QPixmap(1600, 1000)
        canvas.fill(QColor('#f3f5f0'))
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        def text(x, y, value, size, color='#34483b', bold=False):
            painter.setPen(QColor(color))
            painter.setFont(QFont('Microsoft YaHei', size, QFont.Weight.Bold if bold else QFont.Weight.Normal))
            painter.drawText(x, y, value)
        def put(name, x, y, width, height):
            pixmap = shots[name]
            factor = min(width / pixmap.width(), height / pixmap.height())
            target = QRectF(x, y, pixmap.width() * factor, pixmap.height() * factor)
            painter.drawPixmap(target, pixmap, QRectF(pixmap.rect()))
        text(80, 110, 'Quota Station' if english else '额度小站', 40, bold=True)
        text(82, 170, 'Your AI quotas, at a glance.' if english else '把 AI 额度放在手边，少切几个窗口。', 21, '#687265')
        text(84, 226, 'Windows  /  macOS     ·     English  /  简体中文', 15, '#687265')
        put('card', 65, 304, 310, 310)
        put('ball', 440, 300, 290, 290)
        text(147, 648, 'Card' if english else '小卡片', 20)
        text(541, 648, 'Orb' if english else '悬浮球', 20)
        put('dock', 102, 740, 24, 128)
        text(169, 777, '12 px. Still in view.' if english else '12 像素，也能看额度。', 20)
        text(169, 824, 'Dock at the edge. Hover to peek.' if english else '贴边收起，悬停即看。', 16, '#687265')
        put('expanded', 877, 180, 615, 735)
        text(84, 956, 'Real app UI · Synthetic demo data · No real accounts' if english else '真实程序界面 · 虚构演示数据 · 不含真实账号', 12, '#748171')
        painter.end()
        assert canvas.save(str(destination / f'overview-{language}.png'))
    print('Rendered bilingual public previews using isolated synthetic data.')


if __name__ == '__main__':
    main()
