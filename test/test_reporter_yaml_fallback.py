"""The test reporter's summary falls back to JSON when a value is not YAML-representable."""

from __future__ import annotations

import enum
import json
from pathlib import Path

import yaml

from test.helpers.reporter import Reporter


class _Color(enum.Enum):
    RED = 1


def _reporter(tmp_path: Path) -> Reporter:
    return Reporter(run_id="run", test_id="t", artifacts_dir=tmp_path, emit_yaml=True)


def test_unrepresentable_value_writes_a_complete_json_summary(tmp_path: Path) -> None:
    reporter = _reporter(tmp_path)
    reporter.emit("step", color=_Color.RED)
    reporter.finalize()
    summary = json.loads((tmp_path / "run.summary.yaml").read_text(encoding="utf-8"))
    assert summary["record_count"] == 1
    assert summary["records"][0]["color"] == "_Color.RED"


def test_plain_values_still_write_yaml(tmp_path: Path) -> None:
    reporter = _reporter(tmp_path)
    reporter.emit("step", value=3)
    reporter.finalize()
    text = (tmp_path / "run.summary.yaml").read_text(encoding="utf-8")
    assert not text.lstrip().startswith("{")
    assert yaml.safe_load(text)["records"][0]["value"] == 3
