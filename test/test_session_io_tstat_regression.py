"""Regression tests for #8: SessionIOError during thermostat-style traffic.

Uses faked transports only (no kernel.connect / client.async_connect).
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Callable
from typing import Any, cast

import pytest

from elke27_lib import session as session_mod
from elke27_lib.framing import DeframeState
from elke27_lib.kernel import E27Kernel
from elke27_lib.outbound import OutboundItem, OutboundPriority, OutboundQueue
from elke27_lib.session import (
    Session,
    SessionConfig,
    SessionIOError,
    SessionState,
)


def _identity() -> session_mod.linking.E27Identity:
    return session_mod.linking.E27Identity("mn", "sn", "fw", "hw", "os")


class _SendTrackingSocket:
    """Tracks concurrent send() calls (outbound queue must serialize via _send_lock)."""

    def __init__(self) -> None:
        self._send_active = 0
        self._send_overlap = 0
        self._guard = threading.Lock()
        self.sent: list[bytes] = []

    def settimeout(self, _value: float) -> None:
        return None

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


class _DualFailureSocket:
    """recv returns EOF after the socket is closed during deliberate teardown."""

    def __init__(self) -> None:
        self.closed = False
        self.timeout: float | None = None
        self._recv_blocked = threading.Event()

    def settimeout(self, value: float) -> None:
        self.timeout = value

    def recv(self, _max_bytes: int) -> bytes:
        self._recv_blocked.set()
        if self.closed:
            return b""
        raise TimeoutError("wait")

    def close(self) -> None:
        self.closed = True


def _ready_session(*, sock: object) -> Session:
    cfg = SessionConfig(host="panel", auto_receive=False)
    sess = Session(cfg, client_identity=_identity(), link_key_hex="00")
    sess.state = SessionState.ACTIVE
    cast(Any, sess).sock = sock
    sess._deframe_state = DeframeState()
    sess.info = session_mod.SessionInfo(
        session_id=1, session_key_hex="00" * 16, session_hmac_hex="11" * 16
    )
    return sess


@pytest.mark.asyncio
async def test_outbound_sends_are_serialized_by_send_lock() -> None:
    sock = _SendTrackingSocket()
    sess = _ready_session(sock=sock)
    loop = asyncio.get_running_loop()
    queue = OutboundQueue(
        loop=loop,
        send_fn=sess._send_all,
        min_interval_s=0.0,
        max_burst=4,
    )
    queue.start()
    for i in range(8):
        queue.enqueue(
            OutboundItem(
                payload=bytes([i]),
                seq=i,
                kind="request",
                priority=OutboundPriority.NORMAL,
                enqueued_at=time.monotonic(),
            )
        )
    await asyncio.sleep(0.01)
    await asyncio.wait_for(queue.wait_idle(), timeout=3.0)
    await asyncio.sleep(0.05)
    assert sock._send_overlap == 0
    assert len(sock.sent) == 8


def test_real_recv_thread_emits_single_disconnect_on_teardown() -> None:
    sock = _DualFailureSocket()
    cfg = SessionConfig(host="panel", auto_receive=True, auto_receive_thread_fallback=True)
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
    sess._start_receiver()
    assert sock._recv_blocked.wait(timeout=2.0)

    sess.handle_disconnect(SessionIOError("deliberate teardown"))
    deadline = time.monotonic() + 2.0
    while len(disconnects) < 1 and time.monotonic() < deadline:
        time.sleep(0.02)

    assert len(disconnects) == 1
    assert isinstance(disconnects[0], SessionIOError)
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
