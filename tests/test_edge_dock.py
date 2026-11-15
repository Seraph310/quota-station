"""Monitor geometry boundaries independent of the host's physical screen layout."""
import unittest

from PySide6.QtCore import QPoint, QRect

from edge_dock import nearest_screen, outside_edge


class Screen:
    def __init__(self, area):
        self.area = area

    def geometry(self):
        return self.area


class EdgeGeometryTests(unittest.TestCase):
    def test_touch_and_shadow_only_crossing_do_not_dock(self):
        area = QRect(0, 0, 1920, 1080)
        self.assertIsNone(outside_edge(QRect(0, 300, 138, 116), area, [], 350))
        self.assertIsNone(outside_edge(QRect(-11, 300, 138, 116), area, [], 350))
        self.assertEqual(outside_edge(QRect(-12, 300, 138, 116), area, [], 350), 'left')
        self.assertEqual(outside_edge(QRect(1810, 300, 138, 116), area, [], 350), 'right')

    def test_crossing_adjacent_monitor_seam_does_not_dock(self):
        left, right = QRect(-1920, 0, 1920, 1080), QRect(0, 0, 2560, 1440)
        self.assertIsNone(outside_edge(QRect(-60, 300, 138, 116), left, [right], 350))
        self.assertIsNone(outside_edge(QRect(-60, 300, 138, 116), right, [left], 350))
        self.assertEqual(outside_edge(QRect(-1950, 300, 138, 116), left, [right], 350), 'left')

    def test_exposed_part_of_offset_monitor_is_still_an_edge(self):
        left, right = QRect(0, 0, 1920, 1080), QRect(1920, 400, 2560, 1440)
        self.assertEqual(outside_edge(QRect(1850, 100, 138, 116), left, [right], 150), 'right')
        self.assertIsNone(outside_edge(QRect(1850, 500, 138, 116), left, [right], 550))

    def test_offscreen_release_uses_nearest_screen_not_primary(self):
        primary = Screen(QRect(0, 0, 1920, 1080))
        secondary = Screen(QRect(-2560, -200, 2560, 1440))
        self.assertIs(nearest_screen(QPoint(-2700, 500), [primary, secondary]), secondary)
        self.assertIs(nearest_screen(QPoint(2300, 500), [primary, secondary]), primary)
        self.assertIs(nearest_screen(QPoint(-1200, -400), [primary, secondary]), secondary)


if __name__ == '__main__':
    unittest.main()
