"""Anki's deprecation notices, recorded so tests and real-Anki checks can list them and fail on them.

Anki prints most deprecations through anki._legacy.print_deprecation_warning
instead of raising a warning, so pytest's filterwarnings never sees them.
KISO_STRICT_ANKI_NOTICES=1 turns a notice into a failure when the add-on's code made the deprecated
call. One raised inside Anki (its own older code calling a newer deprecation, as the legacy
importers do on some versions) is listed but doesn't fail: no add-on can change it.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Callable, List, Tuple

STRICT = os.environ.get("KISO_STRICT_ANKI_NOTICES") == "1"
notices: List[Tuple[str, str, bool]] = []   # (where, message, raised inside Anki)


def _inside_anki(file: str) -> bool:
    # __path__, not __file__: anki can be a namespace package, with no __init__.py.
    path = Path(file).resolve()
    return any(path.is_relative_to(Path(folder).resolve())
               for name in ("anki", "aqt") for folder in getattr(sys.modules.get(name), "__path__", []))


def failing() -> List[Tuple[str, str, bool]]:
    """The notices strict mode fails on: the deprecated call was the add-on's."""
    return [n for n in notices if not n[2]]


def describe(notice: Tuple[str, str, bool]) -> str:
    where, msg, inside = notice
    return f"{where}: {msg}" + (" (raised inside Anki)" if inside else "")


def install(where: Callable[[], str] = lambda: os.environ.get("PYTEST_CURRENT_TEST", "")) -> None:
    """Record every notice from now on. Safe to call again after more modules load."""
    import anki._legacy

    original = getattr(anki._legacy.print_deprecation_warning, "kiso_original",
                       anki._legacy.print_deprecation_warning)

    def record(msg, frame=1):
        # frame 1 is the deprecated function; `frame` more is whoever called it.
        caller = sys._getframe(frame + 1).f_code.co_filename
        notices.append((where(), msg, _inside_anki(caller)))
        return original(msg, frame + 1)

    record.kiso_original = original
    # Modules such as anki.decks import the function by name, so rebind it there too.
    for module in [anki._legacy, *list(sys.modules.values())]:
        current = getattr(module, "print_deprecation_warning", None)
        if current is original or getattr(current, "kiso_original", None) is original:
            module.print_deprecation_warning = record
