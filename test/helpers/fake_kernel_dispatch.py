from __future__ import annotations

import contextlib
from collections.abc import Callable
from typing import cast

from elke27_lib.dispatcher_loop import Dispatcher, PendingRequest


class FakeKernelDispatchSupport:
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        if not hasattr(self, "dispatcher"):
            self.dispatcher = Dispatcher()
        self._fake_dispatch_listeners: list[Callable[[int, tuple[str, str], bool], None]] = []

    def add_dispatch_listener(
        self, listener: Callable[[int, tuple[str, str], bool], None]
    ) -> Callable[[], None]:
        self._fake_dispatch_listeners.append(listener)

        def remove() -> None:
            with contextlib.suppress(ValueError):
                self._fake_dispatch_listeners.remove(listener)

        return remove

    def register_dispatch_correlation(
        self, seq: int, expected_route: tuple[str, str] | None
    ) -> None:
        now_fn = getattr(self, "now", None)
        now = float(cast(float, now_fn())) if callable(now_fn) else 0.0
        self.dispatcher.add_pending(
            PendingRequest(
                seq=seq,
                expected_route=expected_route,
                created_at=now,
                opaque=None,
            )
        )

    def drop_dispatch_correlation(self, seq: int) -> None:
        self.dispatcher.drop_pending(seq)
