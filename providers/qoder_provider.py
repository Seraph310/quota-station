"""Qoder Credits provider: standalone App first, SDK/IDE for older setups.

The App adapter follows the standalone desktop account. Without an App profile,
the SDK reads qodercli sign-in, then the IDE fallback queries credit/usage.
No route creates an Agent turn; desktop routes are compatibility interfaces.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import time

from . import qoder_app

_RUNTIME = Path(__file__).resolve().parent / "qoder_runtime"
_ERRORS = {
    "auth_required": "Qoder CLI 尚未登录；请打开已登录的 Qoder IDE 后刷新。",
    "usage_unavailable": "Qoder 暂未返回账户额度，请稍后刷新。",
    "sdk_query_failed": "Qoder SDK 暂时无法读取额度。",
    "ide_unavailable": "请打开并登录 Qoder IDE，然后刷新额度。",
    "ide_permission": "无法访问 Qoder IDE 本地服务，请以同一 Windows 用户运行小组件。",
    "ide_timeout": "Qoder IDE 额度查询超时，请稍后刷新。",
    "invalid_response": "Qoder 额度响应格式异常，请稍后刷新。",
}


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _format(value: float) -> str:
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def _run_bridge(filename: str) -> dict:
    node = shutil.which("node")
    if not node:
        raise RuntimeError("未找到 Node.js，暂时无法读取 Qoder 额度。")
    bridge = _RUNTIME / filename
    if not bridge.is_file():
        raise RuntimeError("Qoder 读取组件缺失，请重新安装小组件。")
    try:
        result = subprocess.run(
            [node, str(bridge)], cwd=str(_RUNTIME), capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=28,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env={**os.environ, "NODE_NO_WARNINGS": "1"},
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("Qoder 额度查询超时，请稍后刷新。") from None
    except OSError:
        raise RuntimeError("无法启动 Qoder 额度读取组件。") from None
    # Never expose raw stderr/stdout: third-party errors can contain account data.
    if result.returncode != 0:
        raise RuntimeError("Qoder 额度读取组件暂时不可用。")
    try:
        payload = json.loads(result.stdout)
    except (ValueError, TypeError):
        raise RuntimeError("Qoder 额度响应格式异常，请稍后刷新。") from None
    if not isinstance(payload, dict):
        raise RuntimeError("Qoder 额度响应格式异常，请稍后刷新。")
    if "error" in payload:
        code = payload["error"]
        raise RuntimeError(_ERRORS.get(code, _ERRORS["usage_unavailable"]) if isinstance(code, str) else _ERRORS["usage_unavailable"])
    return payload


def _normalize(usage: dict) -> dict:
    details = []
    remaining = []
    for key, label in (("userQuota", "套餐剩余"), ("addOnQuota", "附加包剩余"), ("orgResourcePackage", "组织分配剩余")):
        bucket = usage.get(key)
        if bucket is None:
            continue
        if not isinstance(bucket, dict):
            raise RuntimeError("Qoder 额度响应格式异常，请稍后刷新。")
        if key == "orgResourcePackage" and bucket.get("available") is False:
            continue
        amount = bucket.get("remaining")
        if not _number(amount) or amount < 0:
            raise RuntimeError("Qoder 未返回完整的剩余额度，暂不显示余额。")
        unit = bucket.get("unit")
        if not isinstance(unit, str) or unit.lower() not in ("credit", "credits"):
            raise RuntimeError("Qoder 返回了不同的计量单位，暂不合并余额。")
        remaining.append(float(amount))
        total = bucket.get("cap" if key == "orgResourcePackage" else "total")
        value = f"{_format(amount)} Credits"
        if _number(total):
            value = f"{_format(amount)} / {_format(total)} Credits"
        details.append({"label": label, "value": value})
    for bucket in usage.get("dedicatedResourcePackages", []):
        amount = bucket.get("remaining")
        if not _number(amount) or amount < 0:
            raise RuntimeError("Qoder 未返回完整的专用资源包额度。")
        available = bucket.get("available") is True
        if available:
            remaining.append(float(amount))
        details.append({"label": bucket.get("name", "专用资源包"),
                        "value": f"{_format(amount)} Credits" + ("" if available else "（暂不可用，不计入合计）")})
    if not remaining:
        raise RuntimeError("Qoder 未返回账户余额；已用额度或会话消耗不能代替剩余额度。")
    plan = usage.get("userType")
    if isinstance(plan, str) and plan:
        plan_name = {"personal_professional": "个人专业版"}.get(plan, plan[:80])
        details.insert(0, {"label": "套餐", "value": plan_name})
    expiry = usage.get("expiresAt")
    if _number(expiry) and expiry > 0:
        if expiry > 100_000_000_000:
            expiry /= 1000
        try:
            details.append({"label": "套餐刷新" if usage.get("source") == "Qoder App" else "套餐到期",
                            "value": time.strftime("%Y-%m-%d", time.localtime(expiry))})
        except (OverflowError, OSError, ValueError):
            pass
    source = usage.get("source")
    source_name = {"Qoder IDE": "Qoder IDE 实时查询", "Qoder App": "新版 Qoder App 实时查询"}.get(source, "Qoder 官方 SDK")
    details.append({"label": "数据来源", "value": source_name})
    return {
        "name": "Qoder", "balance": round(math.fsum(remaining), 8),
        "unit": "Credits", "subtitle": "可用 Credits 合计" if source == "Qoder App" else "剩余 Credits", "reset_at": None,
        "details": details, "updated_at": time.time(),
    }


def fetch() -> dict:
    """Fetch real account quota, never turn unknown quota into zero."""
    if qoder_app.profile_present():
        return _normalize(qoder_app.fetch_usage())
    try:
        return _normalize(_run_bridge("qoder_bridge.mjs"))
    except RuntimeError:
        # A running IDE can have its own sign-in even when qodercli is unsigned.
        return _normalize(_run_bridge("qoder_ide_bridge.mjs"))
