"""Arm night maps to Stay Instant (ARMED_STAY_INST) with firmware gating (#139)."""

from __future__ import annotations

import pytest

from elke27_lib import Elke27InvalidArgument, Elke27PanelError, Elke27StayInstantRequiredError
from elke27_lib.client import ArmMode, Elke27Client
from elke27_lib.const import E27ErrorCode
from elke27_lib.firmware_version import NIGHT_ARM_MIN_FIRMWARE, firmware_at_least
from test.helpers.arm_night_panel import drive_until_done, make_client_with_firmware


@pytest.mark.parametrize(
    ("arm_state", "expected"),
    [
        ("ARMED_STAY_INST", ArmMode.ARMED_NIGHT),
        ("ARMED_STAY", ArmMode.ARMED_STAY),
    ],
)
def test_panel_arm_state_maps_to_public_arm_mode(arm_state: str, expected: ArmMode) -> None:
    assert Elke27Client.arm_mode_from_panel_string(arm_state) is expected


@pytest.mark.parametrize(
    ("firmware", "expected"),
    [
        ("0.5.36", False),
        ("0.5.37", True),
        ("0.5.100", True),
    ],
)
def test_night_offered_only_on_supported_firmware(firmware: str, expected: bool) -> None:
    assert firmware_at_least(firmware, NIGHT_ARM_MIN_FIRMWARE) is expected


@pytest.mark.asyncio
async def test_arm_night_sends_stay_inst_and_updates_snapshot() -> None:
    client, session = make_client_with_firmware("0.5.37")

    await drive_until_done(
        client,
        session,
        client.async_arm_area(1, mode=ArmMode.ARMED_NIGHT, pin="1234"),
    )

    assert session.sent[0]["area"]["set_arm_state"]["arm_state"] == "ARMED_STAY_INST"
    area = client.snapshot.areas[1]
    assert area.arm_mode is ArmMode.ARMED_NIGHT
    assert area.night_arm_supported is True


@pytest.mark.asyncio
async def test_arm_night_rejected_before_send_on_old_firmware() -> None:
    client, session = make_client_with_firmware("0.5.36")

    with pytest.raises(Elke27InvalidArgument, match="0.5.37"):
        await client.async_arm_area(1, mode=ArmMode.ARMED_NIGHT, pin="1234")
    assert session.sent == []


@pytest.mark.asyncio
async def test_arm_night_panel_error_surfaces_without_state_change() -> None:
    client, session = make_client_with_firmware("0.5.37")

    with pytest.raises(Elke27PanelError):
        await drive_until_done(
            client,
            session,
            client.async_arm_area(1, mode=ArmMode.ARMED_NIGHT, pin="1234"),
            custom_replies={
                0: {
                    "area": {
                        "set_arm_state": {
                            "area_id": 1,
                            "error_code": int(E27ErrorCode.ELKERR_INVALID_MODE),
                        }
                    }
                }
            },
        )
    area = client.snapshot.areas.get(1)
    assert area is None or area.arm_mode is not ArmMode.ARMED_NIGHT


@pytest.mark.asyncio
async def test_arm_night_ignored_raises_stay_instant_error() -> None:
    client, session = make_client_with_firmware("0.5.37")

    with pytest.raises(Elke27StayInstantRequiredError):
        await drive_until_done(
            client,
            session,
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

    area = client.snapshot.areas.get(1)
    assert area is None or area.arm_mode is not ArmMode.ARMED_NIGHT
