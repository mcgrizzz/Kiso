"""Vendoring: an add-on's third-party libraries, unpacked from pure-Python wheels into lib/shared.

    [tool.kiso]
    vendor = "requirements.lock.txt"   # exact pins (name==version), direct and transitive
    vendor_python = "3.10"             # optional: resolve for this Python (default: requires-python's floor)

Anki installs one archive on every platform, so only pure-Python (none-any) wheels are taken: a
package without one fails the build, and a compiled file in lib/ stops it. Wheels are cached in
.wheelhouse/ (a later build can run offline); each wheel's licence files are kept; and
lib/vendor_manifest.json records the name, version, wheel and sha256 of each. lib/ ships with the
add-on. At run time, kiso.vendor puts lib/shared on sys.path and finds copies another add-on loaded.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import List, Tuple

from .project import Project

COMPILED = (".so", ".pyd", ".dylib")
LICENCES = ("license", "licence", "copying", "notice")


def canonical(name: str) -> str:
    """PEP 503 normalisation, to match lockfile names to wheel file names."""
    return re.sub(r"[-_.]+", "-", name).lower()


def read_lockfile(path: Path) -> List[Tuple[str, str]]:
    pins = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if "==" not in line:
            raise SystemExit(f"{path.name}: not an exact pin: {raw.strip()!r}")
        name, version = (part.strip() for part in line.split("==", 1))
        pins.append((name, version))
    if not pins:
        raise SystemExit(f"{path.name} pins nothing")
    return pins


def download(project: Project) -> None:
    """Fetch the pinned wheels into the cache. pip only accepts none-any wheels with these flags,
    so a package without a pure wheel fails here instead of shipping a platform's binary."""
    project.wheel_cache.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "pip", "download", "--no-deps", "-r", str(project.vendor_lockfile),
           "--only-binary=:all:", "--implementation", "py", "--abi", "none", "--platform", "any",
           "--python-version", project.vendor_python, "-d", str(project.wheel_cache)]
    if subprocess.run(cmd).returncode:
        raise SystemExit("Downloading the vendored wheels failed (see pip's output above)")


def find_wheel(cache: Path, name: str, version: str) -> Path:
    """Exactly one cached wheel for a pin; stale versions in the cache are ignored."""
    matches = [w for w in cache.glob("*.whl")
               if len(w.name.split("-")) >= 3 and canonical(w.name.split("-")[0]) == canonical(name)
               and w.name.split("-")[1] == version]
    if not matches:
        raise SystemExit(f"No cached wheel for {name}=={version}; vendor without --offline")
    if len(matches) > 1:
        raise SystemExit(f"Several cached wheels for {name}=={version}: {sorted(m.name for m in matches)}")
    if not matches[0].name.endswith("-none-any.whl"):
        raise SystemExit(f"{matches[0].name} isn't a pure-Python wheel; refusing to vendor it")
    return matches[0]


def unpack(wheel: Path, dest: Path) -> None:
    """The importable files, and the licence files from .dist-info; no other metadata."""
    with zipfile.ZipFile(wheel) as zf:
        for name in zf.namelist():
            if name.endswith("/"):
                continue
            if ".data/" in name:
                if ".data/purelib/" not in name:
                    continue
                target = name.split(".data/purelib/", 1)[1]
            elif ".dist-info/" in name:
                inside = name.split("/", 1)[1].lower().split("/")
                if not any(part.startswith(LICENCES) for part in inside):
                    continue
                target = name
            else:
                target = name
            out = dest / target
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(zf.read(name))


def compiled_files(folder: Path) -> List[Path]:
    return [p for p in folder.rglob("*") if p.suffix in COMPILED]


def vendor(project: Project, offline: bool = False) -> List[Path]:
    """lib/shared and lib/vendor_manifest.json afresh from the lockfile. Returns the wheels."""
    if not offline:
        download(project)
    wheels = [find_wheel(project.wheel_cache, name, version) for name, version in read_lockfile(project.vendor_lockfile)]
    shutil.rmtree(project.vendor_dir, ignore_errors=True)
    project.vendor_dir.mkdir(parents=True)
    for wheel in wheels:
        unpack(wheel, project.vendor_dir)
    compiled = compiled_files(project.vendor_dir)
    if compiled:
        raise SystemExit("Compiled files in lib/shared: " + ", ".join(str(p.relative_to(project.root)) for p in compiled))
    entries = [{"name": w.name.split("-")[0], "version": w.name.split("-")[1], "wheel": w.name,
                "sha256": hashlib.sha256(w.read_bytes()).hexdigest()} for w in sorted(wheels, key=lambda w: w.name.lower())]
    project.vendor_manifest.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")
    return wheels


def current(project: Project) -> bool:
    """lib/shared holds exactly what the lockfile pins."""
    if not (project.vendor_dir.is_dir() and project.vendor_manifest.is_file()):
        return False
    have = {(canonical(e["name"]), e["version"]) for e in json.loads(project.vendor_manifest.read_text(encoding="utf-8"))}
    return have == {(canonical(n), v) for n, v in read_lockfile(project.vendor_lockfile)}


def ensure(project: Project) -> bool:
    """Vendor if the add-on vendors and lib/shared isn't current. Returns whether it vendored."""
    if not project.vendor or current(project):
        return False
    vendor(project)
    return True


def audit(project: Project) -> int:
    """pip-audit on the lockfile, skipping the advisories listed in audit_ignore."""
    cmd = [sys.executable, "-m", "pip_audit", "-r", str(project.vendor_lockfile), "--disable-pip", "--no-deps"]
    for advisory in project.audit_ignore:
        cmd += ["--ignore-vuln", advisory]
    return subprocess.run(cmd).returncode
