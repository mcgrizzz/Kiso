"""Screenshots of an add-on's settings as Anki shows them, for reviewing the UI (dev only).

`kiso shots` leaves a DEV_SHOTS request in a synced add-on's folder; only dev copies
(with DEV_WATCH) look for it. The add-on's dev watch hands it to start(): the settings
open in a fresh dialog, and the page walks every page, scrolled from top to bottom,
running the add-on's own tour where it has one (shell.js, Kiso.shots; Kiso.setup's
`shots`). Each step is a grab of the dialog as Qt draws it: Anki's fonts, theme and
the user's own pictures. It runs at the dialog's saved size, then narrow (or at one size
asked for, and only one named tour: `kiso shots --tour NAME --size WxH`). Nothing is
saved, the dialog closes at its saved size, and a settings window already open is left
alone (the run refuses). The grabs land in kiso_shots/<id>/ beside the request, with
done.json listing them and any errors.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple

from . import settings, ui

OUT = "kiso_shots"   # not dev_shots: Windows names ignore case, and DEV_SHOTS is the request
NARROW = 800          # px: where layouts wrap
TIMEOUT = 300.0       # s for a whole run

# The run under way. PyQt holds a timer's bound method only weakly, so without this a run
# nothing else refers to is collected before its first step.
active: Optional["Run"] = None


def slug(text: Any, limit: int = 40) -> str:
    out = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")
    return out[:limit].rstrip("-") or "shot"


def start(mw: Any, open_settings: Optional[Callable[[], None]], request: str, base: Path, log: Any) -> "Run":
    """Begin a run for a request's text (JSON: {"id", "narrow"?, "tour"?, "size"?: [w, h]});
    returns at once."""
    from aqt.qt import QTimer

    try:
        req = json.loads(request or "{}")
    except ValueError:
        req = {}
    req = req if isinstance(req, dict) else {}
    global active
    size = req.get("size")
    run = active = Run(open_settings, base / OUT / slug(req.get("id") or time.strftime("%Y%m%d-%H%M%S")), log,
                       narrow=int(req.get("narrow", NARROW) or 0), tour=str(req["tour"]) if req.get("tour") else None,
                       size=(int(size[0]), int(size[1])) if isinstance(size, list) and len(size) == 2 else None)
    QTimer.singleShot(0, run.start)   # after the watch's tick: the settings may open modally
    return run


class Run:
    def __init__(self, open_settings: Optional[Callable[[], None]], out: Path, log: Any, *,
                 narrow: int = NARROW, timeout: float = TIMEOUT, tour: Optional[str] = None,
                 size: Optional[Tuple[int, int]] = None):
        self.open_settings, self.out, self.log = open_settings, out, log
        self.narrow, self.timeout = narrow, timeout
        self.tour, self.wanted = tour, size
        self.files: List[str] = []
        self.errors: List[str] = []
        self.dlg: Any = None
        self.size: Tuple[int, int] = (0, 0)
        self.sizes: List[Tuple[str, Optional[Tuple[int, int]]]] = []
        self.tag = ""
        self.count = 0
        self.done = False

    def start(self) -> None:
        from aqt.qt import QTimer

        self.out.mkdir(parents=True, exist_ok=True)
        if self.open_settings is None:
            return self.finish("this add-on has no settings page")
        if settings.open_dialogs:
            return self.finish("a settings window is open: close it first, so its edits are left as they are")
        # Queued before opening: a dialog run with exec() only returns once it's closed, and
        # these run inside its loop meanwhile.
        QTimer.singleShot(0, lambda: self.attach(40))
        QTimer.singleShot(int(self.timeout * 1000), lambda: self.finish(f"timed out after {self.timeout:g} s"))
        try:
            self.open_settings()
        except Exception as exc:
            self.finish(f"the settings didn't open: {exc}")

    def attach(self, tries: int) -> None:
        from aqt.qt import QTimer

        if self.done:
            return
        if not settings.open_dialogs:
            if tries > 0:
                QTimer.singleShot(50, lambda: self.attach(tries - 1))
            else:
                self.finish("no settings window opened")
            return
        self.dlg = settings.open_dialogs[-1]
        # In front: a covered window isn't drawn, so it would grab stale frames.
        self.dlg.raise_()
        self.dlg.activateWindow()
        self.size = (self.dlg.width(), self.dlg.height())
        self.sizes = self.plan(self.size)
        self.dlg.kiso_bridge.shooter = self
        ui.when_ready(self.dlg.kiso_web, "window.kisoReady === true", self.next_size,
                      still_wanted=lambda: not self.done, timeout=30,
                      on_timeout=lambda: self.finish("the settings page didn't load"))

    def plan(self, saved: Tuple[int, int]) -> List[Tuple[str, Optional[Tuple[int, int]]]]:
        """The sizes to go through: [(tag, size or None for as it is)]."""
        if self.wanted:
            return [(f"{self.wanted[0]}x{self.wanted[1]}", self.wanted)]
        sizes: List[Tuple[str, Optional[Tuple[int, int]]]] = [("saved", None)]
        if self.narrow and saved[0] > self.narrow:
            sizes.append((f"{self.narrow}px", (self.narrow, saved[1])))
        return sizes

    def next_size(self) -> None:
        from aqt.qt import QTimer

        if self.done:
            return
        if not self.sizes:
            return self.finish()
        self.tag, size = self.sizes.pop(0)
        if size:
            self.dlg.resize(*size)
        # Time for the page to lay itself out at the new size.
        QTimer.singleShot(500, lambda: None if self.done else self.dlg.kiso_web.eval(
            f"Kiso.shots.run({json.dumps(self.tour)})"))

    def shot(self, arg: dict) -> str:
        """Grab the dialog as it is now (the page has waited for it to settle)."""
        self.count += 1
        parts = [slug(self.tag), f"{self.count:03d}", slug(arg.get("page")), slug(arg.get("label") or "page")]
        if arg.get("part"):
            parts.append(f"{int(arg['part']):02d}")
        name = "-".join(parts) + ".png"
        if not self.dlg.grab().save(str(self.out / name)):
            self.errors.append(f"couldn't save {name}")
            return ""
        self.files.append(name)
        return name

    def size_done(self, arg: dict) -> None:
        from aqt.qt import QTimer

        self.errors.extend(f"{self.tag}: {e}" for e in arg.get("errors") or [])
        QTimer.singleShot(0, self.next_size)   # after the reply reaches the page

    def finish(self, error: Optional[str] = None) -> None:
        global active
        if self.done:
            return
        self.done = True
        if active is self:
            active = None
        if error:
            self.errors.append(error)
        if self.dlg is not None:
            try:
                self.dlg.kiso_bridge.shooter = None
                self.dlg.resize(*self.size)          # it remembers the size it closes at
                self.dlg.kiso_bridge.dirty = False   # nothing is saved, and closing doesn't ask
                self.dlg.reject()
            except RuntimeError:   # already gone
                pass
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / "done.json").write_text(json.dumps({"files": self.files, "errors": self.errors}, indent=1),
                                            encoding="utf-8")
        self.log.info("Screenshots: %d in %s%s", len(self.files), self.out,
                      f" ({len(self.errors)} errors)" if self.errors else "")
