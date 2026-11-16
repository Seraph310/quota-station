"""Screen-edge parking for the quota card; hover never activates the window."""
from __future__ import annotations

import math

from PySide6.QtCore import QObject, QPoint, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QWidget
from i18n import tr


def nearest_screen(point, screens):
    """Keep off-screen releases on the nearest monitor, including negative origins."""
    def distance(screen):
        area = screen.geometry()
        dx = max(area.left() - point.x(), 0, point.x() - area.right())
        dy = max(area.top() - point.y(), 0, point.y() - area.bottom())
        return dx * dx + dy * dy
    return min(screens, key=distance)


def outside_edge(body, area, other_areas, pointer_y, threshold=12):
    """Only exposed desktop edges dock; monitor seams remain ordinary drag targets."""
    y = max(area.top(), min(pointer_y, area.bottom()))
    for side, crossed, x in (
        ('left', body.left() <= area.left() - threshold, area.left() - 1),
        ('right', body.right() >= area.right() + threshold, area.right() + 1),
    ):
        if crossed and not any(rect.contains(QPoint(x, y)) for rect in other_areas):
            return side
    return None


def quota_indicator(snapshot):
    """Use an explicit remaining percentage; cash/credits alone have no denominator."""
    if not snapshot:
        return None, '—'
    if snapshot.get('quota_state') == 'unlimited':
        return None, '∞'
    balance = snapshot.get('balance')
    if isinstance(balance, bool) or not isinstance(balance, (int, float)) or not math.isfinite(balance):
        return None, '—'
    unit = snapshot.get('unit', '')
    percent = balance if unit == '%' else snapshot.get('remaining_percent')
    if (isinstance(percent, (int, float)) and not isinstance(percent, bool)
            and math.isfinite(percent) and 0 <= percent <= 100):
        text = '<1%' if 0 < percent < 1 else f'{percent:.0f}%'
        return percent, text
    if unit == '%':
        return None, '—'
    magnitude = abs(balance)
    if magnitude >= 1_000_000_000:
        text = f'{balance:.1e}'
    elif magnitude >= 1000:
        divisor, suffix = (1_000_000, 'M') if magnitude >= 1_000_000 else (1000, 'K')
        text = f'{balance / divisor:.1f}'.rstrip('0').rstrip('.') + suffix
    elif 0 < magnitude < 0.01:
        text = f'{balance:.1g}'
    else:
        text = f'{balance:.2f}'.rstrip('0').rstrip('.')
    prefix = {'CNY': '¥', '元': '¥', 'USD': '$', 'EUR': '€', 'GBP': '£'}.get(unit, unit)
    return None, (prefix if prefix in ('¥', '$', '€', '£') else '') + text


class DockBar(QWidget):
    WIDTH, HEIGHT = 12, 64

    def __init__(self, docking):
        super().__init__(docking.station)
        self.docking = docking
        self.press_at = None
        self.dragged = False
        self.percent, self.quota_text = None, '—'
        self.setFixedSize(self.WIDTH, self.HEIGHT)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setAccessibleName(tr('额度小站侧边条，悬停查看，拖回屏幕恢复卡片'))

    def sync(self):
        station = self.docking.station
        key = station.active_key
        self.percent, self.quota_text = quota_indicator(station.snapshots.get(key))
        self.setToolTip(station.details_text(key))
        stale = '上次余额' if key in station.errors else '剩余额度'
        self.setAccessibleName(tr('{name}，{status} {value}，悬停查看，拖回屏幕恢复卡片', name=station.source_name(key), status=tr(stale), value=self.quota_text))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # The outer corners continue off-screen; only the inward edge is rounded.
        x = -5 if self.docking.side == 'left' else 0.5
        painter.setPen(QPen(QColor('#bfcfbe'), 1))
        painter.setBrush(QColor(246, 250, 244, 238))
        painter.drawRoundedRect(QRectF(x, 0.5, self.width() + 4.5, self.height() - 1), 6, 6)
        color = QColor(self.docking.station.source_color(self.docking.station.active_key))
        if self.percent is not None:
            track = QRectF(2, 5, self.width() - 4, self.height() - 10)
            clip = QPainterPath()
            clip.addRoundedRect(track, 4, 4)
            painter.save()
            painter.setClipPath(clip)
            painter.fillRect(track, QColor('#e3eade'))
            color.setAlpha(125)
            height = track.height() * self.percent / 100
            painter.fillRect(QRectF(track.left(), track.bottom() - height, track.width(), height), color)
            painter.restore()
        # A rotated number keeps the entire native window just 12 px wide.
        painter.translate(self.width() / 2, self.height() / 2)
        painter.rotate(-90)
        font = QFont(self.font())
        font.setPixelSize(9)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        text = painter.fontMetrics().elidedText(self.quota_text, Qt.TextElideMode.ElideRight, self.height() - 8)
        painter.setPen(QColor('#293c30') if self.quota_text != '—' else QColor('#7c8978'))
        painter.drawText(QRectF(-self.height() / 2 + 4, -self.width() / 2, self.height() - 8, self.width()),
                         Qt.AlignmentFlag.AlignCenter, text)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.press_at = event.globalPosition().toPoint()
            self.window_at = self.docking.station.pos()
            self.dragged = False
            self.docking.suspend()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.press_at is not None and event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.globalPosition().toPoint() - self.press_at
            if delta.manhattanLength() >= QApplication.startDragDistance():
                self.dragged = True
            if self.dragged:
                self.docking.station.move(self.window_at + delta)
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.press_at is not None:
            self.press_at = None
            if self.dragged:
                self.docking.finish_bar_drag(event.globalPosition().toPoint())
            else:
                self.docking.peek()
            event.accept()
        else:
            super().mouseReleaseEvent(event)


class EdgeDock(QObject):
    HOVER_DELAY = 350
    HIDE_DELAY = 600

    def __init__(self, station):
        super().__init__(station)
        self.station = station
        self.side = None
        self.peeked = False
        self.screen_name = ''
        self.center_y = 0
        self.hover_armed = True
        self.bar = DockBar(self)
        station.layout().addWidget(self.bar)
        self.bar.hide()
        self.hover_timer = QTimer(self)
        self.hover_timer.setSingleShot(True)
        self.hover_timer.timeout.connect(self._hover_timeout)
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self._hide_timeout)
        application = QApplication.instance()
        application.screenAdded.connect(self._screen_added)
        application.screenRemoved.connect(self._screens_changed)
        for screen in application.screens():
            self._watch_screen(screen)

    def _watch_screen(self, screen):
        screen.availableGeometryChanged.connect(self._screens_changed)
        screen.geometryChanged.connect(self._screens_changed)

    def _screen_added(self, screen):
        self._watch_screen(screen)
        self._screens_changed()

    def _screens_changed(self, *_args):
        # Let Qt finish updating all monitor rectangles before re-anchoring.
        QTimer.singleShot(0, self._reposition)

    def _reposition(self):
        if self.side:
            self.place()
            self.station.save_settings()
            self.station.write_runtime()
        else:
            self.station.clamp_position()

    def screen(self):
        screens = QApplication.screens()
        return next((item for item in screens if item.name() == self.screen_name),
                    nearest_screen(self.station.frameGeometry().center(), screens))

    def settings(self):
        return {'side': self.side, 'screen': self.screen_name, 'center_y': self.center_y} if self.side else None

    def restore(self, saved):
        if not isinstance(saved, dict) or saved.get('side') not in ('left', 'right'):
            return
        y = saved.get('center_y')
        if not isinstance(y, (int, float)) or isinstance(y, bool) or not math.isfinite(y):
            return
        self.screen_name = saved.get('screen', '')
        self.dock(saved['side'], self.screen(), center_y=round(y), persist=False)
        self.hover_armed = True

    def suspend(self):
        self.hover_timer.stop()
        self.hide_timer.stop()

    def _passive(self, enabled):
        station = self.station
        flag = Qt.WindowType.WindowDoesNotAcceptFocus
        if bool(station.windowFlags() & flag) == enabled:
            return
        visible, position = station.isVisible(), station.pos()
        station.setWindowFlag(flag, enabled)
        station.move(position)
        if visible:
            station.show()  # WA_ShowWithoutActivating remains set in both modes.

    def _view(self, bar):
        station = self.station
        station.mini.timer.stop()
        station.mini.page_turn.finish()
        station.expanded = False
        station.paper.hide()
        station.mini.setVisible(not bar)
        self.bar.setVisible(bar)
        margin = 0 if bar else 14
        station.layout().setContentsMargins(margin, margin, margin, margin)
        station.layout().activate()
        self.bar.update()

    def place(self):
        if not self.side:
            return
        screen = self.screen()
        self.screen_name = screen.name()
        area, available = screen.geometry(), screen.availableGeometry()
        self.center_y = max(available.top() + self.bar.HEIGHT // 2,
                            min(self.center_y, available.bottom() - self.bar.HEIGHT // 2 + 1))
        station = self.station
        x = area.left() if self.side == 'left' else area.right() - station.width() + 1
        y = max(available.top(), min(round(self.center_y - station.height() / 2),
                                    available.bottom() - station.height() + 1))
        station.move(x, y)

    def dock(self, side, screen, *, center_y=None, persist=True):
        self.suspend()
        self.center_y = self.station.y() + self.station.height() / 2 if center_y is None else center_y
        self.side, self.screen_name, self.peeked = side, screen.name(), False
        # Releasing a dragged card must not immediately open the bar underneath it.
        self.hover_armed = False
        self._view(bar=True)
        self.place()
        self._passive(True)
        self.hover_armed = not self.pointer_inside()
        self.station.undock_action.setVisible(True)
        if persist:
            self.station.save_settings()
        self.station.write_runtime()

    def finish_drag(self, point):
        station = self.station
        screen = nearest_screen(point, QApplication.screens())
        widget = station.paper if station.expanded else station.mini
        body = QRect(widget.mapToGlobal(QPoint()), widget.size())
        others = [item.geometry() for item in QApplication.screens() if item is not screen]
        side = outside_edge(body, screen.geometry(), others, point.y())
        if side:
            self.dock(side, screen)
        else:
            self._passive(False)
            station.clamp_position(snap=True)
            station.save_settings()
            station.write_runtime()

    def detach_for_drag(self):
        if self.side:
            self.suspend()
            self.side, self.peeked = None, False
            self.station.undock_action.setVisible(False)
            # Keep native flags until release, preserving Qt's implicit mouse grab.

    def finish_bar_drag(self, point):
        station, area = self.station, self.screen().geometry()
        edge_x = area.left() if self.side == 'left' else area.right() - self.bar.width() + 1
        if abs(station.x() - edge_x) < 28:
            self.center_y = station.y() + station.height() / 2
            self.hover_armed = False
            self.place()
            station.save_settings()
            station.write_runtime()
        else:
            self.undock()
            station.move(point - station.rect().center())
            self.finish_drag(point)

    def undock(self):
        self.suspend()
        if self.side:
            self._view(bar=False)
            self.place()
        self.side, self.peeked = None, False
        self.station.undock_action.setVisible(False)
        self._passive(False)
        self.station.clamp_position()
        self.station.save_settings()
        self.station.write_runtime()

    def peek(self):
        if not self.side or not self.station.isVisible() or self.bar.press_at is not None:
            return
        self.suspend()
        self.peeked = True
        self._view(bar=False)
        self.place()
        self.station.write_runtime()
        if not self.pointer_inside():
            self.hide_timer.start(self.HIDE_DELAY)

    def tuck(self):
        if not self.side:
            return
        self.suspend()
        self.peeked = False
        self._view(bar=True)
        self.place()
        self.station.write_runtime()

    def pointer_inside(self):
        return self.station.frameGeometry().contains(QCursor.pos())

    def enter(self):
        self.hide_timer.stop()
        if self.side and not self.peeked and self.hover_armed and self.bar.press_at is None:
            self.hover_timer.start(self.HOVER_DELAY)

    def leave(self):
        self.hover_timer.stop()
        if not self.pointer_inside():
            self.hover_armed = True
        if self.side and self.peeked:
            self.hide_timer.start(self.HIDE_DELAY)

    def _hover_timeout(self):
        if self.pointer_inside():
            self.peek()

    def _hide_timeout(self):
        if not self.side or not self.peeked or not self.station.isVisible() or self.pointer_inside():
            return
        station = self.station
        if (station.mini.press_at is not None or station.mini.resize_grip.start_at is not None
                or station.mini.timer.isActive() or station.mini.page_turn.isVisible()
                or QApplication.activePopupWidget() is not None):
            self.hide_timer.start(self.HIDE_DELAY)
            return
        self.tuck()
