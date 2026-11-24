"""Tests for devtools/ratchet.py, devtools/privatecheck.py and devtools/allow.py."""

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
    if str(DEVTOOLS) not in sys.path:
        sys.path.insert(0, str(DEVTOOLS))
    spec = importlib.util.spec_from_file_location(name, DEVTOOLS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


allow = _load("allow")
ratchet = _load("ratchet")
privatecheck = _load("privatecheck")

BASE = """
LEGACY_HELPERS = {"a.py", "b.py"}
COUNT_CEILING: dict[str, int] = {"a.py": 3, "b.py": 1}
FROZEN_IGNORES = {"test/helpers/*": ["SLF001", "BLE001"]}
OTHER = {"x.py": 9}
"""


def _tables(source: str) -> dict[str, object]:
    return {t.name: t for t in ratchet.python_tables("test/guards.py", source)}


def _messages(base: str, head: str) -> list[str]:
    return [f.message for f in ratchet.compare(_tables(base), _tables(head))]


def test_ratchet_ignores_unnamed_tables_and_accepts_shrinking() -> None:
    head = BASE.replace('"b.py"}', "}").replace('"a.py": 3', '"a.py": 2').replace("9", "99")
    assert _messages(BASE, head) == []


def test_ratchet_flags_added_set_member() -> None:
    head = BASE.replace('{"a.py", "b.py"}', '{"a.py", "b.py", "c.py"}')
    assert _messages(BASE, head) == ["LEGACY_HELPERS gained 'c.py'"]


def test_ratchet_flags_raised_count_and_new_key() -> None:
    head = BASE.replace('"a.py": 3, "b.py": 1', '"a.py": 4, "b.py": 1, "c.py": 1')
    assert _messages(BASE, head) == [
        "COUNT_CEILING['a.py'] rose 3 -> 4",
        "COUNT_CEILING gained 'c.py'",
    ]


def test_ratchet_flags_removed_table() -> None:
    head = BASE.replace('LEGACY_HELPERS = {"a.py", "b.py"}\n', "")
    assert _messages(BASE, head) == ["LEGACY_HELPERS was removed; ceilings only shrink"]


def test_ratchet_allows_glob_narrowed_to_matching_paths() -> None:
    head = BASE.replace('"test/helpers/*": ["SLF001", "BLE001"]', '"test/helpers/k.py": ["SLF001"]')
    assert _messages(BASE, head) == []


def test_ratchet_flags_glob_swap_that_adds_a_code_or_leaves_the_glob() -> None:
    head = BASE.replace('"test/helpers/*": ["SLF001", "BLE001"]', '"test/helpers/k.py": ["E501"]')
    assert _messages(BASE, head) == ["FROZEN_IGNORES gained 'test/helpers/k.py'"]
    elsewhere = BASE.replace('"test/helpers/*"', '"test/other/*"')
    assert _messages(BASE, elsewhere) == ["FROZEN_IGNORES gained 'test/other/*'"]


def test_ratchet_reads_pyproject_ignore_tables() -> None:
    source = (
        '[tool.ruff.lint]\nignore = ["E501"]\n[tool.ruff.lint.per-file-ignores]\n"a.py" = ["B"]\n'
    )
    grown = source.replace('["E501"]', '["E501", "E731"]').replace('["B"]', '["B", "F"]')
    base = {t.name: t for t in ratchet.toml_tables(source)}
    head = {t.name: t for t in ratchet.toml_tables(grown)}
    assert [(f.line, f.message) for f in ratchet.compare(base, head)] == [
        (2, "tool.ruff.lint.ignore gained 'E731'"),
        (4, "tool.ruff.lint.per-file-ignores['a.py'] gained ['F']"),
    ]


def test_allow_marker_needs_reason_expiry_and_named_human() -> None:
    good = "# noqa: ELK201 -- legacy file is split next week (expires 2026-12-01, approved by Mitch Mitchell)"
    assert allow.parse(good, TODAY) == allow.Marker(frozenset({"ELK201"}), None)
    problems = [
        allow.parse(text, TODAY).problem
        for text in (
            "# noqa: ELK201",
            "# noqa: ELK201 -- too short (expires 2026-12-01, approved by Mitch Mitchell)",
            "# noqa: ELK201 -- reason in three words (expires 2026-11-01, approved by Mitch Mitchell)",
            "# noqa: ELK201 -- reason in three words (expires 2026-12-01, approved by Architect)",
        )
    ]
    assert all(problems)
    assert allow.parse("# noqa: E501", TODAY) is None


def test_ratchet_exception_on_the_line_skips_only_a_valid_marker(tmp_path: Path) -> None:
    marker = "# noqa: ELK201 -- split lands in #12 (expires 2026-12-01, approved by Mitch Mitchell)"
    (tmp_path / "test").mkdir()
    (tmp_path / "test" / "g.py").write_text(f'X_CEILING = {{\n    "a.py": 4,  {marker}\n}}\n')
    head = ratchet.Tree(tmp_path, None)
    finding = ratchet.Finding("test/g.py", 2, "X_CEILING['a.py'] rose 3 -> 4")
    assert ratchet.apply_exceptions([finding], head, TODAY) == []
    late = dt.date(2026, 12, 2)
    assert [f.message for f in ratchet.apply_exceptions([finding], head, late)] == [
        "X_CEILING['a.py'] rose 3 -> 4 (exception expired on 2026-12-01)"
    ]


def _private_findings(source: str) -> list[str]:
    path = Path("src/elke27_lib/mod.py")
    return privatecheck.findings(path, source, path.as_posix(), TODAY)


def test_privatecheck_flags_private_names_from_library_modules() -> None:
    source = (
        "from .redact import _should_redact\n"
        "from elke27_lib.util import (\n    public,\n    _helper,\n)\n"
        "from .arm import mode as _mode\n"
        "from os import _exit\n"
        "from . import __version__\n"
    )
    assert _private_findings(source) == [
        "src/elke27_lib/mod.py:1 ELK202 imports private _should_redact from .redact; make it public",
        "src/elke27_lib/mod.py:2 ELK202 imports private _helper from elke27_lib.util; make it public",
    ]


def test_privatecheck_exception_marker() -> None:
    marker = (
        "# noqa: ELK202 -- moves public in #200 (expires 2026-12-01, approved by Mitch Mitchell)"
    )
    assert _private_findings(f"from .redact import _should_redact  {marker}\n") == []
