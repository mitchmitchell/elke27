"""Test helpers for arm-night / Stay Instant (simulator paths)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any, cast

from elke27_lib import session_thread as session_mod
from elke27_lib.client import Elke27Client
from test.helpers.fake_panel_replies import synthetic_success_reply
from test.helpers.internal import get_kernel, get_private


class _FakeSessionCfg:
    host = "127.0.0.1"
    port = 2101


class _FakeSession:
    state = session_mod.SessionState.ACTIVE
    cfg = _FakeSessionCfg()

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


def _make_client() -> tuple[Elke27Client, _FakeSession]:
    client = Elke27Client()
    kernel = get_kernel(client)
    kernel.load_features_blocking()
    session = _FakeSession()
    cast(Any, kernel)._session = session
    kernel.state.panel.session_id = 1
    return client, session


def make_client_with_firmware(
    firmware: str, *, arm_state: str = "DISARMED"
) -> tuple[Elke27Client, _FakeSession]:
    client, session = _make_client()
    kernel = get_kernel(client)
    kernel.state.panel.firmware = firmware
    kernel.state.get_or_create_area(1).arm_state = arm_state
    return client, session


async def drive_until_done(
    client: Elke27Client,
    session: _FakeSession,
    call: Coroutine[Any, Any, Any],
    *,
    custom_replies: dict[int, dict[str, Any]] | None = None,
) -> Any:
    on_message = get_private(get_kernel(client), "_on_message")
    client._event_loop = asyncio.get_running_loop()
    task = asyncio.create_task(call)
    seen = 0
    while not task.done():
        await asyncio.sleep(0)
        while seen < len(session.sent):
            sent = session.sent[seen]
            if custom_replies is not None and seen in custom_replies:
                reply = dict(custom_replies[seen])
                reply["seq"] = sent["seq"]
                on_message(reply)
            else:
                on_message(synthetic_success_reply(sent, sent_history=session.sent[:seen]))
            seen += 1
    return await task
