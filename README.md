# Kiso 基礎

The plumbing Anki add-ons share: guarded hooks, config migration, a settings
page shell, live reload, logging, and the tooling to build, sync and test.

Kiso is bundled into each add-on when it's built, under the add-on's own
package (`<pkg>/_kiso/`), so two add-ons using different Kiso versions never
meet inside Anki.

## Using it in an add-on

In the add-on's `pyproject.toml`:

```toml
[tool.kiso]
package = "myaddon"                 # the inner package, next to the root __init__.py
root_files = ["__init__.py", "manifest.json", "config.json", "config.md"]
dev_name = "My Add-on (dev)"        # its name in Anki's add-on list when synced
kiso = "0.1"                        # the Kiso version it expects
```

Install Kiso in the add-on's dev environment (`pip install -e ../kiso`), add
`/myaddon/_kiso/` to `.gitignore`, and import it relatively:
`from ._kiso.addon import Addon`.

```sh
kiso bundle            # copy Kiso into myaddon/_kiso/ (pytest and the commands below do it too)
kiso sync --watch      # copy into Anki's add-ons folder; a running Anki reloads on each change
kiso build             # dist/<folder>-<version>.ankiaddon
```

Real-Anki checks use `kiso_dev.harness` (offscreen Anki, throwaway profile,
the add-on installed through its real root `__init__.py`). The pytest plugin
lists Anki's printed deprecation notices after each run and fails on them with
`KISO_STRICT_ANKI_NOTICES=1`. Kiso's own real-Anki check runs on a stand-in
add-on in `checks/`: `python checks/check_runtime.py`.

## What's in it

| Module | For |
| --- | --- |
| `addon` | `Addon`: config action, Tools menu, log file, add-on switch, dev watch, `reload()` |
| `hooks` | `guard`, `Subscriptions`: hook callbacks and timers (repeating, debounced) that log instead of raising and come off on reload |
| `config` | `migrate`, `fill`, `load`: defaults and versioned migration steps |
| `settings` | `Bridge`, `make_dialog`, `page_html`, and the page shell in `web/` |
| `ui` | `rebuild_main_window` after a reload changes what goes into pages; `when_ready` waits for a page condition |
| `logs`, `toggle`, `devreload` | The parts `Addon` is built from |
