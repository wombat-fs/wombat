"""AutoBackupManager — periodic project snapshot and crash recovery.

Usage
-----
    mgr = AutoBackupManager()
    mgr.start(lambda: self._project)   # pass a callable that returns the current Project
    # on close:
    mgr.stop()
    mgr.clear()   # delete all backups after clean exit

Recovery check at startup
--------------------------
    backups = mgr.find_backups()
    # present the most recent one to the user; load it via Project.load(path)
    # after restoring (or declining), call mgr.clear()
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QStandardPaths, QTimer

if TYPE_CHECKING:
    from wombat.app.project import Project

log = logging.getLogger(__name__)

_BACKUP_SUFFIX = ".wombat"
_PREFIX = "backup_"


def _backup_dir() -> Path:
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    return Path(base) / "backups"


class AutoBackupManager:
    """Saves a project copy periodically without touching the project's own path.

    The backup directory is separate from the project directory.  Each backup is
    named ``backup_<YYYYMMDD_HHMMSS>.wombat`` and the most recent `max_backups`
    are kept; older ones are pruned automatically.
    """

    def __init__(self, interval_minutes: int = 5, max_backups: int = 5) -> None:
        self._interval_ms = interval_minutes * 60 * 1000
        self._max_backups = max_backups
        self._get_project: Callable[[], Project | None] = lambda: None
        self._timer = QTimer()
        self._timer.timeout.connect(self._save_backup)

    # ----------------------------------------------------------------- lifecycle

    def start(self, get_project: Callable[[], Project | None]) -> None:
        """Start the backup timer.  ``get_project`` is called each tick."""
        self._get_project = get_project
        _backup_dir().mkdir(parents=True, exist_ok=True)
        self._timer.start(self._interval_ms)
        log.debug("Auto-backup started (interval %d ms)", self._interval_ms)

    def stop(self) -> None:
        self._timer.stop()

    def clear(self) -> None:
        """Delete all backup files (call after a clean close or successful recovery)."""
        for p in self.find_backups():
            try:
                p.unlink()
            except OSError:
                pass

    # ----------------------------------------------------------------- discovery

    def find_backups(self) -> list[Path]:
        """Return backup files sorted newest first."""
        d = _backup_dir()
        if not d.exists():
            return []
        files = sorted(
            d.glob(f"{_PREFIX}*{_BACKUP_SUFFIX}"),
            reverse=True,
        )
        return files

    # ----------------------------------------------------------------- save

    def _save_backup(self) -> None:
        project = self._get_project()
        if project is None:
            return
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = _backup_dir() / f"{_PREFIX}{ts}{_BACKUP_SUFFIX}"
        try:
            _save_project_copy(project, path)
        except OSError as exc:
            log.warning("Auto-backup failed: %s", exc)
            return
        log.debug("Auto-backup saved: %s", path)
        self._prune()

    def _prune(self) -> None:
        backups = self.find_backups()
        for old in backups[self._max_backups:]:
            try:
                old.unlink()
            except OSError:
                pass


def _save_project_copy(project: Project, path: Path) -> None:
    """Write a project snapshot to *path* without mutating project.path."""
    base_dir = path.parent
    data = project._to_dict(base_dir)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
