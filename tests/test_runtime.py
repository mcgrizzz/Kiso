import json
import logging
import sys
from types import SimpleNamespace

import aqt.qt

from kiso import config, devreload, hooks, settings, shots, toggle, ui


class FakeHook(list):
    """gui_hooks hooks are lists with append/remove."""


def test_a_guarded_callback_logs_instead_of_raising(caplog):
    def boom():
        raise RuntimeError("bad moment")
    with caplog.at_level(logging.ERROR):
        assert hooks.guard(boom, logging.getLogger("t"), "Renderer")() is None
    assert "Renderer failed" in caplog.text and "bad moment" in caplog.text


def test_a_failing_filter_passes_its_value_on(caplog):
    hook = FakeHook()
    subs = hooks.Subscriptions(logging.getLogger("t"))

    def boom(handled, message, context):
        raise RuntimeError("bad message")
    subs.filter(hook, boom, "Page message")
    with caplog.at_level(logging.ERROR):
        assert hook[0]((False, None), "x", None) == (False, None)
    assert "Page message failed" in caplog.text
    subs.remove_all()
    assert hook == []


def test_subscriptions_come_off_together():
    a, b = FakeHook(), FakeHook()
    subs = hooks.Subscriptions(logging.getLogger("t"))
    subs.add(a, lambda: 1)
    subs.add(b, lambda: 2)
    subs.add(None, lambda: 3)   # a hook this Anki doesn't have
    assert len(a) == len(b) == 1
    subs.remove_all()
    assert a == [] and b == []


def test_migrate_runs_newer_steps_then_fills_defaults():
    defaults = {"light": {"tint": False, "strength": 70}, "images": {}, "config_version": 3}

    def v2(cfg):
        cfg["light"] = {"tint": cfg.pop("tint", False)}

    def v3(cfg):
        cfg["light"]["strength"] = cfg["light"].pop("percent", 70)
    old = {"tint": True, "images": {"a.png": {"x": 10}}, "config_version": 1}
    cfg, changed = config.migrate(old, defaults, 3, [(3, v3), (2, v2)], free_form=["images"])
    assert changed and cfg == {"light": {"tint": True, "strength": 70}, "images": {"a.png": {"x": 10}},
                               "config_version": 3}
    assert old["config_version"] == 1                      # the input is left alone
    assert config.migrate(cfg, defaults, 3, [(3, v3), (2, v2)]) == (cfg, False)
    fresh, _ = config.migrate({}, defaults, 3, [(2, v2)])  # a new config skips the steps
    assert fresh == defaults
    fresh["light"]["tint"] = True
    assert defaults["light"]["tint"] is False               # defaults are copied, never shared


def test_load_writes_back_only_when_migrating_changed_something():
    written = []
    manager = SimpleNamespace(getConfig=lambda pkg: {"config_version": 1},
                              writeConfig=lambda pkg, cfg: written.append(cfg))
    cfg = config.load(manager, "x", lambda c: config.migrate(c, {"a": 1, "config_version": 1}, 1))
    assert cfg == {"a": 1, "config_version": 1} and written == [cfg]
    manager.getConfig = lambda pkg: cfg
    config.load(manager, "x", lambda c: config.migrate(c, {"a": 1, "config_version": 1}, 1))
    assert len(written) == 1


def test_toggle_reports_after_anki_has_written_it():
    meta = {"keshiki": True}
    seen = []
    manager = SimpleNamespace(toggleEnabled=lambda module, enable=None: meta.__setitem__(module, not meta[module]),
                              addon_meta=lambda module: SimpleNamespace(enabled=meta[module]))
    assert toggle.watch_own_toggle(manager, "keshiki", seen.append)
    manager.toggleEnabled("keshiki")
    manager.toggleEnabled("other") if "other" in meta else None
    assert seen == [False]
    assert not toggle.watch_own_toggle(SimpleNamespace(), "keshiki", seen.append)


def test_bridge_dispatches_its_own_messages_only():
    class Page(settings.Bridge):
        prefix = "demo:"

        def op_echo(self, arg):
            return {"echo": arg}
    closed = []
    bridge = Page(close=lambda: closed.append(1))
    assert bridge.handle("domDone") is None
    assert bridge.handle("demo:" + json.dumps({"op": "echo", "arg": 5})) == {"echo": 5}
    assert "error" in bridge.handle("demo:" + json.dumps({"op": "nope"}))
    bridge.handle('demo:{"op": "dirty", "arg": true}')
    assert bridge.dirty
    bridge.handle('demo:{"op": "close"}')
    assert closed == [1] and not bridge.dirty


def test_page_html_inlines_the_shell_and_the_addons_parts():
    html = settings.page_html(css=[".mine{}"], js=["Kiso.setup({});"])
    assert "/*STYLE*/" not in html and "/*SCRIPT*/" not in html
    assert "--kiso-canvas" in html and ".mine{}" in html and "Kiso.setup({});" in html
    assert html.index("function call(") < html.index("Kiso.setup({});")


def test_purge_forgets_a_package_and_its_children():
    sys.modules["demo_pkg"] = SimpleNamespace()
    sys.modules["demo_pkg.child"] = SimpleNamespace()
    sys.modules["demo_pkg_other"] = SimpleNamespace()
    assert devreload.purge("demo_pkg") == 2
    assert "demo_pkg_other" in sys.modules
    del sys.modules["demo_pkg_other"]


def test_dev_watch_waits_for_a_quiet_tick(tmp_path):
    (tmp_path / "a.py").write_text("x = 1")
    fired = []
    watch = devreload.DevWatch(tmp_path, lambda: fired.append(1))
    watch.tick()
    assert fired == []
    (tmp_path / "b.py").write_text("y = 2")
    watch.tick()                 # changed: wait for it to hold still
    assert fired == []
    watch.tick()                 # unchanged since: reload
    assert fired == [1]


def test_dev_watch_hands_each_request_over_once(tmp_path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "a.py").write_text("x = 1")
    got = []
    watch = devreload.DevWatch(pkg, lambda: None, requests={devreload.SHOTS: got.append})
    watch.tick()
    assert got == []
    (tmp_path / devreload.SHOTS).write_text('{"id": "r1"}')
    watch.tick()
    watch.tick()
    assert got == ['{"id": "r1"}'] and not (tmp_path / devreload.SHOTS).exists()


def test_screenshot_names_are_plain():
    assert shots.slug("Day & time") == "day-time"
    assert shots.slug("Spirited Away Train · 3") == "spirited-away-train-3"
    assert shots.slug("") == shots.slug("景色") == "shot"
    assert len(shots.slug("x" * 80)) == 40


def test_a_run_goes_through_saved_then_narrow_or_one_size_asked_for(tmp_path):
    run = shots.Run(None, tmp_path, None, narrow=800)
    assert run.plan((1100, 780)) == [("saved", None), ("800px", (800, 780))]
    assert run.plan((700, 600)) == [("saved", None)]
    run = shots.Run(None, tmp_path, None, tour="readme", size=(960, 608))
    assert run.plan((1100, 780)) == [("960x608", (960, 608))] and run.tour == "readme"


def test_the_bridge_takes_screenshot_steps_only_during_a_run():
    bridge = settings.Bridge()
    assert "error" in bridge.handle('kiso:{"op": "kiso_shot", "arg": {}}')
    calls = []
    bridge.shooter = SimpleNamespace(shot=lambda arg: calls.append(("shot", arg)) or "a.png",
                                     size_done=lambda arg: calls.append(("done", arg)))
    assert bridge.handle('kiso:{"op": "kiso_shot", "arg": {"page": "p"}}') == "a.png"
    bridge.handle('kiso:{"op": "kiso_shots_done", "arg": {"errors": []}}')
    assert calls == [("shot", {"page": "p"}), ("done", {"errors": []})]


def test_when_ready_asks_until_the_page_says_yes(monkeypatch):
    monkeypatch.setattr(aqt.qt, "QTimer", SimpleNamespace(singleShot=lambda ms, fn: fn()))
    answers = iter([False, None, True])
    asked, done = [], []
    web = SimpleNamespace(evalWithCallback=lambda js, cb: (asked.append(js), cb(next(answers))))
    ui.when_ready(web, "typeof saveNow === 'function'", lambda: done.append(1))
    assert len(asked) == 3 and done == [1]

    gave_up, wanted = [], [True]

    def answer(js, cb):
        wanted[0] = False             # the window closed while asking
        cb(True)
    ui.when_ready(SimpleNamespace(evalWithCallback=answer), "1", lambda: done.append(2),
                  still_wanted=lambda: wanted[0])
    assert done == [1]

    ui.when_ready(SimpleNamespace(evalWithCallback=lambda js, cb: cb(False)), "0", lambda: done.append(3),
                  timeout=0, on_timeout=lambda: gave_up.append(1))
    assert gave_up == [1] and done == [1]


def test_rebuild_reloads_the_toolbar_and_a_main_screen_only():
    calls = []
    mw = SimpleNamespace(state="overview", toolbar=SimpleNamespace(draw=lambda: calls.append("toolbar")),
                         moveToState=lambda state: calls.append(state))
    ui.rebuild_main_window(mw)
    mw.state = "profileManager"
    ui.rebuild_main_window(mw)
    assert calls == ["toolbar", "overview", "toolbar"]
