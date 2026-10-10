"""Transport retry policy for kernel requests and async_execute (issue #12)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, cast

import pytest

from elke27_lib import Elke27PanelError
from elke27_lib.client import Elke27Client
from elke27_lib.const import E27ErrorCode
from elke27_lib.errors import ConnectionLost, E27Timeout
from elke27_lib.kernel import E27Kernel
from elke27_lib.outbound import OutboundPriority
from test.helpers.internal import get_kernel, get_private


class _FakeSession:
    def __init__(self, *, fail_send_count: int = 0) -> None:
        self.sent: list[dict[str, Any]] = []
        self._fail_send_count = fail_send_count
        self._send_calls = 0

    def send_json(
        self,
        msg: dict[str, Any],
        *,
        priority: object = None,
        on_sent: Callable[[float], None] | None = None,
        on_fail: Callable[[BaseException], None] | None = None,
    ) -> None:
        self._send_calls += 1
        if self._fail_send_count > 0:
            self._fail_send_count -= 1
            if on_fail is not None:
                on_fail(RuntimeError("send failed"))
            return
        self.sent.append(msg)
        if on_sent is not None:
            on_sent(0.0)


def _wire_kernel(kernel: E27Kernel, session: _FakeSession, *, max_retries: int = 2) -> None:
    kernel_any = cast(Any, kernel)
    kernel_any._session = session
    kernel_any._request_max_retries = max_retries
    kernel_any._loop = asyncio.get_running_loop()


@pytest.mark.asyncio
async def test_kernel_timeout_then_success_retries_same_seq() -> None:
    kernel = E27Kernel(request_timeout_s=0.02, request_max_retries=2, request_max_backoff_s=0.0)
    session = _FakeSession()
    _wire_kernel(kernel, session)

    seq = 50
    future = kernel.pending_responses.create(
        seq,
        command_key="zone_get_status",
        expected_route=("zone", "get_status"),
        loop=asyncio.get_running_loop(),
    )
    kernel.send_request_with_seq(
        seq,
        "zone",
        "get_status",
        {"zone_id": 1},
        pending=False,
        opaque=None,
        expected_route=("zone", "get_status"),
        timeout_s=0.02,
    )
    await asyncio.sleep(0)
    assert len(session.sent) == 1

    on_reply_timeout = get_private(kernel, "_on_reply_timeout")
    on_reply_timeout(seq)
    await asyncio.sleep(0)
    assert len(session.sent) == 2
    assert session.sent[0]["seq"] == session.sent[1]["seq"] == seq

    on_message = get_private(kernel, "_on_message")
    on_message({"seq": seq, "zone": {"get_status": {"zone_id": 1, "status": "OK"}}})
    msg = await asyncio.wait_for(future, timeout=0.2)
    assert msg["seq"] == seq


@pytest.mark.asyncio
async def test_kernel_exhausted_timeouts_fail_once() -> None:
    kernel = E27Kernel(request_timeout_s=0.02, request_max_retries=1, request_max_backoff_s=0.0)
    session = _FakeSession()
    _wire_kernel(kernel, session, max_retries=1)

    seq = 51
    future = kernel.pending_responses.create(
        seq,
        command_key="zone_get_status",
        expected_route=("zone", "get_status"),
        loop=asyncio.get_running_loop(),
    )
    kernel.send_request_with_seq(
        seq,
        "zone",
        "get_status",
        {"zone_id": 1},
        pending=False,
        opaque=None,
        expected_route=("zone", "get_status"),
        timeout_s=0.02,
    )
    await asyncio.sleep(0)
    on_reply_timeout = get_private(kernel, "_on_reply_timeout")
    on_reply_timeout(seq)
    await asyncio.sleep(0)
    on_reply_timeout(seq)
    with pytest.raises(E27Timeout):
        await asyncio.wait_for(future, timeout=0.2)
    assert len(session.sent) == 2


@pytest.mark.asyncio
async def test_kernel_arm_not_retried_after_sent_timeout() -> None:
    kernel = E27Kernel(request_timeout_s=0.02, request_max_retries=2, request_max_backoff_s=0.0)
    session = _FakeSession()
    _wire_kernel(kernel, session)

    seq = 52
    future = kernel.pending_responses.create(
        seq,
        command_key="area_set_arm_state",
        expected_route=("area", "set_arm_state"),
        loop=asyncio.get_running_loop(),
    )
    kernel.send_request_with_seq(
        seq,
        "area",
        "set_arm_state",
        {"area_id": 1, "arm_state": "ARMED_AWAY", "pin": 1234},
        pending=False,
        opaque=None,
        expected_route=("area", "set_arm_state"),
        timeout_s=0.02,
    )
    await asyncio.sleep(0)
    on_reply_timeout = get_private(kernel, "_on_reply_timeout")
    on_reply_timeout(seq)
    with pytest.raises(E27Timeout):
        await asyncio.wait_for(future, timeout=0.2)
    assert len(session.sent) == 1


@pytest.mark.asyncio
async def test_kernel_disarm_retried_immediately_without_backoff() -> None:
    kernel = E27Kernel(request_timeout_s=0.02, request_max_retries=2, request_max_backoff_s=30.0)
    session = _FakeSession()
    _wire_kernel(kernel, session)

    seq = 53
    loop = asyncio.get_running_loop()
    future = kernel.pending_responses.create(
        seq,
        command_key="area_set_arm_state",
        expected_route=("area", "set_arm_state"),
        loop=loop,
    )
    kernel.send_request_with_seq(
        seq,
        "area",
        "set_arm_state",
        {"area_id": 1, "arm_state": "DISARMED", "pin": 1234},
        pending=False,
        opaque=None,
        expected_route=("area", "set_arm_state"),
        timeout_s=0.02,
    )
    await asyncio.sleep(0)
    assert session.sent[0]["area"]["set_arm_state"]["arm_state"] == "DISARMED"

    on_reply_timeout = get_private(kernel, "_on_reply_timeout")
    on_reply_timeout(seq)
    await asyncio.sleep(0)
    assert len(session.sent) == 2
    assert not cast(Any, kernel)._transport_retry_timers

    cancel_active_timeout = get_private(kernel, "_cancel_active_timeout")
    cancel_active_timeout()
    on_message = get_private(kernel, "_on_message")
    on_message({"seq": seq, "area": {"set_arm_state": {"area_id": 1, "error_code": 0}}})
    await asyncio.wait_for(future, timeout=0.2)


@pytest.mark.asyncio
async def test_kernel_connection_lost_retries_unsent_queue() -> None:
    kernel = E27Kernel(request_timeout_s=0.5, request_max_retries=1, request_max_backoff_s=0.0)
    session = _FakeSession()
    _wire_kernel(kernel, session, max_retries=1)

    seq1 = 60
    seq2 = 61
    kernel.pending_responses.create(
        seq1,
        command_key="a",
        expected_route=("zone", "get_status"),
        loop=asyncio.get_running_loop(),
    )
    kernel.pending_responses.create(
        seq2,
        command_key="b",
        expected_route=("zone", "get_status"),
        loop=asyncio.get_running_loop(),
    )
    kernel.send_request_with_seq(
        seq1,
        "zone",
        "get_status",
        {"zone_id": 1},
        pending=False,
        opaque=None,
        expected_route=("zone", "get_status"),
    )
    kernel.send_request_with_seq(
        seq2,
        "zone",
        "get_status",
        {"zone_id": 2},
        pending=False,
        opaque=None,
        expected_route=("zone", "get_status"),
    )
    await asyncio.sleep(0)
    assert len(session.sent) == 1

    abort_requests = get_private(kernel, "_abort_requests")
    abort_requests(ConnectionLost("Session disconnected."))
    await asyncio.sleep(0)
    assert len(session.sent) == 2


def _make_client(session: _FakeSession, *, max_retries: int = 2) -> Elke27Client:
    client = Elke27Client()
    kernel = get_kernel(client)
    cast(Any, kernel)._session = session
    kernel.state.panel.session_id = 1
    cast(Any, kernel)._request_max_retries = max_retries
    cast(Any, kernel)._request_max_backoff_s = 0.0
    cast(Any, kernel)._loop = asyncio.get_running_loop()
    return client


@pytest.mark.asyncio
async def test_async_execute_panel_refusal_single_send() -> None:
    session = _FakeSession()
    client = _make_client(session, max_retries=2)

    task = asyncio.create_task(
        client.async_execute("area_set_arm_state", area_id=1, arm_state="ARMED_AWAY", pin=1234)
    )
    for _ in range(20):
        if session.sent or task.done():
            break
        await asyncio.sleep(0)
    sent = session.sent[0]
    on_message = get_private(get_kernel(client), "_on_message")
    on_message(
        {
            "seq": sent["seq"],
            "area": {
                "set_arm_state": {"area_id": 1, "error_code": int(E27ErrorCode.ELKERR_NOT_READY)}
            },
        }
    )
    result = await task
    assert not result.ok
    assert isinstance(result.error, Elke27PanelError)
    assert result.error.panel_error_code == int(E27ErrorCode.ELKERR_NOT_READY)
    assert len(session.sent) == 1


@pytest.mark.asyncio
async def test_async_execute_panel_busy_then_success() -> None:
    session = _FakeSession()
    client = _make_client(session, max_retries=2)

    task = asyncio.create_task(client.async_execute("zone_get_status", zone_id=1))
    busy_code = int(E27ErrorCode.ELKERR_ZWAVE_BUSY)
    for attempt in range(2):
        for _ in range(20):
            if len(session.sent) > attempt or task.done():
                break
            await asyncio.sleep(0)
        sent = session.sent[attempt]
        on_message = get_private(get_kernel(client), "_on_message")
        if attempt == 0:
            on_message(
                {
                    "seq": sent["seq"],
                    "zone": {"get_status": {"zone_id": 1, "error_code": busy_code}},
                }
            )
        else:
            on_message({"seq": sent["seq"], "zone": {"get_status": {"zone_id": 1, "status": "OK"}}})

    result = await task
    assert result.ok
    assert len(session.sent) == 2


@pytest.mark.asyncio
async def test_disarm_uses_high_priority() -> None:
    session = _FakeSession()
    client = _make_client(session)
    priorities: list[object] = []
    original_send = session.send_json

    def _send_json(
        msg: dict[str, Any],
        *,
        priority: object = None,
        on_sent: Callable[[float], None] | None = None,
        on_fail: Callable[[BaseException], None] | None = None,
    ) -> None:
        priorities.append(priority)
        original_send(msg, priority=priority, on_sent=on_sent, on_fail=on_fail)

    cast(Any, get_kernel(client)._session).send_json = _send_json

    task = asyncio.create_task(
        client.async_execute("area_set_arm_state", area_id=1, arm_state="DISARMED", pin=1234)
    )
    for _ in range(20):
        if session.sent or task.done():
            break
        await asyncio.sleep(0)
    sent = session.sent[0]
    on_message = get_private(get_kernel(client), "_on_message")
    on_message({"seq": sent["seq"], "area": {"set_arm_state": {"area_id": 1, "error_code": 0}}})
    result = await task
    assert result.ok
    assert priorities == [OutboundPriority.HIGH]
