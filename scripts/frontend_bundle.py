# -*- coding: utf-8 -*-
"""Assemble the ordered frontend source fragments into template.html.

This is a source-layout refactor, not a runtime module system. All app fragments
are concatenated into the original single top-level scope so the existing
offline single-file build and first-card behavior remain unchanged.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "software" / "src"
SHELL = SRC / "shell.html"
STYLES = SRC / "styles.css"
MANIFEST = SRC / "app.manifest.json"
TARGET = ROOT / "software" / "template.html"


def manifest_files() -> list[Path]:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if payload.get("version") != 1:
        raise RuntimeError("unsupported frontend source manifest version")
    names = payload.get("files")
    if not isinstance(names, list) or not names or len(names) != len(set(names)):
        raise RuntimeError("frontend source manifest must contain unique ordered files")
    paths = []
    for name in names:
        if not isinstance(name, str) or not name.endswith(".js") or "/" in name or "\\" in name:
            raise RuntimeError("invalid frontend source fragment: %r" % (name,))
        path = SRC / "app" / name
        if not path.is_file():
            raise RuntimeError("missing frontend source fragment: %s" % path.relative_to(ROOT))
        paths.append(path)
    return paths


def assemble_template() -> str:
    shell = SHELL.read_text(encoding="utf-8")
    styles = STYLES.read_text(encoding="utf-8")
    parts = [path.read_text(encoding="utf-8") for path in manifest_files()]
    app = "".join(parts)
    if shell.count("__KY_STYLES__") != 1 or shell.count("__KY_APP__") != 1:
        raise RuntimeError("shell.html must contain exactly one __KY_STYLES__ and __KY_APP__")
    if "</script>" in app:
        raise RuntimeError("frontend source contains a premature </script> sequence")
    if re.search(r"^\s*(?:import|export)\s", app, re.MULTILINE):
        raise RuntimeError("frontend fragments must share one classic top-level script")
    return shell.replace("__KY_STYLES__", styles, 1).replace("__KY_APP__", app, 1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="write software/template.html")
    parser.add_argument("--check", action="store_true", help="fail if template.html is stale")
    args = parser.parse_args(argv)
    assembled = assemble_template()
    if args.write:
        TARGET.write_text(assembled, encoding="utf-8", newline="\n")
        print("wrote", TARGET.relative_to(ROOT))
        return 0
    if args.check:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current != assembled:
            print("template.html is stale; run python scripts/frontend_bundle.py --write", file=sys.stderr)
            return 1
        print("frontend template is up to date")
        return 0
    print("fragments=%d bytes=%d" % (len(manifest_files()), len(assembled.encode("utf-8"))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
