"""Synthetic fixtures only: no real profile reads, network, or model calls."""

import base64
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import traceback
import unittest
from unittest.mock import MagicMock, patch
import urllib.error
import urllib.request

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from providers import qoder_app as app
from providers import qoder_provider as provider


def usage(**buckets):
    return {"displayMode": "qoder", "qoderUsage": {"userType": "personal_professional", **buckets}}


def bucket(total=100, used=25, **extra):
    return {"total": total, "used": used, "unit": "Credits", **extra}


class NormalizeTests(unittest.TestCase):
    def test_total_minus_used_and_org_cap_are_combined(self):
        data = usage(userQuota=bucket(), addOnQuota=bucket(20, 3),
                     orgResourcePackage=bucket(10000, 10, cap=40, available=True))
        normalized = app.normalize_usage(data)
        self.assertEqual(normalized["userQuota"]["remaining"], 75)
        self.assertEqual(normalized["addOnQuota"]["remaining"], 17)
        self.assertEqual(normalized["orgResourcePackage"]["remaining"], 30)
        self.assertEqual(normalized["orgResourcePackage"]["cap"], 40)
        result = provider._normalize(normalized)
        self.assertEqual(result["balance"], 122)
        self.assertIn({"label": "组织分配剩余", "value": "30 / 40 Credits"}, result["details"])

    def test_known_zero_overuse_and_zero_cap_do_not_become_unknown(self):
        for quota in (bucket(0, 0), bucket(5, 9)):
            with self.subTest(quota=quota):
                result = provider._normalize(app.normalize_usage(usage(userQuota=quota)))
                self.assertEqual(result["balance"], 0)
        normalized = app.normalize_usage(usage(orgResourcePackage=bucket(1000, 0, cap=0, available=True)))
        self.assertEqual(normalized["orgResourcePackage"]["remaining"], 0)

    def test_unavailable_org_without_amounts_is_safely_excluded(self):
        normalized = app.normalize_usage(usage(userQuota=bucket(10, 4),
                                             orgResourcePackage={"available": False}))
        self.assertEqual(provider._normalize(normalized)["balance"], 6)

    def test_enterprise_or_unknown_mode_is_not_a_zero_balance(self):
        for data in ({"displayMode": "enterprise"}, {"displayMode": "future-mode"}, None, [], {}):
            with self.subTest(data=data), self.assertRaises(RuntimeError):
                app.normalize_usage(data)

    def test_missing_and_invalid_numeric_amounts_are_rejected(self):
        for field in ("total", "used"):
            for value in (None, True, "25", -1, float("nan"), float("inf")):
                with self.subTest(field=field, value=value), self.assertRaises(RuntimeError):
                    app.normalize_usage(usage(userQuota={**bucket(), field: value}))
        for cap in (False, -1, "20"):
            with self.subTest(cap=cap), self.assertRaises(RuntimeError):
                app.normalize_usage(usage(orgResourcePackage=bucket(cap=cap)))

    def test_null_or_missing_org_cap_falls_back_to_total(self):
        for quota in (bucket(100, 7), bucket(100, 7, cap=None)):
            with self.subTest(quota=quota):
                normalized = app.normalize_usage(usage(orgResourcePackage=quota))
                self.assertEqual(normalized["orgResourcePackage"]["cap"], 100)
                self.assertEqual(normalized["orgResourcePackage"]["remaining"], 93)

    def test_invalid_units_are_rejected_for_every_package_type(self):
        for key in ("userQuota", "addOnQuota", "orgResourcePackage", "dedicatedResourcePackages"):
            for unit in ("Tokens", "USD", None, 7):
                data = bucket(unit=unit)
                if key == "dedicatedResourcePackages":
                    data = [{**data, "id": "fixture-package", "available": True}]
                with self.subTest(key=key, unit=unit), self.assertRaisesRegex(RuntimeError, "计量单位"):
                    app.normalize_usage(usage(**{key: data}))

    def test_credit_case_and_singular_are_normalized(self):
        for unit in ("credit", "CREDITS", "Credits"):
            result = app.normalize_usage(usage(userQuota=bucket(unit=unit)))
            self.assertEqual(result["userQuota"]["unit"], "Credits")

    def test_active_dedicated_package_can_supply_balance_without_subscription(self):
        normalized = app.normalize_usage(usage(dedicatedResourcePackages=[
            {"id": "new-user", "name": "新用户包", "total": 100, "available": True},
            {"id": "gift", "name": "赠送包", "total": 30, "used": 10, "available": True},
        ]))
        self.assertEqual(provider._normalize(normalized)["balance"], 120)

    def test_expired_disabled_suspended_and_exhausted_packages_are_excluded(self):
        packages = [
            {"id": "active", "total": 10, "used": 2, "available": True, "expiresAt": 2000},
            {"id": "expired-sec", "total": 50, "available": True, "expiresAt": 999},
            {"id": "expired-ms", "total": 50, "available": True, "expiresAt": 1700000000000},
            {"id": "disabled", "total": 50, "available": False},
            {"id": "unknown-availability", "total": 50},
            *[{"id": status, "total": 50, "available": True, "status": status}
              for status in ("EXPIRED", "SUSPENDED", "EXHAUSTED")],
        ]
        # Millisecond example uses a current-scale timestamp; adjust active and
        # expired second timestamps to the same synthetic clock.
        packages[0]["expiresAt"] = 1700000010
        packages[1]["expiresAt"] = 1700000000
        with patch.object(app.time, "time", return_value=1700000001):
            normalized = app.normalize_usage(usage(dedicatedResourcePackages=packages))
        result = provider._normalize(normalized)
        self.assertEqual(result["balance"], 8)
        unavailable = [row for row in result["details"] if "不计入合计" in row["value"]]
        self.assertEqual(len(unavailable), 7)

    def test_only_unavailable_packages_do_not_claim_zero_available_quota(self):
        normalized = app.normalize_usage(usage(dedicatedResourcePackages=[
            {"id": "disabled", "total": 10, "available": False}]))
        with self.assertRaisesRegex(RuntimeError, "未返回账户余额"):
            provider._normalize(normalized)

    def test_prefixed_and_lowercase_blocked_status_overrides_available_true(self):
        for status in ("EXPIRED", "SUSPENDED", "EXHAUSTED"):
            for rendered in ("QUOTA_DETAIL_STATUS_" + status, ("QUOTA_DETAIL_STATUS_" + status).lower(), status.lower()):
                with self.subTest(status=rendered):
                    normalized = app.normalize_usage(usage(userQuota=bucket(10, 4), dedicatedResourcePackages=[
                        {"id": "blocked", "total": 90, "available": True, "status": rendered}]))
                    self.assertFalse(normalized["dedicatedResourcePackages"][0]["available"])
                    self.assertEqual(provider._normalize(normalized)["balance"], 6)

    def test_malformed_or_duplicate_packages_are_rejected(self):
        good = {"id": "same-id", "total": 10, "available": True}
        for packages in (None, {}, [None], [{"total": 1}], [{**good, "id": " "}], [good, good]):
            with self.subTest(packages=packages), self.assertRaises(RuntimeError):
                app.normalize_usage(usage(dedicatedResourcePackages=packages))

    def test_dedicated_explicit_remaining_must_be_valid(self):
        for value in (None, True, "2", -2, float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                app.normalize_usage(usage(dedicatedResourcePackages=[
                    {"id": "p", "total": 10, "remaining": value, "available": True}]))

    def test_missing_user_type_and_invalid_org_availability_are_rejected(self):
        for user_type in (None, "", " ", False):
            with self.subTest(user_type=user_type), self.assertRaises(RuntimeError):
                app.normalize_usage(usage(userType=user_type, userQuota=bucket()))
        with self.assertRaises(RuntimeError):
            app.normalize_usage(usage(orgResourcePackage=bucket(available="true")))


class RequestTests(unittest.TestCase):
    def test_request_is_one_fixed_https_get_with_redirects_blocked(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = json.dumps(usage(userQuota=bucket())).encode()
        opener = MagicMock()
        opener.open.return_value = response
        with patch.object(app.urllib.request, "build_opener", return_value=opener) as build:
            self.assertEqual(app._request_usage("synthetic-token")["displayMode"], "qoder")
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://openapi.qoder.sh/sash/api/v2/me/usage")
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.get_header("Authorization"), "Bearer synthetic-token")
        self.assertIsNone(request.data)
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 15)
        self.assertEqual(opener.open.call_count, 1)
        self.assertIsInstance(build.call_args.args[0], app._NoRedirect)
        response.read.assert_called_once_with(1_048_577)

    def test_redirect_handler_refuses_cross_host_or_same_host_redirect(self):
        handler = app._NoRedirect()
        req = urllib.request.Request(app._ENDPOINT, headers={"Authorization": "Bearer synthetic-token"})
        for status in (301, 302, 303, 307, 308):
            for target in ("https://another.invalid/usage", app._ENDPOINT + "?moved=true"):
                with self.subTest(status=status, target=target):
                    self.assertIsNone(handler.redirect_request(req, None, status, "Moved", {}, target))

    def test_http_errors_and_redirect_errors_do_not_echo_secrets(self):
        for status in (301, 302, 307, 308, 401, 403, 429, 500):
            error = urllib.error.HTTPError("https://invalid/synthetic-secret-token", status,
                                           "synthetic-private-error", {}, io.BytesIO())
            opener = MagicMock()
            opener.open.side_effect = error
            with self.subTest(status=status), patch.object(app.urllib.request, "build_opener", return_value=opener):
                with self.assertRaises(RuntimeError) as caught:
                    app._request_usage("synthetic-secret-token")
            rendered = "".join(traceback.format_exception(caught.exception))
            self.assertNotIn("synthetic-secret-token", rendered)
            self.assertNotIn("synthetic-private-error", rendered)
            self.assertTrue(caught.exception.__suppress_context__)
            error.close()

    def test_network_error_does_not_echo_secrets(self):
        opener = MagicMock()
        opener.open.side_effect = urllib.error.URLError("synthetic-secret-token")
        with patch.object(app.urllib.request, "build_opener", return_value=opener):
            with self.assertRaisesRegex(RuntimeError, "检查网络") as caught:
                app._request_usage("synthetic-secret-token")
        self.assertNotIn("synthetic-secret-token", "".join(traceback.format_exception(caught.exception)))

    def test_oversized_or_invalid_json_response_is_safe(self):
        for body in (b"synthetic-secret-token", b"x" * 1_048_577):
            response = MagicMock()
            response.__enter__.return_value = response
            response.read.return_value = body
            opener = MagicMock()
            opener.open.return_value = response
            with self.subTest(length=len(body)), patch.object(app.urllib.request, "build_opener", return_value=opener):
                with self.assertRaisesRegex(RuntimeError, "格式异常") as caught:
                    app._request_usage("synthetic-secret-token")
            self.assertNotIn("synthetic-secret-token", "".join(traceback.format_exception(caught.exception)))


class AuthTests(unittest.TestCase):
    DIRECTORY = Path(__file__).parent / "synthetic-qoder-profile"
    KEY = bytes(range(32))
    NONCE = bytes(range(12))
    TOKEN = "synthetic-only-token"

    def encrypted_fixture(self, **overrides):
        auth = {"schemaVersion": 1, "token": self.TOKEN,
                "expiresAt": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(), **overrides}
        encrypted = b"v10" + self.NONCE + AESGCM(self.KEY).encrypt(self.NONCE, json.dumps(auth).encode(), None)
        state = json.dumps({"os_crypt": {"encrypted_key": base64.b64encode(b"DPAPIwrapped-fixture").decode()}}).encode()
        return encrypted, state

    def decrypt(self, encrypted, state, *, key=None):
        fixtures = {self.DIRECTORY / "auth.v1.dat": encrypted, self.DIRECTORY / "Local State": state}
        with patch.object(app, "_read_small", side_effect=fixtures.__getitem__) as read, \
                patch.object(app, "_dpapi", return_value=self.KEY if key is None else key) as dpapi:
            result = app._decrypt_auth(self.DIRECTORY)
        self.assertEqual(read.call_count, 2)
        dpapi.assert_called_once_with(b"wrapped-fixture", encrypt=False)
        return result

    def test_synthetic_aes_gcm_profile_decrypts_without_reading_real_credentials(self):
        encrypted, state = self.encrypted_fixture()
        token, original = self.decrypt(encrypted, state)
        self.assertEqual(token, self.TOKEN)
        self.assertEqual(original, encrypted)

    def test_expired_or_malformed_auth_is_rejected_without_secret_output(self):
        cases = [{"schemaVersion": 2}, {"expiresAt": "2000-01-01T00:00:00Z"},
                 {"expiresAt": "2099-01-01T00:00:00"}, {"expiresAt": "invalid"},
                 {"token": ""}, {"token": "unsafe\r\nAuthorization"}, {"token": "非ASCII"},
                 {"token": "a" * 32769}]
        for changes in cases:
            encrypted, state = self.encrypted_fixture(**changes)
            with self.subTest(changes=list(changes)), self.assertRaises(RuntimeError) as caught:
                self.decrypt(encrypted, state)
            self.assertEqual(str(caught.exception), app._LOGIN_ERROR)
            self.assertTrue(caught.exception.__suppress_context__)

    def test_corrupt_ciphertext_wrong_key_and_bad_wrapping_are_safely_rejected(self):
        encrypted, state = self.encrypted_fixture()
        corrupt = encrypted[:-1] + bytes([encrypted[-1] ^ 1])
        invalid_states = (b"synthetic-secret-token", b"{}", b'{"os_crypt":{"encrypted_key":"!!!!"}}')
        cases = [(corrupt, state, self.KEY), (encrypted, state, b"x" * 31),
                 (encrypted, state, b"x" * 32), (b"v11" + encrypted[3:], state, self.KEY),
                 *[(encrypted, item, self.KEY) for item in invalid_states]]
        for cipher, local_state, key in cases:
            with self.subTest(cipher_size=len(cipher)), self.assertRaises(RuntimeError) as caught:
                self.decrypt(cipher, local_state, key=key)
            self.assertEqual(str(caught.exception), app._LOGIN_ERROR)
            self.assertNotIn("synthetic-secret-token", "".join(traceback.format_exception(caught.exception)))

    def test_file_read_and_dpapi_errors_do_not_echo_paths_or_tokens(self):
        with patch.object(app, "_read_small", side_effect=OSError("synthetic-secret-token")):
            with self.assertRaises(RuntimeError) as caught:
                app._decrypt_auth(self.DIRECTORY)
        self.assertNotIn("synthetic-secret-token", "".join(traceback.format_exception(caught.exception)))
        encrypted, state = self.encrypted_fixture()
        with patch.object(app, "_read_small", side_effect=[encrypted, state]), \
                patch.object(app, "_dpapi", side_effect=ValueError("synthetic-secret-token")):
            with self.assertRaises(RuntimeError) as caught:
                app._decrypt_auth(self.DIRECTORY)
        self.assertNotIn("synthetic-secret-token", "".join(traceback.format_exception(caught.exception)))

    def test_profile_presence_depends_on_local_state_not_signed_in_token_file(self):
        with patch.object(app, "profile_directory", return_value=self.DIRECTORY), \
                patch.object(Path, "is_file", autospec=True, return_value=True) as is_file:
            self.assertTrue(app.profile_present())
        is_file.assert_called_once_with(self.DIRECTORY / "Local State")

    def test_either_profile_file_locks_account_source_to_new_app(self):
        for present in ({"Local State"}, {"auth.v1.dat"}, {"Local State", "auth.v1.dat"}, set()):
            with self.subTest(present=present), \
                    patch.object(app, "profile_directory", return_value=self.DIRECTORY), \
                    patch.object(Path, "is_file", autospec=True, side_effect=lambda path: path.name in present):
                self.assertEqual(app.profile_present(), bool(present))

    def test_auth_change_during_request_aborts_instead_of_mixing_accounts(self):
        with patch.object(app, "profile_directory", return_value=self.DIRECTORY), \
                patch.object(app, "_decrypt_auth", return_value=(self.TOKEN, b"before")), \
                patch.object(app, "_request_usage", return_value=usage(userQuota=bucket())) as request, \
                patch.object(app, "_read_small", return_value=b"after"), \
                patch.object(app, "normalize_usage") as normalize:
            with self.assertRaisesRegex(RuntimeError, "登录状态刚刚更新"):
                app.fetch_usage()
        request.assert_called_once_with(self.TOKEN)
        normalize.assert_not_called()

    def test_auth_file_disappearance_during_request_is_a_safe_retry_error(self):
        with patch.object(app, "profile_directory", return_value=self.DIRECTORY), \
                patch.object(app, "_decrypt_auth", return_value=(self.TOKEN, b"before")), \
                patch.object(app, "_request_usage", return_value=usage(userQuota=bucket())), \
                patch.object(app, "_read_small", side_effect=FileNotFoundError("synthetic-secret-token")):
            with self.assertRaisesRegex(RuntimeError, "登录状态刚刚更新") as caught:
                app.fetch_usage()
        self.assertNotIn("synthetic-secret-token", str(caught.exception))

    def test_unusable_auth_aborts_before_any_http_request(self):
        with patch.object(app, "profile_directory", return_value=self.DIRECTORY), \
                patch.object(app, "_decrypt_auth", side_effect=RuntimeError(app._LOGIN_ERROR)), \
                patch.object(app, "_request_usage") as request:
            with self.assertRaisesRegex(RuntimeError, "确认已登录"):
                app.fetch_usage()
        request.assert_not_called()

    def test_unchanged_synthetic_profile_returns_normalized_quota(self):
        with patch.object(app, "profile_directory", return_value=self.DIRECTORY), \
                patch.object(app, "_decrypt_auth", return_value=(self.TOKEN, b"same")), \
                patch.object(app, "_request_usage", return_value=usage(userQuota=bucket())), \
                patch.object(app, "_read_small", return_value=b"same"):
            result = app.fetch_usage()
        self.assertEqual(result["source"], "Qoder App")
        self.assertEqual(result["userQuota"]["remaining"], 75)


if __name__ == "__main__":
    unittest.main()
