"""Tests for devtools/catchcheck.py (swallowed exceptions and catch-alls)."""

from __future__ import annotations

import datetime as dt
import importlib.util
import subprocess
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


catchcheck = _load("catchcheck")

SOURCE = """
import contextlib
from contextlib import suppress
from contextlib import suppress as quiet

def f(loop):
    with contextlib.suppress(Exception):
        loop.close()
    with suppress(BaseException, OSError):
        loop.close()
    with suppress(OSError):
        loop.close()
    try:
        loop.run()
    except RuntimeError:
        return
    try:
        loop.run()
    except (TimeoutError, OSError):
        pass
    for _ in range(3):
        try:
            loop.run()
        except ValueError:
            continue
    try:
        loop.run()
    except KeyError:
        return None
    try:
        loop.run()
    except KeyError as err:
        raise ValueError("bad") from err
    try:
        loop.run()
    except OSError:
        loop.log()
        return
    with quiet(Exception):
        loop.close()
"""


def test_counts_broad_suppress_and_swallowing_excepts_only() -> None:
    assert [line for line, _ in catchcheck.sites(SOURCE, TODAY)] == [7, 9, 15, 19, 24, 28, 39]


def test_exception_marker_drops_the_site_until_it_expires() -> None:
    marker = "# noqa: ELK203 -- close races a dead socket (expires 2026-12-01, approved by Mitch Mitchell)"
    source = f"import contextlib\nwith contextlib.suppress(Exception):  {marker}\n    pass\n"
    assert catchcheck.sites(source, TODAY) == []
    late = catchcheck.sites(source, dt.date(2026, 12, 2))
    assert late == [
        (2, "contextlib.suppress(Exception) hides every error (exception expired on 2026-12-01)")
    ]


def test_findings_fail_above_and_below_the_ceiling() -> None:
    found = {"a.py": [(3, "except X swallows the error")], "b.py": []}
    assert catchcheck.findings(found, {"b.py": 1}) == [
        "a.py:3 ELK203 except X swallows the error (1 sites, ceiling 0)",
        "b.py:1 ELK203 count fell to 0; lower CATCH_CEILING from 1",
    ]
    assert catchcheck.findings(found, {"a.py": 1}) == []


def test_repository_matches_catch_ceiling() -> None:
    """The same command CI runs through devtools/lint.py."""
    result = subprocess.run(
        [sys.executable, "devtools/catchcheck.py"], cwd=ROOT, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
