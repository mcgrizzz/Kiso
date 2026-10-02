"""Hearing when the add-on is turned off or on in Tools -> Add-ons.

Anki unloads add-ons only when it restarts: toggleEnabled just writes the
add-on's meta.json, and no hook announces it. Wrapping toggleEnabled lets an
add-on react now (stop a server, hide what it draws) and undo that if it's
turned back on in the same session.
"""

from __future__ import annotations

from typing import Any, Callable


def watch_own_toggle(manager: Any, package: str, on_toggled: Callable[[bool], None]) -> bool:
    """Call on_toggled(enabled) after Anki turns `package` on or off.

    Anki's own toggleEnabled runs first and unchanged. Returns False when the
    method is missing (a future Anki), leaving today's behaviour."""
    original = getattr(manager, "toggleEnabled", None)
    if original is None:
        return False

    def toggle(module: str, enable: Any = None) -> None:
        original(module, enable)
        if module == package:
            on_toggled(bool(manager.addon_meta(module).enabled))

    manager.toggleEnabled = toggle
    return True
