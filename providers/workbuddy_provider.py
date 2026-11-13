"""Read-only WorkBuddy remaining-credit adapter; does not run model requests."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import json
import math
import os
from pathlib import Path
import socket
import time
import urllib.error
import urllib.request

from . import _workbuddy_windows as windows
from runtime_paths import data_root


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LEGACY_CACHE = Path.home() / "WorkBuddy" / "wb-credits-ball" / "token.bin"
PROJECT_CACHE = data_root() / ".cache" / "workbuddy-token.bin"
WORKBUDDY_EXE = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "Programs" / "WorkBuddy" / "WorkBuddy.exe"
SUMMARY_URL = "https://copilot.tencent.com/billing/meter/get-user-resource-summary"
MAX_RESPONSE_BYTES = 1024 * 1024


class _AuthError(RuntimeError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, new_url):
        raise RuntimeError("WorkBuddy 查询地址发生跳转，请稍后重试")


def _cached_token() -> str | None:
    # The original ball's cache is read-only, and preferred over our own cache.
    for path in (LEGACY_CACHE, PROJECT_CACHE):
        token = windows.read_cached_token(path)
        if token:
            return token
    return None


def _request_summary(token: str) -> dict:
    version = windows.executable_version(WORKBUDDY_EXE)
    headers = {
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
        "Accept-Language": "zh-CN",
        "User-Agent": "WorkBuddy" + (f"/{version}" if version else ""),
        "X-IDE-Type": "WorkBuddy", "X-IDE-Name": "WorkBuddy", "X-Product": "WorkBuddy",
    }
    if version:
        headers["X-IDE-Version"] = version
    request = urllib.request.Request(SUMMARY_URL, data=b"{}", headers=headers, method="POST")
    try:
        with urllib.request.build_opener(_NoRedirect()).open(request, timeout=15) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            raise _AuthError("WorkBuddy 登录已失效，请打开 WorkBuddy 并确认已登录") from None
        raise RuntimeError(f"WorkBuddy 查询暂时失败（HTTP {error.code}）") from None
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError):
        raise RuntimeError("暂时无法连接 WorkBuddy，请检查网络后重试") from None
    if len(raw) > MAX_RESPONSE_BYTES:
        raise RuntimeError("WorkBuddy 返回数据异常，暂不能确认剩余积分")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeError):
        raise RuntimeError("WorkBuddy 返回格式异常，暂不能确认剩余积分") from None
    if not isinstance(payload, dict):
        raise RuntimeError("WorkBuddy 返回格式异常，暂不能确认剩余积分")
    return payload


def _parse_summary(payload: dict) -> tuple[float, int]:
    # Raw API error text is not forwarded because it may contain account data.
    if not isinstance(payload, dict) or payload.get("code") != 0 or isinstance(payload.get("code"), bool):
        raise RuntimeError("WorkBuddy 未能返回有效额度，请打开客户端确认登录状态")
    data = payload.get("data")
    packages = data.get("Packages") if isinstance(data, dict) else None
    if not isinstance(packages, list) or not packages:
        # No verified API contract says an empty list is equivalent to zero.
        raise RuntimeError("WorkBuddy 未返回可确认的资源包，暂不能确认剩余积分")
    total = Decimal(0)
    for package in packages:
        value = package.get("CycleRemainCapacity") if isinstance(package, dict) else None
        if value is None or isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise RuntimeError("WorkBuddy 资源包额度字段异常，暂不能确认剩余积分")
        try:
            capacity = Decimal(str(value))
        except (InvalidOperation, ValueError):
            raise RuntimeError("WorkBuddy 资源包额度字段异常，暂不能确认剩余积分") from None
        if not capacity.is_finite() or capacity < 0:
            raise RuntimeError("WorkBuddy 资源包额度字段异常，暂不能确认剩余积分")
        total += capacity
    balance = float(total)
    if not math.isfinite(balance):
        raise RuntimeError("WorkBuddy 资源包额度字段异常，暂不能确认剩余积分")
    return balance, len(packages)


def fetch() -> dict:
    """Fetch remaining credits once; only an expired-session recovery may retry."""
    try:
        token = _cached_token()
        from_process = token is None
        if token is None:
            token = windows.find_running_token()
        if not token:
            raise RuntimeError("未找到 WorkBuddy 登录状态，请先打开 WorkBuddy 并登录")
        try:
            payload = _request_summary(token)
        except _AuthError:
            if from_process:
                raise
            replacement = windows.find_running_token()
            if not replacement or replacement == token:
                raise RuntimeError("WorkBuddy 登录已失效，请打开 WorkBuddy 并确认已登录") from None
            token, from_process = replacement, True
            payload = _request_summary(token)
        balance, package_count = _parse_summary(payload)
        if from_process:
            # Save only a server-accepted credential, and never change the old cache.
            windows.write_cached_token(PROJECT_CACHE, token)
        return {
            "name": "WorkBuddy", "balance": balance, "unit": "积分",
            "subtitle": "剩余积分", "reset_at": None,
            "details": [
                {"label": "额度口径", "value": "各资源包本周期剩余积分之和"},
                {"label": "资源包", "value": f"{package_count} 个"},
            ],
            "updated_at": time.time(),
        }
    except RuntimeError:
        raise
    except Exception:
        # No raw OS, credential, or server details in UI/logs.
        raise RuntimeError("WorkBuddy 额度暂时无法读取，请稍后重试") from None
