"""One read-only integration check, storing only display-ready quota snapshots."""
from concurrent.futures import ThreadPoolExecutor
import importlib
import json
from pathlib import Path
import time

BASE = Path(__file__).resolve().parent

def query(index, name):
    start = time.time()
    try:
        value = importlib.import_module('providers.' + name + '_provider').fetch()
        return index, value, {'provider': value['name'], 'success': True, 'balance': value['balance'], 'unit': value['unit'], 'seconds': round(time.time() - start, 2)}
    except Exception as exc:
        return index, None, {'provider': name, 'success': False, 'error_type': type(exc).__name__}

if __name__ == '__main__':
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda pair: query(*pair), enumerate(['codex', 'qoder', 'workbuddy'])))
    cache = {i: data for i, data, _ in results if data}
    (BASE / 'state').mkdir(exist_ok=True)
    (BASE / 'state' / 'balances.json').write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding='utf-8')
    report = {'checked_at': time.strftime('%Y-%m-%d %H:%M:%S'), 'read_only': True, 'providers': [r for _, _, r in results]}
    (BASE / 'tests' / 'integration_verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))
