"""Focused offscreen interaction tests for this project's own Qt widgets only.

No real desktop window, tray icon, network provider, or production STATE file
is accessed. Optional widget-render artifacts contain synthetic quota values.
"""

from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

import app as quota_app


LEFT = Qt.MouseButton.LeftButton


def snapshot(index, balance):
    return {
        "name": quota_app.NAMES[index], "balance": balance,
        "unit": "%" if index == 0 else ("Credits" if index == 1 else "积分"),
        "subtitle": "本周剩余" if index == 0 else "剩余额度",
        "reset_at": None, "details": [], "updated_at": time.time(),
    }


class AppInteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication(["quota-station-offscreen-tests"])
        if cls.qt.platformName() != "offscreen":
            raise unittest.SkipTest("Refusing to test against a real desktop Qt backend")
        cls.qt.setQuitOnLastWindowClosed(False)
        quota_app.setup_fonts(cls.qt)
        cls.original_double_interval = cls.qt.doubleClickInterval()
        cls.native_double_interval = (
            int(ctypes.windll.user32.GetDoubleClickTime())
            if os.name == "nt" else cls.original_double_interval
        )
        cls.qt.setDoubleClickInterval(cls.native_double_interval)

    @classmethod
    def tearDownClass(cls):
        cls.qt.setDoubleClickInterval(cls.original_double_interval)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix=".app-test-", dir=Path(__file__).parent)
        self.addCleanup(self.temporary.cleanup)
        self.state_patch = patch.object(quota_app, "STATE", Path(self.temporary.name))
        self.state_patch.start()
        self.addCleanup(self.state_patch.stop)
        # Suppress tray publication even though the entire Qt backend is offscreen.
        self.tray_show_patch = patch.object(quota_app.QSystemTrayIcon, "show", lambda _self: None)
        self.tray_show_patch.start()
        self.addCleanup(self.tray_show_patch.stop)
        self.station = quota_app.Station(offline=True)
        self.station.poll.stop()
        self.station.clock.stop()
        self.station.show()
        self.qt.processEvents()
        self.station.mini.setFocus()

    def tearDown(self):
        self.station.mini.timer.stop()
        self.station.poll.stop()
        self.station.clock.stop()
        self.station.tray.hide()
        self.station.close()
        self.station.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.qt.processEvents()

    def wait_for_click(self):
        QTest.qWait(self.qt.doubleClickInterval() + 100)

    def double_click(self, delay):
        mini = self.station.mini
        QTest.mouseClick(mini, LEFT)
        QTest.qWait(delay)
        # Match Qt's recognized double-click sequence: the second press arrives
        # as MouseButtonDblClick, followed by a release, not a second normal press.
        QTest.mouseDClick(mini, LEFT)
        QTest.mouseRelease(mini, LEFT)

    def drag_resize_grip(self, delta):
        grip = self.station.mini.resize_grip
        self.qt.processEvents()
        start = grip.rect().center()
        destination = grip.mapToGlobal(start) + delta
        QTest.mousePress(grip, LEFT, pos=start)
        event = QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(grip.mapFromGlobal(destination)), QPointF(destination),
            Qt.MouseButton.NoButton, LEFT, Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(grip, event)
        self.qt.processEvents()
        QTest.mouseRelease(grip, LEFT, pos=grip.mapFromGlobal(destination))
        self.qt.processEvents()

    def test_single_click_uses_native_interval_and_cycles_once(self):
        self.assertEqual(self.qt.styleHints().mouseDoubleClickInterval(), self.native_double_interval)
        QTest.mouseClick(self.station.mini, LEFT)
        self.assertTrue(self.station.mini.timer.isActive())
        self.assertEqual(self.station.mini.timer.interval(), self.native_double_interval + 30)
        self.assertEqual(self.station.active, 0)
        self.wait_for_click()
        self.assertEqual(self.station.active, 1)
        self.assertFalse(self.station.expanded)

    def test_two_independent_clicks_keep_both_actions_at_interval_boundary(self):
        QTest.mouseClick(self.station.mini, LEFT)
        # Outside the OS double-click interval but near the extra 30 ms guard.
        QTest.qWait(self.native_double_interval + 5)
        QTest.mouseClick(self.station.mini, LEFT)
        self.wait_for_click()
        self.assertEqual(self.station.active, 2)
        self.assertFalse(self.station.expanded)

    def test_quick_double_click_expands_without_switching_agent(self):
        self.station.cycle(1)
        self.double_click(min(80, max(1, self.native_double_interval // 3)))
        self.assertTrue(self.station.expanded)
        self.assertEqual(self.station.active, 1)
        self.assertFalse(self.station.mini.timer.isActive())
        self.wait_for_click()
        self.assertEqual(self.station.active, 1)

    def test_slow_native_double_click_and_collapse_preserve_agent(self):
        self.station.cycle(2)
        self.double_click(max(1, self.native_double_interval - 40))
        self.assertTrue(self.station.expanded)
        self.assertEqual(self.station.active, 2)
        QTest.mouseClick(self.station.close_button, LEFT)
        self.assertFalse(self.station.expanded)
        self.assertEqual(self.station.active, 2)
        self.assertTrue(self.station.mini.hasFocus())
        self.wait_for_click()
        self.assertEqual(self.station.active, 2)

    def test_double_event_restores_origin_if_timer_was_already_delivered(self):
        # Exercises the defensive rollback separately from OS timing recognition.
        self.station.cycle(1)
        QTest.mouseClick(self.station.mini, LEFT)
        self.wait_for_click()
        self.assertEqual(self.station.active, 2)
        QTest.mouseDClick(self.station.mini, LEFT)
        QTest.mouseRelease(self.station.mini, LEFT)
        self.assertTrue(self.station.expanded)
        self.assertEqual(self.station.active, 1)

    def test_drag_moves_own_widget_without_scheduling_a_click(self):
        mini = self.station.mini
        start = mini.rect().center()
        before = self.station.pos()
        QTest.mousePress(mini, LEFT, pos=start)
        delta = QPoint(max(25, QApplication.startDragDistance() + 5), 18)
        local = QPointF(start + delta)
        global_position = QPointF(mini.mapToGlobal(start) + delta)
        event = QMouseEvent(
            QEvent.Type.MouseMove, local, global_position,
            Qt.MouseButton.NoButton, LEFT, Qt.KeyboardModifier.NoModifier,
        )
        # QTest.mouseMove cannot reliably preserve held buttons on every
        # offscreen platform; send the move only to our own widget explicitly.
        QApplication.sendEvent(mini, event)
        QTest.mouseRelease(mini, LEFT, pos=start)
        self.assertTrue(mini.was_dragged)
        self.assertNotEqual(self.station.pos(), before)
        self.assertFalse(mini.timer.isActive())
        self.wait_for_click()
        self.assertEqual(self.station.active, 0)
        self.assertFalse(self.station.expanded)

    def test_keyboard_switch_expand_and_escape_preserve_platform(self):
        mini = self.station.mini
        QTest.keyClick(mini, Qt.Key.Key_Left)
        self.assertEqual(self.station.active, 2)
        QTest.keyClick(mini, Qt.Key.Key_Right)
        self.assertEqual(self.station.active, 0)
        QTest.keyClick(mini, Qt.Key.Key_Right)
        QTest.keyClick(mini, Qt.Key.Key_Return)
        self.assertTrue(self.station.expanded)
        self.assertEqual(self.station.active, 1)
        QTest.keyClick(self.station.close_button, Qt.Key.Key_Escape)
        self.assertFalse(self.station.expanded)
        self.assertEqual(self.station.active, 1)
        self.assertTrue(mini.hasFocus())

    def test_scale_changes_card_and_fonts_together_and_clamps_limits(self):
        self.station.move(100, 100)
        mini = self.station.mini
        self.assertEqual(self.station.mini_scale, 1.0)
        labels = (mini.name, mini.value, mini.unit, mini.dots)
        original_pixels = [item.font().pixelSize() for item in labels]
        self.assertTrue(all(pixels > 0 for pixels in original_pixels))
        for requested, expected in ((1.5, 1.5), (0.1, 0.8), (3.0, 2.0), (1.0, 1.0)):
            with self.subTest(requested=requested):
                self.station.set_mini_scale(requested)
                self.qt.processEvents()
                self.assertAlmostEqual(self.station.mini_scale, expected)
                self.assertAlmostEqual(mini.width(), 138 * expected, delta=1)
                self.assertAlmostEqual(mini.height(), 116 * expected, delta=1)
                for item, original in zip(labels, original_pixels):
                    self.assertAlmostEqual(item.font().pixelSize(), original * expected, delta=1)

    def test_resize_grip_projects_drag_without_moving_or_switching(self):
        self.station.cycle(2)
        self.station.move(100, 100)
        for delta in (QPoint(69, 58), QPoint(60, 0), QPoint(-69, -58)):
            with self.subTest(delta=(delta.x(), delta.y())):
                self.station.set_mini_scale(1.0)
                anchor = self.station.pos()
                # A pending body click must not later fire during handle resizing.
                QTest.mouseClick(self.station.mini, LEFT)
                self.assertTrue(self.station.mini.timer.isActive())
                self.drag_resize_grip(delta)
                expected = max(0.8, min(2.0, 1.0 + (delta.x() * 138 + delta.y() * 116) / (138 ** 2 + 116 ** 2)))
                self.assertAlmostEqual(self.station.mini_scale, expected, places=5)
                self.assertEqual(self.station.pos(), anchor)
                self.assertEqual(self.station.active, 2)
                self.assertFalse(self.station.expanded)
                self.assertFalse(self.station.mini.timer.isActive())
                saved = json.loads((quota_app.STATE / "settings.json").read_text(encoding="utf-8"))
                self.assertAlmostEqual(saved["mini_scale"], expected, places=5)
        self.wait_for_click()
        self.assertEqual(self.station.active, 2)

    def test_resize_grip_click_and_double_click_do_not_trigger_body_actions(self):
        self.station.move(100, 100)
        grip = self.station.mini.resize_grip
        anchor = self.station.pos()
        QTest.mouseClick(grip, LEFT)
        QTest.mouseDClick(grip, LEFT)
        QTest.mouseRelease(grip, LEFT)
        self.wait_for_click()
        self.assertEqual(self.station.mini_scale, 1.0)
        self.assertEqual(self.station.pos(), anchor)
        self.assertEqual(self.station.active, 0)
        self.assertFalse(self.station.expanded)
        self.assertFalse(self.station.mini.timer.isActive())

    def test_scale_persists_and_ball_reuses_it_with_hidden_grip(self):
        self.station.move(100, 100)
        self.station.set_mini_scale(1.4, persist=True)
        self.station.set_shape("ball")
        self.qt.processEvents()
        self.assertFalse(self.station.mini.resize_grip.isVisible())
        self.assertAlmostEqual(self.station.mini.width(), 124 * 1.4, delta=1)
        self.assertAlmostEqual(self.station.mini.height(), 124 * 1.4, delta=1)
        restored = quota_app.Station(offline=True)
        try:
            restored.poll.stop()
            restored.clock.stop()
            restored.show()
            self.qt.processEvents()
            self.assertAlmostEqual(restored.mini_scale, 1.4)
            self.assertEqual(restored.shape, "ball")
            self.assertFalse(restored.mini.resize_grip.isVisible())
            restored.set_shape("card")
            self.qt.processEvents()
            self.assertTrue(restored.mini.resize_grip.isVisible())
            self.assertAlmostEqual(restored.mini.width(), 138 * 1.4, delta=1)
            self.assertAlmostEqual(restored.mini.height(), 116 * 1.4, delta=1)
        finally:
            restored.mini.timer.stop()
            restored.poll.stop()
            restored.clock.stop()
            restored.tray.hide()
            restored.close()
            restored.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            self.qt.processEvents()

    def test_body_click_and_double_click_still_work_after_resize(self):
        self.station.move(100, 100)
        self.station.set_mini_scale(1.5)
        self.qt.processEvents()
        QTest.mouseClick(self.station.mini, LEFT)
        self.wait_for_click()
        self.assertEqual(self.station.active, 1)
        self.double_click(min(80, max(1, self.native_double_interval // 3)))
        self.assertTrue(self.station.expanded)
        self.assertEqual(self.station.active, 1)
        self.station.collapse()
        self.assertAlmostEqual(self.station.mini_scale, 1.5)
        self.assertEqual(self.station.active, 1)

    def test_refresh_failure_keeps_last_value_then_accepts_actual_zero(self):
        old = snapshot(0, 72.0)
        self.station.receive(0, quota_app.validate_snapshot(old), "")
        self.station.busy.add(0)
        self.station.render()
        self.assertEqual(self.station.mini.value.text(), "72%")
        self.station.receive(0, None, "临时无法连接")
        self.assertEqual(self.station.snapshots[0], old)
        self.assertEqual(self.station.mini.value.text(), "72%")
        self.assertEqual(self.station.mini.unit.text(), "上次余额")
        self.assertEqual(self.station.rows[0][3].text(), "更新失败")
        self.assertNotIn(0, self.station.busy)
        self.station.receive(0, quota_app.validate_snapshot(snapshot(0, 0.0)), "")
        self.assertEqual(self.station.mini.value.text(), "0%")
        self.assertEqual(self.station.mini.unit.text(), "本周剩余")
        self.assertNotIn(0, self.station.errors)
        self.assertEqual(self.station.rows[0][4].value(), 0)

    def test_initial_failure_is_unavailable_and_credit_zero_is_visible(self):
        self.station.cycle(2)
        self.station.receive(2, None, "未连接")
        self.assertEqual(self.station.mini.value.text(), "—")
        self.assertEqual(self.station.mini.unit.text(), "待连接")
        self.station.receive(2, quota_app.validate_snapshot(snapshot(2, 0.0)), "")
        self.assertEqual(self.station.mini.value.text(), "0")
        self.assertNotIn(2, self.station.errors)
        for invalid in (None, False, float("nan"), -1.0):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                quota_app.validate_snapshot(snapshot(2, invalid))

    def test_render_synthetic_card_and_paper_in_memory(self):
        for index, balance in enumerate((72.0, 1280.0, 3560.0)):
            self.station.receive(index, snapshot(index, balance), "")
        for expanded in (False, True):
            if expanded:
                self.station.expand()
            self.qt.processEvents()
            pixmap = QPixmap(self.station.size())
            pixmap.fill(Qt.GlobalColor.transparent)
            QWidget.render(self.station, pixmap)
            self.assertFalse(pixmap.isNull())
            self.assertGreater(pixmap.width(), 100)
            self.assertGreater(pixmap.height(), 100)
            # Export only when explicitly requested; never capture the desktop.
            artifact_dir = os.environ.get("QUOTA_TEST_RENDER_DIR")
            if artifact_dir:
                destination = Path(artifact_dir).resolve()
                if not destination.is_relative_to(quota_app.BASE.resolve()):
                    self.fail("Render directory must stay within this project")
                destination.mkdir(parents=True, exist_ok=True)
                self.assertTrue(pixmap.save(str(destination / ("paper.png" if expanded else "card.png"))))


if __name__ == "__main__":
    unittest.main()
