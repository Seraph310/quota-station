"""Read-only compatibility adapter for the standalone Qoder App (0.4.3).

Uses the App's existing Windows-encrypted sign-in and its own GET quota route.
Credentials stay in memory; this module never refreshes or writes login files.
This is a client compatibility interface, not a promised public API.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import time
import urllib.error
import urllib.request

from ._workbuddy_windows import _dpapi

_ENDPOINT = "https://openapi.qoder.sh/sash/api/v2/me/usage"
_LOGIN_ERROR = "请打开新版 Qoder 并确认已登录，然后刷新额度。"
_FORMAT_ERROR = "新版 Qoder 额度响应格式异常，请稍后刷新。"


def profile_directory() -> Path:
    root = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
    return root / "com.qoder.app.stable"


def profile_present() -> bool:
    # A signed-out App must not silently fall back to a different IDE/CLI account.
    directory = profile_directory()
    return any((directory / name).is_file() for name in ("Local State", "auth.v1.dat"))


def _read_small(path: Path, limit: int = 65536) -> bytes:
    with path.open("rb") as stream:
        value = stream.read(limit + 1)
    if len(value) > limit:
        raise ValueError("oversized input")
    return value


def _decrypt_auth(directory: Path) -> tuple[str, bytes]:
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        encrypted = _read_small(directory / "auth.v1.dat")
        local_state = json.loads(_read_small(directory / "Local State"))
        wrapped = base64.b64decode(local_state["os_crypt"]["encrypted_key"], validate=True)
        if not wrapped.startswith(b"DPAPI") or not encrypted.startswith(b"v10") or len(encrypted) < 31:
            raise ValueError("unsupported encryption")
        key = _dpapi(wrapped[5:], encrypt=False)
        if not key or len(key) != 32:
            raise ValueError("credentials belong to another Windows identity")
        auth = json.loads(AESGCM(key).decrypt(encrypted[3:15], encrypted[15:], None))
        token = auth.get("token")
        expiry = datetime.fromisoformat(auth["expiresAt"].replace("Z", "+00:00"))
        if (auth.get("schemaVersion") != 1 or not isinstance(token, str)
                or not token or len(token) > 32768 or not token.isascii()
                or any(ord(c) < 33 or ord(c) == 127 for c in token)
                or expiry.tzinfo is None or expiry <= datetime.now(timezone.utc)):
            raise ValueError("unusable sign-in")
        return token, encrypted
    except Exception:
        # Do not echo crypto, JSON or transport exception text containing secrets.
        raise RuntimeError(_LOGIN_ERROR) from None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _request_usage(token: str) -> dict:
    request = urllib.request.Request(_ENDPOINT, method="GET", headers={
        "Accept": "application/json", "Authorization": "Bearer " + token,
        "Cosy-ClientType": "10", "User-Agent": "Qoder",
    })
    try:
        with urllib.request.build_opener(_NoRedirect()).open(request, timeout=15) as response:
            body = response.read(1_048_577)
            if len(body) > 1_048_576:
                raise ValueError("oversized response")
            return json.loads(body)
    except urllib.error.HTTPError as exc:
        status = exc.code
        exc.close()
        if status in (401, 403):
            raise RuntimeError(_LOGIN_ERROR) from None
        raise RuntimeError("新版 Qoder 额度服务暂时不可用，请稍后刷新。") from None
    except (ValueError, TypeError):
        raise RuntimeError(_FORMAT_ERROR) from None
    except Exception:
        raise RuntimeError("新版 Qoder 额度查询失败，请检查网络后刷新。") from None


def _number(value: object) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value >= 0)


def _bucket(value: object, org: bool = False) -> dict:
    if not isinstance(value, dict):
        raise RuntimeError(_FORMAT_ERROR)
    total = value.get("cap") if org else value.get("total")
    if org and total is None:
        total = value.get("total")
    used = value.get("used")
    if not _number(total) or not _number(used):
        raise RuntimeError(_FORMAT_ERROR)
    unit = value.get("unit", "Credits")
    if not isinstance(unit, str) or unit.lower() not in ("credit", "credits"):
        raise RuntimeError("新版 Qoder 返回了不同的计量单位，暂不合并余额。")
    result = {"total": total, "used": used, "remaining": max(0, total - used), "unit": "Credits"}
    if org:
        available = value.get("available", total > 0)
        if not isinstance(available, bool):
            raise RuntimeError(_FORMAT_ERROR)
        result.update(cap=total, available=available)
    return result


def normalize_usage(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise RuntimeError(_FORMAT_ERROR)
    if payload.get("displayMode") == "enterprise":
        raise RuntimeError("当前 Qoder 企业账号需在客户端查看用量，未提供可换算的 Credits 余额。")
    usage = payload.get("qoderUsage")
    if payload.get("displayMode") != "qoder" or not isinstance(usage, dict):
        raise RuntimeError(_FORMAT_ERROR)
    if not isinstance(usage.get("userType"), str) or not usage["userType"].strip():
        raise RuntimeError(_FORMAT_ERROR)
    result = {"userType": usage["userType"], "source": "Qoder App", "dedicatedResourcePackages": []}
    for key in ("userQuota", "addOnQuota", "orgResourcePackage"):
        if key in usage and usage[key] is not None:
            # An explicitly unavailable organization package contributes nothing.
            if key == "orgResourcePackage" and isinstance(usage[key], dict) and usage[key].get("available") is False:
                result[key] = {"available": False}
            else:
                result[key] = _bucket(usage[key], org=key == "orgResourcePackage")
    if _number(usage.get("expiresAt")):
        result["expiresAt"] = usage["expiresAt"]
    packages = usage.get("dedicatedResourcePackages", [])
    if not isinstance(packages, list):
        raise RuntimeError(_FORMAT_ERROR)
    seen = set()
    for package in packages:
        if not isinstance(package, dict) or not isinstance(package.get("id"), str) or not package["id"].strip():
            raise RuntimeError(_FORMAT_ERROR)
        if package["id"] in seen:
            raise RuntimeError(_FORMAT_ERROR)
        seen.add(package["id"])
        bucket = _bucket({**package, "used": package.get("used", 0)})
        if "remaining" in package:
            if not _number(package["remaining"]):
                raise RuntimeError(_FORMAT_ERROR)
            bucket["remaining"] = package["remaining"]
        expiry = package.get("expiresAt", package.get("expires_at"))
        expired = _number(expiry) and expiry > 0 and (expiry / 1000 if expiry >= 1e10 else expiry) <= time.time()
        status = package.get("status", "")
        status = status.upper().removeprefix("QUOTA_DETAIL_STATUS_") if isinstance(status, str) else ""
        bucket["available"] = (package.get("available") is True and not expired
                               and status not in ("EXPIRED", "SUSPENDED", "EXHAUSTED"))
        name = package.get("name")
        bucket["name"] = name[:60] if isinstance(name, str) and name.strip() else "专用资源包"
        result["dedicatedResourcePackages"].append(bucket)
    return result


def fetch_usage() -> dict:
    directory = profile_directory()
    token, original = _decrypt_auth(directory)
    payload = _request_usage(token)
    try:
        unchanged = _read_small(directory / "auth.v1.dat") == original
    except OSError:
        unchanged = False
    if not unchanged:
        raise RuntimeError("Qoder 登录状态刚刚更新，请再刷新一次额度。")
    return normalize_usage(payload)
