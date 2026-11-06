from __future__ import annotations

import asyncio
import concurrent.futures
import inspect
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

import pytest

from elke27_lib import discovery, linking_thread
from elke27_lib.client import Elke27Client
from elke27_lib.kernel_loop import E27Kernel
from elke27_lib.pending_loop import PendingResponseManager

_REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.asyncio
async def test_kernel_link_tcp_path_runs_off_asyncio_loop_thread() -> None:
    captured: dict[str, threading.Thread] = {}

    def _fake_do_tcp_api_link(*_a: object, **_k: object) -> linking_thread.E27LinkKeys:
        captured["worker"] = threading.current_thread()
        return linking_thread.E27LinkKeys(
            tempkey_hex="0" * 32,
            linkkey_hex="0" * 32,
            linkhmac_hex="0" * 40,
        )

    panel: dict[str, Any] = {"host": "127.0.0.1", "port": 1}
    identity = linking_thread.E27Identity(
        mn="222", sn="000000001", fwver="0.1", hwver="0.1", osver="0.1"
    )
    creds = type("C", (), {"access_code": "1", "passphrase": "2"})

    kernel = E27Kernel()
    with mock.patch.object(linking_thread, "do_tcp_api_link", _fake_do_tcp_api_link):
        await kernel.link(panel, identity, creds)

    assert "worker" in captured
    assert captured["worker"] is not threading.main_thread()
    assert threading.current_thread() is threading.main_thread()


def test_session_marshals_callbacks_with_call_soon_threadsafe() -> None:
    session_text = (_REPO_ROOT / "src" / "elke27_lib" / "session_thread.py").read_text(
        encoding="utf-8"
    )
    assert "call_soon_threadsafe" in session_text
    assert "def _invoke_on_loop" in session_text


def test_pending_loop_uses_acquire_timeout_on_shared_lock() -> None:
    pending_text = (_REPO_ROOT / "src" / "elke27_lib" / "pending_loop.py").read_text(
        encoding="utf-8"
    )
    assert pending_text.count("acquire(timeout=") >= 5


@pytest.mark.parametrize(
    ("obj", "method"),
    [
        (PendingResponseManager(), "create"),
        (PendingResponseManager(), "drop"),
        (PendingResponseManager(), "pending_count"),
        (PendingResponseManager(), "fail_all"),
        (Elke27Client(kernel=E27Kernel()), "subscribe"),
        (Elke27Client(kernel=E27Kernel()), "unsubscribe"),
        (Elke27Client(kernel=E27Kernel()), "subscribe_typed"),
        (Elke27Client(kernel=E27Kernel()), "unsubscribe_typed"),
        (E27Kernel(), "load_features_blocking"),
    ],
)
def test_lock_uses_acquire_timeout(obj: object, method: str) -> None:
    fn = getattr(obj, method)
    assert "acquire(timeout=" in inspect.getsource(fn)


def test_pending_manager_create_raises_when_30s_lock_times_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import elke27_lib.pending_loop as pending_mod
    from elke27_lib.pending_loop import PendingResponseManager

    loop = asyncio.new_event_loop()
    try:

        class _Lock:
            def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:  # noqa: ARG002
                if timeout == 30.0:
                    return False
                return True

            def release(self) -> None:
                return None

        monkeypatch.setattr(pending_mod.threading, "Lock", _Lock)
        m = PendingResponseManager()
        with pytest.raises(RuntimeError, match="Pending response lock contention timed out"):
            m.create(1, command_key="k", expected_route=("a", "b"), loop=loop)
    finally:
        loop.close()


def test_discovery_async_scan_uses_executor_for_udp_socket() -> None:
    src = inspect.getsource(discovery.AIOELKDiscovery.async_scan)
    assert "asyncio.to_thread" in src
    assert "create_udp_socket" in src
    assert "_destinations_from_address" in src


@pytest.mark.asyncio
async def test_close_scheduled_on_loop_returns_quickly_with_blocked_recv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import elke27_lib.session_thread as session_mod

    class _SlowSock:
        def settimeout(self, _t: float) -> None:
            return None

        def connect(self, _a: object) -> None:
            return None

        def close(self) -> None:
            return None

        def recv(self, _n: int) -> bytes:
            time.sleep(30.0)
            return b""

    loop = asyncio.get_running_loop()
    done = asyncio.Event()
    cfg = session_mod.SessionConfig(
        host="example",
        auto_receive=True,
        io_timeout_s=60.0,
        auto_receive_thread_fallback=True,
    )
    sess = session_mod.Session(
        cfg,
        client_identity=session_mod.linking.E27Identity("m", "s", "f", "h", "o"),
        link_key_hex="00",
    )
    monkeypatch.setattr(session_mod.socket, "socket", lambda *_a, **_k: _SlowSock())
    monkeypatch.setattr(
        session_mod,
        "perform_hello",
        lambda **_k: SimpleNamespace(
            session_id=1, session_key_hex="00" * 16, hmac_key_hex="11" * 16
        ),
    )
    sess.on_message = lambda _m: None
    sess.bind_loop(loop)
    await asyncio.to_thread(sess.connect)

    started = time.monotonic()

    def _close_from_loop() -> None:
        try:
            sess.close()
        finally:
            loop.call_soon_threadsafe(done.set)

    loop.call_soon_threadsafe(_close_from_loop)
    await asyncio.wait_for(done.wait(), timeout=2.0)
    assert time.monotonic() - started < 1.5


@pytest.mark.asyncio
async def test_hello_failure_notifies_disconnect_on_bound_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import elke27_lib.session_thread as session_mod
    from elke27_lib.errors import E27Error
    from elke27_lib.session_thread import SessionProtocolError

    tids: list[int] = []

    def _on_disc(_e: object) -> None:
        tids.append(threading.get_ident())

    loop = asyncio.get_running_loop()
    cfg = session_mod.SessionConfig(host="example", auto_receive=False)
    sess = session_mod.Session(
        cfg,
        client_identity=session_mod.linking.E27Identity("m", "s", "f", "h", "o"),
        link_key_hex="00",
    )
    sess.on_disconnected = _on_disc
    sess.bind_loop(loop)

    class _Sock:
        def settimeout(self, _t: float) -> None:
            return None

        def connect(self, _a: object) -> None:
            return None

        def close(self) -> None:
            return None

    monkeypatch.setattr(session_mod.socket, "socket", lambda *_a, **_k: _Sock())
    monkeypatch.setattr(
        session_mod,
        "perform_hello",
        lambda **_k: (_ for _ in ()).throw(E27Error("no hello")),
    )

    def _go() -> None:
        with pytest.raises(SessionProtocolError):
            sess.connect()

    await asyncio.to_thread(_go)
    await asyncio.sleep(0.05)
    assert tids == [threading.get_ident()]


@pytest.mark.asyncio
async def test_sync_authenticate_worker_thread_sees_threaded_opaque_fill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Elke27Client(kernel=E27Kernel())
    client._kernel.state.panel.session_id = 1
    fut: concurrent.futures.Future[dict[str, object]] = concurrent.futures.Future()

    def _req(*_a: object, **_k: object) -> int:
        def _fill() -> None:
            time.sleep(0.05)
            fut.set_result({"success": True, "error_code": 0})

        threading.Thread(target=_fill, daemon=True).start()
        return 7

    monkeypatch.setattr(client._kernel, "request", _req)
    r = await asyncio.to_thread(
        client.request,
        ("control", "authenticate"),
        pin=1234,
        opaque=fut,
    )
    assert r.ok is True


@pytest.mark.asyncio
async def test_outbound_on_sent_exception_triggers_on_fail() -> None:
    import logging

    from elke27_lib.outbound_loop import OutboundItem, OutboundPriority, OutboundQueue

    loop = asyncio.get_running_loop()
    failed: list[BaseException] = []

    def _send(_b: bytes) -> None:
        return None

    q = OutboundQueue(loop=loop, send_fn=_send, logger=logging.getLogger("t"))
    q.start()
    q.enqueue(
        OutboundItem(
            payload=b"x",
            seq=1,
            kind="k",
            priority=OutboundPriority.NORMAL,
            enqueued_at=0.0,
            on_sent=lambda _t: (_ for _ in ()).throw(RuntimeError("cb")),
            on_fail=lambda e: failed.append(e),
        )
    )
    await asyncio.sleep(0)
    await q.wait_idle(timeout_s=0.5)
    q.stop()
    assert failed and isinstance(failed[0], RuntimeError)
