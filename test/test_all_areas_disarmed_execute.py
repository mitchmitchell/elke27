"""Disarmed gate follows arm_state mapping via async_raw_request (#109)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from typing import Any

import pytest

from elke27_lib.client import Elke27Client
from elke27_lib.errors import Elke27PermissionError
from test.helpers.fake_session import FakePanelSession, connect_with_fake_panel

_INSTALLER_RAW = {"net_dev": {"del_attribs": {"net_dev_id": 3}}}
_BLOCK_WAIT_S = 2.0


def _doc_status(area_id: int, arm_state: object, **fields: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "area_id": area_id,
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


def _status_without_arm_state(area_id: int) -> dict[str, object]:
    payload = _doc_status(area_id, "DISARMED")
    del payload["arm_state"]
    return payload


async def _seed_areas(panel: FakePanelSession, *payloads: dict[str, object]) -> None:
    for payload in payloads:
        await panel.deliver({"seq": 0, "area": {"get_status": payload}})


def _installer_raw_messages(sent: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [msg for msg in sent if msg.get("net_dev", {}).get("del_attribs") is not None]


async def _wait_for_installer_send(
    panel: FakePanelSession, after: int, task: asyncio.Task[Any]
) -> None:
    for _ in range(100):
        if _installer_raw_messages(panel.sent[after:]):
            return
        if task.done():
            result = await task
            pytest.fail(
                f"gate closed before send: {result.error!r}" if result.error else "unexpected ok"
            )
        await asyncio.sleep(0)
    pytest.fail("installer raw request was not sent before polling ended")


async def _assert_disarmed_gate_allows(client: Elke27Client, panel: FakePanelSession) -> None:
    after = len(panel.sent)
    task = asyncio.create_task(client.async_raw_request(_INSTALLER_RAW, allow_installer=True))
    await _wait_for_installer_send(panel, after, task)
    assert _installer_raw_messages(panel.sent[after:])
    sent = panel.sent[-1]
    await panel.deliver(
        {
            "seq": sent["seq"],
            "session_id": sent.get("session_id"),
            "net_dev": {"del_attribs": {}},
        }
    )
    result = await asyncio.wait_for(task, _BLOCK_WAIT_S)
    assert result.ok is True


@pytest.mark.asyncio
async def test_raw_request_passes_disarmed_gate_when_all_areas_disarmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Elke27Client(enable_raw_passthrough=True, skip_connect_bootstrap=True)
    panel = await connect_with_fake_panel(monkeypatch, client)
    await _seed_areas(panel, _doc_status(1, "DISARMED"), _doc_status(2, "DISARMED"))
    await _assert_disarmed_gate_allows(client, panel)


@pytest.mark.asyncio
async def test_raw_request_passes_disarmed_gate_for_padded_disarmed_strings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Elke27Client(enable_raw_passthrough=True, skip_connect_bootstrap=True)
    panel = await connect_with_fake_panel(monkeypatch, client)
    await _seed_areas(panel, _doc_status(1, " DISARMED "), _doc_status(2, "DISARMED"))
    await _assert_disarmed_gate_allows(client, panel)


@pytest.mark.parametrize(
    "seed",
    [
        pytest.param(
            lambda panel: _seed_areas(
                panel, _doc_status(1, "DISARMED"), _doc_status(2, "ARMED_AWAY")
            ),
            id="ARMED_AWAY",
        ),
        pytest.param(
            lambda panel: _seed_areas(panel, _doc_status(1, "stay")),
            id="unknown",
        ),
        pytest.param(
            lambda panel: _seed_areas(panel, _doc_status(1, "ALARM_MEM")),
            id="ALARM_MEM",
        ),
        pytest.param(
            lambda panel: _seed_areas(panel, _status_without_arm_state(1)),
            id="arm_state_missing",
        ),
        pytest.param(
            lambda panel: _seed_areas(panel, _doc_status(1, 7)),
            id="arm_state_non_string",
        ),
    ],
)
@pytest.mark.asyncio
async def test_raw_request_blocked_for_non_disarmed_arm_states(
    monkeypatch: pytest.MonkeyPatch,
    seed: Callable[[FakePanelSession], Any],
) -> None:
    client = Elke27Client(enable_raw_passthrough=True)
    panel = await connect_with_fake_panel(monkeypatch, client)
    await seed(panel)
    after = len(panel.sent)
    result = await asyncio.wait_for(
        client.async_raw_request(_INSTALLER_RAW, allow_installer=True),
        timeout=_BLOCK_WAIT_S,
    )
    assert result.ok is False
    assert isinstance(result.error, Elke27PermissionError)
    assert "disarmed" in str(result.error).lower()
    assert _installer_raw_messages(panel.sent[after:]) == []
