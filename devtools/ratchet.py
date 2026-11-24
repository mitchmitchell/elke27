"""Fail when a ceiling or allowlist grows against the base branch (ELK201).

Ceilings and allowlists may only go down. This check reads every ratchet table at
the base revision and in the working tree (or ``--head REV``) and reports each
table entry that was added or raised:

- module-level ``*_CEILING``, ``LEGACY_*`` and ``FROZEN_*`` assignments in Python
  files under ``test/`` and ``devtools/`` (dicts of counts, dicts of code lists,
  and sets, lists, tuples or ``frozenset``/``set`` calls of names);
- every ruff suppression key (``ignore``, ``extend-ignore``, ``per-file-ignores``,
  ``extend-per-file-ignores``, ``exclude``, ``extend-exclude``, ``external``,
  flake8-self ``ignore-names``/``extend-ignore-names``, in the ``lint`` section and
  the legacy top-level spelling) in ``pyproject.toml``, ``ruff.toml`` and
  ``.ruff.toml``; a key absent at the base counts as empty;
- ruff ``select``/``extend-select``, where dropping a rule is the growth, and ruff
  ``include``, where setting it or dropping an entry is the growth;
- every table of counts under ``[tool.elke27]`` whose key ends in ``ceiling`` (a
  value that is not an integer is a finding), every list whose key ends in
  ``exclude``, and every list ending in ``_modules`` or ``_paths`` (what a check
  covers; dropping an entry is the growth);
- inline ``noqa`` directives naming ``SLF001`` in ``src/``, counted per file.

Tables are matched by file and name, so a same-named table elsewhere cannot stand
in for the real one. A table that disappears is reported too. Replacing a glob
entry of a code-list table with exact paths it matched, each with a subset of its
codes, narrows the table and is allowed. A new Python table is allowed (it starts a
new ceiling).

An entry that must grow needs ``# noqa: ELK201 -- <reason> (expires YYYY-MM-DD,
approved by <Name>)`` on its line (see ``devtools/allow.py``). Every ELK201 marker in
a file that holds a ratchet table is re-validated on each run, grown or not, so an
expired or unapproved marker on an unchanged line fails.

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
RUFF_FILES = (("pyproject.toml", ("tool", "ruff")), ("ruff.toml", ()), (".ruff.toml", ()))
RUFF_SUPPRESSIONS = (
    ("ignore",),
    ("extend-ignore",),
    ("per-file-ignores",),
    ("extend-per-file-ignores",),
    ("exclude",),
    ("extend-exclude",),
    ("external",),
    ("lint", "ignore"),
    ("lint", "extend-ignore"),
    ("lint", "per-file-ignores"),
    ("lint", "extend-per-file-ignores"),
    ("lint", "exclude"),
    ("lint", "external"),
    ("format", "exclude"),
    ("flake8-self", "ignore-names"),
    ("flake8-self", "extend-ignore-names"),
    ("lint", "flake8-self", "ignore-names"),
    ("lint", "flake8-self", "extend-ignore-names"),
)
RUFF_SCOPES = (("include",),)
SRC = "src/"
INLINE_NOQA = re.compile(r"#\s*noqa:[^#]*\bSLF001\b")
INLINE_TABLE = "inline noqa: SLF001 per src file"
RUFF_SELECTIONS = (
    ("select",),
    ("extend-select",),
    ("lint", "select"),
    ("lint", "extend-select"),
)

Value = int | frozenset[str] | None


@dataclass(frozen=True)
class Table:
    """One ratchet table: entry -> count, code set, or ``None`` for set members."""

    path: str
    name: str
    entries: dict[str, Value]
    lines: dict[str, int]
    problems: tuple[tuple[int, str], ...] = ()


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


MUTATORS = {
    "add",
    "update",
    "append",
    "extend",
    "insert",
    "setdefault",
    "__setitem__",
    "__ior__",
    "union",
    "difference_update",
    "intersection_update",
    "symmetric_difference_update",
}


def _table_target(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name) and TABLE_NAME.match(node.id):
        return node.id
    if isinstance(node, ast.Subscript | ast.Attribute | ast.Starred):
        return _table_target(node.value)
    return None


def _writes(tree: ast.Module) -> list[tuple[str, int, str]]:
    """Every write to a table name anywhere in the module, as ``(name, line, form)``."""
    found: list[tuple[str, int, str]] = []
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign | ast.AugAssign):
            targets = [node.target]
        elif isinstance(node, ast.For | ast.AsyncFor | ast.With | ast.AsyncWith):
            targets = (
                [node.target]
                if isinstance(node, ast.For | ast.AsyncFor)
                else [item.optional_vars for item in node.items if item.optional_vars is not None]
            )
        elif isinstance(node, ast.NamedExpr):
            targets = [node.target]
        elif isinstance(node, ast.Global | ast.Nonlocal):
            found += [
                (n, node.lineno, "global rebinding") for n in node.names if TABLE_NAME.match(n)
            ]
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in MUTATORS
            and (name := _table_target(node.func.value)) is not None
        ):
            found.append((name, node.lineno, f".{node.func.attr}() call"))
        for target in targets:
            elements = target.elts if isinstance(target, ast.Tuple | ast.List) else [target]
            for element in elements:
                name = _table_target(element)
                if name is None:
                    continue
                line = element.lineno
                if isinstance(node, ast.AugAssign):
                    found.append((name, line, "augmented assignment"))
                elif isinstance(element, ast.Name):
                    found.append((name, line, "assignment"))
                else:
                    found.append((name, line, "item or attribute assignment"))
    return found


def _read_table(value: ast.expr) -> tuple[dict[str, Value], dict[str, int], list[tuple[int, str]]]:
    entries: dict[str, Value] = {}
    lines: dict[str, int] = {}
    problems: list[tuple[int, str]] = []
    if isinstance(value, ast.Dict):
        for key_node, value_node in zip(value.keys, value.values, strict=True):
            if key_node is None:
                problems.append((value_node.lineno, "** splat; must be a literal table"))
                continue
            key = _key(key_node)
            parsed = _value(value_node)
            if key is None or isinstance(parsed, str):
                problems.append(
                    (key_node.lineno, "entry is not a literal; must be a literal table")
                )
                continue
            entries[key] = parsed
            lines[key] = value_node.lineno
    elif (members := _names(value)) is not None:
        for member in members:
            key = _key(member)
            if key is None:
                problems.append((member.lineno, "member is not a literal; must be a literal table"))
                continue
            entries[key] = None
            lines[key] = member.lineno
    else:
        problems.append(
            (value.lineno, "value is not a literal dict or set; must be a literal table")
        )
    return entries, lines, problems


def python_tables(path: str, source: str) -> list[Table]:
    """Ratchet tables in one Python file; anything not readable as a literal is a problem.

    A table is one module-level assignment of a literal dict, set, list, tuple or
    ``set``/``frozenset`` call. A splat, a non-literal key or value, a second
    assignment, or any later write (``|=``, item assignment, ``.update()`` and other
    mutating calls) is recorded as a problem, which ``compare`` reports.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        return [Table(path, "<syntax>", {}, {}, ((error.lineno or 1, "file does not parse"),))]
    definitions: dict[str, ast.Assign | ast.AnnAssign] = {}
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
            target = stmt.targets[0]
        elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
            target = stmt.target
        else:
            continue
        if isinstance(target, ast.Name) and TABLE_NAME.match(target.id):
            definitions.setdefault(target.id, stmt)
    extra: dict[str, list[tuple[int, str]]] = {}
    for name, line, form in _writes(tree):
        definition = definitions.get(name)
        if definition is not None and definition.lineno == line and form == "assignment":
            continue
        extra.setdefault(name, []).append(
            (line, f"{name} changed by {form}; must be a literal table")
        )
    tables: list[Table] = []
    for name in sorted(definitions.keys() | extra.keys()):
        definition = definitions.get(name)
        entries: dict[str, Value] = {}
        lines: dict[str, int] = {}
        problems: list[tuple[int, str]] = []
        if definition is not None and definition.value is not None:
            entries, lines, problems = _read_table(definition.value)
        problems += extra.get(name, [])
        tables.append(Table(path, name, entries, lines, tuple(problems)))
    return tables


_HEADER = re.compile(r"^\s*\[+\s*(?P<name>[^\]]+?)\s*\]+")


def _toml_line(lines: list[str], keys: tuple[str, ...], entry: str) -> int:
    """Line of ``entry`` inside the section or array of ``keys`` (1 when not found)."""
    dotted = ".".join(keys)
    quoted = (f'"{entry}"', f"'{entry}'")
    start: int | None = None
    for index, line in enumerate(lines):
        header = _HEADER.match(line)
        if header is None:
            continue
        name = header.group("name").replace('"', "").replace("'", "")
        if name == dotted:
            start = index + 1
            break
        if dotted.startswith(f"{name}."):
            leaf = dotted[len(name) + 1 :]
            for inner in range(index + 1, len(lines)):
                if _HEADER.match(lines[inner]):
                    break
                if re.match(rf"^\s*{re.escape(leaf)}\s*=", lines[inner]):
                    start = inner
                    break
            if start is not None:
                break
    if start is None and len(keys) == 1:
        leaf = keys[0]
        for index, line in enumerate(lines):
            if _HEADER.match(line):
                break
            if leaf and re.match(rf"^\s*{re.escape(leaf)}\s*=", line):
                start = index
                break
    if start is None:
        return 1
    for index in range(start, len(lines)):
        if index > start and _HEADER.match(lines[index]):
            break
        if any(q in lines[index] for q in quoted):
            return index + 1
    return start + 1


def _lookup(config: dict[str, object], keys: tuple[str, ...]) -> object:
    node: object = config
    for key in keys:
        node = node.get(key) if isinstance(node, dict) else None
    return node


def _entries(node: object) -> dict[str, Value]:
    if isinstance(node, dict):
        return {
            str(path): frozenset(str(c) for c in codes)
            for path, codes in node.items()
            if isinstance(codes, list)
        }
    if isinstance(node, list):
        return {str(item): None for item in node}
    return {}


def toml_tables(
    source: str, path: str = PYPROJECT, prefix: tuple[str, ...] = ("tool", "ruff")
) -> list[Table]:
    """Ruff suppression and selection tables plus ``[tool.elke27]`` ceilings of one file.

    Every known ruff key yields a table, empty when the key is absent, so a key that
    first appears in a change is compared against nothing and any entry is growth.
    Selection tables are named ``...!select``: for them a removed entry is growth.
    Scope tables (``include``) are named ``...!scope``: setting one where the base had
    none, or removing an entry, narrows what ruff checks and is growth.
    ``[tool.elke27]`` lists ending in ``_modules`` or ``_paths`` name what a check
    covers and are selection tables too.
    """
    config = tomllib.loads(source)
    lines = source.splitlines()
    tables: list[Table] = []
    for keys, suffix in (
        [(k, "") for k in RUFF_SUPPRESSIONS]
        + [(k, "!select") for k in RUFF_SELECTIONS]
        + [(k, "!scope") for k in RUFF_SCOPES]
    ):
        full = (*prefix, *keys)
        entries = _entries(_lookup(config, full))
        found = {key: _toml_line(lines, full, key) for key in entries}
        tables.append(Table(path, ".".join(full) + suffix, entries, found))
    if path == PYPROJECT:
        tables += _toml_ceilings(_lookup(config, ("tool", "elke27")), ("tool", "elke27"), lines)
    return tables


def _toml_ceilings(node: object, prefix: tuple[str, ...], lines: list[str]) -> list[Table]:
    if not isinstance(node, dict):
        return []
    tables: list[Table] = []
    for key, value in node.items():
        keys = (*prefix, str(key))
        name = ".".join(keys)
        if str(key).endswith("exclude") and isinstance(value, list):
            entries = _entries(value)
            found = {k: _toml_line(lines, keys, k) for k in entries}
            tables.append(Table(PYPROJECT, name, entries, found))
        elif str(key).endswith(("_modules", "_paths")) and isinstance(value, list):
            entries = _entries(value)
            found = {k: _toml_line(lines, keys, k) for k in entries}
            tables.append(Table(PYPROJECT, name + "!select", entries, found))
        elif not isinstance(value, dict):
            continue
        elif str(key).endswith("ceiling"):
            counts: dict[str, Value] = {}
            problems: list[tuple[int, str]] = []
            for k, v in value.items():
                if isinstance(v, int) and not isinstance(v, bool):
                    counts[str(k)] = v
                else:
                    line = _toml_line(lines, keys, str(k))
                    problems.append((line, f"{k!r} is not an integer count"))
            found = {k: _toml_line(lines, keys, k) for k in counts}
            tables.append(Table(PYPROJECT, name, counts, found, tuple(problems)))
        else:
            tables += _toml_ceilings(value, keys, lines)
    return tables


def tables(tree: Tree) -> dict[str, Table]:
    """Every ratchet table in a tree, keyed by ``path::name``."""
    found: dict[str, Table] = {}
    for path in tree.paths():
        if not path.endswith(".py") or not path.startswith(PY_DIRS) or path.startswith(PY_SKIP):
            continue
        source = tree.read(path)
        if source is not None:
            for table in python_tables(path, source):
                found[f"{path}::{table.name}"] = table
    inline: dict[str, Value] = {}
    inline_lines: dict[str, int] = {}
    for path in tree.paths():
        if not (path.startswith(SRC) and path.endswith(".py")):
            continue
        hits = [
            number
            for number, text in enumerate((tree.read(path) or "").splitlines(), 1)
            if INLINE_NOQA.search(text)
        ]
        if hits:
            inline[path] = len(hits)
            inline_lines[path] = hits[0]
    found[f"{SRC}::{INLINE_TABLE}"] = Table(SRC, INLINE_TABLE, inline, inline_lines)
    for path, prefix in RUFF_FILES:
        source = tree.read(path)
        if source is not None and path != PYPROJECT:
            found[f"{path}::config file"] = Table(
                path,
                "ruff config file (overrides [tool.ruff] in pyproject.toml)",
                {path: None},
                {path: 1},
            )
        try:
            parsed = toml_tables(source or "", path, prefix)
        except tomllib.TOMLDecodeError:
            parsed = [Table(path, "<toml>", {}, {}, ((1, "file does not parse"),))]
        for table in parsed:
            found[f"{path}::{table.name}"] = table
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
    """Growth findings from ``base`` to ``head`` (exceptions not applied).

    Tables are matched by ``path::name``. A Python table new at head starts a new
    ceiling; a TOML table is never new (it is compared against an empty base).
    """
    findings: list[Finding] = []
    for new in sorted(head.values(), key=lambda t: (t.path, t.name)):
        findings += [
            Finding(new.path, line, f"{new.name}: {message}") for line, message in new.problems
        ]
    for key, old in sorted(base.items()):
        if key not in head:
            findings.append(Finding(old.path, 1, f"{old.name} was removed; ceilings only shrink"))
    for key, new in sorted(head.items()):
        old = base.get(key)
        if old is None:
            if new.path.endswith(".py"):
                continue
            old = Table(new.path, new.name, {}, {})
        name = new.name
        if name.endswith("!scope"):
            if new.entries and not old.entries:
                findings.append(
                    Finding(new.path, 1, f"{name[:-6]} set; it narrows what ruff checks")
                )
            for entry in sorted(old.entries.keys() - new.entries.keys()):
                findings.append(Finding(new.path, 1, f"{name[:-6]} dropped {entry!r}"))
            continue
        if name.endswith("!select"):
            for entry in sorted(old.entries.keys() - new.entries.keys()):
                findings.append(Finding(new.path, 1, f"{name[:-7]} dropped {entry!r}"))
            continue
        for entry, value in new.entries.items():
            line = new.lines.get(entry, 1)
            if entry not in old.entries:
                if not _narrows(entry, value, old):
                    findings.append(Finding(new.path, line, f"{name} gained {entry!r}"))
                continue
            before = old.entries[entry]
            if isinstance(value, int) and isinstance(before, int) and value > before:
                findings.append(
                    Finding(new.path, line, f"{name}[{entry!r}] rose {before} -> {value}")
                )
            elif isinstance(value, frozenset) and isinstance(before, frozenset):
                if gained := sorted(value - before):
                    findings.append(Finding(new.path, line, f"{name}[{entry!r}] gained {gained}"))
            elif type(value) is not type(before):
                findings.append(Finding(new.path, line, f"{name}[{entry!r}] changed kind"))
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


def marker_findings(head: dict[str, Table], tree: Tree, today: dt.date) -> list[Finding]:
    """Every ELK201 marker in a file holding a ratchet table that ``allow`` rejects.

    Checked whether or not its line grew, so an expired or unapproved exception on an
    unchanged entry still fails.
    """
    found: list[Finding] = []
    for path in sorted({table.path for table in head.values()}):
        source = tree.read(path)
        if source is None:
            continue
        for line, marker in sorted(allow.line_markers(source.splitlines(), today).items()):
            if CODE in marker.codes and marker.problem is not None:
                found.append(Finding(path, line, f"exception marker rejected: {marker.problem}"))
    return found


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
        head_tables = tables(head)
        findings = compare(tables(Tree(root, base_rev)), head_tables)
    except GitError as error:
        print(f"ratchet: {error}", file=sys.stderr)
        return 2
    today = dt.date.today()
    findings = apply_exceptions(findings, head, today)
    reported = {(f.path, f.line) for f in findings}
    findings += [
        f for f in marker_findings(head_tables, head, today) if (f.path, f.line) not in reported
    ]
    for finding in findings:
        print(finding.render())
    print(f"ratchet: {len(findings)} finding(s) against {base_rev[:12]}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
