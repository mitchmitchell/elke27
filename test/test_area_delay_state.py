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
from elke27_lib.types import (
    DELAY_NONE,
    ArmMode,
    DelayStateEntry,
    DelayStateExit,
)
from elke27_lib.types import (
    AreaState as PublicAreaState,
)
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
            _exit_frame(
                arm_state="ARMED_AWAY",
                arm_cmd_state="DISARMED",
                ee_timer=20,
                alarm_zone="",
            ),
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
    assert arm_mode_from_panel_string("ARMED_STAY_INST") is ArmMode.ARMED_NIGHT


def test_armed_stay_inst_complete_is_not_delay() -> None:
    inst = "ARMED_STAY_INST"
    assert arm_mode_from_panel_string(inst) is ArmMode.ARMED_NIGHT
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
    snapshots = []
    for idx, frame in enumerate(frames):
        await panel.deliver({"seq": idx, "area": {"get_status": frame}})
        snapshots.append(client.snapshot.areas[1])
    for snap in snapshots[:2]:
        assert snap.entry_delay is True
        assert snap.arming is False
        assert isinstance(snap.delay_state, DelayStateEntry)
    last = snapshots[2]
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


def test_t12_armed_with_disarm_cmd_is_none() -> None:
    area = _area_from_payload(
        _exit_frame(arm_state="ARMED_AWAY", arm_cmd_state="DISARMED", ee_timer=20, alarm_zone="")
    )
    assert delay_state_from_area_status(area) is DELAY_NONE


@pytest.mark.asyncio
async def test_y03_public_flags_entry_vs_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Elke27Client()
    panel = await connect_with_fake_panel(monkeypatch, client)
    await panel.deliver({"seq": 0, "area": {"get_status": dict(ELK_ENTRY_CAPTURE, ee_timer=6)}})
    entry_snap = client.snapshot.areas[1]
    assert entry_snap.entry_delay is True
    assert entry_snap.arming is False
    await panel.deliver({"seq": 1, "area": {"get_status": _exit_frame(ee_timer=22)}})
    exit_snap = client.snapshot.areas[1]
    assert exit_snap.arming is True
    assert exit_snap.entry_delay is False


@pytest.mark.asyncio
async def test_c02_multi_area_snapshot_delay_states(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Elke27Client()
    panel = await connect_with_fake_panel(monkeypatch, client)
    area1_idle = {
        "area_id": 1,
        "arm_state": "DISARMED",
        "arm_cmd_state": "DISARMED",
        "ee_timer": 0,
        "alarm_zone": "",
        "alarms": "",
        "alrm_snd": "",
        "error_code": 0,
    }
    area2_exit = {**_exit_frame(ee_timer=33), "area_id": 2}
    await panel.deliver({"seq": 0, "area": {"get_status": area1_idle}})
    await panel.deliver({"seq": 1, "area": {"get_status": area2_exit}})
    assert client.snapshot.areas[1].delay_state is DELAY_NONE
    assert isinstance(client.snapshot.areas[2].delay_state, DelayStateExit)
    assert client.snapshot.areas[2].delay_state.seconds == 33

    area1_entry = dict(ELK_ENTRY_CAPTURE, ee_timer=7)
    area2_idle = dict(area1_idle)
    area2_idle["area_id"] = 2
    await panel.deliver({"seq": 2, "area": {"get_status": area1_entry}})
    await panel.deliver({"seq": 3, "area": {"get_status": area2_idle}})
    assert isinstance(client.snapshot.areas[1].delay_state, DelayStateEntry)
    assert client.snapshot.areas[2].delay_state is DELAY_NONE


@pytest.mark.asyncio
async def test_t18_alrm_snd_only_ends_entry_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Elke27Client()
    panel = await connect_with_fake_panel(monkeypatch, client)
    await panel.deliver({"seq": 0, "area": {"get_status": ELK_ENTRY_CAPTURE}})
    assert client.snapshot.areas[1].entry_delay is True
    await panel.deliver(
        {
            "seq": 1,
            "area": {
                "get_status": dict(ELK_ENTRY_CAPTURE, alarms="", alrm_snd="BURG"),
            },
        }
    )
    snap = client.snapshot.areas[1]
    assert snap.entry_delay is False
    assert snap.delay_state is DELAY_NONE


def test_t13_unknown_arm_cmd_state_blocks_exit() -> None:
    area = AreaState(
        area_id=1,
        arm_state="DISARMED",
        arm_cmd_state="ARMED_SOMETHING_NEW",
        ee_timer=25,
        alarm_zone="",
    )
    assert delay_state_from_area_status(area) is DELAY_NONE


def test_t14_unknown_arm_state_blocks_exit() -> None:
    area = AreaState(
        area_id=1,
        arm_state="ARMED_SOMETHING_NEW",
        arm_cmd_state="ARMED_AWAY",
        ee_timer=25,
        alarm_zone="",
    )
    assert delay_state_from_area_status(area) is DELAY_NONE


def test_t16_unknown_arm_state_blocks_entry() -> None:
    area = AreaState(
        area_id=1,
        arm_state="ARMED_SOMETHING_NEW",
        ee_timer=9,
        alarm_zone="ID:6 - Zone 6",
    )
    assert delay_state_from_area_status(area) is DELAY_NONE


def test_t15_armed_state_fallback_for_entry() -> None:
    area = AreaState(
        area_id=1,
        armed_state="ARMED_STAY",
        arm_state=None,
        ee_timer=8,
        alarm_zone="  padded  ",
    )
    entry = delay_state_from_area_status(area)
    assert isinstance(entry, DelayStateEntry)
    assert entry.zone == "padded"


def test_t05_entry_zone_is_stripped() -> None:
    area = AreaState(
        area_id=1,
        arm_state="ARMED_STAY",
        ee_timer=5,
        alarm_zone="  ID:6 - Zone 6  ",
    )
    entry = delay_state_from_area_status(area)
    assert isinstance(entry, DelayStateEntry)
    assert entry.zone == "ID:6 - Zone 6"


def test_t07_whitespace_only_alarm_zone_is_blank() -> None:
    area = AreaState(
        area_id=1,
        arm_state="ARMED_STAY",
        ee_timer=5,
        alarm_zone="   ",
    )
    assert delay_state_from_area_status(area) is DELAY_NONE


def test_t08_none_alarm_zone_is_not_entry() -> None:
    area = AreaState(
        area_id=1,
        arm_state="ARMED_AWAY",
        ee_timer=12,
        alarm_zone=None,
    )
    state = delay_state_from_area_status(area)
    assert state is DELAY_NONE
    assert not isinstance(state, DelayStateEntry)


def test_t10_negative_ee_timer_is_blank() -> None:
    area = AreaState(
        area_id=1,
        arm_state="DISARMED",
        arm_cmd_state="ARMED_AWAY",
        ee_timer=-3,
        alarm_zone="",
    )
    assert delay_state_from_area_status(area) is DELAY_NONE


def test_i01_i02_public_all_exports_delay_symbols() -> None:
    import elke27_lib

    assert "DelayStateExit" in elke27_lib.__all__
    assert "DelayStateEntry" in elke27_lib.__all__
    assert "DelayStateNone" in elke27_lib.__all__
    assert "DelayState" in elke27_lib.__all__
    assert "delay_state_from_area_status" not in elke27_lib.__all__
    assert "delay_state_from_area_status" not in dir(elke27_lib)


def test_y05_public_area_state_default_delay() -> None:
    assert PublicAreaState(area_id=1).delay_state is DELAY_NONE
