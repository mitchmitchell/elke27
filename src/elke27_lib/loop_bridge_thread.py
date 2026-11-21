"""Block a sync caller until a coroutine finishes on a running event loop."""

from __future__ import annotations

import asyncio
import concurrent.futures
from collections.abc import Coroutine
from typing import Any, TypeVar

T = TypeVar("T")


class LoopHopTimeout(Exception):
    """The wait ended and the hop was cancelled before the coroutine could start."""


def run_coroutine_on_loop(
    loop: asyncio.AbstractEventLoop,
    coro: Coroutine[Any, Any, T],
    *,
    timeout_s: float,
) -> T:
    hop = asyncio.run_coroutine_threadsafe(coro, loop)
    try:
        return hop.result(timeout=timeout_s)
    except concurrent.futures.CancelledError:
        raise
    except (TimeoutError, concurrent.futures.TimeoutError):
        if hop.cancel():
            raise LoopHopTimeout from None
        return hop.result()
