from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import cast

import pytest

from elke27_lib.client import Elke27Client


@pytest.mark.live_e27
@pytest.mark.asyncio
async def test_live_system_r_u_alive(live_e27_client: Elke27Client) -> None:
    kernel = getattr(live_e27_client, "_kernel")
    stop_keepalive = cast(Callable[[], None], getattr(kernel, "_stop_keepalive"))
    stop_keepalive()
    setattr(kernel, "_keepalive_interval_s", 1.0)
    setattr(kernel, "_keepalive_timeout_s", 2.0)
    setattr(kernel, "_keepalive_max_missed", 2)
    setattr(kernel, "_keepalive_enabled", True)

    fired = asyncio.Event()
    result_box: dict[str, bool] = {}
    original = cast(
        Callable[[], Awaitable[bool]], getattr(kernel, "_send_keepalive_request")
    )

    async def _wrapped_keepalive() -> bool:
        ok = await original()
        result_box["ok"] = ok
        fired.set()
        return ok

    setattr(kernel, "_send_keepalive_request", _wrapped_keepalive)
    start_keepalive = cast(Callable[[], None], getattr(kernel, "_start_keepalive"))
    start_keepalive()

    await asyncio.wait_for(fired.wait(), timeout=10.0)
    assert result_box.get("ok") is True
