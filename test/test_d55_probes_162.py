"""D55 probe tests for #162: each pins a guard branch that no current test reaches."""

from __future__ import annotations

import datetime as dt
import subprocess
from pathlib import Path

import pytest

from test.helpers.devtools import load
from test.helpers.reporter import Reporter

allow = load("allow")
privatecheck = load("privatecheck")
ratchet = load("ratchet")
TODAY = dt.date(2026, 11, 24)


def _private_findings(source: str) -> list[str]:
    path = Path("src/elke27_lib/mod.py")
    return privatecheck.findings(path, source, path.as_posix(), TODAY)


def _problems(source: str) -> list[tuple[int, str]]:
    return [p for t in ratchet.python_tables("test/g.py", source) for p in t.problems]


def _tree_tables(tmp_path: Path, files: dict[str, str]) -> dict[str, object]:
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text, encoding="utf-8")
    tree = ratchet.Tree(tmp_path, None)
    tree.paths = lambda: sorted(files)
    return ratchet.tables(tree)


def _git_repo(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    for args in (
        ["init", "-q"],
        ["add", "."],
        ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base"],
    ):
        subprocess.run(["git", *args], cwd=root, check=True)


GOOD = "(expires 2026-12-01, approved by Mitch Mitchell)"


def _toml(source: str) -> dict[str, object]:
    return {t.name: t for t in ratchet.toml_tables(source)}


@pytest.mark.parametrize(
    ("base", "grown", "message"),
    [
        (
            "[tool.ruff]\nexternal = []\n",
            "[tool.ruff]\nexternal = ['X']\n",
            "tool.ruff.external gained 'X'",
        ),
        (
            "[tool.ruff.lint]\nexternal = []\n",
            "[tool.ruff.lint]\nexternal = ['X']\n",
            "tool.ruff.lint.external gained 'X'",
        ),
        (
            "[tool.ruff]\nextend-exclude = []\n",
            "[tool.ruff]\nextend-exclude = ['gen']\n",
            "tool.ruff.extend-exclude gained 'gen'",
        ),
        (
            "[tool.ruff]\nignore = []\n",
            "[tool.ruff]\nignore = ['E731']\n",
            "tool.ruff.ignore gained 'E731'",
        ),
    ],
)
def test_probe_every_listed_ruff_suppression_key_is_ratcheted(
    base: str, grown: str, message: str
) -> None:
    assert [f.message for f in ratchet.compare(_toml(base), _toml(grown))] == [message]


def test_probe_ruff_toml_and_dot_ruff_toml_are_separate_tables(tmp_path: Path) -> None:
    base = _tree_tables(
        tmp_path / "base",
        {"ruff.toml": "[lint]\nignore = []\n", ".ruff.toml": "[lint]\nignore = ['E501']\n"},
    )
    head = _tree_tables(
        tmp_path / "head",
        {"ruff.toml": "[lint]\nignore = ['E501']\n", ".ruff.toml": "[lint]\nignore = ['E501']\n"},
    )
    assert ("ruff.toml", "lint.ignore gained 'E501'") in [
        (f.path, f.message) for f in ratchet.compare(base, head)
    ]


def test_probe_same_name_table_in_another_file_is_compared_to_its_own_base(
    tmp_path: Path,
) -> None:
    base = _tree_tables(
        tmp_path / "base",
        {"test/a.py": 'LEGACY_X = {"a.py", "b.py"}\n', "test/b.py": 'LEGACY_X = {"z.py"}\n'},
    )
    head = _tree_tables(
        tmp_path / "head",
        {
            "test/a.py": 'LEGACY_X = {"a.py", "b.py"}\n',
            "test/b.py": 'LEGACY_X = {"z.py", "a.py"}\n',
        },
    )
    assert [(f.path, f.message) for f in ratchet.compare(base, head)] == [
        ("test/b.py", "LEGACY_X gained 'a.py'")
    ]


def test_probe_fail_closed_on_bool_member_global_and_syntax(tmp_path: Path) -> None:
    assert _problems('A_CEILING = {"a.py": True}\n') == [
        (1, "entry is not a literal; must be a literal table")
    ]
    assert _problems("N = 'x'\nLEGACY_X = {N}\n") == [
        (2, "member is not a literal; must be a literal table")
    ]
    assert _problems('LEGACY_X = {"a"}\ndef f():\n    global LEGACY_X\n') == [
        (3, "LEGACY_X changed by global rebinding; must be a literal table")
    ]
    assert _problems("LEGACY_X = {\n") == [(1, "file does not parse")]
    (tmp_path / "pyproject.toml").write_text("[tool.ruff\n", encoding="utf-8")
    tree = ratchet.Tree(tmp_path, None)
    tree.paths = lambda: ["pyproject.toml"]
    assert ratchet.tables(tree)["pyproject.toml::<toml>"].problems == ((1, "file does not parse"),)


def test_probe_kind_changes_are_findings() -> None:
    old = {t.name: t for t in ratchet.python_tables("test/g.py", 'A_CEILING = {"a.py": 3}\n')}
    new = {t.name: t for t in ratchet.python_tables("test/g.py", 'A_CEILING = {"a.py": ["X"]}\n')}
    assert [f.message for f in ratchet.compare(old, new)] == ["A_CEILING['a.py'] changed kind"]


def test_probe_devtools_tables_are_ratcheted(tmp_path: Path) -> None:
    base = _tree_tables(tmp_path / "base", {"devtools/x.py": 'LEGACY_X = {"a"}\n'})
    head = _tree_tables(tmp_path / "head", {"devtools/x.py": 'LEGACY_X = {"a", "b"}\n'})
    assert [f.message for f in ratchet.compare(base, head)] == ["LEGACY_X gained 'b'"]


def test_probe_ratchet_exits_2_without_origin_main(tmp_path: Path) -> None:
    _git_repo(tmp_path, {"a.txt": "x\n"})
    assert ratchet.main([], root=tmp_path) == 2


def test_probe_marker_edges() -> None:
    assert (
        allow.parse(
            "# noqa: ELK201 -- reason in three words (expires 2026-11-24, approved by Mitch Mitchell)",
            TODAY,
        ).problem
        is None
    )
    assert "is not a date" in (
        allow.parse(
            "# noqa: ELK201 -- reason in three words (expires 2026-13-01, approved by Mitch Mitchell)",
            TODAY,
        ).problem
        or ""
    )
    markers = allow.line_markers([f"x = 1  # noqa: ELK202 -- reason in three words {GOOD}"], TODAY)
    assert allow.verdict(markers, 1, "ELK201") == (False, None)


def test_probe_privatecheck_from_line_marker_and_rejected_marker_text() -> None:
    marker = f"# noqa: ELK202 -- moves public in #200 {GOOD}"
    assert _private_findings(f"from .redact import (  {marker}\n    _helper,\n)\n") == []
    expired = (
        "# noqa: ELK202 -- moves public in #200 (expires 2026-01-01, approved by Mitch Mitchell)"
    )
    assert _private_findings(f"from .redact import _helper  {expired}\n") == [
        "src/elke27_lib/mod.py:1 ELK202 imports private _helper from .redact; make it public"
        " (exception expired on 2026-01-01)"
    ]


def test_probe_privatecheck_exits_1_on_a_finding(tmp_path: Path) -> None:
    mod = tmp_path / "src" / "elke27_lib" / "m.py"
    mod.parent.mkdir(parents=True)
    mod.write_text("from .redact import _helper\n", encoding="utf-8")
    assert privatecheck.main(["--root", str(tmp_path)]) == 1


def test_probe_reporter_summary_is_redacted(tmp_path: Path) -> None:
    reporter = Reporter(run_id="run", test_id="t", artifacts_dir=tmp_path, emit_yaml=True)
    reporter.emit("step", pin="4321", access_code="9999")
    reporter.finalize()
    text = (tmp_path / "run.summary.yaml").read_text(encoding="utf-8")
    assert "4321" not in text and "9999" not in text
