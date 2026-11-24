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
from PySide6.QtGui import QActionGroup, QColor, QFont, QFontDatabase, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
    QLayout, QMenu, QMessageBox, QProgressBar, QPushButton, QScrollArea, QSystemTrayIcon,
    QVBoxLayout, QWidget,
)

from source_picker import SourcePicker
from page_turn import PageTurn
from edge_dock import EdgeDock, nearest_screen
from updater_ui import UpdateController
from runtime_paths import data_root, native_source_keys, resource_root
from providers import workbuddy_provider as workbuddy
from providers import antigravity_provider as antigravity
from workbuddy_watch import WorkBuddyAccountWatch
from version import __version__
import i18n
from i18n import tr, pair

BASE = resource_root()
STATE = data_root() / 'state'
NAMES = ['Codex', 'Qoder', 'WorkBuddy', 'Antigravity']
COLORS = ['#458068', '#8170a7', '#ad7a44', '#5677ad']
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
    data = antigravity.display_snapshot(data)
    if data.get('source') in ('magpie', 'workbuddy') and data.get('quota_state') == 'unlimited' and data.get('balance') is None:
        return data
    value = data.get('balance')
    money = data.get('source') == 'magpie' and data.get('kind') == 'balance' and data.get('unit') in ('$', '¥', '€', '£', '元', 'USD', 'CNY', 'EUR', 'GBP')
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or (value < 0 and not money):
        raise ValueError('未返回可确认的剩余额度')
    if data.get('unit') == '%' and value > 100:
        raise ValueError('剩余百分比超出范围')
    return data


def number_text(data):
    if not data or data.get('balance') is None and data.get('quota_state') != 'unlimited':
        return '—'
    if data.get('quota_state') == 'unlimited':
        return tr('不限量')
    value = data['balance']
    if data.get('unit') == '%':
        return f'{value:,.0f}%'
    if data.get('unit') in ('$', '¥', '€', '£'):
        return f'{data["unit"]}{value:,.2f}'
    # Keep fractional credits visible while avoiding noisy precision.
    return f'{value:,.2f}'.rstrip('0').rstrip('.') if value % 1 else f'{value:,.0f}'


def age_text(timestamp):
    if not timestamp:
        return tr('尚未更新')
    age = max(0, time.time() - float(timestamp))
    if age < 60:
        return tr('刚刚更新')
    if age < 3600:
        return tr('{count} 分钟前', count=int(age // 60))
    if age < 86400:
        return tr('{count} 小时前', count=int(age // 3600))
    return time.strftime('%m-%d %H:%M', time.localtime(timestamp))


def label(text='', size=12, color=TEXT, bold=False):
    item = QLabel(text)
    item.setStyleSheet(f'color:{color};font-size:{size}px;font-weight:{600 if bold else 400};background:transparent;border:0;')
    item.setTextFormat(Qt.TextFormat.PlainText)
    item.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    return item


class WeeklyQuotas(QWidget):
    """Two aligned quota readings, kept separate at every card size."""
    def __init__(self):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setStyleSheet('background:transparent;border:0;')
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        self.readings = []
        for model in antigravity.WEEKLY_MODELS:
            row = QHBoxLayout()
            row.setSpacing(4)
            name, value = label(model), label('—', bold=True)
            row.addWidget(name)
            row.addStretch()
            row.addWidget(value)
            box.addLayout(row)
            self.readings.append((name, value))
        self.hide()

    def sync(self, quotas, scale=1.0, compact=False):
        self.setVisible(bool(quotas))
        for (name, value), item in zip(self.readings, quotas):
            name.setText(tr(item['model']))
            name.setStyleSheet(f'color:{MUTED};font-size:{round((11 if compact else 13) * scale)}px;background:transparent;border:0;')
            value.setStyleSheet(f'color:{TEXT};font-size:{round((15 if compact else 18) * scale)}px;font-weight:600;background:transparent;border:0;')
            value.setText(number_text(item))
        if quotas:
            for pair in self.readings:
                for field in pair:
                    field.ensurePolished()
            self.setFixedHeight(sum(max(name.sizeHint().height(), value.sizeHint().height())
                                    for name, value in self.readings))


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
    for i, color in enumerate(COLORS[:3]):
        p.setBrush(QColor(color))
        p.drawRoundedRect(QRectF(30, 32 + i * 24, 68 - i * 14, 10), 5, 5)
    p.end()
    return QIcon(pix)


class Bridge(QObject):
    result = Signal(int, object, str, int)
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
            self.station.docking.detach_for_drag()
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
            self.station.docking._passive(False)
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
        self.weekly = WeeklyQuotas()
        self.unit = label('正在连接', 11, MUTED)
        self.dots = label('● · ·', 11, COLORS[0])
        for item in (self.name, self.value, self.weekly, self.unit, self.dots):
            if isinstance(item, QLabel):
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
                self.station.docking.detach_for_drag()
                self.station.move(self.window_at + delta)
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mouseReleaseEvent(event)
        if self.double_release:
            self.double_release = False
        elif self.was_dragged:
            self.station.docking.finish_drag(event.globalPosition().toPoint())
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
        self.was_dragged = False
        self.setObjectName('paper')
        self.setStyleSheet(f'QFrame#paper{{background:{PAPER};border:1px solid {LINE};border-radius:22px;}}')
        self.setFixedWidth(332)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.press_at = event.globalPosition().toPoint()
            self.window_at = self.station.pos()
            self.was_dragged = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.press_at is not None and event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.globalPosition().toPoint() - self.press_at
            if delta.manhattanLength() >= QApplication.startDragDistance():
                self.was_dragged = True
            if self.was_dragged:
                self.station.move(self.window_at + delta)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.press_at is not None and self.was_dragged:
            self.station.docking.finish_drag(event.globalPosition().toPoint())
        self.press_at = None
        super().mouseReleaseEvent(event)


class Station(QWidget):
    def __init__(self, offline=False):
        super().__init__()
        self.offline = offline
        settings = read_json(STATE / 'settings.json', {})
        if not isinstance(settings, dict):
            settings = {}
        self.language = i18n.set_language(settings.get('language', 'auto'))
        self.antigravity_display = settings.get('antigravity_display', 'weekly')
        if self.antigravity_display not in ('weekly', 'weekly_5h'):
            self.antigravity_display = 'weekly'
        native_keys = native_source_keys()
        self.sources = {i: {'id': i, 'name': NAMES[i], 'origin': '本机直连', 'color': COLORS[i],
                            'account': '', 'plan': '', 'available': True}
                        for i in native_keys}
        saved_sources = read_json(STATE / 'sources.json', [])
        for source in saved_sources if isinstance(saved_sources, list) else []:
            if isinstance(source, dict) and isinstance(source.get('id'), str) and source['id'].startswith('magpie:') and source.get('origin') == 'Magpie' and isinstance(source.get('name'), str):
                self.sources[source['id']] = source
        default_keys = [key for key in native_keys if key != 3]
        chosen = settings.get('visible_sources', default_keys)
        self.visible_sources = []
        for key in chosen if isinstance(chosen, list) else default_keys:
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
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)
        self.setWindowTitle('额度小站')
        self.setWindowIcon(icon())
        self.setStyleSheet(f'QToolTip{{background:{PAPER};color:{TEXT};border:1px solid {LINE};padding:8px;}} QMenu{{background:{PAPER};color:{TEXT};padding:7px;border:1px solid {LINE};}} QMenu::item{{padding:7px 22px;}} QMenu::item:selected{{background:{SOFT};}}')
        self.snapshots = {}
        self.workbuddy_watch = WorkBuddyAccountWatch(self)
        self.workbuddy_watch.changed.connect(self.workbuddy_file_changed)
        watching_workbuddy = not offline and 2 in self.visible_sources
        if watching_workbuddy:
            self.workbuddy_watch.start(workbuddy.account_snapshot_path())
        self.workbuddy_account = workbuddy.current_account() if watching_workbuddy else None
        self.workbuddy_generation = 0
        self.workbuddy_retry = QTimer(self)
        self.workbuddy_retry.setSingleShot(True)
        self.workbuddy_retry.setInterval(3000)
        self.workbuddy_retry.timeout.connect(lambda: self.refresh_native((2,)))
        cached_balances = read_json(STATE / 'balances.json', {})
        if watching_workbuddy and isinstance(cached_balances, dict) and '2' in cached_balances:
            if not self.matches_workbuddy_account(cached_balances['2']):
                del cached_balances['2']
                try:
                    atomic_json(STATE / 'balances.json', cached_balances)
                except OSError:
                    pass
        for key, value in cached_balances.items() if isinstance(cached_balances, dict) else []:
            try:
                source_key = int(key) if key in ('0', '1', '2', '3') else key
                if source_key in self.sources:
                    self.snapshots[source_key] = validate_snapshot(value)
            except (ValueError, TypeError, KeyError):
                pass
        self.workbuddy_retry_available = self.workbuddy_account is not None and 2 not in self.snapshots
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
        self.docking = EdgeDock(self)
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
        self.menu_text = []
        self.menu_action('显示额度小站', self.reveal)
        self.menu_action('展开全部额度', self.expand)
        self.menu_action('显示来源…', self.show_sources)
        self.menu_action('立即刷新', self.refresh)
        self.antigravity_menu = self.menu.addMenu('Antigravity')
        self.antigravity_display_group = QActionGroup(self)
        self.antigravity_actions = {}
        for mode, caption in [('weekly', '只显示总额度'), ('weekly_5h', '总额度 + 5 小时')]:
            action = self.antigravity_menu.addAction(tr(caption))
            action.setCheckable(True)
            action.triggered.connect(lambda _checked=False, selected=mode: self.set_antigravity_display(selected))
            self.antigravity_display_group.addAction(action)
            self.antigravity_actions[mode] = action
            self.menu_text.append((action, caption))
        self.update_action = self.menu_action('检查更新…')
        self.updater = UpdateController(self, self.update_action)
        self.update_action.triggered.connect(self.updater.show)
        self.menu_action('恢复小卡片默认大小', lambda: self.set_mini_scale(1.0, persist=True))
        self.undock_action = self.menu_action('取消边缘吸附', self.docking.undock)
        self.undock_action.setVisible(False)
        self.language_menu = self.menu.addMenu('Language / 语言')
        self.language_group = QActionGroup(self)
        self.language_actions = {}
        for choice, caption in [('auto', tr('跟随系统')), ('zh-CN', '简体中文'), ('en', 'English')]:
            action = self.language_menu.addAction(caption)
            action.setCheckable(True)
            action.setChecked(choice == self.language)
            action.triggered.connect(lambda _checked=False, selected=choice: self.set_language(selected))
            self.language_group.addAction(action)
            self.language_actions[choice] = action
        self.menu.addSeparator()
        self.top_action = self.menu_action('总在最前')
        self.top_action.setCheckable(True)
        self.top_action.setChecked(self.topmost)
        self.top_action.triggered.connect(self.toggle_topmost)
        self.menu_action('隐藏到托盘', self.hide)
        self.menu_action('退出', self.quit)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self.tray_activated)
        self.tray.show()
        self.retranslate()
        self.render()
        self.layout().activate()
        area = QApplication.primaryScreen().availableGeometry()
        self.move(int(settings.get('x', area.right() - 210)), int(settings.get('y', area.top() + 100)))
        self.clamp_position()
        if not self.topmost:
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
        self.docking.restore(settings.get('edge_dock'))
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
        self.paper_title = label(tr('额度小站'), 15, bold=True)
        text.addWidget(self.paper_title)
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
        return self.sources.get(key, {}).get('name', tr('额度小站'))

    def menu_action(self, text, *args):
        action = self.menu.addAction(tr(text), *args)
        self.menu_text.append((action, text))
        return action

    def retranslate(self):
        self.setWindowTitle(tr('额度小站'))
        self.paper_title.setText(tr('额度小站'))
        self.close_button.setAccessibleName(tr('收起额度详情'))
        self.close_button.setToolTip(tr('收起（Esc）'))
        self.refresh_button.setAccessibleName(tr('立即刷新全部额度'))
        self.sources_button.setText(tr('显示来源'))
        self.sources_button.setAccessibleName(tr('选择显示的 Agent 额度来源'))
        self.mini.resize_grip.setAccessibleName(tr('拖动书页折角缩放小卡片'))
        self.mini.resize_grip.setToolTip(tr('拖住小折角，沿对角线调整大小'))
        for key, text in [('card', '小卡片'), ('ball', '悬浮球')]:
            self.shape_buttons[key].setText(tr(text))
        for action, text in self.menu_text:
            action.setText(tr(text))
        self.language_actions['auto'].setText(tr('跟随系统'))
        for choice, action in self.language_actions.items():
            action.setChecked(choice == self.language)
        self.updater.sync()

    def set_language(self, choice):
        self.mini.timer.stop()
        self.mini.page_turn.finish()
        self.language = i18n.set_language(choice)
        self.retranslate()
        self.rebuild_rows()
        self.selection_error = '' if self.save_settings() else '语言设置尚未保存，请检查 state 目录权限'
        if self.source_picker:
            self.source_picker.signature = None
        self.render()
        self.layout().activate()
        if not self.docking.side:
            self.clamp_position()

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
            row.weekly = WeeklyQuotas()
            layout.addWidget(row.weekly)
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
            left, right = label(tr('正在连接'), 11, MUTED), label('', 10, MUTED)
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
            empty = QPushButton(tr('选择显示来源'))
            empty.setStyleSheet(f'border:0;background:{SOFT};color:{COLORS[0]};border-radius:10px;padding:18px;')
            empty.clicked.connect(self.show_sources)
            box.addWidget(empty)
        box.addStretch()
        self.row_scroll.setWidget(content)

    def fit_rows(self):
        content = self.row_scroll.widget()
        for row, *_ in self.rows:
            row.layout().invalidate()
            row.layout().activate()
            row.updateGeometry()
        content.layout().invalidate()
        content.layout().activate()
        area = (QApplication.screenAt(self.frameGeometry().center()) or QApplication.primaryScreen()).availableGeometry()
        self.row_scroll.setFixedHeight(min(max(60, content.sizeHint().height()), max(100, min(450, area.height() - 200))))

    def showing_cached_quota(self, key):
        return (self.errors.get(key) == antigravity.OFFLINE_MESSAGE
                and self.snapshots.get(key, {}).get('source') == 'antigravity')

    def quota_readings(self, snapshot):
        weekly = antigravity.weekly_quotas(snapshot)
        if self.antigravity_display == 'weekly_5h' and len(weekly) == 1 and weekly[0]['model'] == 'Gemini':
            return antigravity.gemini_windows(snapshot)
        return weekly

    def set_antigravity_display(self, mode):
        if mode not in ('weekly', 'weekly_5h'):
            return
        self.mini.timer.stop()
        self.mini.page_turn.finish()
        self.antigravity_display = mode
        self.render()
        self.layout().activate()
        self.clamp_position()
        self.save_settings()

    def render(self):
        key = self.active_key
        data = self.snapshots.get(key)
        weekly = self.quota_readings(data)
        paired = len(weekly) > 1
        name, color = self.source_name(key), self.source_color(key)
        scale = self.mini_scale
        px = lambda value: max(1, round(value * scale))
        radius = px(124) // 2 if self.shape == 'ball' else px(29)
        self.mini.setFixedSize(px(124 if self.shape == 'ball' else 138), px(124 if self.shape == 'ball' else 116))
        self.mini.layout().setContentsMargins(px(12 if paired else 8), px(8 if paired else 11), px(12 if paired else 8), px(8 if paired else 10))
        self.mini.layout().setSpacing(px(1 if paired else 3))
        self.mini.resize_grip.setVisible(self.shape == 'card')
        self.mini.layout_resize_grip()
        self.mini.setStyleSheet(f'QPushButton{{background:{PAPER};border:1px solid {LINE};border-radius:{radius}px;}} QPushButton:focus{{border-color:#b1c9b8;}}')
        self.mini.name.setText('● ' + name)
        self.mini.name.setStyleSheet(f'color:{color};font-size:{px(12)}px;border:0;background:transparent;')
        self.mini.value.setText(number_text(data))
        self.mini.value.setVisible(not paired)
        self.mini.weekly.sync(weekly if paired else [], scale, compact=True)
        value_size = 25 if len(number_text(data)) > 5 else 29
        self.mini.value.setStyleSheet(f'color:{TEXT};font-size:{px(value_size)}px;font-weight:600;border:0;background:transparent;')
        unit = tr(data.get('subtitle', '剩余额度') if data else ('正在连接' if key in self.busy else '待连接'))
        if weekly and weekly[0]['model'] == '总额度':
            unit = ''
        self.mini.unit.setText(unit if key not in self.errors else tr('上次余额' if data else '待连接'))
        if self.showing_cached_quota(key):
            self.mini.unit.setText(tr('上次读数'))
        if key is None:
            self.mini.unit.setText(tr('选择显示来源'))
        self.mini.unit.setVisible(bool(self.mini.unit.text()))
        self.mini.unit.setStyleSheet(f'color:{MUTED};font-size:{px(11)}px;border:0;background:transparent;')
        count = len(self.visible_sources)
        self.mini.dots.setText(' '.join('●' if i == self.active else '·' for i in range(count)) if count <= 6 else f'{self.active + 1} / {count}')
        self.mini.dots.setStyleSheet(f'color:{color};font-size:{px(11)}px;border:0;background:transparent;')
        click_hint = tr('左侧上一页 · 右侧下一页' if self.shape == 'card' else '单击切换')
        reading = ' · '.join(f'{tr(item["model"])} {number_text(item)}' for item in weekly) if weekly else number_text(data)
        self.mini.setAccessibleName(tr('{name} {unit} {value}，{hint}，双击展开', name=name, unit=unit, value=reading, hint=click_hint))
        self.mini.setToolTip(self.details_text(key) + '\n\n' + click_hint + tr(' · 双击展开\n拖动调整位置 · 右键菜单 · Enter 展开 · 左右键切换'))
        for i, (row, value, left, right, progress) in zip(self.row_keys, self.rows):
            item = self.snapshots.get(i)
            weekly = self.quota_readings(item)
            paired = len(weekly) > 1
            row.weekly.sync(weekly if paired else [])
            value.setText(number_text(item))
            value.setVisible(not paired)
            left.setText(tr(item.get('subtitle', '剩余额度') if item else ('正在连接' if i in self.busy else '待连接')))
            if weekly and weekly[0]['model'] == '总额度':
                left.setText('')
            if i in self.errors:
                if self.showing_cached_quota(i):
                    left.setText(tr('上次读数'))
                    right.setText(age_text(item.get('updated_at')))
                else:
                    right.setText(tr('更新失败' if item else '待连接'))
                    left.setText(tr('上次余额' if item else '暂不可用'))
            elif i in self.busy:
                right.setText(tr('更新中…'))
            elif item:
                reset = item.get('reset_at')
                right.setText(tr('{time} 重置', time=time.strftime('%m-%d %H:%M', time.localtime(reset))) if reset else age_text(item.get('updated_at')))
            else:
                right.setText('')
            left.setVisible(bool(left.text()))
            percent = item.get('remaining_percent', item.get('balance') if item.get('unit') == '%' else None) if item else None
            progress.setVisible(not paired and isinstance(percent, (int, float)))
            if isinstance(percent, (int, float)):
                progress.setValue(round(percent * 10))
            row.setToolTip(self.details_text(i) + tr('\n右键查看详情'))
        refreshing = bool(self.busy or self.magpie_busy)
        self.refresh_button.setEnabled(not refreshing)
        self.refresh_button.setText(tr('更新中' if refreshing else '刷新'))
        failed = any(key in self.errors and not self.showing_cached_quota(key) for key in self.visible_sources)
        cached = any(self.showing_cached_quota(key) for key in self.visible_sources)
        self.last_updated.setText(tr('部分来源待连接' if failed else '部分来源显示上次读数' if cached else
                                     '每 5 分钟自动更新' if count else '尚未选择来源'))
        for shape_key, button in self.shape_buttons.items():
            button.setChecked(shape_key == self.shape)
        self.antigravity_menu.menuAction().setVisible(3 in self.visible_sources)
        pools = antigravity.weekly_quotas(self.snapshots.get(3))
        self.antigravity_menu.menuAction().setEnabled(not pools or (len(pools) == 1 and pools[0]['model'] == 'Gemini'))
        for mode, action in self.antigravity_actions.items():
            action.setChecked(mode == self.antigravity_display)
        self.tray.setToolTip((tr('额度小站') + '\n' + '\n'.join(f'{self.source_name(key)}  {number_text(self.snapshots.get(key))}' for key in self.visible_sources))[:120])
        self.fit_rows()
        if self.source_picker:
            self.source_picker.sync()
        self.docking.bar.sync()
        self.write_runtime()

    def write_runtime(self):
        try:
            atomic_json(STATE / 'runtime.json', {'pid': os.getpid(), 'active': self.source_name(self.active_key), 'active_source': self.active_key, 'expanded': self.expanded, 'shape': self.shape, 'mini_scale': self.mini_scale, 'busy': sorted(self.busy), 'magpie_busy': self.magpie_busy, 'errors': self.errors, 'visible': self.isVisible(), 'geometry': [self.x(), self.y(), self.width(), self.height()], 'docked': self.docking.side, 'dock_peek': self.docking.peeked, 'language': self.language, 'resolved_language': i18n.language()})
        except OSError:
            pass

    def details_text(self, i):
        item = self.snapshots.get(i)
        lines = [self.source_name(i)]
        if i in self.sources:
            lines.append(tr('来源：') + tr(self.sources[i]['origin']))
        if item:
            if item.get('source') != 'antigravity':
                lines.append(pair(tr(item.get('subtitle', '剩余额度')), number_text(item)) + (f' {tr(item.get("unit", ""))}' if item.get('unit') != '%' else ''))
            lines.append(tr('成功更新：') + time.strftime('%m-%d %H:%M:%S', time.localtime(item['updated_at'])))
            for detail in item.get('details', []):
                if isinstance(detail, dict):
                    value = detail.get('value', '')
                    # Account names are user data, even when they match a UI key.
                    value = str(value) if detail.get('label') == '账号' else tr(value)
                    lines.append(pair(tr(detail.get('label', '')), value))
        if i in self.errors:
            lines.append(tr(self.errors[i]))
        return '\n'.join(lines)

    def refresh(self):
        if self.offline:
            return
        self.refresh_native()
        self.refresh_sources()

    def matches_workbuddy_account(self, snapshot):
        return (self.workbuddy_account is not None and isinstance(snapshot, dict)
                and snapshot.get('source') == 'workbuddy'
                and snapshot.get('account_key') == self.workbuddy_account.key)

    def sync_workbuddy_account(self):
        account = workbuddy.current_account()
        cached = self.snapshots.get(2)
        if account == self.workbuddy_account and (cached is None or self.matches_workbuddy_account(cached)):
            return False
        self.workbuddy_account = account
        self.workbuddy_generation += 1
        self.workbuddy_retry.stop()
        self.workbuddy_retry_available = account is not None
        self.errors.pop(2, None)
        if cached is not None and not self.matches_workbuddy_account(cached):
            del self.snapshots[2]
            try:
                atomic_json(STATE / 'balances.json', self.snapshots)
            except OSError:
                pass
        self.mini.page_turn.finish()
        self.render()
        return True

    def workbuddy_file_changed(self):
        if not self.offline and 2 in self.visible_sources and self.sync_workbuddy_account():
            self.request_native(2, 'workbuddy_provider')
            self.render()

    def refresh_native(self, only=None):
        if self.offline:
            return
        for i, module in enumerate(('codex_provider', 'qoder_provider', 'workbuddy_provider', 'antigravity_provider')):
            if i not in self.visible_sources or (only is not None and i not in only):
                continue
            if i == 2:
                self.workbuddy_watch.rearm()
                self.sync_workbuddy_account()
            self.request_native(i, module)
        self.render()

    def request_native(self, index, provider):
        if index == 2:
            self.workbuddy_retry.stop()
            if not self.workbuddy_account:
                self.errors[index] = '未找到 WorkBuddy 登录状态，请先打开 WorkBuddy 并登录'
                return
        if index in self.busy:
            return
        self.busy.add(index)
        generation = self.workbuddy_generation

        def run():
            try:
                result = validate_snapshot(importlib.import_module('providers.' + provider).fetch())
                self.bridge.result.emit(index, result, '', generation)
            except Exception as exc:
                # Adapters raise safe, user-facing errors; never log raw response bodies.
                message = str(exc) if isinstance(exc, (RuntimeError, ValueError)) else '连接暂不可用，请打开对应客户端并登录后刷新'
                if any(s in message.lower() for s in ('bearer ', 'token=', 'eyj', 'authorization')):
                    message = '登录连接暂不可用，请打开对应客户端并登录后刷新'
                self.bridge.result.emit(index, None, message[:160], generation)

        threading.Thread(target=run, daemon=True, name=f'quota-{provider}').start()

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
            if key == 2 and not self.offline:
                self.workbuddy_watch.start(workbuddy.account_snapshot_path())
                self.sync_workbuddy_account()
                self.request_native(2, 'workbuddy_provider')
        elif not checked and key in self.visible_sources:
            self.visible_sources.remove(key)
            if key == 2:
                self.workbuddy_watch.stop()
                self.workbuddy_retry.stop()
                self.workbuddy_retry_available = False
                self.workbuddy_generation += 1
        self.active = self.visible_sources.index(previous) if previous in self.visible_sources else 0
        self.mini.origin_agent = self.active
        self.rebuild_rows()
        self.selection_error = '' if self.save_settings() else '选择尚未保存，请检查 state 目录权限'
        self.render()
        self.layout().activate()
        self.clamp_position()
        if checked and key != 2 and key not in self.snapshots:
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

    def receive(self, index, data, error, generation=0):
        self.busy.discard(index)
        if index == 3 and error in (antigravity.NO_ACCOUNT_MESSAGE, antigravity.ACCOUNT_CHANGED_MESSAGE):
            self.snapshots.pop(index, None)
            try:
                atomic_json(STATE / 'balances.json', self.snapshots)
            except OSError:
                pass
        if index == 2 and not self.offline:
            if 2 not in self.visible_sources:
                self.render()
                return
            self.sync_workbuddy_account()
            if generation != self.workbuddy_generation:
                self.refresh_native((2,))
                return
            if not error and not self.matches_workbuddy_account(data):
                error = 'WorkBuddy 账号已切换，正在重新读取'
            # Allow one retry while the desktop client opens or switches accounts.
            if error and self.workbuddy_retry_available:
                self.workbuddy_retry.start()
            self.workbuddy_retry_available = False
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
        if self.docking.side:
            self.docking.undock()
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
        if self.docking.side:
            self.docking.tuck()
            return
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
        if self.docking.side:
            self.docking.place()
            return
        screen = nearest_screen(self.frameGeometry().center(), QApplication.screens())
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
            settings = {'shape': self.shape, 'mini_scale': self.mini_scale, 'topmost': self.topmost, 'x': self.x(), 'y': self.y(), 'visible_sources': self.visible_sources, 'magpie_connection': self.magpie_connection, 'edge_dock': self.docking.settings(), 'language': self.language}
            if self.antigravity_display != 'weekly':
                settings['antigravity_display'] = self.antigravity_display
            atomic_json(STATE / 'settings.json', settings)
            return True
        except OSError:
            return False

    def reveal(self):
        self.clamp_position()
        self.show()
        if self.docking.side:
            self.docking.peek()
            self.docking.hide_timer.start(2000)
            return
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

    def enterEvent(self, event):
        self.docking.enter()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.docking.leave()
        super().leaveEvent(event)

    def hideEvent(self, event):
        self.docking.suspend()
        super().hideEvent(event)
        self.write_runtime()

    def showEvent(self, event):
        super().showEvent(event)
        self.write_runtime()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.collapse()
        elif event.key() == Qt.Key.Key_F5:
            self.refresh()
        else:
            super().keyPressEvent(event)

    def show_details(self, index):
        QMessageBox.information(self, self.source_name(index) + tr(' · 额度详情'), self.details_text(index))

    def quit(self):
        self.workbuddy_watch.stop()
        self.workbuddy_retry.stop()
        self.updater.cancel.set()
        self.updater.auto_timer.stop()
        self.save_settings()
        self.tray.hide()
        QApplication.quit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', action='version', version=__version__)
    parser.add_argument('--smoke-test', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--update-ready', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--offline', action='store_true', help='Show cached data without querying providers')
    parser.add_argument('--expanded', action='store_true')
    parser.add_argument('--sources', action='store_true', help='Open the quota source selection page')
    parser.add_argument('--updates', action='store_true', help='Open the update window')
    parser.add_argument('--qa-window', action='store_true', help='Expose a normal window for native accessibility verification')
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    app.setApplicationName('Quota Station')
    app.setOrganizationName('QuotaStation')
    app.setQuitOnLastWindowClosed(False)
    setup_fonts(app)
    if args.smoke_test:
        from packaged_smoke import run
        return run(app, args.smoke_test)
    # Match Windows' own double-click speed, including accessibility preferences.
    if os.name == 'nt':
        app.setDoubleClickInterval(ctypes.windll.user32.GetDoubleClickTime())
    server_name = 'QuotaStation_v1'
    if os.environ.get('QUOTA_STATION_DATA_DIR'):
        import hashlib
        server_name += '_' + hashlib.sha256(str(STATE.resolve()).encode()).hexdigest()[:16]
    socket = QLocalSocket()
    socket.connectToServer(server_name)
    if socket.waitForConnected(400):
        socket.write(b'updates' if args.updates else b'sources' if args.sources else b'expanded' if args.expanded else b'show')
        socket.waitForBytesWritten(400)
        return 0
    QLocalServer.removeServer(server_name)
    server = QLocalServer()
    if not server.listen(server_name):
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
        elif command == b'updates':
            station.updater.show()
        elif command == b'expanded':
            station.expand()
        else:
            station.reveal()
    server.newConnection.connect(incoming)
    station.show()
    if args.update_ready:
        from updater_core import mark_ready
        QTimer.singleShot(700, lambda: mark_ready(args.update_ready, __version__))
    if args.expanded:
        station.expand()
    if args.sources:
        station.show_sources()
    if args.updates:
        station.updater.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
