"""#62: a set_status ack with no new state must not emit the stale cached value."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from elke27_lib import session as session_mod
from elke27_lib.client import Elke27Client, LinkKeys
from elke27_lib.events import OutputStatusUpdated, TstatStatusUpdated
from elke27_lib.handlers import output as output_handler
from elke27_lib.handlers import tstat as tstat_handler
from elke27_lib.states import PanelState
from test.helpers.dispatch import EmitSpy, make_ctx
from test.helpers.internal import get_kernel


def _events(emit: Any, kind: type) -> list[Any]:
    return [e for e in emit.events if isinstance(e, kind)]


def test_output_ack_without_status_emits_nothing_then_broadcast_emits_new_value() -> None:
    state = PanelState()
    emit = EmitSpy()
    set_status = output_handler.make_output_set_status_handler(state, emit, now=lambda: 1.0)
    get_status = output_handler.make_output_get_status_handler(state, emit, now=lambda: 2.0)
    assert get_status({"output": {"get_status": {"output_id": 3, "status": "OFF"}}}, make_ctx())
    emit.events.clear()

    # The panel acks the ON command with only output_id/error_code.
    ack = {"output": {"set_status": {"output_id": 3, "error_code": 0}}}
    assert set_status(ack, make_ctx()) is True
    assert _events(emit, OutputStatusUpdated) == []
    assert state.outputs[3].status == "OFF" and state.outputs[3].on is False

    # The status broadcast then carries ON: exactly one event, with the new value.
    assert get_status({"output": {"get_status": {"output_id": 3, "status": "ON"}}}, make_ctx())
    events = _events(emit, OutputStatusUpdated)
    assert len(events) == 1 and events[0].status == "ON" and events[0].on is True


def test_output_ack_with_new_status_still_emits() -> None:
    state = PanelState()
    emit = EmitSpy()
    set_status = output_handler.make_output_set_status_handler(state, emit, now=lambda: 1.0)
    msg = {"output": {"set_status": {"output_id": 3, "status": "ON", "error_code": 0}}}
    assert set_status(msg, make_ctx()) is True
    events = _events(emit, OutputStatusUpdated)
    assert len(events) == 1 and events[0].on is True


def test_tstat_ack_without_state_emits_nothing_then_broadcast_emits_new_fan_mode() -> None:
    state = PanelState()
    emit = EmitSpy()
    set_status = tstat_handler.make_tstat_set_status_handler(state, emit, now=lambda: 1.0)
    get_status = tstat_handler.make_tstat_get_status_handler(state, emit, now=lambda: 2.0)
    assert get_status({"tstat": {"get_status": {"tstat_id": 1, "fan_mode": "AUTO"}}}, make_ctx())
    emit.events.clear()

    assert set_status({"tstat": {"set_status": {"tstat_id": 1, "error_code": 0}}}, make_ctx())
    assert _events(emit, TstatStatusUpdated) == []
    assert state.tstats[1].fan_mode == "AUTO"

    assert get_status({"tstat": {"get_status": {"tstat_id": 1, "fan_mode": "ON"}}}, make_ctx())
    events = _events(emit, TstatStatusUpdated)
    assert len(events) == 1 and events[0].fan_mode == "ON"


def test_tstat_ack_with_new_state_still_emits() -> None:
    state = PanelState()
    emit = EmitSpy()
    set_status = tstat_handler.make_tstat_set_status_handler(state, emit, now=lambda: 1.0)
    msg = {"tstat": {"set_status": {"tstat_id": 1, "fan_mode": "ON"}}}
    assert set_status(msg, make_ctx()) is True
    events = _events(emit, TstatStatusUpdated)
    assert len(events) == 1 and events[0].fan_mode == "ON"


def test_unchanged_output_get_status_still_emits() -> None:
    """A get_status reply always emits, even when nothing changed (readiness needs it)."""
    state = PanelState()
    emit = EmitSpy()
    get_status = output_handler.make_output_get_status_handler(state, emit, now=lambda: 1.0)
    msg = {"output": {"get_status": {"output_id": 3, "status": "OFF"}}}
    assert get_status(msg, make_ctx())
    emit.events.clear()
    assert get_status(msg, make_ctx())
    assert len(_events(emit, OutputStatusUpdated)) == 1


def test_unchanged_tstat_get_status_still_emits() -> None:
    state = PanelState()
    emit = EmitSpy()
    get_status = tstat_handler.make_tstat_get_status_handler(state, emit, now=lambda: 1.0)
    msg = {"tstat": {"get_status": {"tstat_id": 1, "fan_mode": "AUTO"}}}
    assert get_status(msg, make_ctx())
    emit.events.clear()
    assert get_status(msg, make_ctx())
    assert len(_events(emit, TstatStatusUpdated)) == 1


class _ReconnectSession:
    """Stands in for the transport only: kernel.connect, dispatch and readiness are real."""

    instances: list[_ReconnectSession] = []

    def __init__(self, cfg: object, client_identity: object, link_key_hex: str) -> None:
        del cfg, client_identity, link_key_hex
        self.state = session_mod.SessionState.ACTIVE
        self.info = session_mod.SessionInfo(
            session_id=11, session_key_hex="00", session_hmac_hex="11"
        )
        self.wire_log_suppress_seqs: object = None
        self.on_message: Any = None
        self.on_disconnected: Any = None
        self.on_idle: Any = None
        _ReconnectSession.instances.append(self)

    def connect(self) -> session_mod.SessionInfo:
        return self.info

    def enable_outbound_queue(self, **_kwargs: object) -> None:
        return None

    def start_auto_receive(self) -> None:
        return None

    def send_json(self, msg: dict[str, Any], **_kwargs: object) -> None:
        del msg

    def close(self) -> None:
        self.state = session_mod.SessionState.DISCONNECTED

    def panel_says(self, msg: dict[str, Any]) -> None:
        self.on_message(msg)


def _panel_bootstrap(session: _ReconnectSession) -> None:
    """Inventory plus one get_status per configured item; identical in every session."""
    session.panel_says(
        {"area": {"get_configured": {"areas": [1], "block_id": 1, "block_count": 1}}}
    )
    session.panel_says(
        {"zone": {"get_configured": {"zones": [1], "block_id": 1, "block_count": 1}}}
    )
    session.panel_says(
        {"output": {"get_configured": {"outputs": [3], "block_id": 1, "block_count": 1}}}
    )
    session.panel_says(
        {"area": {"get_status": {"area_id": 1, "arm_state": "DISARMED", "ready_status": "READY"}}}
    )
    session.panel_says({"zone": {"get_status": {"zone_id": 1, "violated": False}}})
    session.panel_says({"output": {"get_status": {"output_id": 3, "status": "OFF"}}})


@pytest.mark.asyncio
async def test_reconnect_with_unchanged_status_replies_still_becomes_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After a dropped link, every bootstrap get_status reply repeats the cached state;
    the client must still report ready on the new session."""
    _ReconnectSession.instances = []
    monkeypatch.setattr(session_mod, "Session", _ReconnectSession)
    client = Elke27Client()
    kernel = get_kernel(client)
    kernel.load_features_blocking()
    # Bootstrap requests go nowhere; the fake panel pushes its replies below instead.
    monkeypatch.setattr(kernel, "_bootstrap_requests", lambda: None)
    monkeypatch.setattr(kernel, "_start_keepalive", lambda: None)
    keys = LinkKeys("aa", "bb", "cc")

    await client.async_connect("h", 1, keys)
    first = _ReconnectSession.instances[-1]
    _panel_bootstrap(first)
    assert await client.wait_ready(timeout_s=1.0) is True
    assert kernel.state.outputs[3].status == "OFF"

    first.on_disconnected(session_mod.SessionIOError("link dropped"))
    await asyncio.sleep(0)
    assert client.ready is False

    await client.async_connect("h", 1, keys)
    second = _ReconnectSession.instances[-1]
    assert second is not first
    _panel_bootstrap(second)
    assert await client.wait_ready(timeout_s=1.0) is True
