"""Arm night maps to Stay Instant (ARMED_STAY_INST) with application-firmware gating (#139)."""

from __future__ import annotations

from typing import Any, cast

import pytest

from elke27_lib import Elke27InvalidArgument, Elke27PanelError, Elke27StayInstantRequiredError
from elke27_lib.client import ArmMode, Elke27Client
from elke27_lib.const import E27ErrorCode
from elke27_lib.firmware_version import NIGHT_ARM_MIN_APP_FIELD, pack_application_firmware
from elke27_lib.handlers.control import make_control_get_version_info_handler
from elke27_lib.states import PanelState
from test.test_panel_errors_ready_night import drive_until_done, make_client_with_app_version


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
async def test_high_ssp_low_app_does_not_enable_night() -> None:
    client, session = make_client_with_app_version(
        pack_application_firmware(0, 0, 5, 36), ssp="99.99.99"
    )
    with pytest.raises(Elke27InvalidArgument, match="0.5.37"):
        await client.async_arm_area(1, mode=ArmMode.ARMED_NIGHT, pin="1234")
    assert session.sent == []


@pytest.mark.asyncio
async def test_arm_night_sends_stay_inst_and_updates_snapshot() -> None:
    client, session = make_client_with_app_version(NIGHT_ARM_MIN_APP_FIELD)

    await drive_until_done(
        client,
        session,
        client.async_arm_area(1, mode=ArmMode.ARMED_NIGHT, pin="1234"),
    )

    assert session.sent[0]["area"]["set_arm_state"]["arm_state"] == "ARMED_STAY_INST"
    area = client.snapshot.areas[1]
    assert area.arm_mode is ArmMode.ARMED_NIGHT
    assert area.night_arm_supported is True
    assert client.snapshot.panel.application_firmware == "0.0.5.37"


@pytest.mark.asyncio
async def test_arm_night_panel_error_stays_panel_error_not_stay_instant() -> None:
    client, session = make_client_with_app_version(NIGHT_ARM_MIN_APP_FIELD)

    with pytest.raises(Elke27PanelError, match="not ready"):
        await drive_until_done(
            client,
            session,
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
async def test_arm_night_ignored_raises_stay_instant_error() -> None:
    client, session = make_client_with_app_version(NIGHT_ARM_MIN_APP_FIELD)

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


@pytest.mark.asyncio
async def test_arm_night_refresh_failure_raises_command_outcome_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _session = make_client_with_app_version(NIGHT_ARM_MIN_APP_FIELD)

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
