"""An asyncio loop whose cross-thread callbacks lag behind its timers (#149).

The stock selector loop queues ``call_soon_threadsafe`` callbacks ahead of timers
that come due while the loop is blocked, so a reply that reached the receive
thread during a stall is processed before the reply timeout fires, and before the
keepalive check that timeout wakes. Other loops (libuv-based ones such as uvloop
run due timers and their ready work before I/O wakeups), or a loop with a deep
backlog, can deliver the reply after that check instead. This loop forces the
late order with public API only: once the loop wakes, each callback handed over
from another thread is rescheduled ``HANDOFF_LAG_S`` later, after the due timers
and everything they set off have run. Calls made on the loop's own thread keep
the stock behaviour.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from contextvars import Context
from typing import TypeVarTuple

_Ts = TypeVarTuple("_Ts")

HANDOFF_LAG_S = 0.05


class TimersFirstEventLoop(asyncio.SelectorEventLoop):
    def __init__(self) -> None:
        super().__init__()
        self.loop_thread_id: int | None = None

    def run_forever(self) -> None:
        self.loop_thread_id = threading.get_ident()
        super().run_forever()

    def call_soon_threadsafe(
        self,
        callback: Callable[[*_Ts], object],
        *args: *_Ts,
        context: Context | None = None,
    ) -> asyncio.Handle:
        if threading.get_ident() == self.loop_thread_id:
            return super().call_soon_threadsafe(callback, *args, context=context)

        def _after_due_timers() -> None:
            self.call_later(HANDOFF_LAG_S, callback, *args, context=context)

        return super().call_soon_threadsafe(_after_due_timers)
