"""An add-on project, as its pyproject.toml describes it:

    [project]
    version = "0.1.0"

    [tool.kiso]
    package = "keshiki"                  # the inner package, next to the root __init__.py
    root_files = ["__init__.py", "manifest.json", "config.json", "config.md"]
    dev_name = "Keshiki (dev)"           # its name in Anki's add-on list when synced
    kiso = "0.1"                         # the Kiso version it expects (a prefix)
    include = ["assets"]                 # optional: more folders shipped beside the package
    before_build = "python tools/gen.py" # optional: run in the project folder before a build
    vendor = "requirements.lock.txt"     # optional: third-party libraries for lib/shared (kiso_dev.vendor)
    vendor_python = "3.10"               # optional: the Python they're resolved for (default: requires-python's floor)
    audit_ignore = ["PYSEC-2026-1"]      # optional: advisories `kiso audit` skips (say why in a comment)
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

if sys.version_info >= (3, 11):
    import tomllib
else:   # pragma: no cover
    import tomli as tomllib


@dataclass
class Project:
    root: Path
    package: str
    version: str
    root_files: List[str] = field(default_factory=list)
    dev_name: str = ""
    kiso: str = ""
    include: List[str] = field(default_factory=list)
    before_build: str = ""
    vendor: str = ""
    vendor_python: str = ""
    audit_ignore: List[str] = field(default_factory=list)

    @property
    def package_dir(self) -> Path:
        return self.root / self.package

    @property
    def bundle_dir(self) -> Path:
        """Where Kiso is bundled: inside the inner package, imported relatively."""
        return self.package_dir / "_kiso"

    @property
    def include_dirs(self) -> List[Path]:
        """Folders shipped beside the package: `include`, and lib/ when the add-on vendors."""
        names = list(self.include) + (["lib"] if self.vendor and "lib" not in self.include else [])
        return [self.root / name for name in names]

    @property
    def vendor_lockfile(self) -> Path:
        return self.root / self.vendor

    @property
    def vendor_dir(self) -> Path:
        return self.root / "lib" / "shared"

    @property
    def vendor_manifest(self) -> Path:
        return self.root / "lib" / "vendor_manifest.json"

    @property
    def wheel_cache(self) -> Path:
        return self.root / ".wheelhouse"

    @property
    def addon_folder(self) -> str:
        """The folder name Anki installs it under (manifest.json's "package")."""
        import json
        return json.loads((self.root / "manifest.json").read_text(encoding="utf-8"))["package"]


def find(start: Path = None) -> Project:
    """The project whose pyproject.toml is at `start` or the nearest folder above it."""
    here = (start or Path.cwd()).resolve()
    for folder in [here, *here.parents]:
        path = folder / "pyproject.toml"
        if path.is_file():
            data = tomllib.loads(path.read_text(encoding="utf-8"))
            if "kiso" in data.get("tool", {}):
                cfg = data["tool"]["kiso"]
                floor = re.search(r">=\s*(\d+\.\d+)", data["project"].get("requires-python", ""))
                return Project(root=folder, package=cfg["package"], version=data["project"]["version"],
                               root_files=list(cfg.get("root_files", ["__init__.py", "manifest.json"])),
                               dev_name=cfg.get("dev_name", ""), kiso=str(cfg.get("kiso", "")),
                               include=list(cfg.get("include", [])), before_build=cfg.get("before_build", ""),
                               vendor=cfg.get("vendor", ""),
                               vendor_python=str(cfg.get("vendor_python") or (floor.group(1) if floor else "3.10")),
                               audit_ignore=list(cfg.get("audit_ignore", [])))
    raise SystemExit(f"No pyproject.toml with a [tool.kiso] table at or above {here}")
