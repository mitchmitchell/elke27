"""Fail when a ceiling or allowlist grows against the base branch (ELK201).

Ceilings and allowlists may only go down. This check reads every ratchet table at
the base revision and in the working tree (or ``--head REV``) and reports each
table entry that was added or raised:

- module-level ``*_CEILING``, ``LEGACY_*`` and ``FROZEN_*`` assignments in Python
  files under ``test/`` and ``devtools/`` (dicts of counts, dicts of code lists,
  and sets, lists, tuples or ``frozenset``/``set`` calls of names);
- ``[tool.ruff.lint] per-file-ignores`` and ``ignore`` and ``[tool.ruff]
  extend-exclude`` in ``pyproject.toml``.

A table that disappears is reported too. Replacing a glob entry of a code-list
table with exact paths it matched, each with a subset of its codes, narrows the
table and is allowed. A new table name is allowed (it starts a new ceiling).

An entry that must grow needs ``# noqa: ELK201 -- <reason> (expires YYYY-MM-DD,
approved by <Name>)`` on its line (see ``devtools/allow.py``).

Usage: ``python devtools/ratchet.py [--base REV] [--head REV]``. The base defaults
to ``git merge-base origin/main HEAD``. Prints ``path:line ELK201 message`` per
finding and exits 1 when there is any, 2 on a usage or git error.
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import fnmatch
import re
import subprocess
import sys
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import allow

CODE = "ELK201"
DESCRIPTION = "Fail when a ceiling or allowlist grows against the base branch."
ROOT = Path(__file__).resolve().parent.parent
TABLE_NAME = re.compile(r"^(?:[A-Z0-9_]*_CEILING|LEGACY_[A-Z0-9_]+|FROZEN_[A-Z0-9_]+)$")
PY_DIRS = ("test/", "devtools/")
PY_SKIP = ("test/fixtures/",)
PYPROJECT = "pyproject.toml"
TOML_TABLES = (
    ("tool", "ruff", "lint", "per-file-ignores"),
    ("tool", "ruff", "lint", "ignore"),
    ("tool", "ruff", "extend-exclude"),
)

Value = int | frozenset[str] | None


@dataclass(frozen=True)
class Table:
    """One ratchet table: entry -> count, code set, or ``None`` for set members."""

    path: str
    name: str
    entries: dict[str, Value]
    lines: dict[str, int]


@dataclass(frozen=True)
class Finding:
    """One growth finding."""

    path: str
    line: int
    message: str

    def render(self) -> str:
        """``path:line ELK201 message``."""
        return f"{self.path}:{self.line} {CODE} {self.message}"


class Tree:
    """Read files at a git revision, or from the working tree when ``rev`` is None."""

    def __init__(self, root: Path, rev: str | None) -> None:
        self.root = root
        self.rev = rev

    def paths(self) -> list[str]:
        """Tracked paths at the revision (working tree: tracked plus untracked)."""
        if self.rev is None:
            out = _git(self.root, "ls-files", "--cached", "--others", "--exclude-standard")
        else:
            out = _git(self.root, "ls-tree", "-r", "--name-only", self.rev)
        return sorted({p for p in out.splitlines() if p})

    def read(self, path: str) -> str | None:
        """File text, or ``None`` when the file does not exist there."""
        if self.rev is None:
            file = self.root / path
            return file.read_text(encoding="utf-8") if file.is_file() else None
        try:
            return _git(self.root, "show", f"{self.rev}:{path}")
        except GitError:
            return None


class GitError(RuntimeError):
    """A git command failed."""


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout


def _names(node: ast.expr) -> list[ast.expr] | None:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        if node.func.id in {"set", "frozenset"} and len(node.args) == 1 and not node.keywords:
            return _names(node.args[0])
        return None
    if isinstance(node, ast.Set | ast.List | ast.Tuple):
        return list(node.elts)
    return None


def _value(node: ast.expr) -> Value | str:
    try:
        value = ast.literal_eval(node)
    except ValueError:
        return "unparsed"
    if isinstance(value, bool):
        return "unparsed"
    if isinstance(value, int):
        return value
    if isinstance(value, list | tuple | set | frozenset) and all(isinstance(v, str) for v in value):
        return frozenset(value)
    return "unparsed"


def _key(node: ast.expr | None) -> str | None:
    if node is None:
        return None
    try:
        key = ast.literal_eval(node)
    except ValueError:
        return None
    if isinstance(key, str):
        return key
    if isinstance(key, tuple) and all(isinstance(k, str) for k in key):
        return " | ".join(key)
    return None


def python_tables(path: str, source: str) -> list[Table]:
    """Ratchet tables assigned at module level in one Python file."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    tables: list[Table] = []
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
            target, value = stmt.targets[0], stmt.value
        elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
            target, value = stmt.target, stmt.value
        else:
            continue
        if not (isinstance(target, ast.Name) and TABLE_NAME.match(target.id)):
            continue
        entries: dict[str, Value] = {}
        lines: dict[str, int] = {}
        if isinstance(value, ast.Dict):
            for key_node, value_node in zip(value.keys, value.values, strict=True):
                key = _key(key_node)
                parsed = _value(value_node)
                if key is None or isinstance(parsed, str):
                    continue
                entries[key] = parsed
                lines[key] = value_node.lineno
        elif (members := _names(value)) is not None:
            for member in members:
                key = _key(member)
                if key is not None:
                    entries[key] = None
                    lines[key] = member.lineno
        else:
            continue
        tables.append(Table(path, target.id, entries, lines))
    return tables


def _toml_line(lines: list[str], key: str, default: int) -> int:
    quoted = (f'"{key}"', f"'{key}'")
    for number, line in enumerate(lines, start=1):
        if any(q in line for q in quoted):
            return number
    return default


def toml_tables(source: str) -> list[Table]:
    """Ruff ignore tables from ``pyproject.toml``."""
    config = tomllib.loads(source)
    lines = source.splitlines()
    tables: list[Table] = []
    for keys in TOML_TABLES:
        node: object = config
        for key in keys:
            node = node.get(key) if isinstance(node, dict) else None
        name = ".".join(keys)
        entries: dict[str, Value] = {}
        if isinstance(node, dict):
            for path, codes in node.items():
                if isinstance(path, str) and isinstance(codes, list):
                    entries[path] = frozenset(str(c) for c in codes)
        elif isinstance(node, list):
            entries = {str(item): None for item in node}
        else:
            continue
        found = {key: _toml_line(lines, key, 1) for key in entries}
        tables.append(Table(PYPROJECT, name, entries, found))
    return tables


def tables(tree: Tree) -> dict[str, Table]:
    """Every ratchet table in a tree, by table name."""
    found: dict[str, Table] = {}
    for path in tree.paths():
        if not path.endswith(".py") or not path.startswith(PY_DIRS) or path.startswith(PY_SKIP):
            continue
        source = tree.read(path)
        if source is not None:
            for table in python_tables(path, source):
                found[table.name] = table
    pyproject = tree.read(PYPROJECT)
    if pyproject is not None:
        for table in toml_tables(pyproject):
            found[table.name] = table
    return found


def _narrows(key: str, codes: Value, base: Table) -> bool:
    if not isinstance(codes, frozenset):
        return False
    return any(
        isinstance(base_codes, frozenset)
        and any(ch in base_key for ch in "*?[")
        and fnmatch.fnmatch(key, base_key)
        and codes <= base_codes
        for base_key, base_codes in base.entries.items()
    )


def compare(base: dict[str, Table], head: dict[str, Table]) -> list[Finding]:
    """Growth findings from ``base`` to ``head`` (exceptions not applied)."""
    findings: list[Finding] = []
    for name, old in sorted(base.items()):
        new = head.get(name)
        if new is None:
            findings.append(Finding(old.path, 1, f"{name} was removed; ceilings only shrink"))
            continue
        for key, value in new.entries.items():
            line = new.lines.get(key, 1)
            if key not in old.entries:
                if not _narrows(key, value, old):
                    findings.append(Finding(new.path, line, f"{name} gained {key!r}"))
                continue
            before = old.entries[key]
            if isinstance(value, int) and isinstance(before, int) and value > before:
                findings.append(
                    Finding(new.path, line, f"{name}[{key!r}] rose {before} -> {value}")
                )
            elif isinstance(value, frozenset) and isinstance(before, frozenset):
                if gained := sorted(value - before):
                    findings.append(Finding(new.path, line, f"{name}[{key!r}] gained {gained}"))
            elif type(value) is not type(before):
                findings.append(Finding(new.path, line, f"{name}[{key!r}] changed kind"))
    return findings


def apply_exceptions(findings: list[Finding], head: Tree, today: dt.date) -> list[Finding]:
    """Drop findings whose line carries a valid ELK201 exception."""
    kept: list[Finding] = []
    cache: dict[str, dict[int, allow.Marker]] = {}
    for finding in findings:
        if finding.path not in cache:
            source = head.read(finding.path) or ""
            cache[finding.path] = allow.line_markers(source.splitlines(), today)
        skip, problem = allow.verdict(cache[finding.path], finding.line, CODE)
        if skip:
            continue
        message = f"{finding.message} ({problem})" if problem else finding.message
        kept.append(Finding(finding.path, finding.line, message))
    return kept


def main(argv: Sequence[str] | None = None, root: Path = ROOT) -> int:
    """Run the check; see the module docstring."""
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument("--base", help="base revision (default: merge-base origin/main HEAD)")
    parser.add_argument("--head", help="head revision (default: the working tree)")
    args = parser.parse_args(argv)
    try:
        base_rev = args.base or _git(root, "merge-base", "origin/main", "HEAD").strip()
        base_rev = _git(root, "rev-parse", "--verify", f"{base_rev}^{{commit}}").strip()
        head = Tree(root, args.head)
        findings = compare(tables(Tree(root, base_rev)), tables(head))
    except GitError as error:
        print(f"ratchet: {error}", file=sys.stderr)
        return 2
    findings = apply_exceptions(findings, head, dt.date.today())
    for finding in findings:
        print(finding.render())
    print(f"ratchet: {len(findings)} finding(s) against {base_rev[:12]}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
