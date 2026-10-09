"""Light status handling (elke27#7): no stale state from acks, on derived from level."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, cast

import pytest

from elke27_lib.client import Elke27Client
from elke27_lib.dispatcher import DispatchContext
from elke27_lib.events import LightStatusUpdated
from elke27_lib.handlers import light as light_handler
from elke27_lib.states import PanelState
from test.helpers.dispatch import make_ctx
from test.helpers.internal import get_kernel, get_private


class _EmitSpy:
    def __init__(self) -> None:
        self.events: list[object] = []

    def __call__(self, evt: object, _ctx: DispatchContext) -> None:
        self.events.append(evt)


def _handlers() -> tuple[PanelState, _EmitSpy, Any, Any]:
    state = PanelState()
    emit = _EmitSpy()
    get_status = light_handler.make_light_get_status_handler(state, emit, now=lambda: 1.0)
    set_status = light_handler.make_light_set_status_handler(state, emit, now=lambda: 2.0)
    return state, emit, get_status, set_status


def test_set_status_ack_without_state_emits_nothing() -> None:
    """Hardware: set_status replies with only light_id/error_code."""
    state, emit, get_status, set_status = _handlers()
    get_status({"light": {"get_status": {"light_id": 1, "level": 100}}}, make_ctx())
    emit.events.clear()

    ack = {"light": {"set_status": {"light_id": 1, "error_code": 0}}}
    assert set_status(ack, make_ctx()) is True
    assert emit.events == []
    assert state.lights[1].level == 100
    assert state.lights[1].on is True


@pytest.mark.parametrize(
    ("level", "on"),
    [(0, False), (50, True), (100, True)],
)
def test_get_status_level_only_derives_on(level: int, on: bool) -> None:
    """Hardware: get_status has level and rssi but no status field."""
    state, emit, get_status, _set = _handlers()
    payload = {"light_id": 1, "level": level, "rssi": 4, "error_code": 0}
    assert get_status({"light": {"get_status": payload}}, make_ctx()) is True
    light = state.lights[1]
    assert light.on is on
    assert light.level == level
    assert light.status == ("ON" if on else "OFF")
    assert light.fields["rssi"] == 4
    evt = cast(LightStatusUpdated, emit.events[-1])
    assert evt.on is on
    assert evt.level == level


def test_level_change_turns_light_off_after_on() -> None:
    """A later level 0 turns a light that was on off (no sticky on)."""
    state, _emit, get_status, _set = _handlers()
    get_status({"light": {"get_status": {"light_id": 1, "level": 50}}}, make_ctx())
    assert state.lights[1].on is True
    get_status({"light": {"get_status": {"light_id": 1, "level": 0}}}, make_ctx())
    assert state.lights[1].on is False


def test_explicit_status_and_state_override_level() -> None:
    state, _emit, get_status, _set = _handlers()
    get_status(
        {"light": {"get_status": {"light_id": 1, "status": "OFF", "level": 30}}},
        make_ctx(),
    )
    assert state.lights[1].on is False
    get_status(
        {"light": {"get_status": {"light_id": 1, "state": True, "level": 0}}},
        make_ctx(),
    )
    assert state.lights[1].on is True


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


async def _exchange(
    client: Elke27Client, session: _FakeSession, command: str, params: dict[str, Any], reply: Any
) -> Any:
    before = len(session.sent)
    task = asyncio.ensure_future(client.async_execute(command, **params))
    for _ in range(50):
        if len(session.sent) > before or task.done():
            break
        await asyncio.sleep(0)
    sent = session.sent[-1]
    get_private(get_kernel(client), "_on_message")({"seq": sent["seq"], "light": reply})
    result = await task
    for _ in range(5):  # let queued kernel events update the snapshot
        await asyncio.sleep(0)
    return result


@pytest.mark.asyncio
async def test_set_then_get_status_updates_snapshot() -> None:
    """End to end: the set ack leaves the snapshot alone, the follow-up get updates it."""
    client = Elke27Client()
    kernel = get_kernel(client)
    session = _FakeSession()
    cast(Any, kernel)._session = session
    kernel.state.panel.session_id = 1
    kernel.state.inventory.configured_lights = {1}
    kernel.state.inventory.configured_lights_complete = True
    cast(Any, client)._event_loop = asyncio.get_running_loop()
    kernel.load_features_blocking(get_private(client, "_feature_modules"))

    result = await _exchange(
        client,
        session,
        "light_set_status",
        {"light_id": 1, "status": "ON", "level": 50},
        {"set_status": {"light_id": 1, "error_code": 0}},
    )
    assert result.ok is True
    assert 1 not in client.snapshot.lights  # the stateless ack changes nothing

    result = await _exchange(
        client,
        session,
        "light_get_status",
        {"light_id": 1},
        {"get_status": {"light_id": 1, "level": 50, "rssi": 4, "error_code": 0}},
    )
    assert result.ok is True
    light = client.snapshot.lights[1]
    assert light.state is True
    assert light.level == 50
