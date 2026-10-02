"""An add-on's wiring with Anki, in one object.

    addon = Addon(__name__, inner="keshiki", menu="Keshiki Backgrounds...",
                  start=make_feature, stop=lambda feature: feature.teardown(),
                  settings=open_settings, on_config=reload_config)
    addon.install()

- `start()` builds the add-on's running part (its "feature"), and `stop(feature)`
  takes it down; reload() runs stop, purges the inner package, runs start again.
- `settings` opens the settings page from the Tools menu and the add-on's Config
  button. If it raises, Anki's raw JSON editor opens instead.
- `on_config(addon)` runs at profile open and when the JSON editor saves.
- `on_toggle(addon, enabled)` runs when the add-on is turned off or on in Tools > Add-ons.

Every callback is guarded: a failure is logged to the add-on's log file and the
rest keeps working. Callbacks should import the add-on's own modules inside
the function, so a reload's purge brings in the new code.
"""

from __future__ import annotations

import logging
import traceback
from pathlib import Path
from typing import Any, Callable, Optional

from . import devreload
from .hooks import guard
from .logs import attach_to_anki
from .toggle import watch_own_toggle


class Addon:
    def __init__(self, module: str, *, inner: str, start: Callable[[], Any],
                 stop: Callable[[Any], None] = lambda feature: None,
                 settings: Optional[Callable[[], None]] = None, menu: Optional[str] = None,
                 on_config: Optional[Callable[["Addon"], None]] = None,
                 on_toggle: Optional[Callable[["Addon", bool], None]] = None,
                 after_reload: Optional[Callable[["Addon"], None]] = None,
                 web_exports: Optional[str] = None, log_also: tuple = ()):
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

    # -- set up ----------------------------------------------------------

    def install(self) -> None:
        """Wire everything up. Call at import time: add-ons load after the main
        window exists and before the first page renders."""
        from aqt import gui_hooks

        mw = self.mw
        self.start()
        if self._web_exports:
            mw.addonManager.setWebExports(self.module, self._web_exports)
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

    def start(self) -> None:
        try:
            self.feature = self._start()
        except Exception:
            self.feature = None
            self.log.exception("%s failed to start", self.module)

    def stop(self) -> None:
        if self.feature is not None:
            try:
                self._stop(self.feature)
            except Exception:
                self.log.exception("%s failed to stop", self.module)
        self.feature = None

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
        self._config()
        if self.watch is None and (self.base / devreload.MARKER).exists():
            self.watch = devreload.DevWatch(self.base / self.inner, self._reload_from_watch)
            self.watch.start(self.mw)
            self.log.info("Dev watch active")

    # -- reload ------------------------------------------------------------

    def reload(self) -> str:
        """Run the code now on disk without restarting Anki. Only the inner package
        is purged (Kiso's bundled copy with it); the root __init__ needs a restart."""
        self.stop()
        purged = devreload.purge(f"{self.module}.{self.inner}")
        try:
            self.start()
            self._config()
            if self._after_reload:
                self._after_reload(self)
        except Exception:
            return "reload failed:\n" + traceback.format_exc()
        return f"reloaded {purged} modules"

    def _reload_from_watch(self) -> None:
        message = self.reload()
        self.log.info("Dev watch: %s", message)
        from aqt.utils import tooltip

        tooltip(f"{self.module}: {message}", period=3000)
