from collections.abc import Callable
from typing import cast

import pytest

from elke27_lib import session as session_mod
from elke27_lib.kernel import E27Kernel


class _FakeSession:
    def __init__(self) -> None:
        self.info: object = type("_Info", (), {"session_id": 1})()

    def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_explicit_close_suppresses_io_disconnect():
    kernel = E27Kernel()
    setattr(kernel, "_session", _FakeSession())
    events: list[tuple[bool, str | None, object | None]] = []

    def _emit_connection_state(
        *, connected: bool, reason: str | None = None, error_type: object | None = None
    ) -> None:
        events.append((connected, reason, error_type))

    setattr(kernel, "_emit_connection_state", _emit_connection_state)

    await kernel.close()
    assert events == [(False, "closed", None)]

    on_session_disconnected = cast(
        Callable[[Exception], None], getattr(kernel, "_on_session_disconnected")
    )
    on_session_disconnected(session_mod.SessionIOError("bad fd"))
    assert events == [(False, "closed", None)]
