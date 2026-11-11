"""Disarmed gate follows arm_state mapping via async_raw_request (#109)."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

import pytest
from _pytest.monkeypatch import MonkeyPatch

from elke27_lib.client import Elke27Client
from elke27_lib.errors import Elke27PermissionError
from test.helpers.fake_session import connect_with_fake_panel

_INSTALLER_RAW = {"net_dev": {"del_attribs": {"net_dev_id": 3}}}


def _doc_status(area_id: int, arm_state: str, **fields: object) -> dict[str, object]:
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


async def _seed_areas(panel: Any, *payloads: dict[str, object]) -> None:
    for payload in payloads:
        await panel.deliver({"seq": 0, "area": {"get_status": payload}})


def _installer_raw_messages(sent: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [msg for msg in sent if msg.get("net_dev", {}).get("del_attribs") is not None]


async def _assert_disarmed_gate_allows(client: Elke27Client) -> None:
    task = asyncio.create_task(client.async_raw_request(_INSTALLER_RAW, allow_installer=True))
    try:
        await asyncio.sleep(0.05)
        if task.done():
            result = await task
            assert not (
                isinstance(result.error, Elke27PermissionError)
                and "disarmed" in str(result.error).lower()
            )
        else:
            await asyncio.wait_for(task, timeout=0.01)
    except TimeoutError:
        pass
    finally:
        if not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task


@pytest.mark.asyncio
async def test_raw_request_passes_disarmed_gate_when_all_areas_disarmed(
    monkeypatch: MonkeyPatch,
) -> None:
    client = Elke27Client(enable_raw_passthrough=True)
    panel = await connect_with_fake_panel(monkeypatch, client)
    await _seed_areas(panel, _doc_status(1, "DISARMED"), _doc_status(2, "DISARMED"))
    await _assert_disarmed_gate_allows(client)


@pytest.mark.asyncio
async def test_raw_request_passes_disarmed_gate_for_padded_disarmed_strings(
    monkeypatch: MonkeyPatch,
) -> None:
    client = Elke27Client(enable_raw_passthrough=True)
    panel = await connect_with_fake_panel(monkeypatch, client)
    await _seed_areas(panel, _doc_status(1, " DISARMED "), _doc_status(2, "DISARMED"))
    await _assert_disarmed_gate_allows(client)


@pytest.mark.asyncio
async def test_raw_request_blocked_when_one_area_armed(monkeypatch: MonkeyPatch) -> None:
    client = Elke27Client(enable_raw_passthrough=True)
    panel = await connect_with_fake_panel(monkeypatch, client)
    await _seed_areas(panel, _doc_status(1, "DISARMED"), _doc_status(2, "ARMED_AWAY"))
    after = len(panel.sent)
    result = await client.async_raw_request(_INSTALLER_RAW, allow_installer=True)
    assert result.ok is False
    assert isinstance(result.error, Elke27PermissionError)
    assert _installer_raw_messages(panel.sent[after:]) == []


@pytest.mark.asyncio
async def test_raw_request_blocked_for_unmapped_arm_state(monkeypatch: MonkeyPatch) -> None:
    assert Elke27Client.arm_mode_from_panel_string("stay") is None
    client = Elke27Client(enable_raw_passthrough=True)
    panel = await connect_with_fake_panel(monkeypatch, client)
    await _seed_areas(panel, _doc_status(1, "stay"))
    after = len(panel.sent)
    result = await client.async_raw_request(_INSTALLER_RAW, allow_installer=True)
    assert result.ok is False
    assert isinstance(result.error, Elke27PermissionError)
    assert _installer_raw_messages(panel.sent[after:]) == []


@pytest.mark.asyncio
async def test_raw_request_blocked_for_alarm_mem_arm_state(monkeypatch: MonkeyPatch) -> None:
    client = Elke27Client(enable_raw_passthrough=True)
    panel = await connect_with_fake_panel(monkeypatch, client)
    await _seed_areas(panel, _doc_status(1, "ALARM_MEM"))
    after = len(panel.sent)
    result = await client.async_raw_request(_INSTALLER_RAW, allow_installer=True)
    assert result.ok is False
    assert isinstance(result.error, Elke27PermissionError)
    assert _installer_raw_messages(panel.sent[after:]) == []


@pytest.mark.asyncio
async def test_raw_request_blocked_when_arm_state_missing(monkeypatch: MonkeyPatch) -> None:
    payload = _doc_status(1, "DISARMED")
    del payload["arm_state"]
    client = Elke27Client(enable_raw_passthrough=True)
    panel = await connect_with_fake_panel(monkeypatch, client)
    await _seed_areas(panel, payload)
    after = len(panel.sent)
    result = await client.async_raw_request(_INSTALLER_RAW, allow_installer=True)
    assert result.ok is False
    assert isinstance(result.error, Elke27PermissionError)
    assert _installer_raw_messages(panel.sent[after:]) == []
