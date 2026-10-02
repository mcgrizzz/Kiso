"""Running a check against a real, offscreen Anki with the add-on installed in a throwaway profile.

    from kiso_dev.harness import js, pump, run, until

    def check(app, shots, base):   # shots: folder for screenshots or None; base: the temp profile folder
        ...

    if __name__ == "__main__":
        run(check, __doc__)

The add-on (with Kiso bundled) is copied into the temporary addons21 folder, so
it runs through its real root __init__.py, web exports and media server URLs,
and anything it writes (user_files) lands there, not in the repo.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
os.environ["ANKI_SOFTWAREOPENGL"] = "1"

import aqt  # noqa: E402
from aqt.profiles import ProfileManager  # noqa: E402
from aqt.qt import QCoreApplication, QEvent, sip  # noqa: E402

from . import notices  # noqa: E402
from .bundle import bundle  # noqa: E402
from .project import find  # noqa: E402

notices.install(lambda: "real Anki")
PROJECT = None


def until(app, predicate, seconds=20, message="Qt condition timed out"):
    """Pump Qt (deleting what's been deleteLater'd) until predicate() is true."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError(message)


def pump(app, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)


def js(app, web, code, seconds=10):
    """Run JavaScript in a webview and return its result."""
    out = []
    web.page().runJavaScript(code, out.append)
    until(app, lambda: bool(out), seconds, f"no JS result for {code[:60]!r}")
    return out[0]


def addon():
    """The running add-on's root module."""
    return sys.modules[PROJECT.addon_folder]


def install_copy(project, addons: Path) -> Path:
    bundle(project, quiet=True)
    dest = addons / project.addon_folder
    dest.mkdir(parents=True)
    for name in project.root_files:
        src = project.root / name
        if src.exists():
            shutil.copy(src, dest / name)
    for folder in [project.package_dir, *project.include_dirs]:
        shutil.copytree(folder, dest / folder.name, ignore=shutil.ignore_patterns("__pycache__"))
    return dest


def run(check, description, profile="KisoCheck", size=(1280, 800)):
    global PROJECT
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--screenshots", type=Path, help="folder to save screenshots in")
    args = parser.parse_args()
    if args.screenshots:
        args.screenshots.mkdir(parents=True, exist_ok=True)
    PROJECT = find(Path(sys.argv[0]).resolve().parent)
    with tempfile.TemporaryDirectory(prefix="kiso-qt-") as base:
        install_copy(PROJECT, Path(base) / "addons21")
        pm = ProfileManager(Path(base))
        pm.setupMeta()
        pm.create(profile)
        pm.openProfile(profile)
        pm.meta["defaultLang"] = "en_US"
        pm.save()
        pm.db.close()
        # Bypass IPC so this process cannot signal another Anki instance.
        aqt.AnkiApp.secondInstance = lambda self: False
        app = aqt._run(["anki", "-b", base, "-p", profile, "-l", "en"], exec=False)
        assert app is not None
        errors = []
        original_hook = sys.excepthook

        def exception_hook(kind, value, tb):
            errors.append(str(value))
            traceback.print_exception(kind, value, tb)

        sys.excepthook = exception_hook
        try:
            until(app, lambda: aqt.mw.col is not None and aqt.mw.state == "deckBrowser")
            notices.install(lambda: "real Anki")   # again, for modules Anki and the add-on loaded since
            aqt.mw.resize(*size)
            pump(app, 0.5)
            check(app, args.screenshots, Path(base))
            assert not errors, errors
            pump(app, 1)   # let Anki's queued page refreshes finish before the collection closes
        finally:
            if not sip.isdeleted(aqt.mw):
                aqt.mw.close()
                until(app, lambda: sip.isdeleted(aqt.mw), 30)
            sys.excepthook = original_hook
    print("PASS: Anki shut down cleanly.", flush=True)
    for where, msg in notices.notices:
        print(f"Anki deprecation notice ({where}): {msg}", flush=True)
    if notices.notices and notices.STRICT:
        sys.exit(1)
