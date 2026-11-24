"""Tests for devtools/loopcheck.py against fixtures in test/fixtures/loopcheck."""

from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "test" / "fixtures" / "loopcheck"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("loopcheck", ROOT / "devtools" / "loopcheck.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["loopcheck"] = module
    spec.loader.exec_module(module)
    return module


loopcheck = _load()


def _config(**overrides: object):
    config = loopcheck.Config(root=FIXTURES)
    for key, value in overrides.items():
        setattr(config, key, value)
    return config


def _codes(name: str) -> list[tuple[str, int]]:
    path = FIXTURES / name
    findings = loopcheck.check_source(path.read_text(encoding="utf-8"), path, _config())
    return [(f.code, f.line) for f in findings]


BAD = {
    "bad_elk101_loop.py": [("ELK101", 5)],
    "bad_elk101_alias_loop.py": [("ELK101", 5)],
    "bad_elk102_loop.py": [("ELK002", 1), ("ELK102", 5), ("ELK102", 6)],
    "bad_elk103_loop.py": [("ELK002", 1), ("ELK103", 5)],
    "bad_elk104_loop.py": [("ELK104", 5)],
    "bad_elk104_alias_loop.py": [("ELK002", 1), ("ELK104", 5)],
    "bad_elk105_loop.py": [("ELK105", 2)],
    "bad_elk106_loop.py": [("ELK106", 9)],
    "bad_elk107_loop.py": [("ELK107", 2)],
    "bad_elk108_loop.py": [("ELK002", 1), ("ELK108", 6)],
    "bad_elk109_loop.py": [("ELK109", 5)],
    "bad_elk110_loop.py": [("ELK110", 5)],
    "bad_unsuffixed_imports_session.py": [("ELK001", 1)],
    "bad_noqa_no_reason_loop.py": [("ELK003", 5), ("ELK101", 5)],
    "bad_async_in_thread.py": [("ELK004", 1)],
}


@pytest.mark.parametrize(("name", "expected"), sorted(BAD.items()))
def test_bad_fixture_fails_with_exactly_its_code_and_line(
    name: str, expected: list[tuple[str, int]]
) -> None:
    assert sorted(_codes(name)) == sorted(expected)


@pytest.mark.parametrize(
    "name", ["good_loop.py", "good_thread.py", "good_noqa_with_reason_loop.py"]
)
def test_good_fixture_passes(name: str) -> None:
    assert _codes(name) == []


def test_every_code_has_a_bad_fixture() -> None:
    covered = {code for findings in BAD.values() for code, _ in findings}
    expected = {f"ELK00{n}" for n in range(1, 5)} | {f"ELK1{n:02d}" for n in range(1, 11)}
    assert expected <= covered


def test_stale_config_entry_is_elk005(tmp_path: Path) -> None:
    config = _config(loop_modules=[FIXTURES / "missing.py"], config_file=FIXTURES / "x.toml")
    findings = loopcheck.check_paths([], config)
    assert [(f.code, f.line) for f in findings] == [("ELK005", 1)]


def test_configured_loop_module_gets_the_full_ban(tmp_path: Path) -> None:
    target = tmp_path / "client.py"
    target.write_text("import time\n\n\ndef f():\n    time.sleep(1)\n", encoding="utf-8")
    config = loopcheck.Config(root=tmp_path, loop_modules=[target])
    findings = loopcheck.check_paths([tmp_path], config)
    assert [(f.code, f.line) for f in findings] == [("ELK101", 5)]


def test_loop_path_directory_scopes_every_file(tmp_path: Path) -> None:
    pkg = tmp_path / "handlers"
    pkg.mkdir()
    (pkg / "zone.py").write_text("def f():\n    return input()\n", encoding="utf-8")
    config = loopcheck.Config(root=tmp_path, loop_paths=[pkg])
    findings = loopcheck.check_paths([tmp_path], config)
    assert [(f.code, f.render().split()[0]) for f in findings] == [
        ("ELK107", "handlers/zone.py:2:12")
    ]


def test_reasoned_noqa_cannot_silence_elk003(tmp_path: Path) -> None:
    target = tmp_path / "a_loop.py"
    target.write_text(
        "x = 1  # noqa: ELK003 -- reason given here  # type: ignore\n", encoding="utf-8"
    )
    findings = loopcheck.check_paths([target], loopcheck.Config(root=tmp_path))
    assert [f.code for f in findings] == ["ELK003"]


def test_cli_exits_nonzero_and_prints_path_line_col(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = tmp_path / "pyproject.toml"
    cfg.write_text("[tool.elke27.loopcheck]\nloop_modules = []\n", encoding="utf-8")
    (tmp_path / "b_loop.py").write_text("import time\ntime.sleep(1)\n", encoding="utf-8")
    assert loopcheck.main(["--config", str(cfg), str(tmp_path)]) == 1
    assert (
        capsys.readouterr().out.strip() == "b_loop.py:2:1 ELK101 time.sleep blocks the event loop"
    )


def test_cli_exits_zero_when_clean(tmp_path: Path) -> None:
    cfg = tmp_path / "pyproject.toml"
    cfg.write_text("", encoding="utf-8")
    (tmp_path / "c_loop.py").write_text("x = 1\n", encoding="utf-8")
    assert loopcheck.main(["--config", str(cfg), str(tmp_path)]) == 0


def test_wired_into_lint() -> None:
    text = (ROOT / "devtools" / "lint.py").read_text(encoding="utf-8")
    assert '["python", "devtools/loopcheck.py", "src"]' in text


def test_syntax_error_is_one_elk000_finding_not_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = tmp_path / "pyproject.toml"
    cfg.write_text("", encoding="utf-8")
    (tmp_path / "broken_loop.py").write_text("x = 1\ndef f(:\n", encoding="utf-8")
    assert loopcheck.main(["--config", str(cfg), str(tmp_path)]) == 1
    out = capsys.readouterr().out.strip()
    assert out.startswith("broken_loop.py:2:")
    assert " ELK000 syntax error: " in out
    assert len(out.splitlines()) == 1


def test_nonexistent_path_is_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = tmp_path / "pyproject.toml"
    cfg.write_text("", encoding="utf-8")
    missing = tmp_path / "nope"
    with pytest.raises(SystemExit) as exc:
        loopcheck.main(["--config", str(cfg), str(missing)])
    assert exc.value.code == 2
    assert f"no such path: {missing}" in capsys.readouterr().err


def test_hub_is_a_configured_loop_module() -> None:
    config = loopcheck.Config.load(ROOT / "pyproject.toml")
    assert config.is_loop(ROOT / "src" / "elke27_lib" / "hub_loop.py")


def test_each_import_is_recorded_once() -> None:
    imports = loopcheck.ImportTable()
    imports.visit(ast.parse("from . import client\nfrom .hub_loop import Elke27Hub\n"))
    assert [(name, relative) for _, name, relative in imports.imports] == [
        ("client", True),
        ("hub_loop", True),
    ]


def test_builtin_open_and_io_open_are_elk105(tmp_path: Path) -> None:
    target = tmp_path / "f_loop.py"
    target.write_text(
        "import io\n\n\ndef f():\n    open('a')\n    io.open('b')\n",
        encoding="utf-8",
    )
    findings = loopcheck.check_paths([target], loopcheck.Config(root=tmp_path))
    assert [(f.code, f.line, f.message) for f in findings] == [
        ("ELK105", 5, "blocking file I/O open"),
        ("ELK105", 6, "blocking file I/O io.open"),
    ]


def _lock_and_queue_findings(tmp_path: Path, body: str) -> list[tuple[str, int]]:
    target = tmp_path / "w_loop.py"
    target.write_text(
        "import threading\nfrom queue import Queue\n\n\ndef f():\n"
        "    lock = threading.Lock()\n    q = Queue()\n" + body,
        encoding="utf-8",
    )
    findings = loopcheck.check_paths([target], loopcheck.Config(root=tmp_path))
    assert [(f.code, f.line) for f in findings if f.code == "ELK002"] == [("ELK002", 2)]
    return [(f.code, f.line) for f in findings if f.code != "ELK002"]


def test_timeout_keyword_makes_acquire_and_queue_calls_nonblocking(tmp_path: Path) -> None:
    body = "    lock.acquire(timeout=1)\n    q.get(timeout=1)\n    q.put(1, timeout=1)\n"
    assert _lock_and_queue_findings(tmp_path, body) == []


def test_single_positional_blocking_true_is_still_blocking(tmp_path: Path) -> None:
    body = "    lock.acquire(True)\n    q.get(True)\n    q.put(1, True)\n"
    assert _lock_and_queue_findings(tmp_path, body) == [
        ("ELK106", 8),
        ("ELK108", 9),
        ("ELK108", 10),
    ]


def test_positional_timeout_makes_acquire_nonblocking(tmp_path: Path) -> None:
    body = "    lock.acquire(True, 1)\n    q.get(True, 1)\n    q.put(1, True, 1)\n"
    assert _lock_and_queue_findings(tmp_path, body) == []


@pytest.mark.parametrize(
    ("text", "allowed"),
    [
        ("# Copyright (c) 2026 Example", True),
        ("# SPDX-License-Identifier: MIT", True),
        ("# https://docs.astral.sh/ruff/rules/", True),
        ("# https://docs.astral.sh/ruff/rules/ (tests use the public API)", False),
        ("# noqa: BLE001 -- the callback may raise anything", True),
        ("# noqa: BLE001", False),
        ("# type: ignore[assignment] -- stub lacks the overload", True),
        ("# type: ignore[assignment]", False),
        ("# pragma: no cover -- only reached on Windows hosts", True),
        ("# pragma: no cover", False),
        ("# Max wait for a probe to leave the queue.", False),
    ],
)
def test_comment_rule_allows_only_license_urls_and_reasoned_suppressions(
    text: str, allowed: bool
) -> None:
    assert loopcheck.comment_allowed(text, 5) is allowed


def test_comment_rule_reads_python_toml_and_yaml(tmp_path: Path) -> None:
    py = tmp_path / "m.py"
    py.write_text(
        '#!/usr/bin/env python\n"""Doc # not a comment."""\nx = "#"  # why\n', encoding="utf-8"
    )
    toml = tmp_path / "c.toml"
    toml.write_text(
        "# Section banner\n"
        "[tool.ruff.lint]\n"
        "select = [\n"
        '    "E", # https://docs.astral.sh/ruff/rules/#error-e\n'
        '    "B", # bugbear is great\n'
        "]\n"
        "# Long lines are fine in tables.\n"
        "ignore = [\n"
        '    "E501",\n'
        "]\n"
        "[tool.ruff.lint.per-file-ignores]\n"
        '"x/*" = ["ASYNC"]  # thread modules block by design\n'
        'url = "http://a#b"\n',
        encoding="utf-8",
    )
    yml = tmp_path / "w.yml"
    yml.write_text(
        "on:\n  push: # trigger\n    branches: ['a#b']\n# https://example.com/x\n", encoding="utf-8"
    )
    assert loopcheck.disallowed_comments(py, py.read_text(encoding="utf-8")) == [(3, "# why")]
    assert loopcheck.disallowed_comments(toml, toml.read_text(encoding="utf-8")) == [
        (1, "# Section banner"),
        (5, "# bugbear is great"),
    ]
    assert loopcheck.disallowed_comments(yml, yml.read_text(encoding="utf-8")) == [(2, "# trigger")]


def _comment_repo(tmp_path: Path, ceiling: str) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("# old note\nx = 1\ny = 2\n", encoding="utf-8")
    cfg = tmp_path / "pyproject.toml"
    cfg.write_text(
        "[tool.elke27.loopcheck]\n"
        'comment_paths = ["src"]\n'
        'comment_diff_base = "HEAD"\n'
        f"[tool.elke27.loopcheck.comment_ceiling]\n{ceiling}\n",
        encoding="utf-8",
    )
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
    return cfg


def test_comment_ceiling_fails_above_and_below(tmp_path: Path) -> None:
    cfg = _comment_repo(tmp_path, '"src/a.py" = 1')
    assert loopcheck.check_comments(loopcheck.Config.load(cfg)) == []
    (tmp_path / "src" / "a.py").write_text(
        "# old note\nx = 1\n# new note\ny = 2\n", encoding="utf-8"
    )
    found = loopcheck.check_comments(loopcheck.Config.load(cfg))
    assert {(f.line, f.code) for f in found} == {(1, "ELK006"), (3, "ELK006")}
    (tmp_path / "src" / "a.py").write_text("x = 1\ny = 2\n", encoding="utf-8")
    found = loopcheck.check_comments(loopcheck.Config.load(cfg))
    assert [f.message for f in found] == ["comments fell to 0; lower the comment ceiling from 1"]


def test_comment_above_a_changed_line_must_go_even_within_the_ceiling(tmp_path: Path) -> None:
    cfg = _comment_repo(tmp_path, '"src/a.py" = 1')
    (tmp_path / "src" / "a.py").write_text("# old note\nx = 3\ny = 2\n", encoding="utf-8")
    found = loopcheck.check_comments(loopcheck.Config.load(cfg))
    assert [(f.line, f.message[:39]) for f in found] == [
        (1, "comment on or above a changed line; dro")
    ]
    (tmp_path / "src" / "a.py").write_text("# old note\nx = 1\ny = 3\n", encoding="utf-8")
    assert loopcheck.check_comments(loopcheck.Config.load(cfg)) == []


def test_comment_rule_is_configured_for_this_repo() -> None:
    config = loopcheck.Config.load(ROOT / "pyproject.toml")
    assert config.comment_diff_base == "origin/main"
    assert {p.relative_to(ROOT).as_posix() for p in config.comment_paths} == {
        "src",
        "test",
        "devtools",
        "pyproject.toml",
        ".github/workflows",
    }
    counts = {rel: len(hits) for rel, hits in loopcheck.comment_counts(config).items()}
    assert counts == config.comment_ceiling


@pytest.mark.parametrize(
    ("text", "line", "allowed"),
    [
        ("#!/usr/bin/env python3", 1, True),
        ("#!/usr/bin/env python3", 3, False),
        ("# noqa -- blanket without any codes", 5, False),
        ("# noqa: BLE001,SLF001 -- both reach the legacy seam", 5, True),
        ("# type: ignore -- no error code given", 5, False),
        ("# pyright: ignore[reportPrivateUsage] -- legacy seam until #90", 5, True),
        ("# fmt: skip -- keeps the aligned table", 5, True),
        ("# fmt: skip", 5, False),
        ("# SPDX-License-Identifier: MIT", 5, True),
        ("# see SPDX-License-Identifier: anything I like", 5, False),
        ("# explains it -- noqa: E501 -- with words after", 5, False),
    ],
)
def test_comment_rule_suppression_and_header_edges(text: str, line: int, allowed: bool) -> None:
    assert loopcheck.comment_allowed(text, line) is allowed


def test_toml_exclusion_entries_may_carry_a_reason(tmp_path: Path) -> None:
    toml = tmp_path / "c.toml"
    toml.write_text(
        "[tool.ruff]\n"
        "extend-exclude = [\n"
        '    "vendored.py", # vendored upstream; do not edit\n'
        '    "gen.py", # generated\n'
        "]\n"
        "[tool.ruff.lint]\n"
        "select = [\n"
        '    "E", # vendored upstream; do not edit\n'
        "]\n"
        "[tool.basedpyright]\n"
        "# turn off warnings about how you ignore warnings\n"
        "reportIgnoreCommentWithoutRule = false\n",
        encoding="utf-8",
    )
    assert loopcheck.disallowed_comments(toml, toml.read_text(encoding="utf-8")) == [
        (4, "# generated"),
        (8, "# vendored upstream; do not edit"),
        (11, "# turn off warnings about how you ignore warnings"),
    ]


def test_toml_and_yaml_comment_edges(tmp_path: Path) -> None:
    toml = tmp_path / "c.toml"
    toml.write_text(
        "answer = 42# note\n"
        'doc = """\n'
        "# not a comment, inside a string\n"
        '"""\n'
        "lit = '''a # b'''  # after\n",
        encoding="utf-8",
    )
    assert loopcheck.disallowed_comments(toml, toml.read_text(encoding="utf-8")) == [
        (1, "# note"),
        (5, "# after"),
    ]
    yml = tmp_path / "w.yml"
    yml.write_text(
        "name: Mitch's job  # explanation\nq: 'it''s # x'\nr: \"a # b\"  # trailing\n",
        encoding="utf-8",
    )
    assert loopcheck.disallowed_comments(yml, yml.read_text(encoding="utf-8")) == [
        (1, "# explanation"),
        (3, "# trailing"),
    ]


def test_comment_tables_come_from_a_python_file(tmp_path: Path) -> None:
    (tmp_path / "src" / "skip").mkdir(parents=True)
    (tmp_path / "src" / "a.py").write_text("# note\nx = 1\n", encoding="utf-8")
    (tmp_path / "src" / "skip" / "b.py").write_text("# other\n", encoding="utf-8")
    (tmp_path / "ceiling.py").write_text(
        'COMMENT_CEILING: dict[str, int] = {"src/a.py": 1}\nLEGACY_COMMENT_EXCLUDE = {"src/skip"}\n',
        encoding="utf-8",
    )
    cfg = tmp_path / "pyproject.toml"
    cfg.write_text(
        '[tool.elke27.loopcheck]\ncomment_paths = ["src"]\ncomment_ceiling_file = "ceiling.py"\n',
        encoding="utf-8",
    )
    config = loopcheck.Config.load(cfg)
    assert config.comment_ceiling == {"src/a.py": 1}
    assert config.comment_exclude == [tmp_path / "src/skip"]
    assert loopcheck.check_comments(config) == []
    (tmp_path / "ceiling.py").write_text("COMMENT_CEILING = dict(a=1)\n", encoding="utf-8")
    with pytest.raises(ValueError, match="malformed node"):
        loopcheck.Config.load(cfg)
