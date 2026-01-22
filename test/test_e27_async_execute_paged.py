from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import pytest

from elke27_lib.client import Elke27Client
from elke27_lib.errors import E27Timeout


class _FakeSession:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    def send_json(
        self,
        msg: dict[str, Any],
        *,
        priority: object = None,
        on_sent: Callable[[float], None] | None = None,
        on_fail: Callable[[BaseException], None] | None = None,
    ) -> None:
        del priority, on_fail
        self.sent.append(msg)
        if on_sent is not None:
            on_sent(0.0)


async def _wait_for_sent(session: _FakeSession, count: int, *, timeout_s: float = 0.1) -> None:
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout_s
    while len(session.sent) < count and loop.time() < end:
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_async_execute_paged_blocks_merges() -> None:
    client = Elke27Client()
    kernel = getattr(client, "_kernel")
    fake_session = _FakeSession()
    setattr(kernel, "_session", fake_session)
    kernel.state.panel.session_id = 1

    task = asyncio.create_task(client.async_execute("zone_get_configured"))
    await asyncio.sleep(0)

    sent1 = fake_session.sent[0]
    seq1 = sent1["seq"]
    assert sent1["zone"]["get_configured"]["block_id"] == 1

    getattr(kernel, "_on_message")(
        {
            "seq": seq1,
            "zone": {"get_configured": {"block_id": 1, "block_count": 3, "zones": [1, 2]}},
        }
    )
    await _wait_for_sent(fake_session, 2)

    sent2 = fake_session.sent[1]
    seq2 = sent2["seq"]
    assert sent2["zone"]["get_configured"]["block_id"] == 2

    getattr(kernel, "_on_message")(
        {
            "seq": seq2,
            "zone": {"get_configured": {"block_id": 2, "block_count": 3, "zones": [3]}},
        }
    )
    await _wait_for_sent(fake_session, 3)

    sent3 = fake_session.sent[2]
    seq3 = sent3["seq"]
    assert sent3["zone"]["get_configured"]["block_id"] == 3

    getattr(kernel, "_on_message")(
        {
            "seq": seq3,
            "zone": {"get_configured": {"block_id": 3, "block_count": 3, "zones": [4, 5]}},
        }
    )

    result = await task
    assert result.ok is True
    assert result.data == {"zones": [1, 2, 3, 4, 5], "block_count": 3}
    pending = getattr(kernel, "_pending_responses")
    assert pending.pending_count() == 0


@pytest.mark.asyncio
async def test_async_execute_paged_timeout_on_block() -> None:
    client = Elke27Client()
    kernel = getattr(client, "_kernel")
    fake_session = _FakeSession()
    setattr(kernel, "_session", fake_session)
    kernel.state.panel.session_id = 1

    task = asyncio.create_task(client.async_execute("zone_get_configured", timeout_s=0.01))
    await asyncio.sleep(0)

    sent1 = fake_session.sent[0]
    seq1 = sent1["seq"]

    getattr(kernel, "_on_message")(
        {
            "seq": seq1,
            "zone": {"get_configured": {"block_id": 1, "block_count": 2, "zones": [1]}},
        }
    )

    result = await task
    assert result.ok is False
    assert isinstance(result.error, E27Timeout)
    pending = getattr(kernel, "_pending_responses")
    assert pending.pending_count() == 0
