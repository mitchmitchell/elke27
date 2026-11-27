"""Freeze swallowed exceptions and catch-alls per file (ELK203).

Counts two forms in ``src``, ``test`` and ``devtools``:

- every ``contextlib.suppress(...)`` call, whatever it suppresses (a narrow
  ``suppress(OSError)`` drops the error just like ``except OSError: pass``, which
  ruff SIM105 rewrites into it), including aliased imports and starred arguments;
- an ``except`` clause whose body only passes, returns nothing, continues or is
  ``...`` (the error is dropped without a trace).

The count per file must equal ``CATCH_CEILING``: a file above its entry (or a file
not listed) fails, and so does a file below it until the entry is lowered. Entries
only go down (``devtools/ratchet.py`` enforces that). Handle the error, narrow the
except to the state that can really happen and record it, or let it propagate.

One site that must stay needs ``# noqa: ELK203 -- <reason> (expires YYYY-MM-DD,
approved by <Name>)`` on its ``except`` or ``suppress`` line (see
``devtools/allow.py``); it is then not counted.

Usage: ``python devtools/catchcheck.py [--root DIR] [--baseline DIR]``. With
``--baseline`` the counts of that tree are the ceiling (to replay the check on a past
change against the tree it branched from). Prints ``path:line ELK203
message`` for each site in a file whose count is off, and exits 1 when any is.
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import sys
from collections.abc import Sequence
from pathlib import Path

import allow

CODE = "ELK203"
DESCRIPTION = "Freeze swallowed exceptions and catch-alls per file."
ROOT = Path(__file__).resolve().parent.parent
SCAN = ("src", "test", "devtools")
SKIP = ("test/fixtures/",)
BROAD = {"Exception", "BaseException"}

CATCH_CEILING: dict[str, int] = {
    "devtools/ratchet.py": 2,
    "src/elke27_lib/client.py": 26,
    "src/elke27_lib/discovery.py": 1,
    "src/elke27_lib/dispatcher_loop.py": 1,
    "src/elke27_lib/handlers/area.py": 1,
    "src/elke27_lib/handlers/network_param.py": 1,
    "src/elke27_lib/handlers/zone.py": 1,
    "src/elke27_lib/hello_thread.py": 3,
    "src/elke27_lib/kernel_loop.py": 13,
    "src/elke27_lib/linking_thread.py": 4,
    "src/elke27_lib/outbound_loop.py": 1,
    "src/elke27_lib/session_thread.py": 11,
    "test/conftest.py": 1,
    "test/helpers/fake_kernel_dispatch.py": 1,
    "test/helpers/panel_simulator.py": 8,
    "test/helpers/redaction.py": 1,
    "test/test_e27_link_raw_buffers.py": 1,
    "test/test_live_e27_home_assistant_contract.py": 1,
    "test/test_live_e27_system_status.py": 2,
    "test/test_security_round1.py": 5,
    "test/test_session_io_tstat_regression.py": 2,
}


def _swallows(body: list[ast.stmt]) -> bool:
    for stmt in body:
        if isinstance(stmt, ast.Pass | ast.Continue):
            continue
        if isinstance(stmt, ast.Return) and (
            stmt.value is None
            or (isinstance(stmt.value, ast.Constant) and stmt.value.value is None)
        ):
            continue
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
            continue
        return False
    return True


def _suppress_names(tree: ast.Module) -> set[str]:
    names = {"suppress"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "contextlib":
            names |= {a.asname for a in node.names if a.name == "suppress" and a.asname}
    return names


def _suppress_call(call: ast.Call, names: set[str]) -> bool:
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr == "suppress"
    return isinstance(func, ast.Name) and func.id in names


def _broad(call: ast.Call) -> bool:
    return any(
        (isinstance(arg, ast.Name) and arg.id in BROAD)
        or (isinstance(arg, ast.Attribute) and arg.attr in BROAD)
        for arg in call.args
    )


def sites(source: str, today: dt.date) -> list[tuple[int, str]]:
    """``(line, description)`` for each counted site in one file."""
    tree = ast.parse(source)
    markers = allow.line_markers(source.splitlines(), today)
    suppress_names = _suppress_names(tree)
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and _swallows(node.body):
            caught = ast.unparse(node.type) if node.type is not None else "everything"
            found.append((node.lineno, f"except {caught} swallows the error"))
        elif isinstance(node, ast.Call) and _suppress_call(node, suppress_names):
            effect = "hides every error" if _broad(node) else "swallows the error"
            found.append((node.lineno, f"{ast.unparse(node)} {effect}"))
    kept: list[tuple[int, str]] = []
    for line, text in sorted(found):
        skip, problem = allow.verdict(markers, line, CODE)
        if not skip:
            kept.append((line, f"{text} ({problem})" if problem else text))
    return kept


def scan(root: Path, today: dt.date) -> dict[str, list[tuple[int, str]]]:
    """Counted sites by repo-relative path."""
    found: dict[str, list[tuple[int, str]]] = {}
    for base in SCAN:
        for path in sorted((root / base).rglob("*.py")):
            rel = path.relative_to(root).as_posix()
            if rel.startswith(SKIP):
                continue
            if hits := sites(path.read_text(encoding="utf-8"), today):
                found[rel] = hits
    return found


def findings(found: dict[str, list[tuple[int, str]]], ceiling: dict[str, int]) -> list[str]:
    """Rendered findings for every file whose count differs from its ceiling."""
    out: list[str] = []
    for rel in sorted(found.keys() | ceiling.keys()):
        hits = found.get(rel, [])
        limit = ceiling.get(rel, 0)
        if len(hits) > limit:
            out += [
                f"{rel}:{line} {CODE} {text} ({len(hits)} sites, ceiling {limit})"
                for line, text in hits
            ]
        elif len(hits) < limit:
            out.append(
                f"{rel}:1 {CODE} count fell to {len(hits)}; lower CATCH_CEILING from {limit}"
            )
    return out


def main(argv: Sequence[str] | None = None) -> int:
    """Run the check; see the module docstring."""
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--counts", action="store_true", help="print current counts and exit")
    parser.add_argument(
        "--baseline", type=Path, help="use the counts of this tree as the ceiling instead"
    )
    args = parser.parse_args(argv)
    today = dt.date.today()
    found = scan(args.root.resolve(), today)
    if args.counts:
        for rel, hits in sorted(found.items()):
            print(f'    "{rel}": {len(hits)},')
        return 0
    ceiling = CATCH_CEILING
    if args.baseline is not None:
        ceiling = {rel: len(hits) for rel, hits in scan(args.baseline.resolve(), today).items()}
    out = findings(found, ceiling)
    for line in out:
        print(line)
    print(f"catchcheck: {len(out)} finding(s)")
    return 1 if out else 0


if __name__ == "__main__":
    sys.exit(main())
