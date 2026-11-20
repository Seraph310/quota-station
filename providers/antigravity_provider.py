"""Read quota groups from the running official Antigravity desktop service."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.request

from .magpie_provider import timestamp
from updater_core import process_alive


OFFLINE_MESSAGE = 'Antigravity 已关闭，等待客户端更新额度'
NO_ACCOUNT_MESSAGE = '请先在 Antigravity 官方客户端登录'
ACCOUNT_CHANGED_MESSAGE = 'Antigravity 账号已切换，等待新账号额度'
MAX_BYTES = 4 * 1024 * 1024
WEEKLY_MODELS = ('Gemini', 'Argon')


def weekly_quotas(snapshot):
    """Return the two selected weekly quotas, including pre-structured caches."""
    if not snapshot or snapshot.get('source') != 'antigravity':
        return []
    stored = snapshot.get('weekly_quotas')
    values = {}
    if isinstance(stored, list):
        for item in stored:
            if isinstance(item, dict) and item.get('model') in WEEKLY_MODELS:
                values[item['model']] = item.get('balance')
    else:
        # Older snapshots stored these exact labels and percentage strings only.
        # Preserve their timestamp; reading the cache is not a quota refresh.
        for detail in snapshot.get('details', []):
            if not isinstance(detail, dict):
                continue
            for model in WEEKLY_MODELS:
                if detail.get('label') == f'{model} · 本周':
                    match = re.match(r'^剩余 (\d+(?:\.\d+)?)%(?: · |$)', str(detail.get('value', '')))
                    if match:
                        values[model] = float(match[1])
    return [{'model': model, 'balance': value if type(value) in (int, float)
             and math.isfinite(value) and 0 <= value <= 100 else None, 'unit': '%'}
            for model in WEEKLY_MODELS for value in [values.get(model)]]


def display_snapshot(snapshot):
    """Make single-value surfaces follow the selected weekly quotas too."""
    quotas = weekly_quotas(snapshot)
    if not quotas:
        return snapshot
    known = [item for item in quotas if item['balance'] is not None]
    if not known:
        raise ValueError('Antigravity 暂未返回可确认的额度')
    limiting = min(known, key=lambda item: item['balance'])
    return dict(snapshot, weekly_quotas=quotas, balance=limiting['balance'],
                remaining_percent=limiting['balance'], subtitle='本周剩余', reset_at=None)


def _server():
    root = Path(os.environ.get('ANTIGRAVITY_HOME') or Path.home() / '.gemini/antigravity')
    directory = root / 'daemon'
    try:
        files = sorted(directory.glob('hub_*.json'), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        files = []
    for path in files[:32]:
        try:
            with path.open('rb') as stream:
                raw = stream.read(8193)
            if len(raw) > 8192:
                continue
            server = json.loads(raw)
            pid, port, csrf = server['pid'], server['httpPort'], server['csrfToken']
            if (type(pid) is int and pid > 0 and type(port) is int and 1 <= port <= 65535
                    and isinstance(csrf, str) and 1 <= len(csrf) <= 512
                    and csrf.isascii() and not any(c.isspace() for c in csrf) and process_alive(pid)):
                return server
        except (OSError, ValueError, KeyError, TypeError):
            continue
    raise RuntimeError(OFFLINE_MESSAGE)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise RuntimeError('Antigravity 本机查询地址发生跳转')


def _request(server, method, payload):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    request = urllib.request.Request(
        f'http://127.0.0.1:{server["httpPort"]}/exa.language_server_pb.LanguageServerService/{method}',
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json', 'Connect-Protocol-Version': '1',
                 'X-Codeium-Csrf-Token': server['csrfToken']},
    )
    with opener.open(request, timeout=12) as response:
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise RuntimeError('Antigravity 额度响应过大')
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise RuntimeError('Antigravity 额度响应格式异常')
    return result


def _account(server):
    user = _request(server, 'GetUserStatus', {}).get('userStatus')
    email = user.get('email') if isinstance(user, dict) else None
    if not isinstance(email, str) or not email.strip():
        raise RuntimeError(NO_ACCOUNT_MESSAGE)
    return email.strip().casefold()


def normalize(payload, account, *, now=None):
    response = payload.get('response') if isinstance(payload, dict) else None
    if not isinstance(response, dict):
        raise RuntimeError('Antigravity 额度响应格式异常')
    groups = response.get('groups', [])
    if not isinstance(groups, list):
        raise RuntimeError('Antigravity 额度响应格式异常')
    if not groups and isinstance(response.get('buckets'), list):
        groups = [{'displayName': 'Antigravity', 'buckets': response['buckets']}]
    details = [{'label': '数据来源', 'value': 'Antigravity 官方客户端'},
               {'label': '账号', 'value': account}]
    weekly = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        title = str(group.get('displayName') or 'Antigravity')[:80]
        title = {'Gemini Models': 'Gemini', 'Claude and GPT models': 'Claude/GPT',
                 'Gemini 4 Argon': 'Argon'}.get(title, title)
        buckets = group.get('buckets')
        for bucket in buckets if isinstance(buckets, list) else []:
            if not isinstance(bucket, dict):
                continue
            window = bucket.get('window')
            window = {'weekly': '本周', '5h': '5 小时'}.get(window, str(bucket.get('displayName') or '额度')[:80])
            label = f'{title} · {window}'
            fraction = bucket.get('remainingFraction')
            if (bucket.get('disabled') or isinstance(fraction, bool)
                    or not isinstance(fraction, (int, float)) or not math.isfinite(fraction)
                    or not 0 <= fraction <= 1):
                details.append({'label': label, 'value': '暂不可用'})
                continue
            remaining = round(fraction * 100, 6)
            reset = timestamp(bucket.get('resetTime'))
            value = f'剩余 {remaining:g}%'
            if reset:
                value += ' · ' + time.strftime('%m-%d %H:%M', time.localtime(reset)) + ' 重置'
            details.append({'label': label, 'value': value})
            if title in WEEKLY_MODELS and bucket.get('window') == 'weekly':
                weekly.append({'model': title, 'balance': remaining})
    if not weekly:
        raise RuntimeError('Antigravity 暂未返回可确认的额度')
    snapshot = dict(name='Antigravity', source='antigravity', unit='%',
                    weekly_quotas=weekly, details=details,
                    account_key=hashlib.sha256(account.encode()).hexdigest(),
                    updated_at=time.time() if now is None else now)
    return display_snapshot(snapshot)


def fetch():
    try:
        server = _server()
        account = _account(server)
        result = _request(server, 'RetrieveUserQuotaSummary', {'request': {}, 'forceRefresh': True})
        if _account(server) != account:
            raise RuntimeError(ACCOUNT_CHANGED_MESSAGE)
        return normalize(result, account)
    except RuntimeError:
        raise
    except (OSError, ValueError, TypeError, KeyError):
        raise RuntimeError('Antigravity 本机额度暂时无法读取，请稍后刷新') from None
