"""Session ownership: a kernel owns at most one live session (post-0.2.1 fix).

Only ``session.Session`` is replaced by a gated fake; dummy values only.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any

import pytest

from elke27_lib import linking
from elke27_lib import session as session_mod
from elke27_lib.events import ConnectionStateChanged, Event
from elke27_lib.kernel import E27Kernel, KernelError

KEYS = linking.E27LinkKeys("aa", "bb", "cc")
IDENTITY = linking.E27Identity("mn", "sn", "fw", "hw", "os")
CFG = session_mod.SessionConfig(host="198.51.100.1", port=1, keepalive_enabled=False)


class _GatedSession:
    def __init__(self, sessions: list[_GatedSession], gate: threading.Event | None) -> None:
        self.gate = gate
        self.state = session_mod.SessionState.DISCONNECTED
        self.info = session_mod.SessionInfo(
            session_id=1 + len(sessions), session_key_hex="00", session_hmac_hex="11"
        )
        self.wire_log_suppress_seqs: object = None
        self.on_message: Any = None
        self.on_disconnected: Any = None
        self.on_idle: Any = None
        self.started = threading.Event()
        self.close_count = 0
        sessions.append(self)

    def connect(self) -> session_mod.SessionInfo:
        self.started.set()
        if self.gate is not None:
            self.gate.wait(5)
        if self.close_count == 0:
            self.state = session_mod.SessionState.ACTIVE
        return self.info

    def enable_outbound_queue(self, **_kwargs: object) -> None:
        return None

    def start_auto_receive(self) -> None:
        return None

    def send_json(self, msg: dict[str, Any], **kwargs: Any) -> None:
        on_sent = kwargs.get("on_sent")
        if on_sent is not None:
            on_sent(time.monotonic())

    def close(self) -> None:
        self.close_count += 1
        self.state = session_mod.SessionState.DISCONNECTED


@pytest.fixture
def setup(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[E27Kernel, list[_GatedSession], list[threading.Event | None], list[bool]]:
    sessions: list[_GatedSession] = []
    gates: list[threading.Event | None] = []

    def _factory(**_kwargs: object) -> _GatedSession:
        return _GatedSession(sessions, gates.pop(0) if gates else None)

    monkeypatch.setattr(session_mod, "Session", _factory)
    kernel = E27Kernel()
    monkeypatch.setattr(kernel, "load_features_blocking", lambda _modules=None: None)
    events: list[bool] = []

    def _on(evt: Event) -> None:
        if isinstance(evt, ConnectionStateChanged):
            events.append(evt.connected)

    kernel.subscribe(_on, kinds={ConnectionStateChanged.KIND})
    return kernel, sessions, gates, events


async def _connect(kernel: E27Kernel) -> session_mod.SessionState:
    return await kernel.connect(KEYS, session_config=CFG, client_identity=IDENTITY)


async def _started(sessions: list[_GatedSession]) -> None:
    for _ in range(400):
        if sessions and sessions[-1].started.is_set():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("connect never started")


@pytest.mark.asyncio
async def test_close_racing_connect_never_installs_the_session(setup: Any) -> None:
    kernel, sessions, gates, events = setup
    gate = threading.Event()
    gates.append(gate)
    task = asyncio.create_task(_connect(kernel))
    await _started(sessions)
    await kernel.close()
    gate.set()
    with pytest.raises(KernelError, match="abandoned"):
        await task
    assert sessions[0].close_count >= 1
    assert not kernel.state.panel.connected
    with pytest.raises(KernelError):
        _ = kernel.session
    assert events == []
    # The kernel is still usable afterwards.
    await _connect(kernel)
    assert kernel.session is not None
    assert events == [True]


@pytest.mark.asyncio
async def test_connect_closes_prior_session_and_ignores_its_callbacks(setup: Any) -> None:
    kernel, sessions, _gates, events = setup
    await _connect(kernel)
    await _connect(kernel)
    old, new = sessions
    assert old.close_count >= 1
    assert new.close_count == 0
    assert events == [True, False, True]
    old.on_disconnected(session_mod.SessionProtocolError("late (fake)"))
    old.on_message({"seq": 0})
    assert events == [True, False, True]
    assert kernel.state.panel.connected


@pytest.mark.asyncio
async def test_reconnect_after_link_loss_does_not_repeat_disconnect(setup: Any) -> None:
    kernel, sessions, _gates, events = setup
    await _connect(kernel)
    sessions[0].on_disconnected(session_mod.SessionIOError("link lost (fake)"))
    assert events == [True, False]
    await _connect(kernel)
    assert events == [True, False, True]
    assert sessions[0].close_count >= 1


@pytest.mark.asyncio
async def test_superseded_in_flight_connect_is_closed(setup: Any) -> None:
    kernel, sessions, gates, events = setup
    gate = threading.Event()
    gates.append(gate)
    first = asyncio.create_task(_connect(kernel))
    await _started(sessions)
    second = asyncio.create_task(_connect(kernel))
    for _ in range(400):
        if len(sessions) == 2:
            break
        await asyncio.sleep(0.005)
    await second
    gate.set()
    with pytest.raises(KernelError):
        await first
    assert sessions[0].close_count >= 1
    assert kernel.session is not None
    assert events == [True]


async def _wait_sessions(sessions: list[_GatedSession], n: int) -> None:
    for _ in range(400):
        if len(sessions) >= n and sessions[n - 1].started.is_set():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("connect never started")


@pytest.mark.asyncio
async def test_superseded_mid_hello_callbacks_are_ignored(setup: Any) -> None:
    """Race (a): two concurrent connects; the first is superseded while still connecting."""
    kernel, sessions, gates, events = setup
    gate1, gate2 = threading.Event(), threading.Event()
    gates.extend([gate1, gate2])
    first = asyncio.create_task(_connect(kernel))
    await _wait_sessions(sessions, 1)
    second = asyncio.create_task(_connect(kernel))
    await _wait_sessions(sessions, 2)
    # The superseded attempt reports from its receiver thread mid-connect.
    t = threading.Thread(
        target=sessions[0].on_disconnected,
        args=(session_mod.SessionProtocolError("late (fake)"),),
    )
    t.start()
    t.join(5)
    sessions[0].on_message({"seq": 0})
    gate1.set()
    gate2.set()
    await second
    with pytest.raises(KernelError):
        await first
    assert sessions[0].close_count >= 1
    assert sessions[1].close_count == 0
    assert kernel.session is not None
    assert events == [True]
    assert kernel.state.panel.connected


@pytest.mark.asyncio
async def test_close_during_connect_does_not_block_next_in_flight_connect(setup: Any) -> None:
    """Race (b): the close-during-connect mark must not retire the next generation."""
    kernel, sessions, gates, events = setup
    gate1, gate2 = threading.Event(), threading.Event()
    gates.extend([gate1, gate2])
    first = asyncio.create_task(_connect(kernel))
    await _wait_sessions(sessions, 1)
    await kernel.close()
    second = asyncio.create_task(_connect(kernel))
    await _wait_sessions(sessions, 2)
    gate1.set()
    with pytest.raises(KernelError, match="abandoned"):
        await first
    gate2.set()
    assert await second == session_mod.SessionState.ACTIVE
    assert kernel.session is not None
    assert sessions[1].close_count == 0
    assert events == [True]


@pytest.mark.asyncio
async def test_cancel_during_connect_then_reconnect_ignores_orphan(setup: Any) -> None:
    """Race (c): a cancelled attempt's session is orphaned; its callbacks change nothing."""
    kernel, sessions, gates, events = setup
    gate = threading.Event()
    gates.append(gate)
    first = asyncio.create_task(_connect(kernel))
    await _wait_sessions(sessions, 1)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    await _connect(kernel)
    gate.set()
    orphan, current = sessions
    for _ in range(400):
        if orphan.close_count:
            break
        await asyncio.sleep(0.005)
    assert orphan.close_count >= 1
    orphan.on_disconnected(session_mod.SessionIOError("orphan (fake)"))
    orphan.on_message({"seq": 0})
    orphan.on_idle()
    assert kernel.session is not None
    assert current.close_count == 0
    assert events == [True]
    assert kernel.state.panel.connected
