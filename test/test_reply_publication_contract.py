from __future__ import annotations

import asyncio
import gc
import logging
from typing import Any, cast

import pytest

from elke27_lib.client import Elke27DisconnectedError, Elke27SnapshotPublicationError, Result
from elke27_lib.const import E27ErrorCode
from elke27_lib.errors import ConnectionLost
from test.helpers.internal import deliver_panel_message, get_kernel, get_private
from test.test_panel_errors_ready_night import _make_client
from test.test_snapshot_after_arm_bypass import (
    _connect_client_for_fake_panel,
    _drive_until_done,
    _sync_area_disarmed_snapshot,
    _sync_zones_ready_snapshot,
)

_PUBLICATION_TIMEOUT_LOG = "Timed out waiting for reply seq="


@pytest.mark.asyncio
async def test_close_then_reconnect_dispatch_only_area_get_status(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, session = _make_client()
    kernel = get_kernel(client)
    loop = asyncio.get_running_loop()
    _connect_client_for_fake_panel(client, loop)
    client.bind_kernel_loop_thread_for_tests(loop)
    _sync_area_disarmed_snapshot(client, kernel)
    caplog.set_level(logging.WARNING, logger="elke27_lib.client")
    monkeypatch.setattr(
        kernel,
        "command_transport_wait_budget_s",
        lambda _request_timeout_s: 0.5,
    )

    async def _noop_kernel_close() -> None:
        return None

    monkeypatch.setattr(kernel, "close", _noop_kernel_close)
    listeners = get_private(kernel, "_dispatch_listeners")
    assert len(listeners) == 1
    await client.close()
    assert len(listeners) == 0
    assert get_private(client, "_kernel_event_token") is None
    _connect_client_for_fake_panel(client, loop)
    cast(Any, client)._connected = True
    client._ensure_kernel_subscription()
    assert len(listeners) == 1
    result = await _drive_until_done(
        client,
        session,
        client.async_execute("area_get_status", area_id=1, timeout_s=2.0),
        first_reply={
            "seq": 0,
            "area": {
                "get_status": {
                    "error_code": E27ErrorCode.ELKERR_NONE,
                    "area_id": 0,
                }
            },
        },
        max_replies=1,
    )
    assert isinstance(result, Result)
    assert result.ok is True
    assert not any(_PUBLICATION_TIMEOUT_LOG in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_session_loss_during_area_get_status_returns_connection_lost(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, session = _make_client()
    kernel = get_kernel(client)
    loop = asyncio.get_running_loop()
    _connect_client_for_fake_panel(client, loop)
    client.bind_kernel_loop_thread_for_tests(loop)
    _sync_area_disarmed_snapshot(client, kernel)
    caplog.set_level(logging.ERROR, logger="asyncio")
    task = asyncio.create_task(client.async_execute("area_get_status", area_id=1, timeout_s=2.0))
    while not session.sent:
        await asyncio.sleep(0)
    kernel.state.panel.connected = True
    get_private(kernel, "_on_session_disconnected")(ConnectionResetError())
    result = await task
    gc.collect()
    assert isinstance(result, Result)
    assert not result.ok
    assert isinstance(result.error, ConnectionLost)
    assert not any("Future exception was never retrieved" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_session_loss_during_zone_get_status_returns_connection_lost(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, session = _make_client()
    kernel = get_kernel(client)
    loop = asyncio.get_running_loop()
    _connect_client_for_fake_panel(client, loop)
    client.bind_kernel_loop_thread_for_tests(loop)
    _sync_zones_ready_snapshot(client, kernel, (1,))
    caplog.set_level(logging.ERROR, logger="asyncio")
    task = asyncio.create_task(client.async_execute("zone_get_status", zone_id=1))
    while not session.sent:
        await asyncio.sleep(0)
    kernel.state.panel.connected = True
    get_private(kernel, "_on_session_disconnected")(ConnectionResetError())
    result = await task
    gc.collect()
    assert isinstance(result, Result)
    assert not result.ok
    assert isinstance(result.error, ConnectionLost)
    assert not any("Future exception was never retrieved" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_snapshot_publication_failure_returns_failed_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, session = _make_client()
    kernel = get_kernel(client)
    loop = asyncio.get_running_loop()
    _connect_client_for_fake_panel(client, loop)
    client.bind_kernel_loop_thread_for_tests(loop)
    _sync_area_disarmed_snapshot(client, kernel)

    def _area_map_build_failed() -> dict[int, Any]:
        raise ValueError("snapshot area map build failed for contract test")

    monkeypatch.setattr(client, "_build_area_map", _area_map_build_failed)
    task = asyncio.create_task(client.async_execute("area_get_status", area_id=1, timeout_s=2.0))
    result = await _drive_until_done(
        client,
        session,
        task,
        first_reply={
            "seq": 0,
            "area": {
                "get_status": {
                    "area_id": 1,
                    "arm_state": "DISARMED",
                    "error_code": E27ErrorCode.ELKERR_NONE,
                }
            },
        },
        max_replies=1,
    )
    assert isinstance(result, Result)
    assert not result.ok
    assert isinstance(result.error, Elke27SnapshotPublicationError)


@pytest.mark.asyncio
async def test_publication_budget_exhausted_releases_reply_slot(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, _session = _make_client()
    loop = asyncio.get_running_loop()
    _connect_client_for_fake_panel(client, loop)
    caplog.set_level(logging.WARNING, logger="elke27_lib.client")
    client._begin_reply_publication_command(1, ("area", "get_status"), loop)
    await client._await_reply_snapshot_publication(1, deadline=loop.time() - 1.0)
    assert any(_PUBLICATION_TIMEOUT_LOG in rec.message for rec in caplog.records)
    assert get_private(client, "_reply_publication_by_seq") == {}


@pytest.mark.asyncio
async def test_disconnected_publication_wait_raises_without_slot() -> None:
    client, _session = _make_client()
    loop = asyncio.get_running_loop()
    _connect_client_for_fake_panel(client, loop)
    cast(Any, client)._connected = False
    with pytest.raises(Elke27DisconnectedError):
        await client._await_reply_snapshot_publication(1, deadline=loop.time() + 5.0)


@pytest.mark.asyncio
async def test_cancel_releases_reply_publication_slot_for_follow_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, session = _make_client()
    loop = asyncio.get_running_loop()
    _connect_client_for_fake_panel(client, loop)
    client.bind_kernel_loop_thread_for_tests(loop)
    kernel = get_kernel(client)
    _sync_area_disarmed_snapshot(client, kernel)
    monkeypatch.setattr(
        kernel,
        "command_transport_wait_budget_s",
        lambda _request_timeout_s: 2.0,
    )
    task = asyncio.create_task(client.async_execute("area_get_status", area_id=1, timeout_s=5.0))
    while not session.sent:
        await asyncio.sleep(0)
    for _ in range(500):
        if kernel.dispatcher.pending_count() > 0:
            break
        await asyncio.sleep(0)
    cancelled_seq = session.sent[0]["seq"]
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0)
    assert cancelled_seq not in get_private(client, "_reply_publication_by_seq")
    follow_up = asyncio.create_task(
        client.async_execute("area_get_status", area_id=1, timeout_s=2.0)
    )
    while len(session.sent) < 2:
        await asyncio.sleep(0)
    reply = {
        "seq": session.sent[1]["seq"],
        "area": {
            "get_status": {
                "area_id": 1,
                "arm_state": "DISARMED",
                "error_code": E27ErrorCode.ELKERR_NONE,
            }
        },
    }
    while not follow_up.done():
        deliver_panel_message(kernel, reply)
        await asyncio.sleep(0)
    follow_result = await follow_up
    assert isinstance(follow_result, Result)
    assert follow_result.ok is True
