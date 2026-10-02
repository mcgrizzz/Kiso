"""Hook callbacks that can't take an add-on down, and come off cleanly on reload."""

from __future__ import annotations

import logging
from typing import Any, Callable, List, Tuple


def guard(fn: Callable, log: logging.Logger, what: str = "") -> Callable:
    """`fn`, logging instead of raising. Anki drops a hook subscriber that raises,
    so one bad moment would otherwise switch a feature off for the session."""
    def run(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception:
            log.exception("%s failed", what or getattr(fn, "__name__", "callback"))
    run.__wrapped__ = fn
    return run


class Subscriptions:
    """Hooks and timers an add-on feature registers, all removed at once by remove_all()."""

    def __init__(self, log: logging.Logger):
        self.log = log
        self._hooks: List[Tuple[Any, Callable]] = []
        self._timers: List[Any] = []

    def add(self, hook: Any, fn: Callable, what: str = "") -> Callable:
        """Append guarded `fn` to a gui_hooks hook. A hook missing from this Anki is skipped."""
        if hook is None:
            return fn
        guarded = guard(fn, self.log, what)
        hook.append(guarded)
        self._hooks.append((hook, guarded))
        return guarded

    def timer(self, parent: Any, ms: int, fn: Callable, what: str = "") -> Any:
        """A repeating QTimer calling guarded `fn` every `ms`, started now."""
        from aqt.qt import QTimer

        timer = QTimer(parent)
        timer.timeout.connect(guard(fn, self.log, what))
        timer.start(ms)
        self._timers.append(timer)
        return timer

    def debounce(self, parent: Any, fn: Callable, what: str = "") -> "Debounce":
        """A single-shot QTimer calling guarded `fn`, not started: see Debounce."""
        from aqt.qt import QTimer

        timer = QTimer(parent)
        timer.setSingleShot(True)
        timer.timeout.connect(guard(fn, self.log, what))
        self._timers.append(timer)
        return Debounce(timer)

    def remove_all(self) -> None:
        for hook, fn in self._hooks:
            try:
                hook.remove(fn)
            except ValueError:
                pass
        self._hooks = []
        for timer in self._timers:
            timer.stop()
            timer.deleteLater()
        self._timers = []


class Debounce:
    """One call after a burst goes quiet: each restart() pushes the call back.

        scan = subs.debounce(mw, flush, "Change scan")
        scan.restart(0.5)            # on every change; flush runs 0.5 s after the last
        if not scan.pending:         # or: once per event-loop turn, however many events
            scan.restart(0)
    """

    def __init__(self, timer: Any):
        self.timer = timer

    def restart(self, seconds: float) -> None:
        self.timer.start(max(0, round(seconds * 1000)))

    def cancel(self) -> None:
        self.timer.stop()

    @property
    def pending(self) -> bool:
        return self.timer.isActive()
