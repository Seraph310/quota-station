"""Windows-only credential helpers adapted from the user's existing credits ball.

Source: ~/WorkBuddy/wb-credits-ball/credits_ball.py, read-only source.
No process writes, privilege elevation, application launch, or non-WorkBuddy
process discovery. Secret values must never be logged by callers.
"""

from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes as wt
import json
import os
from pathlib import Path
import re
import time


_TOKEN = re.compile(rb"Bearer (eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,})")
_PIPE = re.compile(r"workbuddy-pac-(\d+)-")


class DataBlob(ctypes.Structure):
    _fields_ = [("size", wt.DWORD), ("data", ctypes.POINTER(ctypes.c_char))]


class MemoryInformation(ctypes.Structure):
    _fields_ = [
        ("base", ctypes.c_void_p), ("allocation_base", ctypes.c_void_p),
        ("allocation_protect", wt.DWORD), ("region_size", ctypes.c_size_t),
        ("state", wt.DWORD), ("protect", wt.DWORD), ("kind", wt.DWORD),
    ]


def token_metadata(token: str) -> dict:
    try:
        chunk = token.split(".")[1]
        value = json.loads(base64.urlsafe_b64decode(chunk + "=" * (-len(chunk) % 4)))
        return value if isinstance(value, dict) else {}
    except (ValueError, IndexError, TypeError):
        return {}


def valid_token(token: str | None) -> bool:
    if not isinstance(token, str) or len(token) > 32768 or token.count(".") != 2:
        return False
    metadata = token_metadata(token)
    try:
        return metadata.get("aud") == "account" and float(metadata["exp"]) > time.time() + 30
    except (KeyError, ValueError, TypeError, OverflowError):
        return False


def _kernel():
    if os.name != "nt":
        raise RuntimeError("WorkBuddy 登录读取需要 Windows 环境")
    lib = ctypes.WinDLL("kernel32", use_last_error=True)
    lib.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    lib.OpenProcess.restype = wt.HANDLE
    lib.CloseHandle.argtypes = [wt.HANDLE]
    lib.CloseHandle.restype = wt.BOOL
    lib.LocalFree.argtypes = [ctypes.c_void_p]
    lib.LocalFree.restype = ctypes.c_void_p
    lib.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
    lib.ReadProcessMemory.restype = wt.BOOL
    lib.VirtualQueryEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.POINTER(MemoryInformation), ctypes.c_size_t]
    lib.VirtualQueryEx.restype = ctypes.c_size_t
    lib.FindFirstFileW.argtypes = [wt.LPCWSTR, ctypes.c_void_p]
    lib.FindFirstFileW.restype = wt.HANDLE
    lib.FindNextFileW.argtypes = [wt.HANDLE, ctypes.c_void_p]
    lib.FindNextFileW.restype = wt.BOOL
    lib.FindClose.argtypes = [wt.HANDLE]
    lib.FindClose.restype = wt.BOOL
    return lib


def _dpapi(data: bytes, encrypt: bool) -> bytes | None:
    if not data or len(data) > 65536 or os.name != "nt":
        return None
    kernel = _kernel()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    function = crypt.CryptProtectData if encrypt else crypt.CryptUnprotectData
    function.argtypes = [ctypes.POINTER(DataBlob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(DataBlob)]
    function.restype = wt.BOOL
    buffer = ctypes.create_string_buffer(data, len(data))
    incoming = DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    outgoing = DataBlob()
    # CRYPTPROTECT_UI_FORBIDDEN: never prompt for user interaction.
    if not function(ctypes.byref(incoming), None, None, None, None, 1, ctypes.byref(outgoing)):
        return None
    try:
        return ctypes.string_at(outgoing.data, outgoing.size)
    finally:
        kernel.LocalFree(outgoing.data)


def read_cached_token(path: Path) -> str | None:
    try:
        if path.stat().st_size > 65536:
            return None
        plain = _dpapi(path.read_bytes(), encrypt=False)
        token = plain.decode("utf-8") if plain else None
        return token if valid_token(token) else None
    except (OSError, UnicodeError):
        return None


def write_cached_token(path: Path, token: str) -> bool:
    """Caller supplies only a cache destination inside this new project."""
    if not valid_token(token):
        return False
    encrypted = _dpapi(token.encode("utf-8"), encrypt=True)
    if not encrypted:
        return False
    temporary = path.with_suffix(path.suffix + ".part")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_bytes(encrypted)
        temporary.replace(path)
        return True
    except OSError:
        return False


def _workbuddy_pids(kernel) -> list[int]:
    # Same named-pipe discovery as the original program. No all-process scan.
    buffer = ctypes.create_string_buffer(592)  # WIN32_FIND_DATAW
    handle = kernel.FindFirstFileW(r"\\.\pipe\workbuddy-pac-*", buffer)
    if not handle or handle == ctypes.c_void_p(-1).value:
        return []
    pids = set()
    try:
        while True:
            name = buffer.raw[44:564].decode("utf-16-le", "ignore").split("\0")[0]
            match = _PIPE.search(name)
            if match:
                pids.add(int(match.group(1)))
            if not kernel.FindNextFileW(handle, buffer):
                break
    finally:
        kernel.FindClose(handle)
    return sorted(pids)


def find_running_token() -> str | None:
    """Read a bounded amount from existing WorkBuddy service process memory."""
    if ctypes.sizeof(ctypes.c_void_p) != 8:
        return None
    kernel = _kernel()
    deadline = time.monotonic() + 8
    remaining = 512 * 1024 * 1024
    newest, newest_iat = None, -1.0
    for pid in _workbuddy_pids(kernel):
        handle = kernel.OpenProcess(0x0400 | 0x0010, False, pid)
        if not handle:
            continue
        try:
            address = 0
            info = MemoryInformation()
            while time.monotonic() < deadline and remaining > 0:
                if not kernel.VirtualQueryEx(handle, ctypes.c_void_p(address), ctypes.byref(info), ctypes.sizeof(info)):
                    break
                base, size = int(info.base or 0), int(info.region_size)
                if size <= 0 or base + size <= address:
                    break
                if info.state == 0x1000 and info.kind == 0x20000 and info.protect in (0x02, 0x04, 0x20, 0x40):
                    offset, tail = 0, b""
                    while offset < size and remaining > 0 and time.monotonic() < deadline:
                        count = min(8 * 1024 * 1024, size - offset, remaining)
                        buffer = ctypes.create_string_buffer(count)
                        read = ctypes.c_size_t()
                        ok = kernel.ReadProcessMemory(handle, ctypes.c_void_p(base + offset), buffer, count, ctypes.byref(read))
                        remaining -= count
                        offset += count
                        if not ok:
                            tail = b""
                            continue
                        data = tail + buffer.raw[:read.value]
                        for match in _TOKEN.finditer(data):
                            token = match.group(1).decode("ascii")
                            if valid_token(token):
                                try:
                                    issued = float(token_metadata(token).get("iat", 0))
                                except (TypeError, ValueError):
                                    issued = 0
                                if issued >= newest_iat:
                                    newest, newest_iat = token, issued
                        tail = data[-32768:]
                address = base + size
        finally:
            kernel.CloseHandle(handle)
    return newest


def executable_version(path: Path) -> str | None:
    if os.name != "nt" or not path.is_file():
        return None
    version = ctypes.WinDLL("version", use_last_error=True)
    version.GetFileVersionInfoSizeW.argtypes = [wt.LPCWSTR, ctypes.POINTER(wt.DWORD)]
    version.GetFileVersionInfoSizeW.restype = wt.DWORD
    version.GetFileVersionInfoW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p]
    version.GetFileVersionInfoW.restype = wt.BOOL
    version.VerQueryValueW.argtypes = [ctypes.c_void_p, wt.LPCWSTR, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wt.UINT)]
    version.VerQueryValueW.restype = wt.BOOL
    unused = wt.DWORD()
    size = version.GetFileVersionInfoSizeW(str(path), ctypes.byref(unused))
    if not size or size > 4 * 1024 * 1024:
        return None
    buffer = ctypes.create_string_buffer(size)
    if not version.GetFileVersionInfoW(str(path), 0, size, buffer):
        return None
    pointer, length = ctypes.c_void_p(), wt.UINT()
    if not version.VerQueryValueW(buffer, "\\", ctypes.byref(pointer), ctypes.byref(length)) or length.value < 52:
        return None
    fixed = ctypes.cast(pointer, ctypes.POINTER(wt.DWORD))
    if fixed[0] != 0xFEEF04BD:
        return None
    major_minor, build_revision = fixed[4], fixed[5]  # product version
    return f"{major_minor >> 16}.{major_minor & 65535}.{build_revision >> 16}"
