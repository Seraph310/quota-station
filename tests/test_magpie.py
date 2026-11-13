"""Synthetic tests for the Magpie adapter's quota and account boundaries."""
import json
import unittest
from unittest.mock import patch

from providers import magpie_provider as magpie
from app import number_text, validate_snapshot


def account(user='one@example.test', **overrides):
    value = {'provider': 'codex', 'name': 'Codex', 'kind': 'subscription',
             'user': user, 'readAt': '2026-11-12T06:00:00Z',
             'windows': [{'name': '7 days', 'remaining': 72,
                          'resetsAt': '2026-11-17T08:00:00Z'}]}
    value.update(overrides)
    return value


class MagpieTests(unittest.TestCase):
    def test_account_ids_survive_reordering_and_alias_changes(self):
        first, second = account(), account('two@example.test')
        before = magpie.normalize({'data': [first, second]})
        first['alias'] = 'My account'
        after = magpie.normalize([second, first])
        self.assertNotEqual(before[0]['id'], before[1]['id'])
        self.assertEqual(before[0]['id'], after[1]['id'])
        self.assertEqual(before[1]['id'], after[0]['id'])
        self.assertEqual(after[1]['account'], 'My account')
        self.assertNotIn('@', before[0]['id'])

    def test_primary_window_does_not_use_unknown_image_percentage(self):
        source = magpie.normalize([account(windows=[
            {'name': 'Image generation', 'text': True, 'display': 'Unknown', 'remaining': 100},
            {'name': '5 hours', 'remaining': 86}, {'name': '7 days', 'remaining': 12},
        ])])[0]
        self.assertEqual(source['snapshot']['balance'], 12)
        self.assertEqual(source['snapshot']['subtitle'], '本周剩余')
        self.assertIn({'label': '图片生成', 'value': '暂无数据'}, source['snapshot']['details'])

    def test_credits_use_remaining_amount_and_do_not_add_overlapping_pools(self):
        source = magpie.normalize([account(provider='codearts', windows=[
            {'name': '总积分', 'remaining': 79.7, 'limit': 5700, 'amount': 1156.19, 'unit': 'credits'},
            {'name': '基础积分包', 'remaining': 100, 'limit': 500, 'unit': 'credits'},
        ])])[0]
        self.assertAlmostEqual(source['snapshot']['balance'], 4543.81)
        self.assertEqual(source['snapshot']['unit'], 'Credits')
        self.assertEqual(len(source['snapshot']['details']), 4)

    def test_currency_zero_negative_and_balance_breakdown(self):
        for raw, expected in [('¥0.00', 0), ('$-1.10', -1.1), ('1.2K credits', 1200), ('￥13.75', 13.75)]:
            with self.subTest(raw=raw):
                source = magpie.normalize([account(provider='deepseek', kind='balance', windows=[], balance=raw,
                    balanceSplit=[{'label': 'Granted', 'text': '¥4.35'}])])[0]
                snapshot = validate_snapshot(source['snapshot'])
                self.assertEqual(snapshot['balance'], expected)
                self.assertTrue(number_text(snapshot))
                self.assertIn({'label': '赠送余额', 'value': '¥4.35'}, snapshot['details'])
        self.assertEqual(number_text(magpie.normalize([account(windows=[], balance='$-1.10')])[0]['snapshot']), '$-1.10')

    def test_unknown_and_vendor_errors_do_not_become_zero_or_leak_credentials(self):
        for extra in ({'windows': []}, {'windows': [{'name': 'images', 'text': True, 'remaining': 100}]},
                      {'balance': 'Unknown', 'windows': []},
                      {'error': 'Authorization: Bearer private-token'}):
            with self.subTest(extra=extra):
                source = magpie.normalize([account(**extra)])[0]
                self.assertIsNone(source['snapshot'])
                self.assertTrue(source['error'])
                self.assertNotIn('private-token', json.dumps(source))

    def test_unlimited_and_original_read_time_are_preserved(self):
        source = magpie.normalize([account(windows=[{'name': 'Plan', 'unlimited': True}])], now=999)[0]
        value = validate_snapshot(source['snapshot'])
        self.assertEqual(number_text(value), '不限量')
        self.assertEqual(value['updated_at'], magpie.timestamp('2026-11-12T06:00:00Z'))

    def test_partial_error_keeps_other_accounts_and_unknown_fields_are_not_saved(self):
        source = account()
        source['accessToken'] = 'secret-value'
        values = magpie.normalize([source, account('two', error='expired')])
        self.assertEqual(values[0]['snapshot']['balance'], 72)
        self.assertIsNone(values[1]['snapshot'])
        self.assertNotIn('secret-value', json.dumps(values))

    def test_network_fallback_only_reads_cli_quota(self):
        with patch.object(magpie, '_gateway', side_effect=OSError()), \
             patch.object(magpie, 'discover_executable', return_value='magpie.exe'), \
             patch.object(magpie, '_cli', return_value=[account()]) as cli:
            self.assertEqual(magpie.fetch()[0]['snapshot']['balance'], 72)
            cli.assert_called_once_with('magpie.exe')
        completed = type('Result', (), {'returncode': 0, 'stdout': b'[]'})()
        with patch.object(magpie, 'discover_executable', return_value='magpie.exe'), \
             patch.object(magpie.subprocess, 'run', return_value=completed) as run:
            self.assertEqual(magpie._cli(), [])
            self.assertEqual(run.call_args.args[0], ['magpie.exe', 'quota', '--json'])

    def test_sync_discovers_current_path_and_custom_gateway_without_changing_accounts(self):
        with patch.object(magpie, 'discover_executable', return_value='D:/Apps/Magpie/magpie.exe') as discover, \
             patch.object(magpie, '_status', return_value={'url': 'http://127.0.0.1:4567', 'version': '1.2.3'}), \
             patch.object(magpie, '_gateway', return_value={'data': [account()]}) as gateway, \
             patch.object(magpie, '_cli') as cli:
            result = magpie.synchronize({'executable': 'C:/old/magpie.exe', 'port': 3425})
            discover.assert_called_once_with('C:/old/magpie.exe', rediscover=True)
            gateway.assert_called_once_with(4567)
            cli.assert_not_called()
            self.assertEqual(result['connection']['executable'], 'D:/Apps/Magpie/magpie.exe')
            self.assertEqual(result['connection']['version'], '1.2.3')
            self.assertEqual(result['connection']['source_count'], 1)
            self.assertEqual(result['connection']['transport'], 'gateway')

    def test_sync_reads_cli_when_app_is_not_running_and_reports_partial_accounts(self):
        with patch.object(magpie, 'discover_executable', return_value='D:/magpie.exe'), \
             patch.object(magpie, '_status', return_value={'running': False}), \
             patch.object(magpie, '_gateway', side_effect=OSError()), \
             patch.object(magpie, '_cli', return_value=[account(), account('other', error='expired')]) as cli:
            result = magpie.synchronize()
            cli.assert_called_once_with('D:/magpie.exe')
            self.assertEqual(result['connection']['transport'], 'cli')
            self.assertEqual(result['connection']['source_count'], 2)
            self.assertEqual(result['connection']['readable_count'], 1)

    def test_sync_failure_keeps_discovered_path_without_claiming_a_new_success(self):
        with patch.object(magpie, 'discover_executable', return_value='D:/magpie.exe'), \
             patch.object(magpie, '_status', return_value={}), \
             patch.object(magpie, '_gateway', side_effect=OSError()), \
             patch.object(magpie, '_cli', side_effect=RuntimeError('读取失败')):
            with self.assertRaises(magpie.SyncError) as caught:
                magpie.synchronize({'synced_at': 123})
            self.assertEqual(caught.exception.connection['executable'], 'D:/magpie.exe')
            self.assertEqual(caught.exception.connection['synced_at'], 123)

    def test_gateway_only_install_syncs_without_inventing_an_executable(self):
        with patch.object(magpie, 'discover_executable', return_value=None), \
             patch.object(magpie, '_status', return_value={}), \
             patch.object(magpie, '_gateway', return_value=[]):
            result = magpie.synchronize()
            self.assertEqual(result['connection']['executable'], '')
            self.assertEqual(result['sources'], [])

    def test_status_port_does_not_use_remote_url_credentials_or_invalid_ports(self):
        self.assertEqual(magpie._status_port({'url': 'http://user:secret@192.0.2.1:4567'}), 4567)
        for url in ['https://localhost:3425', 'http://localhost:99999', None]:
            self.assertIsNone(magpie._status_port({'url': url}))

    def test_malformed_payload_and_duplicate_identity_rejected(self):
        for payload in ({'data': {}}, None, [account(), account()]):
            with self.subTest(payload=payload), self.assertRaises(RuntimeError):
                magpie.normalize(payload)


if __name__ == '__main__':
    unittest.main()
