"""An add-on project, as its pyproject.toml describes it:

    [project]
    version = "0.1.0"

    [tool.kiso]
    package = "keshiki"                  # the inner package, next to the root __init__.py
    root_files = ["__init__.py", "manifest.json", "config.json", "config.md"]
    dev_name = "Keshiki (dev)"           # its name in Anki's add-on list when synced
    kiso = "0.1"                         # the Kiso version it expects (a prefix)
"""

from __future__ import annotations

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

    @property
    def package_dir(self) -> Path:
        return self.root / self.package

    @property
    def bundle_dir(self) -> Path:
        """Where Kiso is bundled: inside the inner package, imported relatively."""
        return self.package_dir / "_kiso"

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
                return Project(root=folder, package=cfg["package"], version=data["project"]["version"],
                               root_files=list(cfg.get("root_files", ["__init__.py", "manifest.json"])),
                               dev_name=cfg.get("dev_name", ""), kiso=str(cfg.get("kiso", "")))
    raise SystemExit(f"No pyproject.toml with a [tool.kiso] table at or above {here}")
