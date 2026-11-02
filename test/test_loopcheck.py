"""Tests for devtools/loopcheck.py against fixtures in test/fixtures/loopcheck."""

from __future__ import annotations

import importlib.util
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
    target.write_text("x = 1  # type: ignore\n", encoding="utf-8")
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


def test_not_wired_into_lint() -> None:
    assert "loopcheck" not in (ROOT / "devtools" / "lint.py").read_text(encoding="utf-8")
