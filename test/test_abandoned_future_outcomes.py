"""Futures nobody awaits any more still have their failure retrieved.

A failed future that is collected before anyone reads its exception makes asyncio
log "Future exception was never retrieved", and that log lands in whichever test
happens to trigger the collection.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

import pytest

from elke27_lib.client import Elke27Client
from elke27_lib.const import E27ErrorCode
from elke27_lib.errors import E27Timeout
from elke27_lib.events import ConnectionStateChanged, Event
from elke27_lib.kernel_loop import E27Kernel, KeepaliveTestHooks
from test.helpers.fake_session import FakePanelSession, connect_with_fake_panel
from test.helpers.internal import unretrieved_future_errors
from test.helpers.panel_command_driver import seed_area_disarmed
from test.helpers.panel_simulator import IDENTITY, LINK_KEYS, PanelSimulator

COMMAND_TIMEOUT_S = 0.5
PROBE_TIMEOUT_S = 0.25
SEND_WAIT_S = 30.0
WEDGED_COMMAND_TIMEOUT_S = 100.0


async def _settle() -> None:
    for _ in range(3):
        await asyncio.sleep(0)


async def _wait_for(cond: Callable[[], bool], *, timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if cond():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("condition not met in time")


async def _next_sent(panel: FakePanelSession, count: int) -> dict[str, Any]:
    async with asyncio.timeout(2.0):
        while len(panel.sent) < count:
            await asyncio.sleep(0.005)
    return dict(panel.sent[count - 1])


@pytest.mark.asyncio
async def test_timed_out_command_reply_failure_is_retrieved(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The kernel fails the reply future on a later loop turn, after async_execute
    has given up on it."""
    caplog.set_level(logging.ERROR, logger="asyncio")
    kernel = E27Kernel(
        skip_connect_bootstrap=True,
        request_max_retries=0,
        request_timeout_s=COMMAND_TIMEOUT_S,
    )
    client = Elke27Client(kernel=kernel)
    await connect_with_fake_panel(monkeypatch, client)
    monkeypatch.setattr(kernel, "command_transport_wait_budget_s", lambda _timeout_s: 0.01)
    result = await client.async_execute("control_get_version_info", timeout_s=5.0)
    assert result.ok is False
    assert isinstance(result.error, E27Timeout)
    await _settle()
    assert unretrieved_future_errors(caplog.records) == []


@pytest.mark.asyncio
async def test_keepalive_probe_failed_by_close_is_retrieved(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """close() cancels the keepalive task while its probe waits to be sent, then
    fails every pending reply future, the probe's included."""
    caplog.set_level(logging.ERROR, logger="asyncio")
    with PanelSimulator() as panel:
        kernel = E27Kernel(
            skip_connect_bootstrap=True,
            request_timeout_s=WEDGED_COMMAND_TIMEOUT_S,
            request_max_retries=0,
            keepalive_test_hooks=KeepaliveTestHooks(send_wait_s=SEND_WAIT_S),
        )
        drops: list[tuple[float, int]] = []

        def _on_event(evt: Event) -> None:
            if isinstance(evt, ConnectionStateChanged) and not evt.connected:
                drops.append((time.monotonic(), panel.probes))

        kernel.subscribe(_on_event, kinds=[ConnectionStateChanged.KIND])
        await kernel.connect(
            LINK_KEYS,
            client_identity=IDENTITY,
            session_config=panel.session_config(interval_s=30.0, timeout_s=PROBE_TIMEOUT_S),
        )
        try:
            kernel.request(("area", "get_status"), area_id=1)
            kernel.request_link_check()
            await asyncio.sleep(0.3)
            assert panel.probes == 0
            await kernel.close()
            await _settle()
            assert unretrieved_future_errors(caplog.records) == []
        finally:
            if kernel.state.panel.connected:
                await kernel.close()


@pytest.mark.asyncio
async def test_released_publication_failed_by_disconnect_is_retrieved(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A disconnect fails every publication waiter, including one whose command
    no longer waits on publication; releasing that command reads the failure.

    An ack-only ``area_set_arm_state`` still registers a publication future, then
    awaits a follow-up status refresh without waiting on that future. Disconnecting
    during the refresh fails the write's publication future; release retrieves it.
    """
    caplog.set_level(logging.ERROR, logger="asyncio")
    kernel = E27Kernel(
        skip_connect_bootstrap=True,
        request_max_retries=0,
        request_timeout_s=COMMAND_TIMEOUT_S,
    )
    client = Elke27Client(kernel=kernel)
    panel = await connect_with_fake_panel(monkeypatch, client)
    await seed_area_disarmed(panel)
    await asyncio.sleep(0)
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
    await _next_sent(panel, sent_before + 2)
    assert panel.on_disconnected is not None
    panel.on_disconnected(ConnectionResetError("panel dropped during refresh"))
    async with asyncio.timeout(COMMAND_TIMEOUT_S + 2.0):
        result = await task

    assert result.ok is True
    assert result.status_refresh_ok is False
    await _settle()
    assert unretrieved_future_errors(caplog.records) == []
