"""Tests for devtools/diffcover.py (changed library lines the suite never runs)."""

from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

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
    assert diffcover.removed_calls(DIFF) == {"src/elke27_lib/mod.py": {"helper"}}


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
        {"src/elke27_lib/mod.py": {"helper"}},
    )
    assert out == [
        "src/elke27_lib/mod.py:8 ELK205 helper() lost its tested caller in this change; delete or test it",
        "src/elke27_lib/mod.py:5 ELK205 changed line never runs under the test suite",
        "src/elke27_lib/mod.py:4 ELK205 branch to line 6 is never taken",
    ]


def test_unmeasured_changed_module_is_a_finding() -> None:
    out = diffcover.findings(
        {"files": {}}, {"src/elke27_lib/new.py": {1}}, {"src/elke27_lib/new.py": ["x = 1"]}, TODAY
    )
    assert out == [
        "src/elke27_lib/new.py:1 ELK205 changed module is not measured; no test imports it"
    ]


def test_pragma_on_a_changed_line_needs_the_exception_form() -> None:
    good = "x = 1  # pragma: no cover -- only on a dead socket (expires 2026-12-01, approved by Mitch Mitchell)"
    assert diffcover.pragma_problem(good, TODAY) is None
    assert diffcover.pragma_problem("x = 1  # pragma: no cover", TODAY) is not None
    assert diffcover.pragma_problem("x = 1", TODAY) is None
    out = diffcover.findings(
        {"files": {"src/a.py": {"missing_lines": [], "missing_branches": []}}},
        {"src/a.py": {1}},
        {"src/a.py": ["x = 1  # pragma: no cover"]},
        TODAY,
    )
    assert len(out) == 1 and "pragma: no cover" in out[0]


def test_ci_and_make_run_the_same_command() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "run: uv run python devtools/diffcover.py" in workflow
    assert "uv run python devtools/diffcover.py" in makefile
