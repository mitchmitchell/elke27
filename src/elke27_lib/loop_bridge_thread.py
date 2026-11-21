"""Block a sync caller until a coroutine finishes on a running event loop."""

from __future__ import annotations

import asyncio
import concurrent.futures
import threading
from collections.abc import Coroutine
from typing import Any, TypeVar

T = TypeVar("T")


class LoopHopTimeout(Exception):
    """Raised when the hop deadline passed before the coroutine was abandoned and cancelled."""


class LoopHopClosed(Exception):
    """Raised when the event loop could not accept a thread-safe coroutine submission."""


def _hop_result_after_abandon(hop: concurrent.futures.Future[T]) -> T:
    try:
        return hop.result()
    except concurrent.futures.CancelledError:
        raise LoopHopTimeout from None


def run_coroutine_on_loop(
    loop: asyncio.AbstractEventLoop,
    coro: Coroutine[Any, Any, T],
    *,
    timeout_s: float,
    started: threading.Event,
    abandoned: threading.Event,
) -> T:
    """On timeout, abandon and cancel only if the coroutine never claimed the hop; else wait for its result."""
    try:
        hop = asyncio.run_coroutine_threadsafe(coro, loop)
    except RuntimeError as exc:
        raise LoopHopClosed from exc

    try:
        return hop.result(timeout=timeout_s)
    except TimeoutError:
        abandoned.set()
        if started.is_set():
            return _hop_result_after_abandon(hop)
        if hop.cancel():
            raise LoopHopTimeout from None
        if started.is_set():
            return _hop_result_after_abandon(hop)
        raise LoopHopTimeout from None
