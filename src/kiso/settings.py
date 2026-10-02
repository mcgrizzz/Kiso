"""A settings page: one HTML page in an AnkiWebView dialog, talking to Python over pycmd.

The page is Kiso's shell (web/shell.*: sidebar, footer with Save and Cancel,
unsaved-change tracking, per-page Revert and Restore defaults, asking before
closing with unsaved edits, error messages that jump to their field) plus the
add-on's own pages, registered with Kiso.setup() in its script.

The bridge works on plain dicts and takes its Qt side effects as callables, so
it can be tested headless; the dialog keeps its aqt imports local.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Tuple

WEB = Path(__file__).resolve().parent / "web"


def page_html(css: Iterable[str] = (), js: Iterable[str] = ()) -> str:
    """The whole page, inlined: Kiso's shell, then the add-on's own CSS and scripts
    (as text). Nothing is served, so no web exports are needed."""
    def read(name):
        return (WEB / name).read_text(encoding="utf-8")
    return (read("shell.html")
            .replace("/*STYLE*/", read("shell.css") + "".join(css))
            .replace("/*SCRIPT*/", read("shell.js") + "".join(js)))


class Bridge:
    """Answers the page's call(op, arg) by running op_<op>(arg). Messages carry
    `prefix` so the bridge ignores Anki's own (and other add-ons') pycmd traffic.

    The shell itself uses op_state (returns at least {"cfg": ..., "defaults": ...}),
    op_save (returns {"cfg": saved} or {"errors": [{message, page, field}]}),
    op_dirty and op_close; the add-on adds the rest."""

    prefix = "kiso:"

    def __init__(self, *, close: Optional[Callable[[], None]] = None):
        self.close = close   # make_dialog fills it in when left out
        self.dirty = False

    def handle(self, cmd: str) -> Any:
        if not cmd.startswith(self.prefix):
            return None
        try:
            msg = json.loads(cmd[len(self.prefix):])
            return getattr(self, "op_" + msg["op"])(msg.get("arg"))
        except Exception as exc:
            logging.getLogger(type(self).__module__).exception("Settings request failed")
            return {"error": str(exc)}

    def op_dirty(self, value) -> None:
        self.dirty = bool(value)

    def op_close(self, _arg) -> None:
        self.dirty = False
        if self.close:
            self.close()


def make_dialog(mw: Any, *, title: str, html: str, bridge: Callable[[Any, Any], Bridge], geom_key: str,
                size: Tuple[int, int] = (1100, 780), on_finished: Optional[Callable[[], None]] = None) -> Any:
    """The settings dialog, not yet shown. `bridge(dialog, webview)` builds the bridge,
    for side effects that need either. Closing with X or Esc while there are
    unsaved edits asks the page first; the bridge's close() closes for real."""
    from aqt.qt import QDialog, QTimer, QVBoxLayout
    from aqt.utils import disable_help_button, restoreGeom, saveGeom
    from aqt.webview import AnkiWebView

    class SettingsDialog(QDialog):
        def reject(self):   # X / Esc
            if self.kiso_bridge.dirty:
                self.kiso_web.eval("askClose()")
            else:
                super().reject()

    dlg = SettingsDialog(mw)
    dlg.setWindowTitle(title)
    disable_help_button(dlg)
    layout = QVBoxLayout(dlg)
    layout.setContentsMargins(0, 0, 0, 0)
    web = AnkiWebView(parent=dlg, title=title)
    layout.addWidget(web)
    dlg.kiso_web = web
    dlg.kiso_bridge = bridge(dlg, web)
    if dlg.kiso_bridge.close is None:
        # Deferred so the bridge's reply reaches the page before the page goes.
        dlg.kiso_bridge.close = lambda: QTimer.singleShot(0, dlg.accept)
    web.set_bridge_command(dlg.kiso_bridge.handle, dlg)
    web.stdHtml(html, context=dlg)

    def finished(_result):
        saveGeom(dlg, geom_key)
        if on_finished:
            on_finished()
        web.cleanup()

    dlg.finished.connect(finished)
    dlg.resize(*size)
    restoreGeom(dlg, geom_key)
    return dlg
