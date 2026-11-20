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
    modules = ['codex_provider', 'qoder_provider', 'workbuddy_provider', 'antigravity_provider', 'magpie_provider']
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
            for side in ('left', 'right'):
                station.docking.dock(side, application.primaryScreen())
                application.processEvents()
                assert station.width() == 12 and station.height() == 64
                assert station.grab().save(str(destination / f'dock-{side}.png'))
                station.docking.peek()
                application.processEvents()
                assert station.mini.isVisible() and station.docking.peeked
                assert station.grab().save(str(destination / f'dock-{side}-peek.png'))
                station.docking.tuck()
            station.docking.undock()
            station.expand()
            application.processEvents()
            assert station.grab().save(str(destination / 'expanded.png'))
            station.show_sources()
            application.processEvents()
            assert station.source_picker.grab().save(str(destination / 'sources.png'))
            from updater_ui import UpdateDialog
            station.updater.release = {'version': '99.0.0', 'newer': True, 'notes': '演示更新内容'}
            station.updater.state, station.updater.message = 'available', '新版本  v99.0.0'
            station.updater.dialog = UpdateDialog(station.updater)
            station.updater.dialog.show()
            application.processEvents()
            assert station.updater.dialog.action.text() in ('一键升级', '安装桌面版')
            assert station.updater.dialog.grab().save(str(destination / 'updates.png'))
            station.set_language('en')
            application.processEvents()
            assert station.source_picker.done_button.text() == 'Done'
            assert station.updater.dialog.action.text() in ('Update now', 'Install desktop app')
            assert station.grab().save(str(destination / 'expanded-en.png'))
            assert station.source_picker.grab().save(str(destination / 'sources-en.png'))
            assert station.updater.dialog.grab().save(str(destination / 'updates-en.png'))
            station.collapse()
            application.processEvents()
            assert station.grab().save(str(destination / 'card-en.png'))
            station.set_language('zh-CN')
            assert station.source_picker.done_button.text() == '完成'
            assert station.updater.dialog.action.text() in ('一键升级', '安装桌面版')
            if 3 in station.sources:
                from providers import antigravity_provider as antigravity
                payload = {'response': {'groups': [
                    {'displayName': 'Gemini Models', 'buckets': [{'window': 'weekly', 'remainingFraction': .42}]},
                    {'displayName': 'Gemini 4 Argon', 'buckets': [{'window': 'weekly', 'remainingFraction': .8}]},
                ]}}
                station.set_source_visible(3, True)
                station.receive(3, antigravity.normalize(payload, 'demo@example.test'), '')
                station.active = station.visible_sources.index(3)
                station_app.Station.render(station)
                application.processEvents()
                assert [v.text() for _, v in station.mini.weekly.readings] == ['42%', '80%']
                assert station.mini.weekly.isVisible() and station.mini.value.isHidden()
                assert station.grab().save(str(destination / 'antigravity-weekly.png'))
                station.receive(3, None, antigravity.OFFLINE_MESSAGE)
                station_app.Station.render(station)
                application.processEvents()
                assert station.mini.unit.text() == '上次读数'
                assert station.grab().save(str(destination / 'antigravity-weekly-cached.png'))
            report = {'success': True, 'version': __version__, 'frozen': bool(getattr(sys, 'frozen', False)),
                      'platform': sys.platform, 'architecture': platform.machine(),
                      'native_sources': station_app.native_source_keys(), 'state_isolated': True,
                      'provider_imports': modules, 'visible_sources': len(station.visible_sources),
                      'edge_docking': ['left', 'right'], 'languages': ['zh-CN', 'en'],
                      'live_language_switch': True, 'antigravity_weekly_pair': 3 in station.sources}
        finally:
            if station.source_picker:
                station.source_picker.close()
            if station.updater.dialog:
                station.updater.dialog.close()
            station.poll.stop()
            station.clock.stop()
            station.tray.hide()
            station.close()
    assert station_app.STATE == real_state
    (destination / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return 0
