"""Synthetic, offline tests: no real account values or credentials in fixtures."""

from __future__ import annotations

import base64
import json
import os
import time
import unittest
from unittest.mock import MagicMock, patch
import urllib.error

from providers import workbuddy_provider as provider
from providers import _workbuddy_windows as windows


def summary(*values):
    return {"code": 0, "data": {"Packages": [{"CycleRemainCapacity": value} for value in values]}}


class SummaryTests(unittest.TestCase):
    def test_sums_verified_numeric_values(self):
        self.assertEqual(provider._parse_summary(summary("1.25", 2.5, 0)), (3.75, 3))

    def test_explicit_zero_is_zero(self):
        self.assertEqual(provider._parse_summary(summary(0, "0")), (0.0, 2))

    def test_packages_shape_validation(self):
        for data in (None, [], {}, {"Packages": None}, {"Packages": {}}, {"Packages": []}, {"Packages": ""}):
            with self.subTest(data=data), self.assertRaises(RuntimeError):
                provider._parse_summary({"code": 0, "data": data})

    def test_one_bad_package_rejects_whole_total(self):
        for value in (None, True, False, "", "unknown", "NaN", "Infinity", float("inf"), -1, "-0.5", [], {}):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                provider._parse_summary(summary(20, value))
        for package in (None, 4, {}, []):
            with self.subTest(package=package), self.assertRaises(RuntimeError):
                provider._parse_summary({"code": 0, "data": {"Packages": [package]}})

    def test_raw_server_message_not_exposed(self):
        for payload in ({"code": 1, "msg": "SENSITIVE_VALUE"}, {"code": False}, [], None):
            with self.subTest(payload=payload):
                with self.assertRaises(RuntimeError) as caught:
                    provider._parse_summary(payload)
                self.assertNotIn("SENSITIVE_VALUE", str(caught.exception))


class FetchTests(unittest.TestCase):
    def test_legacy_cache_preferred_and_never_written(self):
        with patch.object(windows, "read_cached_token", return_value="synthetic") as read, \
             patch.object(windows, "write_cached_token") as write, \
             patch.object(windows, "find_running_token") as process, \
             patch.object(provider, "_request_summary", return_value=summary(42)) as request:
            result = provider.fetch()
        read.assert_called_once_with(provider.LEGACY_CACHE)
        write.assert_not_called()
        process.assert_not_called()
        request.assert_called_once_with("synthetic")
        self.assertEqual(result["balance"], 42.0)
        self.assertEqual(result["name"], "WorkBuddy")
        self.assertIsNone(result["reset_at"])
        self.assertGreater(result["updated_at"], 0)
        self.assertTrue(all(set(item) == {"label", "value"} for item in result["details"]))

    def test_project_cache_can_be_reused_without_running_client(self):
        with patch.object(windows, "read_cached_token", side_effect=[None, "synthetic"]) as read:
            self.assertEqual(provider._cached_token(), "synthetic")
        self.assertEqual([call.args[0] for call in read.call_args_list], [provider.LEGACY_CACHE, provider.PROJECT_CACHE])

    def test_no_credential_makes_no_network_request(self):
        with patch.object(provider, "_cached_token", return_value=None), \
             patch.object(windows, "find_running_token", return_value=None) as process, \
             patch.object(provider, "_request_summary") as request:
            with self.assertRaisesRegex(RuntimeError, "请先打开 WorkBuddy"):
                provider.fetch()
        process.assert_called_once()
        request.assert_not_called()

    def test_process_credential_cached_only_after_valid_response(self):
        with patch.object(provider, "_cached_token", return_value=None), \
             patch.object(windows, "find_running_token", return_value="synthetic"), \
             patch.object(provider, "_request_summary", return_value=summary(12)), \
             patch.object(windows, "write_cached_token") as write:
            provider.fetch()
        write.assert_called_once_with(provider.PROJECT_CACHE, "synthetic")
        self.assertTrue(provider.PROJECT_CACHE.is_relative_to(provider.PROJECT_ROOT))
        self.assertNotEqual(provider.PROJECT_CACHE, provider.LEGACY_CACHE)

    def test_invalid_response_does_not_cache_process_credential(self):
        with patch.object(provider, "_cached_token", return_value=None), \
             patch.object(windows, "find_running_token", return_value="synthetic"), \
             patch.object(provider, "_request_summary", return_value=summary()), \
             patch.object(windows, "write_cached_token") as write:
            with self.assertRaises(RuntimeError):
                provider.fetch()
        write.assert_not_called()

    def test_auth_recovery_is_bounded_to_one_new_credential(self):
        with patch.object(provider, "_cached_token", return_value="old"), \
             patch.object(windows, "find_running_token", return_value="new") as process, \
             patch.object(provider, "_request_summary", side_effect=[provider._AuthError("失效"), summary(8)]) as request, \
             patch.object(windows, "write_cached_token") as write:
            self.assertEqual(provider.fetch()["balance"], 8.0)
        self.assertEqual(request.call_count, 2)
        process.assert_called_once()
        write.assert_called_once_with(provider.PROJECT_CACHE, "new")

    def test_same_failed_credential_not_retried(self):
        with patch.object(provider, "_cached_token", return_value="same"), \
             patch.object(windows, "find_running_token", return_value="same"), \
             patch.object(provider, "_request_summary", side_effect=provider._AuthError("失效")) as request:
            with self.assertRaises(RuntimeError):
                provider.fetch()
        request.assert_called_once()

    def test_network_failure_does_not_trigger_process_scan(self):
        with patch.object(provider, "_cached_token", return_value="synthetic"), \
             patch.object(windows, "find_running_token") as process, \
             patch.object(provider, "_request_summary", side_effect=RuntimeError("网络错误")) as request:
            with self.assertRaisesRegex(RuntimeError, "网络错误"):
                provider.fetch()
        request.assert_called_once()
        process.assert_not_called()


class RequestTests(unittest.TestCase):
    def test_request_uses_installed_version_and_summary_only(self):
        response = MagicMock()
        response.read.return_value = json.dumps(summary(1)).encode("utf-8")
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value = response
        with patch.object(windows, "executable_version", return_value="5.6.2"), \
             patch.object(provider.urllib.request, "build_opener", return_value=opener):
            self.assertEqual(provider._request_summary("synthetic")["code"], 0)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, provider.SUMMARY_URL)
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.data, b"{}")
        self.assertEqual(request.get_header("X-ide-version"), "5.6.2")
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 15)

    def test_network_error_detail_not_exposed(self):
        opener = MagicMock()
        opener.open.side_effect = urllib.error.URLError("SENSITIVE_VALUE")
        with patch.object(windows, "executable_version", return_value=None), \
             patch.object(provider.urllib.request, "build_opener", return_value=opener):
            with self.assertRaises(RuntimeError) as caught:
                provider._request_summary("synthetic")
        self.assertNotIn("SENSITIVE_VALUE", str(caught.exception))

    def test_redirect_cannot_forward_credential(self):
        with self.assertRaises(RuntimeError):
            provider._NoRedirect().redirect_request(None, None, 302, "", {}, "https://example.invalid")


class WindowsHelperTests(unittest.TestCase):
    def test_jwt_checks_expiry_and_account_audience(self):
        def token(payload):
            data = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
            return f"synthetic.{data}.synthetic"
        self.assertTrue(windows.valid_token(token({"aud": "account", "exp": time.time() + 3600})))
        self.assertFalse(windows.valid_token(token({"aud": "account", "exp": 1})))
        self.assertFalse(windows.valid_token(token({"aud": "other", "exp": time.time() + 3600})))
        self.assertFalse(windows.valid_token("invalid"))

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI only")
    def test_dpapi_roundtrip_with_synthetic_data(self):
        original = b"synthetic-not-a-real-credential"
        encrypted = windows._dpapi(original, encrypt=True)
        self.assertIsInstance(encrypted, bytes)
        self.assertNotIn(original, encrypted)
        self.assertEqual(windows._dpapi(encrypted, encrypt=False), original)


if __name__ == "__main__":
    unittest.main()
