"""Real-Anki check of the crash guard, over three launches of one Anki folder: the add-on's start
crashes Anki outright (native code, nothing to catch); the next launch leaves it off and offers
to start it; with its code changed, it starts as usual."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

LAUNCH = os.environ.get("KISO_CHECK_LAUNCH")


def launch():
    """One launch, in this process (the parent runs it as a child)."""
    # isort: off
    from kiso_dev.harness import addon, run, until

    import aqt.utils
    # isort: on
    asked = []
    aqt.utils.askUser = lambda text, **kw: asked.append(text) or False   # "Keep it off"

    def check(app, shots, base):
        guarded = addon().addon
        if LAUNCH == "after":
            until(app, lambda: asked, 5, "the user wasn't told the add-on was held back")
            assert guarded.held_back and guarded.feature is None and "closed Anki unexpectedly" in asked[0], asked
            print("HELD BACK", flush=True)
        else:
            assert not guarded.held_back and not asked, asked
            print("STARTED", flush=True)

    run(check, __doc__)


def main():
    with tempfile.TemporaryDirectory(prefix="kiso-crash-", ignore_cleanup_errors=True) as base:
        def run_launch(name, **env):
            proc = subprocess.run([sys.executable, __file__], capture_output=True, text=True, timeout=240,
                                  env={**os.environ, "KISO_CHECK_BASE": base, "KISO_CHECK_LAUNCH": name, **env})
            return proc.returncode, proc.stdout + proc.stderr

        folder = Path(base) / "addons21" / "kisocheck"
        code, out = run_launch("crash", KISO_CHECK_CRASH_ON_START="1")
        assert code != 0 and "PASS: Anki shut down cleanly." not in out, out[-2000:]
        assert (folder / ".kiso_starting").exists(), "the crash left no mark"
        print(f"PASS: an add-on whose start crashes Anki outright ends it (exit code {code}), leaving its mark.")
        code, out = run_launch("after")
        assert code == 0 and "HELD BACK" in out, out[-3000:]
        log = (Path(base) / "logs" / "addons" / "kisocheck" / "kisocheck.log").read_text(encoding="utf-8")
        assert "wasn't started" in log and "in _start" in log, log[-2000:]   # the stack, from Anki's crash.log
        print("PASS: the next launch leaves it off, offers to start it anyway, and logs the crash's stack.")
        (Path(base) / "addons21" / "kisocheck" / "fixture" / "fixed.py").write_text("FIXED = True\n")
        code, out = run_launch("fixed")
        assert code == 0 and "STARTED" in out, out[-3000:]
        print("PASS: with its code changed, it starts as usual.")


if __name__ == "__main__":
    launch() if LAUNCH else main()
