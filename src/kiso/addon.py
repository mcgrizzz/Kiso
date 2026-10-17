"""An add-on's wiring with Anki, in one object.

    addon = Addon(__name__, inner="keshiki", menu="Keshiki Backgrounds...",
                  start=make_feature, stop=lambda feature: feature.teardown(),
                  settings=open_settings, on_config=reload_config)
    addon.install()

- `start()` builds the add-on's running part (its "feature"), and `stop(feature)`
  takes it down; reload() runs stop, purges the inner package, runs start again.
  A feature whose stop finishes later (a server thread that must let its last
  requests through, which may need the main thread) returns a check from stop,
  `done() -> bool`: the reload then waits for it without blocking Anki.
- `settings` opens the settings page from the Tools menu and the add-on's Config
  button. If it raises, Anki's raw JSON editor opens instead.
- `on_config(addon)` runs at profile open and when the JSON editor saves.
- `on_toggle(addon, enabled)` runs when the add-on is turned off or on in Tools > Add-ons.
- `web_exports` is the pattern of files Anki's media server may serve from the add-on. Pass a
  function that reads it from the inner package, and a reload registers the new code's pattern.
- In a dev copy (`kiso sync`), the dev watch reloads on each sync and answers `kiso shots`
  (screenshots of the settings, as Anki shows them: shots.py).
- A start that crashed Anki outright (native code: nothing to catch) isn't run again with the
  same code: the next launch leaves the add-on off, offers to start it, and logs the crash's
  Python stack from Anki's crash.log (crashguard.py).

Every callback is guarded: a failure is logged to the add-on's log file and the
rest keeps working. Callbacks should import the add-on's own modules inside
the function, so a reload's purge brings in the new code.
"""

from __future__ import annotations

import atexit
import logging
import traceback
from pathlib import Path
from typing import Any, Callable, Optional, Union

from . import crashguard, devreload
from .hooks import guard
from .logs import attach_to_anki
from .toggle import watch_own_toggle
from .ui import wait_until


class Addon:
    def __init__(self, module: str, *, inner: str, start: Callable[[], Any],
                 stop: Callable[[Any], None] = lambda feature: None,
                 settings: Optional[Callable[[], None]] = None, menu: Optional[str] = None,
                 on_config: Optional[Callable[["Addon"], None]] = None,
                 on_toggle: Optional[Callable[["Addon", bool], None]] = None,
                 after_reload: Optional[Callable[["Addon"], None]] = None,
                 web_exports: Union[str, Callable[[], str], None] = None, log_also: tuple = ()):
        from aqt import mw

        self.mw = mw
        self.module = module
        self.inner = inner
        self.base = Path(__import__(module).__file__).resolve().parent
        self.log = logging.getLogger(module)
        self._start, self._stop = start, stop
        self._settings, self._menu = settings, menu
        self._on_config, self._on_toggle, self._after_reload = on_config, on_toggle, after_reload
        self._web_exports, self._log_also = web_exports, log_also
        self.feature: Any = None
        self.watch: Optional[devreload.DevWatch] = None
        self.stop_timeout = 30.0   # seconds a reload waits for a stop that finishes later
        self._waiting: Any = None  # the timer of a reload waiting for the old feature to stop
        self.guard = crashguard.Guard(self.base)
        self.held_back = False   # not started: this code crashed Anki as it started last time
        atexit.register(self.guard.settled)   # Anki closing normally: no crash to remember

    # -- set up ----------------------------------------------------------

    def install(self) -> None:
        """Wire everything up. Call at import time: add-ons load after the main
        window exists and before the first page renders."""
        from aqt import gui_hooks

        mw = self.mw
        self.start()
        self._export_web()
        if self._settings:
            # Registered at import time so it works even if the feature failed to start.
            mw.addonManager.setConfigAction(self.module, self.open_settings)
            if self._menu:
                from aqt.qt import QAction

                action = QAction(self._menu, mw)
                action.triggered.connect(self.open_settings)
                mw.form.menuTools.addAction(action)
        mw.addonManager.setConfigUpdatedAction(self.module, guard(lambda _cfg: self._config(), self.log, "Config update"))
        gui_hooks.profile_did_open.append(guard(self._profile_open, self.log, "Profile open"))
        if self._on_toggle:
            watch_own_toggle(mw.addonManager, self.module,
                             guard(lambda enabled: self._on_toggle(self, enabled), self.log, "Add-on switch"))

    def _export_web(self) -> None:
        pattern = self._web_exports() if callable(self._web_exports) else self._web_exports
        if pattern:
            self.mw.addonManager.setWebExports(self.module, pattern)

    def start(self, anyway: bool = False) -> None:
        code = crashguard.fingerprint([self.base / self.inner], [self.base / "__init__.py"])
        if not anyway and self.guard.crashed_before(code):
            self.feature, self.held_back = None, True
            # Logged once the profile is open: the log file isn't attached yet at launch.
            self._held_note = (f"{self.module} wasn't started: Anki closed unexpectedly while this same code was "
                               "starting. " + crashguard.last_crash(self.mw.pm.base))
            return
        self.held_back = False
        token = self.guard.starting(code)
        try:
            self.feature = self._start()
        except Exception:
            self.feature = None
            self.log.exception("%s failed to start", self.module)
        from aqt.qt import QTimer

        QTimer.singleShot(crashguard.SETTLE_MS, lambda: self.guard.settled(token))

    def _offer_start(self) -> None:
        """Held back at launch: say so, and start it now if the user asks."""
        from aqt.utils import askUser

        name = self.mw.addonManager.addonName(self.module)
        if askUser(f"{name} closed Anki unexpectedly the last time it started, so it hasn't been started this "
                   "time. It will start as usual once it's updated.\n\nStart it now anyway?",
                   parent=self.mw, title=name, defaultno=True):
            self.start(anyway=True)
            self._export_web()
            self._config()
            if self._after_reload:
                self._after_reload(self)


    def stop(self) -> Optional[Callable[[], bool]]:
        """Take the feature down. Returns its check when its stop finishes later."""
        done = None
        if self.feature is not None:
            try:
                done = self._stop(self.feature)
            except Exception:
                self.log.exception("%s failed to stop", self.module)
        self.feature = None
        return done if callable(done) else None

    def open_settings(self, *_args) -> Optional[bool]:
        try:
            self._settings()
        except Exception:
            self.log.exception("Settings failed to open")
            return False   # literal False: Anki falls back to its JSON editor
        return None

    def _config(self) -> None:
        if self._on_config:
            self._on_config(self)

    def _profile_open(self) -> None:
        try:
            attach_to_anki(self.module, self.log, also=self._log_also)
        except Exception:
            self.log.exception("Couldn't attach Anki's add-on log")
        if self.held_back and not getattr(self, "_offered", False):
            self._offered = True
            self.log.error("%s", self._held_note)
            from aqt.qt import QTimer

            QTimer.singleShot(0, guard(self._offer_start, self.log, "Offer to start"))   # once the window is up
        self._config()
        if self.watch is None and (self.base / devreload.MARKER).exists():
            self.watch = devreload.DevWatch(self.base / self.inner, self._reload_from_watch,
                                            requests={devreload.SHOTS: guard(self._shots, self.log, "Screenshots")})
            self.watch.start(self.mw)
            self.log.info("Dev watch active")

    def _shots(self, request: str) -> None:
        # The module as it is now: a reload since this watch started may have changed it.
        import importlib

        shots = importlib.import_module(__package__ + ".shots")
        shots.start(self.mw, self._settings, request, self.base, self.log)

    # -- reload ------------------------------------------------------------

    def reload(self, then: Optional[Callable[[str], None]] = None) -> str:
        """Run the code now on disk without restarting Anki. Only the inner package
        is purged (Kiso's bundled copy with it); the root __init__ needs a restart.

        Returns the result. When the old feature's stop finishes later, the reload
        waits for it on a timer (Anki stays responsive, so the work it waits on can
        finish), returns at once saying so, and hands the result to `then` (else the
        log) when it ends."""
        if self._waiting is not None:
            return "a reload is already waiting for the old code to stop"
        done = self.stop()
        if done is None or done():
            message = self._load()
            if then:
                then(message)
            return message
        report = then or (lambda message: self.log.info("Reload: %s", message))

        def finished(message: str) -> None:
            self._waiting = None
            report(message)

        self._waiting = wait_until(
            self.mw, guard(done, self.log, "Stop check"),   # a failing check counts as not stopped yet
            guard(lambda: finished(self._load()), self.log, "Reload"), timeout=self.stop_timeout,
            on_timeout=guard(lambda: finished(f"reload failed: the old code didn't stop within "
                                              f"{self.stop_timeout:g} s; restart Anki"), self.log, "Reload"))
        return "reloading once the old code has stopped"

    def _load(self) -> str:
        purged = devreload.purge(f"{self.module}.{self.inner}")
        try:
            self.start()
            self._export_web()   # the new code may serve different files
            self._config()
            if self._after_reload:
                self._after_reload(self)
        except Exception:
            return "reload failed:\n" + traceback.format_exc()
        if self.held_back:
            return (f"reloaded {purged} modules, but didn't start them: this same code closed Anki unexpectedly "
                    "as it started last time (change it, or start it anyway from the notice at launch)")
        return f"reloaded {purged} modules"

    def _reload_from_watch(self) -> None:
        self.reload(then=self._report)

    def _report(self, message: str) -> None:
        self.log.info("Dev watch: %s", message)
        from aqt.utils import tooltip

        tooltip(f"{self.module}: {message}", period=3000)
