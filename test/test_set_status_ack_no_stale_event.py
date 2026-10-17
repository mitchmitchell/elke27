"""#62: a set_status ack with no new state must not emit the stale cached value."""

from __future__ import annotations

from typing import Any

from elke27_lib.events import OutputStatusUpdated, TstatStatusUpdated
from elke27_lib.handlers import output as output_handler
from elke27_lib.handlers import tstat as tstat_handler
from elke27_lib.states import PanelState
from test.helpers.dispatch import make_ctx
from test.test_handlers_output_extra import _EmitSpy


def _events(emit: Any, kind: type) -> list[Any]:
    return [e for e in emit.events if isinstance(e, kind)]


def test_output_ack_without_status_emits_nothing_then_broadcast_emits_new_value() -> None:
    state = PanelState()
    emit = _EmitSpy()
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
    emit = _EmitSpy()
    set_status = output_handler.make_output_set_status_handler(state, emit, now=lambda: 1.0)
    msg = {"output": {"set_status": {"output_id": 3, "status": "ON", "error_code": 0}}}
    assert set_status(msg, make_ctx()) is True
    events = _events(emit, OutputStatusUpdated)
    assert len(events) == 1 and events[0].on is True


def test_tstat_ack_without_state_emits_nothing_then_broadcast_emits_new_fan_mode() -> None:
    state = PanelState()
    emit = _EmitSpy()
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
    emit = _EmitSpy()
    set_status = tstat_handler.make_tstat_set_status_handler(state, emit, now=lambda: 1.0)
    msg = {"tstat": {"set_status": {"tstat_id": 1, "fan_mode": "ON"}}}
    assert set_status(msg, make_ctx()) is True
    events = _events(emit, TstatStatusUpdated)
    assert len(events) == 1 and events[0].fan_mode == "ON"
