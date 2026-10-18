"""Security round 1 (D2-D7) regression tests. Dummy values only."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import queue
from typing import Any, cast

import pytest

from elke27_lib import linking
from elke27_lib.client import MAX_PAGED_BLOCK_COUNT, Elke27Client, Result
from elke27_lib.discovery import AIOELKDiscovery, E27System, async_discover_host
from elke27_lib.errors import E27Error, ProtocolError
from elke27_lib.events import ConnectionStateChanged
from elke27_lib.framing import DeframeState, frame_build
from elke27_lib.hello import SessionKeys
from elke27_lib.kernel import DEFAULT_EVENT_QUEUE_MAXLEN, E27Kernel
from elke27_lib.linking import E27LinkKeys
from elke27_lib.presentation import encrypt_schema0_envelope
from elke27_lib.provisioning import Credentials
from elke27_lib.session import Session, SessionConfig, SessionInfo, SessionState
from elke27_lib.types import ClientConfig, LinkKeys
from test.helpers.internal import get_kernel, get_private

DUMMY_A = "DUMMYSECRETAAAA1111"
DUMMY_B = "DUMMYSECRETBBBB2222"
DUMMY_C = "DUMMYSECRETCCCC3333"
DUMMY_PIN = 424242


# ---------------------------------------------------------------- D2


@pytest.mark.parametrize(
    "obj",
    [
        LinkKeys(tempkey_hex=DUMMY_A, linkkey_hex=DUMMY_B, linkhmac_hex=DUMMY_C),
        E27LinkKeys(tempkey_hex=DUMMY_A, linkkey_hex=DUMMY_B, linkhmac_hex=DUMMY_C),
        SessionKeys(session_id=7, session_key_hex=DUMMY_B, hmac_key_hex=DUMMY_C),
        SessionInfo(session_id=7, session_key_hex=DUMMY_B, session_hmac_hex=DUMMY_C),
        Credentials(access_code=DUMMY_A, pass_phrase=DUMMY_B),
    ],
    ids=["LinkKeys", "E27LinkKeys", "SessionKeys", "SessionInfo", "Credentials"],
)
def test_secret_types_hide_secrets_in_repr(obj: object) -> None:
    for text in (repr(obj), str(obj)):
        for dummy in (DUMMY_A, DUMMY_B, DUMMY_C):
            assert dummy not in text


def test_link_keys_to_json_unchanged() -> None:
    keys = LinkKeys(tempkey_hex=DUMMY_A, linkkey_hex=DUMMY_B, linkhmac_hex=DUMMY_C)
    assert keys.to_json() == {
        "tempkey_hex": DUMMY_A,
        "linkkey_hex": DUMMY_B,
        "linkhmac_hex": DUMMY_C,
    }


@pytest.mark.asyncio
async def test_link_credentials_hidden_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    """The client's internal _Credentials passed to the kernel hides both fields."""
    client = Elke27Client()
    kernel = get_kernel(client)
    seen: list[str] = []

    async def fake_link(panel: object, identity: object, creds: object, **_k: object) -> Any:
        seen.append(repr(creds))
        return E27LinkKeys(tempkey_hex=DUMMY_C, linkkey_hex=DUMMY_C, linkhmac_hex=DUMMY_C)

    monkeypatch.setattr(kernel, "link", fake_link)
    identity = linking.E27Identity(mn="1", sn="2", fwver="0", hwver="0", osver="0")
    with contextlib.suppress(Exception):  # only the creds repr matters here
        await client.async_link(
            "198.51.100.1",
            2101,
            access_code=DUMMY_A,
            passphrase=DUMMY_B,
            client_identity=identity,
        )
    assert seen
    assert DUMMY_A not in seen[0] and DUMMY_B not in seen[0]


# ---------------------------------------------------------------- D3


def test_inbound_debug_log_redacts_pin_and_user_pin_not_stored(
    caplog: pytest.LogCaptureFixture,
) -> None:
    kernel = E27Kernel()
    kernel.load_features_blocking()
    caplog.set_level(logging.DEBUG)
    on_message = get_private(kernel, "_on_message")
    on_message({"user": {"get_attribs": {"user_id": 1, "name": "U1", "pin": DUMMY_PIN}}})
    assert str(DUMMY_PIN) not in caplog.text
    assert "Inbound message" in caplog.text
    user = kernel.state.users[1]
    assert user.pin is None
    assert user.has_pin is True


def test_inbound_log_not_built_without_debug(monkeypatch: pytest.MonkeyPatch) -> None:
    import elke27_lib.kernel as kernel_mod

    calls: list[object] = []
    monkeypatch.setattr(kernel_mod, "redact_for_diagnostics", lambda m: calls.append(m) or m)
    kernel = E27Kernel(logger=logging.getLogger("elke27.test.nodebug"))
    logging.getLogger("elke27.test.nodebug").setLevel(logging.INFO)
    get_private(kernel, "_on_message")({"user": {"get_attribs": {"user_id": 1, "pin": 1}}})
    assert calls == []


# ---------------------------------------------------------------- D4


def _conn_event(connected: bool, reason: str | None = None) -> ConnectionStateChanged:
    return ConnectionStateChanged(
        kind=ConnectionStateChanged.KIND,
        at=0.0,
        seq=None,
        classification="LOCAL",
        route=("__local__", ConnectionStateChanged.KIND),
        session_id=1,
        connected=connected,
        reason=reason,
    )


class _AuthStub:
    """Stands in for the client's one authenticate round trip."""

    def __init__(self, client: Elke27Client) -> None:
        self.client = client
        self.pins: list[int] = []
        self.outcome: str = "ok"  # ok | refused | no_reply | raise

    async def __call__(self, *, pin: int, timeout_s: float | None) -> Result[Any]:
        del timeout_s
        self.pins.append(pin)
        if self.outcome == "ok":
            cast(Any, self.client)._last_auth_error_code = None
            return Result.success({})
        if self.outcome == "refused":
            cast(Any, self.client)._last_auth_error_code = 11008
            return Result.failure(E27Error("control_authenticate failed with error_code=11008"))
        if self.outcome == "raise":
            raise RuntimeError("boom")
        await asyncio.sleep(10)  # no reply
        raise AssertionError("unreachable")


def _client(*, reauth: bool = False) -> tuple[Elke27Client, list[int | None], _AuthStub]:
    kernel = E27Kernel(request_timeout_s=0.05)
    client = Elke27Client(ClientConfig(reauth_on_reconnect=reauth), kernel=kernel)
    sent: list[int | None] = []

    def fake_refresh(*, auth_pin: int | None = None, domains: object = None) -> None:
        del domains
        sent.append(auth_pin)

    cast(Any, kernel).request_csm_refresh = fake_refresh
    cast(Any, client)._safe_request = lambda *_a, **_k: None
    stub = _AuthStub(client)
    cast(Any, client)._async_authenticate = stub
    return client, sent, stub


def _authenticate(client: Elke27Client, *, success: bool) -> None:
    kernel = get_kernel(client)
    cast(Any, kernel).request = lambda *_a, **_k: 5
    q: queue.Queue[dict[str, object]] = queue.Queue(maxsize=1)
    q.put({"success": success, "error_code": 0 if success else 2})
    cast(Any, client)._request_authenticate(("control", "authenticate"), opaque=q, pin=DUMMY_PIN)


async def _drop_and_reconnect(client: Elke27Client) -> None:
    """Link loss, then a reconnect after the 600 s window (the re-auth path)."""
    times = iter([0.0, 1000.0])
    cast(Any, client)._now_monotonic = lambda: next(times, 1000.0)
    client._handle_kernel_event(_conn_event(False, reason="io_error"))  # pyright: ignore[reportPrivateUsage]
    client._handle_kernel_event(_conn_event(True))  # pyright: ignore[reportPrivateUsage]
    tasks = list(cast(Any, client)._reauth_tasks)
    if tasks:
        await asyncio.gather(*tasks)


def _reauth_warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if r.levelno == logging.WARNING and "Re-authentication" in r.getMessage()
    ]


@pytest.mark.asyncio
async def test_failed_auth_is_not_cached_or_resent() -> None:
    client, sent, stub = _client(reauth=True)
    _authenticate(client, success=False)
    assert get_private(client, "_last_auth_pin") is None
    assert client.authenticated is False
    await _drop_and_reconnect(client)
    assert stub.pins == []
    assert sent == [None]


@pytest.mark.asyncio
async def test_disconnect_clears_cached_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _, _ = _client(reauth=True)
    _authenticate(client, success=True)
    assert get_private(client, "_last_auth_pin") == DUMMY_PIN
    assert client.authenticated is True

    async def fake_close() -> None:
        return None

    monkeypatch.setattr(get_kernel(client), "close", fake_close)
    await client.async_disconnect()
    assert get_private(client, "_last_auth_pin") is None


@pytest.mark.asyncio
async def test_default_reconnect_sends_no_authenticate() -> None:
    client, sent, stub = _client()
    _authenticate(client, success=True)
    await _drop_and_reconnect(client)
    assert stub.pins == []
    assert sent == [None]
    assert get_private(client, "_last_auth_pin") is None
    assert client.authenticated is False


@pytest.mark.asyncio
async def test_opt_in_reconnect_resends_pin_exactly_once_per_acceptance() -> None:
    client, sent, stub = _client(reauth=True)
    _authenticate(client, success=True)
    await _drop_and_reconnect(client)
    assert stub.pins == [DUMMY_PIN]
    assert client.authenticated is True
    assert sent == [None]  # the CSM refresh never carries the PIN


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        ("refused", "Re-authentication after reconnect refused (error_code=11008); not resending"),
        (
            "no_reply",
            "Re-authentication after reconnect got no reply or an error; "
            "treated as refused; not resending",
        ),
        ("raise", "Re-authentication after reconnect failed (RuntimeError); not resending"),
    ],
)
async def test_opt_in_reauth_refused_or_unanswered_is_final(
    outcome: str, expected: str, caplog: pytest.LogCaptureFixture
) -> None:
    client, _, stub = _client(reauth=True)
    _authenticate(client, success=True)
    cast(Any, client).set_authenticated_role("master")
    stub.outcome = outcome
    caplog.set_level(logging.DEBUG)
    await _drop_and_reconnect(client)
    assert stub.pins == [DUMMY_PIN]
    assert _reauth_warnings(caplog) == [expected]
    assert str(DUMMY_PIN) not in caplog.text
    assert client.authenticated is False
    assert get_private(client, "_auth_role") is None
    assert get_private(client, "_last_auth_pin") is None
    # Never re-sent: a later reconnect sends nothing.
    await _drop_and_reconnect(client)
    assert stub.pins == [DUMMY_PIN]
    assert len(_reauth_warnings(caplog)) == 1


@pytest.mark.asyncio
async def test_deliberate_close_event_clears_pin_even_with_opt_in() -> None:
    client, _, _ = _client(reauth=True)
    _authenticate(client, success=True)
    client._handle_kernel_event(_conn_event(False, reason="closed"))  # pyright: ignore[reportPrivateUsage]
    assert get_private(client, "_last_auth_pin") is None
    assert client.authenticated is False


def test_session_change_clears_pin_for_refresh_csm() -> None:
    client, _, _ = _client()
    kernel = get_kernel(client)
    kernel.state.panel.session_id = 1
    _authenticate(client, success=True)
    assert cast(Any, client)._session_auth_pin() == DUMMY_PIN
    kernel.state.panel.session_id = 2
    assert cast(Any, client)._session_auth_pin() is None
    assert get_private(client, "_last_auth_pin") is None


# ---------------------------------------------------------------- D5


def _discovery_reply(ipv4: str, *, port: object = 2101) -> bytes:
    return json.dumps(
        {
            "ELKWC2017": "dummy",
            "MAC_ADDR": "aa:bb:cc:dd:ee:ff",
            "IPV4_ADDR": ipv4,
            "LISTEN_PORT": port,
            "ENCRYPTED_LISTEN_PORT": 2601,
            "NAME": "Dummy",
        }
    ).encode()


class _FakeTransport:
    def __init__(self, protocol: Any, replies: list[tuple[bytes, tuple[str, int]]]) -> None:
        self._protocol = protocol
        self._replies = replies

    def sendto(self, data: bytes, addr: object) -> None:
        del data, addr
        loop = asyncio.get_running_loop()
        for payload, src in self._replies:
            loop.call_soon(self._protocol.datagram_received, payload, src)

    def close(self) -> None:
        pass


def _patch_endpoint(
    monkeypatch: pytest.MonkeyPatch, replies: list[tuple[bytes, tuple[str, int]]]
) -> None:
    loop = asyncio.get_running_loop()

    async def fake_endpoint(factory: Any, **_k: Any) -> tuple[Any, Any]:
        protocol = factory()
        return _FakeTransport(protocol, replies), protocol

    monkeypatch.setattr(loop, "create_datagram_endpoint", fake_endpoint)


@pytest.mark.asyncio
async def test_unicast_discovery_ignores_other_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_endpoint(monkeypatch, [(_discovery_reply("203.0.113.5"), ("198.51.100.9", 2362))])
    result = await async_discover_host(
        "198.51.100.1", timeout=0.2, socket_factory=lambda: cast(Any, object())
    )
    assert result is None


@pytest.mark.asyncio
async def test_unicast_discovery_returns_queried_address(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_endpoint(monkeypatch, [(_discovery_reply("203.0.113.5"), ("198.51.100.1", 2362))])
    result = await async_discover_host(
        "198.51.100.1", timeout=0.2, socket_factory=lambda: cast(Any, object())
    )
    assert result is not None
    assert result.host == "198.51.100.1"


@pytest.mark.parametrize("port", [99999999, 0, -1, 65536, "x", True])
def test_discovery_rejects_out_of_range_port(
    port: object, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    found: dict[tuple[str, int], E27System] = {}
    scanner = AIOELKDiscovery()
    stop = scanner._process_response(  # pyright: ignore[reportPrivateUsage]
        _discovery_reply("198.51.100.1", port=port), ("198.51.100.1", 2362), None, found
    )
    assert stop is False
    assert found == {}
    assert "aa:bb:cc:dd:ee:ff" not in caplog.text.split("<=")[-1]


def test_broadcast_discovery_flags_address_mismatch() -> None:
    found: dict[tuple[str, int], E27System] = {}
    scanner = AIOELKDiscovery()
    scanner._process_response(  # pyright: ignore[reportPrivateUsage]
        _discovery_reply("203.0.113.5"), ("198.51.100.9", 2362), None, found
    )
    scanner._process_response(  # pyright: ignore[reportPrivateUsage]
        _discovery_reply("198.51.100.7"), ("198.51.100.7", 2362), None, found
    )
    by_source = {s.source_host: s for s in found.values()}
    assert by_source["198.51.100.9"].address_mismatch is True
    assert by_source["198.51.100.7"].address_mismatch is False


# ---------------------------------------------------------------- D6


_KEY = bytes(range(16))


def _frame(envelope_seq: int) -> bytes:
    payload = json.dumps({"seq": 0, "area": {"get_status": {"area_id": 1}}}).encode()
    proto, ct = encrypt_schema0_envelope(
        payload=payload, session_key=_KEY, envelope_seq=envelope_seq
    )
    return frame_build(protocol_byte=proto, data_frame=ct)


class _FrameSocket:
    def __init__(self, frames: list[bytes]) -> None:
        self.frames = frames

    def recv(self, _n: int) -> bytes:
        if self.frames:
            return self.frames.pop(0)
        raise TimeoutError


def _session(frames: list[bytes]) -> Session:
    s = Session(
        SessionConfig(host="198.51.100.1"),
        client_identity=linking.E27Identity("1", "2", "0", "0", "0"),
        link_key_hex="00" * 16,
    )
    cast(Any, s).sock = _FrameSocket(frames)
    cast(Any, s)._deframe_state = DeframeState()
    s.info = SessionInfo(1, _KEY.hex(), "00" * 32)
    s.state = SessionState.ACTIVE
    return s


def _warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.levelno == logging.WARNING and "seq" in r.getMessage()]


def test_replayed_frame_warns_once_and_is_kept(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    frame = _frame(7)
    s = _session([frame, frame, frame])
    first = s.recv_json(timeout_s=1)
    assert get_private(s, "_last_rx_envelope_seq") == 7
    assert _warnings(caplog) == []
    second = s.recv_json(timeout_s=1)
    third = s.recv_json(timeout_s=1)
    assert first == second == third  # warn-only: never dropped
    warns = _warnings(caplog)
    assert len(warns) == 1
    assert warns[0].getMessage() == (
        "Inbound envelope seq did not increase (last=7 got=7); frame kept"
    )
    assert get_private(s, "_rx_seq_regressions") == 2


def test_rx_seq_tracker_resets_for_new_session(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    s = _session([_frame(9)])
    s.recv_json(timeout_s=1)
    assert get_private(s, "_last_rx_envelope_seq") == 9
    cast(Any, s)._reset_rx_envelope_seq()  # what connect() does after HELLO
    assert get_private(s, "_last_rx_envelope_seq") is None
    cast(Any, s).sock = _FrameSocket([_frame(1)])
    s.recv_json(timeout_s=1)
    assert _warnings(caplog) == []
    assert get_private(s, "_last_rx_envelope_seq") == 1


# ---------------------------------------------------------------- D7


class _ChunkSocket:
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks

    def settimeout(self, _t: float | None) -> None:
        pass

    def recv(self, _n: int) -> bytes:
        if self.chunks:
            return self.chunks.pop(0)
        raise TimeoutError


def test_discovery_nonce_split_across_chunks() -> None:
    raw = b'{"ELKWC2017":"dummy","nonce":"DUMMYNONCE"}'
    sock = _ChunkSocket([raw[:15], raw[15:]])
    assert linking.wait_for_discovery_nonce(cast(Any, sock), timeout_s=1.0) == "DUMMYNONCE"


def test_discovery_invalid_json_is_an_error_not_need_more_data() -> None:
    from elke27_lib.errors import E27ProtocolError

    sock = _ChunkSocket([b'{"ELKWC2017":"dummy","nonce":}'])
    with pytest.raises(E27ProtocolError):
        linking.wait_for_discovery_nonce(cast(Any, sock), timeout_s=1.0)


def test_discovery_non_object_reply_ignored() -> None:
    found: dict[tuple[str, int], E27System] = {}
    stop = AIOELKDiscovery()._process_response(  # pyright: ignore[reportPrivateUsage]
        b'["ELKWC2017"]', ("198.51.100.1", 2362), None, found
    )
    assert stop is False and found == {}


def test_discovery_buffer_capped_for_large_nonceless_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import time

    sizes: list[int] = []
    real_parse = linking.parse_discovery_hello_and_local

    def spy(data: bytes) -> tuple[str | None, str | None]:
        sizes.append(len(data))
        return real_parse(data)

    monkeypatch.setattr(linking, "parse_discovery_hello_and_local", spy)
    obj = b'{"filler":"' + b"x" * 50 + b'"}'
    stream = b'{"ELKWC2017":"dummy"}' + obj * (1_000_000 // len(obj))
    chunks = [stream[i : i + 4096] for i in range(0, len(stream), 4096)]
    timeout_s = 1.0
    start = time.monotonic()
    with pytest.raises(Exception):  # noqa: B017 - times out without a nonce
        linking.wait_for_discovery_nonce(cast(Any, _ChunkSocket(chunks)), timeout_s=timeout_s)
    assert time.monotonic() - start <= timeout_s + 2
    assert sizes
    assert max(sizes) <= linking.DISCOVERY_BUFFER_MAX


@pytest.mark.asyncio
async def test_paged_block_count_over_cap_is_protocol_error() -> None:
    from test.test_e27_async_execute_paged import _FakeSession, _set_session

    client = Elke27Client()
    kernel = get_kernel(client)
    fake_session = _FakeSession()
    _set_session(kernel, fake_session)
    kernel.state.panel.session_id = 1

    task = asyncio.create_task(client.async_execute("zone_get_configured"))
    await asyncio.sleep(0)
    seq1 = fake_session.sent[0]["seq"]
    get_private(kernel, "_on_message")(
        {
            "seq": seq1,
            "zone": {"get_configured": {"block_id": 1, "block_count": 10_000, "zones": [1]}},
        }
    )
    result = await asyncio.wait_for(task, timeout=1.0)
    assert result.ok is False
    assert isinstance(result.error, ProtocolError)
    assert str(MAX_PAGED_BLOCK_COUNT) in str(result.error)
    assert len(fake_session.sent) == 1


def test_event_deque_default_bound_and_drop_counter(caplog: pytest.LogCaptureFixture) -> None:
    assert DEFAULT_EVENT_QUEUE_MAXLEN == 4096
    assert get_private(E27Kernel(), "_events").maxlen == 4096
    assert get_private(E27Kernel(event_queue_maxlen=0), "_events").maxlen is None
    assert get_private(E27Kernel(event_queue_maxlen=3), "_events").maxlen == 3

    kernel = E27Kernel(event_queue_maxlen=2)
    ctx = cast(
        Any,
        type(
            "Ctx",
            (),
            {"seq": None, "classification": "LOCAL", "route": ("a", "b"), "session_id": 1},
        )(),
    )
    caplog.set_level(logging.DEBUG)
    for _ in range(5):
        kernel.emit(_conn_event(True), ctx)
    assert len(get_private(kernel, "_events")) == 2
    assert kernel.events_dropped == 3
    full = [r for r in caplog.records if "Event queue full" in r.getMessage()]
    assert len(full) == 1 and full[0].levelno == logging.DEBUG
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_default_event_queue_full_with_subscriber_logs_no_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A subscriber-only client (as in Home Assistant) fills the default deque quietly."""
    kernel = E27Kernel()
    delivered: list[object] = []
    kernel.subscribe(delivered.append)
    ctx = cast(
        Any,
        type(
            "Ctx",
            (),
            {"seq": None, "classification": "LOCAL", "route": ("a", "b"), "session_id": 1},
        )(),
    )
    caplog.set_level(logging.DEBUG)
    for _ in range(DEFAULT_EVENT_QUEUE_MAXLEN + 4):
        kernel.emit(_conn_event(True), ctx)
    assert len(delivered) == DEFAULT_EVENT_QUEUE_MAXLEN + 4
    assert kernel.events_dropped == 4
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
