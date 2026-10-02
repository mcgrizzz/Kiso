"""Copying Kiso into an add-on (`<package>/_kiso/`), from the Kiso installed in this environment.

The copy is generated, never committed: .gitignore it, and leave it out of
lint. Pin the expected version in [tool.kiso] kiso = "0.1"; a mismatch stops the
bundle rather than quietly shipping something else.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import kiso

from .project import Project

SOURCE = Path(kiso.__file__).resolve().parent
# An absolute import would reach for whichever Kiso another add-on loaded first.
_ABSOLUTE = re.compile(r"^\s*(from|import)\s+kiso(\.|\s|$)", re.M)


def check_relative(source: Path = SOURCE) -> None:
    for path in source.rglob("*.py"):
        if _ABSOLUTE.search(path.read_text(encoding="utf-8")):
            raise SystemExit(f"{path} imports kiso absolutely; a bundled copy must import relatively")


def stamp(source: Path = SOURCE) -> str:
    """The version, plus the newest change time when bundling from a working copy."""
    newest = max(p.stat().st_mtime for p in source.rglob("*") if p.is_file())
    return f"{kiso.__version__} {int(newest)}"


def bundle(project: Project, quiet: bool = False) -> bool:
    """Copy Kiso in if what's there is missing or older. Returns whether it copied."""
    if project.kiso and not kiso.__version__.startswith(project.kiso):
        raise SystemExit(f"{project.package} expects Kiso {project.kiso}, but {kiso.__version__} is installed")
    target = project.bundle_dir
    version_file = target / "VERSION"
    want = stamp()
    if version_file.is_file() and version_file.read_text().strip() == want:
        return False
    check_relative()
    stage = target.with_name("_kiso.bundling")
    shutil.rmtree(stage, ignore_errors=True)
    shutil.copytree(SOURCE, stage, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (stage / "VERSION").write_text(want + "\n")
    shutil.rmtree(target, ignore_errors=True)
    stage.replace(target)
    if not quiet:
        print(f"Bundled Kiso {kiso.__version__} into {target.relative_to(project.root)}")
    return True
