"""Decision 55 probes for #172: diffcover branches the suite leaves unpinned."""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

DEVTOOLS = Path(__file__).resolve().parent.parent / "devtools"
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

PATH = "src/elke27_lib/probe_mod.py"
EXCEPTION = "-- only on a dead socket (expires 2026-12-01, approved by Mitch Mitchell)"


def _report(source: str, missing: list[int] | None = None) -> dict[str, object]:
    from coverage.config import DEFAULT_EXCLUDE
    from coverage.parser import PythonParser

    parser = PythonParser(text=source, exclude="|".join(f"(?:{p})" for p in DEFAULT_EXCLUDE))
    parser.parse_source()
    entry = {
        "missing_lines": missing or [],
        "missing_branches": [],
        "excluded_lines": sorted(parser.excluded),
    }
    return {"files": {PATH: entry}}


def _findings(source: str, changed: set[int]) -> list[str]:
    return diffcover.findings(_report(source), {PATH: changed}, {PATH: source.splitlines()}, TODAY)


def test_changed_non_python_file_under_src_is_ignored() -> None:
    diff = "--- a/src/elke27_lib/py.typed\n+++ b/src/elke27_lib/py.typed\n@@ -0,0 +1 @@\n+x\n"
    assert diffcover.changed_lines(diff) == {}


def test_orphan_needs_every_body_line_missing_and_a_removed_call() -> None:
    source = "def a():\n    x = 1\n    return x\n\n\ndef b():\n    return 2\n"
    assert diffcover.orphaned_functions(source, {2, 7}, {"a"}) == []


def test_exception_text_must_follow_the_pragma_directly() -> None:
    line = f"def f():  # pragma: no cover because {EXCEPTION}"
    pattern = diffcover.coverage_rules().exclude[0]
    assert diffcover.pragma_problem(line, pattern, TODAY) is not None


def test_type_checking_block_does_not_cover_for_a_bare_enclosing_pragma() -> None:
    source = "def f() -> None:  # pragma: no cover\n    if TYPE_CHECKING:\n        import os\n"
    out = _findings(source, {3})
    assert len(out) == 1
    assert out[0].startswith(f"{PATH}:3 ELK205 changed line excluded on line 1:")


def test_nearest_unaccepted_pragma_is_reported() -> None:
    source = (
        "def outer():  # pragma: no cover\n    def inner():  # pragma: no cover\n        return 1\n"
    )
    out = _findings(source, {3})
    assert len(out) == 1
    assert "excluded on line 2:" in out[0]


def test_excluded_line_without_a_matching_pattern_is_a_finding() -> None:
    report = {"files": {PATH: {"missing_lines": [], "missing_branches": [], "excluded_lines": [1]}}}
    out = diffcover.findings(report, {PATH: {1}}, {PATH: ["x = 1"]}, TODAY)
    assert out == [
        f"{PATH}:1 ELK205 changed line excluded from coverage without a matching pattern"
    ]


def test_comment_only_unmeasured_module_is_not_a_finding() -> None:
    assert diffcover.findings({"files": {}}, {PATH: {1}}, {PATH: ["# only a note"]}, TODAY) == []


def test_continuation_edit_under_a_pragma_on_the_first_line_is_checked() -> None:
    out = _findings("x = call(  # pragma: no cover\n    1,\n)\n", {2})
    assert len(out) == 1
    assert out[0].startswith(f"{PATH}:1 ELK205 changed line excluded on line 1:")


def test_missing_statement_is_not_also_reported_for_its_branches() -> None:
    source = ["def f(x):", "    if x:", "        return 1", "    return 0"]
    entry = {"missing_lines": [2, 3, 4], "missing_branches": [[2, 3], [2, 4]]}
    out = diffcover.findings({"files": {PATH: entry}}, {PATH: {2}}, {PATH: source}, TODAY)
    assert out == [f"{PATH}:2 ELK205 changed line never runs under the test suite"]


def test_no_branch_pragma_inside_an_accepted_excluded_block_is_not_rechecked() -> None:
    source = f"def f():  # pragma: no cover {EXCEPTION}\n    while x:  # pragma: no branch\n        return 1\n"
    assert _findings(source, {2}) == []


def test_run_tests_measures_branches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(diffcover.subprocess, "run", fake_run)
    report = tmp_path / "r.json"
    assert diffcover.run_tests(tmp_path, report, ["-x"]) == 0
    assert {"--cov=src", "--cov-branch", f"--cov-report=json:{report}", "-x"} <= set(seen[0])


def _git(root: Path, *args: str) -> str:
    cmd = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
    return subprocess.run(
        [*cmd, *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


def test_main_finds_an_orphan_in_an_unchanged_module(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pkg = tmp_path / "src" / "elke27_lib"
    pkg.mkdir(parents=True)
    (pkg / "b.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
    (pkg / "a.py").write_text("def g():\n    helper()\n    return 2\n", encoding="utf-8")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "base")
    base = _git(tmp_path, "rev-parse", "HEAD")
    (pkg / "a.py").write_text("def g():\n    return 2\n", encoding="utf-8")
    entry = {"missing_branches": [], "excluded_lines": []}
    report = {
        "files": {
            "src/elke27_lib/a.py": {**entry, "missing_lines": []},
            "src/elke27_lib/b.py": {**entry, "missing_lines": [2]},
        }
    }
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    assert diffcover.main(["--base", base, "--coverage-json", str(path)], root=tmp_path) == 1
    assert "src/elke27_lib/b.py:1 ELK205 no test runs helper()" in capsys.readouterr().out
