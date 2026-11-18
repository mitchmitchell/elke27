from __future__ import annotations

import contextlib
from collections.abc import Callable

from elke27_lib.dispatcher_loop import Dispatcher, PendingRequest


class FakeKernelDispatchSupport:
    dispatcher: Dispatcher
    _fake_dispatch_listeners: list[Callable[[int, tuple[str, str], bool], None]]

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.dispatcher = Dispatcher()
        self._fake_dispatch_listeners = []

    def now(self) -> float:
        return 0.0

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
        self.dispatcher.add_pending(
            PendingRequest(
                seq=seq,
                expected_route=expected_route,
                created_at=self.now(),
                opaque=None,
            )
        )

    def drop_dispatch_correlation(self, seq: int) -> None:
        self.dispatcher.drop_pending(seq)
