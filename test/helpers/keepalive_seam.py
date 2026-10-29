"""Injectable keepalive clock / timeout scheduler for offline tests (#79)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, cast

from elke27_lib.kernel import E27Kernel, KeepaliveTestHooks, _QueuedRequest, _RequestState
from elke27_lib.outbound import OutboundPriority
from elke27_lib.session import SessionState
from test.helpers.internal import get_private, set_private


@dataclass
class MonotonicTestClock:
    """Settable monotonic clock for kernel ``now_monotonic``."""

    t: float = 1000.0

    def now(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


@dataclass
class KeepaliveSeam:
    clock: MonotonicTestClock
    kernel: E27Kernel
    _timeouts: list[tuple[float, Callable[[], None]]] = field(default_factory=list)

    def fire_due_timeouts(self) -> None:
        now = self.clock.now()
        remaining: list[tuple[float, Callable[[], None]]] = []
        for deadline, callback in self._timeouts:
            if deadline <= now:
                callback()
            else:
                remaining.append((deadline, callback))
        self._timeouts = remaining

    async def sleep(self, delay: float) -> None:
        self.clock.advance(delay)
        self.fire_due_timeouts()
        await asyncio.sleep(0)

    def schedule_reply_timeout(self, delay: float, callback: Callable[[], None]) -> None:
        self._timeouts.append((self.clock.now() + delay, callback))

    def advance(self, dt: float) -> None:
        self.clock.advance(dt)
        self.fire_due_timeouts()


def kernel_with_keepalive_seam(*, start: float = 1000.0) -> KeepaliveSeam:
    clock = MonotonicTestClock(start)
    seam = KeepaliveSeam(clock=clock, kernel=E27Kernel())  # placeholder
    hooks = KeepaliveTestHooks(sleep=seam.sleep, schedule_reply_timeout=seam.schedule_reply_timeout)
    seam.kernel = E27Kernel(now_monotonic=clock.now, keepalive_test_hooks=hooks)
    return seam


class _FakeSession:
    def __init__(self) -> None:
        self.state = SessionState.ACTIVE
        self.disconnects: list[Exception | None] = []

    def handle_disconnect(self, err: Exception | None) -> None:
        self.disconnects.append(err)


def _probing_kernel(seam: KeepaliveSeam) -> tuple[E27Kernel, _FakeSession]:
    kernel = seam.kernel
    set_private(kernel, "_loop", asyncio.get_running_loop())
    set_private(kernel, "_keepalive_enabled", True)
    set_private(kernel, "_keepalive_interval_s", 0.0)
    set_private(kernel, "_keepalive_timeout_s", 5.0)
    set_private(kernel, "_keepalive_max_missed", 1)
    set_private(kernel, "_last_rx_at", 0.0)
    fake = _FakeSession()
    cast(Any, fake)._outbound = type("O", (), {"is_idle": lambda self: True})()
    set_private(kernel, "_session", fake)
    kernel.requests.register(("system", "r_u_alive"), lambda: {})
    return kernel, fake


def _arm_probe_timeout(kernel: E27Kernel, seq: int, timeout_s: float) -> None:
    item = _QueuedRequest(
        seq=seq,
        domain="system",
        name="r_u_alive",
        payload={},
        pending=False,
        opaque=None,
        expected_route=("system", "r_u_alive"),
        priority=OutboundPriority.HIGH,
        timeout_s=timeout_s,
    )
    set_private(kernel, "_request_state", _RequestState.IN_FLIGHT)
    set_private(kernel, "_active_seq", seq)
    set_private(kernel, "_active_request", item)
    cast(Any, kernel)._on_request_sent(seq, timeout_s)


def _install_probe_send(
    seam: KeepaliveSeam,
    kernel: E27Kernel,
    *,
    reply_delay_s: float | None,
) -> None:
    timeout_s = float(get_private(kernel, "_keepalive_timeout_s"))

    def _send(seq: int, *_a: Any, **kw: Any) -> int:
        cast(Any, kernel)._signal_sent_event(seq)
        _arm_probe_timeout(kernel, seq, float(kw.get("timeout_s", timeout_s)))
        if reply_delay_s is None:
            return seq
        seam.advance(reply_delay_s)
        if reply_delay_s < timeout_s:
            set_private(kernel, "_last_rx_at", seam.clock.now())
            cast(Any, kernel)._pending_responses.resolve(
                seq, {"seq": seq, "system": {"r_u_alive": {}}}
            )
        return seq

    set_private(kernel, "_send_request_with_seq", _send)


def _install_o14_late_rx_rescue_send(seam: KeepaliveSeam, kernel: E27Kernel) -> None:
    """Probe reply times out (D > T) after send returns; unrelated rx lands after ``sent_at``."""
    timeout_s = float(get_private(kernel, "_keepalive_timeout_s"))

    def _send(seq: int, *_a: Any, **kw: Any) -> int:
        cast(Any, kernel)._signal_sent_event(seq)
        _arm_probe_timeout(kernel, seq, float(kw.get("timeout_s", timeout_s)))

        async def _deliver_after_send() -> None:
            await asyncio.sleep(0)
            seam.clock.advance(timeout_s + 0.01)
            seam.clock.advance(0.001)
            cast(Any, kernel)._on_message(
                {
                    "seq": seq + 10_000,
                    "area": {"get_status": {"area_id": 1, "error_code": 0}},
                }
            )
            seam.fire_due_timeouts()

        asyncio.create_task(_deliver_after_send())
        return seq

    set_private(kernel, "_send_request_with_seq", _send)


async def run_o10() -> None:
    seam = kernel_with_keepalive_seam()
    kernel, fake = _probing_kernel(seam)
    timeout_s = float(get_private(kernel, "_keepalive_timeout_s"))
    _install_probe_send(seam, kernel, reply_delay_s=timeout_s - 0.5)
    set_private(kernel, "_keepalive_missed", 1)
    assert await cast(Any, kernel)._send_keepalive_request() is True

    async def _probe_ok(*, force: bool = False) -> bool:
        set_private(kernel, "_closing", True)
        return True

    set_private(kernel, "_send_keepalive_request", _probe_ok)
    await cast(Any, kernel)._keepalive_loop()
    assert get_private(kernel, "_keepalive_missed") == 0
    assert fake.disconnects == []


async def run_o11() -> None:
    seam = kernel_with_keepalive_seam()
    kernel, fake = _probing_kernel(seam)
    timeout_s = float(get_private(kernel, "_keepalive_timeout_s"))
    _install_probe_send(seam, kernel, reply_delay_s=timeout_s)
    # Boundary: scheduled timeout at D=T fires; no early resolve -> miss.
    assert await cast(Any, kernel)._send_keepalive_request() is False
    assert fake.disconnects == []


async def run_o12() -> None:
    seam = kernel_with_keepalive_seam()
    kernel, fake = _probing_kernel(seam)
    timeout_s = float(get_private(kernel, "_keepalive_timeout_s"))
    _install_probe_send(seam, kernel, reply_delay_s=timeout_s + 0.01)
    assert await cast(Any, kernel)._send_keepalive_request() is False
    set_private(kernel, "_keepalive_missed", 0)

    async def _probe_miss(*, force: bool = False) -> bool:
        return False

    set_private(kernel, "_send_keepalive_request", _probe_miss)
    await cast(Any, kernel)._keepalive_loop()
    assert len(fake.disconnects) == 1


async def run_o13() -> None:
    seam = kernel_with_keepalive_seam()
    kernel, fake = _probing_kernel(seam)
    set_private(kernel, "_keepalive_max_missed", 2)
    probes = {"n": 0}

    async def _probe_miss(*, force: bool = False) -> bool:
        probes["n"] += 1
        return False

    set_private(kernel, "_send_keepalive_request", _probe_miss)
    await cast(Any, kernel)._keepalive_loop()
    assert probes["n"] == 2
    assert len(fake.disconnects) == 1


class RecordingSession:
    """Fake transport that records outbound frames and delivers replies on demand."""

    def __init__(self) -> None:
        self.state = SessionState.ACTIVE
        self.disconnects: list[Exception | None] = []
        self.sent: list[tuple[dict[str, Any], Callable[[float], None] | None]] = []
        self.on_message: Callable[[dict[str, Any]], None] | None = None

    def handle_disconnect(self, err: Exception | None) -> None:
        self.disconnects.append(err)

    def send_json(
        self,
        obj: dict[str, Any],
        *,
        priority: OutboundPriority = OutboundPriority.NORMAL,
        on_sent: Callable[[float], None] | None = None,
        on_fail: Callable[[BaseException], None] | None = None,
    ) -> None:
        del priority, on_fail
        self.sent.append((obj, on_sent))

    def confirm_sent(self, index: int) -> int:
        obj, on_sent = self.sent[index]
        if on_sent is not None:
            on_sent(0.0)
        return int(obj["seq"])

    def deliver(self, msg: dict[str, Any]) -> None:
        assert self.on_message is not None
        self.on_message(msg)


def attach_recording_session(seam: KeepaliveSeam) -> RecordingSession:
    kernel, _ = _probing_kernel(seam)
    session = RecordingSession()
    cast(Any, session)._outbound = type("O", (), {"is_idle": lambda self: True})()
    session.on_message = cast(Any, kernel)._on_message
    set_private(kernel, "_session", session)
    return session


async def run_forced_probe_no_rescue_from_prior_command_reply() -> None:
    """Forced probe queued behind an in-flight command; the command's reply must not rescue it."""
    seam = kernel_with_keepalive_seam()
    kernel = seam.kernel
    session = attach_recording_session(seam)
    kernel.register_request(("area", "arm"), lambda: {})

    cmd_seq = kernel.request(("area", "arm"))
    assert len(session.sent) == 1
    assert session.confirm_sent(0) == cmd_seq

    probe = asyncio.create_task(cast(Any, kernel)._send_keepalive_request(force=True))
    for _ in range(3):
        await asyncio.sleep(0)
    assert len(session.sent) == 1

    seam.clock.advance(2.0)
    session.deliver({"seq": cmd_seq, "area": {"arm": {"error_code": 0}}})
    assert len(session.sent) == 2
    probe_seq = session.confirm_sent(1)
    assert session.sent[1][0]["system"] == {"r_u_alive": {}}
    for _ in range(3):
        await asyncio.sleep(0)

    seam.advance(float(get_private(kernel, "_keepalive_timeout_s")))
    assert await asyncio.wait_for(probe, timeout=2.0) is False
    assert probe_seq != cmd_seq


async def run_o14() -> None:
    seam = kernel_with_keepalive_seam()
    kernel, fake = _probing_kernel(seam)
    _install_o14_late_rx_rescue_send(seam, kernel)
    assert await cast(Any, kernel)._send_keepalive_request() is True
    set_private(kernel, "_keepalive_missed", 1)

    async def _probe_rescue(*, force: bool = False) -> bool:
        set_private(kernel, "_closing", True)
        return True

    set_private(kernel, "_send_keepalive_request", _probe_rescue)
    await cast(Any, kernel)._keepalive_loop()
    assert fake.disconnects == []


async def run_o15() -> None:
    seam = kernel_with_keepalive_seam()
    kernel, fake = _probing_kernel(seam)
    timeout_s = float(get_private(kernel, "_keepalive_timeout_s"))
    _install_probe_send(seam, kernel, reply_delay_s=timeout_s + 0.01)
    cast(Any, kernel)._start_keepalive()
    task = get_private(kernel, "_keepalive_task")
    assert task is not None
    await asyncio.wait_for(task, timeout=2.0)
    assert task.done()
    assert len(fake.disconnects) == 1
    set_private(kernel, "_keepalive_enabled", True)
    set_private(kernel, "_session", fake)
    fake.state = SessionState.ACTIVE
    fake.disconnects.clear()
    set_private(kernel, "_closing", False)
    set_private(kernel, "_keepalive_missed", 0)
    cast(Any, kernel)._start_keepalive()
    second = get_private(kernel, "_keepalive_task")
    assert second is not None and second is not task and not second.done()
    live_task = get_private(kernel, "_keepalive_task")
    assert live_task is not None and not live_task.done()
    set_private(kernel, "_closing", True)
    cast(Any, kernel)._stop_keepalive()
