from __future__ import annotations

import asyncio
from typing import Any

import pytest

from elke27_lib import linking
from elke27_lib import session as session_mod
from elke27_lib.client import Elke27Client
from elke27_lib.const import E27ErrorCode
from elke27_lib.events import ConnectionStateChanged
from elke27_lib.handlers import area as area_handler
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
        "arm_cmd_state": "ARMED_AWAY",
        "troubles": [],
        "chime_count": 0,
        "Chime": False,
        "xzn_id": 0,
        "xzn_time": 0,
        "ee_timer": 45,
        "alrm_snd": False,
        "auto_arm_timer": 0,
        "error_code": E27ErrorCode.ELKERR_NONE,
    }
    payload.update(overrides)
    return payload


def _snapshot_for(area: AreaState):
    client = Elke27Client(kernel=E27Kernel())
    client._kernel.state.areas[area.area_id] = area
    return client._build_area_map()[area.area_id]


def test_exit_delay_payload_updates_internal_and_public_snapshot() -> None:
    state = PanelState()
    handler = _status_handler(state)
    msg = {"area": {"get_status": _base_status_payload()}}
    assert handler(msg, make_ctx()) is True
    area = state.areas[1]
    assert area.arm_state == "DISARMED"
    assert area.arm_cmd_state == "ARMED_AWAY"
    assert area.ee_timer == 45
    assert area.alarm_zone == ""

    snapshot_area = _snapshot_for(area)
    assert snapshot_area.arm_mode is ArmMode.DISARMED
    assert snapshot_area.arm_cmd_mode is ArmMode.ARMED_AWAY
    assert snapshot_area.ee_timer == 45
    assert snapshot_area.alarm_zone == ""
    assert snapshot_area.arming is True


def test_fully_armed_payload_clears_exit_delay_pending_fields() -> None:
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
    assert area.arm_cmd_state is None
    assert area.ee_timer is None

    snapshot_area = _snapshot_for(area)
    assert snapshot_area.arm_mode is ArmMode.ARMED_STAY
    assert snapshot_area.arm_cmd_mode is None
    assert snapshot_area.ee_timer is None
    assert snapshot_area.arming is False


def test_missing_alarm_zone_makes_arming_false() -> None:
    state = PanelState()
    handler = _status_handler(state)
    msg = {
        "area": {
            "get_status": {
                "area_id": 1,
                "arm_state": "DISARMED",
                "arm_cmd_state": "ARMED_AWAY",
                "ee_timer": 30,
                "error_code": E27ErrorCode.ELKERR_NONE,
            }
        }
    }
    assert handler(msg, make_ctx()) is True
    area = state.areas[1]
    assert area.alarm_zone is None
    assert _snapshot_for(area).arming is False


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

    snapshot_area = _snapshot_for(area)
    assert snapshot_area.arm_cmd_mode is None
    assert snapshot_area.ee_timer is None
    assert snapshot_area.arming is False


def test_disarm_reply_without_arm_cmd_clears_stale_exit_delay() -> None:
    state = PanelState()
    state.areas[1] = AreaState(
        area_id=1,
        arm_state="DISARMED",
        arm_cmd_state="ARMED_AWAY",
        ee_timer=12,
        alarm_zone="",
    )
    handler = _status_handler(state)
    msg = {
        "area": {
            "get_status": {
                "area_id": 1,
                "arm_state": "DISARMED",
                "error_code": E27ErrorCode.ELKERR_NONE,
            }
        }
    }
    assert handler(msg, make_ctx()) is True
    area = state.areas[1]
    assert area.arm_cmd_state is None
    assert area.ee_timer is None
    assert area.alarm_zone is None
    assert _snapshot_for(area).arming is False


def test_stale_alarm_zone_cleared_on_disarm_reply() -> None:
    state = PanelState()
    state.areas[1] = AreaState(
        area_id=1,
        arm_state="DISARMED",
        arm_cmd_state="ARMED_AWAY",
        ee_timer=10,
        alarm_zone="2",
    )
    handler = _status_handler(state)
    msg = {
        "area": {
            "get_status": {
                "area_id": 1,
                "arm_state": "DISARMED",
                "error_code": E27ErrorCode.ELKERR_NONE,
            }
        }
    }
    assert handler(msg, make_ctx()) is True
    assert state.areas[1].alarm_zone is None


def test_set_arm_state_shaped_payload_clears_when_armed() -> None:
    state = PanelState()
    state.areas[1] = AreaState(
        area_id=1,
        arm_state="DISARMED",
        arm_cmd_state="ARMED_AWAY",
        ee_timer=20,
    )
    area_handler._reconcile_area_state(
        state,
        {
            "area_id": 1,
            "arm_state": "ARMED_AWAY",
            "error_code": E27ErrorCode.ELKERR_NONE,
        },
        now=1.0,
        _source="set_arm_state",
    )
    area = state.areas[1]
    assert area.arm_state == "ARMED_AWAY"
    assert area.arm_cmd_state is None
    assert area.ee_timer is None
    assert area.alarm_zone is None


def test_set_arm_state_shaped_disarm_reply_via_reconcile() -> None:
    state = PanelState()
    state.areas[1] = AreaState(
        area_id=1,
        arm_state="DISARMED",
        arm_cmd_state="ARMED_STAY",
        ee_timer=8,
    )
    handler = _status_handler(state)
    msg = {
        "area": {
            "get_status": {
                "area_id": 1,
                "arm_state": "DISARMED",
                "error_code": E27ErrorCode.ELKERR_NONE,
            }
        }
    }
    assert handler(msg, make_ctx()) is True
    assert state.areas[1].arm_cmd_state is None
    assert state.areas[1].ee_timer is None


def test_ee_timer_zero_not_arming() -> None:
    state = PanelState()
    handler = _status_handler(state)
    msg = {
        "area": {
            "get_status": _base_status_payload(
                arm_cmd_state="ARMED_AWAY",
                ee_timer=0,
            )
        }
    }
    assert handler(msg, make_ctx()) is True
    assert _snapshot_for(state.areas[1]).arming is False


def test_non_empty_alarm_zone_not_arming() -> None:
    state = PanelState()
    handler = _status_handler(state)
    msg = {
        "area": {
            "get_status": _base_status_payload(
                alarm_zone="3",
                ee_timer=30,
            )
        }
    }
    assert handler(msg, make_ctx()) is True
    area = state.areas[1]
    assert area.alarm_zone == "3"
    assert _snapshot_for(area).arming is False


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
                "alarm_zone": "",
                "error_code": E27ErrorCode.ELKERR_NONE,
            }
        }
    }
    assert handler(msg, make_ctx()) is True
    area = state.areas[1]
    assert area.arm_cmd_state == "ARMED_STAY"
    assert area.ee_timer == 30
    assert _snapshot_for(area).arming is True


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
    assert handler(msg, make_ctx()) is True
    area = state.areas[1]
    assert area.arm_cmd_state is None
    assert area.ee_timer is None


@pytest.mark.asyncio
async def test_reconnect_clears_exit_delay_pending_on_kernel_connect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kernel = E27Kernel()
    kernel.state.areas[1] = AreaState(
        area_id=1,
        arm_cmd_state="ARMED_AWAY",
        ee_timer=15,
        alarm_zone="1",
    )
    monkeypatch.setattr(kernel, "load_features_blocking", lambda _modules=None: None)

    async def _to_thread(fn, *a, **k):  # type: ignore[no-untyped-def]
        return fn(*a, **k)

    monkeypatch.setattr(asyncio, "to_thread", _to_thread)

    class _SessionOk:
        def __init__(self, cfg, client_identity, link_key_hex) -> None:  # type: ignore[no-untyped-def]
            _ = cfg, client_identity, link_key_hex
            self.state = session_mod.SessionState.ACTIVE
            self.info = session_mod.SessionInfo(
                session_id=11, session_key_hex="00", session_hmac_hex="11"
            )

        def connect(self) -> session_mod.SessionInfo:
            return self.info

        def enable_outbound_queue(self, **_kwargs: object) -> None:
            return None

        def start_auto_receive(self) -> None:
            return None

    monkeypatch.setattr(session_mod, "Session", _SessionOk)
    monkeypatch.setattr(kernel, "_bootstrap_requests", lambda: None)
    monkeypatch.setattr(kernel, "_start_keepalive", lambda: None)

    await kernel.connect(
        linking.E27LinkKeys("aa", "bb", "cc"),
        panel={"host": "h", "port": 1},
        client_identity=linking.E27Identity("mn", "sn", "fw", "hw", "os"),
        session_config=session_mod.SessionConfig(host="h", port=1),
    )
    assert kernel.state.areas[1].arm_cmd_state is None
    assert kernel.state.areas[1].ee_timer is None
    assert kernel.state.areas[1].alarm_zone is None


def test_ee_timer_duplicate_tick_stays_arming_true() -> None:
    state = PanelState()
    handler = _status_handler(state)
    assert handler({"area": {"get_status": _base_status_payload()}}, make_ctx()) is True
    for timer in (40, 29, 29):
        assert (
            handler(
                {
                    "area": {
                        "get_status": {
                            "area_id": 1,
                            "ee_timer": timer,
                            "error_code": E27ErrorCode.ELKERR_NONE,
                        }
                    }
                },
                make_ctx(),
            )
            is True
        )
    area = state.areas[1]
    assert area.ee_timer == 29
    assert _snapshot_for(area).arming is True


def test_ee_timer_late_higher_tick_ignored_keeps_previous() -> None:
    state = PanelState()
    handler = _status_handler(state)
    assert handler({"area": {"get_status": _base_status_payload()}}, make_ctx()) is True
    assert (
        handler(
            {
                "area": {
                    "get_status": {
                        "area_id": 1,
                        "ee_timer": 40,
                        "error_code": E27ErrorCode.ELKERR_NONE,
                    }
                }
            },
            make_ctx(),
        )
        is True
    )
    assert (
        handler(
            {
                "area": {
                    "get_status": {
                        "area_id": 1,
                        "ee_timer": 50,
                        "error_code": E27ErrorCode.ELKERR_NONE,
                    }
                }
            },
            make_ctx(),
        )
        is True
    )
    area = state.areas[1]
    assert area.ee_timer == 40
    assert _snapshot_for(area).arming is True


def test_bool_ee_timer_rejected() -> None:
    state = PanelState()
    state.areas[1] = AreaState(
        area_id=1,
        arm_state="DISARMED",
        arm_cmd_state="ARMED_AWAY",
        ee_timer=30,
        alarm_zone="",
        exit_delay_payload_complete=True,
    )
    handler = _status_handler(state)
    msg = {
        "area": {
            "get_status": {
                "area_id": 1,
                "ee_timer": True,
                "error_code": E27ErrorCode.ELKERR_NONE,
            }
        }
    }
    assert handler(msg, make_ctx()) is True
    area = state.areas[1]
    assert area.arm_cmd_state is None
    assert area.ee_timer is None
    assert area.alarm_zone is None
    assert _snapshot_for(area).arming is False


def test_ee_timer_zero_tick_does_not_clear_arm_state() -> None:
    state = PanelState()
    handler = _status_handler(state)
    assert handler({"area": {"get_status": _base_status_payload()}}, make_ctx()) is True
    assert (
        handler(
            {
                "area": {
                    "get_status": {
                        "area_id": 1,
                        "ee_timer": 0,
                        "error_code": E27ErrorCode.ELKERR_NONE,
                    }
                }
            },
            make_ctx(),
        )
        is True
    )
    area = state.areas[1]
    assert area.arm_state == "DISARMED"
    assert _snapshot_for(area).arm_mode is ArmMode.DISARMED
    assert _snapshot_for(area).arming is False


def test_partial_arm_cmd_patch_does_not_clear_arm_state() -> None:
    state = PanelState()
    handler = _status_handler(state)
    assert (
        handler(
            {
                "area": {
                    "get_status": _base_status_payload(arm_cmd_state="ARMED_STAY"),
                }
            },
            make_ctx(),
        )
        is True
    )
    assert (
        handler(
            {
                "area": {
                    "get_status": {
                        "area_id": 1,
                        "arm_cmd_state": "ARMED_AWAY",
                        "error_code": E27ErrorCode.ELKERR_NONE,
                    }
                }
            },
            make_ctx(),
        )
        is True
    )
    area = state.areas[1]
    assert area.arm_state == "DISARMED"
    assert _snapshot_for(area).arm_mode is ArmMode.DISARMED


def test_invalid_ee_timer_null_after_full_payload_clears_arming() -> None:
    state = PanelState()
    handler = _status_handler(state)
    assert handler({"area": {"get_status": _base_status_payload()}}, make_ctx()) is True
    assert _snapshot_for(state.areas[1]).arming is True

    msg = {
        "area": {
            "get_status": {
                "area_id": 1,
                "ee_timer": None,
                "error_code": E27ErrorCode.ELKERR_NONE,
            }
        }
    }
    assert handler(msg, make_ctx()) is True
    area = state.areas[1]
    assert area.arm_cmd_state is None
    assert area.ee_timer is None
    assert area.alarm_zone is None
    assert area.exit_delay_payload_complete is False
    assert _snapshot_for(area).arming is False


def test_ee_timer_tick_after_full_payload_keeps_arming_true() -> None:
    state = PanelState()
    handler = _status_handler(state)
    assert handler({"area": {"get_status": _base_status_payload()}}, make_ctx()) is True
    assert _snapshot_for(state.areas[1]).arming is True

    msg = {
        "area": {
            "get_status": {
                "area_id": 1,
                "ee_timer": 40,
                "error_code": E27ErrorCode.ELKERR_NONE,
            }
        }
    }
    assert handler(msg, make_ctx()) is True
    area = state.areas[1]
    assert area.ee_timer == 40
    assert area.arm_cmd_state == "ARMED_AWAY"
    assert area.alarm_zone == ""
    assert _snapshot_for(area).arming is True


def test_fresh_arm_cmd_with_stale_timer_clears_and_not_arming() -> None:
    state = PanelState()
    handler = _status_handler(state)
    assert handler({"area": {"get_status": _base_status_payload()}}, make_ctx()) is True
    msg = {
        "area": {
            "get_status": {
                "area_id": 1,
                "arm_cmd_state": "ARMED_AWAY",
                "error_code": E27ErrorCode.ELKERR_NONE,
            }
        }
    }
    assert handler(msg, make_ctx()) is True
    area = state.areas[1]
    assert area.arm_cmd_state == "ARMED_AWAY"
    assert area.ee_timer is None
    assert area.alarm_zone is None
    assert _snapshot_for(area).arming is False


def test_exit_delay_full_sequence_ends_not_arming() -> None:
    state = PanelState()
    handler = _status_handler(state)
    assert handler({"area": {"get_status": _base_status_payload()}}, make_ctx()) is True
    assert _snapshot_for(state.areas[1]).arming is True

    assert (
        handler(
            {
                "area": {
                    "get_status": {
                        "area_id": 1,
                        "ee_timer": 40,
                        "error_code": E27ErrorCode.ELKERR_NONE,
                    }
                }
            },
            make_ctx(),
        )
        is True
    )
    assert _snapshot_for(state.areas[1]).arming is True

    assert (
        handler(
            {
                "area": {
                    "get_status": {
                        "area_id": 1,
                        "ee_timer": 0,
                        "error_code": E27ErrorCode.ELKERR_NONE,
                    }
                }
            },
            make_ctx(),
        )
        is True
    )
    assert _snapshot_for(state.areas[1]).arming is False

    assert (
        handler(
            {
                "area": {
                    "get_status": _base_status_payload(
                        arm_state="ARMED_AWAY",
                        arm_cmd_state="ARMED_AWAY",
                        ee_timer=0,
                    )
                }
            },
            make_ctx(),
        )
        is True
    )
    assert _snapshot_for(state.areas[1]).arming is False


def test_stay_to_away_partial_update_not_arming() -> None:
    state = PanelState()
    handler = _status_handler(state)
    assert (
        handler(
            {
                "area": {
                    "get_status": _base_status_payload(
                        arm_cmd_state="ARMED_STAY",
                    )
                }
            },
            make_ctx(),
        )
        is True
    )
    assert _snapshot_for(state.areas[1]).arming is True

    assert (
        handler(
            {
                "area": {
                    "get_status": {
                        "area_id": 1,
                        "arm_cmd_state": "ARMED_AWAY",
                        "error_code": E27ErrorCode.ELKERR_NONE,
                    }
                }
            },
            make_ctx(),
        )
        is True
    )
    area = state.areas[1]
    assert area.arm_cmd_state == "ARMED_AWAY"
    assert area.ee_timer is None
    assert _snapshot_for(area).arming is False


def _event_base(kind: str) -> dict[str, Any]:
    return dict(
        kind=kind,
        at=0.0,
        seq=None,
        classification="LOCAL",
        route=("__local__", kind),
        session_id=1,
    )


def test_disconnect_snapshot_reset_clears_exit_delay_pending() -> None:
    kernel = E27Kernel()
    kernel.state.areas[1] = AreaState(
        area_id=1,
        arm_state="DISARMED",
        arm_cmd_state="ARMED_STAY",
        ee_timer=9,
        alarm_zone="",
    )
    client = Elke27Client(kernel=kernel)
    client._replace_snapshot(areas=client._build_area_map())
    before_disconnect = client.get_area(1)
    assert before_disconnect is not None
    assert before_disconnect.arming is True

    client._handle_kernel_event(
        ConnectionStateChanged(**_event_base(ConnectionStateChanged.KIND), connected=False)
    )
    assert kernel.state.areas[1].arm_cmd_state is None
    assert kernel.state.areas[1].ee_timer is None
    assert kernel.state.areas[1].alarm_zone is None
    public_area = client.get_area(1)
    assert public_area is not None
    assert public_area.arming is False
    assert public_area.arm_cmd_mode is None
    assert public_area.ee_timer is None
