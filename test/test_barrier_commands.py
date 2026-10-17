"""Fake-kernel tests for async_set_barrier / async_refresh_barrier and barrier status."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable
from typing import Any, cast

import pytest

from elke27_lib import ClientConfig, Elke27Client
from elke27_lib.client import _SEND_ONCE_COMMANDS, Result
from elke27_lib.const import E27ErrorCode
from elke27_lib.errors import (
    Elke27CommandOutcomeUnknownError,
    Elke27DisconnectedError,
    Elke27InvalidArgument,
    Elke27PanelError,
    Elke27PermissionError,
    PermissionDeniedError,
)
from elke27_lib.kernel import E27Kernel
from elke27_lib.states import BarrierState as KernelBarrierState
from elke27_lib.types import barrier_is_open
from test.helpers.internal import get_kernel, get_private
from test.test_transport_command_retry import _FakeSession, _make_client


class _FakePanel:
    def __init__(self) -> None:
        self.connected = True


class _FakeInventory:
    def __init__(self) -> None:
        self.configured_barriers: set[int] = {1, 2}
        self.configured_barriers_complete = True


class _FakeState:
    def __init__(self) -> None:
        self.panel = _FakePanel()
        self.inventory = _FakeInventory()
        self.barriers: dict[int, KernelBarrierState] = {}


class _FakeKernel:
    def __init__(self) -> None:
        self.state = _FakeState()

    def subscribe(
        self, _callback: Callable[[object], None], _kinds: Iterable[str] | None = None
    ) -> int:
        return 1

    def unsubscribe(self, _token: int) -> bool:
        return True


def _client() -> tuple[Elke27Client, _FakeKernel, list[tuple[str, dict[str, Any]]]]:
    kernel = _FakeKernel()
    client = Elke27Client(kernel=kernel, config=ClientConfig(event_queue_size=1))  # type: ignore[arg-type]
    client._connected = True
    calls: list[tuple[str, dict[str, Any]]] = []
    return client, kernel, calls


def _executor(calls: list[tuple[str, dict[str, Any]]], result: Result[Any]) -> Callable[..., Any]:
    async def _execute(command_key: str, **params: Any) -> Result[Any]:
        calls.append((command_key, dict(params)))
        return result

    return _execute


@pytest.mark.asyncio
@pytest.mark.parametrize(("open_", "status"), [(True, "open"), (False, "close")])
async def test_set_barrier_success_sends_once(open_: bool, status: str) -> None:
    client, _kernel, calls = _client()
    client.async_execute = _executor(calls, Result(ok=True, data={}, error=None))  # type: ignore[method-assign]
    assert await client.async_set_barrier(2, open=open_) is None
    assert calls == [("barrier_set_status", {"barrier_id": 2, "status": status})]


@pytest.mark.asyncio
async def test_set_barrier_refusal_raises_permission_error() -> None:
    client, _kernel, calls = _client()
    client.async_execute = _executor(  # type: ignore[method-assign]
        calls, Result(ok=False, data=None, error=PermissionDeniedError("no"))
    )
    with pytest.raises(Elke27PermissionError):
        await client.async_set_barrier(1, open=True)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_set_barrier_outcome_unknown_is_not_retried() -> None:
    client, _kernel, calls = _client()
    err = Elke27CommandOutcomeUnknownError(("barrier", "set_status"))
    client.async_execute = _executor(calls, Result(ok=False, data=None, error=err))  # type: ignore[method-assign]
    with pytest.raises(Elke27CommandOutcomeUnknownError):
        await client.async_set_barrier(1, open=False)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_set_barrier_disconnected() -> None:
    client, kernel, calls = _client()
    kernel.state.panel.connected = False
    client.async_execute = _executor(calls, Result(ok=True, data={}, error=None))  # type: ignore[method-assign]
    with pytest.raises(Elke27DisconnectedError):
        await client.async_set_barrier(1, open=True)
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("barrier_id", [0, -1, 3, True])
async def test_set_barrier_invalid_or_unconfigured_id(barrier_id: Any) -> None:
    client, _kernel, calls = _client()
    client.async_execute = _executor(calls, Result(ok=True, data={}, error=None))  # type: ignore[method-assign]
    with pytest.raises(Elke27InvalidArgument):
        await client.async_set_barrier(barrier_id, open=True)
    assert calls == []


@pytest.mark.asyncio
async def test_set_barrier_unknown_inventory_allows_send() -> None:
    client, kernel, calls = _client()
    kernel.state.inventory.configured_barriers_complete = False
    client.async_execute = _executor(calls, Result(ok=True, data={}, error=None))  # type: ignore[method-assign]
    await client.async_set_barrier(5, open=True)
    assert len(calls) == 1


def test_barrier_set_status_is_send_once() -> None:
    assert "barrier_set_status" in _SEND_ONCE_COMMANDS
    assert ("barrier", "set_status") in E27Kernel()._disable_retries_for_routes


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("OPEN", True),
        ("open", True),
        ("CLOSE", False),
        ("CLOSED", False),
        ("STOPPED", None),
        ("ON", None),
        ("OFF", None),
        ("weird", None),
        (None, None),
        (1, None),
    ],
)
def test_barrier_status_normalisation(status: object, expected: bool | None) -> None:
    assert barrier_is_open(status) is expected


@pytest.mark.asyncio
async def test_refresh_barrier_reads_once_and_returns_typed_fields() -> None:
    client, kernel, calls = _client()

    async def _execute(command_key: str, **params: Any) -> Result[Any]:
        calls.append((command_key, dict(params)))
        kernel.state.barriers[1] = KernelBarrierState(
            barrier_id=1,
            name="Garage",
            status="CLOSED",
            fields={"tamper": False, "low_batt": 1, "rssi": -60},
        )
        return Result(ok=True, data={}, error=None)

    client.async_execute = _execute  # type: ignore[method-assign]
    state = await client.async_refresh_barrier(1)
    assert calls == [("barrier_get_status", {"barrier_id": 1})]
    assert state is not None
    assert (state.status, state.is_open, state.tamper, state.low_batt, state.rssi) == (
        "CLOSED",
        False,
        False,
        True,
        -60,
    )


@pytest.mark.asyncio
async def test_refresh_barrier_missing_entry_and_errors() -> None:
    client, kernel, calls = _client()
    client.async_execute = _executor(calls, Result(ok=True, data={}, error=None))  # type: ignore[method-assign]
    assert await client.async_refresh_barrier(2) is None
    kernel.state.panel.connected = False
    with pytest.raises(Elke27DisconnectedError):
        await client.async_refresh_barrier(2)
    with pytest.raises(Elke27InvalidArgument):
        await client.async_refresh_barrier(0)


# --- Behavioural send-once tests through the real async_execute path ---


async def _wait_sent(session: Any, count: int, task: asyncio.Task[Any]) -> None:
    for _ in range(50):
        if len(session.sent) >= count or task.done():
            return
        await asyncio.sleep(0)


def _real_client(session: Any) -> Elke27Client:
    client = _make_client(session, max_retries=2)
    inv = get_kernel(client).state.inventory
    inv.configured_barriers = {1}
    inv.configured_barriers_complete = True
    get_kernel(client).state.panel.connected = True
    client._connected = True
    return client


@pytest.mark.asyncio
async def test_real_execute_panel_busy_is_not_resent() -> None:
    session = _FakeSession()
    client = _real_client(session)
    task = asyncio.create_task(client.async_set_barrier(1, open=True))
    await _wait_sent(session, 1, task)
    sent = session.sent[0]
    assert sent["barrier"]["set_status"]["status"] == "open"
    busy = int(E27ErrorCode.ELKERR_ZWAVE_BUSY)
    get_private(get_kernel(client), "_on_message")(
        {"seq": sent["seq"], "barrier": {"set_status": {"barrier_id": 1, "error_code": busy}}}
    )
    with pytest.raises(Elke27PanelError) as exc_info:
        await asyncio.wait_for(task, timeout=2.0)
    assert type(exc_info.value) is Elke27PanelError
    assert exc_info.value.panel_error_code == busy
    for _ in range(20):
        await asyncio.sleep(0)
    assert len(session.sent) == 1


@pytest.mark.asyncio
async def test_real_execute_sent_without_reply_is_outcome_unknown() -> None:
    session = _FakeSession()
    client = _real_client(session)
    cast(Any, client)._command_transport_wait_budget_s = lambda _t: 0.1
    real_execute = client.async_execute

    async def _short_timeout(command_key: str, **params: Any) -> Any:
        return await real_execute(command_key, timeout_s=0.02, **params)

    client.async_execute = _short_timeout  # type: ignore[method-assign]
    with pytest.raises(Elke27CommandOutcomeUnknownError) as exc_info:
        await asyncio.wait_for(client.async_set_barrier(1, open=False), timeout=2.0)
    assert exc_info.value.route == ("barrier", "set_status")
    assert len(session.sent) == 1
    assert session.sent[0]["barrier"]["set_status"]["status"] == "close"
