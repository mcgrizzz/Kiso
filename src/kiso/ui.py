"""The main window and webviews: rebuilding pages, waiting for a page to be ready."""

from __future__ import annotations

import time
from typing import Any, Callable, Optional

MAIN_SCREENS = ("deckBrowser", "overview", "review")


def rebuild_main_window(mw: Any) -> None:
    """Load the toolbar, the current screen and its bottom bar afresh, so
    webview_will_set_content runs for them again: after a reload changed what an
    add-on puts into those pages."""
    mw.toolbar.draw()
    if mw.state in MAIN_SCREENS:
        mw.moveToState(mw.state)


def when_ready(web: Any, condition: str, then: Callable[[], None], *,
               still_wanted: Callable[[], bool] = lambda: True, timeout: float = 15.0,
               every_ms: int = 50, on_timeout: Optional[Callable[[], None]] = None) -> None:
    """Call then() once the JavaScript `condition` is true in a webview's page, asking
    every `every_ms` for up to `timeout` seconds, then on_timeout(). Main thread;
    returns at once, and the callbacks run on the main thread.

    It stops quietly once still_wanted() is false (the window closed, a newer request
    took over), or when the page is deleted while a question is pending."""
    from aqt.qt import QTimer

    deadline = time.monotonic() + timeout

    def answered(ready: Any) -> None:
        if not still_wanted():
            return
        if ready:
            then()
        elif time.monotonic() < deadline:
            QTimer.singleShot(every_ms, ask)
        elif on_timeout:
            on_timeout()

    def ask() -> None:
        if still_wanted():
            try:
                web.evalWithCallback(condition, answered)
            except RuntimeError:
                pass   # the Qt page was deleted

    ask()
