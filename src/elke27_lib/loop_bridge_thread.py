"""Block a sync caller until a synchronous callable finishes on a running event loop."""

from __future__ import annotations

import asyncio
import concurrent.futures
import threading
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


class LoopHopTimeout(Exception):
    """Raised when the hop ended before fn() ran."""


class LoopHopClosed(Exception):
    """Raised when the event loop could not accept a thread-safe coroutine submission."""


def run_on_loop(
    loop: asyncio.AbstractEventLoop,
    fn: Callable[[], T],
    *,
    timeout_s: float,
    gate: concurrent.futures.Future[None] | None = None,
    schedule: Callable[[Callable[[], None]], None] | None = None,
) -> T:
    """Return fn()'s result when it ran; raise LoopHopTimeout when fn() did not run."""
    claim = gate if gate is not None else concurrent.futures.Future()
    finished = threading.Event()
    outcome: list[T] = []
    errors: list[BaseException] = []

    def _invoke() -> None:
        if not claim.set_running_or_notify_cancel():
            finished.set()
            return
        try:
            outcome.append(fn())
        except Exception as err:  # noqa: BLE001 -- forward any callback error to the caller
            errors.append(err)
        finally:
            finished.set()

    submit = schedule if schedule is not None else loop.call_soon_threadsafe
    try:
        submit(_invoke)
    except RuntimeError as exc:
        raise LoopHopClosed from exc

    if not finished.wait(timeout=timeout_s):
        if claim.cancel():
            raise LoopHopTimeout from None
    while not finished.is_set():
        finished.wait(timeout=timeout_s)
    if errors:
        raise errors[0]
    if not outcome:
        raise LoopHopTimeout from None
    return outcome[0]
