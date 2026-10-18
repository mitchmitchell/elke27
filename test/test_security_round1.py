"""Security round 1 (D2-D8) regression tests. Dummy values only.

The tests go through the public API (``async_connect``, ``async_execute``,
``async_disconnect``, discovery scans, ``Session.connect``/``recv_json``) with
only the transport faked, and assert on public state, the wire and the logs.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import Callable
from typing import Any, cast

import pytest

import elke27_lib.kernel as kernel_mod
from elke27_lib import linking
from elke27_lib import session as session_mod
from elke27_lib.client import MAX_PAGED_BLOCK_COUNT, Elke27Client
from elke27_lib.discovery import AIOELKDiscovery, async_discover_host
from elke27_lib.errors import E27ProtocolError, E27ProvisioningTimeout, ProtocolError
from elke27_lib.events import ConnectionStateChanged
from elke27_lib.framing import frame_build
from elke27_lib.hello import SessionKeys
from elke27_lib.kernel import DEFAULT_EVENT_QUEUE_MAXLEN, E27Kernel
from elke27_lib.linking import E27LinkKeys
from elke27_lib.presentation import encrypt_schema0_envelope
from elke27_lib.provisioning import Credentials
from elke27_lib.session import Session, SessionConfig, SessionInfo
from elke27_lib.types import ClientConfig, LinkKeys

DUMMY_A = "DUMMYSECRETAAAA1111"
DUMMY_B = "DUMMYSECRETBBBB2222"
DUMMY_C = "DUMMYSECRETCCCC3333"
DUMMY_PIN = 424242
HOST = "198.51.100.1"
KEYS = LinkKeys("aa", "bb", "cc")


# ---------------------------------------------------------------- fake transport


class _FakePanel:
    """The panel behind a fake transport: records the wire and answers requests.

    Only ``session.Session`` is replaced; the kernel, dispatch and client are real.
    """

    def __init__(self) -> None:
        self.sessions: list[_FakeSession] = []
        # accept | refuse | silent | hold
        self.auth: str = "accept"
        self.held: list[tuple[_FakeSession, dict[str, Any]]] = []
        # (domain, name) -> reply builder; overrides the default empty ack.
        self.overrides: dict[tuple[str, str], Callable[[dict[str, Any]], dict[str, Any]]] = {}

    @property
    def session(self) -> _FakeSession:
        return self.sessions[-1]

    def wire(self) -> list[dict[str, Any]]:
        return [m for s in self.sessions for m in s.sent]

    def auth_requests(self, session: _FakeSession | None = None) -> list[dict[str, Any]]:
        sent = (session or self.session).sent
        return [m for m in sent if "authenticate" in m]

    def drop_link(self) -> None:
        self.session.on_disconnected(session_mod.SessionIOError("link dropped"))

    def release_held(self) -> None:
        for session, reply in self.held:
            session.on_message(reply)
        self.held.clear()

    def reply(self, session: _FakeSession, msg: dict[str, Any]) -> None:
        loop = asyncio.get_running_loop()
        seq = msg["seq"]
        if "authenticate" in msg:
            if self.auth == "silent":
                return
            code = 11008 if self.auth == "refuse" else 0
            reply = {"seq": seq, "authenticate": {"error_code": code}}
            if self.auth == "hold":
                self.held.append((session, reply))
                return
            loop.call_soon(session.on_message, reply)
            return
        domain = next(k for k in msg if k not in ("seq", "session_id"))
        name = next(iter(msg[domain]))
        build = self.overrides.get((domain, name))
        if build is not None:
            reply = build(msg)
        elif name == "get_configured":
            body = {"block_id": 1, "block_count": 1, "error_code": 0}
            reply = {"seq": seq, domain: {name: body}}
        else:
            reply = {"seq": seq, domain: {name: {"error_code": 0}}}
        loop.call_soon(session.on_message, reply)


class _FakeSession:
    def __init__(self, panel: _FakePanel) -> None:
        self.panel = panel
        self.state = session_mod.SessionState.ACTIVE
        self.info = SessionInfo(
            session_id=11 + len(panel.sessions), session_key_hex="00", session_hmac_hex="11"
        )
        self.wire_log_suppress_seqs: object = None
        self.on_message: Any = None
        self.on_disconnected: Any = None
        self.on_idle: Any = None
        self.sent: list[dict[str, Any]] = []
        panel.sessions.append(self)

    def connect(self) -> SessionInfo:
        return self.info

    def enable_outbound_queue(self, **_kwargs: object) -> None:
        return None

    def start_auto_receive(self) -> None:
        return None

    def send_json(
        self,
        msg: dict[str, Any],
        *,
        priority: object = None,
        on_sent: Callable[[float], None] | None = None,
        on_fail: Callable[[BaseException], None] | None = None,
    ) -> None:
        del priority, on_fail
        self.sent.append(msg)
        if on_sent is not None:
            on_sent(time.monotonic())
        self.panel.reply(self, msg)

    def close(self) -> None:
        self.state = session_mod.SessionState.DISCONNECTED


@pytest.fixture
def panel(monkeypatch: pytest.MonkeyPatch) -> _FakePanel:
    fake = _FakePanel()

    def _factory(*, cfg: object, client_identity: object, link_key_hex: str) -> _FakeSession:
        del cfg, client_identity, link_key_hex
        return _FakeSession(fake)

    monkeypatch.setattr(session_mod, "Session", _factory)
    return fake


class _Clock:
    """Monotonic clock with a settable outage jump."""

    def __init__(self) -> None:
        self.offset = 0.0

    def __call__(self) -> float:
        return time.monotonic() + self.offset


async def _until(cond: Callable[[], bool], timeout_s: float = 1.0) -> None:
    deadline = time.monotonic() + timeout_s
    while not cond():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.005)


async def _settle() -> None:
    await asyncio.sleep(0.05)


def _pin_messages(wire: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [m for m in wire if str(DUMMY_PIN) in json.dumps(m)]


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
    """The credentials the client hands to ``kernel.link`` hide both fields."""
    kernel = E27Kernel()
    client = Elke27Client(kernel=kernel)
    seen: list[str] = []

    async def fake_link(panel: object, identity: object, creds: object, **_k: object) -> Any:
        seen.append(repr(creds))
        return E27LinkKeys(tempkey_hex=DUMMY_C, linkkey_hex=DUMMY_C, linkhmac_hex=DUMMY_C)

    monkeypatch.setattr(kernel, "link", fake_link)
    identity = linking.E27Identity(mn="1", sn="2", fwver="0", hwver="0", osver="0")
    with contextlib.suppress(Exception):  # only the creds repr matters here
        await client.async_link(
            HOST,
            2101,
            access_code=DUMMY_A,
            passphrase=DUMMY_B,
            client_identity=identity,
        )
    assert seen
    assert DUMMY_A not in seen[0] and DUMMY_B not in seen[0]


# ---------------------------------------------------------------- D3


@pytest.mark.asyncio
async def test_inbound_debug_log_redacts_pin_and_user_pin_not_stored(
    panel: _FakePanel, caplog: pytest.LogCaptureFixture
) -> None:
    kernel = E27Kernel()
    client = Elke27Client(kernel=kernel)
    await client.async_connect(HOST, 2101, KEYS)
    caplog.set_level(logging.DEBUG)
    panel.session.on_message(
        {"user": {"get_attribs": {"user_id": 1, "name": "U1", "pin": DUMMY_PIN}}}
    )
    assert str(DUMMY_PIN) not in caplog.text
    assert "Inbound message" in caplog.text
    user = kernel.state.users[1]
    assert user.pin is None
    assert user.has_pin is True
    await client.async_disconnect()


@pytest.mark.asyncio
async def test_inbound_log_not_built_without_debug(
    panel: _FakePanel, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = logging.getLogger("elke27.test.nodebug")
    log.setLevel(logging.INFO)
    client = Elke27Client(logger=log)
    await client.async_connect(HOST, 2101, KEYS)
    calls: list[object] = []
    monkeypatch.setattr(kernel_mod, "redact_for_diagnostics", lambda m: calls.append(m) or m)
    panel.session.on_message({"user": {"get_attribs": {"user_id": 1, "pin": 1}}})
    assert calls == []
    await client.async_disconnect()


# ---------------------------------------------------------------- D4


async def _connected(
    *, reauth: bool = False, request_timeout_s: float = 5.0, kernel: E27Kernel | None = None
) -> tuple[Elke27Client, _Clock]:
    clock = _Clock()
    config = ClientConfig(reauth_on_reconnect=reauth, request_timeout_s=request_timeout_s)
    client = Elke27Client(config, kernel=kernel, now_monotonic=clock)
    await client.async_connect(HOST, 2101, KEYS)
    return client, clock


async def _authenticate(client: Elke27Client) -> bool:
    result = await client.async_execute("control_authenticate", pin=DUMMY_PIN)
    return result.ok


async def _drop_and_reconnect(
    client: Elke27Client, panel: _FakePanel, clock: _Clock, *, outage_s: float = 1000.0
) -> None:
    """Link loss, then a reconnect ``outage_s`` seconds later."""
    panel.drop_link()
    clock.offset += outage_s
    await client.async_connect(HOST, 2101, KEYS)


def _reauth_logs(caplog: pytest.LogCaptureFixture, level: int = logging.WARNING) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if r.levelno == level and "Re-authentication" in r.getMessage()
    ]


@pytest.mark.asyncio
async def test_failed_auth_is_not_cached_or_resent(panel: _FakePanel) -> None:
    client, clock = await _connected(reauth=True)
    panel.auth = "refuse"
    assert await _authenticate(client) is False
    assert client.authenticated is False
    panel.auth = "accept"
    await _drop_and_reconnect(client, panel, clock)
    await _settle()
    assert panel.auth_requests() == []
    assert len(_pin_messages(panel.wire())) == 1  # only the refused authenticate
    await client.async_disconnect()


@pytest.mark.asyncio
async def test_disconnect_clears_cached_pin(panel: _FakePanel) -> None:
    client, _ = await _connected(reauth=True)
    assert await _authenticate(client) is True
    assert client.authenticated is True
    await client.async_disconnect()
    assert client.authenticated is False
    # A new connect after a deliberate disconnect sends no authenticate.
    await client.async_connect(HOST, 2101, KEYS)
    await _settle()
    assert panel.auth_requests() == []
    await client.async_disconnect()


@pytest.mark.asyncio
async def test_default_reconnect_sends_no_authenticate(panel: _FakePanel) -> None:
    client, clock = await _connected()
    assert await _authenticate(client) is True
    await _drop_and_reconnect(client, panel, clock)
    await _settle()
    assert panel.auth_requests() == []
    assert len(_pin_messages(panel.wire())) == 1
    assert client.authenticated is False
    await client.async_disconnect()


@pytest.mark.asyncio
async def test_opt_in_reconnect_resends_pin_exactly_once_per_acceptance(
    panel: _FakePanel,
) -> None:
    client, clock = await _connected(reauth=True)
    assert await _authenticate(client) is True
    await _drop_and_reconnect(client, panel, clock)
    await _until(lambda: client.authenticated)
    assert panel.auth_requests() == [
        {
            "seq": panel.auth_requests()[0]["seq"],
            "session_id": 12,
            "authenticate": {"pin": DUMMY_PIN},
        }
    ]
    # Only the two authenticates carry the PIN: the CSM refresh never does.
    assert _pin_messages(panel.wire()) == [
        m for s in panel.sessions for m in panel.auth_requests(s)
    ]
    await client.async_disconnect()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        ("refuse", "Re-authentication after reconnect refused (error_code=11008); not resending"),
        (
            "silent",
            "Re-authentication after reconnect got no reply or an error; "
            "treated as refused; not resending",
        ),
    ],
)
async def test_opt_in_reauth_refused_or_unanswered_is_final(
    panel: _FakePanel, outcome: str, expected: str, caplog: pytest.LogCaptureFixture
) -> None:
    client, clock = await _connected(reauth=True, request_timeout_s=0.1)
    assert await _authenticate(client) is True
    panel.auth = outcome
    caplog.set_level(logging.DEBUG)
    await _drop_and_reconnect(client, panel, clock)
    await _until(lambda: bool(_reauth_logs(caplog)))
    assert len(panel.auth_requests()) == 1
    assert _reauth_logs(caplog) == [expected]
    assert str(DUMMY_PIN) not in caplog.text
    assert client.authenticated is False
    # Never re-sent: a later reconnect sends nothing.
    panel.auth = "accept"
    await _drop_and_reconnect(client, panel, clock)
    await _settle()
    assert panel.auth_requests() == []
    assert len(_reauth_logs(caplog)) == 1
    await client.async_disconnect()


class _Bug(Exception):
    """An unexpected (non-client) exception: a bug, not a refusal."""


@pytest.mark.asyncio
async def test_opt_in_reauth_unexpected_error_propagates_as_a_bug(
    panel: _FakePanel, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    kernel = E27Kernel()
    client, clock = await _connected(reauth=True, kernel=kernel)
    assert await _authenticate(client) is True
    real_send = kernel.send_request_with_seq

    def _send(seq: int, domain: str, name: str, *args: Any, **kwargs: Any) -> Any:
        if domain == "authenticate":
            raise _Bug("unexpected")
        return real_send(seq, domain, name, *args, **kwargs)

    monkeypatch.setattr(kernel, "send_request_with_seq", _send)
    caplog.set_level(logging.DEBUG)
    await _drop_and_reconnect(client, panel, clock)
    await _until(lambda: bool(_reauth_logs(caplog, logging.ERROR)))
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert [r.getMessage() for r in errors] == ["Re-authentication after reconnect raised"]
    assert errors[0].exc_info is not None and errors[0].exc_info[0] is _Bug
    assert _reauth_logs(caplog) == []  # not reported as a refusal
    assert client.authenticated is False
    assert str(DUMMY_PIN) not in caplog.text
    await client.async_disconnect()


@pytest.mark.asyncio
@pytest.mark.parametrize("outage_s", [1.0, 600.0, 601.0])
async def test_opt_in_reauth_fires_on_every_reconnect(panel: _FakePanel, outage_s: float) -> None:
    client, clock = await _connected(reauth=True)
    assert await _authenticate(client) is True
    await _drop_and_reconnect(client, panel, clock, outage_s=outage_s)
    await _until(lambda: client.authenticated)
    assert len(panel.auth_requests()) == 1
    # Whatever the outage (the 600 s window only decides the CSM refresh), the
    # PIN goes out in the two authenticates only.
    await _settle()
    assert len(_pin_messages(panel.wire())) == 2
    await client.async_disconnect()


@pytest.mark.asyncio
@pytest.mark.parametrize("how", ["async_disconnect", "close", "link_drop"])
async def test_inflight_reauth_never_restores_pin(
    panel: _FakePanel, how: str, caplog: pytest.LogCaptureFixture
) -> None:
    client, clock = await _connected(reauth=True)
    assert await _authenticate(client) is True
    panel.auth = "hold"
    caplog.set_level(logging.DEBUG)
    await _drop_and_reconnect(client, panel, clock)
    await _until(lambda: bool(panel.held))

    if how == "async_disconnect":
        await client.async_disconnect()
    elif how == "close":
        await client.close()
    else:
        panel.drop_link()

    panel.release_held()  # the panel accepts, too late
    await _settle()
    assert client.authenticated is False
    link_drop_warnings = [m for m in _reauth_logs(caplog) if "cancelled by a link drop" in m]
    assert len(link_drop_warnings) == (1 if how == "link_drop" else 0)
    assert str(DUMMY_PIN) not in caplog.text
    if how == "close":
        return
    # The PIN was not restored: the next connect sends no authenticate.
    panel.auth = "accept"
    await client.async_connect(HOST, 2101, KEYS)
    await _settle()
    assert panel.auth_requests() == []
    assert client.authenticated is False
    await client.async_disconnect()


@pytest.mark.asyncio
async def test_deliberate_close_event_clears_pin_even_with_opt_in(panel: _FakePanel) -> None:
    client, _ = await _connected(reauth=True)
    assert await _authenticate(client) is True
    await client.async_disconnect()  # the kernel reports reason="closed"
    assert client.authenticated is False
    await client.async_connect(HOST, 2101, KEYS)
    await _settle()
    assert panel.auth_requests() == []
    await client.async_disconnect()


@pytest.mark.asyncio
async def test_session_change_clears_pin_for_refresh_csm(panel: _FakePanel) -> None:
    client, _ = await _connected(request_timeout_s=0.05)
    assert await _authenticate(client) is True
    await client.async_refresh_csm()
    first = panel.session
    assert len(_pin_messages(first.sent)) == 2  # authenticate + the refresh's authenticate
    # A new session (new session_id) without a link-drop event in between.
    await client.async_connect(HOST, 2101, KEYS)
    assert panel.session is not first
    await client.async_refresh_csm()
    assert _pin_messages(panel.session.sent) == []
    await client.async_disconnect()


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


def _no_socket() -> Any:
    return cast(Any, object())


@pytest.mark.asyncio
async def test_unicast_discovery_ignores_other_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_endpoint(monkeypatch, [(_discovery_reply("203.0.113.5"), ("198.51.100.9", 2362))])
    result = await async_discover_host(HOST, timeout=0.2, socket_factory=_no_socket)
    assert result is None


@pytest.mark.asyncio
async def test_unicast_discovery_returns_queried_address(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_endpoint(monkeypatch, [(_discovery_reply("203.0.113.5"), (HOST, 2362))])
    result = await async_discover_host(HOST, timeout=0.2, socket_factory=_no_socket)
    assert result is not None
    assert result.host == HOST


@pytest.mark.asyncio
@pytest.mark.parametrize("port", [99999999, 0, -1, 65536, "x", True])
async def test_discovery_rejects_out_of_range_port(
    port: object, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    _patch_endpoint(monkeypatch, [(_discovery_reply(HOST, port=port), (HOST, 2362))])
    found = await AIOELKDiscovery().async_scan(timeout=0.2, address=HOST, sock=_no_socket())
    assert found == []
    assert "port out of range" in caplog.text
    ignored = [r for r in caplog.records if "port out of range" in r.getMessage()]
    assert all("aa:bb:cc:dd:ee:ff" not in r.getMessage() for r in ignored)


@pytest.mark.asyncio
async def test_broadcast_discovery_flags_address_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_endpoint(
        monkeypatch,
        [
            (_discovery_reply("203.0.113.5"), ("198.51.100.9", 2362)),
            (_discovery_reply("198.51.100.7"), ("198.51.100.7", 2362)),
        ],
    )
    found = await AIOELKDiscovery().async_scan(timeout=0.2, sock=_no_socket())
    by_source = {s.source_host: s for s in found}
    assert by_source["198.51.100.9"].address_mismatch is True
    assert by_source["198.51.100.7"].address_mismatch is False


@pytest.mark.asyncio
async def test_discovery_non_object_reply_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_endpoint(monkeypatch, [(b'["ELKWC2017"]', (HOST, 2362))])
    found = await AIOELKDiscovery().async_scan(timeout=0.2, address=HOST, sock=_no_socket())
    assert found == []


# ---------------------------------------------------------------- D6


_KEY = bytes(range(16))


def _frame(envelope_seq: int) -> bytes:
    payload = json.dumps({"seq": 0, "area": {"get_status": {"area_id": 1}}}).encode()
    proto, ct = encrypt_schema0_envelope(
        payload=payload, session_key=_KEY, envelope_seq=envelope_seq
    )
    return frame_build(protocol_byte=proto, data_frame=ct)


class _FrameSocket:
    """A TCP socket that delivers the given frames, then times out."""

    def __init__(self, frames: list[bytes]) -> None:
        self.frames = frames

    def settimeout(self, _t: float | None) -> None:
        return None

    def setsockopt(self, *_a: object) -> None:
        return None

    def connect(self, _addr: object) -> None:
        return None

    def recv(self, _n: int) -> bytes:
        if self.frames:
            return self.frames.pop(0)
        raise TimeoutError

    def sendall(self, _data: bytes) -> None:
        return None

    def shutdown(self, _how: int) -> None:
        return None

    def close(self) -> None:
        return None


def _connected_session(monkeypatch: pytest.MonkeyPatch, frames: list[bytes]) -> Session:
    """A Session that ran connect() (HELLO faked) and will receive ``frames``."""
    sock = _FrameSocket(frames)
    monkeypatch.setattr(session_mod.socket, "socket", lambda *_a, **_k: sock)
    monkeypatch.setattr(
        session_mod,
        "perform_hello",
        lambda **_k: SessionKeys(session_id=1, session_key_hex=_KEY.hex(), hmac_key_hex="00" * 32),
    )
    s = Session(
        SessionConfig(host=HOST, auto_receive=False),
        client_identity=linking.E27Identity("1", "2", "0", "0", "0"),
        link_key_hex="00" * 16,
    )
    s.connect()
    return s


def _seq_logs(caplog: pytest.LogCaptureFixture, level: int) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if r.levelno == level and "envelope seq did not increase" in r.getMessage()
    ]


def test_replayed_frame_warns_once_and_is_kept(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    frame = _frame(7)
    s = _connected_session(monkeypatch, [frame, frame, frame])
    first = s.recv_json(timeout_s=1)
    assert _seq_logs(caplog, logging.WARNING) == []
    second = s.recv_json(timeout_s=1)
    third = s.recv_json(timeout_s=1)
    assert first == second == third  # warn-only: never dropped
    assert _seq_logs(caplog, logging.WARNING) == [
        "Inbound envelope seq did not increase (last=7 got=7); frame kept"
    ]
    assert _seq_logs(caplog, logging.DEBUG) == [
        "Inbound envelope seq did not increase (last=7 got=7); count=2"
    ]


def test_rx_seq_tracker_resets_for_new_session(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    s = _connected_session(monkeypatch, [_frame(9)])
    s.recv_json(timeout_s=1)
    # A new HELLO session starts the tracker afresh: seq 1 after 9 is fine.
    monkeypatch.setattr(session_mod.socket, "socket", lambda *_a, **_k: _FrameSocket([_frame(1)]))
    s.connect()
    s.recv_json(timeout_s=1)
    assert _seq_logs(caplog, logging.WARNING) == []
    # Within that session, a lower seq still warns.
    monkeypatch.setattr(
        session_mod.socket, "socket", lambda *_a, **_k: _FrameSocket([_frame(5), _frame(4)])
    )
    s.connect()
    s.recv_json(timeout_s=1)
    s.recv_json(timeout_s=1)
    assert _seq_logs(caplog, logging.WARNING) == [
        "Inbound envelope seq did not increase (last=5 got=4); frame kept"
    ]


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


def test_discovery_cap_keeps_split_hello_prefix() -> None:
    """Over the cap, the newest bytes are kept, not just the last chunk (Bugbot)."""
    raw = b'{"ELKWC2017":"dummy","nonce":"DUMMYNONCE"}'
    junk = b"x" * (linking.DISCOVERY_BUFFER_MAX - 22)
    sock = _ChunkSocket([junk, raw[:20], raw[20:]])
    assert len(junk) + len(raw) > linking.DISCOVERY_BUFFER_MAX
    assert linking.wait_for_discovery_nonce(cast(Any, sock), timeout_s=1.0) == "DUMMYNONCE"


def test_discovery_invalid_json_is_an_error_not_need_more_data() -> None:
    sock = _ChunkSocket([b'{"ELKWC2017":"dummy","nonce":}'])
    with pytest.raises(E27ProtocolError):
        linking.wait_for_discovery_nonce(cast(Any, sock), timeout_s=1.0)


def test_discovery_buffer_capped_for_large_nonceless_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    with pytest.raises(E27ProvisioningTimeout):
        linking.wait_for_discovery_nonce(cast(Any, _ChunkSocket(chunks)), timeout_s=timeout_s)
    assert time.monotonic() - start <= timeout_s + 2
    assert sizes
    assert max(sizes) <= linking.DISCOVERY_BUFFER_MAX


@pytest.mark.asyncio
async def test_paged_block_count_over_cap_is_protocol_error(panel: _FakePanel) -> None:
    client = Elke27Client()
    await client.async_connect(HOST, 2101, KEYS)
    await _settle()
    panel.overrides[("zone", "get_configured")] = lambda msg: {
        "seq": msg["seq"],
        "zone": {"get_configured": {"block_id": 1, "block_count": 10_000, "zones": [1]}},
    }
    before = len(panel.session.sent)
    result = await asyncio.wait_for(client.async_execute("zone_get_configured"), timeout=1.0)
    assert result.ok is False
    assert isinstance(result.error, ProtocolError)
    assert str(MAX_PAGED_BLOCK_COUNT) in str(result.error)
    requested = [m for m in panel.session.sent[before:] if "zone" in m]
    assert len(requested) == 1  # no second block requested
    await client.async_disconnect()


def _conn_event() -> ConnectionStateChanged:
    return ConnectionStateChanged(
        kind=ConnectionStateChanged.KIND,
        at=0.0,
        seq=None,
        classification="LOCAL",
        route=("__local__", ConnectionStateChanged.KIND),
        session_id=1,
        connected=True,
        reason=None,
    )


def _emit(kernel: E27Kernel, count: int) -> None:
    ctx = cast(
        Any,
        type(
            "Ctx",
            (),
            {"seq": None, "classification": "LOCAL", "route": ("a", "b"), "session_id": 1},
        )(),
    )
    for _ in range(count):
        kernel.emit(_conn_event(), ctx)


@pytest.mark.parametrize(
    ("maxlen", "kept"),
    [(None, DEFAULT_EVENT_QUEUE_MAXLEN), (0, DEFAULT_EVENT_QUEUE_MAXLEN + 2), (3, 3)],
)
def test_event_deque_bounds(maxlen: int | None, kept: int) -> None:
    assert DEFAULT_EVENT_QUEUE_MAXLEN == 4096
    kernel = E27Kernel(event_queue_maxlen=maxlen)
    _emit(kernel, DEFAULT_EVENT_QUEUE_MAXLEN + 2)
    assert len(kernel.drain_events()) == kept
    assert kernel.events_dropped == DEFAULT_EVENT_QUEUE_MAXLEN + 2 - kept


def test_event_deque_drop_logged_once_at_debug(caplog: pytest.LogCaptureFixture) -> None:
    kernel = E27Kernel(event_queue_maxlen=2)
    caplog.set_level(logging.DEBUG)
    _emit(kernel, 5)
    assert len(kernel.drain_events()) == 2
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
    caplog.set_level(logging.DEBUG)
    _emit(kernel, DEFAULT_EVENT_QUEUE_MAXLEN + 4)
    assert len(delivered) == DEFAULT_EVENT_QUEUE_MAXLEN + 4
    assert kernel.events_dropped == 4
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
