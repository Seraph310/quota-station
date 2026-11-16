"""Small update dialog; checks are silent until the user opens it."""
import json
from pathlib import Path
import sys
import threading
import time

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QProgressBar, QPushButton, QVBoxLayout

import updater_core as core
from version import __version__
from i18n import tr, language


class UpdateSignals(QObject):
    checked = Signal(object, str)
    progress = Signal(int, str)
    prepared = Signal(str, str)
    handoff = Signal(object, str)


class UpdateDialog(QDialog):
    def __init__(self, controller):
        super().__init__(None, Qt.WindowType.Window)
        self.controller = controller
        controller.station.destroyed.connect(self.deleteLater)
        self.setWindowTitle('额度小站 · 检查更新')
        self.setWindowIcon(controller.station.windowIcon())
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, controller.station.topmost)
        self.setMinimumWidth(350)
        self.setStyleSheet('''
            QDialog { background:#fcfdfb; }
            QLabel { color:#303532; font-size:13px; }
            QPushButton { background:#f0f3ee; border:0; border-radius:8px; padding:8px 16px; color:#303532; }
            QPushButton:hover { background:#e3e8df; }
            QPushButton:disabled { color:#899185; }
            QProgressBar { border:0; background:#e3e8df; border-radius:3px; height:6px; }
            QProgressBar::chunk { background:#458068; border-radius:3px; }
            QPlainTextEdit { border:0; background:#f0f3ee; color:#303532; padding:8px; }
        ''')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(14)
        self.version = QLabel(f'当前版本  v{__version__}')
        layout.addWidget(self.version)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)
        self.notes = QPlainTextEdit()
        self.notes.setReadOnly(True)
        self.notes.setFixedHeight(180)
        self.notes.hide()
        layout.addWidget(self.notes)
        row = QHBoxLayout()
        self.details = QPushButton('更新内容')
        self.details.setCheckable(True)
        self.details.toggled.connect(self.notes.setVisible)
        row.addWidget(self.details)
        row.addStretch()
        self.cancel = QPushButton('关闭')
        self.cancel.clicked.connect(self.close)
        row.addWidget(self.cancel)
        self.action = QPushButton('检查更新')
        self.action.setStyleSheet('background:#458068;color:white;')
        self.action.clicked.connect(controller.primary_action)
        row.addWidget(self.action)
        layout.addLayout(row)
        self.sync()

    def sync(self):
        controller = self.controller
        self.setWindowTitle(tr('额度小站 · 检查更新'))
        self.version.setText(tr('当前版本  v{version}', version=__version__))
        self.details.setText(tr('更新内容'))
        busy = controller.state in ('checking', 'downloading')
        self.status.setText(tr(controller.message))
        self.progress.setVisible(busy)
        self.progress.setRange(0, 0 if controller.percent < 0 else 100)
        if controller.percent >= 0:
            self.progress.setValue(controller.percent)
        self.action.setEnabled(not busy)
        self.action.setText(tr(('安装桌面版' if controller.source_mode else '一键升级')
                            if controller.can_install() else '再次检查'))
        self.cancel.setText(tr('取消' if controller.state == 'downloading' else '关闭'))
        self.details.setVisible(bool(controller.release))
        self.notes.setPlainText(controller.release['notes'] if controller.release else '')
        # A live language switch can make a button wider than its old geometry.
        for button in (self.details, self.cancel, self.action):
            button.setMinimumWidth(button.fontMetrics().horizontalAdvance(button.text()) + 32)
        if getattr(self, '_language', None) != language():
            self._language = language()
            self.layout().activate()
            self.adjustSize()

    def closeEvent(self, event):
        if self.controller.state == 'downloading':
            self.controller.cancel.set()
        super().closeEvent(event)


class UpdateController(QObject):
    def __init__(self, station, action):
        super().__init__(station)
        self.station, self.action = station, action
        self.dialog = None
        self.state, self.message, self.percent = 'idle', '', -1
        self.source_mode = not getattr(sys, 'frozen', False)
        self.release = None
        self.pending_job = None
        self.cancel = threading.Event()
        self.signals = UpdateSignals(self)
        self.signals.checked.connect(self.checked)
        self.signals.progress.connect(self.progressed)
        self.signals.prepared.connect(self.prepared)
        self.signals.handoff.connect(self.handed_off)
        self.auto_timer = QTimer(self)
        self.auto_timer.setSingleShot(True)
        self.auto_timer.timeout.connect(self.auto_check)
        if not station.offline:
            try:
                previous = json.loads((core.user_data_root() / 'updates/last-result.json').read_text('utf-8'))
                if previous.get('status') == 'error':
                    self.state, self.message = 'rollback', previous['message']
                    self.action.setText('上次升级未完成…')
            except (OSError, ValueError, KeyError, AttributeError):
                pass
            self.auto_timer.start(20_000)

    def sync(self):
        caption = '上次升级未完成…' if self.state == 'rollback' else (
            f'发现新版本 v{self.release["version"]}…' if self.release and self.release['newer'] else '检查更新…')
        self.action.setText(tr(caption))
        if self.dialog:
            self.dialog.sync()

    def show(self):
        self.station.mini.timer.stop()
        if self.dialog is None:
            self.dialog = UpdateDialog(self)
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()
        if self.state in ('idle', 'error'):
            self.check()
        else:
            self.sync()

    def can_install(self):
        return bool(self.release and (self.release['newer'] or
                    (self.source_mode and core.version_tuple(self.release['version']) >= (0, 4, 0))))

    def auto_check(self):
        if self.state == 'rollback':
            self.auto_timer.start(86400_000)
            return
        path = core.user_data_root() / 'updates/check.json'
        try:
            last = json.loads(path.read_text('utf-8')).get('checked_at', 0)
        except (OSError, ValueError, AttributeError):
            last = 0
        if not isinstance(last, (int, float)) or time.time() - last >= 86400:
            self.check()
        self.auto_timer.start(86400_000)

    def check(self):
        if self.state in ('checking', 'downloading'):
            return
        self.state, self.message, self.percent = 'checking', '正在检查更新…', -1
        self.sync()
        def work():
            try:
                release = core.check_release(__version__)
                self.signals.checked.emit(release, '')
            except Exception as exc:
                self.signals.checked.emit(None, str(exc) if isinstance(exc, core.UpdateError) else '检查更新失败，请稍后重试')
        threading.Thread(target=work, daemon=True).start()

    def checked(self, release, error):
        if error:
            self.state, self.message = 'error', error
        else:
            self.release = release
            self.state = 'available' if self.can_install() else 'latest'
            self.message = f'新版本  v{release["version"]}' if release['newer'] else '已是最新版本'
            if self.source_mode and self.can_install():
                self.message = f'可安装桌面版  v{release["version"]}'
            self.action.setText(f'发现新版本 v{release["version"]}…' if release['newer'] else '检查更新…')
            if not self.station.offline:
                try:
                    core.write_json(core.user_data_root() / 'updates/check.json', {'checked_at': time.time()})
                except OSError:
                    pass
        self.sync()

    def primary_action(self):
        if self.state in ('checking', 'downloading'):
            return
        if not self.can_install():
            self.check()
            return
        self.cancel.clear()
        self.state, self.message, self.percent = 'downloading', '正在下载', 0
        self.sync()
        release = dict(self.release)
        def work():
            try:
                job = core.prepare_update(release, self.signals.progress.emit, self.cancel)
                self.signals.prepared.emit(str(job), '')
            except Exception as exc:
                self.signals.prepared.emit('', str(exc) if isinstance(exc, core.UpdateError) else '下载或准备失败，当前版本未改变，请重试')
        threading.Thread(target=work, daemon=True).start()

    def progressed(self, percent, message):
        self.percent = percent
        self.message = f'{message}  {percent}%' if percent >= 0 else message
        self.sync()

    def prepared(self, job, error):
        if error or self.cancel.is_set():
            if job:
                core.discard_update(job)
            self.state, self.message = 'error', error or '已取消更新'
            self.sync()
            return
        try:
            if not self.station.save_settings():
                raise core.UpdateError('设置未能保存，升级已停止')
        except Exception as exc:
            self.state, self.message = 'error', str(exc) if isinstance(exc, core.UpdateError) else '无法启动升级，当前版本未改变'
            self.sync()
            return
        self.message = '正在升级，即将重新打开…'
        self.pending_job = job
        self.sync()
        def work():
            try:
                self.signals.handoff.emit(core.launch_update(Path(job)), '')
            except Exception as exc:
                self.signals.handoff.emit(None, str(exc) if isinstance(exc, core.UpdateError) else '无法启动升级，当前版本未改变')
        threading.Thread(target=work, daemon=True).start()

    def handed_off(self, process, error):
        if error or self.cancel.is_set():
            if process is not None and process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
            if self.pending_job:
                core.discard_update(self.pending_job)
            self.state, self.message = 'error', error or '已取消更新'
            self.sync()
            return
        self.station.quit()
