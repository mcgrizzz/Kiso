"""A start that crashed Anki, not started again until the code changes.

Some failures can't be caught: a crash in native code (Qt, PyQt, a driver) ends Anki at once,
with no exception and nothing logged. If it happens while an add-on starts, every launch
crashes the same way. So the start leaves a mark beside the add-on first, naming the code (its
files' sizes and times), and removes it once the start has settled (a few seconds later, or
when Anki closes). A mark still there at the next launch means that code crashed Anki: it isn't
started, and the user is told and may start it anyway. New code (an update, a dev sync) starts
as usual. Anki's own updates replace the add-on's folder, mark and all.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Iterable, Optional

MARK = ".kiso_starting"
CODE = (".py", ".js", ".css", ".html")
SETTLE_MS = 5000   # a crash this soon after a start counts as the start's


def fingerprint(folders: Iterable[Path], files: Iterable[Path] = ()) -> str:
    """The code as it is: each code file's path, size and time."""
    digest = hashlib.sha1()
    paths = [p for folder in folders if folder.is_dir() for p in folder.rglob("*")
             if p.suffix in CODE and "__pycache__" not in p.parts]
    for path in sorted([*paths, *(f for f in files if f.is_file())]):
        try:
            st = path.stat()
        except OSError:
            continue
        digest.update(f"{path.as_posix()}|{st.st_size}|{st.st_mtime_ns}\n".encode())
    return digest.hexdigest()


def last_crash(anki_base) -> str:
    """The thread that crashed, from the last crash in Anki's crash.log (Anki points Python's
    faulthandler there), for the add-on's log."""
    try:
        text = (Path(anki_base) / "crash.log").read_text(encoding="utf-8", errors="replace")
    except (OSError, TypeError):
        return "Anki's crash.log can't be read."
    start = max(text.rfind("Fatal Python error"), text.rfind("Windows fatal exception"))
    block = text[start:] if start >= 0 else ""
    current = block.find("Current thread")
    if current < 0:
        return "Anki's crash.log has no stack for it."
    lines = block[current:].splitlines()
    end = next((i for i, line in enumerate(lines) if i and not line.strip()), len(lines))
    return "The crashed thread, from Anki's crash.log:\n" + "\n".join(lines[:min(end, 40)])


class Guard:
    def __init__(self, base: Path):
        self.mark = base / MARK
        self.token = 0

    def crashed_before(self, code: str) -> bool:
        """Whether this same code was starting when an earlier Anki ended without warning (a
        mark this Anki left is a start still settling, not a crash)."""
        try:
            left, _, pid = self.mark.read_text(encoding="utf-8").partition(" ")
        except OSError:
            return False
        return left == code and pid.strip() != str(os.getpid())

    def starting(self, code: str) -> int:
        """Leave the mark (if the folder can be written: else the start goes unguarded)."""
        self.token += 1
        try:
            self.mark.write_text(f"{code} {os.getpid()}", encoding="utf-8")
        except OSError:
            pass
        return self.token

    def settled(self, token: Optional[int] = None) -> None:
        """The start is behind us (token: only if no start has begun since)."""
        if token is not None and token != self.token:
            return
        try:
            self.mark.unlink(missing_ok=True)
        except OSError:
            pass
