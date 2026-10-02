import json
import types
import zipfile

import pytest

from kiso import vendor as runtime
from kiso_dev import build, project, vendor


def make_addon(tmp_path, kiso_extra='vendor = "requirements.lock.txt"\n', pins="example==1.0\n"):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nversion = "1.2.3"\nrequires-python = ">=3.10"\n[tool.kiso]\npackage = "demo"\n'
        'root_files = ["__init__.py", "manifest.json"]\n' + kiso_extra)
    (tmp_path / "manifest.json").write_text(json.dumps({"package": "demo", "name": "Demo"}))
    (tmp_path / "__init__.py").write_text("")
    (tmp_path / "demo").mkdir()
    (tmp_path / "demo" / "__init__.py").write_text("")
    (tmp_path / "requirements.lock.txt").write_text("# pinned\n" + pins)
    return project.find(tmp_path)


def wheel(cache, name="example", version="1.0", tag="py3-none-any", files=None):
    cache.mkdir(exist_ok=True)
    path = cache / f"{name}-{version}-{tag}.whl"
    with zipfile.ZipFile(path, "w") as zf:
        for member, content in (files or {
            f"{name}.py": "VERSION = '1.0'\n",
            f"{name}-{version}.dist-info/METADATA": "metadata",
            f"{name}-{version}.dist-info/RECORD": "record",
            f"{name}-{version}.dist-info/LICENSE": "licence text",
            f"{name}-{version}.dist-info/licenses/third-party.txt": "third party",
            f"{name}-{version}.data/purelib/extra.py": "# purelib\n",
        }).items():
            zf.writestr(member, content)
    return path


def test_the_vendor_settings_come_from_pyproject(tmp_path):
    proj = make_addon(tmp_path)
    assert (proj.vendor, proj.vendor_python) == ("requirements.lock.txt", "3.10")   # requires-python's floor
    assert proj.vendor_dir == tmp_path / "lib" / "shared" and proj.include_dirs == [tmp_path / "lib"]


def test_vendoring_unpacks_the_pinned_wheels_with_their_licences(tmp_path):
    proj = make_addon(tmp_path)
    wheel(proj.wheel_cache)
    wheel(proj.wheel_cache, version="0.9")   # a stale version in the cache is ignored
    vendor.vendor(proj, offline=True)
    shared = proj.vendor_dir
    assert (shared / "example.py").is_file() and (shared / "extra.py").is_file()
    assert (shared / "example-1.0.dist-info" / "LICENSE").read_text() == "licence text"
    assert (shared / "example-1.0.dist-info" / "licenses" / "third-party.txt").is_file()
    assert not (shared / "example-1.0.dist-info" / "METADATA").exists()
    [entry] = json.loads(proj.vendor_manifest.read_text())
    assert (entry["name"], entry["version"], entry["wheel"]) == ("example", "1.0", "example-1.0-py3-none-any.whl")
    assert vendor.current(proj) and not vendor.ensure(proj)   # nothing to do until the lockfile changes
    (tmp_path / "requirements.lock.txt").write_text("example==0.9\n")
    assert not vendor.current(proj)


def test_only_pure_wheels_and_exact_pins_are_vendored(tmp_path):
    proj = make_addon(tmp_path)
    wheel(proj.wheel_cache, tag="cp310-cp310-win_amd64")
    with pytest.raises(SystemExit, match="No cached wheel|isn't a pure-Python wheel"):
        vendor.vendor(proj, offline=True)
    (proj.wheel_cache / "example-1.0-cp310-cp310-win_amd64.whl").unlink()
    wheel(proj.wheel_cache, files={"example/_speedups.so": "binary", "example/__init__.py": ""})
    with pytest.raises(SystemExit, match="Compiled files"):
        vendor.vendor(proj, offline=True)
    (tmp_path / "requirements.lock.txt").write_text("example>=1.0\n")
    with pytest.raises(SystemExit, match="not an exact pin"):
        vendor.vendor(proj, offline=True)


def test_a_vendoring_build_ships_lib_and_its_manifest(tmp_path):
    proj = make_addon(tmp_path)
    wheel(proj.wheel_cache)
    names = zipfile.ZipFile(build.build(proj, offline=True)).namelist()
    assert {"lib/shared/example.py", "lib/vendor_manifest.json", "demo/_kiso/vendor.py"} <= set(names)


def test_no_build_ships_compiled_files(tmp_path):
    proj = make_addon(tmp_path, kiso_extra="")
    (tmp_path / "demo" / "_native.pyd").write_bytes(b"binary")
    with pytest.raises(SystemExit, match="_native.pyd"):
        build.build(proj)


# -- at run time -------------------------------------------------------------


@pytest.fixture()
def world(tmp_path):
    shared = tmp_path / "addon" / "lib" / "shared"
    for pkg, version in (("pydantic", "1.10.22"), ("fastapi", "0.125.0"), ("attrs", "25.1.0")):
        (shared / pkg).mkdir(parents=True)
        (shared / f"{pkg}-{version}.dist-info").mkdir()
    addons, anki = tmp_path / "addons21", tmp_path / "anki_bundle"

    def module(where, version):
        m = types.ModuleType("m")
        m.__file__ = str(where / "__init__.py")
        m.__version__ = version
        return m
    return shared, addons, anki, module


def test_add_to_path_puts_lib_shared_first(world, monkeypatch):
    shared, *_ = world
    monkeypatch.setattr("sys.path", ["elsewhere"])
    assert runtime.add_to_path(shared.parent.parent) == shared
    import sys
    assert sys.path[0] == str(shared)


def test_a_critical_library_at_another_version_blocks(world):
    shared, addons, anki, module = world
    modules = {"pydantic": module(addons / "1234" / "vendor" / "pydantic", "2.9.0")}
    [clash] = runtime.find_clashes(shared, ["pydantic"], [str(anki)], modules)
    assert (clash.name, clash.version, clash.bundled, clash.blocks) == ("pydantic", "2.9.0", "1.10.22", True)


def test_same_versions_other_libraries_and_ankis_own_copies_do_not_block(world):
    shared, addons, anki, module = world
    modules = {
        "fastapi": module(addons / "1234" / "fastapi", "0.125.0"),   # same version: works
        "attrs": module(addons / "1234" / "attrs", "21.0.0"),        # not critical
        "pydantic": module(anki / "pydantic", "2.9.0"),              # Anki's own package
    }
    clashes = runtime.find_clashes(shared, ["fastapi", "pydantic"], [str(anki)], modules)
    assert {c.name for c in clashes} == {"fastapi", "attrs"} and not any(c.blocks for c in clashes)
    assert runtime.find_clashes(shared, [], [str(anki)], {"pydantic": module(shared / "pydantic", "1.10.22")}) == []


def test_the_refusal_names_the_add_on(world, tmp_path):
    _, addons, _, _ = world
    file = str(addons / "1234" / "vendor" / "pydantic" / "__init__.py")
    assert runtime.addon_folder(file, str(addons)) == "1234"
    assert runtime.addon_folder(str(tmp_path / "elsewhere.py"), str(addons)) is None
    message = runtime.refusal("Demo", [runtime.Clash("pydantic", file, "2.9.0", "1.10.22", True)],
                              lambda f: "Other Add-on")
    assert message.startswith("Demo did not start")
    assert "pydantic (version 2.9.0, from the add-on “Other Add-on”; Demo needs 1.10.22)" in message
