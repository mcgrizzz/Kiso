"""Add-on config: defaults filled in, versioned migrations, load and save. Pure, tested headless."""

from __future__ import annotations

import copy
from typing import Any, Callable, Iterable, Sequence, Tuple

Step = Tuple[int, Callable[[dict], None]]


def fill(cfg: dict, defaults: dict, free_form: Iterable[str] = ()) -> bool:
    """Add keys missing from cfg, recursing into dicts except those named in
    `free_form` (dicts of user data, filled as a whole or not at all).
    Containers are copied, so a config never shares state with its defaults.
    Returns whether anything was added."""
    free_form = set(free_form)
    changed = False
    for key, value in defaults.items():
        if key not in cfg:
            cfg[key] = copy.deepcopy(value)
            changed = True
        elif isinstance(value, dict) and isinstance(cfg[key], dict) and key not in free_form:
            changed |= fill(cfg[key], value, free_form)
    return changed


def migrate(cfg: dict, defaults: dict, version: int, steps: Sequence[Step] = (),
            free_form: Iterable[str] = ()) -> Tuple[dict, bool]:
    """A copy of cfg brought up to `version`: each (to_version, fn) step whose
    version is above the config's own runs in order, then defaults fill the gaps.
    Returns (cfg, changed). A config without "config_version" is a new one."""
    cfg = copy.deepcopy(cfg or {})
    changed = False
    current = cfg.get("config_version", version)
    for to_version, step in sorted(steps, key=lambda s: s[0]):
        if current < to_version:
            step(cfg)
            changed = True
    changed |= fill(cfg, defaults, free_form)
    if cfg.get("config_version") != version:
        cfg["config_version"] = version
        changed = True
    return cfg, changed


def load(manager: Any, package: str, migrate_fn: Callable[[dict], Tuple[dict, bool]]) -> dict:
    """The add-on's config, migrated, and written back only if migrating changed it."""
    cfg, changed = migrate_fn(manager.getConfig(package) or {})
    if changed:
        manager.writeConfig(package, cfg)
    return cfg
