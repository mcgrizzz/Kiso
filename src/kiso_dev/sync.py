"""Copying an add-on into an installed Anki's addons21/<folder> for live development.

The copy gets a DEV_WATCH file, so a running Anki notices each sync and
reloads the add-on by itself. The first sync, and changes to the root
__init__.py, still need an Anki restart. The copy is listed under the project's
dev_name. user_files and the settings in meta.json are left alone.
"""

from __future__ import annotations

import glob
import json
import os
import shutil
import time
from pathlib import Path
from typing import Optional

from . import vendor
from .bundle import SOURCE as KISO_SOURCE
from .bundle import bundle
from .project import Project


def default_dest(project: Project) -> Optional[Path]:
    env = os.environ.get("KISO_ADDON_DIR")
    if env:
        return Path(env)
    candidates = [os.path.expandvars(r"%APPDATA%\Anki2"), *glob.glob("/mnt/c/Users/*/AppData/Roaming/Anki2"),
                  os.path.expanduser("~/.local/share/Anki2"), os.path.expanduser("~/Library/Application Support/Anki2")]
    for base in candidates:
        if (Path(base) / "addons21").is_dir():
            return Path(base) / "addons21" / project.addon_folder
    return None


def _copy_tree(src: Path, dest: Path) -> None:
    # Stage beside the destination, then swap, so Anki never imports a half-written package.
    stage = dest.with_name(dest.name + ".syncing")
    shutil.rmtree(stage, ignore_errors=True)
    shutil.copytree(src, stage, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.rmtree(dest, ignore_errors=True)
    os.replace(stage, dest)


def _name_dev_copy(project: Project, dest: Path) -> None:
    """Anki lists an add-on by meta.json's "name"; only that key changes."""
    if not project.dev_name:
        return
    path = dest / "meta.json"
    meta = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    if meta.get("name") != project.dev_name:
        meta["name"] = project.dev_name
        path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")


def sync(project: Project, dest: Path, include: bool = True) -> None:
    """With `include`, the include folders are copied too, each only if it differs from the
    installed one (they're vendored libraries, and Anki loads them once per session)."""
    bundle(project, quiet=True)
    vendor.ensure(project)
    dest.mkdir(parents=True, exist_ok=True)
    _copy_tree(project.package_dir, dest / project.package)
    for folder in project.include_dirs if include else []:
        if folder.is_dir() and not _same(_stamp(folder), _stamp(dest / folder.name)):
            _copy_tree(folder, dest / folder.name)
    for name in project.root_files:
        if (project.root / name).exists():
            shutil.copy2(project.root / name, dest / name)
    (dest / "DEV_WATCH").touch()
    _name_dev_copy(project, dest)


def _same(a: tuple, b: tuple) -> bool:
    """Stamps of a folder and its copy match. Some drives keep coarser times than the
    source (whole seconds on a Windows drive from WSL, two seconds on FAT)."""
    return a[0] == b[0] and abs(a[1] - b[1]) < 2


def _stamp(*folders: Path) -> tuple:
    files = [p for folder in folders for p in folder.rglob("*")
             if p.is_file() and "__pycache__" not in p.parts and "_kiso" not in p.parts]
    return len(files), max((p.stat().st_mtime for p in files), default=0)


def watch(project: Project, dest: Path, every: float = 1.0) -> None:
    """Sync whenever the add-on's package, its root files or Kiso itself change. The include
    folders aren't watched: a change there needs an Anki restart, so it goes with the next sync."""
    roots = [project.package_dir, KISO_SOURCE]
    extra = [project.root / n for n in project.root_files if (project.root / n).exists()]
    stamp = (_stamp(*roots), max(p.stat().st_mtime for p in extra))
    try:
        while True:
            time.sleep(every)
            current = (_stamp(*roots), max(p.stat().st_mtime for p in extra))
            if current != stamp:
                stamp = current
                sync(project, dest, include=False)
                print(f"  synced {time.strftime('%H:%M:%S')}")
    except KeyboardInterrupt:
        print()
