"""Tests for devtools/ratchet.py, devtools/privatecheck.py and devtools/allow.py."""

from __future__ import annotations

import ast
import datetime as dt
import subprocess
import sys
from pathlib import Path

import pytest

from test.helpers.devtools import load

ROOT = Path(__file__).resolve().parent.parent
DEVTOOLS = ROOT / "devtools"
TODAY = dt.date(2026, 11, 24)


allow = load("allow")
ratchet = load("ratchet")
privatecheck = load("privatecheck")

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
        "src/elke27_lib/mod.py:4 ELK202 imports private _helper from elke27_lib.util; make it public",
    ]


def test_privatecheck_exception_marker() -> None:
    marker = (
        "# noqa: ELK202 -- moves public in #200 (expires 2026-12-01, approved by Mitch Mitchell)"
    )
    assert _private_findings(f"from .redact import _should_redact  {marker}\n") == []


def test_ratchet_reads_tool_elke27_ceilings() -> None:
    source = '[tool.elke27.loopcheck.comment_ceiling]\n"src/a.py" = 3\n"src/b.py" = 1\n'
    grown = source.replace("= 3", "= 4").replace('"src/b.py" = 1', '"src/c.py" = 1')
    base = {t.name: t for t in ratchet.toml_tables(source)}
    head = {t.name: t for t in ratchet.toml_tables(grown)}
    assert [(f.line, f.message) for f in ratchet.compare(base, head)] == [
        (2, "tool.elke27.loopcheck.comment_ceiling['src/a.py'] rose 3 -> 4"),
        (3, "tool.elke27.loopcheck.comment_ceiling gained 'src/c.py'"),
    ]


def _tree_tables(tmp_path: Path, files: dict[str, str]) -> dict[str, object]:
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text, encoding="utf-8")
    tree = ratchet.Tree(tmp_path, None)
    tree.paths = lambda: sorted(files)
    return ratchet.tables(tree)


def test_ratchet_keys_tables_by_file_so_a_shadow_cannot_replace_them(tmp_path: Path) -> None:
    real = 'LEGACY_HELPERS = {"a.py"}\n'
    base = _tree_tables(tmp_path / "base", {"test/test_review_guards.py": real})
    head = _tree_tables(
        tmp_path / "head",
        {
            "test/test_review_guards.py": 'LEGACY_HELPERS = {"a.py", "b.py"}\n',
            "test/zz_shadow.py": real,
        },
    )
    assert [f.message for f in ratchet.compare(base, head)] == ["LEGACY_HELPERS gained 'b.py'"]


def test_ratchet_toml_key_missing_at_base_is_empty_not_a_new_ceiling() -> None:
    base = {t.name: t for t in ratchet.toml_tables("[tool.ruff.lint]\nselect = ['E']\n")}
    grown = (
        "[tool.ruff]\nexclude = ['gen']\nextend-ignore = ['E731']\n"
        "[tool.ruff.lint]\nselect = ['E']\nextend-ignore = ['B']\n"
        "[tool.ruff.lint.extend-per-file-ignores]\n'a.py' = ['F']\n"
    )
    head = {t.name: t for t in ratchet.toml_tables(grown)}
    assert sorted(f.message for f in ratchet.compare(base, head)) == [
        "tool.ruff.exclude gained 'gen'",
        "tool.ruff.extend-ignore gained 'E731'",
        "tool.ruff.lint.extend-ignore gained 'B'",
        "tool.ruff.lint.extend-per-file-ignores gained 'a.py'",
    ]


def test_ratchet_flags_a_dropped_selected_rule() -> None:
    base = {t.name: t for t in ratchet.toml_tables("[tool.ruff.lint]\nselect = ['E', 'B']\n")}
    head = {t.name: t for t in ratchet.toml_tables("[tool.ruff.lint]\nselect = ['E']\n")}
    assert [f.message for f in ratchet.compare(base, head)] == ["tool.ruff.lint.select dropped 'B'"]


def test_ratchet_reads_standalone_ruff_toml(tmp_path: Path) -> None:
    base = _tree_tables(tmp_path / "base", {".ruff.toml": "[lint]\nignore = []\n"})
    head = _tree_tables(tmp_path / "head", {".ruff.toml": "[lint]\nignore = ['E501']\n"})
    assert [(f.path, f.message) for f in ratchet.compare(base, head)] == [
        (".ruff.toml", "lint.ignore gained 'E501'")
    ]


def test_ratchet_tracks_tool_elke27_exclude_lists() -> None:
    source = "[tool.elke27.loopcheck]\ncomment_exclude = ['src/a']\n"
    base = {t.name: t for t in ratchet.toml_tables(source)}
    head = {t.name: t for t in ratchet.toml_tables(source.replace("'src/a']", "'src/a', 'src/b']"))}
    assert [f.message for f in ratchet.compare(base, head)] == [
        "tool.elke27.loopcheck.comment_exclude gained 'src/b'"
    ]


def test_privatecheck_reports_and_accepts_markers_on_the_alias_line() -> None:
    marker = (
        "# noqa: ELK202 -- moves public in #200 (expires 2026-12-01, approved by Mitch Mitchell)"
    )
    source = f"from .redact import (\n    public,\n    _helper,  {marker}\n    _other,\n)\n"
    assert _private_findings(source) == [
        "src/elke27_lib/mod.py:4 ELK202 imports private _other from .redact; make it public"
    ]


def _problems(source: str) -> list[tuple[int, str]]:
    return [p for t in ratchet.python_tables("test/g.py", source) for p in t.problems]


def test_ratchet_fails_closed_on_tables_it_cannot_read() -> None:
    source = (
        "N = 9\n"
        '_EXTRA = {"z.py": 1}\n'
        'A_CEILING = {"a.py": 3 + 9, "b.py": N}\n'
        'B_CEILING = {"a.py": 1, **_EXTRA}\n'
        'LEGACY_X = {"a.py"}\n'
        'LEGACY_X |= {"b.py"}\n'
        'A_CEILING["c.py"] = 5\n'
        'LEGACY_X.add("d.py")\n'
        "C_CEILING = dict(a=1)\n"
        "C_CEILING = {}\n"
        "def f():\n"
        '    B_CEILING.update({"e.py": 1})\n'
    )
    assert _problems(source) == [
        (3, "entry is not a literal; must be a literal table"),
        (3, "entry is not a literal; must be a literal table"),
        (7, "A_CEILING changed by item or attribute assignment; must be a literal table"),
        (4, "** splat; must be a literal table"),
        (12, "B_CEILING changed by .update() call; must be a literal table"),
        (9, "value is not a literal dict or set; must be a literal table"),
        (10, "C_CEILING changed by assignment; must be a literal table"),
        (6, "LEGACY_X changed by augmented assignment; must be a literal table"),
        (8, "LEGACY_X changed by .add() call; must be a literal table"),
    ]
    tables = {t.name: t for t in ratchet.python_tables("test/g.py", source)}
    assert len(ratchet.compare(tables, tables)) == 9


def test_ratchet_flags_a_new_ruff_config_file(tmp_path: Path) -> None:
    base = _tree_tables(tmp_path / "base", {"pyproject.toml": "[tool.ruff.lint]\nselect = ['E']\n"})
    head = _tree_tables(
        tmp_path / "head",
        {"pyproject.toml": "[tool.ruff.lint]\nselect = ['E']\n", "ruff.toml": "line-length = 99\n"},
    )
    assert [(f.path, f.message) for f in ratchet.compare(base, head)] == [
        (
            "ruff.toml",
            "ruff config file (overrides [tool.ruff] in pyproject.toml) gained 'ruff.toml'",
        )
    ]


def test_ratchet_flags_extend_select_shrinking() -> None:
    base = {
        t.name: t for t in ratchet.toml_tables("[tool.ruff.lint]\nextend-select = ['BLE', 'S']\n")
    }
    head = {t.name: t for t in ratchet.toml_tables("[tool.ruff.lint]\nextend-select = ['S']\n")}
    assert [f.message for f in ratchet.compare(base, head)] == [
        "tool.ruff.lint.extend-select dropped 'BLE'"
    ]


def test_ratchet_puts_the_finding_on_the_entry_in_its_own_section() -> None:
    source = (
        "[tool.ruff.lint]\n"
        "ignore = [\n    'E501',\n]\n"
        "[tool.ruff.lint.per-file-ignores]\n"
        "'a.py' = ['E501']\n"
        "[tool.ruff.format]\n"
        "exclude = ['a.py']\n"
    )
    grown = source.replace("'a.py' = ['E501']", "'a.py' = ['E501']\n'b.py' = ['E501']").replace(
        "exclude = ['a.py']", "exclude = ['a.py', 'b.py']"
    )
    base = {t.name: t for t in ratchet.toml_tables(source)}
    head = {t.name: t for t in ratchet.toml_tables(grown)}
    assert sorted((f.line, f.message) for f in ratchet.compare(base, head)) == [
        (7, "tool.ruff.lint.per-file-ignores gained 'b.py'"),
        (9, "tool.ruff.format.exclude gained 'b.py'"),
    ]


def test_allow_marker_expiry_is_capped_at_90_days() -> None:
    far = "# noqa: ELK201 -- reason in three words (expires 2099-12-31, approved by Mitch Mitchell)"
    near = (
        "# noqa: ELK201 -- reason in three words (expires 2027-02-22, approved by Mitch Mitchell)"
    )
    over = (
        "# noqa: ELK201 -- reason in three words (expires 2027-02-23, approved by Mitch Mitchell)"
    )
    assert allow.parse(near, TODAY).problem is None
    assert allow.parse(far, TODAY).problem == "exception expiry 2099-12-31 is more than 90 days out"
    assert (
        allow.parse(over, TODAY).problem == "exception expiry 2027-02-23 is more than 90 days out"
    )


def _git_repo(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
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
        subprocess.run(["git", *args], cwd=root, check=True)


def test_ratchet_revalidates_markers_on_unchanged_lines(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    expired = (
        "# noqa: ELK201 -- kept for the old seam (expires 2026-01-01, approved by Mitch Mitchell)"
    )
    _git_repo(tmp_path, {"test/g.py": f'X_CEILING = {{\n    "a.py": 4,  {expired}\n}}\n'})
    assert ratchet.main(["--base", "HEAD"], root=tmp_path) == 1
    out = capsys.readouterr().out
    assert "test/g.py:2 ELK201 exception marker rejected: exception expired on 2026-01-01" in out


def test_loading_a_devtools_script_leaves_the_session_clean() -> None:
    assert str(DEVTOOLS) not in sys.path
    assert "allow" not in sys.modules
    assert not any(name.startswith("devtools_") for name in sys.modules)
    assert "tomllib" in sys.modules


def test_allow_policy_lets_a_vendored_copy_set_its_own_approvers_and_codes() -> None:
    policy = allow.Policy(approvers=frozenset({"Ann Lee"}), codes=r"HA2\d\d", max_days=30)
    good = "# noqa: HA201 -- kept for the old hub (expires 2026-12-01, approved by Ann Lee)"
    assert allow.parse(good, TODAY, policy) == allow.Marker(frozenset({"HA201"}), None)
    mitch = good.replace("Ann Lee", "Mitch Mitchell")
    assert (
        allow.parse(mitch, TODAY, policy).problem == "exception approver must be one of ['Ann Lee']"
    )
    late = good.replace("2026-12-01", "2027-01-01")
    assert allow.parse(late, TODAY, policy).problem == (
        "exception expiry 2027-01-01 is more than 30 days out"
    )
    assert (
        allow.parse(
            "# noqa: ELK201 -- a b c (expires 2026-12-01, approved by Ann Lee)", TODAY, policy
        )
        is None
    )
    assert allow.parse(mitch.replace("HA201", "ELK201"), TODAY).problem is None
    assert list(allow.line_markers(["x = 1", good], TODAY, policy)) == [2]


def test_vendorable_modules_import_only_the_standard_library() -> None:
    for name in ("allow", "privacc", "privacc_probes"):
        tree = ast.parse((DEVTOOLS / f"{name}.py").read_text(encoding="utf-8"))
        imported = {
            (node.module or "").split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        } | {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        assert imported <= set(sys.stdlib_module_names) | {"__future__"}, (name, imported)
