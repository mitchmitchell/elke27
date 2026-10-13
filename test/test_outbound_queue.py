import asyncio
import time
from collections.abc import Callable

import pytest

from elke27_lib.outbound import OutboundItem, OutboundPriority, OutboundQueue


@pytest.mark.asyncio
async def test_outbound_queue_throttle() -> None:
    loop = asyncio.get_running_loop()
    sent_times: list[float] = []
    done = asyncio.Event()

    def _send(payload: bytes) -> None:
        del payload

    def _on_sent(ts: float) -> None:
        sent_times.append(ts)
        if len(sent_times) >= 5:
            done.set()

    queue = OutboundQueue(loop=loop, send_fn=_send, min_interval_s=0.05, max_burst=1)
    queue.start()

    for i in range(5):
        queue.enqueue(
            OutboundItem(
                payload=b"x",
                seq=i,
                kind="request",
                priority=OutboundPriority.NORMAL,
                enqueued_at=time.monotonic(),
                on_sent=_on_sent,
            )
        )

    await asyncio.wait_for(done.wait(), timeout=2.0)
    deltas = [b - a for a, b in zip(sent_times, sent_times[1:], strict=False)]
    assert all(delta >= 0.04 for delta in deltas)


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
