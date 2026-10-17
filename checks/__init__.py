# A stand-in add-on that only carries Kiso, for the real-Anki checks next to it.

try:
    from aqt import mw
except ImportError:   # imported outside Anki
    mw = None

addon = None


def _start():
    import os
    if os.environ.get("KISO_CHECK_CRASH_ON_START"):   # check_crash.py: a start that crashes Anki
        import faulthandler
        faulthandler._sigsegv()   # a real segfault, as a broken Qt call gives (ctypes would catch one on Windows)
    return None


if mw is not None:
    from .fixture._kiso.addon import Addon

    addon = Addon(__name__, inner="fixture", start=_start)
    addon.install()
