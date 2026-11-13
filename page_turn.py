"""A textured paper surface bent in 3D and projected over the next card."""
from __future__ import annotations

import math

from PySide6.QtCore import QEasingCurve, QPoint, QPointF, QRectF, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QPolygonF, QTransform
from PySide6.QtWidgets import QWidget


def shadow_outline(points):
    """A single convex silhouette keeps soft shadows smooth and cheap to draw."""
    points = sorted(set(points))
    if len(points) < 3:
        return QPainterPath()

    def cross(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    halves = []
    for ordered in (points, reversed(points)):
        half = []
        for point in ordered:
            while len(half) > 1 and cross(half[-2], half[-1], point) <= 0:
                half.pop()
            half.append(point)
        halves.extend(half[:-1])
    path = QPainterPath()
    path.addPolygon(QPolygonF([QPointF(x, y) for x, y in halves]))
    path.closeSubpath()
    return path


class PageTurn(QWidget):
    DURATION = 520

    def __init__(self, parent):
        super().__init__(parent)
        self.card = parent
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.before = self.after = None
        self.progress = 0.0
        self.direction = 1
        self.radius = 29
        self.animation = QVariantAnimation(self)
        self.animation.setDuration(self.DURATION)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutSine)
        self.animation.valueChanged.connect(self.set_progress)
        self.animation.finished.connect(self.finish)
        self.hide()

    def start(self, before, after, direction, radius):
        self.finish()
        self.before, self.after = before, after
        self.direction = 1 if direction > 0 else -1
        self.radius = radius
        self.progress = 0.0
        # Use the card's existing shadow margin so a lifted corner can leave the
        # card outline without resizing or moving the actual desktop widget.
        host = self.card.window()
        if self.parentWidget() is not host:
            self.setParent(host)
        self.setGeometry(host.rect())
        self.show()
        self.raise_()
        self.animation.start()

    def set_progress(self, progress):
        self.progress = float(progress)
        self.update()

    def finish(self):
        self.animation.stop()
        self.hide()
        self.before = self.after = None

    def paintEvent(self, event):
        if self.before is None or self.after is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        origin = self.card.mapTo(self.parentWidget(), QPoint(0, 0)) - self.pos()
        painter.translate(origin)
        width, height = float(self.card.width()), float(self.card.height())
        bounds = QRectF(0, 0, width, height)
        outline = QPainterPath()
        outline.addRoundedRect(bounds.adjusted(.5, .5, -.5, -.5), self.radius, self.radius)
        painter.save()
        painter.setClipPath(outline)
        painter.drawPixmap(bounds, self.after, QRectF(self.after.rect()))
        painter.restore()
        progress = min(1.0, max(0.0, self.progress))
        if progress <= 0:
            painter.drawPixmap(bounds, self.before, QRectF(self.before.rect()))
            return
        if progress >= 1:
            return

        diagonal = math.hypot(width, height)
        normal_x, normal_y = width / diagonal, height / diagonal
        span = width * height / diagonal + 2
        crease = diagonal * (1 - progress)
        radius = max(.15, diagonal * .07 * math.sin(math.pi * progress))
        angle = math.pi * (.58 + .42 * progress)
        arc_end = crease + radius * angle
        sign = self.direction
        center_x, center_y = width / 2, height / 2
        camera = diagonal * 2.8

        def original(q, tangent):
            x, y = normal_x * q - normal_y * tangent, normal_y * q + normal_x * tangent
            return QPointF(x, y) if sign > 0 else QPointF(width - x, height - y)

        def surface(q):
            distance = max(0, q - crease)
            phi = min(angle, distance / radius)
            tail = max(0, distance - radius * angle)
            position = crease + radius * math.sin(phi) + tail * math.cos(angle)
            depth = radius * (1 - math.cos(phi)) + tail * math.sin(angle)
            return position, depth, phi

        def projected(q, tangent, shadow=False):
            position, depth, _ = surface(q)
            point = original(position, tangent)
            if shadow:
                return QPointF(point.x() + depth * .16, point.y() + depth * .24)
            scale = camera / (camera - depth)
            return QPointF(center_x + (point.x() - center_x) * scale,
                           center_y + (point.y() - center_y) * scale)

        def strip(low, high):
            polygon = QPolygonF([original(low, -span), original(high, -span),
                                 original(high, span), original(low, span)])
            path = QPainterPath()
            path.addPolygon(polygon)
            path.closeSubpath()
            return polygon, outline.intersected(path)

        _, flat = strip(-diagonal, crease)
        painter.save()
        painter.setClipPath(flat)
        painter.drawPixmap(bounds, self.before, QRectF(self.before.rect()))
        painter.restore()

        # Each curved strip has its own projective texture transform. Beyond
        # the bend the actual corner/edge of the page rotates back over the old
        # face, creating a broad, tapered flap instead of a diagonal wipe band.
        curve_end = min(diagonal, arc_end)
        cuts = [crease + (curve_end - crease) * index / 24 for index in range(25)]
        if curve_end < diagonal:
            cuts.append(diagonal)
        patches = []
        shadow_points = []
        sheet_path = QPainterPath()
        max_depth = 0.0
        for low, high in zip(cuts, cuts[1:]):
            source, region = strip(low, high)
            if region.isEmpty() or high - low < .001:
                continue
            coordinates = ((low, -span), (high, -span), (high, span), (low, span))
            target = QPolygonF([projected(q, tangent) for q, tangent in coordinates])
            mapping = QTransform()
            if not QTransform.quadToQuad(source, target, mapping):
                continue
            _, depth, phi = surface((low + high) / 2)
            max_depth = max(max_depth, surface(high)[1])
            # Adjacent projective clips otherwise leave subpixel hairlines.
            # Overlap only the internal seams; retain the rounded paper edge.
            _, paint_region = strip(low - .6, high + .6)
            patches.append((depth, paint_region, mapping, phi))
            sheet_path = sheet_path.united(mapping.map(region))
            shade_mapping = QTransform()
            shade_quad = QPolygonF([projected(q, tangent, shadow=True) for q, tangent in coordinates])
            if QTransform.quadToQuad(source, shade_quad, shade_mapping):
                shadow_points.extend((point.x(), point.y()) for point in shade_mapping.map(region).toFillPolygon())

        # A raised sheet casts a displaced, soft shadow on the sheet below.
        shadow_path = shadow_outline(shadow_points)
        painter.save()
        painter.setClipPath(outline)
        softness = min(width * .10, 2 + max_depth * .15)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for spread, alpha in ((1.5, 5), (1, 9), (.55, 15)):
            painter.setPen(QPen(QColor(30, 43, 30, alpha), softness * spread,
                                Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.drawPath(shadow_path)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.fillPath(shadow_path, QColor(30, 43, 30, 38))
        painter.restore()

        # Render the lifted sheet independently so its free edge can disappear
        # softly into the transparent window margin instead of being cut off.
        sheet = QPixmap(self.size() * self.devicePixelRatioF())
        sheet.setDevicePixelRatio(self.devicePixelRatioF())
        sheet.fill(Qt.GlobalColor.transparent)
        surface_painter = QPainter(sheet)
        surface_painter.setRenderHints(painter.renderHints())
        surface_painter.translate(origin)
        surface_painter.fillPath(sheet_path, QColor(236, 239, 229))
        for depth, region, mapping, phi in sorted(patches, key=lambda patch: patch[0]):
            surface_painter.save()
            surface_painter.setTransform(mapping, True)
            surface_painter.setClipPath(region)
            light = sign * (.35 * normal_x + .45 * normal_y) * math.sin(phi) + .82 * math.cos(phi)
            if math.cos(phi) >= 0:
                surface_painter.drawPixmap(bounds, self.before, QRectF(self.before.rect()))
                surface_painter.fillPath(region, QColor(20, 32, 22, round(60 * (1 - max(0, light)))))
            else:
                brightness = .85 + .15 * max(0, min(1, -light))
                surface_painter.fillPath(region, QColor(round(244 * brightness), round(246 * brightness), round(237 * brightness)))
            surface_painter.restore()

        # Follow the deformed free edge, including the original rounded corner.
        _, folded = strip(crease, diagonal + 1)
        boundary = list(folded.toFillPolygon())
        edge = QPainterPath()
        if boundary:
            first = True
            for start, end in zip(boundary, boundary[1:] + boundary[:1]):
                start_q = normal_x * start.x() + normal_y * start.y()
                end_q = normal_x * end.x() + normal_y * end.y()
                if sign < 0:
                    start_q, end_q = diagonal - start_q, diagonal - end_q
                if max(abs(start_q - crease), abs(end_q - crease)) < .05:
                    first = True
                    continue
                count = max(1, math.ceil(math.hypot(end.x() - start.x(), end.y() - start.y()) / 3))
                for step in range(count):
                    x = start.x() + (end.x() - start.x()) * step / count
                    y = start.y() + (end.y() - start.y()) * step / count
                    if sign < 0:
                        x, y = width - x, height - y
                    point = projected(normal_x * x + normal_y * y, -normal_y * x + normal_x * y)
                    if first:
                        edge.moveTo(point)
                        first = False
                    else:
                        edge.lineTo(point)
            surface_painter.setBrush(Qt.BrushStyle.NoBrush)
            surface_painter.setPen(QPen(QColor(92, 111, 86, 105), .8))
            surface_painter.drawPath(edge)
        surface_painter.resetTransform()
        surface_painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        margin = 9.0
        for start, end in ((QPointF(0, 0), QPointF(margin, 0)),
                           (QPointF(self.width(), 0), QPointF(self.width() - margin, 0)),
                           (QPointF(0, 0), QPointF(0, margin)),
                           (QPointF(0, self.height()), QPointF(0, self.height() - margin))):
            fade = QLinearGradient(start, end)
            fade.setColorAt(0, QColor(0, 0, 0, 0))
            fade.setColorAt(1, QColor(0, 0, 0, 255))
            surface_painter.fillRect(self.rect(), fade)
        surface_painter.end()
        painter.resetTransform()
        painter.drawPixmap(0, 0, sheet)
