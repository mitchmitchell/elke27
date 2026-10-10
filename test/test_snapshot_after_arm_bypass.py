"""Regression for issue #15: snapshot must track panel after arm/bypass."""

from __future__ import annotations

import asyncio
import threading
from typing import Any, cast

import pytest

from elke27_lib.client import ArmMode, Elke27Client, Result
from elke27_lib.const import E27ErrorCode
from elke27_lib.events import (
    UNSET_AT,
    UNSET_CLASSIFICATION,
    UNSET_ROUTE,
    UNSET_SEQ,
    UNSET_SESSION_ID,
    AreaStatusUpdated,
    PanelAttribsUpdated,
)
from elke27_lib.types import EventType, PanelInfo
from test.helpers.fake_panel_replies import synthetic_success_reply
from test.helpers.internal import get_kernel, get_private
from test.test_panel_errors_ready_night import _FakeSession, _make_client


async def _drive_until_done(
    client: Elke27Client,
    session: _FakeSession,
    call: Any,
    *,
    first_reply: dict[str, Any] | None = None,
    max_replies: int | None = None,
) -> Any:
    task = asyncio.ensure_future(call)
    on_message = get_private(get_kernel(client), "_on_message")
    seen = 0
    cast(Any, client)._connected = True
    client._event_loop = asyncio.get_running_loop()
    while not task.done():
        await asyncio.sleep(0)
        if max_replies is not None and seen >= max_replies:
            continue
        while seen < len(session.sent):
            sent = session.sent[seen]
            if seen == 0 and first_reply is not None:
                reply = dict(first_reply)
                reply["seq"] = sent["seq"]
                on_message(reply)
            else:
                on_message(synthetic_success_reply(sent, sent_history=session.sent[:seen]))
            seen += 1
    return await task


@pytest.mark.asyncio
async def test_arm_ack_only_then_get_status_updates_snapshot() -> None:
    client, session = _make_client()
    kernel = get_kernel(client)
    area = kernel.state.get_or_create_area(1)
    area.arm_state = "DISARMED"

    await _drive_until_done(
        client,
        session,
        client.async_arm_area(1, mode=ArmMode.ARMED_AWAY, pin="1234"),
        first_reply={
            "seq": 0,
            "area": {"set_arm_state": {"area_id": 1, "error_code": E27ErrorCode.ELKERR_NONE}},
        },
    )

    assert len(session.sent) == 2
    assert "get_status" in session.sent[1]["area"]
    assert client.snapshot.areas[1].arm_mode == ArmMode.ARMED_AWAY
    assert client.snapshot.stale is False


@pytest.mark.asyncio
async def test_zone_bypass_ack_only_then_get_status_updates_snapshot() -> None:
    client, session = _make_client()
    kernel = get_kernel(client)
    zone = kernel.state.get_or_create_zone(17)
    zone.area_id = 1
    zone.bypassed = False

    await _drive_until_done(
        client,
        session,
        client.async_set_zone_bypass(17, bypassed=True, pin="1234"),
        first_reply={
            "seq": 0,
            "zone": {"set_status": {"zone_id": 17, "error_code": E27ErrorCode.ELKERR_NONE}},
        },
    )

    assert len(session.sent) == 2
    assert "get_status" in session.sent[1]["zone"]
    assert client.snapshot.zones[17].bypassed is True
    assert client.snapshot.stale is False


@pytest.mark.asyncio
async def test_set_arm_state_reply_with_arm_state_skips_follow_up_read() -> None:
    client, session = _make_client()
    kernel = get_kernel(client)
    kernel.state.get_or_create_area(1).arm_state = "DISARMED"

    result = await _drive_until_done(
        client,
        session,
        client.async_execute(
            "area_set_arm_state",
            area_id=1,
            arm_state="ARMED_STAY",
            pin=1234,
        ),
        first_reply={
            "seq": 0,
            "area": {
                "set_arm_state": {
                    "area_id": 1,
                    "error_code": E27ErrorCode.ELKERR_NONE,
                    "arm_state": "ARMED_STAY",
                }
            },
        },
        max_replies=1,
    )

    assert isinstance(result, Result)
    assert result.ok is True
    assert result.status_refresh_ok is True
    assert len(session.sent) == 1
    assert client.snapshot.areas[1].arm_mode == ArmMode.ARMED_STAY


@pytest.mark.asyncio
async def test_arm_ok_when_status_read_times_out() -> None:
    client, session = _make_client()
    kernel = get_kernel(client)
    kernel.state.get_or_create_area(1).arm_state = "DISARMED"
    client._replace_snapshot(
        areas=client._build_area_map(),
    )

    result = await _drive_until_done(
        client,
        session,
        client.async_execute(
            "area_set_arm_state",
            area_id=1,
            arm_state="ARMED_AWAY",
            pin=1234,
            timeout_s=0.05,
        ),
        first_reply={
            "seq": 0,
            "area": {"set_arm_state": {"area_id": 1, "error_code": E27ErrorCode.ELKERR_NONE}},
        },
        max_replies=1,
    )

    assert isinstance(result, Result)
    assert result.ok is True
    assert result.status_refresh_ok is False
    assert client.snapshot.stale is True


@pytest.mark.asyncio
async def test_arm_ok_when_status_read_returns_panel_error() -> None:
    client, session = _make_client()
    kernel = get_kernel(client)
    kernel.state.get_or_create_area(1).arm_state = "DISARMED"
    client._replace_snapshot(
        areas=client._build_area_map(),
    )

    task = asyncio.create_task(
        client.async_execute(
            "area_set_arm_state",
            area_id=1,
            arm_state="ARMED_AWAY",
            pin=1234,
        )
    )
    on_message = get_private(kernel, "_on_message")
    client._event_loop = asyncio.get_running_loop()
    seen = 0
    while not task.done():
        await asyncio.sleep(0)
        while seen < len(session.sent):
            sent = session.sent[seen]
            if seen == 0:
                on_message(
                    {
                        "seq": sent["seq"],
                        "area": {
                            "set_arm_state": {
                                "area_id": 1,
                                "error_code": E27ErrorCode.ELKERR_NONE,
                            }
                        },
                    }
                )
            elif seen == 1:
                on_message(
                    {
                        "seq": sent["seq"],
                        "area": {
                            "get_status": {
                                "area_id": 1,
                                "error_code": int(E27ErrorCode.ELKERR_INVALID_PIN),
                            }
                        },
                    }
                )
            seen += 1
    result = await task

    assert result.ok is True
    assert result.status_refresh_ok is False
    assert client.snapshot.stale is True


def test_unrelated_snapshot_update_preserves_stale_flag() -> None:
    """Regression for Bugbot r4238451936 / commit 9728ee1."""
    client = Elke27Client()
    client._replace_snapshot(panel_info=PanelInfo(model="M1"))
    client._mark_snapshot_stale()
    assert client.snapshot.stale is True

    client._handle_kernel_event(
        PanelAttribsUpdated(
            kind=PanelAttribsUpdated.KIND,
            at=UNSET_AT,
            seq=UNSET_SEQ,
            classification=UNSET_CLASSIFICATION,
            route=UNSET_ROUTE,
            session_id=UNSET_SESSION_ID,
            changed_fields=("panel_name",),
        )
    )

    assert client.snapshot.stale is True


def test_mark_snapshot_stale_notifies_subscribers() -> None:
    client = Elke27Client()
    client._replace_snapshot(panel_info=PanelInfo(model="M1"))
    seen: list[object] = []
    client.subscribe(lambda evt: seen.append(evt))

    client._mark_snapshot_stale()

    assert len(seen) == 1
    evt = seen[0]
    assert getattr(evt, "event_type", None) == EventType.PANEL
    assert getattr(evt, "data", {}).get("stale") is True


def test_area_arm_status_reconciliation_clears_stale_flag() -> None:
    client = Elke27Client()
    kernel = get_kernel(client)
    kernel.state.get_or_create_area(1).arm_state = "ARMED_AWAY"
    client._replace_snapshot(areas=client._build_area_map())
    client._mark_snapshot_stale()
    assert client.snapshot.stale is True

    client._handle_kernel_event(
        AreaStatusUpdated(
            kind=AreaStatusUpdated.KIND,
            at=UNSET_AT,
            seq=UNSET_SEQ,
            classification=UNSET_CLASSIFICATION,
            route=UNSET_ROUTE,
            session_id=UNSET_SESSION_ID,
            area_id=1,
            changed_fields=("arm_state",),
        )
    )

    assert client.snapshot.stale is False


@pytest.mark.asyncio
async def test_async_execute_waits_for_receive_thread_snapshot_publication() -> None:
    """Regression for Codex r4238451930 (receive-thread resolve before loop dispatch).

    ``E27Kernel._on_message`` resolves the pending future before ``dispatch`` and
    ``client._on_kernel_event`` schedules ``_handle_kernel_event`` with
    ``call_soon_threadsafe``. A same-thread ``call_soon`` driver cannot reproduce
    that gap; deliver the panel reply from a worker thread and defer
    ``call_soon_threadsafe(_handle_kernel_event)`` so ``async_execute`` would return
    before snapshot publication without ``_await_snapshot_publication``.
    """
    client, session = _make_client()
    loop = asyncio.get_running_loop()
    cast(Any, client)._connected = True
    client._event_loop = loop
    kernel = get_kernel(client)
    kernel.state.get_or_create_area(1).arm_state = "DISARMED"
    client._replace_snapshot(areas=client._build_area_map())

    deferred_handles: list[tuple[Any, tuple[Any, ...]]] = []
    real_call_soon_threadsafe = loop.call_soon_threadsafe

    def intercept_call_soon_threadsafe(fn: Any, /, *args: Any) -> None:
        if (
            getattr(fn, "__name__", None) == "_handle_kernel_event"
            and getattr(fn, "__self__", None) is client
        ):
            deferred_handles.append((fn, args))
            return
        real_call_soon_threadsafe(fn, *args)

    loop.call_soon_threadsafe = intercept_call_soon_threadsafe  # type: ignore[method-assign]

    async def flush_deferred_snapshot_handles() -> None:
        while not deferred_handles:
            await asyncio.sleep(0)
        await asyncio.sleep(0.02)
        while deferred_handles:
            fn, args = deferred_handles.pop(0)
            fn(*args)

    flush_task = asyncio.create_task(flush_deferred_snapshot_handles())
    snapshot_version_before = client.snapshot.version

    task = asyncio.create_task(
        client.async_execute(
            "area_set_arm_state",
            area_id=1,
            arm_state="ARMED_AWAY",
            pin=1234,
        )
    )

    while not session.sent:
        await asyncio.sleep(0.01)

    sent = session.sent[0]
    on_message = get_private(kernel, "_on_message")
    reply = {
        "seq": sent["seq"],
        "area": {
            "set_arm_state": {
                "area_id": 1,
                "error_code": E27ErrorCode.ELKERR_NONE,
                "arm_state": "ARMED_AWAY",
            }
        },
    }

    delivery_error: list[BaseException] = []

    def receive_thread() -> None:
        try:
            on_message(reply)
        except BaseException as exc:  # noqa: BLE001
            delivery_error.append(exc)

    threading.Thread(target=receive_thread, name="fake-receive", daemon=True).start()

    result = await task

    assert delivery_error == []
    assert isinstance(result, Result)
    assert result.ok is True
    assert result.status_refresh_ok is True
    assert client.snapshot.version > snapshot_version_before
    assert client.snapshot.areas[1].arm_mode == ArmMode.ARMED_AWAY

    await flush_task
    loop.call_soon_threadsafe = real_call_soon_threadsafe  # type: ignore[method-assign]
