"""额度小站: a local, read-only desktop quota companion."""
from __future__ import annotations

import argparse
import ctypes
import importlib
import json
import math
import os
from pathlib import Path
import sys
import threading
import time

from PySide6.QtCore import QObject, QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
    QLayout, QMenu, QMessageBox, QProgressBar, QPushButton, QScrollArea, QSystemTrayIcon,
    QVBoxLayout, QWidget,
)

from source_picker import SourcePicker
from page_turn import PageTurn
from runtime_paths import data_root, native_source_keys, resource_root
from version import __version__

BASE = resource_root()
STATE = data_root() / 'state'
NAMES = ['Codex', 'Qoder', 'WorkBuddy']
COLORS = ['#458068', '#8170a7', '#ad7a44']
PAPER, TEXT, MUTED, LINE, SOFT = '#fcfdfb', '#303532', '#687265', '#e3e8df', '#f0f3ee'


def read_json(path: Path, fallback):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return fallback


def atomic_json(path: Path, data):
    path.parent.mkdir(exist_ok=True, parents=True)
    temp = path.with_suffix('.part')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def validate_snapshot(data):
    if not isinstance(data, dict):
        raise ValueError('额度返回格式不正确')
    if data.get('source') == 'magpie' and data.get('quota_state') == 'unlimited' and data.get('balance') is None:
        return data
    value = data.get('balance')
    money = data.get('source') == 'magpie' and data.get('kind') == 'balance' and data.get('unit') in ('$', '¥', '€', '£', '元', 'USD', 'CNY', 'EUR', 'GBP')
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or (value < 0 and not money):
        raise ValueError('未返回可确认的剩余额度')
    if data.get('unit') == '%' and value > 100:
        raise ValueError('剩余百分比超出范围')
    return data


def number_text(data):
    if not data:
        return '—'
    if data.get('quota_state') == 'unlimited':
        return '不限量'
    value = data['balance']
    if data.get('unit') == '%':
        return f'{value:,.0f}%'
    if data.get('unit') in ('$', '¥', '€', '£'):
        return f'{data["unit"]}{value:,.2f}'
    # Keep fractional credits visible while avoiding noisy precision.
    return f'{value:,.2f}'.rstrip('0').rstrip('.') if value % 1 else f'{value:,.0f}'


def age_text(timestamp):
    if not timestamp:
        return '尚未更新'
    age = max(0, time.time() - float(timestamp))
    if age < 60:
        return '刚刚更新'
    if age < 3600:
        return f'{int(age // 60)} 分钟前'
    if age < 86400:
        return f'{int(age // 3600)} 小时前'
    return time.strftime('%m-%d %H:%M', time.localtime(timestamp))


def label(text='', size=12, color=TEXT, bold=False):
    item = QLabel(text)
    item.setStyleSheet(f'color:{color};font-size:{size}px;font-weight:{600 if bold else 400};background:transparent;border:0;')
    item.setTextFormat(Qt.TextFormat.PlainText)
    item.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    return item


def setup_fonts(app):
    # Explicitly register installed fonts so development/offscreen rendering also
    # works when the Windows font service is unavailable to the test process.
    font_root = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts'
    for filename in ('msyh.ttc', 'segoeui.ttf'):
        path = font_root / filename
        if path.is_file():
            QFontDatabase.addApplicationFont(str(path))
    app.setFont(QFont('PingFang SC' if sys.platform == 'darwin' else 'Microsoft YaHei', 9))


def icon(size=128):
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.scale(size / 128, size / 128)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(PAPER))
    p.drawRoundedRect(QRectF(6, 6, 116, 116), 30, 30)
    for i, color in enumerate(COLORS):
        p.setBrush(QColor(color))
        p.drawRoundedRect(QRectF(30, 32 + i * 24, 68 - i * 14, 10), 5, 5)
    p.end()
    return QIcon(pix)


class Bridge(QObject):
    result = Signal(int, object, str)
    sources = Signal(object, str)


class ResizeGrip(QWidget):
    """A dedicated diagonal drag target, separate from the card's click/drag."""
    def __init__(self, mini):
        super().__init__(mini)
        self.mini = mini
        self.station = mini.station
        self.start_at = None
        self.setFixedSize(26, 26)
        self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        self.setAccessibleName('拖动书页折角缩放小卡片')
        self.setToolTip('拖住小折角，沿对角线调整大小')

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.scale(self.width() / 26, self.height() / 26)
        # A softly lifted paper corner: shadow below the crease, pale underside
        # above it. The existing drag target and event handling stay intact.
        shadow = QPainterPath()
        shadow.moveTo(6, 22)
        shadow.lineTo(22, 6)
        shadow.quadTo(23, 17, 17, 21)
        shadow.quadTo(11, 24, 6, 22)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(56, 77, 60, 20))
        p.drawPath(shadow)

        fold = QPainterPath()
        fold.moveTo(5, 20)
        fold.quadTo(7.5, 13.5, 6.5, 6.5)
        fold.quadTo(13.5, 7.5, 20, 5)
        fold.lineTo(5, 20)
        fold.closeSubpath()
        paper = QLinearGradient(6, 6, 17, 17)
        paper.setColorAt(0, QColor('#fdfefb'))
        paper.setColorAt(1, QColor('#dce5da'))
        p.setBrush(paper)
        p.setPen(QPen(QColor('#cad6c7'), 0.65))
        p.drawPath(fold)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.mini.timer.stop()
            self.mini.page_turn.finish()
            self.mini.press_at = None
            self.start_at = event.globalPosition().toPoint()
            self.start_scale = self.station.mini_scale
            self.anchor = self.station.pos()
        event.accept()

    def mouseMoveEvent(self, event):
        if self.start_at is not None and event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.globalPosition().toPoint() - self.start_at
            # Project the pointer onto the original card diagonal. Global mouse
            # coordinates avoid feedback as the grip itself moves during resize.
            change = (delta.x() * 138 + delta.y() * 116) / (138 * 138 + 116 * 116)
            self.station.set_mini_scale(self.start_scale + change, clamp=False)
            self.station.move(self.anchor)
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.start_at is not None:
            self.start_at = None
            self.station.clamp_position()
            self.station.save_settings()
        event.accept()

    def mouseDoubleClickEvent(self, event):
        # The resize corner never switches agents or opens the note.
        self.mini.timer.stop()
        event.accept()


class MiniButton(QPushButton):
    """Native double-click timing plus drag suppression; no click-count heuristics."""
    def __init__(self, station):
        super().__init__()
        self.station = station
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.press_at = None
        self.was_dragged = False
        self.double_release = False
        self.origin_agent = 0
        self.pending_offset = 1
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.commit_click)
        box = QVBoxLayout(self)
        box.setContentsMargins(8, 11, 8, 10)
        box.setSpacing(3)
        self.name = label('● Codex', 12)
        self.value = label('—', 29, bold=True)
        self.unit = label('正在连接', 11, MUTED)
        self.dots = label('● · ·', 11, COLORS[0])
        for item in (self.name, self.value, self.unit, self.dots):
            item.setAlignment(Qt.AlignmentFlag.AlignCenter)
            box.addWidget(item)
        self.resize_grip = ResizeGrip(self)
        self.page_turn = PageTurn(self)

    def commit_click(self):
        self.timer.stop()
        self.station.cycle(self.pending_offset)

    def resizeEvent(self, event):
        if hasattr(self, 'page_turn'):
            self.page_turn.finish()
        super().resizeEvent(event)
        self.layout_resize_grip()

    def hideEvent(self, event):
        self.timer.stop()
        self.page_turn.finish()
        super().hideEvent(event)

    def layout_resize_grip(self):
        # Keep the fold inside the rounded paper edge at every card size.
        scale = self.station.mini_scale
        side, inset = round(26 * scale), round(32 * scale)
        self.resize_grip.setFixedSize(side, side)
        self.resize_grip.move(self.width() - inset, self.height() - inset)
        self.resize_grip.raise_()
        if hasattr(self, 'page_turn') and self.page_turn.isVisible():
            self.page_turn.raise_()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        if self.timer.isActive():
            self.commit_click()
        self.page_turn.finish()
        self.origin_agent = self.station.active
        # Assign the exact center to next; the two sides otherwise go backwards
        # and forwards. The ball keeps its existing single-click behavior.
        self.pending_offset = -1 if self.station.shape == 'card' and event.position().x() < self.rect().center().x() else 1
        self.press_at = event.globalPosition().toPoint()
        self.window_at = self.station.pos()
        self.was_dragged = False
        self.double_release = False
        self.setFocus()
        event.accept()

    def mouseMoveEvent(self, event):
        if self.press_at is not None and event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.globalPosition().toPoint() - self.press_at
            if delta.manhattanLength() >= QApplication.startDragDistance():
                self.was_dragged = True
                self.timer.stop()
            if self.was_dragged:
                self.station.move(self.window_at + delta)
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mouseReleaseEvent(event)
        if self.double_release:
            self.double_release = False
        elif self.was_dragged:
            self.station.clamp_position(snap=True)
            self.station.save_settings()
        elif self.press_at is not None:
            self.timer.start(QApplication.styleHints().mouseDoubleClickInterval() + 30)
        self.press_at = None
        event.accept()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.timer.stop()
            self.page_turn.finish()
            self.double_release = True
            self.station.active = self.origin_agent
            self.station.expand()
            event.accept()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.timer.stop()
            self.station.expand()
        elif event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            self.timer.stop()
            self.station.cycle(-1 if event.key() == Qt.Key.Key_Left else 1)
        elif event.key() == Qt.Key.Key_F5:
            self.station.refresh()
        else:
            super().keyPressEvent(event)


class Paper(QFrame):
    def __init__(self, station):
        super().__init__()
        self.station = station
        self.press_at = None
        self.setObjectName('paper')
        self.setStyleSheet(f'QFrame#paper{{background:{PAPER};border:1px solid {LINE};border-radius:22px;}}')
        self.setFixedWidth(332)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.press_at = event.globalPosition().toPoint()
            self.window_at = self.station.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.press_at is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.station.move(self.window_at + event.globalPosition().toPoint() - self.press_at)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.press_at = None
        self.station.clamp_position(snap=True)
        self.station.save_settings()
        super().mouseReleaseEvent(event)


class Station(QWidget):
    def __init__(self, offline=False):
        super().__init__()
        self.offline = offline
        settings = read_json(STATE / 'settings.json', {})
        if not isinstance(settings, dict):
            settings = {}
        native_keys = native_source_keys()
        self.sources = {i: {'id': i, 'name': NAMES[i], 'origin': '本机直连', 'color': COLORS[i],
                            'account': '', 'plan': '', 'available': True}
                        for i in native_keys}
        saved_sources = read_json(STATE / 'sources.json', [])
        for source in saved_sources if isinstance(saved_sources, list) else []:
            if isinstance(source, dict) and isinstance(source.get('id'), str) and source['id'].startswith('magpie:') and source.get('origin') == 'Magpie' and isinstance(source.get('name'), str):
                self.sources[source['id']] = source
        chosen = settings.get('visible_sources', native_keys)
        self.visible_sources = []
        for key in chosen if isinstance(chosen, list) else native_keys:
            if isinstance(key, (int, str)) and not isinstance(key, bool) and key in self.sources and key not in self.visible_sources:
                self.visible_sources.append(key)
        self.active = 0  # Launch with the first selected source; collapse preserves selection.
        self.shape = settings.get('shape', 'card') if settings.get('shape') in ('card', 'ball') else 'card'
        saved_scale = settings.get('mini_scale', 1.0)
        self.mini_scale = max(0.8, min(2.0, float(saved_scale))) if isinstance(saved_scale, (int, float)) and not isinstance(saved_scale, bool) and math.isfinite(saved_scale) else 1.0
        self.expanded = False
        self.topmost = settings.get('topmost', True)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle('额度小站')
        self.setWindowIcon(icon())
        self.setStyleSheet(f'QToolTip{{background:{PAPER};color:{TEXT};border:1px solid {LINE};padding:8px;}} QMenu{{background:{PAPER};color:{TEXT};padding:7px;border:1px solid {LINE};}} QMenu::item{{padding:7px 22px;}} QMenu::item:selected{{background:{SOFT};}}')
        self.snapshots = {}
        cached_balances = read_json(STATE / 'balances.json', {})
        for key, value in cached_balances.items() if isinstance(cached_balances, dict) else []:
            try:
                source_key = int(key) if key in ('0', '1', '2') else key
                if source_key in self.sources:
                    self.snapshots[source_key] = validate_snapshot(value)
            except (ValueError, TypeError, KeyError):
                pass
        self.errors = {}
        self.busy = set()
        self.magpie_busy = False
        self.magpie_syncing = False
        self.magpie_error = ''
        connection = settings.get('magpie_connection', {})
        self.magpie_connection = connection if isinstance(connection, dict) else {}
        self.magpie_sync_message = ''
        self.selection_error = ''
        self.source_picker = None
        self.bridge = Bridge()
        self.bridge.result.connect(self.receive)
        self.bridge.sources.connect(self.receive_sources)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 14)
        outer.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)
        self.mini = MiniButton(self)
        self.paper = Paper(self)
        outer.addWidget(self.mini)
        outer.addWidget(self.paper)
        for widget in (self.mini, self.paper):
            effect = QGraphicsDropShadowEffect(widget)
            effect.setBlurRadius(22)
            effect.setOffset(0, 5)
            effect.setColor(QColor(30, 50, 34, 35))
            widget.setGraphicsEffect(effect)
        self.build_paper()
        self.paper.hide()
        self.tray = QSystemTrayIcon(icon(), self)
        self.menu = QMenu(self)
        self.menu.addAction('显示额度小站', self.reveal)
        self.menu.addAction('展开全部额度', self.expand)
        self.menu.addAction('显示来源…', self.show_sources)
        self.menu.addAction('立即刷新', self.refresh)
        self.menu.addAction('恢复小卡片默认大小', lambda: self.set_mini_scale(1.0, persist=True))
        self.menu.addSeparator()
        self.top_action = self.menu.addAction('总在最前')
        self.top_action.setCheckable(True)
        self.top_action.setChecked(self.topmost)
        self.top_action.triggered.connect(self.toggle_topmost)
        self.menu.addAction('隐藏到托盘', self.hide)
        self.menu.addAction('退出', self.quit)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self.tray_activated)
        self.tray.show()
        self.render()
        self.layout().activate()
        area = QApplication.primaryScreen().availableGeometry()
        self.move(int(settings.get('x', area.right() - 210)), int(settings.get('y', area.top() + 100)))
        self.clamp_position()
        if not self.topmost:
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
        self.poll = QTimer(self)
        self.poll.timeout.connect(self.refresh)
        self.poll.start(300_000)
        self.clock = QTimer(self)
        self.clock.timeout.connect(self.render)
        self.clock.start(60_000)
        if not offline:
            QTimer.singleShot(350, self.refresh)

    def build_paper(self):
        box = QVBoxLayout(self.paper)
        box.setContentsMargins(20, 19, 20, 16)
        box.setSpacing(0)
        head = QHBoxLayout()
        text = QVBoxLayout()
        text.addWidget(label('额度小站', 15, bold=True))
        head.addLayout(text)
        head.addStretch()
        self.close_button = QPushButton('↙')
        self.close_button.setAccessibleName('收起额度详情')
        self.close_button.setToolTip('收起（Esc）')
        self.close_button.setFixedSize(34, 34)
        self.close_button.clicked.connect(self.collapse)
        self.close_button.setStyleSheet(f'QPushButton{{background:{SOFT};border:0;border-radius:10px;font-size:18px;color:{TEXT};}} QPushButton:hover{{background:{LINE};}}')
        head.addWidget(self.close_button)
        box.addLayout(head)
        box.addSpacing(10)
        self.row_scroll = QScrollArea()
        self.row_scroll.setWidgetResizable(True)
        self.row_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.row_scroll.setStyleSheet(f'QScrollArea{{border:0;background:transparent;}} QScrollBar:vertical{{width:5px;background:transparent;}} QScrollBar::handle:vertical{{background:{LINE};border-radius:2px;min-height:20px;}} QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0;}}')
        box.addWidget(self.row_scroll)
        self.rebuild_rows()
        bottom = QHBoxLayout()
        self.last_updated = label('每 5 分钟自动更新', 10, MUTED)
        bottom.addWidget(self.last_updated)
        bottom.addStretch()
        self.refresh_button = QPushButton('刷新')
        self.refresh_button.setAccessibleName('立即刷新全部额度')
        self.refresh_button.setStyleSheet(f'QPushButton{{border:0;background:transparent;color:{MUTED};font-size:11px;padding:5px 2px;}} QPushButton:hover{{color:{COLORS[0]};}}')
        self.refresh_button.clicked.connect(self.refresh)
        bottom.addWidget(self.refresh_button)
        box.addLayout(bottom)
        box.addSpacing(9)
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f'background:{LINE};border:0;')
        box.addWidget(line)
        box.addSpacing(12)
        settings = QHBoxLayout()
        self.sources_button = QPushButton('显示来源')
        self.sources_button.setAccessibleName('选择显示的 Agent 额度来源')
        self.sources_button.setStyleSheet(f'QPushButton{{border:0;background:transparent;color:{COLORS[0]};font-size:12px;padding:6px 0;}} QPushButton:hover{{color:{TEXT};}}')
        self.sources_button.clicked.connect(self.show_sources)
        settings.addWidget(self.sources_button)
        settings.addStretch()
        self.shape_buttons = {}
        for key, caption in [('card', '小卡片'), ('ball', '悬浮球')]:
            button = QPushButton(caption)
            button.setCheckable(True)
            button.setStyleSheet(f'QPushButton{{border:0;background:transparent;color:{MUTED};border-radius:8px;font-size:11px;padding:6px 9px;}} QPushButton:checked{{background:{SOFT};color:{TEXT};}}')
            button.clicked.connect(lambda _checked=False, k=key: self.set_shape(k))
            settings.addWidget(button)
            self.shape_buttons[key] = button
        box.addLayout(settings)

    @property
    def active_key(self):
        return self.visible_sources[self.active] if self.visible_sources else None

    def source_name(self, key):
        return self.sources.get(key, {}).get('name', '额度小站')

    def source_color(self, key):
        return self.sources.get(key, {}).get('color', COLORS[0])

    def rebuild_rows(self):
        self.rows = []
        self.row_keys = list(self.visible_sources)
        content = QWidget()
        content.setStyleSheet('background:transparent;')
        box = QVBoxLayout(content)
        box.setContentsMargins(0, 0, 6, 0)
        box.setSpacing(0)
        for i, key in enumerate(self.row_keys):
            meta = self.sources[key]
            color = self.source_color(key)
            row = QWidget()
            layout = QVBoxLayout(row)
            layout.setContentsMargins(0, 13, 0, 13)
            layout.setSpacing(7)
            top = QHBoxLayout()
            top.setSpacing(7)
            top.addWidget(label('●', 10, color))
            name_label = label(meta['name'], 13)
            top.addWidget(name_label, 1)
            value = label('—', 20, bold=True)
            top.addWidget(value)
            layout.addLayout(top)
            if meta['origin'] == 'Magpie':
                identity = label(meta.get('account') or 'Magpie', 10, MUTED)
                identity.setWordWrap(True)
                layout.addWidget(identity)
            progress = QProgressBar()
            progress.setRange(0, 1000)
            progress.setTextVisible(False)
            progress.setFixedHeight(4)
            progress.setStyleSheet(f'QProgressBar{{border:0;background:{SOFT};border-radius:2px;}} QProgressBar::chunk{{background:{color};border-radius:2px;}}')
            progress.hide()
            layout.addWidget(progress)
            info = QHBoxLayout()
            left, right = label('正在连接', 11, MUTED), label('', 10, MUTED)
            info.addWidget(left)
            info.addStretch()
            info.addWidget(right)
            layout.addLayout(info)
            row.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            row.customContextMenuRequested.connect(lambda _p, source=key: self.show_details(source))
            box.addWidget(row)
            self.rows.append((row, value, left, right, progress))
            if i < len(self.row_keys) - 1:
                line = QFrame()
                line.setFixedHeight(1)
                line.setStyleSheet(f'background:{LINE};border:0;')
                box.addWidget(line)
        if not self.rows:
            empty = QPushButton('选择显示来源')
            empty.setStyleSheet(f'border:0;background:{SOFT};color:{COLORS[0]};border-radius:10px;padding:18px;')
            empty.clicked.connect(self.show_sources)
            box.addWidget(empty)
        box.addStretch()
        self.row_scroll.setWidget(content)

    def fit_rows(self):
        content = self.row_scroll.widget()
        content.layout().activate()
        area = (QApplication.screenAt(self.frameGeometry().center()) or QApplication.primaryScreen()).availableGeometry()
        self.row_scroll.setFixedHeight(min(max(60, content.sizeHint().height()), max(100, min(450, area.height() - 200))))

    def render(self):
        key = self.active_key
        data = self.snapshots.get(key)
        name, color = self.source_name(key), self.source_color(key)
        scale = self.mini_scale
        px = lambda value: max(1, round(value * scale))
        radius = px(62 if self.shape == 'ball' else 29)
        self.mini.setFixedSize(px(124 if self.shape == 'ball' else 138), px(124 if self.shape == 'ball' else 116))
        self.mini.layout().setContentsMargins(px(8), px(11), px(8), px(10))
        self.mini.layout().setSpacing(px(3))
        self.mini.resize_grip.setVisible(self.shape == 'card')
        self.mini.layout_resize_grip()
        self.mini.setStyleSheet(f'QPushButton{{background:{PAPER};border:1px solid {LINE};border-radius:{radius}px;}} QPushButton:focus{{border-color:#b1c9b8;}}')
        self.mini.name.setText('● ' + name)
        self.mini.name.setStyleSheet(f'color:{color};font-size:{px(12)}px;border:0;background:transparent;')
        self.mini.value.setText(number_text(data))
        self.mini.value.setStyleSheet(f'color:{TEXT};font-size:{px(25 if len(number_text(data)) > 5 else 29)}px;font-weight:600;border:0;background:transparent;')
        unit = data.get('subtitle', '剩余额度') if data else ('正在连接' if key in self.busy else '待连接')
        self.mini.unit.setText(unit if key not in self.errors else ('上次余额' if data else '待连接'))
        if key is None:
            self.mini.unit.setText('选择显示来源')
        self.mini.unit.setStyleSheet(f'color:{MUTED};font-size:{px(11)}px;border:0;background:transparent;')
        count = len(self.visible_sources)
        self.mini.dots.setText(' '.join('●' if i == self.active else '·' for i in range(count)) if count <= 6 else f'{self.active + 1} / {count}')
        self.mini.dots.setStyleSheet(f'color:{color};font-size:{px(11)}px;border:0;background:transparent;')
        click_hint = '左侧上一页 · 右侧下一页' if self.shape == 'card' else '单击切换'
        self.mini.setAccessibleName(f'{name} {unit} {number_text(data)}，{click_hint}，双击展开')
        self.mini.setToolTip(self.details_text(key) + '\n\n' + click_hint + ' · 双击展开\n拖动调整位置 · 右键菜单 · Enter 展开 · 左右键切换')
        for i, (row, value, left, right, progress) in zip(self.row_keys, self.rows):
            item = self.snapshots.get(i)
            value.setText(number_text(item))
            left.setText(item.get('subtitle', '剩余额度') if item else ('正在连接' if i in self.busy else '待连接'))
            if i in self.errors:
                right.setText('更新失败' if item else '待连接')
                left.setText('上次余额' if item else '暂不可用')
            elif i in self.busy:
                right.setText('更新中…')
            elif item:
                reset = item.get('reset_at')
                right.setText(time.strftime('%m-%d %H:%M', time.localtime(reset)) + ' 重置' if reset else age_text(item.get('updated_at')))
            else:
                right.setText('')
            percent = item.get('remaining_percent', item.get('balance') if item.get('unit') == '%' else None) if item else None
            progress.setVisible(isinstance(percent, (int, float)))
            if isinstance(percent, (int, float)):
                progress.setValue(round(percent * 10))
            row.setToolTip(self.details_text(i) + '\n右键查看详情')
        refreshing = bool(self.busy or self.magpie_busy)
        self.refresh_button.setEnabled(not refreshing)
        self.refresh_button.setText('更新中' if refreshing else '刷新')
        failed = any(key in self.errors for key in self.visible_sources)
        self.last_updated.setText('部分来源待连接' if failed else ('每 5 分钟自动更新' if count else '尚未选择来源'))
        for shape_key, button in self.shape_buttons.items():
            button.setChecked(shape_key == self.shape)
        self.tray.setToolTip(('额度小站\n' + '\n'.join(f'{self.source_name(key)}  {number_text(self.snapshots.get(key))}' for key in self.visible_sources))[:120])
        self.fit_rows()
        if self.source_picker:
            self.source_picker.sync()
        try:
            atomic_json(STATE / 'runtime.json', {'pid': os.getpid(), 'active': name, 'active_source': key, 'expanded': self.expanded, 'shape': self.shape, 'mini_scale': self.mini_scale, 'busy': sorted(self.busy), 'magpie_busy': self.magpie_busy, 'errors': self.errors, 'visible': self.isVisible(), 'geometry': [self.x(), self.y(), self.width(), self.height()]})
        except OSError:
            pass

    def details_text(self, i):
        item = self.snapshots.get(i)
        lines = [self.source_name(i)]
        if i in self.sources:
            lines.append('来源：' + self.sources[i]['origin'])
        if item:
            lines.append(f'{item.get("subtitle", "剩余额度")}：{number_text(item)}' + (f' {item.get("unit", "")}' if item.get('unit') != '%' else ''))
            lines.append('成功更新：' + time.strftime('%m-%d %H:%M:%S', time.localtime(item['updated_at'])))
            for detail in item.get('details', []):
                if isinstance(detail, dict):
                    lines.append(f'{detail.get("label", "")}：{detail.get("value", "")}')
        if i in self.errors:
            lines.append(self.errors[i])
        return '\n'.join(lines)

    def refresh(self):
        if self.offline:
            return
        self.refresh_native()
        self.refresh_sources()

    def refresh_native(self):
        if self.offline:
            return
        for i, module in enumerate(('codex_provider', 'qoder_provider', 'workbuddy_provider')):
            if i not in self.visible_sources or i in self.busy:
                continue
            self.busy.add(i)
            def run(index=i, provider=module):
                try:
                    result = validate_snapshot(importlib.import_module('providers.' + provider).fetch())
                    self.bridge.result.emit(index, result, '')
                except Exception as exc:
                    # Adapters raise safe, user-facing errors; never log raw response bodies.
                    message = str(exc) if isinstance(exc, (RuntimeError, ValueError)) else '连接暂不可用，请打开对应客户端并登录后刷新'
                    if any(s in message.lower() for s in ('bearer ', 'token=', 'eyj', 'authorization')):
                        message = '登录连接暂不可用，请打开对应客户端并登录后刷新'
                    self.bridge.result.emit(index, None, message[:160])
            threading.Thread(target=run, daemon=True, name=f'quota-{module}').start()
        self.render()

    def sync_magpie(self):
        self.refresh_sources(synchronize=True)

    def refresh_sources(self, synchronize=False):
        if self.offline or self.magpie_busy:
            return
        self.magpie_busy = True
        self.magpie_syncing = synchronize
        self.magpie_sync_message = ''
        if synchronize:
            self.magpie_error = ''
        connection = dict(self.magpie_connection)
        def run():
            try:
                from providers.magpie_provider import fetch, synchronize as sync_sources
                result = sync_sources(connection) if synchronize else fetch(connection)
                self.bridge.sources.emit(result, '')
            except Exception as exc:
                message = str(exc) if isinstance(exc, RuntimeError) else 'Magpie 暂时无法连接'
                discovered = getattr(exc, 'connection', None)
                self.bridge.sources.emit({'connection': discovered} if isinstance(discovered, dict) else None, message)
        threading.Thread(target=run, daemon=True, name='quota-magpie').start()
        self.render()

    def receive_sources(self, sources, error):
        was_syncing = self.magpie_syncing
        self.magpie_busy = False
        self.magpie_syncing = False
        self.magpie_error = error
        if isinstance(sources, dict):
            connection = sources.get('connection')
            if isinstance(connection, dict):
                allowed = ('executable', 'port', 'version', 'transport', 'synced_at', 'source_count', 'readable_count')
                self.magpie_connection = {key: connection[key] for key in allowed if key in connection}
                if not self.save_settings():
                    self.selection_error = 'Magpie 连接设置尚未保存，请检查 state 目录权限'
            sources = sources.get('sources', [])
        if was_syncing:
            if error:
                self.magpie_sync_message = ''
            else:
                unavailable = sum(bool(source.get('error')) for source in sources)
                self.magpie_sync_message = f'已同步 {len(sources)} 个来源' + (f' · {unavailable} 个暂不可用' if unavailable else '')
        previous_catalog = [(key, meta.get('name'), meta.get('account')) for key, meta in self.sources.items()]
        if error:
            for key, meta in self.sources.items():
                if meta['origin'] == 'Magpie':
                    self.errors[key] = error
        else:
            seen = set()
            for source in sources:
                key = source['id']
                seen.add(key)
                self.sources[key] = {k: v for k, v in source.items() if k not in ('snapshot', 'error')}
                self.sources[key]['available'] = True
                if source.get('error'):
                    self.errors[key] = source['error']
                else:
                    try:
                        self.snapshots[key] = validate_snapshot(source['snapshot'])
                        self.errors.pop(key, None)
                    except (ValueError, TypeError, KeyError):
                        self.errors[key] = 'Magpie 暂未提供可确认的额度'
            for key, meta in self.sources.items():
                if meta['origin'] == 'Magpie' and key not in seen:
                    meta['available'] = False
                    self.errors[key] = 'Magpie 当前未返回此账号，请检查 Magpie 中的连接'
            try:
                atomic_json(STATE / 'sources.json', [meta for meta in self.sources.values() if meta['origin'] == 'Magpie'])
                atomic_json(STATE / 'balances.json', self.snapshots)
            except OSError:
                self.selection_error = '本地缓存未能保存，请检查 state 目录权限'
        current_catalog = [(key, meta.get('name'), meta.get('account')) for key, meta in self.sources.items()]
        if previous_catalog != current_catalog:
            self.rebuild_rows()
        self.render()
        self.layout().activate()
        self.clamp_position()

    def set_source_visible(self, key, checked):
        if key not in self.sources:
            return
        self.mini.timer.stop()
        self.mini.page_turn.finish()
        previous = self.active_key
        if checked and key not in self.visible_sources:
            self.visible_sources.append(key)
        elif not checked and key in self.visible_sources:
            self.visible_sources.remove(key)
        self.active = self.visible_sources.index(previous) if previous in self.visible_sources else 0
        self.mini.origin_agent = self.active
        self.rebuild_rows()
        self.selection_error = '' if self.save_settings() else '选择尚未保存，请检查 state 目录权限'
        self.render()
        self.layout().activate()
        self.clamp_position()
        if checked and key not in self.snapshots:
            if isinstance(key, int):
                self.refresh_native()
            else:
                self.refresh_sources()

    def show_sources(self):
        self.mini.timer.stop()
        self.mini.page_turn.finish()
        if self.source_picker is None:
            self.source_picker = SourcePicker(self)
            area = (QApplication.screenAt(self.frameGeometry().center()) or QApplication.primaryScreen()).availableGeometry()
            self.source_picker.resize(min(480, area.width() - 48), min(650, area.height() - 72))
            self.source_picker.move(area.center() - self.source_picker.rect().center())
        self.source_picker.sync()
        if self.source_picker.isMinimized():
            self.source_picker.showNormal()
        else:
            self.source_picker.show()
        self.source_picker.raise_()
        self.source_picker.activateWindow()
        if not any(meta['origin'] == 'Magpie' for meta in self.sources.values()):
            self.refresh_sources()

    def receive(self, index, data, error):
        self.busy.discard(index)
        if error:
            self.errors[index] = error
        else:
            self.errors.pop(index, None)
            self.snapshots[index] = data
            try:
                atomic_json(STATE / 'balances.json', self.snapshots)
            except OSError:
                pass
        self.render()
        self.layout().activate()
        self.clamp_position()

    def cycle(self, offset):
        self.mini.page_turn.finish()
        target = (self.active + offset) % len(self.visible_sources) if self.visible_sources else 0
        animate = target != self.active and self.shape == 'card' and self.mini.isVisible()
        before = self.mini.grab() if animate else None
        self.active = target
        self.render()
        if animate:
            self.mini.layout().activate()
            after = self.mini.grab()
            self.mini.page_turn.start(before, after, offset, round(29 * self.mini_scale))

    def expand(self):
        self.mini.timer.stop()
        self.mini.page_turn.finish()
        self.expanded = True
        self.mini.hide()
        self.paper.show()
        self.render()
        self.layout().activate()
        self.clamp_position()
        self.show()
        self.raise_()
        self.close_button.setFocus()

    def collapse(self):
        self.expanded = False
        self.paper.hide()
        self.mini.show()
        self.render()
        self.layout().activate()
        self.clamp_position()
        self.mini.setFocus()
        self.save_settings()

    def set_shape(self, shape):
        self.mini.page_turn.finish()
        self.shape = shape
        self.render()
        self.save_settings()

    def set_mini_scale(self, value, persist=False, clamp=True):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            return
        self.mini.page_turn.finish()
        self.mini_scale = max(0.8, min(2.0, float(value)))
        self.render()
        self.layout().activate()
        if clamp:
            self.clamp_position()
        if persist:
            self.save_settings()

    def clamp_position(self, snap=False):
        screen = QApplication.screenAt(self.frameGeometry().center()) or QApplication.primaryScreen()
        area = screen.availableGeometry()
        x = max(area.left(), min(self.x(), area.right() - self.width() + 1))
        y = max(area.top(), min(self.y(), area.bottom() - self.height() + 1))
        if snap:
            if x - area.left() < 24:
                x = area.left()
            if area.right() - x - self.width() < 24:
                x = area.right() - self.width() + 1
        self.move(x, y)

    def save_settings(self):
        try:
            atomic_json(STATE / 'settings.json', {'shape': self.shape, 'mini_scale': self.mini_scale, 'topmost': self.topmost, 'x': self.x(), 'y': self.y(), 'visible_sources': self.visible_sources, 'magpie_connection': self.magpie_connection})
            return True
        except OSError:
            return False

    def reveal(self):
        self.clamp_position()
        self.show()
        self.raise_()
        self.activateWindow()

    def toggle_topmost(self, enabled):
        self.topmost = bool(enabled)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self.topmost)
        self.show()
        if self.source_picker:
            picker_visible = self.source_picker.isVisible()
            self.source_picker.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self.topmost)
            if picker_visible:
                self.source_picker.show()
        self.save_settings()

    def tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.reveal()

    def contextMenuEvent(self, event):
        self.mini.timer.stop()
        self.menu.popup(event.globalPos())

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.collapse()
        elif event.key() == Qt.Key.Key_F5:
            self.refresh()
        else:
            super().keyPressEvent(event)

    def show_details(self, index):
        QMessageBox.information(self, self.source_name(index) + ' · 额度详情', self.details_text(index))

    def quit(self):
        self.save_settings()
        self.tray.hide()
        QApplication.quit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', action='version', version=__version__)
    parser.add_argument('--smoke-test', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--offline', action='store_true', help='Show cached data without querying providers')
    parser.add_argument('--expanded', action='store_true')
    parser.add_argument('--sources', action='store_true', help='Open the quota source selection page')
    parser.add_argument('--qa-window', action='store_true', help='Expose a normal window for native accessibility verification')
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    app.setApplicationName('额度小站')
    app.setOrganizationName('QuotaStation')
    app.setQuitOnLastWindowClosed(False)
    setup_fonts(app)
    if args.smoke_test:
        from packaged_smoke import run
        return run(app, args.smoke_test)
    # Match Windows' own double-click speed, including accessibility preferences.
    if os.name == 'nt':
        app.setDoubleClickInterval(ctypes.windll.user32.GetDoubleClickTime())
    socket = QLocalSocket()
    socket.connectToServer('QuotaStation_v1')
    if socket.waitForConnected(400):
        socket.write(b'sources' if args.sources else b'expanded' if args.expanded else b'show')
        socket.waitForBytesWritten(400)
        return 0
    QLocalServer.removeServer('QuotaStation_v1')
    server = QLocalServer()
    if not server.listen('QuotaStation_v1'):
        return 1
    station = Station(offline=args.offline)
    if args.qa_window:
        station.setWindowFlag(Qt.WindowType.Tool, False)
        station.setWindowFlag(Qt.WindowType.Window, True)
    def incoming():
        connection = server.nextPendingConnection()
        command = b'show'
        if connection:
            if not connection.bytesAvailable():
                connection.waitForReadyRead(250)
            command = bytes(connection.readAll())
            connection.close()
            connection.deleteLater()
        if command == b'sources':
            station.show_sources()
        elif command == b'expanded':
            station.expand()
        else:
            station.reveal()
    server.newConnection.connect(incoming)
    station.show()
    if args.expanded:
        station.expand()
    if args.sources:
        station.show_sources()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
