"""Watch WorkBuddy's active account marker with native filesystem notifications."""
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QObject, QTimer, Signal


class WorkBuddyAccountWatch(QObject):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.path = None
        self._stamp = None
        self._files = QFileSystemWatcher(self)
        self._files.fileChanged.connect(self._file_event)
        self._files.directoryChanged.connect(self._directory_event)
        self._settle = QTimer(self)
        self._settle.setSingleShot(True)
        self._settle.setInterval(150)
        self._settle.timeout.connect(self.changed.emit)

    def start(self, path: Path):
        self.path = path.absolute()
        self.rearm()

    def stop(self):
        self.path = self._stamp = None
        self._settle.stop()
        paths = self._files.files() + self._files.directories()
        if paths:
            self._files.removePaths(paths)

    def rearm(self):
        if self.path is None:
            return False
        try:
            info = self.path.stat()
            stamp = (info.st_dev, info.st_ino, info.st_mtime_ns, info.st_size)
        except OSError:
            stamp = None
        # Follow creation of storage/skeleton inside the WorkBuddy profile. If
        # WorkBuddy is not installed, the usual five-minute refresh can reattach.
        folder = next((p for p in self.path.parents[:3] if p.is_dir()), None)
        wanted = {folder.as_posix()} if folder else set()
        filename = self.path.as_posix()
        if stamp is not None:
            wanted.add(filename)
        watched = set(self._files.files() + self._files.directories())
        old = self._stamp
        if old and stamp and old[:2] != stamp[:2] and filename in watched:
            # Atomic replacement can leave a watch attached to the old file.
            self._files.removePath(filename)
            watched.remove(filename)
        if wanted - watched:
            self._files.addPaths(list(wanted - watched))
        if watched - wanted:
            self._files.removePaths(list(watched - wanted))
        self._stamp = stamp
        return stamp != old

    def _file_event(self, _path):
        if self.path is not None:
            self.rearm()
            self._settle.start()

    def _directory_event(self, _path):
        if self.rearm():
            self._settle.start()
