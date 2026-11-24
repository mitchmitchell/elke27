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


NO_SUPPLEMENT: dict[tuple[str, str], frozenset[str]] = {}


@pytest.fixture
def no_supplement(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(extractor, "REVIEWED_SUPPLEMENT", NO_SUPPLEMENT)


def _write_sample(tmp_path: Path, text: str = SAMPLE) -> Path:
    doc = tmp_path / "reference.txt"
    doc.write_text(text, encoding="utf-8")
    return doc


def _fields(text: str) -> dict[tuple[str, str], frozenset[str]]:
    return dict(extractor.extract(text.splitlines(), NO_SUPPLEMENT).fields)


def test_extract_reads_response_and_broadcast_fields_only() -> None:
    extraction = extractor.extract(SAMPLE.splitlines(), NO_SUPPLEMENT)

    assert dict(extraction.fields) == {
        ("widget", "get_status"): frozenset(
            {"widget_id", "Mode", "flags", "error_code", "error_message"}
        ),
        ("widget", "changed"): frozenset({"widget_id", "Mode"}),
        ("widget", "get_name"): frozenset({"name", "error_code"}),
    }
    assert dict(extraction.group_fields) == {"widget": frozenset({"get_mode"})}


def test_extract_joins_wrapped_examples_and_keeps_first_location() -> None:
    extraction = extractor.extract(SAMPLE.splitlines(), NO_SUPPLEMENT)

    assert extraction.locations[("widget", "get_status")] == {
        "widget_id": 6,
        "Mode": 6,
        "flags": 6,
        "error_code": 6,
        "error_message": 10,
    }


def test_extract_reports_examples_that_are_not_json() -> None:
    extraction = extractor.extract(SAMPLE.splitlines(), NO_SUPPLEMENT)

    assert list(extraction.unparsed) == [14, 17]


def test_scanner_ignores_a_closing_brace_inside_a_string() -> None:
    text = '  ▪ {"seq":0,"widget":{"get_label":{"label":"a } b","error_code":0}}} .\n'

    assert _fields(text) == {("widget", "get_label"): frozenset({"label", "error_code"})}


def test_scanner_keeps_an_escaped_quote_inside_a_string() -> None:
    text = '  ▪ {"seq":0,"widget":{"get_label":{"label":"a \\" } b","error_code":0}}} .\n'

    assert _fields(text) == {("widget", "get_label"): frozenset({"label", "error_code"})}


def test_extract_skips_object_fragments_without_seq() -> None:
    text = (
        '  ▪ {"widget":{"get_label":{"label":"x"}}}\n  ▪ {"seq":0,"widget":{"changed":{"a":1}}}\n'
    )

    assert _fields(text) == {("widget", "changed"): frozenset({"a"})}


def test_every_non_object_command_value_becomes_a_group_field() -> None:
    text = (
        '  ▪ {"seq":0,"walktest":{"walktest_total":16,"walktest_tested":0}}\n'
        '  ▪ {"seq":1,"control":{"rebooting":3}}\n'
        '  ▪ {"seq":0,"network":{"get_ssid":["one","two"],"error_code":0}}\n'
        '  ▪ {"seq":0,"network":{"get_rssi":{"rssi":41,"error_code":0}}}\n'
    )

    extraction = extractor.extract(text.splitlines(), NO_SUPPLEMENT)

    assert dict(extraction.fields) == {("network", "get_rssi"): frozenset({"rssi", "error_code"})}
    assert dict(extraction.group_fields) == {
        "walktest": frozenset({"walktest_total", "walktest_tested"}),
        "control": frozenset({"rebooting"}),
        "network": frozenset({"get_ssid", "error_code"}),
    }
    assert extraction.group_locations["network"] == {"get_ssid": 3, "error_code": 3}
    assert list(extraction.unshaped) == []


def test_extract_reports_responses_whose_group_body_is_not_an_object() -> None:
    text = '  ▪ {"seq":0,"widget":5}\n  ▪ {"seq":0,"widget":{"changed":{"a":1}},"other":[1]}\n'

    extraction = extractor.extract(text.splitlines(), NO_SUPPLEMENT)

    assert list(extraction.unshaped) == [1, 2]
    assert dict(extraction.fields) == {}
    assert dict(extraction.group_fields) == {}


def test_each_round_bullet_ends_an_unbalanced_example() -> None:
    text = (
        '  ▪ {"seq":0,"widget":{"get_code":{"code":"1234\n'
        '  ◦ {"seq":0,"widget":{"get_a":{"a":1}}}\n'
        '  ▪ {"seq":0,"widget":{"get_code":{"code":"1234\n'
        '  • {"seq":0,"widget":{"get_b":{"b":1}}}\n'
    )

    extraction = extractor.extract(text.splitlines(), NO_SUPPLEMENT)

    assert dict(extraction.fields) == {
        ("widget", "get_a"): frozenset({"a"}),
        ("widget", "get_b"): frozenset({"b"}),
    }
    assert list(extraction.unparsed) == [1, 3]


def test_a_wrapped_line_starting_with_a_minus_or_star_is_joined() -> None:
    text = (
        '  - {"seq":0,"widget":{"get_pos":{"long":\n'
        '    -81.5,"lat":35.7}}}\n'
        '  * {"seq":0,"widget":{"get_note":{"note":"a\n'
        '    * b"}}}\n'
    )

    extraction = extractor.extract(text.splitlines(), NO_SUPPLEMENT)

    assert dict(extraction.fields) == {
        ("widget", "get_pos"): frozenset({"long", "lat"}),
        ("widget", "get_note"): frozenset({"note"}),
    }
    assert list(extraction.unparsed) == []


MALFORMED_TROUBLE = """\
  ▪ {"seq":0,"widget":{"get_trouble":{"widget_id":1,"","error_code":0}}}
  ▪ {"seq":0,"widget":{"changed":{"a":1}}}
"""
TROUBLE_SUPPLEMENT = {("widget", "get_trouble"): frozenset({"widget_id", "error_code"})}


def test_supplement_fills_a_type_whose_only_example_is_malformed() -> None:
    extraction = extractor.extract(MALFORMED_TROUBLE.splitlines(), TROUBLE_SUPPLEMENT)

    assert dict(extraction.fields) == {
        ("widget", "get_trouble"): frozenset({"widget_id", "error_code"}),
        ("widget", "changed"): frozenset({"a"}),
    }
    assert extraction.locations[("widget", "get_trouble")] == {"widget_id": 1, "error_code": 1}
    assert extraction.supplemented == frozenset({("widget", "get_trouble")})
    assert list(extraction.unparsed) == [1]


def test_supplement_entry_with_a_valid_example_is_refused() -> None:
    text = MALFORMED_TROUBLE + '  ▪ {"seq":0,"widget":{"get_trouble":{"widget_id":1}}}\n'

    with pytest.raises(extractor.SupplementError, match="valid example"):
        extractor.extract(text.splitlines(), TROUBLE_SUPPLEMENT)


def test_supplement_entry_without_a_malformed_example_is_refused() -> None:
    supplement = {("widget", "get_other"): frozenset({"widget_id"})}

    with pytest.raises(extractor.SupplementError, match="no malformed example"):
        extractor.extract(MALFORMED_TROUBLE.splitlines(), supplement)


def test_reviewed_supplement_names_the_two_phase_one_types() -> None:
    assert dict(extractor.REVIEWED_SUPPLEMENT) == {
        ("area", "get_trouble"): frozenset({"area_id", "error_code"}),
        ("zone", "get_all_zones_status"): frozenset({"status"}),
    }
    for message_type, names in extractor.REVIEWED_SUPPLEMENT.items():
        assert protocol_manifest.DOCUMENTED_FIELDS[message_type] == names


def test_rendered_manifest_round_trips_and_is_sorted() -> None:
    fields = {("b", "y"): {"z", "a"}, ("a", "x"): {"k"}}
    group_fields = {"q": {"n", "m"}, "p": {"o"}}

    source = extractor.render_manifest(fields, group_fields)
    namespace: dict[str, object] = {}
    exec(compile(source, "<manifest>", "exec"), namespace)

    assert namespace["DOCUMENTED_FIELDS"] == {("a", "x"): {"k"}, ("b", "y"): {"a", "z"}}
    assert namespace["DOCUMENTED_GROUP_FIELDS"] == {"p": {"o"}, "q": {"m", "n"}}
    assert source.index('("a", "x")') < source.index('("b", "y")')
    assert source.index('"a",') < source.index('"z",')
    assert source.index('"p":') < source.index('"q":')
    assert source.index('"m",') < source.index('"n",')


def test_checked_in_manifest_is_exactly_generator_output() -> None:
    path = ROOT / "src" / "elke27_lib" / "protocol_manifest.py"

    rendered = extractor.render_manifest(
        protocol_manifest.DOCUMENTED_FIELDS, protocol_manifest.DOCUMENTED_GROUP_FIELDS
    )

    assert path.read_text(encoding="utf-8") == rendered


def test_manifest_has_field_names_for_every_message_type() -> None:
    fields = protocol_manifest.DOCUMENTED_FIELDS

    assert fields
    for (group, command), names in fields.items():
        assert group and command
        assert names
        assert all(isinstance(name, str) and name for name in names)
    for group, names in protocol_manifest.DOCUMENTED_GROUP_FIELDS.items():
        assert group
        assert names
        assert all(isinstance(name, str) and name for name in names)


def test_system_attribs_lists_burg_supervision_time_in_one_spelling() -> None:
    names = protocol_manifest.DOCUMENTED_FIELDS[("system", "get_attribs")]

    assert "Burg Supervision Time" in names
    assert "BurgSupervision Time" not in names
    matrix = (ROOT / "docs" / "audit" / "field-matrix" / "system_get_attribs.md").read_text(
        encoding="utf-8"
    )
    assert matrix.count("| `Burg Supervision Time` |") == 1
    assert "BurgSupervision" not in matrix


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
    assert extractor.extract(lines, NO_SUPPLEMENT).locations[("widget", "changed")] == {"Mode": 2}


@pytest.mark.usefixtures("no_supplement")
def test_main_writes_manifest_and_private_locations(tmp_path: Path) -> None:
    doc = _write_sample(tmp_path)
    output = tmp_path / "manifest.py"
    locations = tmp_path / "locations.md"

    code = extractor.main([str(doc), "--output", str(output), "--locations", str(locations)])

    assert code == 0
    extraction = extractor.extract(SAMPLE.splitlines(), NO_SUPPLEMENT)
    assert output.read_text(encoding="utf-8") == extractor.render_manifest(
        extraction.fields, extraction.group_fields
    )
    assert "line" not in output.read_text(encoding="utf-8")
    assert "## widget.get_status" in locations.read_text(encoding="utf-8")
    assert "- `error_message`: line 10" in locations.read_text(encoding="utf-8")


@pytest.mark.usefixtures("no_supplement")
def test_main_check_flags_drift_without_writing(tmp_path: Path) -> None:
    doc = _write_sample(tmp_path)
    output = tmp_path / "manifest.py"
    output.write_text("stale\n", encoding="utf-8")

    assert extractor.main([str(doc), "--output", str(output), "--check"]) == 1
    assert output.read_text(encoding="utf-8") == "stale\n"

    assert extractor.main([str(doc), "--output", str(output)]) == 0
    assert extractor.main([str(doc), "--output", str(output), "--check"]) == 0


@pytest.mark.usefixtures("no_supplement")
def test_main_check_with_locations_writes_nothing(tmp_path: Path) -> None:
    doc = _write_sample(tmp_path)
    output = tmp_path / "manifest.py"
    output.write_text("stale\n", encoding="utf-8")
    locations = tmp_path / "locations.md"

    code = extractor.main(
        [str(doc), "--output", str(output), "--check", "--locations", str(locations)]
    )

    assert code == 2
    assert not locations.exists()
    assert output.read_text(encoding="utf-8") == "stale\n"


def test_main_refuses_a_stale_supplement(tmp_path: Path) -> None:
    doc = _write_sample(tmp_path)
    output = tmp_path / "manifest.py"

    assert extractor.main([str(doc), "--output", str(output)]) == 2
    assert not output.exists()


def test_main_marks_supplemented_and_group_locations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(extractor, "REVIEWED_SUPPLEMENT", TROUBLE_SUPPLEMENT)
    doc = _write_sample(tmp_path, MALFORMED_TROUBLE + '  ▪ {"seq":1,"control":{"rebooting":3}}\n')
    output = tmp_path / "manifest.py"
    locations = tmp_path / "locations.md"

    assert extractor.main([str(doc), "--output", str(output), "--locations", str(locations)]) == 0

    report = locations.read_text(encoding="utf-8")
    assert "## widget.get_trouble (reviewed supplement; malformed example)\n" in report
    assert "## widget.changed\n" in report
    assert "## control (group-level fields)\n- `rebooting`: line 3\n" in report


@pytest.mark.usefixtures("no_supplement")
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


def test_extractor_root_is_the_repository_root() -> None:
    assert extractor.ROOT == ROOT


@pytest.mark.usefixtures("no_supplement")
def test_main_refuses_locations_inside_the_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    monkeypatch.setattr(extractor, "ROOT", repo)
    doc = _write_sample(tmp_path)
    output = tmp_path / "manifest.py"
    inside = repo / "docs" / "locations.md"
    inside.parent.mkdir(parents=True)

    code = extractor.main([str(doc), "--output", str(output), "--locations", str(inside)])

    assert code == 2
    assert not inside.exists()
    assert not output.exists()
