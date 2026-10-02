"""The kiso command:

    kiso bundle             copy Kiso into the add-on (<package>/_kiso/)
    kiso build              bundle, then build dist/<folder>-<version>.ankiaddon
    kiso sync [--watch]     bundle, then copy into Anki's add-ons folder for live reload
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import build, bundle, project, sync


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="kiso", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("bundle", help="copy Kiso into the add-on")
    sub.add_parser("build", help="build the .ankiaddon")
    s = sub.add_parser("sync", help="copy into Anki's add-ons folder")
    s.add_argument("--dest", type=Path, help="the installed add-on folder (default: found automatically)")
    s.add_argument("--watch", action="store_true", help="stay running and sync on every change")
    args = parser.parse_args(argv)
    proj = project.find()
    if args.command == "bundle":
        if not bundle.bundle(proj):
            print(f"Kiso is up to date in {proj.bundle_dir.relative_to(proj.root)}")
    elif args.command == "build":
        out = build.build(proj)
        print(f"{out.relative_to(proj.root)} ({out.stat().st_size // 1024} KiB)")
    elif args.command == "sync":
        dest = args.dest or sync.default_dest(proj)
        if dest is None:
            sys.exit("No Anki add-ons folder found; pass --dest or set KISO_ADDON_DIR.")
        first = not (dest / proj.package).exists()
        sync.sync(proj, dest)
        print(f"Synced to {dest}.")
        print("Restart Anki to load it." if first else
              "A running Anki reloads it within a few seconds (changes to the root __init__.py need a restart).")
        if args.watch:
            print("Watching for changes (Ctrl+C to stop)")
            sync.watch(proj, dest)


if __name__ == "__main__":
    main()
