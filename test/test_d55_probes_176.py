"""Decision 55 probes for #176: the privacc CLI and the devtools loader."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

import test.helpers.devtools as devtools_helper
from test.helpers.devtools import load

privacc = load("privacc")


def test_privacc_cli_exits_on_hits_and_honours_package(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    clean = tmp_path / "clean.py"
    clean.write_text("x = 1\n", encoding="utf-8")
    dirty = tmp_path / "dirty.py"
    dirty.write_text(
        "from homeassistant.core import _cache\npatch('elke27_lib.client._x')\n", encoding="utf-8"
    )
    assert privacc.main([str(clean)]) == 0
    assert privacc.main([str(dirty)]) == 1
    assert privacc.main(["--package", "homeassistant", str(dirty)]) == 1
    out = capsys.readouterr().out.splitlines()
    assert [line for line in out if line.startswith("privacc:")] == [
        "privacc: 0 hit(s)",
        "privacc: 1 hit(s)",
        "privacc: 2 hit(s)",
    ]


def test_loader_keeps_modules_it_did_not_add_from_devtools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "probe_tool.py").write_text("import colorsys\n", encoding="utf-8")
    monkeypatch.setattr(devtools_helper, "DEVTOOLS", tmp_path)
    monkeypatch.delitem(sys.modules, "colorsys", raising=False)
    devtools_helper.load("probe_tool")
    assert "colorsys" in sys.modules
    assert "devtools_probe_tool" not in sys.modules
