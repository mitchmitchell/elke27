"""Public-path keepalive harness (#95): a fake panel link, a stepped clock, and the
``KeepaliveTestHooks`` that let a test decide when probes are written, answered or
time out. Probes are started with ``E27Kernel.request_link_check`` on a kernel
connected through ``E27Kernel.connect``; outcomes are read from ``keepalive_stats``.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import pytest

from elke27_lib import linking_thread as linking
from elke27_lib import session_thread as session_mod
from elke27_lib.kernel_loop import E27Kernel, KeepaliveStats, KeepaliveTestHooks
from elke27_lib.outbound_loop import OutboundPriority
from test.helpers.keepalive_seam import MonotonicTestClock

KEYS = linking.E27LinkKeys("aa", "bb", "cc")
IDENTITY = linking.E27Identity("mn", "sn", "fw", "hw", "os")
IDLE_INTERVAL_S = 3600.0
TIMEOUT_S = 5.0


class PanelLink:
    """Stand-in for ``Session``: records frames and plays the panel on demand."""

    def __init__(
        self,
        clock: MonotonicTestClock,
        *,
        fail_sends: bool,
        connect_gate: threading.Event | None = None,
    ) -> None:
        self.clock = clock
        self.fail_sends = fail_sends
        self.connect_gate = connect_gate
        self.handshake_entered = threading.Event()
        self.probe_in_flight_at_creation = False
        self.pending_at_creation = 0
        self.state = session_mod.SessionState.DISCONNECTED
        self.info = session_mod.SessionInfo(
            session_id=1, session_key_hex="00", session_hmac_hex="11"
        )
        self.sent: list[tuple[Mapping[str, Any], Callable[[float], None] | None]] = []
        self.disconnects: list[Exception | None] = []
        self.cancelled: list[int] = []
        self.wire_log_suppress_seqs: object = None
        self.on_message: Callable[[Mapping[str, Any]], None] | None = None
        self.on_disconnected: Callable[[Exception | None], None] | None = None
        self.on_idle: Callable[..., None] | None = None
        self.on_rx: Callable[[], None] | None = None

    def connect(self) -> session_mod.SessionInfo:
        """Complete the handshake, first waiting on ``connect_gate`` when one is set.

        Sets ``handshake_entered`` on entry. A gate that stays closed for 5 s fails
        the handshake instead of letting a stuck test carry on.
        """
        self.handshake_entered.set()
        if self.connect_gate is not None and not self.connect_gate.wait(timeout=5.0):
            raise session_mod.SessionIOError("connect gate never opened")
        self.state = session_mod.SessionState.ACTIVE
        return self.info

    def bind_loop(self, *_args: object, **_kwargs: object) -> None:
        return None

    def enable_outbound_queue(self, **_kwargs: object) -> None:
        return None

    def start_auto_receive(self) -> None:
        return None

    def send_json(
        self,
        obj: Mapping[str, Any],
        *,
        priority: OutboundPriority = OutboundPriority.NORMAL,
        on_sent: Callable[[float], None] | None = None,
        on_fail: Callable[[BaseException], None] | None = None,
    ) -> None:
        del priority
        if self.fail_sends:
            if on_fail is not None:
                on_fail(session_mod.SessionIOError("send failed"))
            return
        self.sent.append((obj, on_sent))

    def cancel_outbound_pending_seq(self, seq: int) -> None:
        self.cancelled.append(seq)

    def handle_disconnect(self, err: Exception | None) -> None:
        self.disconnects.append(err)
        self.state = session_mod.SessionState.DISCONNECTED

    def close(self) -> None:
        self.state = session_mod.SessionState.DISCONNECTED

    def seq(self, index: int) -> int:
        return int(self.sent[index][0]["seq"])

    def confirm(self, index: int) -> int:
        """Report frame ``index`` written to the socket, as the transport would."""
        on_sent = self.sent[index][1]
        assert on_sent is not None
        on_sent(0.0)
        return self.seq(index)

    def receive(self, msg: Mapping[str, Any]) -> None:
        """Deliver one inbound message the way ``Session`` does: ``on_rx`` first."""
        assert self.on_rx is not None and self.on_message is not None
        self.on_rx()
        self.on_message(msg)

    def reply(self, index: int) -> None:
        self.receive({"seq": self.seq(index), "system": {"r_u_alive": {}}})

    def drop(self) -> None:
        """Report the link lost, as the receive thread does on a socket error."""
        assert self.on_disconnected is not None
        self.on_disconnected(session_mod.SessionIOError("link lost"))


async def _idle_sleep(delay: float) -> None:
    if delay >= IDLE_INTERVAL_S / 2:
        await asyncio.Event().wait()
    await asyncio.sleep(0)


@dataclass
class KeepaliveLink:
    """A kernel on a ``PanelLink`` whose probe reply deadlines follow ``clock``."""

    monkeypatch: pytest.MonkeyPatch
    clock: MonotonicTestClock
    kernel: E27Kernel
    fail_sends: bool = False
    links: list[PanelLink] = field(default_factory=list)
    deadlines: list[tuple[float, Callable[[], None]]] = field(default_factory=list)
    connect_gate: threading.Event | None = None
    """When set, the next link's handshake blocks until the event is set."""

    @property
    def session(self) -> PanelLink:
        return self.links[-1]

    @property
    def stats(self) -> KeepaliveStats:
        return self.kernel.keepalive_stats

    def schedule(self, delay: float, callback: Callable[[], None]) -> None:
        self.deadlines.append((self.clock.now() + delay, callback))

    def advance(self, dt: float) -> None:
        self.clock.advance(dt)
        due = [cb for at, cb in self.deadlines if at <= self.clock.now()]
        self.deadlines = [(at, cb) for at, cb in self.deadlines if at > self.clock.now()]
        for callback in due:
            callback()

    def _new_link(self, **_kwargs: object) -> PanelLink:
        gate, self.connect_gate = self.connect_gate, None
        link = PanelLink(self.clock, fail_sends=self.fail_sends, connect_gate=gate)
        link.probe_in_flight_at_creation = self.kernel.keepalive_stats.probe_in_flight
        link.pending_at_creation = self.kernel.pending_responses.pending_count()
        self.links.append(link)
        return link

    async def connect(self, *, max_missed: int = 1) -> PanelLink:
        self.monkeypatch.setattr(session_mod, "Session", self._new_link)
        cfg = session_mod.SessionConfig(
            host="198.51.100.1",
            port=1,
            keepalive_enabled=True,
            keepalive_interval_s=IDLE_INTERVAL_S,
            keepalive_timeout_s=TIMEOUT_S,
            keepalive_max_missed=max_missed,
        )
        await self.kernel.connect(KEYS, session_config=cfg, client_identity=IDENTITY)
        return self.session

    async def check_link(self, *, frames: int = 1) -> None:
        """Ask for a probe now and wait until the link holds ``frames`` frames."""
        self.kernel.request_link_check()
        await until(lambda: len(self.session.sent) >= frames)


def keepalive_link(
    monkeypatch: pytest.MonkeyPatch,
    *,
    send_wait_s: float | None = None,
    fail_sends: bool = False,
    start: float = 1000.0,
    probe_builder: Callable[[], Mapping[str, Any]] | None = None,
    sleep: Callable[[float], Awaitable[None]] = _idle_sleep,
) -> KeepaliveLink:
    clock = MonotonicTestClock(start)
    link_ref: list[KeepaliveLink] = []
    hooks = KeepaliveTestHooks(
        sleep=sleep,
        schedule_reply_timeout=lambda d, cb: link_ref[0].schedule(d, cb),
        send_wait_s=send_wait_s,
    )
    kernel = E27Kernel(
        now_monotonic=clock.now, keepalive_test_hooks=hooks, skip_connect_bootstrap=True
    )
    monkeypatch.setattr(kernel, "load_features_blocking", lambda _modules=None: None)
    kernel.requests.register(("system", "r_u_alive"), probe_builder or dict)
    link_ref.append(KeepaliveLink(monkeypatch, clock, kernel, fail_sends))
    return link_ref[0]


async def until(cond: Callable[[], bool], *, timeout_s: float = 2.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        if cond():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition not met")


def assert_keepalive_invariants(stats: KeepaliveStats) -> None:
    """Architect #95 counters; post-write probe errors share no dedicated counter."""
    assert stats.replies + stats.probe_timeouts <= stats.probes_sent
    assert stats.rescued <= stats.probe_timeouts
    if stats.last_round_trip_s is not None:
        assert stats.last_round_trip_s >= 0.0
    if stats.last_round_trip_s is not None and stats.max_round_trip_s is not None:
        assert stats.max_round_trip_s >= stats.last_round_trip_s
