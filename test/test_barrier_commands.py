"""Fake-kernel tests for async_set_barrier / async_refresh_barrier and barrier status."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

import pytest

from elke27_lib import ClientConfig, Elke27Client
from elke27_lib.client import _SEND_ONCE_COMMANDS, Result
from elke27_lib.errors import (
    Elke27CommandOutcomeUnknownError,
    Elke27DisconnectedError,
    Elke27InvalidArgument,
    Elke27PermissionError,
    PermissionDeniedError,
)
from elke27_lib.kernel import E27Kernel
from elke27_lib.states import BarrierState as KernelBarrierState
from elke27_lib.types import barrier_is_open


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
@pytest.mark.parametrize(("open_", "status"), [(True, "OPEN"), (False, "CLOSE")])
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
