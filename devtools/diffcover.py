"""Run the tests with branch coverage and fail on changed library lines that never run (ELK205).

Every line a change adds or edits under ``src/`` must be executed by the suite, and
every branch out of it must be taken. A caller-less method, a branch no test takes
or a new module the suite never imports fails here instead of in review.

Steps: run ``pytest`` with ``--cov=src --cov-branch`` (extra pytest arguments go
after ``--``), read the JSON report, take the lines changed since the base revision
(``git diff -U0 BASE -- src``; the base defaults to ``git merge-base origin/main
HEAD``), and report each changed line that coverage lists as missing or as the
source of a missing branch. A function no test runs whose name was called on a line
the change removed (its tested caller went away) is a finding too.

A changed line excluded with ``# pragma: no cover`` must give the reason in the
exception form ``# pragma: no cover -- <reason of three or more words> (expires
YYYY-MM-DD, approved by <Name>)`` with a listed approver (see
``devtools/allow.py``); a bare pragma on a changed line is a finding.

Usage: ``python devtools/diffcover.py [--base REV] [--root DIR] [--coverage-json FILE]
[-- PYTEST ARGS]``. ``--coverage-json`` skips the test run and reads an existing report. Exits
with pytest's status when the tests fail, 1 on a finding, 2 on a git error.
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import json
import re
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

import allow

CODE = "ELK205"
DESCRIPTION = "Fail on changed library lines that the test suite never runs."
ROOT = Path(__file__).resolve().parent.parent
SRC = "src/"
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
_PRAGMA = re.compile(r"#\s*pragma:\s*no\s*cover\b(?P<rest>.*)$", re.IGNORECASE)


class GitError(RuntimeError):
    """A git command failed."""


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout


def changed_lines(diff: str) -> dict[str, set[int]]:
    """Added or edited line numbers (new side) per ``src/`` Python file in a unified diff."""
    changed: dict[str, set[int]] = {}
    current: str | None = None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            name = line[4:].strip()
            name = name[2:] if name.startswith("b/") else name
            current = name if name.startswith(SRC) and name.endswith(".py") else None
        elif current is not None and (match := _HUNK.match(line)):
            start, count = int(match.group(1)), int(match.group(2) or "1")
            changed.setdefault(current, set()).update(range(start, start + count))
    return changed


_CALL = re.compile(r"\b([A-Za-z_]\w*)\s*\(")


def removed_calls(diff: str) -> dict[str, set[str]]:
    """Names called on removed lines, per ``src/`` Python file (new-side path)."""
    calls: dict[str, set[str]] = {}
    current: str | None = None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            name = line[4:].strip()
            name = name[2:] if name.startswith("b/") else name
            current = name if name.startswith(SRC) and name.endswith(".py") else None
        elif current is not None and line.startswith("-") and not line.startswith("---"):
            calls.setdefault(current, set()).update(_CALL.findall(line[1:]))
    return calls


def orphaned_functions(source: str, missing: set[int], called: set[str]) -> list[tuple[int, str]]:
    """Functions no test runs whose name was called on a line this change removed."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) or node.name not in called:
            continue
        body = [
            n.lineno
            for n in node.body
            if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))
        ]
        if body and all(line in missing for line in body):
            found.append((node.lineno, node.name))
    return found


def pragma_problem(line: str, today: dt.date) -> str | None:
    """Why a ``pragma: no cover`` on a changed line is not an accepted exception."""
    match = _PRAGMA.search(line)
    if match is None:
        return None
    marker = allow.parse(f"# noqa: ELK205 {match.group('rest').strip()}", today)
    if marker is None or marker.problem is None:
        return None
    return f"pragma: no cover {marker.problem}"


def findings(
    report: dict[str, object],
    changed: dict[str, set[int]],
    sources: dict[str, list[str]],
    today: dt.date,
    removed: dict[str, set[str]] | None = None,
) -> list[str]:
    """Rendered findings for changed lines that never ran or left a branch untaken."""
    files = report.get("files")
    files = files if isinstance(files, dict) else {}
    out: list[str] = []
    for path in sorted(changed):
        lines = changed[path]
        text = sources.get(path, [])
        for number in sorted(lines):
            if 0 < number <= len(text) and (problem := pragma_problem(text[number - 1], today)):
                out.append(f"{path}:{number} {CODE} {problem}")
        entry = files.get(path)
        if not isinstance(entry, dict):
            if any(t.strip() and not t.strip().startswith("#") for t in text):
                out.append(f"{path}:1 {CODE} changed module is not measured; no test imports it")
            continue
        missing = set(entry.get("missing_lines", []))
        for number, name in orphaned_functions(
            "\n".join(text), missing, (removed or {}).get(path, set())
        ):
            out.append(
                f"{path}:{number} {CODE} {name}() lost its tested caller in this change; delete or test it"
            )
        for number in sorted(lines & missing):
            out.append(f"{path}:{number} {CODE} changed line never runs under the test suite")
        for source, target in entry.get("missing_branches", []):
            if (
                source in lines
                and source not in missing
                and not (target in lines and target in missing)
            ):
                where = "the exit" if target < 0 else f"line {target}"
                out.append(f"{path}:{source} {CODE} branch to {where} is never taken")
    return out


def _run_tests(root: Path, report: Path, pytest_args: list[str]) -> int:
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "--cov=src",
        "--cov-branch",
        f"--cov-report=json:{report}",
        "--cov-report=term:skip-covered",
        *pytest_args,
    ]
    return subprocess.run(cmd, cwd=root, check=False).returncode


def main(argv: Sequence[str] | None = None, root: Path = ROOT) -> int:
    """Run the check; see the module docstring."""
    args_in = list(sys.argv[1:] if argv is None else argv)
    pytest_args: list[str] = []
    if "--" in args_in:
        split = args_in.index("--")
        args_in, pytest_args = args_in[:split], args_in[split + 1 :]
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument("--base", help="base revision (default: merge-base origin/main HEAD)")
    parser.add_argument("--coverage-json", type=Path, help="read this report; skip the tests")
    parser.add_argument("--root", type=Path, help="repository to check (default: this one)")
    args = parser.parse_args(args_in)
    root = (args.root or root).resolve()
    try:
        base = args.base or _git(root, "merge-base", "origin/main", "HEAD").strip()
        diff = _git(root, "diff", "-U0", "--no-color", base, "--", "src")
    except GitError as error:
        print(f"diffcover: {error}", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory() as tmp:
        report_path = args.coverage_json or Path(tmp) / "coverage.json"
        if args.coverage_json is None and (status := _run_tests(root, report_path, pytest_args)):
            return status
        report = json.loads(report_path.read_text(encoding="utf-8"))
    changed = changed_lines(diff)
    removed = removed_calls(diff)
    changed.update({path: changed.get(path, set()) for path in removed})
    sources = {
        path: (root / path).read_text(encoding="utf-8").splitlines()
        for path in changed
        if (root / path).is_file()
    }
    out = findings(report, changed, sources, dt.date.today(), removed)
    for line in out:
        print(line)
    total = sum(len(v) for v in changed.values())
    print(f"diffcover: {len(out)} finding(s) in {total} changed src line(s) since {base[:12]}")
    return 1 if out else 0


if __name__ == "__main__":
    sys.exit(main())
