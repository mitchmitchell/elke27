"""Client snapshot ``alarm_active`` follows area.get_status alarms, including clearing (#98)."""

from __future__ import annotations

import pytest

from elke27_lib.client import Elke27Client
from test.helpers.fake_session import connect_with_fake_panel


def _status(**fields: object) -> dict[str, object]:
    """A documented ``area.get_status`` response with the given fields replaced."""
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
        "error_code": 0,
    }
    payload.update(fields)
    return payload


async def _alarm_active_sequence(
    monkeypatch: pytest.MonkeyPatch, *payloads: dict[str, object]
) -> list[bool | None]:
    """Deliver each status in turn and record snapshot ``alarm_active`` after each."""
    client = Elke27Client()
    panel = await connect_with_fake_panel(monkeypatch, client)
    seen: list[bool | None] = []
    for payload in payloads:
        await panel.deliver({"seq": 0, "area": {"get_status": payload}})
        seen.append(client.snapshot.areas[1].alarm_active)
    return seen


@pytest.mark.asyncio
async def test_snapshot_alarm_active_set_then_cleared(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = await _alarm_active_sequence(
        monkeypatch,
        _status(),
        _status(alarms="BURG", alrm_snd="BURG", alarm_zone="Front door"),
        _status(alarms="", alrm_snd=""),
    )
    assert seen == [False, True, False]


@pytest.mark.parametrize(
    "fields",
    [{"alarms": "FIRE"}, {"alarms": ["BURG"]}, {"alrm_snd": True}],
)
@pytest.mark.asyncio
async def test_snapshot_alarm_active_true_for_reported_alarm(
    monkeypatch: pytest.MonkeyPatch, fields: dict[str, object]
) -> None:
    assert await _alarm_active_sequence(monkeypatch, _status(**fields)) == [True]


@pytest.mark.parametrize(
    "fields",
    [{}, {"alarms": "FIRE TROUBLE"}, {"alarms": "", "alrm_snd": "CO TROUBLE"}],
)
@pytest.mark.asyncio
async def test_snapshot_alarm_active_false_without_alarm(
    monkeypatch: pytest.MonkeyPatch, fields: dict[str, object]
) -> None:
    assert await _alarm_active_sequence(monkeypatch, _status(**fields)) == [False]
