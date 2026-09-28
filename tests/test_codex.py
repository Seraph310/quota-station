"""Quota semantics and read-only protocol checks; no network or model use."""

import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from providers import codex_provider as provider


def window(used, minutes=10080, reset=1790000000):
    return {"usedPercent": used, "windowDurationMins": minutes, "resetsAt": reset}


def payload(primary=None, secondary=None):
    return {"rateLimitsByLimitId": {"codex": {"primary": primary, "secondary": secondary}}}


class ParserTests(unittest.TestCase):
    def test_week_is_preferred_and_both_windows_are_retained(self):
        result = provider.parse_rate_limits(payload(window(30, 300), window(7)), now=10)
        self.assertEqual(result["balance"], 93)
        self.assertEqual(result["subtitle"], "本周剩余")
        self.assertEqual(len(result["details"]), 2)
        self.assertIn("5小时窗口", result["details"][0]["label"])
        self.assertEqual(result["updated_at"], 10)

    def test_multi_bucket_view_wins_over_legacy(self):
        data = payload(window(20))
        data["rateLimits"] = {"primary": window(99)}
        self.assertEqual(provider.parse_rate_limits(data)["balance"], 80)

    def test_codex_bucket_wins_over_other_week(self):
        data = payload(window(40, 60))
        data["rateLimitsByLimitId"]["other"] = {"primary": window(1)}
        result = provider.parse_rate_limits(data)
        self.assertEqual(result["balance"], 60)
        self.assertEqual(result["subtitle"], "1小时窗口剩余")
        self.assertEqual(len(result["details"]), 2)

    def test_null_percent_does_not_mean_unused(self):
        data = payload(window(None, 300), window(15))
        result = provider.parse_rate_limits(data)
        self.assertEqual(result["balance"], 85)
        self.assertIn("暂不可用", result["details"][0]["value"])

    def test_missing_percent_is_an_error_not_zero(self):
        for value in (None, True, "0", float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                provider.parse_rate_limits(payload(window(value)))

    def test_empty_multi_view_does_not_fall_back_to_legacy(self):
        with self.assertRaises(RuntimeError):
            provider.parse_rate_limits({"rateLimitsByLimitId": {}, "rateLimits": {"primary": window(1)}})

    def test_malformed_or_missing_result_is_error(self):
        for data in (None, [], {}, {"rateLimitsByLimitId": []}):
            with self.subTest(data=data), self.assertRaises(RuntimeError):
                provider.parse_rate_limits(data)

    def test_legacy_and_real_duration_are_supported(self):
        result = provider.parse_rate_limits({"rateLimits": {"primary": window(0, 15, None)}})
        self.assertEqual(result["balance"], 100)
        self.assertEqual(result["subtitle"], "15分钟窗口剩余")
        self.assertIsNone(result["reset_at"])

    def test_unknown_duration_is_not_invented(self):
        result = provider.parse_rate_limits(payload(window(10, None)))
        self.assertEqual(result["subtitle"], "主额度窗口剩余")

    def test_remaining_percent_is_clamped(self):
        self.assertEqual(provider.parse_rate_limits(payload(window(105)))["balance"], 0)
        self.assertEqual(provider.parse_rate_limits(payload(window(-2)))["balance"], 100)

    def test_credits_and_reset_count_preserve_zero(self):
        data = payload(window(7))
        data["rateLimitsByLimitId"]["codex"]["credits"] = {"balance": "0", "unlimited": False}
        data["rateLimitResetCredits"] = {"availableCount": 0, "credits": []}
        details = provider.parse_rate_limits(data)["details"]
        self.assertIn({"label": "Codex · Credits", "value": "0"}, details)
        self.assertIn({"label": "可用额度重置次数", "value": "0 次"}, details)

    def test_unavailable_credit_balance_does_not_mean_zero(self):
        data = payload(window(7))
        data["rateLimitsByLimitId"]["codex"]["credits"] = {"balance": None, "unlimited": False}
        self.assertIn({"label": "Codex · Credits", "value": "暂不可用"},
                      provider.parse_rate_limits(data)["details"])


class RecordingInput(io.StringIO):
    def __init__(self):
        super().__init__()
        self.sent = []

    def write(self, value):
        self.sent.append(json.loads(value))
        return super().write(value)


class FakeProcess:
    def __init__(self, responses):
        self.stdin = RecordingInput()
        self.stdout = io.StringIO("\n".join(json.dumps(r) for r in responses) + "\n")
        self.waited = False

    def wait(self, timeout=None):
        self.waited = True
        return 0


class ProtocolTests(unittest.TestCase):
    def test_only_initialize_and_read_are_sent_and_process_is_closed(self):
        child = FakeProcess([{"id": 1, "result": {}}, {"id": 2, "result": payload(window(7))}])
        with patch.object(provider, "_find_executable", return_value=Path("codex.exe")), \
                patch.object(provider.subprocess, "Popen", return_value=child) as spawn:
            result = provider.fetch()
        self.assertEqual(result["balance"], 93)
        self.assertEqual([m["method"] for m in child.stdin.sent],
                         ["initialize", "initialized", "account/rateLimits/read"])
        self.assertTrue(child.stdin.closed and child.stdout.closed and child.waited)
        command = spawn.call_args.args[0]
        self.assertIn("features.plugins=false", command)
        self.assertIn("features.apps=false", command)
        self.assertIn("mcp_servers={}", command)
        self.assertNotIn("shell", spawn.call_args.kwargs)

    def test_upstream_error_does_not_leak_sensitive_message(self):
        child = FakeProcess([{"id": 1, "result": {}},
                             {"id": 2, "error": {"code": 401, "message": "secret-test-token"}}])
        with patch.object(provider, "_find_executable", return_value=Path("codex.exe")), \
                patch.object(provider.subprocess, "Popen", return_value=child):
            with self.assertRaises(RuntimeError) as caught:
                provider.fetch()
        self.assertNotIn("secret-test-token", str(caught.exception))
        self.assertTrue(child.waited and child.stdout.closed)


if __name__ == "__main__":
    unittest.main()
