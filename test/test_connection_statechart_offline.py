"""Offline connection statechart cases (O1-O22).

Each test maps to one offline case in the connection statechart test plan. Only
``session.Session`` is replaced by a controllable fake; kernel and client are real.
No sockets, no panel, no credentials (dummy values only).

Cases that need the session-ownership fix are marked xfail until it lands.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import threading
import time
from collections.abc import Callable
from typing import Any

import pytest

from elke27_lib import linking
from elke27_lib import session as session_mod
from elke27_lib.events import ConnectionStateChanged, Event
from elke27_lib.hello import SessionKeys
from elke27_lib.kernel import E27Kernel, KernelError
from test.helpers.reauth_panel import (
    _authenticate,
    _connected,
    _drop_and_reconnect,
    _FakePanel,
)
from test.helpers.reauth_panel import _FakeSession as _ReplyingSession

KEYS = linking.E27LinkKeys("aa", "bb", "cc")
IDENTITY = linking.E27Identity("mn", "sn", "fw", "hw", "os")
CFG = session_mod.SessionConfig(host="198.51.100.1", port=1, keepalive_enabled=False)

NEEDS_OWNERSHIP_FIX = pytest.mark.xfail(
    raises=(AssertionError, pytest.fail.Exception),
    reason="#78: needs the post-0.2.1 session-ownership fix (generation-tagged sessions)",
    strict=True,
)


class _Fake:
    """A controllable session. ``mode``: ok | oserror | io | refuse | proto | not_active."""

    def __init__(self, registry: _Registry) -> None:
        self.registry = registry
        self.mode = registry.next_mode()
        self.gate = registry.next_gate()
        self.state = session_mod.SessionState.DISCONNECTED
        self.info = session_mod.SessionInfo(
            session_id=11 + len(registry.sessions), session_key_hex="00", session_hmac_hex="11"
        )
        self.wire_log_suppress_seqs: object = None
        self.on_message: Any = None
        self.on_disconnected: Any = None
        self.on_idle: Any = None
        self.sent: list[dict[str, Any]] = []
        self.close_count = 0
        self.connect_started = threading.Event()
        registry.sessions.append(self)

    @property
    def live(self) -> bool:
        return self.state == session_mod.SessionState.ACTIVE and self.close_count == 0

    def connect(self) -> session_mod.SessionInfo:
        self.connect_started.set()
        if self.gate is not None:
            self.gate.wait(5)
        if self.mode == "oserror":
            raise ConnectionRefusedError("connect refused (fake)")
        if self.mode == "io":
            raise session_mod.SessionIOError("connect refused (fake)")
        if self.mode == "refuse":
            from elke27_lib.errors import E27HelloNoSession

            refused = E27HelloNoSession(("session_id",))
            if self.on_disconnected is not None:
                self.on_disconnected(refused)
            raise session_mod.SessionProtocolError(str(refused)) from refused
        if self.mode == "proto":
            err = session_mod.SessionProtocolError("hello failed (fake)")
            if self.on_disconnected is not None:
                self.on_disconnected(err)
            raise err
        if self.mode == "not_active":
            self.state = session_mod.SessionState.HELLO
            return self.info
        self.state = session_mod.SessionState.ACTIVE
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

    def close(self) -> None:
        self.close_count += 1
        self.state = session_mod.SessionState.DISCONNECTED


class _Registry:
    def __init__(self) -> None:
        self.sessions: list[_Fake] = []
        self.modes: list[str] = []
        self.gates: list[threading.Event | None] = []

    def next_mode(self) -> str:
        return self.modes.pop(0) if self.modes else "ok"

    def next_gate(self) -> threading.Event | None:
        return self.gates.pop(0) if self.gates else None

    def live_count(self) -> int:
        return sum(1 for s in self.sessions if s.live)


@pytest.fixture
def reg(monkeypatch: pytest.MonkeyPatch) -> _Registry:
    registry = _Registry()

    def _factory(*, cfg: object, client_identity: object, link_key_hex: str) -> _Fake:
        del cfg, client_identity, link_key_hex
        return _Fake(registry)

    monkeypatch.setattr(session_mod, "Session", _factory)
    return registry


def _kernel(monkeypatch: pytest.MonkeyPatch) -> tuple[E27Kernel, list[ConnectionStateChanged]]:
    kernel = E27Kernel()
    monkeypatch.setattr(kernel, "load_features_blocking", lambda _modules=None: None)
    events: list[ConnectionStateChanged] = []

    def _on(evt: Event) -> None:
        if isinstance(evt, ConnectionStateChanged):
            events.append(evt)

    kernel.subscribe(_on, kinds={ConnectionStateChanged.KIND})
    return kernel, events


async def _connect(kernel: E27Kernel) -> session_mod.SessionState:
    return await kernel.connect(KEYS, session_config=CFG, client_identity=IDENTITY)


async def _until(cond: Callable[[], bool], timeout_s: float = 2.0) -> None:
    deadline = time.monotonic() + timeout_s
    while not cond():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.005)


def _pairs_ok(events: list[ConnectionStateChanged]) -> bool:
    """At most one connected=False per connected=True (refusals excepted)."""
    up = False
    for evt in events:
        if evt.connected:
            up = True
        elif up:
            up = False
        elif not evt.hello_refused:
            return False
    return True


def _has_session(kernel: E27Kernel) -> bool:
    try:
        _ = kernel.session
    except KernelError:
        return False
    return True


# ------------------------------------------------------------------ O1


@pytest.mark.asyncio
async def test_o1_transient_connect_failure_retries_without_delay(
    reg: _Registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O1: client retries a transient connect failure immediately; 2nd failure raises."""
    from elke27_lib.client import Elke27Client, LinkKeys

    reg.modes = ["oserror", "oserror"]
    client = Elke27Client()
    started = time.monotonic()
    with pytest.raises(Exception):  # noqa: B017 - public error type varies by mapping
        await client.async_connect("198.51.100.1", 1, LinkKeys("aa", "bb", "cc"))
    assert len(reg.sessions) == 2
    assert time.monotonic() - started < 1.0


@pytest.mark.asyncio
async def test_o1_both_attempts_are_logged(
    reg: _Registry, caplog: pytest.LogCaptureFixture
) -> None:
    """O1: each of the two attempts leaves its own log line."""
    from elke27_lib.client import Elke27Client, LinkKeys

    reg.modes = ["oserror", "oserror"]
    caplog.set_level(logging.DEBUG, logger="elke27_lib")
    with pytest.raises(Exception):  # noqa: B017 - public error type varies by mapping
        await Elke27Client().async_connect("198.51.100.1", 1, LinkKeys("aa", "bb", "cc"))
    msgs = [r.getMessage() for r in caplog.records]
    assert any("Connect failed (attempt 1/2)" in m for m in msgs)
    assert any("Connect failed (attempt 2/2)" in m for m in msgs)


# ------------------------------------------------------------------ O2


@pytest.mark.asyncio
async def test_o2_cancel_during_hello_then_success_closes_orphan(
    reg: _Registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    kernel, events = _kernel(monkeypatch)
    gate = threading.Event()
    reg.gates = [gate]
    task = asyncio.create_task(_connect(kernel))
    await _until(lambda: bool(reg.sessions) and reg.sessions[0].connect_started.is_set())
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    gate.set()
    await _until(lambda: reg.sessions[0].close_count >= 1)
    assert reg.live_count() == 0
    assert not _has_session(kernel)
    assert [e for e in events if not e.connected] == []


# ------------------------------------------------------------------ O3


@NEEDS_OWNERSHIP_FIX
@pytest.mark.asyncio
async def test_o3_orphan_hello_failure_does_not_touch_newer_session(
    reg: _Registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    kernel, events = _kernel(monkeypatch)
    gate = threading.Event()
    reg.modes = ["proto", "ok"]
    reg.gates = [gate, None]
    task = asyncio.create_task(_connect(kernel))
    await _until(lambda: bool(reg.sessions) and reg.sessions[0].connect_started.is_set())
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await _connect(kernel)
    assert kernel.state.panel.connected
    gate.set()
    await _until(lambda: reg.sessions[0].close_count >= 1)
    await asyncio.sleep(0.05)
    assert kernel.state.panel.connected
    assert [e.connected for e in events] == [True]


# ------------------------------------------------------------------ O4


@NEEDS_OWNERSHIP_FIX
@pytest.mark.asyncio
async def test_o4_second_connect_closes_first_session(
    reg: _Registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    kernel, events = _kernel(monkeypatch)
    await _connect(kernel)
    await _connect(kernel)
    assert reg.sessions[0].close_count >= 1
    assert reg.live_count() == 1
    assert _pairs_ok(events)


# ------------------------------------------------------------------ O5 / O6


@NEEDS_OWNERSHIP_FIX
@pytest.mark.asyncio
async def test_o5_retry_after_not_active_leaves_one_live_session(
    reg: _Registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    kernel, _events = _kernel(monkeypatch)
    reg.modes = ["not_active", "ok"]
    with pytest.raises(KernelError):
        await _connect(kernel)
    await _connect(kernel)
    assert reg.sessions[0].close_count >= 1
    assert reg.live_count() == 1


@NEEDS_OWNERSHIP_FIX
@pytest.mark.asyncio
async def test_o6_not_active_session_is_never_installed(
    reg: _Registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    kernel, events = _kernel(monkeypatch)
    reg.modes = ["not_active"]
    with pytest.raises(KernelError):
        await _connect(kernel)
    assert not _has_session(kernel)
    assert reg.sessions[0].close_count >= 1
    assert events == []


# ------------------------------------------------------------------ O7 / O8


@pytest.mark.asyncio
async def test_o7a_hello_refusal_false_is_flagged(
    reg: _Registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O7: a refused HELLO never yields connected=True, and its connected=False
    (no prior True) is flagged as a refusal, so it is not a 'lost' event."""
    kernel, events = _kernel(monkeypatch)
    reg.modes = ["refuse"]
    with pytest.raises(KernelError):
        await _connect(kernel)
    assert not any(e.connected for e in events)
    assert events and all(e.hello_refused for e in events)


@pytest.mark.xfail(
    raises=AssertionError,
    reason="#77: plan O7 pair invariant; a non-refusal HELLO failure still emits an "
    "unflagged connected=False with no prior connected=True (needs its own issue)",
    strict=True,
)
@pytest.mark.asyncio
async def test_o7b_hello_protocol_failure_emits_no_unflagged_false(
    reg: _Registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    kernel, events = _kernel(monkeypatch)
    reg.modes = ["proto"]
    with pytest.raises(KernelError):
        await _connect(kernel)
    assert _pairs_ok(events)


@pytest.mark.asyncio
async def test_o8_tcp_error_on_connect_emits_nothing(
    reg: _Registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    kernel, events = _kernel(monkeypatch)
    reg.modes = ["io"]
    with pytest.raises(KernelError):
        await _connect(kernel)
    assert events == []
    assert not _has_session(kernel)


# ------------------------------------------------------------------ O9


@pytest.mark.asyncio
async def test_o9a_io_error_from_closed_session_ignored(
    reg: _Registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    kernel, events = _kernel(monkeypatch)
    await _connect(kernel)
    await kernel.close()
    reg.sessions[0].on_disconnected(session_mod.SessionIOError("late (fake)"))
    assert [e.connected for e in events] == [True, False]


@NEEDS_OWNERSHIP_FIX
@pytest.mark.asyncio
async def test_o9b_protocol_error_from_closed_session_ignored(
    reg: _Registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    kernel, events = _kernel(monkeypatch)
    await _connect(kernel)
    await kernel.close()
    reg.sessions[0].on_disconnected(session_mod.SessionProtocolError("late (fake)"))
    assert [e.connected for e in events] == [True, False]


# ------------------------------------------------------------------ O10-O16


_KEEPALIVE_SEAM = (
    "#79: needs an injectable keepalive clock/reply-delay seam; existing coverage: "
    "test_dead_link_detection.py ({})"
)


@pytest.mark.skip(reason=_KEEPALIVE_SEAM.format("none for D<T recovery yet"))
def test_o10_keepalive_reply_before_timeout() -> None: ...


@pytest.mark.skip(reason=_KEEPALIVE_SEAM.format("D=T tie is a model artefact; document only"))
def test_o11_keepalive_tie() -> None: ...


@pytest.mark.skip(reason=_KEEPALIVE_SEAM.format("test_single_missed_keepalive_disconnects"))
def test_o12_keepalive_one_miss_disconnects() -> None: ...


@pytest.mark.skip(reason=_KEEPALIVE_SEAM.format("none for max_missed=2 yet"))
def test_o13_keepalive_two_misses() -> None: ...


@pytest.mark.skip(
    reason=_KEEPALIVE_SEAM.format("test_probe_timeout_with_other_traffic_counts_as_alive")
)
def test_o14_keepalive_traffic_rescue() -> None: ...


@pytest.mark.skip(
    reason=_KEEPALIVE_SEAM.format("indirect only: test_keepalive_restarts_on_fresh_event_loop")
)
def test_o15_keepalive_task_cleared_after_expiry() -> None: ...


class _WakeOnCloseSocket:
    """recv blocks until the socket is closed, then fails like a real one."""

    def __init__(self) -> None:
        self.closed = threading.Event()

    def settimeout(self, _t: float | None) -> None:
        return None

    def setsockopt(self, *_a: object) -> None:
        return None

    def connect(self, _addr: object) -> None:
        return None

    def recv(self, _n: int) -> bytes:
        if self.closed.wait(0.05):
            raise OSError("socket closed (fake)")
        raise TimeoutError

    def sendall(self, _data: bytes) -> None:
        return None

    def shutdown(self, _how: int) -> None:
        self.closed.set()

    def close(self) -> None:
        self.closed.set()


def test_o16_intentional_close_wakes_receiver_without_lost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """O16: a real Session's receiver, woken by an intentional close (its blocked
    recv fails), exits without reporting a disconnect."""
    sock = _WakeOnCloseSocket()
    monkeypatch.setattr(session_mod.socket, "socket", lambda *_a, **_k: sock)
    monkeypatch.setattr(
        session_mod,
        "perform_hello",
        lambda **_k: SessionKeys(
            session_id=1, session_key_hex=bytes(range(16)).hex(), hmac_key_hex="00" * 32
        ),
    )
    s = session_mod.Session(
        session_mod.SessionConfig(host="198.51.100.1", auto_receive=False),
        client_identity=linking.E27Identity("1", "2", "0", "0", "0"),
        link_key_hex="00" * 16,
    )
    s.connect()
    lost: list[Exception | None] = []
    s.on_disconnected = lost.append
    s.start_auto_receive()
    time.sleep(0.05)
    s.close()
    time.sleep(0.3)  # let the woken receiver run to exit
    assert sock.closed.is_set()
    assert lost == []
    assert s.state == session_mod.SessionState.DISCONNECTED


# ------------------------------------------------------------------ O17


@NEEDS_OWNERSHIP_FIX
@pytest.mark.asyncio
async def test_o17_link_loss_racing_close_emits_one_false(
    reg: _Registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A receiver-thread loss that lands just after close() must not add a 2nd False."""
    kernel, events = _kernel(monkeypatch)
    await _connect(kernel)
    s = reg.sessions[0]
    late = threading.Thread(
        target=lambda: (
            time.sleep(0.02),
            s.on_disconnected(session_mod.SessionProtocolError("racing loss (fake)")),
        )
    )
    late.start()
    await kernel.close()
    await asyncio.to_thread(late.join)
    assert [e.connected for e in events] == [True, False]


# ------------------------------------------------------------------ O18 / O19


@pytest.mark.asyncio
async def test_o18_connected_but_bootstrap_never_completes(reg: _Registry) -> None:
    """O18: connected, but the panel never answers bootstrap: wait_ready returns
    False at its timeout, the client stays not-ready, and nothing hangs."""
    from elke27_lib.client import Elke27Client, LinkKeys

    client = Elke27Client()
    await asyncio.wait_for(
        client.async_connect("198.51.100.1", 1, LinkKeys("aa", "bb", "cc")), timeout=2.0
    )
    assert reg.live_count() == 1
    assert reg.sessions[0].sent, "bootstrap requests were sent"
    started = time.monotonic()
    assert await client.wait_ready(0.1) is False
    assert time.monotonic() - started < 1.0
    assert client.ready is False
    await asyncio.wait_for(client.async_disconnect(), timeout=2.0)


@pytest.fixture
def replying_panel(monkeypatch: pytest.MonkeyPatch) -> _FakePanel:
    fake = _FakePanel()

    def _factory(*, cfg: object, client_identity: object, link_key_hex: str) -> Any:
        del cfg, client_identity, link_key_hex
        return _ReplyingSession(fake)

    monkeypatch.setattr(session_mod, "Session", _factory)
    return fake


@pytest.mark.asyncio
@pytest.mark.parametrize("auth", ["hold", "refuse"])
async def test_o19_command_issued_before_reauth_reply(
    replying_panel: _FakePanel, auth: str
) -> None:
    """O19: after a reconnect with opt-in re-auth, a command issued before the
    re-auth reply never hangs. If the panel accepts, the command succeeds once
    re-auth lands; if it refuses, the command gets a clear not-authorized error."""
    panel = replying_panel
    client, clock = await _connected(reauth=True, request_timeout_s=2.0)
    assert await _authenticate(client) is True
    authed = {"v": False}

    def _status(msg: dict[str, Any]) -> dict[str, Any]:
        code = 0 if authed["v"] else 11008  # panel: not authorized until re-auth
        return {"seq": msg["seq"], "area": {"get_status": {"area_id": 1, "error_code": code}}}

    panel.overrides[("area", "get_status")] = _status
    panel.auth = auth
    await _drop_and_reconnect(client, panel, clock)
    if auth == "hold":
        await _until(lambda: bool(panel.held))
    started = time.monotonic()
    task = asyncio.create_task(client.async_execute("area_get_status", area_id=1))
    await asyncio.sleep(0.05)
    if auth == "hold":
        authed["v"] = True
        panel.release_held()
    result = await asyncio.wait_for(task, timeout=3.0)
    assert time.monotonic() - started < 1.0
    if auth == "hold":
        assert result.ok
        assert client.authenticated is True
    else:
        assert not result.ok
        assert "not authorized" in str(result.error)
        assert client.authenticated is False
    await client.async_disconnect()


# ------------------------------------------------------------------ O20


@NEEDS_OWNERSHIP_FIX
@pytest.mark.asyncio
async def test_o20_close_during_connect_leaves_no_live_session(
    reg: _Registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    kernel, events = _kernel(monkeypatch)
    gate = threading.Event()
    reg.gates = [gate]
    task = asyncio.create_task(_connect(kernel))
    await _until(lambda: bool(reg.sessions) and reg.sessions[0].connect_started.is_set())
    await kernel.close()
    gate.set()
    with pytest.raises(KernelError):
        await task
    assert reg.live_count() == 0
    assert not _has_session(kernel)
    assert not any(e.connected for e in events)


# ------------------------------------------------------------------ O21


@NEEDS_OWNERSHIP_FIX
@pytest.mark.asyncio
async def test_o21_callbacks_from_non_current_session_are_noops(
    reg: _Registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    kernel, events = _kernel(monkeypatch)
    await _connect(kernel)
    old = reg.sessions[0]
    await kernel.close()
    await _connect(kernel)
    before = list(events)
    old.on_disconnected(session_mod.SessionProtocolError("foreign (fake)"))
    old.on_disconnected(session_mod.SessionIOError("foreign (fake)"))
    assert events == before
    assert kernel.state.panel.connected


# ------------------------------------------------------------------ O22


# O22: expected TLC outcome per config. The Teardown and Keepalive specs have
# terminal states (a run ends once its events are spent), which TLC reports as
# "Deadlock reached" by default. That is not a bug in the modelled code, so those
# specs run with -deadlock; Ownership runs with deadlock checking on.
# FIXED=FALSE configs must still FAIL by invariant (1a/1b/1c/2) so a spec edit that
# hides the bugs is caught. Keepalive: 3a/3e pass, 3c/3d fail by design (policy),
# 3b (D=T tie) fails as a discrete-time model artefact.
_TLC_EXPECT: dict[str, bool] = {
    "Own_AtMostOneLiveWired_TRUE": True,
    "Own_NoForeignCallbackEffect_TRUE": True,
    "Own_NoLiveAfterClose_TRUE": True,
    "Own_AtMostOneLiveWired_FALSE": False,
    "Own_NoForeignCallbackEffect_FALSE": False,
    "Own_NoLiveAfterClose_FALSE": False,
    "Teardown_TRUE": True,
    "Teardown_FALSE": False,
    "KA_A_DltT": True,
    "KA_B_DeqT": False,
    "KA_C_DgtT": False,
    "KA_D_DgtT_M2": False,
    "KA_E_DgtT_traffic": True,
}
_TLC_INVARIANT_RC = 12  # TLC exit code for an invariant violation


def _tlc_cmd() -> list[str]:
    jar = os.environ.get("ELKE27_TLC_JAR")
    return ["java", "-cp", jar, "tlc2.TLC"] if jar else ["tlc"]


@pytest.mark.skipif(
    not os.environ.get("ELKE27_TLC_SPECS"),
    reason="TLC model-check gate is optional; set ELKE27_TLC_SPECS (and ELKE27_TLC_JAR "
    "or put tlc on PATH) to run",
)
@pytest.mark.parametrize("name", sorted(_TLC_EXPECT))
def test_o22_tlc_regression_gate(name: str) -> None:
    spec_dir = os.environ["ELKE27_TLC_SPECS"]
    if name.startswith("Own_"):
        module, flags = "Ownership", []
    elif name.startswith("Teardown"):
        module, flags = "Teardown", ["-deadlock"]
    else:
        module, flags = "Keepalive", ["-deadlock"]
    result = subprocess.run(
        [*_tlc_cmd(), *flags, "-config", f"{name}.cfg", f"{module}.tla"],
        cwd=spec_dir,
        capture_output=True,
        text=True,
        check=False,
        timeout=600,
    )
    if _TLC_EXPECT[name]:
        assert result.returncode == 0, f"{name}: rc={result.returncode}"
        assert "No error has been found" in result.stdout
    else:
        assert result.returncode == _TLC_INVARIANT_RC, f"{name}: rc={result.returncode}"
        assert "is violated" in result.stdout
