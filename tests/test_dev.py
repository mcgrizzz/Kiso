import json
import zipfile

import pytest

import kiso
from kiso_dev import build, bundle, project


def make_addon(tmp_path, kiso_pin=""):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nversion = "1.2.3"\n[tool.kiso]\npackage = "demo"\n'
        f'root_files = ["__init__.py", "manifest.json", "config.json"]\ndev_name = "Demo (dev)"\nkiso = "{kiso_pin}"\n')
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
