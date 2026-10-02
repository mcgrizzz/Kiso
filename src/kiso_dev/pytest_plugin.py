"""Kiso's pytest plugin, loaded automatically wherever kiso is installed:

- Anki's printed deprecation notices are listed at the end of the run, and fail
  it with KISO_STRICT_ANKI_NOTICES=1.
- The add-on under test gets Kiso bundled into it before tests import it.
"""

from __future__ import annotations

from . import notices


def pytest_configure(config):
    try:
        import anki  # noqa: F401
    except ImportError:
        return
    notices.install()
    from .bundle import bundle
    from .project import find
    from .vendor import ensure
    try:
        project = find(config.rootpath)
    except SystemExit:
        return   # not an add-on project (Kiso's own tests)
    bundle(project, quiet=True)
    ensure(project)   # the add-on's vendored libraries, if lib/shared isn't current


def pytest_terminal_summary(terminalreporter):
    if notices.notices:
        terminalreporter.section("Anki deprecation notices")
        for notice in notices.notices:
            terminalreporter.line(notices.describe(notice))


def pytest_sessionfinish(session):
    if notices.failing() and notices.STRICT:
        session.exitstatus = 1
