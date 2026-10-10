from __future__ import annotations

from elke27_lib.client import Elke27Client
from elke27_lib.const import E27ErrorCode
from elke27_lib.handlers.area import make_area_get_status_handler, make_area_set_status_handler
from elke27_lib.kernel import E27Kernel
from elke27_lib.states import AreaState, PanelState
from elke27_lib.types import ArmMode
from test.helpers.dispatch import make_ctx


class _NoEmit:
    def __call__(self, _evt: object, _ctx: object) -> None:
        return None


def _status_handler(state: PanelState):
    return make_area_get_status_handler(state, _NoEmit(), now=lambda: 1.0)


def _set_status_handler(state: PanelState):
    return make_area_set_status_handler(state, _NoEmit(), now=lambda: 1.0)


def _base_status_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "area_id": 1,
        "arm_state": "DISARMED",
        "ready_status": "RDY_AWAY",
        "alarm_zone": "",
        "alarms": [],
        "alarm_mem": [],
        "zones_bypassed": 0,
        "arm_cmd_state": "DISARMED",
        "troubles": [],
        "chime_count": 0,
        "Chime": False,
        "xzn_id": 0,
        "xzn_time": 0,
        "ee_timer": 0,
        "alrm_snd": False,
        "auto_arm_timer": 0,
        "error_code": E27ErrorCode.ELKERR_NONE,
    }
    payload.update(overrides)
    return payload


def test_exit_delay_payload_updates_internal_and_public_snapshot() -> None:
    state = PanelState()
    handler = _status_handler(state)
    msg = {
        "area": {
            "get_status": _base_status_payload(
                arm_state="DISARMED",
                arm_cmd_state="ARMED_AWAY",
                ee_timer=45,
            )
        }
    }
    assert handler(msg, make_ctx()) is True
    area = state.areas[1]
    assert area.arm_state == "DISARMED"
    assert area.arm_cmd_state == "ARMED_AWAY"
    assert area.ee_timer == 45

    client = Elke27Client(kernel=E27Kernel())
    client._kernel.state.areas[1] = area
    snapshot_area = client._build_area_map()[1]
    assert snapshot_area.arm_mode is ArmMode.DISARMED
    assert snapshot_area.arm_cmd_mode is ArmMode.ARMED_AWAY
    assert snapshot_area.ee_timer == 45
    assert snapshot_area.arming is True


def test_fully_armed_payload_arm_cmd_matches() -> None:
    state = PanelState()
    handler = _status_handler(state)
    msg = {
        "area": {
            "get_status": _base_status_payload(
                arm_state="ARMED_STAY",
                arm_cmd_state="ARMED_STAY",
                ee_timer=0,
            )
        }
    }
    assert handler(msg, make_ctx()) is True
    area = state.areas[1]
    assert area.arm_state == "ARMED_STAY"
    assert area.arm_cmd_state == "ARMED_STAY"
    assert area.ee_timer == 0

    client = Elke27Client(kernel=E27Kernel())
    client._kernel.state.areas[1] = area
    snapshot_area = client._build_area_map()[1]
    assert snapshot_area.arm_mode is ArmMode.ARMED_STAY
    assert snapshot_area.arm_cmd_mode is ArmMode.ARMED_STAY
    assert snapshot_area.ee_timer == 0
    assert snapshot_area.arming is False


def test_missing_exit_delay_fields_remain_none() -> None:
    state = PanelState()
    handler = _status_handler(state)
    msg = {
        "area": {
            "get_status": {
                "area_id": 1,
                "arm_state": "DISARMED",
                "ready_status": "RDY_AWAY",
                "error_code": E27ErrorCode.ELKERR_NONE,
            }
        }
    }
    assert handler(msg, make_ctx()) is True
    area = state.areas[1]
    assert area.arm_cmd_state is None
    assert area.ee_timer is None

    client = Elke27Client(kernel=E27Kernel())
    client._kernel.state.areas[1] = area
    snapshot_area = client._build_area_map()[1]
    assert snapshot_area.arm_cmd_mode is None
    assert snapshot_area.ee_timer is None
    assert snapshot_area.arming is False


def test_set_status_route_applies_exit_delay_fields() -> None:
    state = PanelState()
    handler = _set_status_handler(state)
    msg = {
        "area": {
            "set_status": {
                "area_id": 1,
                "arm_state": "DISARMED",
                "arm_cmd_state": "ARMED_STAY",
                "ee_timer": 30,
                "error_code": E27ErrorCode.ELKERR_NONE,
            }
        }
    }
    assert handler(msg, make_ctx()) is True
    area = state.areas[1]
    assert area.arm_cmd_state == "ARMED_STAY"
    assert area.ee_timer == 30


def test_invalid_exit_delay_field_types_are_ignored() -> None:
    state = PanelState()
    state.areas[1] = AreaState(area_id=1)
    handler = _status_handler(state)
    msg = {
        "area": {
            "get_status": {
                "area_id": 1,
                "arm_state": "DISARMED",
                "arm_cmd_state": 99,
                "ee_timer": "30",
                "error_code": E27ErrorCode.ELKERR_NONE,
            }
        }
    }
    outcome = handler(msg, make_ctx())
    assert outcome is True
    area = state.areas[1]
    assert area.arm_cmd_state is None
    assert area.ee_timer is None
