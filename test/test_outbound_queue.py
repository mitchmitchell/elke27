import asyncio
import threading
import time
from collections.abc import Callable
from typing import ParamSpec, TypeVar

import pytest

from elke27_lib.outbound_loop import OutboundItem, OutboundPriority, OutboundQueue

P = ParamSpec("P")
R = TypeVar("R")


async def _to_thread_inline(fn: Callable[P, R], /, *args: P.args, **kwargs: P.kwargs) -> R:
    """Run ``fn`` on the event-loop thread so the throttle test sees no worker-pool jitter."""
    return fn(*args, **kwargs)


async def _throttled_send_gaps(
    monkeypatch: pytest.MonkeyPatch,
    *,
    count: int,
    idle_s: float = 0.0,
    cadence_s: float = 0.0,
) -> list[float]:
    """Return adjacent ``send_fn`` start gaps on the loop clock for a 50 ms, burst-1 queue.

    ``asyncio.to_thread`` runs inline here, so ``send_fn`` starts on the loop thread in the
    same step that the throttle releases the frame. Its ``loop.time()`` stamps are therefore
    the release times, observed through the public ``send_fn`` seam without thread-pool start
    or completion jitter (#106). The queue idles ``idle_s`` after start, then receives
    ``count`` items, sleeping ``cadence_s`` between enqueues when it is non-zero.
    """
    monkeypatch.setattr(asyncio, "to_thread", _to_thread_inline)
    loop = asyncio.get_running_loop()
    loop_thread = threading.get_ident()
    send_times: list[float] = []
    send_threads: list[int] = []
    done = asyncio.Event()

    def _send(payload: bytes) -> None:
        del payload
        send_times.append(loop.time())
        send_threads.append(threading.get_ident())
        if len(send_times) >= count:
            done.set()

    queue = OutboundQueue(loop=loop, send_fn=_send, min_interval_s=0.05, max_burst=1)
    queue.start()
    try:
        if idle_s > 0:
            await asyncio.sleep(idle_s)
        for i in range(count):
            queue.enqueue(
                OutboundItem(
                    payload=b"x",
                    seq=i,
                    kind="request",
                    priority=OutboundPriority.NORMAL,
                    enqueued_at=time.monotonic(),
                )
            )
            if cadence_s > 0:
                await asyncio.sleep(cadence_s)
        await asyncio.wait_for(done.wait(), timeout=3.0)
    finally:
        queue.stop()
    assert send_threads == [loop_thread] * len(send_times)
    return [b - a for a, b in zip(send_times, send_times[1:], strict=False)]


@pytest.mark.asyncio
async def test_outbound_queue_throttle(monkeypatch: pytest.MonkeyPatch) -> None:
    """Back-to-back sends are spaced by ``min_interval_s`` without being over-throttled."""
    deltas = await _throttled_send_gaps(monkeypatch, count=5)
    assert all(delta >= 0.04 for delta in deltas), deltas
    assert max(deltas) < 0.09, deltas


@pytest.mark.asyncio
async def test_outbound_queue_throttle_paced_producer(monkeypatch: pytest.MonkeyPatch) -> None:
    """A producer enqueuing faster than ``min_interval_s`` still gets spaced releases.

    Items arrive 20 ms apart, so each throttle call sees real elapsed time and the token
    refill rate decides the spacing.
    """
    deltas = await _throttled_send_gaps(monkeypatch, count=5, cadence_s=0.02)
    assert all(delta >= 0.04 for delta in deltas), deltas


@pytest.mark.asyncio
async def test_outbound_queue_throttle_idle_does_not_bank_burst(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Idle time refills at most ``max_burst`` tokens, so a later burst is still spaced."""
    deltas = await _throttled_send_gaps(monkeypatch, count=4, idle_s=0.3)
    assert all(delta >= 0.04 for delta in deltas), deltas


@pytest.mark.asyncio
async def test_outbound_queue_priority() -> None:
    loop = asyncio.get_running_loop()
    sent: list[str] = []
    done = asyncio.Event()

    def _send(payload: bytes) -> None:
        del payload

    def _make_on_sent(label: str) -> Callable[[float], None]:
        def _cb(_: float) -> None:
            sent.append(label)
            if len(sent) >= 4:
                done.set()

        return _cb

    queue = OutboundQueue(loop=loop, send_fn=_send, min_interval_s=0.01, max_burst=1)
    queue.start()

    queue.enqueue(
        OutboundItem(
            payload=b"n1",
            seq=1,
            kind="request",
            priority=OutboundPriority.NORMAL,
            enqueued_at=time.monotonic(),
            on_sent=_make_on_sent("n1"),
        )
    )
    queue.enqueue(
        OutboundItem(
            payload=b"n2",
            seq=2,
            kind="request",
            priority=OutboundPriority.NORMAL,
            enqueued_at=time.monotonic(),
            on_sent=_make_on_sent("n2"),
        )
    )
    queue.enqueue(
        OutboundItem(
            payload=b"n3",
            seq=3,
            kind="request",
            priority=OutboundPriority.NORMAL,
            enqueued_at=time.monotonic(),
            on_sent=_make_on_sent("n3"),
        )
    )
    queue.enqueue(
        OutboundItem(
            payload=b"h1",
            seq=99,
            kind="request",
            priority=OutboundPriority.HIGH,
            enqueued_at=time.monotonic(),
            on_sent=_make_on_sent("h1"),
        )
    )

    await asyncio.wait_for(done.wait(), timeout=2.0)
    assert "h1" in sent
    assert sent.index("h1") < sent.index("n3")


@pytest.mark.asyncio
async def test_outbound_queue_stop_fails_pending() -> None:
    loop = asyncio.get_running_loop()
    failed = asyncio.Event()

    def _send(payload: bytes) -> None:
        del payload

    def _on_fail(exc: BaseException) -> None:
        assert isinstance(exc, RuntimeError)
        failed.set()

    queue = OutboundQueue(loop=loop, send_fn=_send, min_interval_s=0.5, max_burst=1)
    queue.start()

    queue.enqueue(
        OutboundItem(
            payload=b"x",
            seq=1,
            kind="request",
            priority=OutboundPriority.NORMAL,
            enqueued_at=time.monotonic(),
            on_fail=_on_fail,
        )
    )

    queue.stop(fail_exc=RuntimeError("transport gone"))
    await asyncio.wait_for(failed.wait(), timeout=1.0)


@pytest.mark.asyncio
async def test_outbound_queue_cancel_pending_seq() -> None:
    loop = asyncio.get_running_loop()

    def _send(_payload: bytes) -> None:
        return None

    queue = OutboundQueue(loop=loop, send_fn=_send, min_interval_s=10.0, max_burst=1)
    queue.start()
    for seq in (10, 11):
        queue.enqueue(
            OutboundItem(
                payload=b"x",
                seq=seq,
                kind="request",
                priority=OutboundPriority.NORMAL,
                enqueued_at=time.monotonic(),
            )
        )
    await asyncio.sleep(0)
    assert queue.cancel_pending_seq(11) is True
    assert queue.cancel_pending_seq(11) is False
    assert queue.cancel_pending_seq(10) is True


@pytest.mark.asyncio
async def test_cancel_pending_seq_during_throttle_skips_send() -> None:
    """Codex P1 (#31): a frame dequeued but still throttling must be cancellable."""
    loop = asyncio.get_running_loop()
    sent: list[bytes] = []

    queue = OutboundQueue(loop=loop, send_fn=sent.append, min_interval_s=0.2, max_burst=1)
    queue.start()
    for seq, payload in ((1, b"first"), (2, b"second")):
        queue.enqueue(
            OutboundItem(
                payload=payload,
                seq=seq,
                kind="request",
                priority=OutboundPriority.NORMAL,
                enqueued_at=time.monotonic(),
            )
        )

    # Wait until seq 2 has been dequeued and is sleeping in _throttle().
    for _ in range(200):
        if queue._current_seq == 2 and not queue._sending:
            break
        await asyncio.sleep(0.005)
    assert queue._current_seq == 2

    assert queue.cancel_pending_seq(2) is True
    await asyncio.sleep(0.4)
    assert sent == [b"first"]
    assert await queue.wait_idle(timeout_s=1.0)
    queue.stop()
