"""Synthetic WorkBuddy profiles and accessibility controls."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from providers import workbuddy_provider as provider
from providers import _workbuddy_windows as windows


class WorkBuddyTests(unittest.TestCase):
    def test_active_selector_not_newest_directory_or_nickname(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ', WORKBUDDY_HOME=tmp):
            root = Path(tmp)
            path = root / 'storage/skeleton/account-snapshot.json'
            path.parent.mkdir(parents=True)
            (root / 'storage/user-unrelated-personal').mkdir()
            def select(uid, team=''):
                path.write_text(json.dumps({'primary': {'uid': uid, 'type': 'personal',
                    'enterpriseId': team, 'nickname': 'Shared name'}}), 'utf-8')
                return provider.current_account()
            a = select('first')
            self.assertNotEqual(a.key, select('second').key)
            self.assertNotEqual(a.key, select('first', 'team').key)
            self.assertEqual(a, select('first'))
            self.assertNotIn('first', a.key)
            for raw in ('{}', 'null', '{"primary":null}', '{', ' ' * 4097):
                path.write_text(raw, 'utf-8')
                self.assertIsNone(provider.current_account())
            path.unlink()
            self.assertIsNone(provider.current_account())

    def test_zero_decimals_unlimited_and_unavailable(self):
        self.assertEqual(provider.parse_amount('0'), (0, 'available'))
        self.assertEqual(provider.parse_amount('28,710.23'), (28710.23, 'available'))
        self.assertEqual(provider.parse_amount('Unlimited'), (None, 'unlimited'))
        for value in ('—', '…', 'N/A', 'NaN', '-5', '99,2', '0%', '买 500 积分'):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                provider.parse_amount(value)

    def test_switch_during_read_drops_the_result(self):
        a, b = provider.Account('first', 'A'), provider.Account('second', 'B')
        with patch.object(provider, 'current_account', side_effect=[a, b]), \
             patch.object(provider.os, 'name', 'nt'), patch.object(windows, 'read_balance', return_value='812.4'):
            with self.assertRaisesRegex(RuntimeError, '账号已切换'):
                provider.fetch()

    def test_fetch_attaches_the_current_account_to_the_balance(self):
        a = provider.Account('first', 'A')
        with patch.object(provider, 'current_account', return_value=a), \
             patch.object(provider.os, 'name', 'nt'), patch.object(windows, 'read_balance', return_value='0'):
            result = provider.fetch()
        self.assertEqual((result['account_key'], result['balance'], result['source']), ('first', 0, 'workbuddy'))


class Node:
    def __init__(self, role, name='', children=(), action=None):
        self.role, self.name = role, name
        self.items = list(children)
        self.activate = Mock(side_effect=action)

    def children(self):
        return self.items


class MenuTests(unittest.TestCase):
    def setUp(self):
        self.account = provider.Account('first', 'Sample')
        self.refresh = Node(windows.BUTTON, '刷新')
        self.cell = Node(windows.BUTTON, '积分余额 2,315.23 刷新 购买积分', [self.refresh])
        self.popup = Node(windows.MENU_POPUP, children=[Node(windows.TEXT, 'Sample'), self.cell])
        self.trigger = Node(windows.MENU_BUTTON, 'Sample Sample', action=self.toggle)
        self.anchor = Node(20, children=[self.trigger])
        acc = patch.object(windows, 'current_account', return_value=self.account)
        acc.start()
        self.addCleanup(acc.stop)
        sleep = patch.object(windows.time, 'sleep')
        sleep.start()
        self.addCleanup(sleep.stop)

    def toggle(self):
        self.anchor.items = [self.trigger] if self.popup in self.anchor.items else [self.trigger, self.popup]

    def read(self):
        return windows._read_menu(self.anchor, self.trigger, self.account)

    def test_closed_menu_is_opened_for_new_usage_and_restored(self):
        self.assertEqual(self.read(), '2,315.23')
        self.refresh.activate.assert_not_called()
        self.assertEqual(self.anchor.items, [self.trigger])

    def test_user_opened_menu_stays_open(self):
        self.toggle()
        self.assertEqual(self.read(), '2,315.23')
        self.trigger.activate.assert_not_called()
        self.refresh.activate.assert_called_once()

    def test_wrong_profile_stale_and_unloaded_rows_are_ignored(self):
        for profile, name in [('Other', '积分余额 15 刷新'), ('Sample', '积分余额 15 非最新 刷新'),
                              ('Sample', '积分余额 获取失败 购买积分')]:
            self.popup.items[0].name = profile
            self.cell.name = name
            with self.subTest(name=name), patch.object(windows.time, 'monotonic', side_effect=[0, 1, 2, 10]):
                with self.assertRaisesRegex(RuntimeError, '尚未显示'):
                    self.read()
            self.assertEqual(self.anchor.items, [self.trigger])

    def test_unknown_panel_is_restored_and_invite_amount_is_ignored(self):
        self.popup.items[1] = Node(windows.BUTTON, '去邀约 最高得 650 积分/人')
        with patch.object(windows.time, 'monotonic', side_effect=[0, 1, 10]), self.assertRaises(RuntimeError):
            self.read()
        self.assertEqual(self.anchor.items, [self.trigger])
