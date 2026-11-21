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
    """Raised when the event loop could not accept a thread-safe callback submission."""


def _new_claim() -> concurrent.futures.Future[None]:
    return concurrent.futures.Future()


def _new_finished() -> threading.Event:
    return threading.Event()


def run_on_loop(
    loop: asyncio.AbstractEventLoop,
    fn: Callable[[], T],
    *,
    timeout_s: float,
    schedule: Callable[[Callable[[], None]], None] | None = None,
) -> T:
    """Return fn()'s result when it ran; raise LoopHopTimeout when fn() did not run."""
    claim = _new_claim()
    finished = _new_finished()
    outcome: list[T] = []
    errors: list[BaseException] = []

    def _invoke() -> None:
        try:
            if not claim.set_running_or_notify_cancel():
                return
            outcome.append(fn())
        except Exception as err:
            errors.append(err)
            raise
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
        finished.wait()
    if errors:
        raise errors[0]
    if not outcome:
        raise LoopHopTimeout from None
    return outcome[0]
