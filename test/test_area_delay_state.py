"""Entry/exit delay ``DelayState`` (#92): table, input checks, and public client paths."""

from __future__ import annotations

import copy

import pytest

from elke27_lib.area_delay import delay_state_from_area_status
from elke27_lib.arm_panel import arm_mode_from_panel_string
from elke27_lib.client import Elke27Client
from elke27_lib.const import E27ErrorCode
from elke27_lib.handlers.area import make_area_get_status_handler
from elke27_lib.states import AreaState, PanelState
from elke27_lib.types import DELAY_NONE, ArmMode, DelayStateEntry, DelayStateExit
from test.helpers.dispatch import make_ctx
from test.helpers.fake_session import connect_with_fake_panel

ELK_ENTRY_CAPTURE: dict[str, object] = {
    "area_id": 1,
    "arm_state": "ARMED_STAY",
    "arm_cmd_state": "ARMED_STAY",
    "ready_status": "RDY_NOT",
    "ee_timer": 9,
    "Chime": False,
    "alarms": "",
    "alarm_mem": "",
    "alrm_snd": "",
    "troubles": "",
    "aud_tbl": 0,
    "alarm_zone": "ID:6 - Zone 6",
    "zones_bypassed": 0,
    "xzn_time": 0,
    "xzn_id": 0,
    "auto_arm_timer": 0,
    "chime_count": 0,
    "error_code": 0,
}


def _area_from_payload(payload: dict[str, object]) -> AreaState:
    state = PanelState()
    handler = make_area_get_status_handler(state, lambda _e, _c: None, now=lambda: 1.0)
    assert handler({"area": {"get_status": payload}}, make_ctx()) is True
    area_id = payload["area_id"]
    assert isinstance(area_id, int)
    return state.areas[area_id]


def _exit_frame(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "area_id": 1,
        "arm_state": "DISARMED",
        "arm_cmd_state": "ARMED_AWAY",
        "ready_status": "RDY_AWAY",
        "ee_timer": 45,
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
        "error_code": E27ErrorCode.ELKERR_NONE,
    }
    base.update(overrides)
    return base


@pytest.mark.parametrize(
    ("payload", "expected_kind"),
    [
        (ELK_ENTRY_CAPTURE, "entry"),
        (
            {**ELK_ENTRY_CAPTURE, "ee_timer": 4},
            "entry",
        ),
        (
            {
                **ELK_ENTRY_CAPTURE,
                "arm_state": "DISARMED",
                "arm_cmd_state": "DISARMED",
                "ee_timer": 0,
                "alarm_zone": "",
            },
            "none",
        ),
        (
            {
                **ELK_ENTRY_CAPTURE,
                "alarms": "BURG",
                "alrm_snd": "",
            },
            "none",
        ),
        (_exit_frame(), "exit"),
        (_exit_frame(ee_timer=1), "exit"),
        (
            _exit_frame(arm_state="ARMED_AWAY", arm_cmd_state="ARMED_AWAY", ee_timer=1),
            "none",
        ),
        (
            _exit_frame(arm_state="ARMED_AWAY", arm_cmd_state="ARMED_AWAY", ee_timer=0),
            "none",
        ),
        (
            _exit_frame(arm_cmd_state="DISARMED", ee_timer=20),
            "none",
        ),
    ],
)
def test_delay_state_table(payload: dict[str, object], expected_kind: str) -> None:
    area = _area_from_payload(payload)
    state = delay_state_from_area_status(area)
    if expected_kind == "none":
        assert state is DELAY_NONE
    elif expected_kind == "entry":
        assert isinstance(state, DelayStateEntry)
        assert state.seconds == payload["ee_timer"]
        assert state.zone == str(payload["alarm_zone"]).strip()
    else:
        assert isinstance(state, DelayStateExit)
        assert state.seconds == payload["ee_timer"]


def test_chime_capital_c_parsed_on_get_status() -> None:
    payload = dict(ELK_ENTRY_CAPTURE)
    payload["Chime"] = True
    area = _area_from_payload(payload)
    assert area.chime is True


def _mutate(base: dict[str, object], **changes: object) -> dict[str, object]:
    out = copy.deepcopy(base)
    out.update(changes)
    return out


@pytest.mark.parametrize(
    ("mutation", "expect_entry"),
    [
        ({"arm_state": "DISARMED"}, False),
        ({"ee_timer": 0}, False),
        ({"alarm_zone": ""}, False),
    ],
)
def test_entry_delay_input_variation(mutation: dict[str, object], expect_entry: bool) -> None:
    payload = _mutate(ELK_ENTRY_CAPTURE, **mutation)
    state = delay_state_from_area_status(_area_from_payload(payload))
    assert isinstance(state, DelayStateEntry) is expect_entry


def test_exit_end_input_variation() -> None:
    armed_done = _exit_frame(arm_state="ARMED_AWAY", arm_cmd_state="ARMED_AWAY", ee_timer=1)
    assert delay_state_from_area_status(_area_from_payload(armed_done)) is DELAY_NONE


def test_armed_stay_inst_exit_delay_via_shared_arm_mapping() -> None:
    exit_frame = {
        "area_id": 1,
        "arm_state": "DISARMED",
        "arm_cmd_state": "ARMED_STAY_INST",
        "ee_timer": 30,
        "alarm_zone": "",
        "alarms": "",
        "alrm_snd": "",
        "error_code": 0,
    }
    state = delay_state_from_area_status(_area_from_payload(exit_frame))
    assert isinstance(state, DelayStateExit)
    assert state.seconds == 30
    assert arm_mode_from_panel_string("DISARMED") is not arm_mode_from_panel_string(
        "ARMED_STAY_INST"
    )


def test_armed_stay_inst_complete_is_not_delay() -> None:
    inst = "ARMED_STAY_INST"
    assert arm_mode_from_panel_string(inst) == arm_mode_from_panel_string(inst)
    armed = {
        "area_id": 1,
        "arm_state": inst,
        "arm_cmd_state": inst,
        "ee_timer": 1,
        "alarm_zone": "",
        "alarms": "",
        "alrm_snd": "",
        "error_code": 0,
    }
    assert delay_state_from_area_status(_area_from_payload(armed)) is DELAY_NONE


@pytest.mark.asyncio
async def test_entry_countdown_sequence_public_client(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Elke27Client()
    panel = await connect_with_fake_panel(monkeypatch, client)
    frames = [
        dict(ELK_ENTRY_CAPTURE, ee_timer=9),
        dict(ELK_ENTRY_CAPTURE, ee_timer=4),
        {
            **ELK_ENTRY_CAPTURE,
            "arm_state": "DISARMED",
            "arm_cmd_state": "DISARMED",
            "ee_timer": 0,
            "alarm_zone": "",
        },
    ]
    for frame in frames:
        await panel.deliver({"seq": 0, "area": {"get_status": frame}})
    last = client.snapshot.areas[1]
    assert last.arm_mode is ArmMode.DISARMED
    assert last.entry_delay is False
    assert last.delay_state is DELAY_NONE


@pytest.mark.asyncio
async def test_entry_ends_in_alarm_public_client(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Elke27Client()
    panel = await connect_with_fake_panel(monkeypatch, client)
    await panel.deliver({"seq": 0, "area": {"get_status": ELK_ENTRY_CAPTURE}})
    assert client.snapshot.areas[1].entry_delay is True
    alarm = dict(ELK_ENTRY_CAPTURE, alarms="BURG", alrm_snd="")
    await panel.deliver({"seq": 1, "area": {"get_status": alarm}})
    snap = client.snapshot.areas[1]
    assert snap.entry_delay is False
    assert isinstance(snap.delay_state, DelayStateEntry) is False


@pytest.mark.asyncio
async def test_exit_delay_sequence_public_client(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Elke27Client()
    panel = await connect_with_fake_panel(monkeypatch, client)
    sequence = [
        _exit_frame(ee_timer=30),
        _exit_frame(ee_timer=5),
        _exit_frame(arm_state="ARMED_AWAY", arm_cmd_state="ARMED_AWAY", ee_timer=1),
    ]
    snapshots = []
    for idx, frame in enumerate(sequence):
        await panel.deliver({"seq": idx, "area": {"get_status": frame}})
        snapshots.append(client.snapshot.areas[1])
    assert snapshots[0].arming is True
    assert isinstance(snapshots[0].delay_state, DelayStateExit)
    assert snapshots[1].arming is True
    assert snapshots[2].arming is False
    assert snapshots[2].delay_state is DELAY_NONE
    assert snapshots[2].ee_timer == 1
