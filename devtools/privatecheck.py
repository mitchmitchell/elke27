"""Ban importing another module's private name inside the library (ELK202).

``from .redact import _should_redact`` (or ``from elke27_lib.x import _y``) couples
one module to another's internals and slips past ruff SLF001, which only sees
attribute access. A private name is one that starts with ``_`` and is not a dunder.
Importing a public name under a private alias (``import x as _x``) is fine.

An import that must stay needs ``# noqa: ELK202 -- <reason> (expires YYYY-MM-DD,
approved by <Name>)`` on the line of the imported name (or of the ``from``) (see ``devtools/allow.py``).

Usage: ``python devtools/privatecheck.py [--root DIR]``. Scans ``src/elke27_lib``
under the root, prints ``path:line ELK202 message`` per finding and exits 1 when
there is any.
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import sys
from collections.abc import Sequence
from pathlib import Path

import allow

CODE = "ELK202"
DESCRIPTION = "Ban importing another module's private name inside the library."
PACKAGE = "elke27_lib"
ROOT = Path(__file__).resolve().parent.parent


def _private(name: str) -> bool:
    return name.startswith("_") and not (name.startswith("__") and name.endswith("__"))


def findings(path: Path, source: str, rel: str, today: dt.date) -> list[str]:
    """ELK202 findings in one library module."""
    tree = ast.parse(source, filename=str(path))
    markers = allow.line_markers(source.splitlines(), today)
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        module = node.module or ""
        if not (node.level or module == PACKAGE or module.startswith(f"{PACKAGE}.")):
            continue
        for alias in node.names:
            if not _private(alias.name):
                continue
            line = alias.lineno
            skip, problem = allow.verdict(markers, line, CODE)
            if not skip and problem is None and line != node.lineno:
                skip, problem = allow.verdict(markers, node.lineno, CODE)
            if skip:
                continue
            source_module = "." * node.level + module
            message = f"imports private {alias.name} from {source_module}; make it public"
            found.append(f"{rel}:{line} {CODE} {message}" + (f" ({problem})" if problem else ""))
    return found


def main(argv: Sequence[str] | None = None) -> int:
    """Run the check; see the module docstring."""
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    root: Path = args.root.resolve()
    today = dt.date.today()
    found = [
        finding
        for path in sorted((root / "src" / PACKAGE).rglob("*.py"))
        for finding in findings(
            path, path.read_text(encoding="utf-8"), path.relative_to(root).as_posix(), today
        )
    ]
    for finding in found:
        print(finding)
    print(f"privatecheck: {len(found)} finding(s)")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
