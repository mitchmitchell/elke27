"""A publication-wait timeout is an error, never a successful read (#147).

Drives ``Elke27Client`` through ``FakePanelSession`` with the public API only.
The client's snapshot publication runs in callbacks the kernel schedules with
``loop.call_soon_threadsafe``; holding the ones bound to the client keeps the
reply out of ``get_snapshot()`` past the command deadline, as a busy loop would.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import pytest

from elke27_lib import ArmMode, Elke27SnapshotPublicationError
from elke27_lib.client import Elke27Client
from elke27_lib.const import E27ErrorCode
from elke27_lib.kernel_loop import E27Kernel
from test.helpers.fake_session import FakePanelSession, connect_with_fake_panel
from test.helpers.panel_command_driver import seed_area_disarmed

COMMAND_TIMEOUT_S = 0.5


class _HeldPublication:
    """Holds client-bound cross-thread callbacks until ``release``."""

    def __init__(self, client: Elke27Client, loop: asyncio.AbstractEventLoop) -> None:
        self._client = client
        self._real = loop.call_soon_threadsafe
        self.held: list[tuple[Callable[..., Any], tuple[Any, ...]]] = []

    def __call__(self, fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any:
        if getattr(fn, "__self__", None) is self._client:
            self.held.append((fn, args))
            return None
        return self._real(fn, *args, **kwargs)

    def release(self) -> None:
        while self.held:
            fn, args = self.held.pop(0)
            fn(*args)


async def _connect(monkeypatch: pytest.MonkeyPatch) -> tuple[Elke27Client, FakePanelSession]:
    client = Elke27Client(kernel=E27Kernel(skip_connect_bootstrap=True, request_max_retries=0))
    panel = await connect_with_fake_panel(monkeypatch, client)
    await seed_area_disarmed(panel)
    await asyncio.sleep(0)
    assert client.get_snapshot().areas[1].arm_mode is ArmMode.DISARMED
    return client, panel


async def _next_sent(panel: FakePanelSession, count: int) -> dict[str, Any]:
    async with asyncio.timeout(2.0):
        while len(panel.sent) < count:
            await asyncio.sleep(0.005)
    return dict(panel.sent[count - 1])


def _armed_away_status(seq: object) -> dict[str, Any]:
    return {
        "seq": seq,
        "area": {
            "get_status": {
                "area_id": 1,
                "arm_state": "ARMED_AWAY",
                "error_code": E27ErrorCode.ELKERR_NONE,
            }
        },
    }


@pytest.mark.asyncio
async def test_status_read_publication_timeout_returns_error_not_stale_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, panel = await _connect(monkeypatch)
    loop = asyncio.get_running_loop()
    hold = _HeldPublication(client, loop)
    monkeypatch.setattr(loop, "call_soon_threadsafe", hold)
    sent_before = len(panel.sent)

    task = asyncio.create_task(
        client.async_execute("area_get_status", area_id=1, timeout_s=COMMAND_TIMEOUT_S)
    )
    sent = await _next_sent(panel, sent_before + 1)
    await panel.deliver(_armed_away_status(sent["seq"]))
    async with asyncio.timeout(COMMAND_TIMEOUT_S + 2.0):
        result = await task

    assert client.get_snapshot().areas[1].arm_mode is ArmMode.DISARMED
    assert result.ok is False
    assert isinstance(result.error, Elke27SnapshotPublicationError)

    monkeypatch.undo()
    hold.release()
    assert client.get_snapshot().areas[1].arm_mode is ArmMode.ARMED_AWAY


@pytest.mark.asyncio
async def test_ack_only_write_reports_failed_refresh_when_publication_times_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, panel = await _connect(monkeypatch)
    loop = asyncio.get_running_loop()
    hold = _HeldPublication(client, loop)
    monkeypatch.setattr(loop, "call_soon_threadsafe", hold)
    sent_before = len(panel.sent)

    task = asyncio.create_task(
        client.async_execute(
            "area_set_arm_state",
            area_id=1,
            arm_state="ARMED_AWAY",
            pin=1234,
            timeout_s=COMMAND_TIMEOUT_S,
        )
    )
    write = await _next_sent(panel, sent_before + 1)
    await panel.deliver(
        {
            "seq": write["seq"],
            "area": {"set_arm_state": {"area_id": 1, "error_code": E27ErrorCode.ELKERR_NONE}},
        }
    )
    refresh = await _next_sent(panel, sent_before + 2)
    assert "get_status" in refresh["area"]
    await panel.deliver(_armed_away_status(refresh["seq"]))
    async with asyncio.timeout(COMMAND_TIMEOUT_S + 2.0):
        result = await task

    assert client.get_snapshot().areas[1].arm_mode is ArmMode.DISARMED
    assert result.ok is True
    assert result.status_refresh_ok is False
    assert 1 in client.get_snapshot().stale_area_ids
