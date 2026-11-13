"""Read Magpie's public quota API; never change its accounts or routing."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import math
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from .magpie_discovery import discover_executable

MAX_BYTES = 4 * 1024 * 1024
COLORS = {'codex': '#458068', 'qoder': '#8170a7', 'workbuddy': '#ad7a44',
          'codearts': '#b45866', 'deepseek': '#5d73bb', 'kiro': '#8a6bad'}


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.timestamp() if parsed.tzinfo else None
    except (ValueError, OverflowError, OSError):
        return None


def source_id(entry):
    # Keep accounts separate and stable when the API reorders its results. Never
    # persist raw credential fields, even if a future API response includes them.
    identity = [str(entry.get(key) or '').strip() for key in
                ('provider', 'kind', 'user', 'id', 'accountId', 'keyId')]
    if not any(identity[2:]):
        identity.append(str(entry.get('name') or ''))
    digest = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()[:24]
    return 'magpie:' + digest


def _balance(text):
    if not isinstance(text, str):
        return None
    match = re.fullmatch(r'\s*([$¥￥€£]?)\s*(-?\d+(?:,\d{3})*(?:\.\d+)?)\s*([kKmM]?)\s*([\w元积分]*)\s*', text)
    if not match:
        return None
    prefix, raw, scale, suffix = match.groups()
    if prefix and suffix:
        return None
    unit = (prefix or suffix).replace('￥', '¥')
    if unit.lower() in ('credit', 'credits'):
        unit = 'Credits'
    if unit not in ('$', '¥', '€', '£', 'Credits', '积分', '元', 'USD', 'CNY', 'EUR', 'GBP'):
        return None
    value = float(raw.replace(',', '')) * {'k': 1000, 'm': 1000000}.get(scale.lower(), 1)
    if not math.isfinite(value):
        return None
    return value, unit


def _window_name(name):
    return {'7 days': '本周', 'Weekly': '本周', '5 hours': '5 小时',
            'Credits': 'Credits', 'Image generation': '图片生成'}.get(name, name)


def normalize(payload, *, now=None):
    entries = payload.get('data') if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        raise RuntimeError('Magpie 额度响应格式异常')
    now = time.time() if now is None else now
    sources = []
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get('provider'), str) or not entry['provider']:
            continue
        key = source_id(entry)
        if key in seen:
            # Ambiguous API identities cannot safely share one persisted checkbox.
            raise RuntimeError('Magpie 返回了无法区分的同名账号，请在 Magpie 中设置不同名称')
        seen.add(key)
        name = str(entry.get('name') or entry['provider'])[:80]
        account = str(entry.get('alias') or entry.get('user') or '')[:160]
        source = {'id': key, 'name': name, 'provider': entry['provider'],
                  'origin': 'Magpie', 'account': account,
                  'plan': str(entry.get('plan') or '')[:80],
                  'color': COLORS.get(entry['provider'], '#678a90'),
                  'snapshot': None, 'error': ''}
        sources.append(source)
        if entry.get('error'):
            # Vendor error bodies may contain credentials. Expose a useful safe
            # status instead of forwarding the untrusted body to the UI/cache.
            source['error'] = 'Magpie 暂未读到此账号额度，请在 Magpie 中检查连接后刷新'
            continue
        details = [{'label': '数据来源', 'value': 'Magpie'},
                   {'label': '账号', 'value': account or name}]
        if source['plan']:
            details.append({'label': '套餐', 'value': source['plan']})
        candidates = []
        unlimited = False
        windows = entry.get('windows')
        for window in windows if isinstance(windows, list) else []:
            if not isinstance(window, dict):
                continue
            title = str(window.get('name') or '额度')[:80]
            remaining = number(window.get('remaining'))
            used = number(window.get('used'))
            if remaining is None and used is not None:
                remaining = 100 - used
            if window.get('text'):
                detail = str(window.get('display') or '暂无数据')[:120]
                details.append({'label': _window_name(title), 'value': '暂无数据' if detail == 'Unknown' else detail})
                continue
            if window.get('unlimited'):
                unlimited = True
                details.append({'label': _window_name(title), 'value': '不限量'})
                continue
            if remaining is None or not 0 <= remaining <= 100:
                continue
            reset = timestamp(window.get('resetsAt'))
            total, amount = number(window.get('limit')), number(window.get('amount'))
            unit = str(window.get('unit') or '')[:20]
            balance, display_unit = remaining, '%'
            if total is not None and total >= 0 and unit:
                # amount is used (not remaining) in Magpie's API.
                if amount is not None and 0 <= amount <= total:
                    balance, display_unit = total - amount, unit
                elif amount is None:
                    balance, display_unit = total * remaining / 100, unit
            if display_unit.lower() in ('credit', 'credits'):
                display_unit = 'Credits'
            value = f'剩余 {remaining:g}%'
            if display_unit != '%':
                value = f'剩余 {balance:,.2f}'.rstrip('0').rstrip('.') + f' / {total:g} {display_unit}'
            if reset:
                value += time.strftime(' · %m-%d %H:%M 重置', time.localtime(reset))
            details.append({'label': _window_name(title), 'value': value})
            candidates.append((title, {'balance': round(balance, 8), 'unit': display_unit,
                'subtitle': _window_name(title) + '剩余' if display_unit == '%' else '剩余 ' + display_unit,
                'remaining_percent': remaining, 'reset_at': reset}))
        balance = _balance(entry.get('balance'))
        if isinstance(entry.get('balance'), str):
            details.append({'label': '余额', 'value': entry['balance'][:120]})
        for split in entry.get('balanceSplit', []) if isinstance(entry.get('balanceSplit'), list) else []:
            if isinstance(split, dict):
                caption = str(split.get('label') or '余额')[:60]
                details.append({'label': {'Granted': '赠送余额', 'Topped up': '充值余额'}.get(caption, caption),
                                'value': str(split.get('text') or '—')[:120]})
        if candidates:
            _, snapshot = min(candidates, key=lambda pair:
                (pair[0] not in ('7 days', 'Weekly', '总积分', 'Total'), pair[0] in ('Image generation',)))
        elif balance:
            snapshot = {'balance': balance[0], 'unit': balance[1], 'subtitle': '剩余余额',
                        'reset_at': None, 'kind': 'balance'}
        elif unlimited:
            snapshot = {'balance': None, 'unit': '', 'subtitle': '可用额度',
                        'reset_at': None, 'quota_state': 'unlimited'}
        else:
            source['error'] = 'Magpie 暂未提供可确认的额度'
            continue
        snapshot.update(name=name, source='magpie', details=details,
                        updated_at=timestamp(entry.get('readAt')) or timestamp(entry.get('asOf')) or now)
        source['snapshot'] = snapshot
    return sources


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise RuntimeError('Magpie 本机查询地址发生跳转')


def _port(preferred=None):
    try:
        port = int(os.environ.get('QUOTA_MAGPIE_PORT') or preferred or 3425)
        if not 1 <= port <= 65535:
            raise ValueError()
    except (ValueError, TypeError):
        raise RuntimeError('QUOTA_MAGPIE_PORT 必须是有效端口号') from None
    return port


def _gateway(port=None):
    port = _port(port)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    with opener.open(f'http://127.0.0.1:{port}/v1/magpie/quotas', timeout=8) as response:
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise RuntimeError('Magpie 额度响应过大')
    return json.loads(raw.decode('utf-8'))


def _cli(executable=None):
    executable = executable or discover_executable()
    if not executable:
        raise RuntimeError('未连接 Magpie，请打开 Magpie 后刷新')
    result = subprocess.run([executable, 'quota', '--json'], capture_output=True,
                            timeout=35, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode or len(result.stdout) > MAX_BYTES:
        raise RuntimeError('Magpie 暂时无法读取额度，请打开 Magpie 后刷新')
    return json.loads(result.stdout.decode('utf-8-sig'))


def _status(executable):
    if not executable:
        return {}
    try:
        result = subprocess.run([executable, 'status', '--json'], capture_output=True, timeout=5,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode or len(result.stdout) > 64 * 1024:
            return {}
        value = json.loads(result.stdout.decode('utf-8-sig'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}


def _status_port(status):
    try:
        url = status.get('url', '')
        parsed = urlsplit(url)
        # Never adopt a remote URL or credentials; only its listening port, then
        # query loopback. HTTPS-only installations can use the CLI fallback.
        if parsed.scheme == 'http' and parsed.port and 1 <= parsed.port <= 65535:
            return parsed.port
    except (ValueError, TypeError, AttributeError):
        pass
    return None


def fetch(connection=None):
    connection = connection if isinstance(connection, dict) else {}
    try:
        try:
            payload = _gateway(connection.get('port'))
        except (OSError, urllib.error.URLError):
            payload = _cli(discover_executable(connection.get('executable')))
        return normalize(payload)
    except RuntimeError:
        raise
    except Exception:
        raise RuntimeError('Magpie 额度暂时不可用，请打开 Magpie 后刷新') from None


class SyncError(RuntimeError):
    def __init__(self, message, connection):
        super().__init__(message)
        self.connection = connection


def synchronize(previous=None):
    """Locate Magpie, read its actual gateway port, then sync current quotas."""
    previous = previous if isinstance(previous, dict) else {}
    connection = dict(previous)
    try:
        executable = discover_executable(previous.get('executable'), rediscover=True)
        status = _status(executable)
        port = _port(_status_port(status) or previous.get('port'))
        connection.update(executable=executable or '', port=port,
                          version=str(status.get('version') or '')[:60])
        try:
            payload = _gateway(port)
            transport = 'gateway'
        except (OSError, urllib.error.URLError):
            if not executable:
                raise RuntimeError('未找到本机 Magpie，请先打开 Magpie，再点击一键同步') from None
            payload = _cli(executable)
            transport = 'cli'
        sources = normalize(payload)
        connection.update(transport=transport, synced_at=time.time(), source_count=len(sources),
                          readable_count=sum(source.get('snapshot') is not None for source in sources))
        return {'sources': sources, 'connection': connection}
    except RuntimeError as exc:
        raise SyncError(str(exc), connection) from None
    except Exception:
        raise SyncError('Magpie 同步暂未完成，请确认已打开 Magpie 后重试', connection) from None
