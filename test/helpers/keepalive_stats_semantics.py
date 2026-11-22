"""Offline keepalive stats scenarios for #95 (fake transport, injected monotonic clock)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, cast

import pytest

from elke27_lib.kernel_loop import E27Kernel, KeepaliveStats, KeepaliveTestHooks, KernelError
from elke27_lib.outbound_loop import OutboundPriority
from elke27_lib.session_thread import SessionIOError
from test.helpers.internal import get_private, set_private
from test.helpers.keepalive_seam import (
    KeepaliveSeam,
    MonotonicTestClock,
    RecordingSession,
    attach_recording_session,
)


def assert_keepalive_invariants(stats: KeepaliveStats) -> None:
    assert stats.replies + stats.probe_timeouts <= stats.probes_sent
    assert stats.rescued <= stats.probe_timeouts
    if stats.last_round_trip_s is not None:
        assert stats.last_round_trip_s >= 0.0
    if stats.last_round_trip_s is not None and stats.max_round_trip_s is not None:
        assert stats.max_round_trip_s >= stats.last_round_trip_s


def probing_seam(*, send_wait_s: float = 30.0) -> tuple[KeepaliveSeam, E27Kernel, RecordingSession]:
    clock = MonotonicTestClock(1000.0)
    seam = KeepaliveSeam(clock=clock, kernel=E27Kernel())
    hooks = KeepaliveTestHooks(
        send_wait_s=send_wait_s,
        sleep=seam.sleep,
        schedule_reply_timeout=seam.schedule_reply_timeout,
    )
    seam.kernel = E27Kernel(now_monotonic=clock.now, keepalive_test_hooks=hooks)
    session = attach_recording_session(seam)
    kernel = seam.kernel
    set_private(kernel, "_keepalive_timeout_s", 5.0)
    return seam, kernel, session


async def wait_until(cond: Callable[[], bool], *, timeout_s: float = 2.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        if cond():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition not met")


async def until_sent(session: RecordingSession, n: int = 1) -> None:
    await wait_until(lambda: len(session.sent) >= n)


def probe_reply(seq: int) -> dict[str, Any]:
    return {"seq": seq, "system": {"r_u_alive": {}}}


def confirm_sent_and_maybe_reply(
    seam: KeepaliveSeam,
    session: RecordingSession,
    index: int,
    *,
    reply_after_s: float | None,
) -> int:
    obj, on_sent = session.sent[index]
    seq = int(obj["seq"])
    if on_sent is not None:
        on_sent(0.0)
    if reply_after_s is not None:
        seam.clock.advance(reply_after_s)
        session.deliver(probe_reply(seq))
    return seq


class FailSendSession(RecordingSession):
    def send_json(
        self,
        obj: dict[str, Any],
        *,
        priority: OutboundPriority = OutboundPriority.NORMAL,
        on_sent: Callable[[float], None] | None = None,
        on_fail: Callable[[BaseException], None] | None = None,
    ) -> None:
        del obj, priority, on_sent
        if on_fail is not None:
            on_fail(SessionIOError("send failed"))


def kernel_failing_send(*, send_wait_s: float = 0.05) -> E27Kernel:
    clock = MonotonicTestClock(1000.0)
    kernel = E27Kernel(
        now_monotonic=clock.now,
        keepalive_test_hooks=KeepaliveTestHooks(send_wait_s=send_wait_s),
    )
    set_private(kernel, "_loop", asyncio.get_running_loop())
    set_private(kernel, "_keepalive_enabled", True)
    set_private(kernel, "_keepalive_timeout_s", 5.0)
    set_private(kernel, "_rx_thread_at", 0.0)
    session = FailSendSession()
    session.on_message = cast(Any, kernel)._on_message
    set_private(kernel, "_session", session)
    kernel.requests.register(("system", "r_u_alive"), lambda: {})
    return kernel


async def run_unsent_send_error() -> None:
    kernel = kernel_failing_send()
    assert await asyncio.wait_for(kernel._send_keepalive_request(force=True), timeout=2.0) is False
    stats = kernel.keepalive_stats
    assert stats.probes_sent == 0
    assert stats.probes_failed == 1
    assert_keepalive_invariants(stats)


async def run_unsent_send_wait_timeout() -> None:
    seam, kernel, session = probing_seam(send_wait_s=0.05)
    task = asyncio.create_task(cast(Any, kernel)._send_keepalive_request(force=True))
    await until_sent(session)
    seam.advance(0.06)
    assert await asyncio.wait_for(task, timeout=2.0) is False
    stats = kernel.keepalive_stats
    assert stats.probes_sent == 0
    assert stats.probes_failed == 1
    assert_keepalive_invariants(stats)


async def run_unsent_abort() -> None:
    seam, kernel, session = probing_seam(send_wait_s=2.0)
    task = asyncio.create_task(cast(Any, kernel)._send_keepalive_request(force=True))
    await until_sent(session)
    cast(Any, kernel)._abort_requests(KernelError("abort"))
    assert await asyncio.wait_for(task, timeout=2.0) is False
    stats = kernel.keepalive_stats
    assert stats.probes_sent == 0
    assert stats.probes_failed == 1
    assert_keepalive_invariants(stats)


async def run_immediate_reply_rtt() -> None:
    seam, kernel, session = probing_seam()
    task = asyncio.create_task(cast(Any, kernel)._send_keepalive_request(force=True))
    await until_sent(session)
    confirm_sent_and_maybe_reply(seam, session, 0, reply_after_s=0.250)
    assert await asyncio.wait_for(task, timeout=2.0) is True
    stats = kernel.keepalive_stats
    assert stats.probes_sent == 1
    assert stats.replies == 1
    assert stats.last_round_trip_s == 0.250
    assert stats.max_round_trip_s == 0.250
    assert_keepalive_invariants(stats)


async def run_unsent_unrelated_inbound() -> None:
    seam, kernel, session = probing_seam(send_wait_s=2.0)
    task = asyncio.create_task(cast(Any, kernel)._send_keepalive_request(force=True))
    await until_sent(session)
    assert kernel.keepalive_stats.probes_sent == 0
    unrelated_seq = int(session.sent[0][0]["seq"]) + 99
    session.deliver({"seq": unrelated_seq, "area": {"get_status": {"area_id": 1}}})
    await asyncio.sleep(0)
    stats = kernel.keepalive_stats
    assert stats.replies == 0
    assert stats.last_round_trip_s is None
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def run_stale_reply_while_newer_outstanding() -> None:
    seam, kernel, session = probing_seam()
    first = asyncio.create_task(cast(Any, kernel)._send_keepalive_request(force=True))
    await until_sent(session)
    seq_old = confirm_sent_and_maybe_reply(seam, session, 0, reply_after_s=None)
    seam.advance(float(get_private(kernel, "_keepalive_timeout_s")) + 0.01)
    assert await asyncio.wait_for(first, timeout=2.0) is False
    assert kernel.keepalive_stats.probe_timeouts == 1

    second = asyncio.create_task(cast(Any, kernel)._send_keepalive_request(force=True))
    await wait_until(lambda: len(session.sent) >= 2)
    seq_new = int(session.sent[1][0]["seq"])
    assert seq_new != seq_old
    session.deliver(probe_reply(seq_old))
    await asyncio.sleep(0)
    mid = kernel.keepalive_stats
    assert mid.replies == 0
    assert mid.last_round_trip_s is None

    confirm_sent_and_maybe_reply(seam, session, 1, reply_after_s=0.1)
    assert await asyncio.wait_for(second, timeout=2.0) is True
    stats = kernel.keepalive_stats
    assert stats.replies == 1
    assert stats.probe_timeouts == 1
    assert stats.last_round_trip_s == pytest.approx(0.1)
    assert_keepalive_invariants(stats)


async def run_probe_timeout_and_rescued() -> None:
    seam, kernel, session = probing_seam()
    task = asyncio.create_task(cast(Any, kernel)._send_keepalive_request(force=True))
    await until_sent(session)
    sent_seq = confirm_sent_and_maybe_reply(seam, session, 0, reply_after_s=None)
    seam.advance(float(get_private(kernel, "_keepalive_timeout_s")) + 0.01)
    set_private(kernel, "_rx_thread_at", seam.clock.now() + 0.001)
    session.deliver({"seq": sent_seq + 500, "area": {"get_status": {"area_id": 1}}})
    assert await asyncio.wait_for(task, timeout=2.0) is True
    stats = kernel.keepalive_stats
    assert stats.probes_sent == 1
    assert stats.probe_timeouts == 1
    assert stats.rescued == 1
    assert stats.replies == 0
    assert_keepalive_invariants(stats)


async def run_large_clock_offset_rtt() -> None:
    seam, kernel, session = probing_seam()
    seam.clock.t = 9_000_000_000.0
    task = asyncio.create_task(cast(Any, kernel)._send_keepalive_request(force=True))
    await until_sent(session)
    confirm_sent_and_maybe_reply(seam, session, 0, reply_after_s=12.5)
    assert await asyncio.wait_for(task, timeout=2.0) is True
    stats = kernel.keepalive_stats
    assert stats.last_round_trip_s == 12.5
    assert stats.last_round_trip_s is not None and stats.last_round_trip_s >= 0.0
    assert_keepalive_invariants(stats)
