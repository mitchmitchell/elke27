"""Regression: an area alarm reported in get_status must set alarm_active."""

from __future__ import annotations

import pytest

from elke27_lib.const import E27ErrorCode
from elke27_lib.handlers.area import area_alarm_active, make_area_get_status_handler
from elke27_lib.states import PanelState
from test.helpers.dispatch import make_ctx


def _status(**fields: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "area_id": 1,
        "arm_state": "ARMED_AWAY",
        "arm_cmd_state": "ARMED_AWAY",
        "ready_status": "RDY_NOT",
        "ee_timer": 0,
        "Chime": False,
        "alarms": "",
        "alarm_mem": "",
        "alrm_snd": "",
        "troubles": "",
        "alarm_zone": "",
        "zones_bypassed": 0,
        "error_code": E27ErrorCode.ELKERR_NONE,
    }
    payload.update(fields)
    return payload


def _alarm_active_after(*payloads: dict[str, object]) -> bool:
    state = PanelState()
    handler = make_area_get_status_handler(state, lambda _e, _c: None, now=lambda: 1.0)
    for payload in payloads:
        assert handler({"area": {"get_status": payload}}, make_ctx()) is True
    return area_alarm_active(state.areas[1])


@pytest.mark.parametrize(
    "fields",
    [
        {"alarms": "BURG", "alrm_snd": "BURG", "alarm_zone": "Front door"},
        {"alarms": "FIRE"},
        {"alarms": ["BURG"]},
        {"alrm_snd": True},
    ],
)
def test_reported_alarm_sets_alarm_active(fields: dict[str, object]) -> None:
    assert _alarm_active_after(_status(**fields)) is True


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"alarms": [], "alrm_snd": False},
        {"alarms": "FIRE TROUBLE"},
        {"alarms": "CO TROUBLE"},
        {"alarms": "FIRE TROUBLE", "alrm_snd": "FIRE TROUBLE"},
        {"alarms": "", "alrm_snd": "CO TROUBLE"},
    ],
)
def test_no_alarm_leaves_alarm_active_false(fields: dict[str, object]) -> None:
    assert _alarm_active_after(_status(**fields)) is False


def test_alarm_clears_when_panel_reports_empty_alarms() -> None:
    assert (
        _alarm_active_after(
            _status(alarms="BURG", alrm_snd="BURG"), _status(alarms="", alrm_snd="")
        )
        is False
    )
