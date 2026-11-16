"""Language changes must preserve identity, cached quotas, docking and settings."""
import ast
import copy
import json
import os
from pathlib import Path
from string import Formatter
import unittest
from unittest.mock import patch

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PySide6.QtWidgets import QApplication

import app
import i18n
from demo import demo_state, demo_sources
from updater_ui import UpdateDialog


class TranslationTests(unittest.TestCase):
    def tearDown(self):
        i18n.set_language('zh-CN')

    def test_system_language_and_unknown_preferences(self):
        with patch.object(i18n, 'system_language', return_value='en'):
            self.assertEqual(i18n.set_language('auto'), 'auto')
            self.assertEqual(i18n.tr('显示来源'), 'Sources')
            self.assertEqual(i18n.set_language('invalid'), 'auto')
        with patch.object(i18n, 'system_language', return_value='zh-CN'):
            i18n.set_language('auto')
            self.assertEqual(i18n.tr('显示来源'), '显示来源')
            i18n.set_language('en')
            self.assertEqual(i18n.tr('显示来源'), 'Sources')

    def test_cached_messages_and_template_parameters(self):
        i18n.set_language('en')
        examples = {
            '已同步 6 个来源 · 2 个暂不可用': 'Synced 6 sources · 2 unavailable',
            '2天窗口剩余': '2-day window remaining',
            '剩余 42% · 11-16 18:00 重置': '42% remaining · Resets 11-16 18:00',
            '正在下载  45%': 'Downloading  45%',
            '升级未完成，已保留原版本。新版本启动超时': 'Update failed; the previous version was kept. The new version timed out during startup',
            'WorkBuddy 查询暂时失败（HTTP 503）': 'WorkBuddy query failed (HTTP 503)',
            'My custom quota': 'My custom quota',
        }
        for source, expected in examples.items():
            self.assertEqual(i18n.tr(source), expected)
        for source, target in i18n.TEMPLATES.items():
            fields = lambda text: {field for _, field, _, _ in Formatter().parse(text) if field}
            self.assertEqual(fields(source), fields(target), source)

    def test_safe_provider_and_updater_errors_have_translations(self):
        root = Path(__file__).resolve().parents[1]
        files = [root / 'app.py', root / 'updater_core.py', *sorted((root / 'providers').glob('*.py'))]
        i18n.set_language('en')
        for path in files:
            tree = ast.parse(path.read_text('utf-8'))
            for node in ast.walk(tree):
                if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call) and node.exc.args:
                    message = node.exc.args[0]
                    if isinstance(message, ast.Constant) and isinstance(message.value, str) and any('\u4e00' <= c <= '\u9fff' for c in message.value):
                        self.assertNotEqual(i18n.tr(message.value), message.value, f'{path.name}:{node.lineno}')


class LanguageUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])
        app.setup_fonts(cls.qt)

    def setUp(self):
        self.context = demo_state('zh-CN')
        self.context.__enter__()
        self.station = app.Station(offline=True)
        self.station.receive_sources(demo_sources(), '')
        self.station.poll.stop()
        self.station.clock.stop()

    def tearDown(self):
        if self.station.source_picker:
            self.station.source_picker.close()
        if self.station.updater.dialog:
            self.station.updater.dialog.close()
        self.station.poll.stop()
        self.station.clock.stop()
        self.station.tray.hide()
        self.station.close()
        self.station.deleteLater()
        self.qt.processEvents()
        self.context.__exit__(None, None, None)
        i18n.set_language('zh-CN')

    def test_menu_switch_retranslates_open_windows_without_changing_quota_data(self):
        station = self.station
        station.show_sources()
        station.updater.source_mode = False
        station.updater.release = {'version': '99.0.0', 'newer': True, 'notes': 'English / 中文 release notes'}
        station.updater.state, station.updater.message = 'available', '新版本  v99.0.0'
        station.updater.dialog = UpdateDialog(station.updater)
        station.updater.dialog.show()
        station.docking.dock('right', self.qt.primaryScreen())
        station.set_mini_scale(1.2)
        before = copy.deepcopy((station.sources, station.snapshots, station.visible_sources, station.active_key, station.docking.settings()))
        station.language_actions['en'].trigger()
        self.qt.processEvents()
        self.assertEqual(station.windowTitle(), 'Quota Station')
        self.assertEqual(station.mini.unit.text(), 'Weekly remaining')
        self.assertEqual(station.sources_button.text(), 'Sources')
        self.assertEqual(station.source_picker.done_button.text(), 'Done')
        self.assertEqual(station.source_picker.count.text(), f'{len(station.visible_sources)} selected')
        self.assertEqual(station.updater.dialog.action.text(), 'Update now')
        self.assertEqual(station.updater.dialog.status.text(), 'New version  v99.0.0')
        station.updater.source_mode = True
        station.updater.sync()
        self.qt.processEvents()
        button = station.updater.dialog.action
        self.assertGreaterEqual(button.width(), button.fontMetrics().horizontalAdvance('Install desktop app') + 32)
        station.updater.source_mode = False
        station.updater.sync()
        self.assertIn('Hover to peek', station.docking.bar.accessibleName())
        self.assertIn('Source: Local clients', station.details_text(0))
        self.assertEqual(before, (station.sources, station.snapshots, station.visible_sources, station.active_key, station.docking.settings()))
        self.assertEqual(json.loads((app.STATE / 'settings.json').read_text('utf-8'))['language'], 'en')
        station.receive(0, None, '没有找到 Codex 命令行程序，请先安装 Codex CLI 并登录。')
        self.assertIn('Codex CLI not found', station.details_text(0))
        station.language_actions['zh-CN'].trigger()
        self.assertEqual(station.source_picker.done_button.text(), '完成')
        self.assertEqual(station.updater.dialog.action.text(), '一键升级')
        self.assertEqual(station.mini.unit.text(), '上次余额')

    def test_restart_restores_language_and_account_names_are_not_translated(self):
        station = self.station
        key = next(key for key in station.sources if isinstance(key, str))
        station.sources[key]['name'] = '显示来源'
        station.snapshots[key]['details'].append({'label': '账号', 'value': '显示来源'})
        station.set_language('en')
        self.assertEqual(station.source_name(key), '显示来源')
        self.assertIn('Account: 显示来源', station.details_text(key))
        station.tray.hide()
        station.close()
        restored = app.Station(offline=True)
        try:
            self.assertEqual(restored.language, 'en')
            self.assertEqual(restored.sources_button.text(), 'Sources')
            self.assertEqual(restored.visible_sources, station.visible_sources)
        finally:
            restored.poll.stop()
            restored.clock.stop()
            restored.tray.hide()
            restored.close()
            restored.deleteLater()

    def test_english_card_labels_fit_at_minimum_and_maximum_scale(self):
        station = self.station
        station.set_language('en')
        station.show()
        for scale in (0.8, 1.0, 2.0):
            station.set_mini_scale(scale)
            for index in range(len(station.visible_sources)):
                station.active = index
                station.render()
                self.qt.processEvents()
                label = station.mini.unit
                self.assertLessEqual(label.fontMetrics().horizontalAdvance(label.text()), label.contentsRect().width(), (scale, label.text()))


if __name__ == '__main__':
    unittest.main()
