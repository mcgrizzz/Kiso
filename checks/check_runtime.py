"""Real-Anki check of Kiso's runtime helpers: debounced timers, waiting for a page,
and rebuilding the main window."""

# isort: off
# kiso_dev.harness sets Qt up for offscreen use before aqt loads, so it comes first.
from kiso_dev.harness import pump, run, until

import logging
import time

import aqt
from aqt import gui_hooks
# isort: on


def check(app, shots, base):
    from kisocheck.fixture._kiso import hooks, ui

    mw = aqt.mw
    subs = hooks.Subscriptions(logging.getLogger("kisocheck"))

    calls = []
    later = subs.debounce(mw, lambda: calls.append(time.monotonic()), "Check debounce")
    for _ in range(5):
        later.restart(0.1)
        pump(app, 0.03)
    assert calls == [] and later.pending
    until(app, lambda: calls, 2)
    pump(app, 0.2)
    assert len(calls) == 1 and not later.pending
    later.restart(0.1)
    subs.remove_all()
    pump(app, 0.3)
    assert len(calls) == 1
    print("PASS: a debounced call runs once after the burst, and remove_all stops a pending one.")

    done, gave_up = [], []
    ui.when_ready(mw.web, "window.kisoFlag === 1", lambda: done.append(1), every_ms=20)
    pump(app, 0.2)
    assert done == []
    mw.web.eval("window.kisoFlag = 1")
    until(app, lambda: done, 5)
    ui.when_ready(mw.web, "false", lambda: done.append(2), timeout=0.2, on_timeout=lambda: gave_up.append(1))
    until(app, lambda: gave_up, 5)
    assert done == [1]
    print("PASS: when_ready waits for the page's condition, and gives up after its timeout.")

    loads = []

    def on_content(web_content, context):
        loads.append(type(context).__name__)
    gui_hooks.webview_will_set_content.append(on_content)
    try:
        ui.rebuild_main_window(mw)
        until(app, lambda: "DeckBrowser" in loads and "TopToolbar" in loads, 10, f"pages not rebuilt: {loads}")
    finally:
        gui_hooks.webview_will_set_content.remove(on_content)
    print("PASS: rebuild_main_window reloads the toolbar and the current screen.")


if __name__ == "__main__":
    run(check, __doc__)
