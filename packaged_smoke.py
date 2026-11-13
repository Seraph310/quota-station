"""Exercise the frozen application with synthetic data, without live accounts."""
import importlib
import json
import platform
from pathlib import Path
import sys

from demo import DemoStation, demo_state
import app as station_app
from version import __version__


def run(application, destination):
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    modules = ['codex_provider', 'qoder_provider', 'workbuddy_provider', 'magpie_provider']
    for name in modules:
        importlib.import_module('providers.' + name)
    bridge = station_app.BASE / 'providers/qoder_runtime/qoder_ide_bridge.mjs'
    if getattr(sys, 'frozen', False) and not bridge.is_file():
        raise RuntimeError('Packaged Qoder bridge is missing')
    real_state = station_app.STATE
    with demo_state():
        assert station_app.STATE != real_state
        station = DemoStation()
        try:
            station.show()
            for key, source in list(station.sources.items()):
                if source['origin'] == 'Magpie' and source['provider'] in ('codearts', 'deepseek'):
                    station.set_source_visible(key, True)
            application.processEvents()
            assert station.grab().save(str(destination / 'card.png'))
            station.cycle(1)
            turn = station.mini.page_turn
            assert turn.isVisible() and turn.before is not None
            turn.animation.pause()
            turn.animation.setCurrentTime(turn.DURATION // 2)
            application.processEvents()
            assert station.grab().save(str(destination / 'page-turn.png'))
            turn.finish()
            station.expand()
            application.processEvents()
            assert station.grab().save(str(destination / 'expanded.png'))
            station.show_sources()
            application.processEvents()
            assert station.source_picker.grab().save(str(destination / 'sources.png'))
            report = {'success': True, 'version': __version__, 'frozen': bool(getattr(sys, 'frozen', False)),
                      'platform': sys.platform, 'architecture': platform.machine(),
                      'native_sources': station_app.native_source_keys(), 'state_isolated': True,
                      'provider_imports': modules, 'visible_sources': len(station.visible_sources)}
        finally:
            if station.source_picker:
                station.source_picker.close()
            station.poll.stop()
            station.clock.stop()
            station.tray.hide()
            station.close()
    assert station_app.STATE == real_state
    (destination / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return 0
