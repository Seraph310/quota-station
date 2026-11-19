"""Read the WorkBuddy account menu using Windows accessibility controls."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import time

from .workbuddy_provider import current_account, parse_amount


def _window_handles():
    user = ctypes.windll.user32
    kernel = ctypes.windll.kernel32
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    user.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    user.GetClassNameW.argtypes = user.GetWindowTextW.argtypes
    user.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    user.IsWindowVisible.argtypes = (wintypes.HWND,)
    handles = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _):
        text = ctypes.create_unicode_buffer(260)
        user.GetWindowTextW(hwnd, text, len(text))
        if text.value != 'WorkBuddy':
            return True
        user.GetClassNameW(hwnd, text, len(text))
        if not text.value.startswith('Chrome_WidgetWin_'):
            return True
        pid = wintypes.DWORD()
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        handle = kernel.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
        if handle:
            try:
                filename = ctypes.create_unicode_buffer(32768)
                size = wintypes.DWORD(len(filename))
                if kernel.QueryFullProcessImageNameW(handle, 0, filename, ctypes.byref(size)):
                    if Path(filename.value).name.casefold() == 'workbuddy.exe':
                        handles.append((bool(user.IsWindowVisible(hwnd)), hwnd))
            finally:
                kernel.CloseHandle(handle)
        return True

    user.EnumWindows(visit, 0)
    return [hwnd for _, hwnd in sorted(handles, reverse=True)]


# MSAA roles from oleacc.h.
MENU_POPUP, MENU_ITEM, TEXT, BUTTON, MENU_BUTTON = 11, 12, 41, 43, 57
BALANCE_LABELS = ('积分余额', '積分餘額', 'Credits Balance', 'Credit Balance')
REFRESH_LABELS = {'刷新', '重新整理', 'Refresh'}


class Accessible:
    def __init__(self, api, obj, child=0):
        self.api = api
        self.obj = obj
        self.child = child

    @property
    def role(self):
        return self.obj.accRole[self.child]

    @property
    def name(self):
        return self.obj.accName[self.child] or ''

    def activate(self):
        self.obj.accDoDefaultAction(self.child)

    def children(self):
        if self.child:
            return []
        from comtypes.automation import VARIANT, VT_DISPATCH, VT_I4
        count = min(256, self.obj.accChildCount)
        if count <= 0:
            return []
        variants = (VARIANT * count)()
        obtained = ctypes.c_long()
        self.api.children(self.obj, 0, count, variants, ctypes.byref(obtained))
        nodes = []
        for variant in variants[:obtained.value]:
            if variant.vt == VT_DISPATCH:
                nodes.append(Accessible(self.api, variant.value.QueryInterface(self.api.interface)))
            elif variant.vt == VT_I4 and variant.value > 0:
                nodes.append(Accessible(self.api, self.obj, variant.value))
        return nodes


class Accessibility:
    def __init__(self, interface):
        from comtypes import GUID
        from comtypes.automation import VARIANT
        self.interface = interface
        pointer = ctypes.POINTER(interface)
        oleacc = ctypes.oledll.oleacc
        self.from_window = oleacc.AccessibleObjectFromWindow
        self.from_window.argtypes = (wintypes.HWND, wintypes.DWORD, ctypes.POINTER(GUID), ctypes.POINTER(pointer))
        self.children = oleacc.AccessibleChildren
        self.children.argtypes = (pointer, ctypes.c_long, ctypes.c_long, ctypes.POINTER(VARIANT), ctypes.POINTER(ctypes.c_long))

    def root(self, hwnd):
        obj = ctypes.POINTER(self.interface)()
        self.from_window(hwnd, 0xFFFFFFFC, ctypes.byref(self.interface._iid_), ctypes.byref(obj))  # OBJID_CLIENT
        return Accessible(self, obj)


def _find(root, predicate, limit=900):
    # Return the parent too so the balance search stays inside this avatar's menu.
    from collections import deque
    queue = deque([(None, root)])
    for _ in range(limit):
        if not queue:
            break
        parent, node = queue.popleft()
        if predicate(node):
            return parent, node
        queue.extend((node, child) for child in node.children())
    return None, None


def _account_popup(anchor):
    return _find(anchor, lambda n: n.role == MENU_POPUP, limit=45)[1]


def _credit_cell(popup, nickname):
    if not popup:
        return None
    items = popup.children()
    if not any(item.role == TEXT and item.name == nickname for item in items):
        return None
    return next((item for item in items if item.role == BUTTON and
                 any(item.name.casefold().startswith(label.casefold() + ' ') for label in BALANCE_LABELS)), None)


def _read_menu(anchor, trigger, account):
    opened_here = _account_popup(anchor) is None
    if opened_here:
        trigger.activate()
    try:
        # WorkBuddy fetches account usage when its menu opens. Its dedicated
        # refresh control is needed when the user already had that menu open.
        refreshed = opened_here
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if current_account() != account:
                raise RuntimeError('WorkBuddy 账号已切换，正在重新读取')
            cell = _credit_cell(_account_popup(anchor), account.nickname)
            if cell:
                if not refreshed:
                    refresh = next((n for n in cell.children() if n.role == BUTTON and n.name in REFRESH_LABELS), None)
                    if refresh:
                        refresh.activate()
                        refreshed = True
                        time.sleep(0.25)
                        continue
                name = cell.name
                words = name.split()
                if not any(s.casefold() in ('非最新', 'stale') for s in words):
                    for label in BALANCE_LABELS:
                        if name.casefold().startswith(label.casefold() + ' '):
                            amount = name[len(label):].split()
                            if amount:
                                try:
                                    parse_amount(amount[0])
                                    return amount[0]
                                except RuntimeError:
                                    pass
                            break
            time.sleep(0.2)
        raise RuntimeError('WorkBuddy 尚未显示当前账号的积分')
    finally:
        if opened_here and current_account() == account and _account_popup(anchor):
            trigger.activate()


def _read(api, handles, account):
    from comtypes import COMError
    valid_names = {account.nickname, f'{account.nickname} {account.nickname}'}
    for hwnd in handles:
        try:
            root = api.root(hwnd)
            for _ in range(3):  # Chromium attaches its accessibility tree on demand.
                anchor, trigger = _find(root, lambda n: n.role in (MENU_BUTTON, MENU_ITEM) and n.name in valid_names)
                if trigger and anchor:
                    return _read_menu(anchor, trigger, account)
                time.sleep(0.2)
        except (COMError, OSError):
            continue
    raise RuntimeError('等待 WorkBuddy 客户端显示当前账号')


def read_balance(account):
    handles = _window_handles()
    if not handles or not account.nickname:
        raise RuntimeError('等待 WorkBuddy 客户端显示当前账号')
    try:
        import comtypes
        import comtypes.client
        try:
            from comtypes.gen import Accessibility as msaa
        except ImportError:
            msaa = comtypes.client.GetModule(str(Path(os.environ['SystemRoot']) / 'System32/oleacc.dll'))
        comtypes.CoInitialize()
        try:
            return _read(Accessibility(msaa.IAccessible), handles, account)
        finally:
            comtypes.CoUninitialize()
    except RuntimeError:
        raise
    except Exception:
        raise RuntimeError('WorkBuddy 额度暂时无法读取，请稍后重试') from None
