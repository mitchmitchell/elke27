from __future__ import annotations

import asyncio
import threading
from typing import Any, cast

import pytest

import elke27_lib.kernel_loop as kernel_mod
import elke27_lib.session_thread as session_mod
from elke27_lib.client import Elke27Client
from elke27_lib.const import E27ErrorCode
from elke27_lib.events import ConnectionStateChanged
from elke27_lib.session_thread import SessionConfig
from elke27_lib.types import EventType, LinkKeys
from test.helpers.fake_session import FakePanelSession, connect_with_fake_panel
from test.helpers.internal import reply_publication_pending
from test.helpers.panel_command_driver import connect_panel, connect_with_app_firmware


@pytest.mark.asyncio
async def test_close_delivers_disconnected_and_ends_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _panel = await connect_panel(monkeypatch)
    collected: list[Any] = []

    async def _drain() -> None:
        async for evt in client.events():
            collected.append(evt)

    drain_task = asyncio.create_task(_drain())
    await asyncio.sleep(0)
    assert (await client.close()).ok is True
    await asyncio.wait_for(drain_task, timeout=2.0)
    assert any(
        evt.event_type == EventType.DISCONNECTED and evt.data.get("reason") == "closed"
        for evt in collected
    )


@pytest.mark.asyncio
async def test_close_during_publication_wait_returns_disconnected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from elke27_lib.client import Elke27DisconnectedError

    client, panel = await connect_with_app_firmware(monkeypatch, 0)
    loop = asyncio.get_running_loop()
    client.bind_kernel_loop_thread_for_tests(loop)
    real_call_soon_threadsafe = loop.call_soon_threadsafe
    deferred: list[tuple[Any, tuple[Any, ...]]] = []
    reply = {
        "seq": 0,
        "area": {
            "get_status": {
                "area_id": 1,
                "arm_state": "DISARMED",
                "error_code": E27ErrorCode.ELKERR_NONE,
            }
        },
    }

    def intercept(fn: Any, /, *args: Any) -> None:
        fn_name = getattr(fn, "__name__", None)
        fn_self = getattr(fn, "__self__", None)
        if fn_self is client and fn_name == "_handle_kernel_event":
            if args and isinstance(args[0], ConnectionStateChanged):
                real_call_soon_threadsafe(fn, *args)
                return
            deferred.append((fn, args))
            return
        if fn_self is client and fn_name == "_complete_dispatch_only_reply_publication":
            deferred.append((fn, args))
            return
        real_call_soon_threadsafe(fn, *args)

    monkeypatch.setattr(loop, "call_soon_threadsafe", intercept)
    task = asyncio.create_task(client.async_execute("area_get_status", area_id=1, timeout_s=2.0))

    async def _wait_status_sent() -> dict[str, Any]:
        while True:
            for msg in panel.sent:
                area = msg.get("area")
                if isinstance(area, dict) and "get_status" in area:
                    return cast(dict[str, Any], msg)
            if task.done():
                raise AssertionError("execute finished before area_get_status was sent")
            await asyncio.sleep(0.01)

    sent = await _wait_status_sent()
    reply["seq"] = sent["seq"]
    reply_seq = sent["seq"]

    def receive_thread() -> None:
        assert panel.on_message is not None
        panel.on_message(reply)

    async def _wait_slot() -> None:
        while True:
            if reply_publication_pending(client, reply_seq) and not task.done():
                return
            if task.done():
                raise AssertionError("execute finished before publication slot registered")
            await asyncio.sleep(0.01)

    threading.Thread(target=receive_thread, name="close-publication-wait", daemon=True).start()
    async with asyncio.timeout(2.0):
        await _wait_slot()
    assert (await client.close()).ok is True
    result = await task
    assert not result.ok
    assert isinstance(result.error, Elke27DisconnectedError)


@pytest.mark.asyncio
async def test_close_then_async_connect_keeps_kernel_subscription(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subscribe_calls: list[int] = []
    real_subscribe = kernel_mod.E27Kernel.subscribe

    def tracked_subscribe(self: kernel_mod.E27Kernel, *args: Any, **kwargs: Any) -> int:
        subscribe_calls.append(1)
        return real_subscribe(self, *args, **kwargs)

    monkeypatch.setattr(kernel_mod.E27Kernel, "subscribe", tracked_subscribe)
    client = Elke27Client()
    await client.close()
    await connect_with_fake_panel(monkeypatch, client)
    assert subscribe_calls == [1]


@pytest.mark.asyncio
async def test_close_then_result_connect_keeps_kernel_subscription(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subscribe_calls: list[int] = []
    dispatch_calls: list[int] = []
    real_subscribe = kernel_mod.E27Kernel.subscribe
    real_add_dispatch = kernel_mod.E27Kernel.add_dispatch_listener

    def tracked_subscribe(self: kernel_mod.E27Kernel, *args: Any, **kwargs: Any) -> int:
        subscribe_calls.append(1)
        return real_subscribe(self, *args, **kwargs)

    def tracked_dispatch(self: kernel_mod.E27Kernel, *args: Any, **kwargs: Any) -> Any:
        dispatch_calls.append(1)
        return real_add_dispatch(self, *args, **kwargs)

    monkeypatch.setattr(kernel_mod.E27Kernel, "subscribe", tracked_subscribe)
    monkeypatch.setattr(kernel_mod.E27Kernel, "add_dispatch_listener", tracked_dispatch)
    from elke27_lib.linking_thread import E27Identity

    client = Elke27Client(skip_connect_bootstrap=True)
    await client.close()
    FakePanelSession.instances.clear()
    monkeypatch.setattr(session_mod, "Session", FakePanelSession)
    identity = E27Identity(mn="m", sn="s", fwver="f", hwver="h", osver="o")
    session_config = SessionConfig(host="panel.invalid", port=2101, wire_log=True)
    connect_result = await client.connect(
        LinkKeys("aa", "bb", "cc"),
        panel={"host": "panel.invalid", "port": 2101},
        client_identity=identity,
        session_config=session_config,
    )
    assert connect_result.ok is True
    assert subscribe_calls == [1]
    assert dispatch_calls == [1]
