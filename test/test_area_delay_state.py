"""Entry/exit delay ``DelayState`` (#92): table, mutation, and public client paths."""

from __future__ import annotations

import copy

import pytest

from elke27_lib.area_delay import (
    DELAY_NONE,
    DelayStateEntry,
    DelayStateExit,
    delay_state_from_area_status,
)
from elke27_lib.client import Elke27Client
from elke27_lib.handlers.area import make_area_get_status_handler
from elke27_lib.states import PanelState
from elke27_lib.types import ArmMode
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
    "alarm_zone": "ID:6 - 3 Car Garage OHD 1",
    "zones_bypassed": 0,
    "xzn_time": 0,
    "xzn_id": 0,
    "auto_arm_timer": 0,
    "chime_count": 0,
    "error_code": 0,
}


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
        "error_code": 0,
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
                "alrm_snd": "BURG",
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
    ],
)
def test_delay_state_table(payload: dict[str, object], expected_kind: str) -> None:
    state = delay_state_from_area_status(payload)
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
    panel = PanelState()
    handler = make_area_get_status_handler(panel, lambda _e, _c: None, now=lambda: 1.0)
    payload = dict(ELK_ENTRY_CAPTURE)
    payload["Chime"] = True
    assert handler({"area": {"get_status": payload}}, make_ctx()) is True
    assert panel.areas[1].chime is True


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
def test_entry_delay_mutation_proof(mutation: dict[str, object], expect_entry: bool) -> None:
    payload = _mutate(ELK_ENTRY_CAPTURE, **mutation)
    state = delay_state_from_area_status(payload)
    assert isinstance(state, DelayStateEntry) is expect_entry


def test_exit_end_rule_mutation_proof() -> None:
    armed_done = _exit_frame(arm_state="ARMED_AWAY", arm_cmd_state="ARMED_AWAY", ee_timer=1)
    assert delay_state_from_area_status(armed_done) is DELAY_NONE


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
    alarm = dict(ELK_ENTRY_CAPTURE, alarms="BURG", alrm_snd="BURG")
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
