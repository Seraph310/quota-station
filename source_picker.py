"""The source selection page. Checkboxes apply immediately and stay local."""
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFrame, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)


class SourcePicker(QDialog):
    def __init__(self, station):
        super().__init__(None, Qt.WindowType.Window)
        self.station = station
        station.destroyed.connect(self.deleteLater)
        self.setWindowIcon(station.windowIcon())
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, station.topmost)
        self.setWindowTitle('额度小站 · 显示来源')
        self.setObjectName('sourcePicker')
        self.resize(480, 610)
        self.setMinimumSize(380, 340)
        self.setStyleSheet('''
            QDialog#sourcePicker, QScrollArea, QWidget#sourceList { background:#fcfdfb; }
            QLabel { color:#303532; background:transparent; border:0; }
            QScrollArea { border:0; }
            QCheckBox { color:#303532; font-size:14px; spacing:12px; padding:3px 0; }
            QCheckBox::indicator { width:18px; height:18px; }
            QPushButton { background:#f0f3ee; border:0; border-radius:9px; padding:8px 14px; color:#303532; }
            QPushButton:hover { background:#e3e8df; }
            QPushButton:disabled { color:#899185; }
            QScrollBar:vertical { background:transparent; width:6px; margin:0; }
            QScrollBar::handle:vertical { background:#cdd7c9; border-radius:3px; min-height:28px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
        ''')
        box = QVBoxLayout(self)
        box.setContentsMargins(24, 22, 24, 18)
        box.setSpacing(14)
        header = QHBoxLayout()
        title = QLabel('显示来源')
        title.setStyleSheet('font-size:20px;font-weight:600;')
        header.addWidget(title)
        header.addStretch()
        self.refresh_button = QPushButton('一键同步 Magpie')
        self.refresh_button.setAccessibleName('自动检测本机 Magpie 并同步额度来源')
        self.refresh_button.clicked.connect(station.sync_magpie)
        header.addWidget(self.refresh_button)
        box.addLayout(header)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        box.addWidget(self.scroll, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setStyleSheet('color:#687265;font-size:11px;')
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        box.addWidget(self.status)
        self.connection_details = QLabel()
        self.connection_details.setTextFormat(Qt.TextFormat.PlainText)
        self.connection_details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.connection_details.setWordWrap(True)
        self.connection_details.setStyleSheet('background:#f0f3ee;border-radius:8px;padding:12px;color:#687265;font-size:11px;')
        self.connection_details.hide()
        box.addWidget(self.connection_details)
        footer = QHBoxLayout()
        self.count = QLabel()
        self.count.setStyleSheet('color:#687265;font-size:12px;')
        footer.addWidget(self.count)
        self.details_button = QPushButton('同步详情')
        self.details_button.setCheckable(True)
        self.details_button.setStyleSheet('background:transparent;color:#687265;padding:8px 10px;font-size:11px;')
        self.details_button.toggled.connect(self.connection_details.setVisible)
        footer.addWidget(self.details_button)
        footer.addStretch()
        done = QPushButton('完成')
        done.setStyleSheet('background:#458068;color:white;padding:8px 22px;')
        done.clicked.connect(self.accept)
        footer.addWidget(done)
        box.addLayout(footer)
        self.checkboxes = {}
        self.signature = None
        self.sync()
        self.refresh_button.setFocus()

    def sync(self):
        station = self.station
        signature = [(key, item.get('name'), item.get('account'), item.get('plan'), item.get('available', True), station.errors.get(key))
                     for key, item in station.sources.items()]
        if signature != self.signature:
            scroll_at = self.scroll.verticalScrollBar().value()
            focused = next((key for key, checkbox in self.checkboxes.items() if checkbox.hasFocus()), None)
            self.signature = signature
            self.checkboxes = {}
            content = QWidget()
            content.setObjectName('sourceList')
            rows = QVBoxLayout(content)
            rows.setContentsMargins(0, 0, 10, 0)
            rows.setSpacing(0)
            for origin in ('本机直连', 'Magpie'):
                heading = QLabel(origin)
                heading.setStyleSheet('color:#687265;font-size:12px;padding:14px 0 9px;')
                rows.addWidget(heading)
                entries = [(key, meta) for key, meta in station.sources.items() if meta['origin'] == origin]
                for key, meta in entries:
                    frame = QFrame()
                    layout = QVBoxLayout(frame)
                    layout.setContentsMargins(0, 8, 0, 10)
                    layout.setSpacing(4)
                    checkbox = QCheckBox(meta['name'])
                    checkbox.setChecked(key in station.visible_sources)
                    account = meta.get('account', '')
                    checkbox.setAccessibleName('显示 ' + meta['name'] + (' · ' + account if account else '') + ' · ' + origin)
                    checkbox.toggled.connect(lambda checked, source=key: self.toggle(source, checked))
                    layout.addWidget(checkbox)
                    caption = ' · '.join(filter(None, (account, meta.get('plan'))))
                    if key in station.errors:
                        status = '暂未连接' if not meta.get('available', True) else '额度暂不可用'
                        caption = (caption + ' · ' if caption else '') + status
                        checkbox.setToolTip(station.errors[key])
                    if caption:
                        subtitle = QLabel(caption)
                        subtitle.setTextFormat(Qt.TextFormat.PlainText)
                        subtitle.setWordWrap(True)
                        subtitle.setStyleSheet('color:#687265;font-size:11px;padding-left:30px;')
                        layout.addWidget(subtitle)
                    rows.addWidget(frame)
                    self.checkboxes[key] = checkbox
                if origin == 'Magpie' and not entries:
                    empty = QLabel('暂无来源')
                    empty.setStyleSheet('color:#899185;font-size:12px;padding:8px 0;')
                    rows.addWidget(empty)
            rows.addStretch()
            self.scroll.setWidget(content)
            self.scroll.verticalScrollBar().setValue(scroll_at)
            if focused in self.checkboxes:
                self.checkboxes[focused].setFocus()
        for key, checkbox in self.checkboxes.items():
            checkbox.blockSignals(True)
            checkbox.setChecked(key in station.visible_sources)
            checkbox.blockSignals(False)
        self.count.setText(f'已选 {len(station.visible_sources)} 项')
        self.refresh_button.setEnabled(not station.magpie_busy and not station.offline)
        self.refresh_button.setText(('同步中…' if station.magpie_syncing else '刷新中…') if station.magpie_busy else '一键同步 Magpie')
        progress = '正在检测本机 Magpie 并同步额度…' if station.magpie_syncing else ''
        self.status.setText(station.selection_error or station.magpie_error or progress or station.magpie_sync_message)
        self.status.setVisible(bool(self.status.text()))
        connection = station.magpie_connection
        lines = ['程序路径：' + (connection.get('executable') or '尚未检测到')]
        if connection.get('version'):
            lines.append('版本：' + str(connection['version']))
        if connection.get('transport'):
            transport = f'本机网关 · 127.0.0.1:{connection.get("port", 3425)}' if connection['transport'] == 'gateway' else 'Magpie 命令行'
            lines.append('连接方式：' + transport)
        synced_at = connection.get('synced_at')
        if isinstance(synced_at, (int, float)):
            try:
                lines.append('上次同步：' + time.strftime('%m-%d %H:%M:%S', time.localtime(synced_at)))
            except (ValueError, OSError, OverflowError):
                pass
        self.connection_details.setText('\n'.join(lines))

    def toggle(self, key, checked):
        self.station.set_source_visible(key, checked)
        self.sync()
