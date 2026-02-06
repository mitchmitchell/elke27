from __future__ import annotations

import asyncio
import logging

import pytest

from elke27_lib.outbound import OutboundItem, OutboundPriority, OutboundQueue


def test_enqueue_stop_non_running_loop_and_debug() -> None:
    loop = asyncio.new_event_loop()
    try:
        logger = logging.getLogger("test_outbound")
        logger.setLevel(logging.DEBUG)
        sent: list[BaseException] = []

        def _on_fail(exc: BaseException) -> None:
            sent.append(exc)

        queue = OutboundQueue(loop=loop, send_fn=lambda _b: None, logger=logger)
        item = OutboundItem(
            payload=b"x",
            seq=1,
            kind="k",
            priority=OutboundPriority.HIGH,
            enqueued_at=0.0,
            on_fail=_on_fail,
        )
        queue.enqueue(item)
        assert queue.is_idle() is False
        queue.stop(fail_exc=RuntimeError("boom"))
        assert sent
    finally:
        loop.close()


@pytest.mark.asyncio
async def test_wait_idle_timeout_and_throttle_and_next_item() -> None:
    loop = asyncio.get_running_loop()
    queue = OutboundQueue(loop=loop, send_fn=lambda _b: None, min_interval_s=0)
    queue._high_q.put_nowait(
        OutboundItem(
            payload=b"x",
            seq=1,
            kind="k",
            priority=OutboundPriority.HIGH,
            enqueued_at=0.0,
        )
    )
    assert await queue.wait_idle(timeout_s=0.0) is False
    await queue._throttle()

    queue._stop_event.set()
    assert await queue._next_item() is None


@pytest.mark.asyncio
async def test_next_item_high_after_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    loop = asyncio.get_running_loop()
    queue = OutboundQueue(loop=loop, send_fn=lambda _b: None)

    async def _wait_for(coro, *args, **kwargs):  # type: ignore[no-untyped-def]
        coro.close()
        queue._high_q.put_nowait(
            OutboundItem(
                payload=b"x",
                seq=1,
                kind="k",
                priority=OutboundPriority.HIGH,
                enqueued_at=0.0,
            )
        )
        raise TimeoutError

    monkeypatch.setattr(asyncio, "wait_for", _wait_for)
    item = await queue._next_item()
    assert item is not None


@pytest.mark.asyncio
async def test_next_item_timeout_no_high(monkeypatch: pytest.MonkeyPatch) -> None:
    loop = asyncio.get_running_loop()
    queue = OutboundQueue(loop=loop, send_fn=lambda _b: None)

    async def _wait_for(coro, *args, **kwargs):  # type: ignore[no-untyped-def]
        coro.close()
        raise TimeoutError

    monkeypatch.setattr(asyncio, "wait_for", _wait_for)
    item = await queue._next_item()
    assert item is None


@pytest.mark.asyncio
async def test_run_handles_none_item() -> None:
    loop = asyncio.get_running_loop()
    queue = OutboundQueue(loop=loop, send_fn=lambda _b: None)

    async def _next_item():  # type: ignore[no-untyped-def]
        queue._stop_event.set()
        return None

    queue._next_item = _next_item  # type: ignore[assignment]
    await queue._run()


@pytest.mark.asyncio
async def test_run_send_success_and_failure() -> None:
    loop = asyncio.get_running_loop()
    sent: list[str] = []
    failed: list[str] = []

    def _send_ok(_b: bytes) -> None:
        sent.append("ok")

    logger = logging.getLogger("test_outbound_run")
    logger.setLevel(logging.DEBUG)
    queue = OutboundQueue(loop=loop, send_fn=_send_ok, logger=logger)
    queue.start()
    queue._normal_q.put_nowait(
        OutboundItem(
            payload=b"x",
            seq=1,
            kind="k",
            priority=OutboundPriority.NORMAL,
            enqueued_at=0.0,
            on_sent=lambda _t: sent.append("sent"),
        )
    )
    await queue.wait_idle(timeout_s=0.2)
    queue.stop()
    assert sent

    def _send_fail(_b: bytes) -> None:
        raise RuntimeError("boom")

    queue = OutboundQueue(loop=loop, send_fn=_send_fail)
    queue.start()
    queue._normal_q.put_nowait(
        OutboundItem(
            payload=b"x",
            seq=2,
            kind="k",
            priority=OutboundPriority.NORMAL,
            enqueued_at=0.0,
            on_fail=lambda _e: failed.append("fail"),
        )
    )
    await queue.wait_idle(timeout_s=0.2)
    queue.stop()
    assert failed


def test_drain_with_failure_queue_empty() -> None:
    loop = asyncio.new_event_loop()
    try:
        queue = OutboundQueue(loop=loop, send_fn=lambda _b: None)
        queue._drain_with_failure(None)

        queue._normal_q.put_nowait(
            OutboundItem(
                payload=b"x",
                seq=1,
                kind="k",
                priority=OutboundPriority.NORMAL,
                enqueued_at=0.0,
                on_fail=lambda _e: (_ for _ in ()).throw(RuntimeError("fail")),
            )
        )

        class _Queue:
            def empty(self):  # type: ignore[no-untyped-def]
                return False

            def get_nowait(self):  # type: ignore[no-untyped-def]
                raise asyncio.QueueEmpty

        queue._high_q = _Queue()  # type: ignore[assignment]
        queue._drain_with_failure(RuntimeError("boom"))
    finally:
        loop.close()
