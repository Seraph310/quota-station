import subprocess
import unittest
from unittest.mock import patch

from providers import qoder_provider as provider


class QoderTests(unittest.TestCase):
    def test_real_quota_buckets_are_combined(self):
        result = provider._normalize({
            "userType": "Pro", "source": "Qoder IDE",
            "userQuota": {"total": 100, "remaining": 10.5, "unit": "Credits"},
            "addOnQuota": {"total": 20, "remaining": 5.2, "unit": "Credits"},
        })
        self.assertEqual(result["balance"], 15.7)
        self.assertEqual(result["unit"], "Credits")
        self.assertIsNone(result["reset_at"])
        self.assertIn({"label": "数据来源", "value": "Qoder IDE 实时查询"}, result["details"])

    def test_known_zero_is_valid(self):
        self.assertEqual(provider._normalize({"userQuota": {"remaining": 0, "unit": "Credits"}})["balance"], 0)

    def test_session_usage_is_not_account_quota(self):
        with self.assertRaisesRegex(RuntimeError, "未返回账户余额"):
            provider._normalize({"session": {"total_credits": 0}})

    def test_missing_bucket_amount_does_not_become_zero(self):
        with self.assertRaisesRegex(RuntimeError, "完整"):
            provider._normalize({"userQuota": {"remaining": 1, "unit": "Credits"}, "addOnQuota": {"used": 0, "unit": "Credits"}})

    def test_invalid_numbers_rejected(self):
        for value in (None, float("nan"), float("inf"), True, -1, "20"):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                provider._normalize({"userQuota": {"remaining": value, "unit": "Credits"}})

    def test_units_are_not_guessed(self):
        with self.assertRaisesRegex(RuntimeError, "计量单位"):
            provider._normalize({"userQuota": {"remaining": 20, "unit": "Tokens"}})

    def test_unavailable_organization_is_not_added(self):
        result = provider._normalize({"userQuota": {"remaining": 3, "unit": "Credits"}, "orgResourcePackage": {"available": False}})
        self.assertEqual(result["balance"], 3)

    def test_falls_back_to_signed_in_ide(self):
        payload = {"userQuota": {"remaining": 8, "unit": "Credits"}, "source": "Qoder IDE"}
        with patch.object(provider.qoder_app, "profile_present", return_value=False), \
                patch.object(provider, "_run_bridge", side_effect=[RuntimeError("auth"), payload]) as run:
            self.assertEqual(provider.fetch()["balance"], 8)
            self.assertEqual(run.call_args_list[1].args, ("qoder_ide_bridge.mjs",))

    def test_sdk_success_does_not_query_ide(self):
        with patch.object(provider.qoder_app, "profile_present", return_value=False), \
                patch.object(provider, "_run_bridge", return_value={"userQuota": {"remaining": 8, "unit": "Credits"}}) as run:
            self.assertEqual(provider.fetch()["balance"], 8)
            run.assert_called_once_with("qoder_bridge.mjs")

    def test_new_app_profile_takes_priority_over_sdk_and_ide(self):
        payload = {"source": "Qoder App", "userQuota": {"remaining": 5, "unit": "Credits"}}
        with patch.object(provider.qoder_app, "profile_present", return_value=True), \
                patch.object(provider.qoder_app, "fetch_usage", return_value=payload) as app_fetch, \
                patch.object(provider, "_run_bridge") as run:
            result = provider.fetch()
        self.assertEqual(result["balance"], 5)
        self.assertEqual(result["subtitle"], "可用 Credits 合计")
        self.assertIn({"label": "数据来源", "value": "新版 Qoder App 实时查询"}, result["details"])
        app_fetch.assert_called_once_with()
        run.assert_not_called()

    def test_new_app_login_failure_never_uses_another_account(self):
        with patch.object(provider.qoder_app, "profile_present", return_value=True), \
                patch.object(provider.qoder_app, "fetch_usage", side_effect=RuntimeError("请登录新版 Qoder")), \
                patch.object(provider, "_run_bridge") as run:
            with self.assertRaisesRegex(RuntimeError, "请登录新版"):
                provider.fetch()
        run.assert_not_called()

    def test_new_app_unknown_balance_never_uses_another_account(self):
        with patch.object(provider.qoder_app, "profile_present", return_value=True), \
                patch.object(provider.qoder_app, "fetch_usage", return_value={"source": "Qoder App"}), \
                patch.object(provider, "_run_bridge") as run:
            with self.assertRaisesRegex(RuntimeError, "未返回账户余额"):
                provider.fetch()
        run.assert_not_called()

    def test_errors_never_echo_transport_secrets(self):
        result = subprocess.CompletedProcess([], 1, "private-user", "secret-token")
        with patch.object(provider.shutil, "which", return_value="node"), patch.object(provider.subprocess, "run", return_value=result):
            with self.assertRaises(RuntimeError) as exc:
                provider._run_bridge("qoder_bridge.mjs")
            self.assertNotIn("secret", str(exc.exception))
            self.assertNotIn("private", str(exc.exception))


if __name__ == "__main__":
    unittest.main()
