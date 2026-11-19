"""Read the active WorkBuddy account and its displayed credit balance."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import time


@dataclass(frozen=True)
class Account:
    key: str
    nickname: str


def account_snapshot_path() -> Path:
    root = Path(os.environ.get('WORKBUDDY_HOME') or Path.home() / '.workbuddy')
    return root / 'storage' / 'skeleton' / 'account-snapshot.json'


def current_account() -> Account | None:
    try:
        with account_snapshot_path().open('rb') as stream:
            raw = stream.read(4097)
        if len(raw) > 4096:
            return None
        profile = json.loads(raw)['primary']
        uid, kind = profile['uid'], profile['type']
        team = profile.get('enterpriseId') or ''
        if not all(isinstance(part, str) for part in (uid, kind, team)) or not uid.strip() or not kind.strip():
            return None
        identity = json.dumps([uid.strip(), kind.strip(), team.strip()], ensure_ascii=False)
        nickname = profile.get('nickname') or profile.get('displayName') or ''
        return Account(hashlib.sha256(identity.encode()).hexdigest(), str(nickname).strip())
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None


_AMOUNT = re.compile(r'(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?')
_UNLIMITED = {'不限量', '无限', '无限量', '無限', '無限量', 'unlimited', '∞'}


def parse_amount(text: str):
    text = text.strip()
    if text.casefold() in _UNLIMITED:
        return None, 'unlimited'
    if _AMOUNT.fullmatch(text):
        import math
        value = float(text.replace(',', ''))
        if math.isfinite(value):
            return value, 'available'
    raise RuntimeError('WorkBuddy 尚未显示当前账号的积分')


def fetch() -> dict:
    account = current_account()
    if not account:
        raise RuntimeError('未找到 WorkBuddy 登录状态，请先打开 WorkBuddy 并登录')
    if os.name != 'nt':
        raise RuntimeError('WorkBuddy 本机额度目前仅支持 Windows')
    from ._workbuddy_windows import read_balance
    text = read_balance(account)
    if current_account() != account:
        raise RuntimeError('WorkBuddy 账号已切换，正在重新读取')
    balance, state = parse_amount(text)
    return {
        'name': 'WorkBuddy', 'source': 'workbuddy', 'account_key': account.key,
        'balance': balance, 'quota_state': state, 'unit': '积分', 'subtitle': '剩余积分',
        'reset_at': None, 'updated_at': time.time(),
        'details': [{'label': '额度口径', 'value': 'WorkBuddy 客户端积分余额'}],
    }
