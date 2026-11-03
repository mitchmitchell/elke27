"""Every Dealer API ``area_get_status`` arm_state value maps to the right ArmMode (#100)."""

from __future__ import annotations

import logging

import pytest

from elke27_lib import client as client_mod
from elke27_lib.client import Elke27Client
from elke27_lib.types import AreaState, ArmMode
from test.helpers.internal import feed_panel_message


def _doc_status(arm_state: str, **fields: object) -> dict[str, object]:
    """A documented ``area.get_status`` response, with arm_state and any given fields replaced."""
    payload: dict[str, object] = {
        "area_id": 1,
        "arm_state": arm_state,
        "arm_cmd_state": "DISARMED",
        "ready_status": "RDY_NOT",
        "ee_timer": 0,
        "Chime": False,
        "alarms": "",
        "alarm_mem": "",
        "alrm_snd": "",
        "troubles": "",
        "alarm_zone": "",
        "zones_bypassed": 0,
        "xzn_time": 0,
        "xzn_id": 0,
        "auto_arm_timer": 0,
        "chime_count": 0,
        "error_code": 0,
    }
    payload.update(fields)
    return payload


async def _area_after(payload: dict[str, object]) -> AreaState:
    client = Elke27Client()
    await feed_panel_message(client, {"seq": 0, "area": {"get_status": payload}})
    return client.snapshot.areas[1]


@pytest.mark.parametrize(
    ("arm_state", "expected"),
    [
        ("DISARMED", ArmMode.DISARMED),
        ("ARMED_STAY", ArmMode.ARMED_STAY),
        ("ARMED_AWAY", ArmMode.ARMED_AWAY),
        ("ARMED_STAY_INST", ArmMode.ARMED_STAY),
        ("ARMED_VACATION", ArmMode.ARMED_VACATION),
        ("ALARM_MEM", None),
    ],
)
@pytest.mark.asyncio
async def test_doc_arm_state_maps_to_arm_mode(arm_state: str, expected: ArmMode | None) -> None:
    assert (await _area_after(_doc_status(arm_state))).arm_mode is expected


@pytest.mark.asyncio
async def test_vacation_is_not_disarmed_or_away() -> None:
    area = await _area_after(_doc_status("ARMED_VACATION"))
    assert area.arm_mode is ArmMode.ARMED_VACATION
    assert area.arming is False


@pytest.mark.parametrize("arm_cmd_state", ["ARMED_AWAY", "ARMED_STAY", "ARMED_VACATION"])
@pytest.mark.asyncio
async def test_exit_delay_is_arming_for_each_commanded_mode(arm_cmd_state: str) -> None:
    area = await _area_after(_doc_status("DISARMED", arm_cmd_state=arm_cmd_state, ee_timer=30))
    assert area.arm_mode is ArmMode.DISARMED
    assert area.arming is True


@pytest.mark.asyncio
async def test_vacation_exit_delay_ended_is_not_arming() -> None:
    area = await _area_after(_doc_status("DISARMED", arm_cmd_state="ARMED_VACATION", ee_timer=0))
    assert area.arming is False


@pytest.mark.asyncio
async def test_unknown_arm_state_is_none_and_warns_once(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger=client_mod.__name__):
        first = await _area_after(_doc_status("ARMED_SOMETHING_NEW"))
        second = await _area_after(_doc_status("ARMED_SOMETHING_NEW"))
    assert first.arm_mode is None
    assert second.arm_mode is None
    warnings = [r for r in caplog.records if "ARMED_SOMETHING_NEW" in r.getMessage()]
    assert len(warnings) == 1


@pytest.mark.asyncio
async def test_alarm_mem_arm_state_does_not_warn(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger=client_mod.__name__):
        area = await _area_after(_doc_status("ALARM_MEM"))
    assert area.alarm_memory is True
    assert not [r for r in caplog.records if "ALARM_MEM" in r.getMessage()]


@pytest.mark.parametrize(
    ("alarm_mem", "expected"),
    [("", False), ("WATER", True), ("BURG", True)],
)
@pytest.mark.asyncio
async def test_alarm_mem_field_sets_alarm_memory(alarm_mem: str, expected: bool) -> None:
    area = await _area_after(_doc_status("DISARMED", alarm_mem=alarm_mem))
    assert area.alarm_memory is expected
