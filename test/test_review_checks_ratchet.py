"""Ratchet coverage for Python ceiling tables and the D55 gaps found on #162."""

from __future__ import annotations

from pathlib import Path

import pytest

from test.helpers.devtools import load

ratchet = load("ratchet")

CEILINGS = (
    "COMMENT_CEILING = {\n"
    '    "src/a.py": 3,\n'
    '    "src/b.py": 1,\n'
    "}\n"
    "LEGACY_COMMENT_EXCLUDE = {\n"
    '    "src/handlers/x.py",\n'
    "}\n"
)


def _tables(root: Path, files: dict[str, str]) -> dict[str, object]:
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    tree = ratchet.Tree(root, None)
    tree.paths = lambda: sorted(files)
    return ratchet.tables(tree)


def _messages(tmp_path: Path, base: dict[str, str], head: dict[str, str]) -> list[str]:
    old = _tables(tmp_path / "base", base)
    new = _tables(tmp_path / "head", head)
    return [f.message for f in ratchet.compare(old, new)]


@pytest.mark.parametrize("path", ["devtools/comment_ceiling.py", "devtools/catchcheck.py"])
def test_python_ceiling_growth_fails_and_shrinking_passes(tmp_path: Path, path: str) -> None:
    grown = CEILINGS.replace('"src/a.py": 3', '"src/a.py": 4').replace(
        '"src/handlers/x.py",', '"src/handlers/x.py",\n    "src/handlers/y.py",'
    )
    assert _messages(tmp_path, {path: CEILINGS}, {path: grown}) == [
        "COMMENT_CEILING['src/a.py'] rose 3 -> 4",
        "LEGACY_COMMENT_EXCLUDE gained 'src/handlers/y.py'",
    ]
    shrunk = CEILINGS.replace('"src/a.py": 3', '"src/a.py": 2').replace('    "src/b.py": 1,\n', "")
    assert _messages(tmp_path, {path: CEILINGS}, {path: shrunk}) == []


def test_python_ceiling_new_against_the_base_is_allowed(tmp_path: Path) -> None:
    head = {"devtools/comment_ceiling.py": CEILINGS}
    assert _messages(tmp_path, {}, head) == []


def test_python_ceiling_added_key_is_growth(tmp_path: Path) -> None:
    base = {"devtools/comment_ceiling.py": CEILINGS}
    head = {"devtools/comment_ceiling.py": CEILINGS.replace('"src/b.py": 1', '"src/c.py": 1')}
    assert _messages(tmp_path, base, head) == ["COMMENT_CEILING gained 'src/c.py'"]


PYPROJECT = "[tool.ruff.lint]\nselect = ['SLF']\n"


@pytest.mark.parametrize(
    ("added", "message"),
    [
        (
            "[tool.ruff.lint.flake8-self]\nextend-ignore-names = ['_seam']\n",
            "tool.ruff.lint.flake8-self.extend-ignore-names gained '_seam'",
        ),
        (
            "[tool.ruff.lint.flake8-self]\nignore-names = ['_seam']\n",
            "tool.ruff.lint.flake8-self.ignore-names gained '_seam'",
        ),
        (
            "[tool.ruff]\ninclude = ['src/**/*.py']\n",
            "tool.ruff.include set; it narrows what ruff checks",
        ),
    ],
)
def test_ruff_name_ignores_and_include_are_growth(tmp_path: Path, added: str, message: str) -> None:
    base = {"pyproject.toml": PYPROJECT}
    head = {"pyproject.toml": PYPROJECT + added}
    assert _messages(tmp_path, base, head) == [message]


def test_ruff_include_dropping_an_entry_is_growth(tmp_path: Path) -> None:
    base = {"pyproject.toml": "[tool.ruff]\ninclude = ['src/**/*.py', 'test/**/*.py']\n"}
    head = {"pyproject.toml": "[tool.ruff]\ninclude = ['src/**/*.py']\n"}
    assert _messages(tmp_path, base, head) == ["tool.ruff.include dropped 'test/**/*.py'"]


def test_toml_ceiling_value_that_is_not_a_count_fails_closed(tmp_path: Path) -> None:
    base = {"pyproject.toml": "[tool.elke27.x.comment_ceiling]\n'src/a.py' = 3\n"}
    head = {"pyproject.toml": "[tool.elke27.x.comment_ceiling]\n'src/a.py' = '3'\n"}
    assert _messages(tmp_path, base, head) == [
        "tool.elke27.x.comment_ceiling: 'src/a.py' is not an integer count"
    ]


def test_loopcheck_scope_lists_only_grow(tmp_path: Path) -> None:
    source = (
        "[tool.elke27.loopcheck]\nloop_modules = ['src/a.py', 'src/b.py']\nloop_paths = ['src/h']\n"
    )
    narrowed = source.replace(", 'src/b.py'", "").replace("['src/h']", "[]")
    assert _messages(tmp_path, {"pyproject.toml": source}, {"pyproject.toml": narrowed}) == [
        "tool.elke27.loopcheck.loop_modules dropped 'src/b.py'",
        "tool.elke27.loopcheck.loop_paths dropped 'src/h'",
    ]
    widened = source.replace("['src/h']", "['src/h', 'src/i']")
    assert _messages(tmp_path, {"pyproject.toml": source}, {"pyproject.toml": widened}) == []


GUARDS = "test/test_review_guards.py"
NOQA = 'NOQA_CEILING: dict[str, int] = {\n    "src/elke27_lib/client.py:BLE001": 12,\n}\n'


def test_new_inline_slf001_noqa_in_src_is_growth(tmp_path: Path) -> None:
    """A new SLF001 escape in src shows up as NOQA_CEILING growth, at its entry."""
    grown = NOQA.replace("}", '    "src/elke27_lib/redact.py:SLF001": 1,\n}')
    found = ratchet.compare(
        _tables(tmp_path / "base", {GUARDS: NOQA}), _tables(tmp_path / "head", {GUARDS: grown})
    )
    assert [(f.path, f.line, f.message) for f in found] == [
        (GUARDS, 3, "NOQA_CEILING gained 'src/elke27_lib/redact.py:SLF001'")
    ]
    file_level = NOQA.replace("}", '    "src/elke27_lib/redact.py:SLF001:file": 1,\n}')
    assert _messages(tmp_path, {GUARDS: NOQA}, {GUARDS: file_level}) == [
        "NOQA_CEILING gained 'src/elke27_lib/redact.py:SLF001:file'"
    ]
    raised = NOQA.replace("12", "13")
    assert _messages(tmp_path, {GUARDS: NOQA}, {GUARDS: raised}) == [
        "NOQA_CEILING['src/elke27_lib/client.py:BLE001'] rose 12 -> 13"
    ]
