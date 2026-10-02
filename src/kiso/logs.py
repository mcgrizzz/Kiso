"""Logging to Anki's per-add-on log file.

Anki gives a file (logs/addons/<folder>/<folder>.log, rotated daily) only to
the logger named "addon.<folder>". An add-on's own loggers borrow its handlers
instead of living under that name, which would repeat every line.
"""

from __future__ import annotations

import logging
from typing import Iterable


def attach_to_anki(module: str, logger: logging.Logger, level: int = logging.INFO,
                   also: Iterable[str] = ()) -> None:
    """Send `logger` (and the loggers named in `also`, such as a web server's) to
    the add-on's log file. Call once a profile is open: Anki sets the file up by then."""
    from aqt import mw

    handlers = mw.addonManager.get_logger(module).handlers
    for target in [logger, *map(logging.getLogger, also)]:
        for handler in handlers:
            if handler not in target.handlers:
                target.addHandler(handler)
    logger.setLevel(level)
