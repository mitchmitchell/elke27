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
from elke27_lib.types import ArmMode, EventType

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


def test_pending_loop_uses_timed_lock_acquire_helper() -> None:
    pending_text = (_REPO_ROOT / "src" / "elke27_lib" / "pending_loop.py").read_text(
        encoding="utf-8"
    )
    assert "_lock.acquire(timeout=" in pending_text
    assert pending_text.count("self._acquire_lock()") >= 5


def test_public_event_and_arm_str_enum_contract() -> None:
    """StrEnum: ``str(member)`` is the wire/value string (not ``Class.name``)."""
    assert EventType.READY.value == "ready"
    assert str(EventType.READY) == "ready"
    assert ArmMode.DISARMED.value == "disarmed"
    assert str(ArmMode.DISARMED) == "disarmed"


def test_pending_response_manager_routes_lock_through_acquire_helper() -> None:
    src = inspect.getsource(PendingResponseManager)
    for name in ("create", "drop", "pending_count", "fail_all", "_pop"):
        assert f"def {name}(" in src


@pytest.mark.parametrize(
    ("obj", "method"),
    [
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

    joins: list[tuple[str, str, float | None]] = []
    real_join = threading.Thread.join

    def _tracked_join(self: threading.Thread, timeout: float | None = None) -> None:  # type: ignore[override]
        joins.append((threading.current_thread().name, self.name, timeout))
        return real_join(self, timeout)

    monkeypatch.setattr(threading.Thread, "join", _tracked_join)

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
    done1 = asyncio.Event()
    done2 = asyncio.Event()
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

    try:

        def _close1() -> None:
            try:
                sess.close()
            finally:
                loop.call_soon_threadsafe(done1.set)

        def _close2() -> None:
            try:
                sess.close()
            finally:
                loop.call_soon_threadsafe(done2.set)

        t0 = time.monotonic()
        loop.call_soon_threadsafe(_close1)
        await asyncio.wait_for(done1.wait(), timeout=2.0)
        first_elapsed = time.monotonic() - t0
        assert first_elapsed < 0.2

        t1 = time.monotonic()
        loop.call_soon_threadsafe(_close2)
        await asyncio.wait_for(done2.wait(), timeout=2.0)
        second_elapsed = time.monotonic() - t1
        assert second_elapsed < 0.2

        recv_joins = [j for j in joins if j[1] == "e27-recv"]
        assert recv_joins
        assert all(j[0] == "e27-recv-join" and j[2] == 1.0 for j in recv_joins)

        main_joins_recv = [j for j in joins if j[0] == "MainThread" and j[1] == "e27-recv"]
        main_joins_helper = [j for j in joins if j[0] == "MainThread" and j[1] == "e27-recv-join"]
        assert main_joins_recv == []
        assert main_joins_helper == []
    finally:
        await asyncio.to_thread(sess.close)


@pytest.mark.asyncio
async def test_stale_recv_join_helper_does_not_clear_new_receiver_after_reconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import elke27_lib.session_thread as session_mod

    joins: list[tuple[str, str, float | None]] = []
    real_join = threading.Thread.join

    def _tracked_join(self: threading.Thread, timeout: float | None = None) -> None:  # type: ignore[override]
        joins.append((threading.current_thread().name, self.name, timeout))
        return real_join(self, timeout)

    monkeypatch.setattr(threading.Thread, "join", _tracked_join)

    old_start = threading.Thread.start
    recv_objs: list[threading.Thread] = []
    join_helpers: list[threading.Thread] = []

    def _track_start(self: threading.Thread) -> None:  # type: ignore[override]
        if self.name == "e27-recv":
            recv_objs.append(self)
        elif self.name == "e27-recv-join":
            join_helpers.append(self)
        return old_start(self)

    monkeypatch.setattr(threading.Thread, "start", _track_start)

    r2_in_recv = threading.Event()

    class _DummyRecvLock:
        def __enter__(self) -> _DummyRecvLock:
            return self

        def __exit__(self, *_a: object) -> bool:
            return False

    _real_lock = threading.Lock
    _recv_lock_is_dummy = [True]

    def _lock_factory() -> Any:
        if _recv_lock_is_dummy[0]:
            _recv_lock_is_dummy[0] = False
            return _DummyRecvLock()
        return _real_lock()

    monkeypatch.setattr(threading, "Lock", _lock_factory)

    _sock_instances: list[Any] = []

    class _SlowSock:
        def __init__(self) -> None:
            self._sock_idx = len(_sock_instances)
            _sock_instances.append(self)
            self.closed = False

        def settimeout(self, _t: float) -> None:
            return None

        def connect(self, _a: object) -> None:
            return None

        def close(self) -> None:
            if self._sock_idx == 0 and not r2_in_recv.is_set():
                return
            self.closed = True

        def recv(self, _n: int) -> bytes:
            if len(_sock_instances) >= 2 and self._sock_idx >= 1:
                r2_in_recv.set()
                _sock_instances[0].closed = True
            while not self.closed:
                if self._sock_idx == 0 and len(_sock_instances) >= 2 and not r2_in_recv.is_set():
                    r2_in_recv.wait(timeout=0.05)
                    continue
                time.sleep(0.05)
            return b""

    loop = asyncio.get_running_loop()
    done1 = asyncio.Event()
    done2 = asyncio.Event()
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
    assert len(recv_objs) == 1
    r1 = recv_objs[0]

    try:

        def _close1() -> None:
            try:
                sess.close()
            finally:
                loop.call_soon_threadsafe(done1.set)

        def _close2() -> None:
            try:
                sess.close()
            finally:
                loop.call_soon_threadsafe(done2.set)

        loop.call_soon_threadsafe(_close1)
        await asyncio.wait_for(done1.wait(), timeout=2.0)
        loop.call_soon_threadsafe(_close2)
        await asyncio.wait_for(done2.wait(), timeout=2.0)
        await asyncio.to_thread(sess.reconnect)
        assert len(_sock_instances) == 2, f"expected 2 fake sockets, got {len(_sock_instances)}"
        assert len(recv_objs) == 2
        r2 = recv_objs[1]
        assert sess.state == session_mod.SessionState.ACTIVE
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            alive_tracked = [t for t in recv_objs if t.is_alive()]
            if len(alive_tracked) == 1 and alive_tracked[0] is r2 and not r1.is_alive():
                break
            await asyncio.sleep(0.05)
        else:
            alive_tracked = [t for t in recv_objs if t.is_alive()]
            raise AssertionError(
                f"expected exactly r2 live among tracked recv threads, got {alive_tracked!r} "
                f"r1_alive={r1.is_alive()}"
            )
        helper_deadline = time.monotonic() + 5.0
        while time.monotonic() < helper_deadline:
            if not join_helpers:
                await asyncio.sleep(0.01)
                continue
            if all(not h.is_alive() for h in join_helpers):
                break
            await asyncio.sleep(0.05)
        else:
            still = [h for h in join_helpers if h.is_alive()]
            raise AssertionError(f"e27-recv-join helper(s) still alive: {still!r}")
        assert join_helpers, "expected at least one e27-recv-join from the two loop closes"

        await asyncio.to_thread(sess.start_auto_receive)
        assert len(recv_objs) == 2
        assert recv_objs[1].is_alive()
        assert not recv_objs[0].is_alive()

        helper_joins_recv = [j for j in joins if j[0] == "e27-recv-join" and j[1] == "e27-recv"]
        any_joins_recv = [j for j in joins if j[1] == "e27-recv"]
        assert len(helper_joins_recv) == len(any_joins_recv)
        main_bad = [
            j for j in joins if j[0] == "MainThread" and j[1] in ("e27-recv", "e27-recv-join")
        ]
        assert main_bad == []
    finally:
        r2_in_recv.set()
        for _sock in _sock_instances:
            _sock.closed = True
        await asyncio.to_thread(sess.close)


@pytest.mark.asyncio
async def test_close_twice_then_reconnect_starts_receiver_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import elke27_lib.session_thread as session_mod

    recv_starts: list[int] = []
    real_start = threading.Thread.start

    def _track_start(self: threading.Thread) -> None:  # type: ignore[override]
        if self.name == "e27-recv":
            recv_starts.append(1)
        return real_start(self)

    monkeypatch.setattr(threading.Thread, "start", _track_start)

    class _Sock:
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
    monkeypatch.setattr(session_mod.socket, "socket", lambda *_a, **_k: _Sock())
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
    assert len(recv_starts) == 1

    try:

        def _close_twice() -> None:
            sess.close()
            sess.close()

        await asyncio.to_thread(_close_twice)
        await asyncio.to_thread(sess.reconnect)
        assert len(recv_starts) == 2
    finally:
        await asyncio.to_thread(sess.close)


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
    kernel = E27Kernel()
    client = Elke27Client(kernel=kernel)
    client.state.panel.session_id = 1
    fut: concurrent.futures.Future[dict[str, object]] = concurrent.futures.Future()

    def _req(*_a: object, **_k: object) -> int:
        def _fill() -> None:
            time.sleep(0.05)
            fut.set_result({"success": True, "error_code": 0})

        threading.Thread(target=_fill, daemon=True).start()
        return 7

    monkeypatch.setattr(kernel, "request", _req)
    r = await asyncio.to_thread(
        client.request,
        ("control", "authenticate"),
        pin=1234,
        opaque=fut,
    )
    assert r.ok is True


@pytest.mark.asyncio
async def test_sync_authenticate_rejected_on_kernel_event_loop_thread() -> None:
    kernel = E27Kernel()
    client = Elke27Client(kernel=kernel)
    loop = asyncio.get_running_loop()
    client.bind_kernel_loop_thread_for_tests(loop)
    with mock.patch.object(kernel, "request", return_value=1):
        result = client.request(("control", "authenticate"), pin=1234)
    assert result.ok is False
    err = result.error
    assert err is not None
    assert "event-loop thread" in str(err)


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
