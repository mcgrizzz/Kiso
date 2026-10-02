"""An add-on's vendored libraries at run time (`kiso vendor` puts them in lib/shared).

    from .mypkg._kiso import vendor
    SHARED = vendor.add_to_path(Path(__file__).parent)    # in the root __init__, before importing them

sys.modules wins over sys.path: a library another add-on imported first stays in use for the
whole session, whatever this add-on bundles. Usually that's harmless; for a library the add-on
can't run on at another version it isn't, so find_clashes() reports each one, and refusal() says
which add-on to disable instead of a traceback. Standard library only: this runs before any
vendored library is imported.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, NamedTuple, Optional


def add_to_path(addon_root: Path) -> Path:
    """Put the add-on's lib/shared first on sys.path (if it has one); returns that folder."""
    shared = Path(addon_root) / "lib" / "shared"
    if shared.is_dir() and str(shared) not in sys.path:
        sys.path.insert(0, str(shared))
    return shared


class Clash(NamedTuple):
    name: str
    file: str                  # where the loaded copy comes from
    version: Optional[str]     # what is loaded, if it says
    bundled: Optional[str]     # what the add-on ships
    critical: bool             # the add-on can't run on another version

    @property
    def blocks(self) -> bool:
        return self.critical and self.version != self.bundled


def bundled_versions(shared: Path) -> Dict[str, str]:
    """{package: version} from the .dist-info folders in lib/shared."""
    out = {}
    for entry in shared.glob("*.dist-info"):
        name, _, version = entry.name[:-len(".dist-info")].partition("-")
        out[name.lower().replace("-", "_")] = version
    return out


def anki_roots() -> List[str]:
    """Where Anki's own Python packages live: its copies are the normal environment, not clashes."""
    roots = []
    for name in ("anki", "aqt"):
        file = getattr(sys.modules.get(name), "__file__", None)
        if file:
            roots.append(str(Path(file).resolve().parent.parent))
    return roots


def _version(module: Any) -> Optional[str]:
    for attr in ("__version__", "VERSION"):
        value = getattr(module, attr, None)
        if value is not None:
            return str(value)
    return None


def find_clashes(shared: Path, critical: Iterable[str] = (), roots: Optional[Iterable[str]] = None,
                 modules: Optional[Dict[str, Any]] = None) -> List[Clash]:
    """Bundled packages already imported from outside lib/shared and outside Anki's own packages.
    `critical` names the ones the add-on can't run on at another version."""
    if not Path(shared).is_dir():
        return []
    modules = sys.modules if modules is None else modules
    prefix, roots, critical = str(shared), tuple(anki_roots() if roots is None else roots), set(critical)
    versions = bundled_versions(shared)
    out = []
    for child in sorted(Path(shared).iterdir()):
        name = child.name[:-3] if child.name.endswith(".py") else child.name
        if not name.isidentifier():
            continue
        module = modules.get(name)
        file = getattr(module, "__file__", None) if module is not None else None
        if file and not file.startswith(prefix) and not file.startswith(roots):
            out.append(Clash(name, file, _version(module), versions.get(name), name in critical))
    return out


def addon_folder(file: str, addons_root: str) -> Optional[str]:
    """The add-on folder a module file lives in, if it is under addons21."""
    try:
        relative = Path(file).resolve().relative_to(Path(addons_root).resolve())
    except ValueError:
        return None
    return relative.parts[0] if relative.parts else None


def addon_name(manager: Any) -> Callable[[str], Optional[str]]:
    """The add-on (by its name in Anki's list) a module file comes from, for refusal()."""
    def name(file: str) -> Optional[str]:
        folder = addon_folder(file, manager.addonsFolder())
        meta = manager.addon_meta(folder) if folder else None
        return meta.human_name() if meta else folder
    return name


def refusal(title: str, blocking: List[Clash], name_of: Callable[[str], Optional[str]]) -> str:
    """What to tell the user when blocking clashes stop the add-on; `name_of(file)` names the add-on."""
    parts = []
    for clash in blocking:
        owner = name_of(clash.file)
        where = f"the add-on “{owner}”" if owner else clash.file
        loaded = f"version {clash.version}" if clash.version else "another version"
        parts.append(f"{clash.name} ({loaded}, from {where}; {title} needs {clash.bundled})")
    return (f"{title} did not start: another add-on loaded a different version of a library {title} "
            f"needs: " + "; ".join(parts) + f". Disable that add-on, or update it or {title}, then restart Anki.")
