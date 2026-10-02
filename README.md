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
include = ["assets"]                # optional: more folders shipped beside the package
before_build = "python tools/gen.py"   # optional: a command `kiso build` runs first, in the project folder
vendor = "requirements.lock.txt"    # optional: third-party libraries to bundle (below)
```

`build`, `sync` and the real-Anki harness copy the `include` folders too. `sync` copies one
only when it differs from the installed copy, and `sync --watch` leaves them alone: Anki loads
them once per session, so a change there needs a restart anyway.

### Bundled libraries

An add-on that needs third-party libraries pins them, direct and transitive, as `name==version`
lines in its `vendor` lockfile. `kiso vendor` (and `build`, `sync`, the harness and pytest, when
`lib/shared` isn't current) unpacks them from pure-Python wheels into `lib/shared`, which ships
beside the package, with each wheel's licence files and a `lib/vendor_manifest.json`:

- Only `none-any` wheels, resolved for `vendor_python` (default: the floor of `requires-python`):
  Anki installs one archive on every platform. A package without one fails, and `kiso build`
  refuses a compiled file (`.so`, `.pyd`, `.dylib`) anywhere in any add-on.
- Wheels are cached in `.wheelhouse/` (add it to `.gitignore`); `--offline` builds from the cache.
- `kiso audit` runs pip-audit on the lockfile; `audit_ignore = ["PYSEC-…"]` skips advisories
  that don't apply (say why in a comment beside each).

At run time, `kiso.vendor` puts `lib/shared` on `sys.path` and catches the case that breaks
bundled libraries: another add-on imported its own copy first, which then stays in use for the
session. `find_clashes` reports each one and `refusal` says which add-on to disable:

```python
from .myaddon._kiso import vendor            # in the root __init__.py, before the libraries
SHARED = vendor.add_to_path(Path(__file__).parent)
...
blocking = [c for c in vendor.find_clashes(SHARED, critical=("pydantic",)) if c.blocks]
if blocking:                                 # at profile open, once every add-on has loaded
    tooltip(vendor.refusal("My Add-on", blocking, vendor.addon_name(mw.addonManager)))
```

Install Kiso in the add-on's dev environment (`pip install -e ../kiso`), add
`/myaddon/_kiso/` to `.gitignore`, and import it relatively:
`from ._kiso.addon import Addon`.

```sh
kiso bundle            # copy Kiso into myaddon/_kiso/ (pytest and the commands below do it too)
kiso sync --watch      # copy into Anki's add-ons folder; a running Anki reloads on each change
kiso build             # dist/<folder>-<version>.ankiaddon
kiso vendor            # bundled libraries into lib/shared (kiso audit: pip-audit them)
```

Real-Anki checks use `kiso_dev.harness` (offscreen Anki, throwaway profile,
the add-on installed through its real root `__init__.py`). The pytest plugin
lists Anki's printed deprecation notices after each run and fails on them with
`KISO_STRICT_ANKI_NOTICES=1`. Kiso's own real-Anki check runs on a stand-in
add-on in `checks/`: `python checks/check_runtime.py`.

## GitHub Actions

An add-on repo needs two short workflows. CI runs ruff and the tests on the newest Anki and on
the oldest the add-on supports, then the real-Anki checks and the build (kept as a download
on the run):

```yaml
# .github/workflows/ci.yml
on: { push: { branches: [main] }, pull_request: {}, workflow_call: {} }
jobs:
  ci:
    uses: mcgrizzz/Kiso/.github/workflows/addon-ci.yml@main
    with:
      floor-anki: "26.8.1"              # the Anki your min_point_version names
      qt-checks: tools/qt_checks.sh     # optional
      test-packages: httpx              # optional: more packages the tests need
```

An add-on with a `vendor` lockfile also gets an audit job: pip-audit on the lockfile, skipping
the advisories in `audit_ignore`.

A tag `v1.2.3` matching pyproject.toml's version (or a manual run, which tags `v<version>`)
runs CI, then attaches the `.ankiaddon` and its `.sha256` to a draft GitHub release:

```yaml
# .github/workflows/release.yml
on: { push: { tags: ["v*"] }, workflow_dispatch: {} }
jobs:
  ci:
    uses: ./.github/workflows/ci.yml
  release:
    needs: ci
    permissions: { contents: write }
    uses: mcgrizzz/Kiso/.github/workflows/addon-release.yml@main
```

Both are built on the setup action, which works in any workflow: `uses: mcgrizzz/Kiso@main`
sets up Python, installs Kiso from that copy of the action (so the add-on bundles exactly
that Kiso) and Anki with its Qt (`anki: "==26.8.1"`, `latest` or `none`; `qt: false` for anki
alone). `kiso info` prints the add-on's folder, version and build file for later steps, and
`kiso check-tag` stops a release whose tag doesn't match the version. Anki's deprecation
notices fail the tests and checks.

The AnkiWeb upload stays by hand (AnkiWeb doesn't allow automated uploads); the userscript
below fills in its form.

## What's in it

| Module | For |
| --- | --- |
| `addon` | `Addon`: config action, Tools menu, log file, add-on switch, dev watch, `reload()` |
| `hooks` | `guard`, `Subscriptions`: hook callbacks and timers (repeating, debounced) that log instead of raising and come off on reload |
| `config` | `migrate`, `fill`, `load`: defaults and versioned migration steps |
| `settings` | `Bridge`, `make_dialog`, `page_html`, and the page shell in `web/` |
| `ui` | `rebuild_main_window` after a reload changes what goes into pages; `when_ready` waits for a page condition |
| `vendor` | Bundled libraries at run time: `add_to_path`, `find_clashes`, `refusal` |
| `logs`, `toggle`, `devreload` | The parts `Addon` is built from |

## AnkiWeb upload helper

`userscripts/ankiweb-upload-helper.user.js` is a Tampermonkey/Violentmonkey script for
any add-on author. On an add-on's AnkiWeb edit page (`/shared/upload?id=...`) it asks
once for a link to the add-on's `ankiweb.md` on GitHub, then fills the form from it
(Title, Tags, Support page, Branches, Description: one `## <field>` section each, the
value in its first fenced block) and attaches the `.ankiaddon` from the repo's latest
release, checked against its `.sha256` if there is one. You check it and press Save
yourself: AnkiWeb doesn't allow automated uploads.

AnkiWeb stores no version and strips hidden text from descriptions, so the description
carries a "what's new" link to the release: placed by `{{version}}` and `{{release_url}}`
in `ankiweb.md`, or added at the end. The helper reads the version on AnkiWeb back from
that link, and attaches no file when the latest release is already there.
