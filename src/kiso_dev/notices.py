"""Anki's deprecation notices, recorded so tests and real-Anki checks can list them and fail on them.

Anki prints most deprecations through anki._legacy.print_deprecation_warning
instead of raising a warning, so pytest's filterwarnings never sees them.
KISO_STRICT_ANKI_NOTICES=1 turns any notice into a failure.
"""

from __future__ import annotations

import os
import sys
from typing import Callable, List, Tuple

STRICT = os.environ.get("KISO_STRICT_ANKI_NOTICES") == "1"
notices: List[Tuple[str, str]] = []   # (where, message)


def install(where: Callable[[], str] = lambda: os.environ.get("PYTEST_CURRENT_TEST", "")) -> None:
    """Record every notice from now on. Safe to call again after more modules load."""
    import anki._legacy

    original = getattr(anki._legacy.print_deprecation_warning, "kiso_original",
                       anki._legacy.print_deprecation_warning)

    def record(msg, frame=1):
        notices.append((where(), msg))
        return original(msg, frame + 1)

    record.kiso_original = original
    # Modules such as anki.decks import the function by name, so rebind it there too.
    for module in [anki._legacy, *list(sys.modules.values())]:
        current = getattr(module, "print_deprecation_warning", None)
        if current is original or getattr(current, "kiso_original", None) is original:
            module.print_deprecation_warning = record
