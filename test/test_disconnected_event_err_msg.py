"""The raw DISCONNECTED event carries err_msg and error_type like ConnectionStateChanged."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from elke27_lib.client import Elke27Client
from elke27_lib.types import EventType
from test.helpers.fake_session import connect_with_fake_panel


async def _disconnected_after_drop(
    monkeypatch: pytest.MonkeyPatch, err: Exception | None
) -> dict[str, Any]:
    client = Elke27Client()
    panel = await connect_with_fake_panel(monkeypatch, client)
    seen: list[Any] = []

    async def _drain() -> None:
        async for evt in client.events():
            seen.append(evt)

    drain_task = asyncio.create_task(_drain())
    await asyncio.sleep(0)
    assert panel.on_disconnected is not None
    panel.on_disconnected(err)
    await asyncio.wait_for(drain_task, timeout=2.0)
    disconnected = [e for e in seen if e.event_type == EventType.DISCONNECTED]
    assert len(disconnected) == 1
    return dict(disconnected[0].data)


@pytest.mark.asyncio
async def test_disconnected_event_carries_error_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = await _disconnected_after_drop(monkeypatch, TimeoutError("2 missed keepalive probes"))
    assert data["connected"] is False
    assert data["error_type"] == "TimeoutError"
    assert data["err_msg"] == "2 missed keepalive probes"


@pytest.mark.asyncio
async def test_disconnected_event_without_error_has_no_reason_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = await _disconnected_after_drop(monkeypatch, None)
    assert data["connected"] is False
    assert not data["err_msg"]
    assert data["error_type"] is None
