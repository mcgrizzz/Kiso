"""`kiso shots`: ask the running Anki for screenshots of the add-on's settings, as it
shows them, and wait for them. The dev copy's watch picks the request up (kiso/shots.py
takes them); they land in <dev copy>/kiso_shots/<id>/.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Callable, Optional, Tuple

REQUEST = "DEV_SHOTS"
OUT = "kiso_shots"   # not dev_shots: Windows names ignore case, and DEV_SHOTS is the request
KEEP = 5   # runs kept in kiso_shots


def request(dest: Path, narrow: int = 800, run_id: Optional[str] = None, tour: Optional[str] = None,
            size: Optional[Tuple[int, int]] = None) -> Path:
    """Leave a request in the dev copy; the folder its shots will land in. `tour`: only the
    add-on's tour of that name; `size`: only that window size (instead of saved, then narrow)."""
    if not (dest / "DEV_WATCH").exists():
        raise SystemExit(f"{dest} isn't a dev copy: run kiso sync first (and restart Anki once).")
    runs = dest / OUT
    if runs.is_dir():
        for old in sorted((p for p in runs.iterdir() if p.is_dir()), key=lambda p: p.name)[:-(KEEP - 1) or None]:
            shutil.rmtree(old, ignore_errors=True)
    run_id = run_id or time.strftime("%Y%m%d-%H%M%S")
    req: dict = {"id": run_id, "narrow": narrow}
    if tour:
        req["tour"] = tour
    if size:
        req["size"] = list(size)
    (dest / REQUEST).write_text(json.dumps(req), encoding="utf-8")
    return runs / run_id


def wait(dest: Path, out: Path, timeout: float = 360.0, pickup: float = 15.0, poll: float = 0.5,
         sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic) -> dict:
    """The run's done.json once Anki writes it."""
    began = clock()
    picked = False
    while clock() - began < timeout:
        done = out / "done.json"
        if done.is_file():
            try:
                return json.loads(done.read_text(encoding="utf-8"))
            except ValueError:   # still being written
                pass
        picked = picked or not (dest / REQUEST).is_file()
        if not picked and clock() - began > pickup:
            (dest / REQUEST).unlink(missing_ok=True)
            raise SystemExit("Anki didn't pick up the request. Is it running, with this dev copy? After the first "
                             "sync with this Kiso, restart Anki once so its dev watch knows about screenshots.")
        sleep(poll)
    raise SystemExit(f"No screenshots after {timeout:g} s; see the add-on's log in Anki.")
