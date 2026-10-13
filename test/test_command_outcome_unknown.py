"""Elke27CommandOutcomeUnknownError: sent but no reply (vs plain timeout before send)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, cast

import pytest

import elke27_lib
from elke27_lib import Elke27CommandOutcomeUnknownError, Elke27TimeoutError
from elke27_lib.client import Elke27Client
from test.helpers.internal import get_kernel, get_private
from test.test_transport_command_retry import _FakeSession, _make_client


class _NeverSentSession(_FakeSession):
    """Accepts frames but never confirms the send (no on_sent)."""

    class _Cfg:
        host = "test"
        port = 0

    cfg = _Cfg()

    def send_json(
        self,
        msg: dict[str, Any],
        *,
        priority: object = None,
        on_sent: Callable[[float], None] | None = None,
        on_fail: Callable[[BaseException], None] | None = None,
    ) -> None:
        self.sent.append(msg)


def test_error_is_public_timeout_subclass_with_route() -> None:
    assert elke27_lib.Elke27CommandOutcomeUnknownError is Elke27CommandOutcomeUnknownError
    assert "Elke27CommandOutcomeUnknownError" in elke27_lib.__all__
    err = Elke27CommandOutcomeUnknownError(("area", "set_arm_state"))
    assert isinstance(err, Elke27TimeoutError)
    assert err.route == ("area", "set_arm_state")
    assert err.is_transient is True
    assert "area.set_arm_state" in str(err)


async def _run(client: Elke27Client, budget_s: float, **kwargs: Any) -> Any:
    cast(Any, client)._command_transport_wait_budget_s = lambda _t: budget_s
    return await asyncio.wait_for(
        client.async_execute("area_set_arm_state", area_id=1, pin=1234, **kwargs), timeout=2.0
    )


@pytest.mark.asyncio
async def test_sent_write_without_reply_is_outcome_unknown() -> None:
    session = _FakeSession()
    client = _make_client(session)
    result = await _run(client, 0.1, arm_state="ARMED_AWAY", timeout_s=0.02)
    assert not result.ok
    assert isinstance(result.error, Elke27CommandOutcomeUnknownError)
    assert result.error.route == ("area", "set_arm_state")
    assert len(session.sent) == 1  # never resent after a confirmed send


@pytest.mark.asyncio
async def test_sent_write_budget_timeout_is_outcome_unknown() -> None:
    """Client-side deadline fires after on_sent but before the kernel reply timeout."""
    session = _FakeSession()
    client = _make_client(session)
    result = await _run(client, 0.05, arm_state="ARMED_AWAY", timeout_s=5.0)
    assert isinstance(result.error, Elke27CommandOutcomeUnknownError)


@pytest.mark.asyncio
async def test_timeout_before_send_stays_plain_timeout() -> None:
    session = _NeverSentSession()
    client = _make_client(session)
    result = await _run(client, 0.05, arm_state="ARMED_AWAY", timeout_s=5.0)
    assert not result.ok
    assert not isinstance(result.error, Elke27CommandOutcomeUnknownError)
    with pytest.raises(Elke27TimeoutError) as exc_info:
        assert result.error is not None
        client._raise_v2_command_error(result.error)
    assert not isinstance(exc_info.value, Elke27CommandOutcomeUnknownError)


@pytest.mark.asyncio
async def test_sent_read_timeout_stays_plain_timeout() -> None:
    session = _FakeSession()
    client = _make_client(session, max_retries=0)
    cast(Any, client)._command_transport_wait_budget_s = lambda _t: 0.05
    result = await client.async_execute("zone_get_status", zone_id=1, timeout_s=5.0)
    assert not result.ok
    assert not isinstance(result.error, Elke27CommandOutcomeUnknownError)


@pytest.mark.asyncio
async def test_cancel_after_confirmed_send_chains_outcome_unknown() -> None:
    session = _FakeSession()
    client = _make_client(session)
    kernel = get_kernel(client)
    task = asyncio.create_task(
        client.async_execute(
            "area_set_arm_state", area_id=1, arm_state="ARMED_AWAY", pin=1234, timeout_s=5.0
        )
    )
    for _ in range(50):
        if session.sent:
            break
        await asyncio.sleep(0)
    await asyncio.sleep(0.01)
    assert session.sent
    task.cancel()
    with pytest.raises(asyncio.CancelledError) as exc_info:
        await task
    assert isinstance(exc_info.value.__cause__, Elke27CommandOutcomeUnknownError)
    assert exc_info.value.__cause__.route == ("area", "set_arm_state")
    assert not cast(Any, kernel)._request_queue_high
    assert not cast(Any, kernel)._request_queue_normal


@pytest.mark.asyncio
async def test_queued_command_failed_by_deadline_stays_plain_timeout() -> None:
    """Kernel sets the sent event when failing a queued (never-sent) command."""
    from elke27_lib.errors import E27Timeout

    session = _NeverSentSession()
    client = _make_client(session)
    kernel = get_kernel(client)
    task = asyncio.create_task(
        client.async_execute(
            "area_set_arm_state", area_id=1, arm_state="ARMED_AWAY", pin=1234, timeout_s=5.0
        )
    )
    for _ in range(50):
        if session.sent:
            break
        await asyncio.sleep(0)
    seq = session.sent[0]["seq"]
    # Same as the kernel's queued-deadline path: fail the future, wake the waiter.
    kernel.pending_responses.fail(seq, E27Timeout(f"Command deadline expired for seq={seq}"))
    get_private(kernel, "_signal_sent_event")(seq)
    result = await asyncio.wait_for(task, timeout=2.0)
    assert not result.ok
    assert not isinstance(result.error, Elke27CommandOutcomeUnknownError)
    with pytest.raises(Elke27TimeoutError) as exc_info:
        assert result.error is not None
        client._raise_v2_command_error(result.error)
    assert type(exc_info.value) is Elke27TimeoutError


@pytest.mark.parametrize(
    ("route", "read_only"),
    [
        (("area", "num_not_rdy_zones"), True),
        (("zone", "pwr_get_trouble"), True),
        (("system", "file_info"), True),
        (("system", "r_u_alive"), True),
        (("area", "get_status"), True),
        (("area", "set_arm_state"), False),
        (("zone", "set_status"), False),
        (("system", "reset_smokes"), False),
        (("output", "refresh_status"), False),
    ],
)
def test_explicit_read_write_classification(route: tuple[str, str], read_only: bool) -> None:
    from elke27_lib.command_kinds import is_read_only_route

    assert is_read_only_route(*route) is read_only


def test_every_registry_get_route_is_classified_read_only() -> None:
    from elke27_lib.command_kinds import READ_ONLY_ROUTES
    from elke27_lib.generators.registry import COMMANDS

    routes = {(s.domain, s.command) for s in COMMANDS.values()}
    missing = {r for r in routes if r[1].startswith("get_") and r not in READ_ONLY_ROUTES}
    assert missing == set()
    assert READ_ONLY_ROUTES <= routes


@pytest.mark.asyncio
async def test_arm_helper_raises_outcome_unknown() -> None:
    from elke27_lib import ArmMode

    session = _FakeSession()
    client = _make_client(session)
    cast(Any, client)._connected = True
    cast(Any, client)._command_transport_wait_budget_s = lambda _t: 0.05
    with pytest.raises(Elke27CommandOutcomeUnknownError) as exc_info:
        await asyncio.wait_for(
            client.async_arm_area(1, mode=ArmMode.ARMED_AWAY, pin="1234"), timeout=2.0
        )
    assert exc_info.value.route == ("area", "set_arm_state")
