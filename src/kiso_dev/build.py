"""Building the .ankiaddon: dist/<folder>-<version>.ankiaddon, a zip Anki installs.

Timestamps and permissions are fixed, so an unchanged tree builds byte-identical.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

from . import vendor
from .bundle import bundle
from .project import Project

SKIP_DIRS = {"__pycache__"}
SKIP_SUFFIXES = {".pyc", ".pyo"}


def files(project: Project):
    yield from (project.root / name for name in project.root_files if (project.root / name).exists())
    for path in sorted(p for folder in [project.package_dir, *project.include_dirs] for p in folder.rglob("*")):
        if path.is_file() and not SKIP_DIRS & set(path.parts) and path.suffix not in SKIP_SUFFIXES \
                and not path.name.startswith("."):
            yield path


def validate(path: Path, project: Project) -> None:
    """Refuse an archive Anki would choke on or that leaks local state."""
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        bad = zf.testzip()
        if bad:
            raise SystemExit(f"Corrupt entry in {path.name}: {bad}")
        # Compiled files: Anki installs one archive on every platform.
        problems = [n for n in names if n == "meta.json" or "__pycache__" in n or ".." in n or "\\" in n
                    or n.endswith((".pyc", ".pyo") + vendor.COMPILED)]
        missing = [f for f in ("__init__.py", "manifest.json") if f not in names]
        if project.vendor:
            missing += [f for f in ("lib/vendor_manifest.json",) if f not in names]
            if not any(n.startswith("lib/shared/") and n.endswith(".py") for n in names):
                missing.append("lib/shared/ (no vendored Python)")
        if not any(n.startswith(f"{project.package}/_kiso/") for n in names):
            missing.append(f"{project.package}/_kiso/")
        for name in names:
            if name.endswith(".json"):
                json.loads(zf.read(name))
    if problems or missing:
        raise SystemExit(f"{path.name}: unexpected {problems or ''} missing {missing or ''}".strip())


def build(project: Project, offline: bool = False) -> Path:
    if project.vendor:
        vendor.vendor(project, offline=offline)   # afresh: a release ships exactly the lockfile
    if project.before_build and subprocess.run(project.before_build, shell=True, cwd=project.root).returncode:
        raise SystemExit(f"before_build failed: {project.before_build}")
    bundle(project, quiet=True)
    out = project.root / "dist" / f"{project.addon_folder}-{project.version}.ankiaddon"
    out.parent.mkdir(exist_ok=True)
    tmp = out.with_suffix(".building")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in files(project):
            info = zipfile.ZipInfo(path.relative_to(project.root).as_posix(), date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, path.read_bytes())
    validate(tmp, project)
    tmp.replace(out)
    out.with_name(out.name + ".sha256").write_text(f"{hashlib.sha256(out.read_bytes()).hexdigest()}  {out.name}\n")
    return out
