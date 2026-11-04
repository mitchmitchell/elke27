from __future__ import annotations

import logging

import pytest

from elke27_lib.const import E27ErrorCode
from elke27_lib.dispatcher import DispatchContext
from elke27_lib.events import ApiError, AreaStatusUpdated, Event
from elke27_lib.handlers.area import make_area_get_status_handler
from elke27_lib.states import PanelState
from test.helpers.dispatch import make_ctx


class _EmitSpy:
    def __init__(self) -> None:
        self.events: list[Event] = []

    def __call__(self, evt: Event, _ctx: DispatchContext) -> None:
        self.events.append(evt)


_Ctx = make_ctx


def _doc_water_alarm() -> dict[str, object]:
    """Documented reply shape: WATER alarm active."""
    return {
        "area_id": 1,
        "arm_state": "DISARMED",
        "arm_cmd_state": "DISARMED",
        "ready_status": "RDY_NOT",
        "ee_timer": 0,
        "Chime": False,
        "alarms": "WATER",
        "alarm_mem": "",
        "alrm_snd": "WATER",
        "troubles": "",
        "alarm_zone": "Bathroom water",
        "zones_bypassed": 0,
        "xzn_time": 0,
        "xzn_id": 0,
        "auto_arm_timer": 0,
        "chime_count": 0,
        "error_code": 0,
    }


def _doc_restored() -> dict[str, object]:
    """Documented reply shape: WATER alarm acknowledged and restored."""
    payload = _doc_water_alarm()
    payload.update(ready_status="RDY_AWAY", alarms="", alrm_snd="", alarm_zone="")
    return payload


def test_area_get_status_updates_state_and_emits_event() -> None:
    state = PanelState()
    emit = _EmitSpy()
    handler = make_area_get_status_handler(state, emit, now=lambda: 123.0)

    assert handler({"seq": 1, "area": {"get_status": _doc_water_alarm()}}, _Ctx()) is True
    area = state.areas[1]
    assert area.arm_state == "DISARMED"
    assert area.arm_cmd_state == "DISARMED"
    assert area.ready_status == "RDY_NOT"
    assert area.alarm_zone == "Bathroom water"
    assert area.chime is False
    assert area.alarm_state is None
    assert any(isinstance(e, AreaStatusUpdated) for e in emit.events)


@pytest.mark.parametrize(
    ("troubles", "expected"),
    [("", ""), ("FIRE TROUBLE", "FIRE TROUBLE"), ("CO TROUBLE", "CO TROUBLE")],
)
def test_area_get_status_reads_documented_troubles(troubles: str, expected: str) -> None:
    """The documented string ``troubles`` field is read (#102)."""
    state = PanelState()
    handler = make_area_get_status_handler(state, _EmitSpy(), now=lambda: 123.0)
    payload = _doc_restored()
    payload["troubles"] = troubles
    assert handler({"seq": 1, "area": {"get_status": payload}}, _Ctx()) is True
    assert state.areas[1].trouble_status == expected


def test_area_get_status_ignores_undocumented_trouble_bool() -> None:
    """The invented ``trouble`` bool key is not a documented field and is not read (#102)."""
    state = PanelState()
    handler = make_area_get_status_handler(state, _EmitSpy(), now=lambda: 123.0)
    payload = _doc_restored()
    payload["trouble"] = True
    assert handler({"seq": 1, "area": {"get_status": payload}}, _Ctx()) is True
    assert state.areas[1].trouble_status == ""


def test_area_get_status_error_code_emits_api_error() -> None:
    state = PanelState()
    emit = _EmitSpy()
    handler = make_area_get_status_handler(state, emit, now=lambda: 123.0)

    msg = {"area": {"get_status": {"area_id": 1, "error_code": E27ErrorCode.ELKERR_INVALID_PARAM}}}

    assert handler(msg, _Ctx()) is True
    assert any(isinstance(e, ApiError) for e in emit.events)


def test_area_get_status_no_changes_logs_debug_not_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """#53: an unchanged status re-read (e.g. after a disarm) is expected; DEBUG only."""
    state = PanelState()
    emit = _EmitSpy()
    handler = make_area_get_status_handler(state, emit, now=lambda: 123.0)
    msg = {"seq": 1, "area": {"get_status": _doc_restored()}}
    assert handler(msg, _Ctx()) is True

    caplog.set_level(logging.DEBUG, logger="elke27_lib.handlers.area")
    assert handler(msg, _Ctx()) is True

    no_changes = [r for r in caplog.records if "area.get_status no changes" in r.getMessage()]
    assert [r.levelno for r in no_changes] == [logging.DEBUG]
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
