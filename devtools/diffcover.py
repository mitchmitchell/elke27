"""Run the tests with branch coverage and fail on changed library lines that never run (ELK205).

Every line a change adds or edits under ``src/`` must be executed by the suite, and
every branch out of it must be taken. A caller-less method, a branch no test takes
or a new module the suite never imports fails here instead of in review.

Steps: run ``pytest`` with ``--cov=src --cov-branch`` (extra pytest arguments go
after ``--``), read the JSON report, and take the lines changed since the base revision
(``git diff -U0 BASE -- src``; the base defaults to ``git merge-base origin/main
HEAD``). Coverage records a statement and a branch source on the statement's first
line, so each changed line is first mapped to the first line of its statement with
coverage's own parser; an edit on a continuation line of a multi-line statement or a
wrapped condition is checked like an edit on its first line. Then report:

- a changed statement coverage lists as missing;
- a branch out of a changed statement that is never taken;
- a changed module the suite never imports;
- a function in any measured ``src/`` module that no test runs, when the change
  removed a call to that name from any ``src/`` file (deleted files included). The
  check knows only the name, not whether the removed caller itself was tested.

Exclusions follow coverage's own config (``report:exclude_lines`` and
``report:partial_branches``, read through ``coverage.Coverage().config``), never a
copy of its patterns:

- every changed line in the report's ``excluded_lines`` is traced, with coverage's
  own parser run once per matched line of each exclusion pattern, to every line
  whose excluded block holds it (so coverage's block rules, ``except``, ``else:``
  and ``finally:`` included, apply unchanged), and every changed line matching a
  partial-branch pattern (``# pragma: no branch``) is checked on its own line. Each
  such line must carry the exception form
  right after the pragma: ``# pragma: no cover -- <reason of three or more words>
  (expires YYYY-MM-DD, approved by <Name>)`` with a listed approver (see
  ``devtools/allow.py``), whether or not the pragma line itself changed. So the
  no-colon spelling, ``no coverage`` and a pragma on an unchanged enclosing ``def``
  all need it;
- decision: the two default exclusions for code that never runs by design,
  ``if TYPE_CHECKING:`` blocks and ``...`` stub bodies (protocols, overloads), are
  accepted without a marker. basedpyright checks that code, and running it in a test
  proves nothing.

Blank and comment-only lines are skipped.

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
from dataclasses import dataclass
from pathlib import Path

import allow

CODE = "ELK205"
DESCRIPTION = "Fail on changed library lines that the test suite never runs."
ROOT = Path(__file__).resolve().parent.parent
SRC = "src/"
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


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


def removed_calls(diff: str) -> set[str]:
    """Names called on removed lines of any ``src/`` Python file, deleted files included.

    The file is taken from the ``---`` (old) side, so a removed line counts even when the
    whole file was deleted (``+++ /dev/null``).
    """
    calls: set[str] = set()
    current: str | None = None
    for line in diff.splitlines():
        if line.startswith("--- "):
            name = line[4:].strip()
            name = name[2:] if name.startswith("a/") else name
            current = name if name.startswith(SRC) and name.endswith(".py") else None
        elif line.startswith("+++ "):
            continue
        elif current is not None and line.startswith("-"):
            calls.update(_CALL.findall(line[1:]))
    return calls


def orphaned_functions(source: str, missing: set[int], called: set[str]) -> list[tuple[int, str]]:
    """Functions no test runs whose name was called on a line this change removed."""
    tree = ast.parse(source)
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


@dataclass(frozen=True)
class Rules:
    """Coverage's exclusion and partial-branch patterns, and the ones accepted as is."""

    exclude: tuple[str, ...]
    partial: tuple[str, ...]
    exempt: frozenset[str]


def coverage_rules(config_file: Path | None = None) -> Rules:
    """``report:exclude_lines`` and ``report:partial_branches`` from coverage's own config.

    The two default exclusions for code that never runs by design, ``if TYPE_CHECKING:``
    blocks and ``...`` stub bodies, are exempt; every other pattern needs the exception
    form on the line it matches.
    """
    import coverage
    from coverage.config import DEFAULT_EXCLUDE

    path = str(config_file) if config_file is not None and config_file.is_file() else False
    config = coverage.Coverage(data_file=None, config_file=path).config
    exempt = frozenset(p for p in DEFAULT_EXCLUDE if "TYPE_CHECKING" in p or "\\.\\.\\." in p)
    return Rules(tuple(config.exclude_list), tuple(config.partial_list), exempt)


def pragma_problem(line: str, pattern: str, today: dt.date) -> str | None:
    """Why the coverage pattern on ``line`` lacks the exception form (``None`` if it has it).

    The exception text must follow the matched pragma directly: ``-- <reason of three
    or more words> (expires YYYY-MM-DD, approved by <Name>)``.
    """
    match = re.search(pattern, line)
    assert match is not None
    marker = allow.parse(f"# noqa: {CODE} {line[match.end() :].strip()}", today)
    assert marker is not None
    if marker.problem is None:
        return None
    return f"{line[match.start() : match.end()].strip()} {marker.problem}"


def _excluded_by(text: list[str], pattern: str) -> dict[int, set[int]]:
    """Each line ``pattern`` matches, mapped to the lines coverage excludes for it alone.

    Coverage's parser is run once more per matched line with matching narrowed to that
    line, so the block it excludes (a ``def``, ``if``, ``except``, ``else:`` or
    ``finally:`` clause, a decorated function) is coverage's own, not a rebuilt rule.
    """
    from coverage.parser import PythonParser

    class _OneMatch(PythonParser):
        def __init__(self, source: str, only: int | None) -> None:
            self.only = only
            super().__init__(text=source, exclude=pattern)

        def lines_matching(self, regex: str) -> set[int]:
            found = super().lines_matching(regex)
            return found if self.only is None else found & {self.only}

    source = "\n".join(text)
    every = _OneMatch(source, None)
    every.parse_source()
    blocks: dict[int, set[int]] = {}
    for line in sorted(every.raw_excluded):
        parser = _OneMatch(source, line)
        parser.parse_source()
        blocks[line] = set(parser.excluded)
    return blocks


def exclusion_problem(
    exclusions: dict[str, dict[int, set[int]]],
    text: list[str],
    number: int,
    rules: Rules,
    today: dt.date,
) -> str | None:
    """Why changed line ``number``, which coverage excluded, lacks an accepted reason.

    ``exclusions`` maps each exclusion pattern to the lines it matched, each with the
    block coverage excludes because of that line alone. Every matched line whose block
    holds ``number`` must be accepted: an exempt pattern is, any other needs the
    exception form on that line. So a valid exception nearby cannot cover for a bare
    pragma on an enclosing block. The nearest unaccepted line is reported.
    """
    problems: list[tuple[int, str]] = []
    covered = False
    for pattern in rules.exclude:
        for line, block in exclusions[pattern].items():
            if number not in block:
                continue
            covered = True
            if pattern in rules.exempt:
                continue
            problem = pragma_problem(text[line - 1], pattern, today)
            if problem is not None:
                problems.append((line, f"excluded on line {line}: {problem}"))
    if problems:
        return max(problems)[1]
    return None if covered else "excluded from coverage without a matching pattern"


def statement_starts(text: list[str], lines: set[int]) -> dict[int, int]:
    """Each line mapped to the first line of its statement, numbered as coverage does."""
    from coverage.parser import PythonParser

    parser = PythonParser(text="\n".join(text))
    parser.parse_source()
    return {n: parser.first_line(n) for n in lines}


def _code_line(text: list[str], number: int) -> bool:
    stripped = text[number - 1].strip() if 0 < number <= len(text) else ""
    return bool(stripped) and not stripped.startswith("#")


def findings(
    report: dict[str, object],
    changed: dict[str, set[int]],
    sources: dict[str, list[str]],
    today: dt.date,
    removed: set[str] | None = None,
    rules: Rules | None = None,
) -> list[str]:
    """Rendered findings for changed lines that never ran or left a branch untaken."""
    rules = rules or coverage_rules()
    files = report.get("files")
    files = files if isinstance(files, dict) else {}
    out: list[str] = []
    for path in sorted(changed):
        lines = changed[path]
        text = sources.get(path, [])
        entry = files.get(path)
        if not isinstance(entry, dict):
            if lines and any(_code_line(text, n) for n in range(1, len(text) + 1)):
                out.append(f"{path}:1 {CODE} changed module is not measured; no test imports it")
            continue
        starts = statement_starts(text, {n for n in lines if 0 < n <= len(text)})
        stmts = set(starts.values())
        missing = set(entry.get("missing_lines", []))
        excluded = set(entry.get("excluded_lines", []))
        changed_excluded = sorted(n for n in (lines | stmts) & excluded if _code_line(text, n))
        exclusions = {p: _excluded_by(text, p) for p in rules.exclude} if changed_excluded else {}
        for number in changed_excluded:
            if problem := exclusion_problem(exclusions, text, number, rules, today):
                out.append(f"{path}:{number} {CODE} changed line {problem}")
        for number in sorted({*lines, *stmts}):
            if not _code_line(text, number) or number in excluded:
                continue
            for pattern in rules.partial:
                if re.search(pattern, text[number - 1]) and (
                    problem := pragma_problem(text[number - 1], pattern, today)
                ):
                    out.append(f"{path}:{number} {CODE} changed line {problem}")
        for number in sorted(stmts & missing):
            out.append(f"{path}:{number} {CODE} changed line never runs under the test suite")
        for source, target in entry.get("missing_branches", []):
            if (
                source in stmts
                and source not in missing
                and not (target in stmts and target in missing)
            ):
                where = "the exit" if target < 0 else f"line {target}"
                out.append(f"{path}:{source} {CODE} branch to {where} is never taken")
    for path in sorted(files):
        entry = files[path]
        if not (path.startswith(SRC) and isinstance(entry, dict) and path in sources and removed):
            continue
        missing = set(entry.get("missing_lines", []))
        for number, name in orphaned_functions("\n".join(sources[path]), missing, removed):
            out.append(
                f"{path}:{number} {CODE} no test runs {name}() and this change removed a call"
                " to it; delete or test it"
            )
    return out


def run_tests(root: Path, report: Path, pytest_args: list[str]) -> int:
    """Run pytest with branch coverage of ``src/`` and write the JSON report; pytest's status."""
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
        if args.coverage_json is None and (status := run_tests(root, report_path, pytest_args)):
            return status
        report = json.loads(report_path.read_text(encoding="utf-8"))
    changed = changed_lines(diff)
    removed = removed_calls(diff)
    files = report.get("files")
    measured = (
        [p for p in files if isinstance(p, str) and p.startswith(SRC)]
        if isinstance(files, dict)
        else []
    )
    sources = {
        path: (root / path).read_text(encoding="utf-8").splitlines()
        for path in {*changed, *measured}
        if (root / path).is_file()
    }
    rules = coverage_rules(root / "pyproject.toml")
    out = findings(report, changed, sources, dt.date.today(), removed, rules)
    for line in out:
        print(line)
    total = sum(len(v) for v in changed.values())
    print(f"diffcover: {len(out)} finding(s) in {total} changed src line(s) since {base[:12]}")
    return 1 if out else 0


if __name__ == "__main__":
    sys.exit(main())
