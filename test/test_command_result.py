"""Public CommandResult returned by arm, disarm and zone-bypass (0.3.14)."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Iterable

import pytest

import elke27_lib
from elke27_lib import ArmMode, ClientConfig, CommandResult, Elke27Client
from elke27_lib.client import Result
from elke27_lib.errors import Elke27PermissionError, PermissionDeniedError


class _FakePanel:
    connected = True


class _FakeState:
    def __init__(self) -> None:
        self.panel = _FakePanel()


class _FakeKernel:
    def __init__(self) -> None:
        self.state = _FakeState()

    def subscribe(
        self, _callback: Callable[[object], None], _kinds: Iterable[str] | None = None
    ) -> int:
        return 1

    def unsubscribe(self, _token: int) -> bool:
        return True


def _client(refresh: bool | None, *, ok: bool = True) -> tuple[Elke27Client, list[str]]:
    client = Elke27Client(kernel=_FakeKernel(), config=ClientConfig(event_queue_size=1))  # type: ignore[arg-type]
    client._connected = True
    sent: list[str] = []

    async def _execute(command_key: str, **_params: object) -> Result[dict[str, object]]:
        sent.append(command_key)
        if not ok:
            return Result(ok=False, error=PermissionDeniedError("denied"))
        return Result(ok=True, data={}, status_refresh_ok=refresh)

    client.async_execute = _execute  # type: ignore[method-assign]
    return client, sent


def _calls(client: Elke27Client):
    return [
        (
            "area_set_arm_state",
            client.async_arm_area(1, mode=ArmMode.ARMED_AWAY, pin="1234", return_result=True),
        ),
        (
            "area_set_arm_state",
            client.async_arm_area(1, mode=ArmMode.DISARMED, pin="1234", return_result=True),
        ),
        ("area_set_arm_state", client.async_disarm_area(1, pin="1234", return_result=True)),
        (
            "zone_set_status",
            client.async_set_zone_bypass(2, bypassed=True, pin="1234", return_result=True),
        ),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("refresh", "refreshed"),
    [(True, True), (False, False), (None, False)],
    ids=["refreshed", "refresh_failed", "not_needed"],
)
async def test_command_result_carries_refresh_outcome(
    refresh: bool | None, refreshed: bool
) -> None:
    client, _ = _client(refresh)
    for route, coro in _calls(client):
        result = await coro
        assert isinstance(result, CommandResult)
        assert result == CommandResult(route=route, status_refresh_ok=refresh)
        assert result.refreshed is refreshed


@pytest.mark.asyncio
async def test_command_errors_still_raise_public_exceptions() -> None:
    client, _ = _client(True, ok=False)
    for _route, coro in _calls(client):
        with pytest.raises(Elke27PermissionError):
            await coro


@pytest.mark.asyncio
async def test_default_return_is_none_for_backward_compat() -> None:
    client, sent = _client(True)
    assert await client.async_arm_area(1, mode=ArmMode.ARMED_STAY, pin="1234") is None
    assert await client.async_disarm_area(1, pin="1234") is None
    assert await client.async_set_zone_bypass(2, bypassed=False, pin="1234") is None
    assert sent == ["area_set_arm_state", "area_set_arm_state", "zone_set_status"]


def test_command_result_is_frozen_and_exported() -> None:
    assert "CommandResult" in elke27_lib.__all__
    result = CommandResult(route="zone_set_status")
    assert result.status_refresh_ok is None
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.route = "x"  # type: ignore[misc]
