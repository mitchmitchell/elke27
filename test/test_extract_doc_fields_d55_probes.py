"""Decision 55 probes for #160: group-level fields, request skipping and reporting."""

from __future__ import annotations

from pathlib import Path

import pytest

from test.helpers.devtools import load

extractor = load("extract_doc_fields")
NO_SUPPLEMENT: dict[tuple[str, str], frozenset[str]] = {}


def test_group_with_only_object_commands_has_no_group_fields() -> None:
    text = '  ▪ {"seq":0,"zone":{"get_x":{"a":1}}}\n'
    extraction = extractor.extract(text.splitlines(), NO_SUPPLEMENT)
    assert dict(extraction.group_fields) == {}
    assert dict(extraction.group_locations) == {}


def test_requests_with_session_id_are_skipped() -> None:
    text = (
        '  ▪ {"seq":1,"session_id":7,"zone":{"get_x":{"req":1}}}\n'
        '  ▪ {"seq":1,"session_id":7,"zone":{"flat":3}}\n'
    )
    extraction = extractor.extract(text.splitlines(), NO_SUPPLEMENT)
    assert dict(extraction.fields) == {}
    assert dict(extraction.group_fields) == {}
    assert list(extraction.unshaped) == []


def test_group_fields_from_several_examples_are_merged_first_line_kept() -> None:
    text = (
        '  ▪ {"seq":0,"walktest":{"walktest_total":16}}\n'
        '  ▪ {"seq":0,"walktest":{"walktest_tested":1}}\n'
        '  ▪ {"seq":0,"walktest":{"walktest_total":15}}\n'
    )
    extraction = extractor.extract(text.splitlines(), NO_SUPPLEMENT)
    assert extraction.group_fields["walktest"] == frozenset({"walktest_total", "walktest_tested"})
    assert extraction.group_locations["walktest"] == {"walktest_total": 1, "walktest_tested": 2}


def test_supplement_matches_a_malformed_example_written_with_curly_quotes() -> None:
    text = "  ▪ {\u201cseq\u201d:0,\u201carea\u201d:{\u201cget_trouble\u201d:{\u201carea_id\u201d:1,}}}\n"
    supplement = {("area", "get_trouble"): frozenset({"area_id"})}
    extraction = extractor.extract(text.splitlines(), supplement)
    assert extraction.fields[("area", "get_trouble")] == frozenset({"area_id"})
    assert extraction.locations[("area", "get_trouble")] == {"area_id": 1}


def test_main_reports_unshaped_responses_on_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(extractor, "REVIEWED_SUPPLEMENT", NO_SUPPLEMENT)
    doc = tmp_path / "ref.txt"
    doc.write_text('  ▪ {"seq":0,"zone":[1,2]}\n  ▪ {"seq":0,"zone":{"get_x":{"a":1}}}\n')
    output = tmp_path / "manifest.py"
    assert extractor.main([str(doc), "--output", str(output)]) == 0
    assert "skipped 1 responses whose group body is not an object" in capsys.readouterr().err
