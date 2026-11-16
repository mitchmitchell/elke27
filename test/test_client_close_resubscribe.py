from __future__ import annotations

from typing import Any

import pytest

import elke27_lib.kernel_loop as kernel_mod
from elke27_lib.client import Elke27Client


@pytest.mark.asyncio
async def test_async_execute_after_close_skips_kernel_resubscribe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subscribe_calls: list[int] = []
    real_subscribe = kernel_mod.E27Kernel.subscribe

    def tracked_subscribe(self: kernel_mod.E27Kernel, *args: Any, **kwargs: Any) -> int:
        subscribe_calls.append(1)
        return real_subscribe(self, *args, **kwargs)

    monkeypatch.setattr(kernel_mod.E27Kernel, "subscribe", tracked_subscribe)
    client = Elke27Client()
    await client.close()
    subscribe_calls.clear()
    await client.async_execute("area_get_status", area_id=1, timeout_s=0.1)
    assert subscribe_calls == []