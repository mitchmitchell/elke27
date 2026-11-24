"""Tests for devtools/diffcover.py (changed library lines the suite never runs)."""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent
DEVTOOLS = ROOT / "devtools"
TODAY = dt.date(2026, 11, 24)


def _load(name: str) -> ModuleType:
    """Load a devtools script by path; sys.path is restored and only devtools modules are dropped."""
    saved_path = list(sys.path)
    saved_modules = set(sys.modules)
    sys.path.insert(0, str(DEVTOOLS))
    try:
        spec = importlib.util.spec_from_file_location(f"devtools_{name}", DEVTOOLS / f"{name}.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path[:] = saved_path
        for added in set(sys.modules) - saved_modules:
            origin = getattr(sys.modules[added], "__file__", None)
            if added == f"devtools_{name}" or (origin and Path(origin).parent == DEVTOOLS):
                del sys.modules[added]


diffcover = _load("diffcover")

DIFF = """diff --git a/src/elke27_lib/mod.py b/src/elke27_lib/mod.py
--- a/src/elke27_lib/mod.py
+++ b/src/elke27_lib/mod.py
@@ -3,0 +4,2 @@ def f():
+    if x:
+        return 1
@@ -10 +12 @@ def g():
-    return helper(seq)
+    return 2
diff --git a/test/test_mod.py b/test/test_mod.py
--- a/test/test_mod.py
+++ b/test/test_mod.py
@@ -1 +1 @@
-x = 1
+x = 2
"""

SOURCE = [
    "def f():",
    "    x = 1",
    '    """doc"""',
    "    if x:",
    "        return 1",
    "    return 0",
    "",
    "def helper(seq):",
    '    """Unused now."""',
    "    return seq",
    "",
    "def g():",
    "    return 2",
]


def test_changed_lines_and_removed_calls_cover_src_only() -> None:
    assert diffcover.changed_lines(DIFF) == {"src/elke27_lib/mod.py": {4, 5, 12}}
    assert diffcover.removed_calls(DIFF) == {"helper"}


def test_findings_name_missing_lines_untaken_branches_and_orphans() -> None:
    report = {
        "files": {
            "src/elke27_lib/mod.py": {
                "missing_lines": [5, 10],
                "missing_branches": [[4, 5], [4, 6]],
            }
        }
    }
    out = diffcover.findings(
        report,
        {"src/elke27_lib/mod.py": {4, 5, 12}},
        {"src/elke27_lib/mod.py": SOURCE},
        TODAY,
        {"helper"},
    )
    assert out == [
        "src/elke27_lib/mod.py:5 ELK205 changed line never runs under the test suite",
        "src/elke27_lib/mod.py:4 ELK205 branch to line 6 is never taken",
        "src/elke27_lib/mod.py:8 ELK205 no test runs helper() and this change removed a call"
        " to it; delete or test it",
    ]


def test_unmeasured_changed_module_is_a_finding() -> None:
    out = diffcover.findings(
        {"files": {}}, {"src/elke27_lib/new.py": {1}}, {"src/elke27_lib/new.py": ["x = 1"]}, TODAY
    )
    assert out == [
        "src/elke27_lib/new.py:1 ELK205 changed module is not measured; no test imports it"
    ]


EXCEPTION = "-- only on a dead socket (expires 2026-12-01, approved by Mitch Mitchell)"

EXCLUDED_SOURCE = f"""\
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import os


def old() -> int:  # pragma: no cover
    x = 1
    return x


def nocolon() -> int:  # pragma no cover
    return 1


def nocoverage() -> int:  # pragma: no coverage
    return 2


def approved() -> int:  # pragma: no cover {EXCEPTION}
    return 3


class P(Protocol):
    def f(self) -> int: ...


def stub() -> int:
    \"\"\"Doc.\"\"\"
    ...


VALUE = 1
"""


def _coverage_report(source: str) -> dict[str, object]:
    """A report entry with the ``excluded_lines`` coverage computes for ``source``.

    Uses coverage's own parser and default exclusion patterns, without tracing, so the
    test does not disturb the coverage run measuring the suite.
    """
    from coverage.config import DEFAULT_EXCLUDE
    from coverage.parser import PythonParser

    parser = PythonParser(text=source, exclude="|".join(f"(?:{p})" for p in DEFAULT_EXCLUDE))
    parser.parse_source()
    entry = {"missing_lines": [], "missing_branches": [], "excluded_lines": sorted(parser.excluded)}
    return {"files": {"src/elke27_lib/probe_mod.py": entry}}


def test_excluded_changed_lines_need_an_exception_on_their_pragma_line() -> None:
    report = _coverage_report(EXCLUDED_SOURCE)
    text = EXCLUDED_SOURCE.splitlines()
    path = "src/elke27_lib/probe_mod.py"
    out = diffcover.findings(report, {path: set(range(1, len(text) + 1))}, {path: text}, TODAY)
    flagged = sorted(int(line.split(":")[1].split()[0]) for line in out)
    assert flagged == [7, 8, 9, 12, 13, 16, 17]
    assert f"{path}:8 ELK205 changed line excluded on line 7: # pragma: no cover" in out[1]


def test_new_line_under_an_unchanged_pragma_def_is_a_finding() -> None:
    report = _coverage_report(EXCLUDED_SOURCE)
    text = EXCLUDED_SOURCE.splitlines()
    path = "src/elke27_lib/probe_mod.py"
    out = diffcover.findings(report, {path: {8}}, {path: text}, TODAY)
    assert out == [
        f"{path}:8 ELK205 changed line excluded on line 7: # pragma: no cover"
        " exception needs '-- <reason> (expires YYYY-MM-DD, approved by <Name>)'"
    ]


def test_pragma_spellings_coverage_honours_cannot_bypass() -> None:
    report = _coverage_report(EXCLUDED_SOURCE)
    text = EXCLUDED_SOURCE.splitlines()
    path = "src/elke27_lib/probe_mod.py"
    out = diffcover.findings(report, {path: {13, 17}}, {path: text}, TODAY)
    assert [line.split(" ELK205 ")[0] for line in out] == [f"{path}:13", f"{path}:17"]


def test_type_checking_blocks_and_stubs_are_accepted_without_a_marker() -> None:
    report = _coverage_report(EXCLUDED_SOURCE)
    text = EXCLUDED_SOURCE.splitlines()
    path = "src/elke27_lib/probe_mod.py"
    files = report["files"]
    assert isinstance(files, dict)
    excluded = set(files[path]["excluded_lines"])
    assert {3, 4, 25, 30} <= excluded
    assert (
        diffcover.findings(report, {path: {3, 4, 25, 28, 29, 30, 20, 21}}, {path: text}, TODAY)
        == []
    )


def test_ci_and_make_run_the_same_command() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "run: uv run python devtools/diffcover.py" in workflow
    assert "uv run python devtools/diffcover.py" in makefile


def _repo(tmp_path: Path, base_source: str) -> str:
    module = tmp_path / "src" / "elke27_lib" / "mod.py"
    module.parent.mkdir(parents=True)
    module.write_text(base_source, encoding="utf-8")
    for args in (
        ["init", "-q"],
        ["add", "."],
        [
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            "base",
        ],
    ):
        subprocess.run(["git", *args], cwd=tmp_path, check=True)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout.strip()


def _report(tmp_path: Path, missing: list[int]) -> Path:
    path = tmp_path / "report.json"
    entry = {"missing_lines": missing, "missing_branches": [], "excluded_lines": []}
    path.write_text(json.dumps({"files": {"src/elke27_lib/mod.py": entry}}), encoding="utf-8")
    return path


def test_main_exits_2_on_a_bad_or_missing_base(tmp_path: Path) -> None:
    _repo(tmp_path, "x = 1\n")
    report = str(_report(tmp_path, []))
    assert diffcover.main(["--base", "nosuchrev", "--coverage-json", report], root=tmp_path) == 2
    assert diffcover.main(["--coverage-json", report], root=tmp_path) == 2


def test_main_passes_pytest_args_after_the_split_and_returns_pytest_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = _repo(tmp_path, "x = 1\n")
    calls: list[list[str]] = []

    def fake_run(root: Path, report: Path, pytest_args: list[str]) -> int:
        calls.append(pytest_args)
        return 5

    monkeypatch.setattr(diffcover, "run_tests", fake_run)
    assert diffcover.main(["--base", base, "--", "-k", "not live", "-x"], root=tmp_path) == 5
    assert calls == [["-k", "not live", "-x"]]


def test_main_reads_the_report_the_tests_wrote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = _repo(tmp_path, "x = 1\n")
    (tmp_path / "src" / "elke27_lib" / "mod.py").write_text("x = 1\ny = 2\n", encoding="utf-8")

    def fake_run(root: Path, report: Path, pytest_args: list[str]) -> int:
        entry = {"missing_lines": [2], "missing_branches": [], "excluded_lines": []}
        report.write_text(json.dumps({"files": {"src/elke27_lib/mod.py": entry}}), encoding="utf-8")
        return 0

    monkeypatch.setattr(diffcover, "run_tests", fake_run)
    assert diffcover.main(["--base", base], root=tmp_path) == 1


def test_main_checks_a_file_whose_change_only_removed_lines(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = _repo(
        tmp_path, "def helper():\n    return 1\n\n\ndef g():\n    helper()\n    return 2\n"
    )
    (tmp_path / "src" / "elke27_lib" / "mod.py").write_text(
        "def helper():\n    return 1\n\n\ndef g():\n    return 2\n", encoding="utf-8"
    )
    report = str(_report(tmp_path, [2]))
    assert diffcover.main(["--base", base, "--coverage-json", report], root=tmp_path) == 1
    out = capsys.readouterr().out
    assert (
        "src/elke27_lib/mod.py:1 ELK205 no test runs helper() and this change removed a call" in out
    )
    assert "diffcover: 1 finding(s) in 0 changed src line(s)" in out


def _entry(missing: list[int], branches: list[list[int]] | None = None) -> dict[str, object]:
    return {"missing_lines": missing, "missing_branches": branches or [], "excluded_lines": []}


def test_orphan_check_spans_modules_and_deleted_files() -> None:
    diff = "\n".join(
        [
            "diff --git a/src/elke27_lib/a.py b/src/elke27_lib/a.py",
            "--- a/src/elke27_lib/a.py",
            "+++ b/src/elke27_lib/a.py",
            "@@ -3 +2,0 @@",
            "-    helper_b(flag)",
            "diff --git a/src/elke27_lib/gone.py b/src/elke27_lib/gone.py",
            "--- a/src/elke27_lib/gone.py",
            "+++ /dev/null",
            "@@ -1,2 +0,0 @@",
            "-def run():",
            "-    return helper_c()",
        ]
    )
    assert diffcover.removed_calls(diff) == {"helper_b", "run", "helper_c"}
    b_source = [
        "def helper_b(flag):",
        "    x = flag",
        "    return x",
        "",
        "def helper_c():",
        "    return 1",
    ]
    report = {"files": {"src/elke27_lib/b.py": _entry([2, 3, 6])}}
    out = diffcover.findings(
        report, {}, {"src/elke27_lib/b.py": b_source}, TODAY, diffcover.removed_calls(diff)
    )
    assert [line.split(" no test runs ")[1].split("(")[0] for line in out] == [
        "helper_b",
        "helper_c",
    ]


CONTINUATION = [
    "def build(x):",
    "    return dict(",
    "        a=x,",
    "        b=x * 4,",
    "    )",
    "",
    "def pick(x, y):",
    "    if (",
    "        x > 1",
    "        and y > 2",
    "    ):",
    "        return 1",
    "    return 0",
]


def test_continuation_line_edit_is_checked_as_its_statement() -> None:
    report = {"files": {"src/elke27_lib/c.py": _entry([2])}}
    out = diffcover.findings(
        report, {"src/elke27_lib/c.py": {4}}, {"src/elke27_lib/c.py": CONTINUATION}, TODAY
    )
    assert out == ["src/elke27_lib/c.py:2 ELK205 changed line never runs under the test suite"]


def test_wrapped_condition_edit_reports_its_untaken_branch() -> None:
    report = {"files": {"src/elke27_lib/c.py": _entry([], [[8, 12]])}}
    out = diffcover.findings(
        report, {"src/elke27_lib/c.py": {10}}, {"src/elke27_lib/c.py": CONTINUATION}, TODAY
    )
    assert out == ["src/elke27_lib/c.py:8 ELK205 branch to line 12 is never taken"]


def test_no_branch_pragma_on_a_changed_line_needs_the_exception_form() -> None:
    text = ["def f(x):", "    if x > 5:  # pragma: no branch", "        return 1", "    return 0"]
    report = {"files": {"src/elke27_lib/d.py": _entry([])}}
    out = diffcover.findings(
        report, {"src/elke27_lib/d.py": {2}}, {"src/elke27_lib/d.py": text}, TODAY
    )
    assert out == [
        "src/elke27_lib/d.py:2 ELK205 changed line # pragma: no branch exception needs"
        " '-- <reason> (expires YYYY-MM-DD, approved by <Name>)'"
    ]
    text[1] = f"    if x > 5:  # pragma: no branch {EXCEPTION}"
    assert (
        diffcover.findings(
            report, {"src/elke27_lib/d.py": {2}}, {"src/elke27_lib/d.py": text}, TODAY
        )
        == []
    )


def test_rules_come_from_coverage_config(tmp_path: Path) -> None:
    config = tmp_path / "pyproject.toml"
    config.write_text(
        "[tool.coverage.report]\nexclude_also = ['raise NotImplementedError']\n", encoding="utf-8"
    )
    rules = diffcover.coverage_rules(config)
    assert "raise NotImplementedError" in rules.exclude
    assert any("branch" in p for p in rules.partial)
    assert len(rules.exempt) == 2 and all(p in rules.exclude for p in rules.exempt)
    text = ["def f():", "    raise NotImplementedError"]
    report = {"files": {"src/elke27_lib/e.py": {**_entry([]), "excluded_lines": [2]}}}
    out = diffcover.findings(
        report, {"src/elke27_lib/e.py": {2}}, {"src/elke27_lib/e.py": text}, TODAY, rules=rules
    )
    assert out == [
        "src/elke27_lib/e.py:2 ELK205 changed line excluded on line 2: raise NotImplementedError"
        " exception needs '-- <reason> (expires YYYY-MM-DD, approved by <Name>)'"
    ]


HANDLERS = [
    "def f(x):",
    "    try:",
    "        y = int(x)",
    "    except ValueError:  # pragma: no cover{except_}",
    "        y = 0",
    "    else:  # pragma: no cover{else_}",
    "        y += 1",
    "    finally:  # pragma: no cover{finally_}",
    "        x = None",
    "    return y",
]


@pytest.mark.parametrize(
    ("clause", "header", "body"), [("except_", 4, 5), ("else_", 6, 7), ("finally_", 8, 9)]
)
def test_pragma_on_except_else_and_finally_follows_coverage_block_rules(
    clause: str, header: int, body: int
) -> None:
    from coverage.config import DEFAULT_EXCLUDE

    path = "src/elke27_lib/h.py"
    marks = {"except_": f" {EXCEPTION}", "else_": f" {EXCEPTION}", "finally_": f" {EXCEPTION}"}
    rules = diffcover.coverage_rules(None)
    assert rules.exclude == tuple(DEFAULT_EXCLUDE)
    text = [line.format(**marks) for line in HANDLERS]
    report = {
        "files": {
            path: {
                "missing_lines": [],
                "missing_branches": [],
                "excluded_lines": [4, 5, 6, 7, 8, 9],
            }
        }
    }
    assert diffcover.findings(report, {path: {body}}, {path: text}, TODAY, rules=rules) == []
    marks[clause] = ""
    text = [line.format(**marks) for line in HANDLERS]
    assert diffcover.findings(report, {path: {body}}, {path: text}, TODAY, rules=rules) == [
        f"{path}:{body} ELK205 changed line excluded on line {header}: # pragma: no cover"
        " exception needs '-- <reason> (expires YYYY-MM-DD, approved by <Name>)'"
    ]


NESTED = [
    "def outer():  # pragma: no cover{outer}",
    "    a = 1",
    "    b = 2  # pragma: no cover{inner}",
    "    c = 3",
    "    return a + b + c",
]


@pytest.mark.parametrize(
    ("outer", "inner", "line", "expected"),
    [
        ("", " {exc}", 4, 1),
        ("", " {exc}", 3, 1),
        (" {exc}", "", 3, 3),
        (" {exc}", " {exc}", 4, None),
        (" {exc}", " {exc}", 3, None),
    ],
)
def test_valid_exception_nearby_does_not_cover_for_a_bare_enclosing_pragma(
    outer: str, inner: str, line: int, expected: int | None
) -> None:
    path = "src/elke27_lib/n.py"
    marks = {"outer": outer.format(exc=EXCEPTION), "inner": inner.format(exc=EXCEPTION)}
    text = [row.format(**marks) for row in NESTED]
    report = {
        "files": {
            path: {"missing_lines": [], "missing_branches": [], "excluded_lines": [1, 2, 3, 4, 5]}
        }
    }
    rules = diffcover.coverage_rules(None)
    got = diffcover.findings(report, {path: {line}}, {path: text}, TODAY, rules=rules)
    if expected is None:
        assert got == []
    else:
        assert got == [
            f"{path}:{line} ELK205 changed line excluded on line {expected}: # pragma: no cover"
            " exception needs '-- <reason> (expires YYYY-MM-DD, approved by <Name>)'"
        ]
