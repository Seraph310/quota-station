"""Synthetic quota groups and official-client connection boundaries."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from providers import antigravity_provider as provider


def quotas(fraction=0.42):
    return {'response': {'groups': [
        {'displayName': 'Gemini Models', 'buckets': [
            {'window': 'weekly', 'remainingFraction': fraction, 'resetTime': '2026-11-26T15:00:00Z'},
            {'window': '5h', 'remainingFraction': 0.02},
        ]},
        {'displayName': 'Claude and GPT models', 'buckets': [
            {'window': 'weekly', 'remainingFraction': 0.01},
        ]},
        {'displayName': 'Gemini 4 Argon', 'buckets': [
            {'window': 'weekly', 'remainingFraction': 0.8},
        ]},
    ]}}


class AntigravityTests(unittest.TestCase):
    def test_card_selects_gemini_and_argon_weekly_only(self):
        result = provider.normalize(quotas(), 'one@example.test', now=123)
        self.assertEqual(result['balance'], 42)
        self.assertEqual(result['subtitle'], '本周剩余')
        self.assertEqual([(item['model'], item['balance']) for item in result['weekly_quotas']],
                         [('Gemini', 42), ('Argon', 80)])
        self.assertEqual(result['updated_at'], 123)
        self.assertEqual(len(result['details']), 6)
        self.assertNotEqual(result['account_key'], provider.normalize(quotas(), 'two@example.test')['account_key'])

    def test_unknown_disabled_and_zero_are_distinct(self):
        self.assertEqual(provider.normalize(quotas(0), 'one@example.test')['balance'], 0)
        for fraction in (None, True, '0.5', float('nan'), -0.1, 1.1):
            data = quotas(fraction)
            data['response']['groups'][0]['buckets'][1]['disabled'] = True
            with self.subTest(fraction=fraction):
                result = provider.normalize(data, 'one@example.test')
                self.assertEqual(result['balance'], 80)
                self.assertIsNone(result['weekly_quotas'][0]['balance'])
                self.assertEqual(result['details'][2]['value'], '暂不可用')
        with self.assertRaisesRegex(RuntimeError, '可确认'):
            provider.normalize({'response': {'groups': []}}, 'one@example.test')

    def test_old_cache_retains_both_weekly_quotas_and_original_time(self):
        old = {'source': 'antigravity', 'balance': 2, 'unit': '%', 'updated_at': 123,
               'subtitle': 'Gemini · 5 小时剩余', 'details': [
                   {'label': 'Gemini · 本周', 'value': '剩余 96.5176% · 11-26 23:06 重置'},
                   {'label': 'Argon · 本周', 'value': '剩余 0%'},
                   {'label': 'Gemini · 5 小时', 'value': '剩余 2%'},
               ]}
        result = provider.display_snapshot(old)
        self.assertEqual([q['balance'] for q in result['weekly_quotas']], [96.5176, 0])
        self.assertEqual(result['balance'], 0)
        self.assertEqual(result['updated_at'], 123)
        self.assertEqual(old['balance'], 2)

    def test_switching_accounts_during_a_read_discards_the_result(self):
        with patch.object(provider, '_server', return_value={}), \
             patch.object(provider, '_account', side_effect=['one@example.test', 'two@example.test']), \
             patch.object(provider, '_request', return_value=quotas()):
            with self.assertRaisesRegex(RuntimeError, '账号已切换'):
                provider.fetch()

    def test_fetch_uses_only_the_official_local_quota_methods(self):
        user = {'userStatus': {'email': 'one@example.test'}}
        with patch.object(provider, '_server', return_value={'httpPort': 5678}), \
             patch.object(provider, '_request', side_effect=[user, quotas(), user]) as call:
            self.assertEqual(provider.fetch()['balance'], 42)
        self.assertEqual([c.args[1] for c in call.call_args_list],
                         ['GetUserStatus', 'RetrieveUserQuotaSummary', 'GetUserStatus'])
        self.assertEqual(call.call_args_list[1].args[2], {'request': {}, 'forceRefresh': True})

    def test_discovery_rejects_stale_and_invalid_process_records(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.dict('os.environ', ANTIGRAVITY_HOME=directory), \
             patch.object(provider, 'process_alive', return_value=False) as alive:
            root = Path(directory) / 'daemon'
            root.mkdir()
            path = root / 'hub_1234.json'
            marker = {'pid': 100, 'httpPort': 1234, 'csrfToken': 'synthetic'}
            path.write_text(json.dumps(marker))
            with self.assertRaisesRegex(RuntimeError, '已关闭'):
                provider._server()
            alive.return_value = True
            self.assertEqual(provider._server(), marker)
            for key, value in [('pid', True), ('httpPort', 70000), ('csrfToken', 'bad\r\nheader')]:
                path.write_text(json.dumps({**marker, key: value}))
                with self.subTest(key=key), self.assertRaisesRegex(RuntimeError, '已关闭'):
                    provider._server()

    def test_transport_is_loopback_without_proxies_or_redirects(self):
        with patch.object(provider.urllib.request, 'build_opener') as build:
            build.return_value.open.return_value.__enter__.return_value.read.return_value = b'{}'
            provider._request({'httpPort': 1234, 'csrfToken': 'synthetic'}, 'GetUserStatus', {})
        request = build.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url, 'http://127.0.0.1:1234/exa.language_server_pb.LanguageServerService/GetUserStatus')
        self.assertEqual(build.call_args.args[0].proxies, {})
        with self.assertRaises(RuntimeError):
            build.call_args.args[1].redirect_request()
