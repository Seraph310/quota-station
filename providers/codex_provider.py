"""Read Codex quota through the official, read-only app-server account API.

No model turn is created. Authentication remains owned by the installed Codex CLI.
Protocol: https://learn.chatgpt.com/docs/app-server
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time
from typing import Any


def _number(value: Any) -> float | None:
    # Missing quota information must never turn into a displayed zero.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _window_label(minutes: float | None, slot: str) -> str:
    if minutes is None or minutes <= 0:
        return "主额度窗口" if slot == "primary" else "次额度窗口"
    if minutes == 10080:
        return "本周"
    if minutes % 1440 == 0:
        return f"{minutes / 1440:g}天窗口"
    if minutes % 60 == 0:
        return f"{minutes / 60:g}小时窗口"
    return f"{minutes:g}分钟窗口"


def _reset_label(timestamp: float | None) -> str | None:
    if timestamp is None or timestamp <= 0:
        return None
    try:
        return time.strftime("%m-%d %H:%M", time.localtime(timestamp))
    except (OverflowError, OSError, ValueError):
        return None


def parse_rate_limits(payload: Any, *, now: float | None = None) -> dict:
    """Convert an account/rateLimits/read result, retaining each returned window."""
    if not isinstance(payload, dict):
        raise RuntimeError("Codex 返回的额度格式无效，请稍后重试。")
    multi = payload.get("rateLimitsByLimitId")
    if multi is not None:
        if not isinstance(multi, dict):
            raise RuntimeError("Codex 返回的多窗口额度格式无效。")
        buckets = list(multi.items())
    else:
        legacy = payload.get("rateLimits")
        buckets = [(legacy.get("limitId") or "codex", legacy)] if isinstance(legacy, dict) else []

    windows: list[dict] = []
    details: list[dict[str, str]] = []
    for bucket_key, bucket in buckets:
        if not isinstance(bucket, dict):
            continue
        bucket_id = str(bucket.get("limitId") or bucket_key)
        name = str(bucket.get("limitName") or ("Codex" if bucket_id == "codex" else bucket_id))
        for slot in ("primary", "secondary"):
            window = bucket.get(slot)
            if not isinstance(window, dict):
                continue
            used = _number(window.get("usedPercent"))
            minutes = _number(window.get("windowDurationMins"))
            label = _window_label(minutes, slot)
            reset = _number(window.get("resetsAt"))
            reset = reset if reset is not None and _reset_label(reset) else None
            remaining = None if used is None else max(0.0, min(100.0, 100.0 - used))
            value = "暂不可用" if remaining is None else f"剩余 {remaining:g}%"
            reset_text = _reset_label(reset)
            if reset_text:
                value += f" · {reset_text} 重置"
            details.append({"label": f"{name} · {label}", "value": value})
            if remaining is not None:
                windows.append({"bucket_id": bucket_id, "minutes": minutes, "slot": slot,
                                "label": label, "remaining": remaining, "reset_at": reset})

        credits = bucket.get("credits")
        if isinstance(credits, dict):
            balance = credits.get("balance")
            if credits.get("unlimited") is True:
                credit_text = "不限量"
            elif isinstance(balance, (str, int, float)) and not isinstance(balance, bool):
                credit_text = str(balance)
            else:
                credit_text = "暂不可用"
            details.append({"label": f"{name} · Credits", "value": credit_text})

    resets = payload.get("rateLimitResetCredits")
    if isinstance(resets, dict):
        count = _number(resets.get("availableCount"))
        if count is not None:
            details.append({"label": "可用额度重置次数", "value": f"{count:g} 次"})
    if not windows:
        raise RuntimeError("Codex 暂未提供可用的额度百分比，请确认已登录 ChatGPT 账户后重试。")

    # Prefer Codex's weekly window; do not mistake another product bucket for it.
    primary = min(windows, key=lambda w: (w["bucket_id"] != "codex",
                                          w["minutes"] != 10080,
                                          w["slot"] != "primary"))
    return {"name": "Codex", "balance": primary["remaining"], "unit": "%",
            "subtitle": f"{primary['label']}剩余", "reset_at": primary["reset_at"],
            "details": details, "updated_at": time.time() if now is None else now}


def _find_executable() -> Path:
    configured = os.environ.get("QUOTA_CODEX_EXECUTABLE")
    if configured:
        candidate = Path(configured).expanduser()
        if candidate.is_file() and candidate.suffix.lower() == ".exe":
            return candidate
        raise RuntimeError("配置的 Codex 程序不存在，请检查 QUOTA_CODEX_EXECUTABLE。")
    roots: list[Path] = []
    for command in ("codex.exe", "codex", "codex.cmd", "codex.ps1"):
        found = shutil.which(command)
        if found:
            candidate = Path(found)
            if candidate.suffix.lower() == ".exe":
                return candidate
            roots.append(candidate.parent)
    roots.append(Path(os.environ.get("APPDATA", "")) / "npm")
    for root in dict.fromkeys(roots):
        # npm's official package contains the native executable; avoiding its
        # shell/Node wrapper also makes process cleanup deterministic.
        package = root / "node_modules" / "@openai"
        for pattern in ("codex/node_modules/@openai/codex-win32-*/vendor/*/bin/codex.exe",
                        "codex-win32-*/vendor/*/bin/codex.exe",
                        "codex/vendor/*/codex/codex.exe"):
            candidates = sorted(package.glob(pattern))
            if candidates:
                return candidates[0]
    # The desktop app can bundle a native CLI without adding it to Windows PATH.
    # Discover its versioned directory so desktop shortcuts also work after updates.
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        app_bin = Path(local_app_data) / "OpenAI" / "Codex" / "bin"
        candidates = [path for path in app_bin.glob("*/codex.exe") if path.is_file()]
        if candidates:
            return max(candidates, key=lambda path: path.stat().st_mtime_ns)
    raise RuntimeError("没有找到 Codex 命令行程序，请先安装 Codex CLI 并登录。")


def _stop_process(process: subprocess.Popen, reader: threading.Thread) -> None:
    if process.stdin:
        try:
            process.stdin.close()
        except OSError:
            pass
    try:
        process.wait(timeout=0.5)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
    reader.join(timeout=1)
    if process.stdout:
        process.stdout.close()


def _read_account_limits(timeout: float) -> dict:
    executable = _find_executable()
    command = [str(executable), "-c", "mcp_servers={}", "-c", "plugins={}",
               "-c", "features.plugins=false", "-c", "features.apps=false",
               "-c", "analytics.enabled=false", "app-server", "--stdio"]
    environment = os.environ.copy()
    # Keep the CLI on the launching user's chosen profile. Some Windows hosts
    # run a child under a helper identity with a different native home folder.
    environment.setdefault("CODEX_HOME", str(Path.home() / ".codex"))
    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                                   errors="replace", bufsize=1, env=environment,
                                   cwd=Path(__file__).resolve().parent.parent,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError as exc:
        raise RuntimeError("Codex 额度服务未能启动，请检查 Codex CLI 安装。") from exc
    messages: queue.Queue = queue.Queue()

    def read_lines() -> None:
        try:
            for line in process.stdout:
                messages.put(line)
        except (OSError, ValueError):
            pass
        finally:
            messages.put(None)

    reader = threading.Thread(target=read_lines, name="codex-quota-reader", daemon=True)
    reader.start()
    deadline = time.monotonic() + timeout

    def send(message: dict) -> None:
        try:
            process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
            process.stdin.flush()
        except (OSError, ValueError) as exc:
            raise RuntimeError("Codex 额度连接已关闭，请稍后重试。") from exc

    def receive(request_id: int) -> dict:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError("Codex 额度查询超时，请检查网络后重试。")
            try:
                line = messages.get(timeout=remaining)
            except queue.Empty as exc:
                raise RuntimeError("Codex 额度查询超时，请检查网络后重试。") from exc
            if line is None:
                raise RuntimeError("Codex 额度服务意外退出，请检查登录状态和 CLI 版本。")
            try:
                message = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError("Codex 额度服务返回了无法识别的数据。") from exc
            if not isinstance(message, dict):
                raise RuntimeError("Codex 额度服务返回了无效响应。")
            if message.get("id") != request_id:
                continue
            if "error" in message:
                # Never expose upstream errors, headers, tokens or credentials.
                raise RuntimeError("Codex 额度查询失败，请在 Codex 中确认已登录并检查网络。")
            if not isinstance(message.get("result"), dict):
                raise RuntimeError("Codex 额度服务返回了不完整的响应。")
            return message["result"]

    try:
        send({"id": 1, "method": "initialize", "params": {
            "clientInfo": {"name": "quota_station", "title": "额度小站", "version": "1.0.0"}}})
        receive(1)
        send({"method": "initialized", "params": {}})
        send({"id": 2, "method": "account/rateLimits/read"})
        return receive(2)
    finally:
        _stop_process(process, reader)


def fetch(timeout: float = 25.0) -> dict:
    """Fetch current quota without starting any conversation or model turn."""
    if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise RuntimeError("Codex 查询超时设置必须为正数。")
    return parse_rate_limits(_read_account_limits(timeout))
