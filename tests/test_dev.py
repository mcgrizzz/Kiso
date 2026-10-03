import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

import kiso
from kiso_dev import build, bundle, cli, project, release, sync


def make_addon(tmp_path, kiso_pin="", extra=""):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nversion = "1.2.3"\n[tool.kiso]\npackage = "demo"\n'
        f'root_files = ["__init__.py", "manifest.json", "config.json"]\ndev_name = "Demo (dev)"\nkiso = "{kiso_pin}"\n'
        + extra)
    (tmp_path / "manifest.json").write_text(json.dumps({"package": "demo", "name": "Demo"}))
    (tmp_path / "config.json").write_text("{}")
    (tmp_path / "__init__.py").write_text("from .demo import thing\n")
    (tmp_path / "demo").mkdir()
    (tmp_path / "demo" / "__init__.py").write_text("thing = 1\n")
    (tmp_path / "demo" / "__pycache__").mkdir()
    (tmp_path / "demo" / "__pycache__" / "x.pyc").write_bytes(b"")
    return project.find(tmp_path)


def test_the_project_comes_from_pyproject(tmp_path):
    proj = make_addon(tmp_path)
    assert (proj.package, proj.version, proj.addon_folder, proj.dev_name) == ("demo", "1.2.3", "demo", "Demo (dev)")
    assert proj.bundle_dir == tmp_path / "demo" / "_kiso"


def test_bundle_copies_kiso_once_and_marks_the_version(tmp_path):
    proj = make_addon(tmp_path)
    assert bundle.bundle(proj, quiet=True)
    assert (proj.bundle_dir / "hooks.py").is_file() and (proj.bundle_dir / "web" / "shell.js").is_file()
    assert (proj.bundle_dir / "VERSION").read_text().startswith(kiso.__version__)
    assert not bundle.bundle(proj, quiet=True)      # already current


def test_bundle_refuses_a_kiso_version_the_addon_doesnt_expect(tmp_path):
    proj = make_addon(tmp_path, kiso_pin="9.")
    with pytest.raises(SystemExit, match="expects Kiso 9."):
        bundle.bundle(proj, quiet=True)


def test_the_runtime_never_imports_itself_absolutely():
    bundle.check_relative()


def test_build_packs_the_addon_with_kiso_and_without_local_state(tmp_path):
    proj = make_addon(tmp_path)
    (tmp_path / "meta.json").write_text("{}")
    out = build.build(proj)
    assert out.name == "demo-1.2.3.ankiaddon" and out.with_name(out.name + ".sha256").is_file()
    names = zipfile.ZipFile(out).namelist()
    assert {"__init__.py", "manifest.json", "config.json", "demo/__init__.py", "demo/_kiso/hooks.py"} <= set(names)
    assert not any("__pycache__" in n or n == "meta.json" for n in names)
    first = out.read_bytes()
    assert build.build(proj).read_bytes() == first   # unchanged tree, byte-identical archive


def test_info_names_the_build_file(tmp_path, monkeypatch, capsys):
    proj = make_addon(tmp_path)
    assert release.info(proj) == {"folder": "demo", "package": "demo", "version": "1.2.3",
                                  "artifact": "dist/demo-1.2.3.ankiaddon", "vendor": ""}
    monkeypatch.chdir(tmp_path)
    cli.main(["info"])
    assert "version=1.2.3\nartifact=dist/demo-1.2.3.ankiaddon" in capsys.readouterr().out


def test_a_release_tag_must_be_the_projects_version(tmp_path):
    proj = make_addon(tmp_path)
    assert release.check_tag(proj, "v1.2.3") == "1.2.3"
    with pytest.raises(SystemExit, match="doesn't match"):
        release.check_tag(proj, "v1.2.4")
    for bad in ("1.2.3", "v1.2", "v01.2.3", "v1.2.3-rc1"):
        with pytest.raises(SystemExit, match="isn't a version"):
            release.check_tag(proj, bad)


def make_vendoring_addon(tmp_path):
    """An add-on whose before_build vendors a library into lib/, shipped through include."""
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "vendor.py").write_text(
        "from pathlib import Path\n"
        "Path('lib/shared').mkdir(parents=True, exist_ok=True)\n"
        "Path('lib/shared/vendored.py').write_text('VERSION = 1\\n')\n")
    return make_addon(tmp_path, extra=f"include = [\"lib\"]\nbefore_build = '\"{sys.executable}\" vendor.py'\n")


def test_include_and_before_build_come_from_pyproject(tmp_path):
    proj = make_vendoring_addon(tmp_path / "vendoring")
    assert proj.include == ["lib"] and proj.include_dirs == [tmp_path / "vendoring" / "lib"]
    assert proj.before_build.endswith("vendor.py")
    plain = make_addon(tmp_path)
    assert plain.include == [] and plain.before_build == ""


def test_build_runs_before_build_then_packs_the_included_folders(tmp_path):
    proj = make_vendoring_addon(tmp_path)
    names = zipfile.ZipFile(build.build(proj)).namelist()
    assert "lib/shared/vendored.py" in names and "demo/_kiso/hooks.py" in names


def test_a_failing_before_build_stops_the_build(tmp_path):
    proj = make_addon(tmp_path, extra=f"before_build = '\"{sys.executable}\" -c \"raise SystemExit(3)\"'\n")
    with pytest.raises(SystemExit, match="before_build failed"):
        build.build(proj)
    assert not (tmp_path / "dist" / "demo-1.2.3.ankiaddon").exists()


def test_sync_copies_an_included_folder_only_when_it_changed(tmp_path):
    proj = make_vendoring_addon(tmp_path / "src")
    build.build(proj)   # vendors lib/
    dest = tmp_path / "addons21" / "demo"
    sync.sync(proj, dest)
    assert (dest / "lib" / "shared" / "vendored.py").read_text() == "VERSION = 1\n"
    first = (dest / "lib").stat().st_ino
    sync.sync(proj, dest)
    assert (dest / "lib").stat().st_ino == first          # unchanged: not copied again
    for p in (dest / "lib").rglob("*"):                   # a Windows drive from WSL keeps whole seconds
        os.utime(p, (int(p.stat().st_mtime), int(p.stat().st_mtime)))
    sync.sync(proj, dest)
    assert (dest / "lib").stat().st_ino == first
    src = proj.root / "lib" / "shared" / "vendored.py"
    src.write_text("VERSION = 2\n")
    os.utime(src, (src.stat().st_atime, src.stat().st_mtime + 10))
    sync.sync(proj, dest, include=False)
    assert (dest / "lib" / "shared" / "vendored.py").read_text() == "VERSION = 1\n"   # what --watch does
    sync.sync(proj, dest)
    assert (dest / "lib" / "shared" / "vendored.py").read_text() == "VERSION = 2\n"


def test_the_harness_installs_the_included_folders_too(tmp_path):
    from kiso_dev import harness

    proj = make_vendoring_addon(tmp_path / "src")
    build.build(proj)
    dest = harness.install_copy(proj, tmp_path / "addons21")
    assert (dest / "lib" / "shared" / "vendored.py").is_file() and (dest / "demo" / "__init__.py").is_file()


def test_strict_mode_fails_only_on_the_add_ons_own_deprecated_calls(monkeypatch):
    import anki._legacy

    from kiso_dev import notices

    monkeypatch.setattr(notices, "notices", [])
    notices.install(lambda: "here")
    warn = anki._legacy.print_deprecation_warning

    def deprecated():   # stands for an Anki API that prints a notice for its caller
        warn("old() is deprecated")

    deprecated()   # the add-on's call
    inside = {"deprecated": deprecated}
    anki_dir = Path(anki._legacy.__file__).parent
    exec(compile("def legacy():\n    deprecated()\n", str(anki_dir / "importing" / "anki2.py"), "exec"), inside)
    inside["legacy"]()   # Anki's own older code making the call
    assert [n[2] for n in notices.notices] == [False, True]
    assert notices.failing() == notices.notices[:1]
    assert notices.describe(notices.notices[1]) == "here: old() is deprecated (raised inside Anki)"


def test_pytest_bundles_kiso_before_the_add_ons_conftest_imports_it(tmp_path):
    # A fresh checkout has no _kiso (nor lib/shared) until pytest starts, and pytest imports the
    # add-on's conftest.py before pytest_configure.
    make_addon(tmp_path)
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "conftest.py").write_text(
        "import sys, pathlib\nsys.path.insert(0, str(pathlib.Path(__file__).parents[1]))\n"
        "from demo._kiso import hooks  # noqa: F401  (needs the bundle)\n")
    (tests / "test_ok.py").write_text("def test_ok():\n    pass\n")
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(tests)],
                            cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
