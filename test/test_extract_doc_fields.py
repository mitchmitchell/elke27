"""Tests for devtools/extract_doc_fields.py and the checked-in protocol manifest."""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from elke27_lib import protocol_manifest

ROOT = Path(__file__).resolve().parent.parent

SAMPLE = """\
Global widget_get_status (ID_NONCE_STRUCT *id_nonce, cJSON *root)
  • Command Response Examples
       ◦ Request
             ▪ {"seq":1,"session_id":65536,"widget":{"get_status":{"widget_id":1}}}
       ◦ Response
             ▪ {"seq":1,"widget":{"get_status":{"widget_id":
               1,"Mode":"OFF","flags":[{"Long
               Name":false}],"error_code":0}}} .
       ◦ Response failed
             ▪ {"seq":1,"widget":{"get_status":{"widget_id":9,"error_code":11006,
               “error_message”:”invalid_id”}}}
  Broadcast
       ▪ {"seq":0,"widget":{"changed":{"widget_id":2,"Mode":"ON"}}}
       ▪ {"seq":0,"widget":{"get_avail":"available":"FF","error_code":0}}
       ▪ {"Mode":"ON"}
       ▪ {"seq":0,"widget":{"get_mode":true}}
       ▪ {"seq":0,"widget":{"get_code":{"code":"1234
       ◦ Response
             ▪ {"seq":0,"widget":{"get_name":{"name":"Front","error_code":0}}}
"""


def _load() -> ModuleType:
    path = ROOT / "devtools" / "extract_doc_fields.py"
    spec = importlib.util.spec_from_file_location("extract_doc_fields", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["extract_doc_fields"] = module
    spec.loader.exec_module(module)
    return module


extractor = _load()


def _write_sample(tmp_path: Path) -> Path:
    doc = tmp_path / "reference.txt"
    doc.write_text(SAMPLE, encoding="utf-8")
    return doc


def test_extract_reads_response_and_broadcast_fields_only() -> None:
    extraction = extractor.extract(SAMPLE.splitlines())

    assert dict(extraction.fields) == {
        ("widget", "get_status"): frozenset(
            {"widget_id", "Mode", "flags", "error_code", "error_message"}
        ),
        ("widget", "changed"): frozenset({"widget_id", "Mode"}),
        ("widget", "get_name"): frozenset({"name", "error_code"}),
    }


def test_extract_joins_wrapped_examples_and_keeps_first_location() -> None:
    extraction = extractor.extract(SAMPLE.splitlines())

    assert extraction.locations[("widget", "get_status")] == {
        "widget_id": 6,
        "Mode": 6,
        "flags": 6,
        "error_code": 6,
        "error_message": 10,
    }


def test_extract_reports_examples_that_are_not_json() -> None:
    extraction = extractor.extract(SAMPLE.splitlines())

    assert list(extraction.unparsed) == [14, 17]


def test_rendered_manifest_round_trips_and_is_sorted() -> None:
    fields = {("b", "y"): {"z", "a"}, ("a", "x"): {"k"}}

    source = extractor.render_manifest(fields)
    namespace: dict[str, object] = {}
    exec(compile(source, "<manifest>", "exec"), namespace)

    assert namespace["DOCUMENTED_FIELDS"] == {("a", "x"): {"k"}, ("b", "y"): {"a", "z"}}
    assert source.index('("a", "x")') < source.index('("b", "y")')
    assert source.index('"a",') < source.index('"z",')


def test_checked_in_manifest_is_exactly_generator_output() -> None:
    path = ROOT / "src" / "elke27_lib" / "protocol_manifest.py"

    rendered = extractor.render_manifest(protocol_manifest.DOCUMENTED_FIELDS)

    assert path.read_text(encoding="utf-8") == rendered


def test_manifest_has_field_names_for_every_message_type() -> None:
    fields = protocol_manifest.DOCUMENTED_FIELDS

    assert fields
    for (group, command), names in fields.items():
        assert group and command
        assert names
        assert all(isinstance(name, str) and name for name in names)


def test_no_library_module_imports_the_manifest() -> None:
    importers: list[str] = []
    for path in (ROOT / "src" / "elke27_lib").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or "", *(alias.name for alias in node.names)]
            if any("protocol_manifest" in name for name in names):
                importers.append(path.name)

    assert importers == []


def test_read_lines_keeps_page_breaks_inside_lines(tmp_path: Path) -> None:
    doc = tmp_path / "reference.txt"
    doc.write_text(
        'one\x0cstill one\n  ▪ {"seq":0,"widget":{"changed":{"Mode":"ON"}}}\n', encoding="utf-8"
    )

    lines = extractor.read_lines(doc)

    assert lines[0] == "one\x0cstill one"
    assert extractor.extract(lines).locations[("widget", "changed")] == {"Mode": 2}


def test_main_writes_manifest_and_private_locations(tmp_path: Path) -> None:
    doc = _write_sample(tmp_path)
    output = tmp_path / "manifest.py"
    locations = tmp_path / "locations.md"

    code = extractor.main([str(doc), "--output", str(output), "--locations", str(locations)])

    assert code == 0
    assert output.read_text(encoding="utf-8") == extractor.render_manifest(
        extractor.extract(SAMPLE.splitlines()).fields
    )
    assert "line" not in output.read_text(encoding="utf-8")
    assert "## widget.get_status" in locations.read_text(encoding="utf-8")
    assert "- `error_message`: line 10" in locations.read_text(encoding="utf-8")


def test_main_check_flags_drift_without_writing(tmp_path: Path) -> None:
    doc = _write_sample(tmp_path)
    output = tmp_path / "manifest.py"
    output.write_text("stale\n", encoding="utf-8")

    assert extractor.main([str(doc), "--output", str(output), "--check"]) == 1
    assert output.read_text(encoding="utf-8") == "stale\n"

    assert extractor.main([str(doc), "--output", str(output)]) == 0
    assert extractor.main([str(doc), "--output", str(output), "--check"]) == 0


def test_main_reads_reference_path_from_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    doc = _write_sample(tmp_path)
    output = tmp_path / "manifest.py"
    monkeypatch.setenv(extractor.DOC_ENV, str(doc))

    assert extractor.main(["--output", str(output)]) == 0
    assert output.is_file()


def test_main_requires_a_reference_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(extractor.DOC_ENV, raising=False)

    assert extractor.main(["--output", str(tmp_path / "manifest.py")]) == 2
    assert extractor.main([str(tmp_path / "absent.txt")]) == 2


def test_main_refuses_locations_inside_the_repository(tmp_path: Path) -> None:
    doc = _write_sample(tmp_path)
    output = tmp_path / "manifest.py"
    inside = ROOT / "docs" / "locations.md"

    code = extractor.main([str(doc), "--output", str(output), "--locations", str(inside)])

    assert code == 2
    assert not inside.exists()
    assert not output.exists()
