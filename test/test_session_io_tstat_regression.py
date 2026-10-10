"""Regression tests for #8: SessionIOError during thermostat-style traffic.

Uses faked transports only (no kernel.connect / client.async_connect).
"""

from __future__ import annotations

import asyncio
import logging
import socket
import threading
import time
from collections.abc import Callable
from typing import Any, cast

import pytest

from elke27_lib import session as session_mod
from elke27_lib.framing import DeframeState
from elke27_lib.kernel import E27Kernel
from elke27_lib.session import (
    Session,
    SessionConfig,
    SessionIOError,
    SessionState,
)


def _identity() -> session_mod.linking.E27Identity:
    return session_mod.linking.E27Identity("mn", "sn", "fw", "hw", "os")


class _NoOpLock:
    def __enter__(self) -> _NoOpLock:
        return self

    def __exit__(self, *_args: object) -> bool:
        return False


class _SendTrackingSocket:
    """Tracks concurrent send() calls (outbound queue must serialize via _send_lock)."""

    def __init__(self) -> None:
        self._send_active = 0
        self._send_overlap = 0
        self._guard = threading.Lock()
        self.sent: list[bytes] = []

    def send(self, data: bytes) -> int:
        with self._guard:
            if self._send_active:
                self._send_overlap += 1
            self._send_active += 1
        try:
            time.sleep(0.02)
            self.sent.append(bytes(data))
            return len(data)
        finally:
            with self._guard:
                self._send_active -= 1

    def close(self) -> None:
        return None


class _PartialSendSocket:
    def __init__(self, *, chunk_size: int) -> None:
        self._chunk_size = chunk_size
        self.sent: list[bytes] = []

    def send(self, data: bytes) -> int:
        n = min(self._chunk_size, len(data))
        self.sent.append(bytes(data[:n]))
        return n

    def close(self) -> None:
        return None


class _TimeoutUntilDeadlineSocket:
    def __init__(self) -> None:
        self.send_calls = 0

    def send(self, _data: bytes) -> int:
        self.send_calls += 1
        raise TimeoutError("would block")

    def close(self) -> None:
        return None


class _BlockingCloseOSErrorSocket:
    """recv blocks until close, then raises OSError like a dead fd."""

    def __init__(self) -> None:
        self._recv_blocked = threading.Event()
        self._closed = False
        self._wake = threading.Event()

    def settimeout(self, _value: float) -> None:
        return None

    def recv(self, _max_bytes: int) -> bytes:
        self._recv_blocked.set()
        while not self._closed:
            self._wake.wait(0.05)
        raise OSError(9, "Bad file descriptor")

    def close(self) -> None:
        self._closed = True
        self._wake.set()


def _ready_session(
    *,
    sock: object,
    io_write_timeout_s: float = 5.0,
) -> Session:
    cfg = SessionConfig(
        host="panel",
        auto_receive=False,
        io_write_timeout_s=io_write_timeout_s,
    )
    sess = Session(cfg, client_identity=_identity(), link_key_hex="00")
    sess.state = SessionState.ACTIVE
    cast(Any, sess).sock = sock
    sess._deframe_state = DeframeState()
    sess.info = session_mod.SessionInfo(
        session_id=1, session_key_hex="00" * 16, session_hmac_hex="11" * 16
    )
    return sess


def _session_with_real_recv(
    sock: _BlockingCloseOSErrorSocket, *, use_thread_fallback: bool
) -> Session:
    cfg = SessionConfig(
        host="panel",
        auto_receive=True,
        auto_receive_thread_fallback=use_thread_fallback,
        io_timeout_s=0.05,
    )
    sess = Session(cfg, client_identity=_identity(), link_key_hex="00")
    sess.state = SessionState.ACTIVE
    cast(Any, sess).sock = sock
    sess._deframe_state = DeframeState()
    sess.info = session_mod.SessionInfo(
        session_id=1, session_key_hex="00" * 16, session_hmac_hex="11" * 16
    )
    sess.on_message = lambda _msg: None
    return sess


def _parallel_send_all(sess: Session, *, workers: int = 8) -> None:
    threads = [
        threading.Thread(target=sess._send_all, args=(bytes([i]) * 8,), name=f"send-{i}")
        for i in range(workers)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=3.0)


def test_parallel_send_all_is_serialized_by_send_lock() -> None:
    sock = _SendTrackingSocket()
    sess = _ready_session(sock=sock)
    _parallel_send_all(sess)
    assert sock._send_overlap == 0
    assert len(sock.sent) == 8


def test_parallel_send_all_overlaps_without_send_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    sock = _SendTrackingSocket()
    sess = _ready_session(sock=sock)
    monkeypatch.setattr(sess, "_send_lock", _NoOpLock())
    _parallel_send_all(sess)
    assert sock._send_overlap > 0


def test_send_all_logs_partial_send_and_completes(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sock = _PartialSendSocket(chunk_size=2)
    sess = _ready_session(sock=sock)
    payload = b"abcdef"
    with caplog.at_level(logging.DEBUG, logger="elke27_lib.session"):
        sess._send_all(payload)
    assert b"".join(sock.sent) == payload
    assert any("Partial socket send" in r.getMessage() for r in caplog.records)


def test_send_all_write_deadline_raises_session_io_error() -> None:
    sock = _TimeoutUntilDeadlineSocket()
    sess = _ready_session(sock=sock, io_write_timeout_s=0.08)
    with pytest.raises(SessionIOError, match="timed out"):
        sess._send_all(b"payload")
    assert sock.send_calls >= 1


def _fill_socket_send_buffer(sock: socket.socket) -> None:
    was_blocking = sock.getblocking()
    sock.setblocking(False)
    try:
        chunk = b"x" * 65536
        while True:
            try:
                sock.send(chunk)
            except BlockingIOError:
                break
    finally:
        sock.setblocking(was_blocking)


def test_real_socket_send_uses_write_deadline_not_socket_read_timeout() -> None:
    """Blocking send must not wait out io_timeout_s when the buffer is full."""
    send_sock, _recv_sock = socket.socketpair()
    try:
        send_sock.settimeout(30.0)
        _fill_socket_send_buffer(send_sock)
        write_deadline_s = 0.12
        cfg = SessionConfig(
            host="panel",
            io_timeout_s=30.0,
            io_write_timeout_s=write_deadline_s,
            auto_receive=False,
        )
        sess = Session(cfg, client_identity=_identity(), link_key_hex="00")
        sess.state = SessionState.ACTIVE
        cast(Any, sess).sock = send_sock
        sess._deframe_state = DeframeState()
        sess.info = session_mod.SessionInfo(
            session_id=1, session_key_hex="00" * 16, session_hmac_hex="11" * 16
        )
        started = time.monotonic()
        with pytest.raises(SessionIOError, match="timed out"):
            sess._send_all(b"overflow" * 4096)
        elapsed = time.monotonic() - started
        assert elapsed < 2.0
        assert elapsed >= write_deadline_s * 0.5
    finally:
        send_sock.close()
        _recv_sock.close()


def test_session_config_positional_preserves_hello_timeout() -> None:
    cfg = SessionConfig("panel", 2101, 4.0, 0.25, 6.5)
    assert cfg.connect_timeout_s == 4.0
    assert cfg.io_timeout_s == 0.25
    assert cfg.hello_timeout_s == 6.5
    assert cfg.io_write_timeout_s == 5.0


def _run_single_disconnect_scenario(
    sock: _BlockingCloseOSErrorSocket,
    *,
    use_thread_fallback: bool,
    begin_teardown: Callable[[Session], None],
) -> list[Exception | None]:
    sess = _session_with_real_recv(sock, use_thread_fallback=use_thread_fallback)
    disconnects: list[Exception | None] = []
    sess.on_disconnected = lambda err: disconnects.append(err)
    sess._start_receiver()
    assert sock._recv_blocked.wait(timeout=2.0)
    begin_teardown(sess)
    deadline = time.monotonic() + 2.0
    while len(disconnects) < 1 and time.monotonic() < deadline:
        time.sleep(0.02)
    time.sleep(0.5)
    sess._stop_receiver()
    return disconnects


def test_real_recv_thread_emits_single_disconnect_on_teardown() -> None:
    sock = _BlockingCloseOSErrorSocket()

    def _begin(sess: Session) -> None:
        sess.handle_disconnect(SessionIOError("deliberate teardown"))

    disconnects = _run_single_disconnect_scenario(
        sock, use_thread_fallback=True, begin_teardown=_begin
    )
    assert len(disconnects) == 1
    assert isinstance(disconnects[0], SessionIOError)


def test_disconnect_gate_blocks_second_callback() -> None:
    class _Sock:
        def close(self) -> None:
            return None

    sess = _ready_session(sock=_Sock())
    disconnects: list[Exception | None] = []
    sess.on_disconnected = lambda err: disconnects.append(err)
    err_a = SessionIOError("first")
    err_b = SessionIOError("second")
    sess._handle_disconnect(err_a)
    sess._handle_disconnect(err_b)
    assert len(disconnects) == 1
    assert disconnects[0] is err_a


def test_without_disconnect_gate_double_callback(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Sock:
        def close(self) -> None:
            return None

    sess = _ready_session(sock=_Sock())

    def _always_begin(_self: Session) -> bool:
        return True

    monkeypatch.setattr(Session, "_try_begin_disconnect_teardown", _always_begin)
    disconnects: list[Exception | None] = []
    sess.on_disconnected = lambda err: disconnects.append(err)
    sess._handle_disconnect(SessionIOError("first"))
    sess._handle_disconnect(SessionIOError("second"))
    assert len(disconnects) == 2


@pytest.mark.asyncio
async def test_single_disconnect_with_asyncio_recv_and_daemon_join() -> None:
    sock = _BlockingCloseOSErrorSocket()
    cfg = SessionConfig(
        host="panel",
        auto_receive=True,
        auto_receive_thread_fallback=False,
        io_timeout_s=0.05,
    )
    sess = Session(cfg, client_identity=_identity(), link_key_hex="00")
    sess.state = SessionState.ACTIVE
    cast(Any, sess).sock = sock
    sess._deframe_state = DeframeState()
    sess.info = session_mod.SessionInfo(
        session_id=1, session_key_hex="00" * 16, session_hmac_hex="11" * 16
    )
    disconnects: list[Exception | None] = []
    sess.on_disconnected = lambda err: disconnects.append(err)
    sess.on_message = lambda _msg: None
    try:
        sess._start_receiver()
        deadline = time.monotonic() + 3.0
        while not sock._recv_blocked.is_set() and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        assert sock._recv_blocked.is_set()

        await asyncio.to_thread(sess.handle_disconnect, SessionIOError("deliberate teardown"))
        deadline = time.monotonic() + 2.0
        while len(disconnects) < 1 and time.monotonic() < deadline:
            await asyncio.sleep(0.02)
        await asyncio.sleep(0.5)
        assert len(disconnects) == 1
    finally:
        sess._stop_receiver()


@pytest.mark.asyncio
async def test_kernel_send_io_error_tears_down_session() -> None:
    kernel = E27Kernel()
    kernel._loop = asyncio.get_running_loop()
    kernel.state.panel.session_id = 9

    disconnected: list[Exception | None] = []

    class _Session:
        state = SessionState.ACTIVE

        def handle_disconnect(self, err: Exception) -> None:
            disconnected.append(err)
            self.state = SessionState.DISCONNECTED

        def send_json(
            self,
            _msg: dict[str, object],
            *,
            priority: object,
            on_sent: Callable[[float], None] | None,
            on_fail: Callable[[BaseException], None] | None,
        ) -> None:
            del priority, on_sent
            assert on_fail is not None
            on_fail(
                SessionIOError(
                    "Socket write failed to panel:2101: [Errno 104] Connection reset by peer"
                )
            )

    cast(Any, kernel)._session = _Session()
    kernel.requests.register(("tstat", "get_status"), lambda **_k: {"tstat_id": 1})
    kernel.request(("tstat", "get_status"), tstat_id=1)
    await asyncio.sleep(0.05)
    assert len(disconnected) == 1
    assert isinstance(disconnected[0], SessionIOError)
    assert "Connection reset" in str(disconnected[0])


@pytest.mark.asyncio
async def test_send_io_error_disconnects_before_second_queued_send() -> None:
    """SessionIOError teardown must run before _complete_active kicks the scheduler."""
    kernel = E27Kernel()
    kernel._loop = asyncio.get_running_loop()
    kernel.state.panel.session_id = 9
    kernel.requests.register(("tstat", "get_status"), lambda **_k: {"tstat_id": 1})

    loop = asyncio.get_running_loop()

    class _Session:
        def __init__(self) -> None:
            self.state = SessionState.ACTIVE
            self.send_count = 0

        def handle_disconnect(self, _err: Exception) -> None:
            self.state = SessionState.DISCONNECTED

        def send_json(
            self,
            _msg: dict[str, object],
            *,
            priority: object,
            on_sent: Callable[[float], None] | None,
            on_fail: Callable[[BaseException], None] | None,
        ) -> None:
            del priority, on_sent
            self.send_count += 1
            assert on_fail is not None
            err = SessionIOError("Socket write failed to panel:2101: [Errno 32] Broken pipe")
            loop.call_soon(on_fail, err)

    sess = _Session()
    cast(Any, kernel)._session = sess
    kernel.request(("tstat", "get_status"), tstat_id=1)
    kernel.request(("tstat", "get_status"), tstat_id=2)
    await asyncio.sleep(0.05)
    assert sess.send_count == 1
    assert sess.state is SessionState.DISCONNECTED


def test_disconnect_log_includes_exception_message(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class _Sock:
        def close(self) -> None:
            return None

    sess = _ready_session(sock=_Sock())
    exc = SessionIOError("Connection closed by the panel (panel:2101).")
    with caplog.at_level(logging.INFO, logger="elke27_lib.session"):
        sess._handle_disconnect(exc)
    recs = [r for r in caplog.records if "Session disconnect" in r.getMessage()]
    assert len(recs) == 1
    msg = recs[0].getMessage()
    assert "err_msg=Connection closed by the panel" in msg
    assert "last_tx_domain" in msg


@pytest.mark.asyncio
async def test_tstat_get_status_send_io_error_while_polling() -> None:
    """A tstat get_status on a dead socket must disconnect via the kernel send path."""
    kernel = E27Kernel()
    kernel._loop = asyncio.get_running_loop()
    kernel.state.panel.session_id = 3
    kernel.requests.register(("tstat", "get_status"), lambda **_k: {"tstat_id": 2})

    class _Session:
        def __init__(self) -> None:
            self.state = SessionState.ACTIVE
            self.disconnected: list[Exception] = []

        def send_json(
            self,
            msg: dict[str, object],
            *,
            priority: object,
            on_sent: Callable[[float], None] | None,
            on_fail: Callable[[BaseException], None] | None,
        ) -> None:
            del priority, on_sent, msg
            assert on_fail is not None
            on_fail(SessionIOError("Socket write failed to panel:2101: [Errno 32] Broken pipe"))

        def handle_disconnect(self, err: Exception) -> None:
            self.disconnected.append(err)
            self.state = SessionState.DISCONNECTED

    fake = _Session()
    cast(Any, kernel)._session = fake
    kernel.request(("tstat", "get_status"), tstat_id=2)
    await asyncio.sleep(0.05)
    assert len(fake.disconnected) == 1
