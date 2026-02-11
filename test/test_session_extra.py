from __future__ import annotations

import asyncio
import logging
import threading
from types import SimpleNamespace

import pytest

from elke27_lib import session as session_mod
from elke27_lib.errors import E27Error
from elke27_lib.framing import DeframeState
from elke27_lib.session import (
    Session,
    SessionConfig,
    SessionIOError,
    SessionNotReadyError,
    SessionProtocolError,
    SessionState,
)


def _identity() -> session_mod.linking.E27Identity:
    return session_mod.linking.E27Identity("mn", "sn", "fw", "hw", "os")


class _FakeSocket:
    def __init__(
        self, *, recv_data: bytes | None = None, recv_exc: Exception | None = None
    ) -> None:
        self._recv_data = recv_data
        self._recv_exc = recv_exc
        self.timeout: float | None = None
        self.connected = False
        self.closed = False
        self.sent: list[bytes] = []

    def settimeout(self, value: float) -> None:
        self.timeout = value

    def connect(self, _addr) -> None:
        self.connected = True

    def recv(self, _max_bytes: int) -> bytes:
        if self._recv_exc is not None:
            raise self._recv_exc
        if self._recv_data is None:
            return b""
        data = self._recv_data
        self._recv_data = b""
        return data

    def sendall(self, data: bytes) -> None:
        self.sent.append(data)

    def close(self) -> None:
        self.closed = True


def _ready_session() -> Session:
    cfg = SessionConfig(host="example", auto_receive=False)
    sess = Session(cfg, client_identity=_identity(), link_key_hex="00")
    sess.state = SessionState.ACTIVE
    sess.sock = _FakeSocket()
    sess._deframe_state = DeframeState()
    sess.info = session_mod.SessionInfo(
        session_id=1, session_key_hex="00" * 16, session_hmac_hex="11" * 16
    )
    return sess


def test_connect_closes_when_already_active(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = SessionConfig(host="example", auto_receive=False)
    sess = Session(cfg, client_identity=_identity(), link_key_hex="00")
    sess.state = SessionState.ACTIVE
    closed: dict[str, int] = {"count": 0}

    def _close() -> None:
        closed["count"] += 1

    monkeypatch.setattr(sess, "close", _close)

    fake_socket = _FakeSocket()
    monkeypatch.setattr(session_mod.socket, "socket", lambda *_a, **_k: fake_socket)
    monkeypatch.setattr(
        session_mod,
        "perform_hello",
        lambda **_k: SimpleNamespace(session_id=1, session_key_hex="00", hmac_key_hex="11"),
    )

    sess.connect()
    assert closed["count"] == 1


def test_connect_socket_error(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = SessionConfig(host="bad", auto_receive=False)
    sess = Session(cfg, client_identity=_identity(), link_key_hex="00")

    class _Sock(_FakeSocket):
        def connect(self, _addr) -> None:  # type: ignore[override]
            raise OSError("boom")

    monkeypatch.setattr(session_mod.socket, "socket", lambda *_a, **_k: _Sock())

    with pytest.raises(SessionIOError):
        sess.connect()


def test_connect_hello_error(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = SessionConfig(host="example", auto_receive=False)
    sess = Session(cfg, client_identity=_identity(), link_key_hex="00")
    fake_socket = _FakeSocket()
    monkeypatch.setattr(session_mod.socket, "socket", lambda *_a, **_k: fake_socket)

    class _HelloErr(E27Error):
        pass

    monkeypatch.setattr(
        session_mod, "perform_hello", lambda **_k: (_ for _ in ()).throw(_HelloErr("no"))
    )

    with pytest.raises(SessionProtocolError):
        sess.connect()


def test_connect_starts_receiver_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = SessionConfig(host="example", auto_receive=True)
    sess = Session(cfg, client_identity=_identity(), link_key_hex="00")
    fake_socket = _FakeSocket()
    monkeypatch.setattr(session_mod.socket, "socket", lambda *_a, **_k: fake_socket)
    monkeypatch.setattr(
        session_mod,
        "perform_hello",
        lambda **_k: SimpleNamespace(session_id=1, session_key_hex="00", hmac_key_hex="11"),
    )
    started: dict[str, int] = {"count": 0}
    monkeypatch.setattr(
        sess, "_start_receiver", lambda: started.__setitem__("count", started["count"] + 1)
    )
    sess.on_message = lambda _msg: None
    sess.connect()
    assert started["count"] == 1


def test_close_stops_outbound_queue() -> None:
    sess = _ready_session()
    called: dict[str, int] = {"count": 0}

    class _Outbound:
        def stop(self, fail_exc: Exception) -> None:  # type: ignore[no-untyped-def]
            assert isinstance(fail_exc, SessionIOError)
            called["count"] += 1

    sess._outbound = _Outbound()  # type: ignore[assignment]
    sess.close()
    assert called["count"] == 1


def test_require_ready_raises() -> None:
    cfg = SessionConfig(host="example", auto_receive=False)
    sess = Session(cfg, client_identity=_identity(), link_key_hex="00")
    with pytest.raises(SessionNotReadyError):
        sess._require_ready()


def test_recv_some_errors_and_empty() -> None:
    sess = _ready_session()
    sess.sock = _FakeSocket(recv_exc=TimeoutError("wait"))
    with pytest.raises(TimeoutError):
        sess._recv_some(max_bytes=1)

    sess.sock = _FakeSocket(recv_exc=OSError("oops"))
    with pytest.raises(SessionIOError):
        sess._recv_some(max_bytes=1)

    sess.sock = _FakeSocket(recv_data=b"")
    with pytest.raises(SessionIOError):
        sess._recv_some(max_bytes=1)

    sess.sock = _FakeSocket(recv_data=b"abc")
    assert sess._recv_some(max_bytes=3) == b"abc"


def test_send_all_error() -> None:
    sess = _ready_session()

    class _Sock(_FakeSocket):
        def sendall(self, data: bytes) -> None:  # type: ignore[override]
            raise OSError("nope")

    sess.sock = _Sock()
    with pytest.raises(SessionIOError):
        sess._send_all(b"x")


def test_recv_one_frame_no_crc_with_idle_and_wire_log(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    sess = _ready_session()
    sess.cfg = SessionConfig(host="example", wire_log=True, auto_receive=False)
    sess._deframe_state = DeframeState()
    idle: dict[str, int] = {"count": 0}
    sess.on_idle = lambda: idle.__setitem__("count", idle["count"] + 1)

    chunks = [TimeoutError("wait"), b"chunk1", b"chunk2", b"chunk3"]

    def _recv_some(*_a, **_k):  # type: ignore[no-untyped-def]
        val = chunks.pop(0)
        if isinstance(val, Exception):
            raise val
        return val

    class _Res:
        def __init__(self, ok: bool, frame_no_crc: bytes | None, error: str | None = None) -> None:
            self.ok = ok
            self.frame_no_crc = frame_no_crc
            self.error = error

    def _deframe_feed(_state, chunk):  # type: ignore[no-untyped-def]
        if chunk == b"chunk1":
            return [_Res(False, None, "bad crc")]
        if chunk == b"chunk2":
            return [_Res(True, None, None)]
        return [_Res(True, b"\x80\x00\x00", None)]

    monkeypatch.setattr(sess, "_recv_some", _recv_some)
    monkeypatch.setattr(session_mod, "deframe_feed", _deframe_feed)
    caplog.set_level(logging.DEBUG, logger="elke27_lib.session")

    frame = sess._recv_one_frame_no_crc(timeout_s=0.1)
    assert frame == b"\x80\x00\x00"
    assert idle["count"] == 1
    assert "Dropping invalid frame while resyncing" in caplog.text


def test_recv_one_frame_timeout() -> None:
    sess = _ready_session()
    sess._recv_one_frame_no_crc  # keep lint quiet
    with pytest.raises(TimeoutError):
        sess._recv_one_frame_no_crc(timeout_s=0.0)


def test_send_json_with_outbound_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    sess = _ready_session()

    class _Outbound:
        def __init__(self) -> None:
            self.items = []

        def enqueue(self, item):  # type: ignore[no-untyped-def]
            self.items.append(item)

    outbound = _Outbound()
    sess._outbound = outbound  # type: ignore[assignment]
    monkeypatch.setattr(sess, "_encode_json", lambda _obj: b"data")
    sess.send_json({"seq": 4})
    assert outbound.items


def test_send_json_direct_calls_on_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    sess = _ready_session()
    monkeypatch.setattr(sess, "_encode_json", lambda _obj: b"data")
    sent: dict[str, int] = {"count": 0}
    sess.send_json({"seq": 1}, on_sent=lambda _ts: sent.__setitem__("count", sent["count"] + 1))
    assert sent["count"] == 1


def test_enable_outbound_queue_starts(monkeypatch: pytest.MonkeyPatch) -> None:
    sess = _ready_session()
    started: dict[str, int] = {"count": 0}

    class _Outbound:
        def __init__(self, **_k):  # type: ignore[no-untyped-def]
            pass

        def start(self) -> None:
            started["count"] += 1

    monkeypatch.setattr(session_mod, "OutboundQueue", _Outbound)
    sess.enable_outbound_queue(loop=asyncio.new_event_loop(), min_interval_s=0.1, max_burst=1)
    assert started["count"] == 1


def test_encode_json_wire_log(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    sess = _ready_session()
    sess.cfg = SessionConfig(host="example", wire_log=True, auto_receive=False)

    monkeypatch.setattr(
        session_mod,
        "encrypt_schema0_envelope",
        lambda **_k: (0x80, b"cipher"),
    )
    monkeypatch.setattr(session_mod, "frame_build", lambda **_k: b"frame")
    caplog.set_level(logging.DEBUG, logger="elke27_lib.session")
    framed = sess._encode_json({"seq": 1})
    assert framed == b"frame"
    assert "TX framed" in caplog.text


def test_recv_json_error_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    sess = _ready_session()

    sess._recv_one_frame_no_crc = lambda **_k: b"\x80"  # type: ignore[assignment]
    with pytest.raises(SessionProtocolError):
        sess.recv_json(timeout_s=0.1)

    sess._recv_one_frame_no_crc = lambda **_k: b"\x80\x00\x00"  # type: ignore[assignment]
    monkeypatch.setattr(
        session_mod,
        "decrypt_schema0_envelope",
        lambda **_k: (_ for _ in ()).throw(ValueError("nope")),
    )
    with pytest.raises(SessionProtocolError):
        sess.recv_json(timeout_s=0.1)

    env = SimpleNamespace(seq=1, payload=b"{bad")
    monkeypatch.setattr(session_mod, "decrypt_schema0_envelope", lambda **_k: env)
    with pytest.raises(SessionProtocolError):
        sess.recv_json(timeout_s=0.1)

    env2 = SimpleNamespace(seq=2, payload=b"123")
    monkeypatch.setattr(session_mod, "decrypt_schema0_envelope", lambda **_k: env2)
    with pytest.raises(SessionProtocolError):
        sess.recv_json(timeout_s=0.1)


def test_recv_json_updates_tracking(monkeypatch: pytest.MonkeyPatch) -> None:
    sess = _ready_session()
    idle: dict[str, int] = {"count": 0}
    sess.on_idle = lambda: idle.__setitem__("count", idle["count"] + 1)
    sess._recv_one_frame_no_crc = lambda **_k: b"\x80\x00\x00"  # type: ignore[assignment]
    env = SimpleNamespace(seq=5, payload=b'{"seq": 9, "zone": {}}')
    monkeypatch.setattr(session_mod, "decrypt_schema0_envelope", lambda **_k: env)
    obj = sess.recv_json(timeout_s=0.0)
    assert obj["seq"] == 9
    assert sess._last_rx_envelope_seq == 5
    assert sess._last_rx_json_seq == 9
    assert idle["count"] == 1


def test_pump_once_handles_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    sess = _ready_session()
    called: dict[str, int] = {"count": 0}
    sess.on_idle = lambda: called.__setitem__("count", called["count"] + 1)

    sess.recv_json = lambda **_k: (_ for _ in ()).throw(TimeoutError())  # type: ignore[assignment]
    assert sess.pump_once(timeout_s=0.01) is None
    assert called["count"] == 1

    handled: dict[str, int] = {"count": 0}
    monkeypatch.setattr(
        sess, "_handle_disconnect", lambda _e: handled.__setitem__("count", handled["count"] + 1)
    )
    sess.recv_json = lambda **_k: (_ for _ in ()).throw(SessionIOError("x"))  # type: ignore[assignment]
    with pytest.raises(SessionIOError):
        sess.pump_once(timeout_s=0.01)
    assert handled["count"] == 1

    sess.recv_json = lambda **_k: (_ for _ in ()).throw(RuntimeError("x"))  # type: ignore[assignment]
    with pytest.raises(RuntimeError):
        sess.pump_once(timeout_s=0.01)
    assert handled["count"] == 2

    sess.recv_json = lambda **_k: (_ for _ in ()).throw(SessionNotReadyError())  # type: ignore[assignment]
    with pytest.raises(SessionNotReadyError):
        sess.pump_once(timeout_s=0.01)


def test_start_and_stop_receiver(monkeypatch: pytest.MonkeyPatch) -> None:
    sess = _ready_session()
    sess.on_message = lambda _msg: None

    async def _dummy_thread(*_a, **_k):  # type: ignore[no-untyped-def]
        return None

    class _Loop:
        def create_task(self, coro):  # type: ignore[no-untyped-def]
            assert asyncio.iscoroutine(coro)
            coro.close()
            return "task"

    monkeypatch.setattr(session_mod.asyncio, "get_running_loop", lambda: _Loop())
    monkeypatch.setattr(session_mod.asyncio, "to_thread", lambda *_a, **_k: _dummy_thread())

    sess._start_receiver()
    assert sess._recv_task == "task"

    sess._recv_task = "task"  # type: ignore[assignment]
    sess._stop_receiver()
    assert sess._recv_task is None

    class _Thread:
        def __init__(self) -> None:
            self.joined = False

        def join(self, timeout: float) -> None:  # type: ignore[no-untyped-def]
            self.joined = True

    sess._recv_stop = threading.Event()
    thread = _Thread()
    sess._recv_thread = thread  # type: ignore[assignment]
    sess._stop_receiver()
    assert thread.joined is True


def test_start_receiver_thread_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = SessionConfig(host="example", auto_receive=True, auto_receive_thread_fallback=True)
    sess = Session(cfg, client_identity=_identity(), link_key_hex="00")
    sess.state = SessionState.ACTIVE
    sess.on_message = lambda _msg: None

    monkeypatch.setattr(
        session_mod.asyncio, "get_running_loop", lambda: (_ for _ in ()).throw(RuntimeError())
    )
    started: dict[str, int] = {"count": 0}

    class _Thread:
        def __init__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            pass

        def start(self) -> None:
            started["count"] += 1

    monkeypatch.setattr(session_mod.threading, "Thread", _Thread)
    sess._start_receiver()
    assert started["count"] == 1


def test_start_receiver_no_loop_no_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = SessionConfig(host="example", auto_receive=True, auto_receive_thread_fallback=False)
    sess = Session(cfg, client_identity=_identity(), link_key_hex="00")
    sess.state = SessionState.ACTIVE
    sess.on_message = lambda _msg: None
    monkeypatch.setattr(
        session_mod.asyncio, "get_running_loop", lambda: (_ for _ in ()).throw(RuntimeError())
    )
    sess._start_receiver()
    assert sess._recv_thread is None


def test_start_receiver_noop_when_running() -> None:
    sess = _ready_session()
    sess._recv_thread = threading.Thread()
    sess._start_receiver()
    assert sess._recv_thread is not None


def test_start_auto_receive_conditions(monkeypatch: pytest.MonkeyPatch) -> None:
    sess = _ready_session()
    sess.on_message = None
    sess.start_auto_receive()

    sess.on_message = lambda _msg: None
    sess.state = SessionState.DISCONNECTED
    sess.start_auto_receive()

    called: dict[str, int] = {"count": 0}
    monkeypatch.setattr(
        sess, "_start_receiver", lambda: called.__setitem__("count", called["count"] + 1)
    )
    sess.cfg = SessionConfig(host="example", auto_receive=True)
    sess.state = SessionState.ACTIVE
    sess.start_auto_receive()
    assert called["count"] == 1


def test_recv_loop_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    sess = _ready_session()
    event = threading.Event()
    sess.on_idle = lambda: event.set()
    sess.on_message = lambda _msg: None
    sess.recv_json = lambda **_k: (_ for _ in ()).throw(TimeoutError())  # type: ignore[assignment]
    sess._recv_loop(event)

    event = threading.Event()
    sess.recv_json = lambda **_k: (_ for _ in ()).throw(SessionNotReadyError())  # type: ignore[assignment]
    sess._recv_loop(event)

    event = threading.Event()
    handled: dict[str, int] = {"count": 0}
    monkeypatch.setattr(
        sess, "_handle_disconnect", lambda _e: handled.__setitem__("count", handled["count"] + 1)
    )
    sess.recv_json = lambda **_k: (_ for _ in ()).throw(SessionIOError("x"))  # type: ignore[assignment]
    sess._recv_loop(event)
    assert handled["count"] >= 1

    event = threading.Event()
    sess.recv_json = lambda **_k: (_ for _ in ()).throw(RuntimeError("x"))  # type: ignore[assignment]
    sess._recv_loop(event)
    assert handled["count"] >= 2

    event = threading.Event()
    sess.recv_json = lambda **_k: {"seq": 1}  # type: ignore[assignment]
    sess.on_message = lambda _msg: event.set()
    sess._recv_loop(event)
    assert event.is_set() is True

    class _Event:
        def __init__(self) -> None:
            self._set = False
            self.wait_called = False

        def is_set(self) -> bool:
            return self._set

        def wait(self, _timeout: float) -> None:
            self.wait_called = True
            self._set = True

    sess.state = SessionState.DISCONNECTED
    evt = _Event()
    sess._recv_loop(evt)  # type: ignore[arg-type]
    assert evt.wait_called is True


def test_handle_disconnect_records(monkeypatch: pytest.MonkeyPatch) -> None:
    sess = _ready_session()
    called: dict[str, int] = {"count": 0}
    sess.on_disconnected = lambda _e: called.__setitem__("count", called["count"] + 1)
    monkeypatch.setattr(sess, "close", lambda: None)
    sess._handle_disconnect(RuntimeError("x"))
    assert called["count"] == 1


def test_handle_disconnect_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    sess = _ready_session()
    called: dict[str, int] = {"count": 0}
    monkeypatch.setattr(
        sess, "_handle_disconnect", lambda _e: called.__setitem__("count", called["count"] + 1)
    )
    sess.handle_disconnect(RuntimeError("x"))
    assert called["count"] == 1


def test_wrap_seq_edges() -> None:
    sess = _ready_session()
    assert sess._wrap_seq(0, wrap_to=1) == 1
    assert sess._wrap_seq(2_147_483_648, wrap_to=1) == 1


def test_extract_domain_key() -> None:
    sess = _ready_session()
    assert sess._extract_domain_key({"seq": 1, "session_id": 2}) is None
    assert sess._extract_domain_key({"seq": 1, "zone": {}}) == "zone"


def test_reconnect_calls_close_and_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    sess = _ready_session()
    called: dict[str, int] = {"close": 0, "connect": 0}
    monkeypatch.setattr(sess, "close", lambda: called.__setitem__("close", called["close"] + 1))
    monkeypatch.setattr(sess, "connect", lambda: "ok")
    assert sess.reconnect() == "ok"
    assert called["close"] == 1
