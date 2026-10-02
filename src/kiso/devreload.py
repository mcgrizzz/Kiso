"""Running new code without restarting Anki, for development.

`kiso sync` copies an add-on into Anki's add-ons folder and leaves a DEV_WATCH
file there. With that file present, DevWatch notices each sync and reloads the
add-on's inner package. Real installs never have the file.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable, Optional, Tuple

MARKER = "DEV_WATCH"
WATCHED = (".py", ".js", ".css", ".html", ".json")


def source_stamp(folder: Path) -> Tuple[int, float]:
    """(file count, newest mtime) across a package: a cheap change signal."""
    newest, count = 0.0, 0
    for path in folder.rglob("*"):
        if path.suffix in WATCHED:
            try:
                newest = max(newest, path.stat().st_mtime)
                count += 1
            except OSError:
                pass
    return count, newest


def purge(package: str) -> int:
    """Forget a package and its submodules, so the next import reads them from disk."""
    names = [n for n in list(sys.modules) if n == package or n.startswith(package + ".")]
    for name in names:
        del sys.modules[name]
    return len(names)


class DevWatch:
    """Polls a package folder and calls on_change() once it changes and then
    holds still for a tick (a sync rewrites the whole tree; reloading mid-copy
    would import half of it)."""

    def __init__(self, folder: Path, on_change: Callable[[], None]):
        self.folder = folder
        self.on_change = on_change
        self.stamp = source_stamp(folder)
        self.pending: Optional[Tuple[int, float]] = None
        self.timer: Any = None

    def start(self, parent: Any, every_ms: int = 1000) -> None:
        from aqt.qt import QTimer

        self.timer = QTimer(parent)
        self.timer.timeout.connect(self.tick)
        self.timer.start(every_ms)

    def tick(self) -> None:
        stamp = source_stamp(self.folder)
        if stamp == self.stamp:
            self.pending = None
            return
        if stamp != self.pending:
            self.pending = stamp
            return
        self.stamp, self.pending = stamp, None
        self.on_change()
