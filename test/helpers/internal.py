from __future__ import annotations

import asyncio
import contextlib
import gc
import logging
import types
from typing import Any

from elke27_lib.client import Elke27Client
from test.helpers.fake_session import FakePanelSession


def get_private(obj: object, name: str) -> Any:
    return getattr(obj, name)


def set_private(obj: object, name: str, value: Any) -> None:
    setattr(obj, name, value)


def get_kernel(client: object) -> Any:
    return get_private(client, "_kernel")


def deliver_panel_message(kernel: object, msg: dict[str, object]) -> None:
    get_private(kernel, "_on_message")(msg)


def trigger_session_disconnect(kernel: Any, err: Exception) -> None:
    get_private(kernel, "_on_session_disconnected")(err)


def reply_publication_seq_active(client: object, seq: int) -> bool:
    return seq in get_private(client, "_reply_publication_by_seq")


def reply_publication_pending(client: object, seq: int) -> bool:
    fut = get_private(client, "_reply_publication_by_seq").get(seq)
    return fut is not None and not fut.done()


def unretrieved_future_errors(records: list[logging.LogRecord]) -> list[str]:
    gc.collect()
    return [r.getMessage() for r in records if "never retrieved" in r.getMessage()]


async def time_out_command(client: Any, command_key: str) -> Any:
    kernel = get_kernel(client)
    kernel.command_transport_wait_budget_s = lambda _timeout_s: 0.01
    return await client.async_execute(command_key, timeout_s=5.0)


async def close_while_keepalive_probe_waits_to_send(client: object) -> None:
    kernel = get_kernel(client)
    kernel._keepalive_enabled = True
    kernel._loop = asyncio.get_running_loop()
    queued: list[int] = []

    def _hold_in_outbound_queue(seq: int, *_args: Any, **_kwargs: Any) -> int:
        queued.append(seq)
        return seq

    kernel._send_request_with_seq = _hold_in_outbound_queue
    probe = asyncio.ensure_future(kernel._send_keepalive_request(force=True))
    while not queued:
        await asyncio.sleep(0)
    await asyncio.sleep(0)
    kernel._keepalive_task = probe
    await kernel.close()
    with contextlib.suppress(asyncio.CancelledError):
        await probe


def release_reply_publication_failed_by_disconnect(
    client: object, reply_seq: int, exc: BaseException
) -> None:
    get_private(client, "_begin_reply_publication_command")(
        reply_seq, ("area", "set_arm_state"), asyncio.get_running_loop()
    )
    get_private(client, "_fail_all_reply_publication_waiters")(exc)
    get_private(client, "_release_reply_publication_command")(reply_seq)


def client_with_fake_session() -> Elke27Client:
    client = Elke27Client()
    kernel = get_kernel(client)
    kernel.load_features_blocking()
    kernel._session = FakePanelSession(
        types.SimpleNamespace(host="panel.invalid", port=2101), None, "00"
    )
    kernel.state.panel.session_id = 1
    return client
