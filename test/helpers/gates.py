"""Gated waits for tests: wait for the signal that proves a step happened, not for time.

``devtools/sleepcheck.py`` counts ``asyncio.sleep(0)`` yields, ``range()`` loops that
await ``asyncio.sleep``, ``time.sleep`` and wall-clock asserts in tests. These helpers
are the supported replacement: the fake (or a public hook) sets an event or resolves
a future at the step, and the test waits on it with a bound, so a missing step fails
fast with a name instead of passing or flaking by timing. Drive timeouts with an
injected clock (``KeepaliveTestHooks``) rather than a real delay.
"""

from __future__ import annotations

import asyncio
import threading
from typing import TypeVar

T = TypeVar("T")

DEFAULT_TIMEOUT_S = 5.0


async def wait_event(event: asyncio.Event, what: str, timeout_s: float = DEFAULT_TIMEOUT_S) -> None:
    """Wait until ``event`` is set; fail naming ``what`` if it is not within the bound."""
    try:
        async with asyncio.timeout(timeout_s):
            await event.wait()
    except TimeoutError:
        raise AssertionError(f"{what} did not happen within {timeout_s}s") from None


async def wait_future(
    future: asyncio.Future[T], what: str, timeout_s: float = DEFAULT_TIMEOUT_S
) -> T:
    """Wait for ``future`` without cancelling it; fail naming ``what`` on the bound."""
    try:
        async with asyncio.timeout(timeout_s):
            return await asyncio.shield(future)
    except TimeoutError:
        raise AssertionError(f"{what} did not resolve within {timeout_s}s") from None


def wait_thread_event(
    event: threading.Event, what: str, timeout_s: float = DEFAULT_TIMEOUT_S
) -> None:
    """Block until a ``threading.Event`` is set; fail naming ``what`` on the bound."""
    if not event.wait(timeout_s):
        raise AssertionError(f"{what} did not happen within {timeout_s}s")


class Checkpoint:
    """A two-sided gate a fake awaits at one step.

    The fake calls ``await checkpoint.arrive()``; the test awaits
    ``checkpoint.wait_reached()`` to know the step happened, acts, then calls
    ``checkpoint.release()`` to let the fake continue. Nothing depends on how many
    times the loop ran in between.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self._reached = asyncio.Event()
        self._released = asyncio.Event()
        self.arrivals = 0

    async def arrive(self) -> None:
        """Mark the step reached, then wait until the test releases it."""
        self.arrivals += 1
        self._reached.set()
        await self._released.wait()

    async def wait_reached(self, timeout_s: float = DEFAULT_TIMEOUT_S) -> None:
        """Wait until the fake has arrived at least once."""
        await wait_event(self._reached, f"checkpoint {self.name!r}", timeout_s)

    def release(self) -> None:
        """Let every current and later ``arrive()`` continue."""
        self._released.set()

    @property
    def reached(self) -> bool:
        """True once the fake has arrived."""
        return self._reached.is_set()
