"""Arm night maps to Stay Instant (ARMED_STAY_INST) with application-firmware gating (#139)."""

from __future__ import annotations

from typing import Any, cast

import pytest

from elke27_lib import Elke27InvalidArgument, Elke27PanelError, Elke27StayInstantRequiredError
from elke27_lib.client import ArmMode, Elke27Client, Result
from elke27_lib.const import E27ErrorCode
from elke27_lib.handlers.control import make_control_get_version_info_handler
from elke27_lib.states import PanelState
from elke27_lib.types import DelayStateExit, LinkKeys
from test.helpers.firmware_fixtures import NIGHT_ARM_MIN_APP_FIELD, pack_application_firmware
from test.helpers.panel_command_driver import (
    area_set_arm_messages,
    connect_panel,
    connect_with_app_firmware,
    drive_until_done,
    seed_area_disarmed,
)


def test_panel_get_version_info_stores_application_firmware() -> None:
    state = PanelState()
    handler = make_control_get_version_info_handler(state, lambda *_a: None, lambda: 0.0)
    handler(
        {
            "control": {
                "get_version_info": {
                    "app": NIGHT_ARM_MIN_APP_FIELD,
                    "SSP": "2.6.1",
                    "error_code": 0,
                }
            }
        },
        cast(Any, object()),
    )
    assert state.panel.application_firmware == "0.0.5.37"
    assert state.panel.app_version == NIGHT_ARM_MIN_APP_FIELD
    assert state.panel.firmware == "2.6.1"


@pytest.mark.parametrize(
    ("arm_state", "expected"),
    [
        ("ARMED_STAY_INST", ArmMode.ARMED_NIGHT),
        ("ARMED_STAY", ArmMode.ARMED_STAY),
    ],
)
def test_panel_arm_state_maps_to_public_arm_mode(arm_state: str, expected: ArmMode) -> None:
    assert Elke27Client.arm_mode_from_panel_string(arm_state) is expected


@pytest.mark.asyncio
async def test_arm_night_rejected_when_application_firmware_too_old(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, panel = await connect_with_app_firmware(
        monkeypatch, pack_application_firmware(0, 0, 5, 36)
    )
    sent_before = len(panel.sent)
    with pytest.raises(Elke27InvalidArgument, match="0.5.37"):
        await client.async_arm_area(1, mode=ArmMode.ARMED_NIGHT, pin="1234")
    assert panel.sent[sent_before:] == []


@pytest.mark.asyncio
async def test_high_ssp_low_app_does_not_enable_night(monkeypatch: pytest.MonkeyPatch) -> None:
    client, panel = await connect_with_app_firmware(
        monkeypatch, pack_application_firmware(0, 0, 5, 36), ssp="99.99.99"
    )
    sent_before = len(panel.sent)
    with pytest.raises(Elke27InvalidArgument, match="0.5.37"):
        await client.async_arm_area(1, mode=ArmMode.ARMED_NIGHT, pin="1234")
    assert panel.sent[sent_before:] == []


@pytest.mark.asyncio
async def test_arm_night_sends_stay_inst_and_updates_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, panel = await connect_with_app_firmware(monkeypatch, NIGHT_ARM_MIN_APP_FIELD)

    await drive_until_done(
        client,
        panel,
        client.async_arm_area(1, mode=ArmMode.ARMED_NIGHT, pin="1234"),
    )

    arm_msgs = [
        msg["area"]["set_arm_state"]
        for msg in panel.sent
        if isinstance(msg.get("area"), dict) and "set_arm_state" in msg["area"]
    ]
    assert arm_msgs[0]["arm_state"] == "ARMED_STAY_INST"
    area = client.snapshot.areas[1]
    assert area.arm_mode is ArmMode.ARMED_NIGHT
    assert area.night_arm_supported is True
    assert client.snapshot.panel.application_firmware == "0.0.5.37"


@pytest.mark.asyncio
async def test_arm_night_panel_error_stays_panel_error_not_stay_instant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, panel = await connect_with_app_firmware(monkeypatch, NIGHT_ARM_MIN_APP_FIELD)

    with pytest.raises(Elke27PanelError, match="not ready"):
        await drive_until_done(
            client,
            panel,
            client.async_arm_area(1, mode=ArmMode.ARMED_NIGHT, pin="1234"),
            custom_replies={
                0: {
                    "area": {
                        "set_arm_state": {
                            "area_id": 1,
                            "error_code": int(E27ErrorCode.ELKERR_NOT_READY),
                        }
                    }
                }
            },
        )


@pytest.mark.asyncio
async def test_arm_night_ignored_raises_stay_instant_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, panel = await connect_with_app_firmware(monkeypatch, NIGHT_ARM_MIN_APP_FIELD)

    with pytest.raises(Elke27StayInstantRequiredError):
        await drive_until_done(
            client,
            panel,
            client.async_arm_area(1, mode=ArmMode.ARMED_NIGHT, pin="1234"),
            custom_replies={
                0: {
                    "area": {
                        "set_arm_state": {"area_id": 1, "error_code": E27ErrorCode.ELKERR_NONE}
                    }
                },
                1: {
                    "area": {
                        "get_status": {
                            "area_id": 1,
                            "error_code": E27ErrorCode.ELKERR_NONE,
                            "arm_state": "DISARMED",
                        }
                    }
                },
            },
        )


@pytest.mark.asyncio
async def test_arm_night_refresh_failure_raises_command_outcome_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _panel = await connect_with_app_firmware(monkeypatch, NIGHT_ARM_MIN_APP_FIELD)

    from elke27_lib import Elke27CommandOutcomeUnknownError
    from elke27_lib.client import Result

    async def _execute_no_refresh(
        command_key: str, /, **params: object
    ) -> Result[dict[str, object]]:
        del command_key, params
        return Result(ok=True, data={"area_id": 1, "error_code": 0}, status_refresh_ok=False)

    monkeypatch.setattr(client, "async_execute", _execute_no_refresh)

    with pytest.raises(Elke27CommandOutcomeUnknownError):
        await client.async_arm_area(1, mode=ArmMode.ARMED_NIGHT, pin="1234")


@pytest.mark.asyncio
async def test_sim_arm_night_then_disarm_with_hardware_app_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, panel = await connect_with_app_firmware(monkeypatch, 1540)
    assert client.snapshot.panel.application_firmware == "0.0.6.4"
    assert client.snapshot.areas[1].night_arm_supported is True

    await drive_until_done(
        client,
        panel,
        client.async_arm_area(1, mode=ArmMode.ARMED_NIGHT, pin="1234"),
    )
    arm_msgs = area_set_arm_messages(panel.sent)
    assert arm_msgs[-1]["arm_state"] == "ARMED_STAY_INST"
    assert arm_msgs[-1]["area_id"] == 1
    assert client.snapshot.areas[1].arm_mode is ArmMode.ARMED_NIGHT

    await drive_until_done(
        client,
        panel,
        client.async_disarm_area(1, pin="1234"),
    )
    assert client.snapshot.areas[1].arm_mode is ArmMode.DISARMED


@pytest.mark.asyncio
async def test_sim_arm_night_area_two_targets_area_two(monkeypatch: pytest.MonkeyPatch) -> None:
    client, panel = await connect_with_app_firmware(monkeypatch, NIGHT_ARM_MIN_APP_FIELD)
    await seed_area_disarmed(panel, 2)

    await drive_until_done(
        client,
        panel,
        client.async_arm_area(2, mode=ArmMode.ARMED_NIGHT, pin="1234"),
    )
    arm_msgs = area_set_arm_messages(panel.sent)
    assert arm_msgs[-1]["area_id"] == 2
    assert arm_msgs[-1]["arm_state"] == "ARMED_STAY_INST"
    assert client.snapshot.areas[2].arm_mode is ArmMode.ARMED_NIGHT
    assert client.snapshot.areas[1].arm_mode is ArmMode.DISARMED


@pytest.mark.asyncio
async def test_sim_arm_night_area_two_checks_armed_area_not_area_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, panel = await connect_with_app_firmware(monkeypatch, NIGHT_ARM_MIN_APP_FIELD)
    await seed_area_disarmed(panel, 2)
    await panel.deliver(
        {
            "seq": 0,
            "session_id": panel.info.session_id,
            "area": {
                "get_status": {
                    "area_id": 1,
                    "arm_state": "ARMED_STAY_INST",
                    "error_code": E27ErrorCode.ELKERR_NONE,
                }
            },
        }
    )

    with pytest.raises(Elke27StayInstantRequiredError):
        await drive_until_done(
            client,
            panel,
            client.async_arm_area(2, mode=ArmMode.ARMED_NIGHT, pin="1234"),
            custom_replies={
                0: {
                    "area": {
                        "set_arm_state": {"area_id": 2, "error_code": E27ErrorCode.ELKERR_NONE}
                    }
                },
                1: {
                    "area": {
                        "get_status": {
                            "area_id": 2,
                            "error_code": E27ErrorCode.ELKERR_NONE,
                            "arm_state": "DISARMED",
                        }
                    }
                },
            },
        )


@pytest.mark.asyncio
async def test_arm_night_exit_delay_pending_is_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, panel = await connect_with_app_firmware(monkeypatch, NIGHT_ARM_MIN_APP_FIELD)
    await drive_until_done(
        client,
        panel,
        client.async_arm_area(1, mode=ArmMode.ARMED_NIGHT, pin="1234"),
        custom_replies={
            0: {"area": {"set_arm_state": {"area_id": 1, "error_code": E27ErrorCode.ELKERR_NONE}}},
            1: {
                "area": {
                    "get_status": {
                        "area_id": 1,
                        "error_code": E27ErrorCode.ELKERR_NONE,
                        "arm_state": "DISARMED",
                        "arm_cmd_state": "ARMED_STAY_INST",
                        "ee_timer": 30,
                        "alarm_zone": "",
                    }
                }
            },
        },
    )
    area = client.snapshot.areas[1]
    assert area.arm_mode is ArmMode.DISARMED
    assert area.arm_cmd_mode is ArmMode.ARMED_NIGHT
    assert area.arming is True
    assert isinstance(area.delay_state, DelayStateExit)


@pytest.mark.asyncio
async def test_arm_night_stay_arm_state_with_stay_inst_cmd_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, panel = await connect_with_app_firmware(monkeypatch, NIGHT_ARM_MIN_APP_FIELD)
    with pytest.raises(Elke27StayInstantRequiredError):
        await drive_until_done(
            client,
            panel,
            client.async_arm_area(1, mode=ArmMode.ARMED_NIGHT, pin="1234"),
            custom_replies={
                0: {
                    "area": {
                        "set_arm_state": {"area_id": 1, "error_code": E27ErrorCode.ELKERR_NONE}
                    }
                },
                1: {
                    "area": {
                        "get_status": {
                            "area_id": 1,
                            "error_code": E27ErrorCode.ELKERR_NONE,
                            "arm_state": "ARMED_STAY",
                            "arm_cmd_state": "ARMED_STAY_INST",
                            "ee_timer": 0,
                            "alarm_zone": "",
                        }
                    }
                },
            },
        )
    assert client.snapshot.areas[1].arm_mode is ArmMode.ARMED_STAY
    assert client.snapshot.areas[1].arm_cmd_mode is ArmMode.ARMED_NIGHT


@pytest.mark.parametrize("ee_timer", [0, None])
@pytest.mark.asyncio
async def test_arm_night_stay_inst_cmd_without_exit_delay_raises(
    monkeypatch: pytest.MonkeyPatch, ee_timer: int | None
) -> None:
    client, panel = await connect_with_app_firmware(monkeypatch, NIGHT_ARM_MIN_APP_FIELD)
    status: dict[str, Any] = {
        "area_id": 1,
        "error_code": E27ErrorCode.ELKERR_NONE,
        "arm_state": "DISARMED",
        "arm_cmd_state": "ARMED_STAY_INST",
        "alarm_zone": "",
    }
    if ee_timer is not None:
        status["ee_timer"] = ee_timer
    with pytest.raises(Elke27StayInstantRequiredError):
        await drive_until_done(
            client,
            panel,
            client.async_arm_area(1, mode=ArmMode.ARMED_NIGHT, pin="1234"),
            custom_replies={
                0: {
                    "area": {
                        "set_arm_state": {"area_id": 1, "error_code": E27ErrorCode.ELKERR_NONE}
                    }
                },
                1: {"area": {"get_status": status}},
            },
        )


@pytest.mark.asyncio
async def test_arm_night_refresh_to_plain_stay_raises_stay_instant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, panel = await connect_with_app_firmware(monkeypatch, NIGHT_ARM_MIN_APP_FIELD)
    with pytest.raises(Elke27StayInstantRequiredError):
        await drive_until_done(
            client,
            panel,
            client.async_arm_area(1, mode=ArmMode.ARMED_NIGHT, pin="1234"),
            custom_replies={
                0: {
                    "area": {
                        "set_arm_state": {"area_id": 1, "error_code": E27ErrorCode.ELKERR_NONE}
                    }
                },
                1: {
                    "area": {
                        "get_status": {
                            "area_id": 1,
                            "error_code": E27ErrorCode.ELKERR_NONE,
                            "arm_state": "ARMED_STAY",
                            "arm_cmd_state": "ARMED_STAY",
                        }
                    }
                },
            },
        )


@pytest.mark.asyncio
async def test_night_arm_supported_false_for_old_app_on_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _panel = await connect_with_app_firmware(
        monkeypatch, pack_application_firmware(0, 0, 5, 36)
    )
    area = client.snapshot.areas[1]
    assert client.snapshot.panel.application_firmware == "0.0.5.36"
    assert area.night_arm_supported is False


_LINK_KEYS = LinkKeys("aa", "bb", "cc")


@pytest.mark.asyncio
async def test_panel_switch_clears_night_arm_supported_on_areas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _panel = await connect_with_app_firmware(monkeypatch, NIGHT_ARM_MIN_APP_FIELD)
    assert client.snapshot.panel.application_firmware == "0.0.5.37"
    assert client.snapshot.areas[1].night_arm_supported is True

    await client.async_connect("panel-other", 2102, _LINK_KEYS)
    assert client.snapshot.panel.application_firmware is None
    assert client.snapshot.areas[1].night_arm_supported is False


@pytest.mark.asyncio
async def test_night_arm_supported_false_when_app_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    client, panel = await connect_panel(monkeypatch)
    await seed_area_disarmed(panel)
    assert client.snapshot.areas[1].night_arm_supported is False


@pytest.mark.asyncio
async def test_vacation_arm_rejected_before_send(monkeypatch: pytest.MonkeyPatch) -> None:
    client, panel = await connect_with_app_firmware(monkeypatch, NIGHT_ARM_MIN_APP_FIELD)
    sent_before = len(panel.sent)
    with pytest.raises(Elke27InvalidArgument, match="does not support arm mode 'armed_vacation'"):
        await client.async_arm_area(1, mode=ArmMode.ARMED_VACATION, pin="1234")
    assert panel.sent[sent_before:] == []


@pytest.mark.asyncio
async def test_arm_stay_and_away_still_use_panel_arm_state_wire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, panel = await connect_with_app_firmware(monkeypatch, NIGHT_ARM_MIN_APP_FIELD)
    await drive_until_done(
        client, panel, client.async_arm_area(1, mode=ArmMode.ARMED_STAY, pin="1234")
    )
    stay_msgs = area_set_arm_messages(panel.sent)
    assert stay_msgs[-1]["arm_state"] == "ARMED_STAY"

    await drive_until_done(
        client, panel, client.async_arm_area(1, mode=ArmMode.ARMED_AWAY, pin="1234")
    )
    away_msgs = area_set_arm_messages(panel.sent)
    assert away_msgs[-1]["arm_state"] == "ARMED_AWAY"
