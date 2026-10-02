"""What a release needs from the project: its file names, and a tag that matches its version.

    kiso info              folder=..., package=..., version=..., artifact=dist/<folder>-<version>.ankiaddon
    kiso check-tag v1.2.3  stops unless the tag is v<version> (pyproject.toml's [project] version)

`kiso info` prints key=value lines, so a GitHub Actions step can append them to $GITHUB_OUTPUT.
"""

from __future__ import annotations

import re
from typing import Dict

from .project import Project

TAG = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")


def info(project: Project) -> Dict[str, str]:
    return {
        "folder": project.addon_folder,
        "package": project.package,
        "version": project.version,
        "artifact": f"dist/{project.addon_folder}-{project.version}.ankiaddon",
    }


def check_tag(project: Project, tag: str) -> str:
    """The version a release tag names, if it's the project's; otherwise stop with why."""
    if not TAG.fullmatch(tag):
        raise SystemExit(f"Release tag {tag!r} isn't a version such as v1.2.3.")
    if tag[1:] != project.version:
        raise SystemExit(f"Release tag {tag} doesn't match the version in pyproject.toml ({project.version}).")
    return project.version
