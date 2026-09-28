"""额度小站: a local, read-only Windows quota companion."""
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
    QLayout, QMenu, QMessageBox, QProgressBar, QPushButton, QSystemTrayIcon,
    QVBoxLayout, QWidget,
)

BASE = Path(__file__).resolve().parent
STATE = BASE / 'state'
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
    value = data.get('balance')
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0:
        raise ValueError('未返回可确认的剩余额度')
    if data.get('unit') == '%' and value > 100:
        raise ValueError('剩余百分比超出范围')
    return data


def number_text(data):
    if not data:
        return '—'
    value = data['balance']
    if data.get('unit') == '%':
        return f'{value:,.0f}%'
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
    app.setFont(QFont('Microsoft YaHei', 9))


def icon():
    pix = QPixmap(128, 128)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
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
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(lambda: station.cycle(1))
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

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.layout_resize_grip()

    def layout_resize_grip(self):
        # Keep the fold inside the rounded paper edge at every card size.
        scale = self.station.mini_scale
        side, inset = round(26 * scale), round(32 * scale)
        self.resize_grip.setFixedSize(side, side)
        self.resize_grip.move(self.width() - inset, self.height() - inset)
        self.resize_grip.raise_()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        if self.timer.isActive():
            self.timer.stop()
            self.station.cycle(1)
        self.origin_agent = self.station.active
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
        self.setFixedWidth(292)

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
        self.active = 0  # Every launch starts with Codex; collapse preserves the current agent.
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
        for key, value in read_json(STATE / 'balances.json', {}).items():
            try:
                self.snapshots[int(key)] = validate_snapshot(value)
            except (ValueError, TypeError, KeyError):
                pass
        self.errors = {}
        self.busy = set()
        self.bridge = Bridge()
        self.bridge.result.connect(self.receive)
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
        text.setSpacing(4)
        text.addWidget(label('额度小站', 14, bold=False))
        text.addWidget(label('留一点余量，从容做事', 11, MUTED))
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
        self.rows = []
        for i, name in enumerate(NAMES):
            row = QWidget()
            layout = QVBoxLayout(row)
            layout.setContentsMargins(0, 13, 0, 13)
            layout.setSpacing(7)
            top = QHBoxLayout()
            top.setSpacing(7)
            top.addWidget(label('●', 10, COLORS[i]))
            top.addWidget(label(name, 13))
            top.addStretch()
            value = label('—', 20, bold=True)
            top.addWidget(value)
            layout.addLayout(top)
            progress = QProgressBar()
            progress.setRange(0, 1000)
            progress.setTextVisible(False)
            progress.setFixedHeight(4)
            progress.setStyleSheet(f'QProgressBar{{border:0;background:{SOFT};border-radius:2px;}} QProgressBar::chunk{{background:{COLORS[i]};border-radius:2px;}}')
            progress.hide()
            layout.addWidget(progress)
            info = QHBoxLayout()
            left, right = label('正在连接', 11, MUTED), label('', 11, MUTED)
            info.addWidget(left)
            info.addStretch()
            info.addWidget(right)
            layout.addLayout(info)
            row.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            row.customContextMenuRequested.connect(lambda _p, index=i: self.show_details(index))
            box.addWidget(row)
            self.rows.append((row, value, left, right, progress))
            if i < 2:
                line = QFrame()
                line.setFixedHeight(1)
                line.setStyleSheet(f'background:{LINE};border:0;')
                box.addWidget(line)
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
        settings.addWidget(label('收起外观', 11, MUTED))
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

    def render(self):
        data = self.snapshots.get(self.active)
        scale = self.mini_scale
        px = lambda value: max(1, round(value * scale))
        radius = px(62 if self.shape == 'ball' else 29)
        self.mini.setFixedSize(px(124 if self.shape == 'ball' else 138), px(124 if self.shape == 'ball' else 116))
        self.mini.layout().setContentsMargins(px(8), px(11), px(8), px(10))
        self.mini.layout().setSpacing(px(3))
        self.mini.resize_grip.setVisible(self.shape == 'card')
        self.mini.layout_resize_grip()
        self.mini.setStyleSheet(f'QPushButton{{background:{PAPER};border:1px solid {LINE};border-radius:{radius}px;}} QPushButton:focus{{border-color:#b1c9b8;}}')
        self.mini.name.setText('● ' + NAMES[self.active])
        self.mini.name.setStyleSheet(f'color:{COLORS[self.active]};font-size:{px(12)}px;border:0;background:transparent;')
        self.mini.value.setText(number_text(data))
        self.mini.value.setStyleSheet(f'color:{TEXT};font-size:{px(25 if data and data["balance"] >= 10000 else 29)}px;font-weight:600;border:0;background:transparent;')
        unit = data.get('subtitle', '剩余额度') if data else ('正在连接' if self.active in self.busy else '待连接')
        self.mini.unit.setText(unit if self.active not in self.errors else ('上次余额' if data else '待连接'))
        self.mini.unit.setStyleSheet(f'color:{MUTED};font-size:{px(11)}px;border:0;background:transparent;')
        self.mini.dots.setText(' '.join('●' if i == self.active else '·' for i in range(3)))
        self.mini.dots.setStyleSheet(f'color:{COLORS[self.active]};font-size:{px(11)}px;border:0;background:transparent;')
        self.mini.setAccessibleName(f'{NAMES[self.active]} {unit} {number_text(data)}，单击切换，双击展开')
        self.mini.setToolTip(self.details_text(self.active) + '\n\n单击切换 · 双击展开 · 拖动调整位置\n右键菜单 · Enter 展开 · 左右键切换')
        for i, (row, value, left, right, progress) in enumerate(self.rows):
            item = self.snapshots.get(i)
            value.setText(number_text(item))
            left.setText(item.get('subtitle', '剩余额度') if item else ('正在连接' if i in self.busy else '待连接'))
            if i in self.errors:
                right.setText('更新失败' if item else '待连接')
                left.setText('上次余额' if item else self.errors[i][:14])
            elif i in self.busy:
                right.setText('更新中…')
            elif item:
                reset = item.get('reset_at')
                right.setText(time.strftime('%m-%d %H:%M 重置', time.localtime(reset)) if reset else age_text(item.get('updated_at')))
            else:
                right.setText('')
            progress.setVisible(bool(item and item.get('unit') == '%'))
            if item and item.get('unit') == '%':
                progress.setValue(round(item['balance'] * 10))
            row.setToolTip(self.details_text(i) + '\n右键查看详情')
        self.refresh_button.setEnabled(not self.busy)
        self.refresh_button.setText('更新中' if self.busy else '刷新')
        self.last_updated.setText('每 5 分钟自动更新' if not self.errors else '部分连接待恢复 · 保留上次余额')
        for key, button in self.shape_buttons.items():
            button.setChecked(key == self.shape)
        self.tray.setToolTip('额度小站\n' + '\n'.join(f'{name}  {number_text(self.snapshots.get(i))}' for i, name in enumerate(NAMES)))
        try:
            atomic_json(STATE / 'runtime.json', {'pid': os.getpid(), 'active': NAMES[self.active], 'expanded': self.expanded, 'shape': self.shape, 'mini_scale': self.mini_scale, 'busy': sorted(self.busy), 'errors': self.errors, 'visible': self.isVisible(), 'geometry': [self.x(), self.y(), self.width(), self.height()]})
        except OSError:
            pass

    def details_text(self, i):
        item = self.snapshots.get(i)
        lines = [NAMES[i]]
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
        for i, module in enumerate(('codex_provider', 'qoder_provider', 'workbuddy_provider')):
            if i in self.busy:
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
        self.active = (self.active + offset) % 3
        self.render()

    def expand(self):
        self.mini.timer.stop()
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
        self.shape = shape
        self.render()
        self.save_settings()

    def set_mini_scale(self, value, persist=False, clamp=True):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            return
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
            atomic_json(STATE / 'settings.json', {'shape': self.shape, 'mini_scale': self.mini_scale, 'topmost': self.topmost, 'x': self.x(), 'y': self.y()})
        except OSError:
            pass

    def reveal(self):
        self.clamp_position()
        self.show()
        self.raise_()
        self.activateWindow()

    def toggle_topmost(self, enabled):
        self.topmost = bool(enabled)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self.topmost)
        self.show()
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
        QMessageBox.information(self, NAMES[index] + ' · 额度详情', self.details_text(index))

    def quit(self):
        self.save_settings()
        self.tray.hide()
        QApplication.quit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--offline', action='store_true', help='Show cached data without querying providers')
    parser.add_argument('--expanded', action='store_true')
    parser.add_argument('--qa-window', action='store_true', help='Expose a normal window for native accessibility verification')
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    app.setApplicationName('额度小站')
    app.setOrganizationName('QuotaStation')
    app.setQuitOnLastWindowClosed(False)
    setup_fonts(app)
    # Match Windows' own double-click speed, including accessibility preferences.
    if os.name == 'nt':
        app.setDoubleClickInterval(ctypes.windll.user32.GetDoubleClickTime())
    socket = QLocalSocket()
    socket.connectToServer('QuotaStation_v1')
    if socket.waitForConnected(400):
        socket.write(b'show')
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
        if connection:
            connection.close()
            connection.deleteLater()
        station.reveal()
    server.newConnection.connect(incoming)
    station.show()
    if args.expanded:
        station.expand()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
