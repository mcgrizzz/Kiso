# A stand-in add-on that only carries Kiso, for the real-Anki checks next to it.

try:
    from aqt import mw
except ImportError:   # imported outside Anki
    mw = None

addon = None

if mw is not None:
    from .fixture._kiso.addon import Addon

    addon = Addon(__name__, inner="fixture", start=lambda: None)
    addon.install()
