"""Real-Anki check of Kiso's runtime helpers: debounced timers, waiting for a page,
rebuilding the main window, and a reload that waits for a stop finishing later."""

# isort: off
# kiso_dev.harness sets Qt up for offscreen use before aqt loads, so it comes first.
from kiso_dev.harness import pump, run, until

import logging
import threading
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

    check_reload(app)


def check_reload(app):
    from kisocheck.fixture._kiso.addon import Addon

    mw = aqt.mw
    starts = []

    def start():
        starts.append(1)
        return len(starts)

    def late_stop(_feature):
        # Like a server whose last request needs the main thread to finish:
        # stopped only once Anki has run this.
        stopped = threading.Event()
        threading.Thread(target=lambda: mw.taskman.run_on_main(stopped.set)).start()
        return stopped.is_set

    addon = Addon("kisocheck", inner="fixture", start=start, stop=late_stop)
    addon.start()
    results = []
    message = addon.reload(then=results.append)
    assert message.startswith("reloading once"), message
    assert addon.reload().startswith("a reload is already waiting")
    assert len(starts) == 1   # the old feature is still stopping
    until(app, lambda: results, 5, "the reload never finished")
    assert results[0].startswith("reloaded") and len(starts) == 2, (results, starts)
    print("PASS: a reload waits for a stop that needs the main thread, without blocking it.")

    never = Addon("kisocheck", inner="fixture", start=start, stop=lambda _f: lambda: False)
    never.stop_timeout = 0.3
    never.start()
    results = []
    never.reload(then=results.append)
    until(app, lambda: results, 5, "the reload never gave up")
    assert "didn't stop" in results[0] and len(starts) == 3, (results, starts)
    print("PASS: a reload gives up when the old feature doesn't stop, and starts nothing.")

    now = Addon("kisocheck", inner="fixture", start=start)
    now.start()
    assert now.reload().startswith("reloaded") and len(starts) == 5
    print("PASS: a feature that stops at once reloads at once.")

    from kisocheck.fixture._kiso import ui

    hits, gave_up = [], []
    assert ui.wait_until(mw, lambda: True, lambda: hits.append("now")) is None and hits == ["now"]
    flag = threading.Event()
    threading.Thread(target=lambda: mw.taskman.run_on_main(flag.set)).start()
    ui.wait_until(mw, flag.is_set, lambda: hits.append("later"))
    ui.wait_until(mw, lambda: 1 / 0, lambda: hits.append("never"), timeout=0.2, on_timeout=lambda: gave_up.append(1))
    until(app, lambda: "later" in hits and gave_up, 5, "wait_until never answered")
    assert hits == ["now", "later"]
    print("PASS: wait_until answers at once, after main-thread work, or gives up (a raising check counts as not yet).")


if __name__ == "__main__":
    run(check, __doc__)
