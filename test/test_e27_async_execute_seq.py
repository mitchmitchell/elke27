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


@pytest.mark.asyncio
async def test_async_execute_sends_seq_and_resolves() -> None:
    client = Elke27Client()
    kernel = getattr(client, "_kernel")
    fake_session = _FakeSession()
    setattr(kernel, "_session", fake_session)
    kernel.state.panel.session_id = 1

    task = asyncio.create_task(client.async_execute("control_get_version_info"))
    await asyncio.sleep(0)

    assert fake_session.sent
    sent = fake_session.sent[0]
    seq = sent["seq"]
    assert seq > 0

    getattr(kernel, "_on_message")(
        {"seq": seq, "control": {"get_version_info": {"version": "1.0"}}}
    )
    result = await task

    assert result.ok is True
    assert result.data == {"version": "1.0"}
    pending = getattr(kernel, "_pending_responses")
    assert pending.pending_count() == 0


@pytest.mark.asyncio
async def test_async_execute_ignores_broadcast() -> None:
    client = Elke27Client()
    kernel = getattr(client, "_kernel")
    fake_session = _FakeSession()
    setattr(kernel, "_session", fake_session)
    kernel.state.panel.session_id = 1

    task = asyncio.create_task(client.async_execute("control_get_version_info"))
    await asyncio.sleep(0)

    sent = fake_session.sent[0]
    seq = sent["seq"]

    getattr(kernel, "_on_message")(
        {"seq": 0, "control": {"get_version_info": {"version": "ignored"}}}
    )
    await asyncio.sleep(0)
    assert not task.done()

    getattr(kernel, "_on_message")(
        {"seq": seq, "control": {"get_version_info": {"version": "1.1"}}}
    )
    result = await task

    assert result.ok is True
    assert result.data == {"version": "1.1"}
    pending = getattr(kernel, "_pending_responses")
    assert pending.pending_count() == 0


@pytest.mark.asyncio
async def test_async_execute_times_out_and_cleans_pending() -> None:
    client = Elke27Client()
    kernel = getattr(client, "_kernel")
    fake_session = _FakeSession()
    setattr(kernel, "_session", fake_session)
    kernel.state.panel.session_id = 1

    result = await client.async_execute("control_get_version_info", timeout_s=0.01)

    assert result.ok is False
    assert isinstance(result.error, E27Timeout)
    assert "control_get_version_info" in str(result.error)
    pending = getattr(kernel, "_pending_responses")
    assert pending.pending_count() == 0
