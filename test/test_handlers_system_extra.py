from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from elke27_lib.dispatcher import DispatchContext
from elke27_lib.events import (
    ApiError,
    AuthorizationRequiredEvent,
    CsmSnapshotUpdated,
    TableCsmChanged,
)
from elke27_lib.handlers import system as system_handler
from elke27_lib.states import PanelState
from test.helpers.dispatch import make_ctx


class _EmitSpy:
    def __init__(self) -> None:
        self.events: list[object] = []

    def __call__(self, evt: object, _ctx: DispatchContext) -> None:
        self.events.append(evt)


def _any_event(spy: _EmitSpy, kind: type) -> bool:
    return any(isinstance(evt, kind) for evt in spy.events)


def test_system_get_trouble_and_errors() -> None:
    state = PanelState()
    emit = _EmitSpy()
    handler = system_handler.make_system_get_trouble_handler(state, emit, now=lambda: 1.0)

    assert handler({"nope": {}}, make_ctx()) is False
    assert handler({"system": {}}, make_ctx()) is False

    msg = {"system": {"get_trouble": {"error_code": 11008}}}
    assert handler(msg, make_ctx(classification="BROADCAST")) is True
    assert _any_event(emit, AuthorizationRequiredEvent)

    emit.events.clear()
    msg = {"system": {"get_trouble": {"error_code": 5}}}
    assert handler(msg, make_ctx()) is True
    assert _any_event(emit, ApiError)

    emit.events.clear()
    msg = {"system": {"get_troubles": {"troubles": [1, 2]}}}
    assert handler(msg, make_ctx()) is True
    assert cast(dict[str, Any], state.system_status["get_trouble"])["troubles"] == [1, 2]
    assert state.system_status["troubles"] == [1, 2]
    assert state.panel.last_message_at == 1.0


def test_system_table_info_and_helpers() -> None:
    state = PanelState()
    emit = _EmitSpy()
    handler = system_handler.make_system_get_table_info_handler(state, emit, now=lambda: 2.0)

    msg = {"system": {"get_table_info": {"table_csm": "4"}}}
    assert handler(msg, make_ctx()) is True
    assert _any_event(emit, TableCsmChanged)
    assert _any_event(emit, CsmSnapshotUpdated)

    emit.events.clear()
    system_handler._apply_system_table_csm(state, emit, make_ctx(), {})
    system_handler._apply_system_table_csm(state, emit, make_ctx(), {"table_csm": 4})
    assert not _any_event(emit, TableCsmChanged)

    assert system_handler._extract_table_csm({"table_csm": True}, domain="system") is None
    assert system_handler._extract_table_csm({"table_csm": 2}, domain="system") == 2
    assert system_handler._extract_table_csm({"table_csm": 2.0}, domain="system") == 2
    assert system_handler._extract_table_csm({"table_csm": "3"}, domain="system") == 3
    assert system_handler._extract_table_csm({"table_csm": "bad"}, domain="system") is None
    assert system_handler._extract_table_csm({"other": 1}, domain="system") is None


def test_system_all_command_wrappers() -> None:
    state = PanelState()
    emit = _EmitSpy()

    def call(
        factory: Callable[[PanelState, _EmitSpy, Callable[[], float]], Callable[..., bool]],
        command: str,
    ):
        handler = cast(Any, factory)(state, emit, now=lambda: 3.0)
        msg = {"system": {command: {"foo": "bar"}}}
        assert handler(msg, make_ctx()) is True
        assert cast(dict[str, Any], state.system_status[command])["foo"] == "bar"

    call(system_handler.make_system_get_troubles_handler, "get_troubles")
    call(system_handler.make_system_get_attribs_handler, "get_attribs")
    call(system_handler.make_system_set_attribs_handler, "set_attribs")
    call(system_handler.make_system_get_cutoffs_handler, "get_cutoffs")
    call(system_handler.make_system_set_cutoffs_handler, "set_cutoffs")
    call(system_handler.make_system_get_sounders_handler, "get_sounders")
    call(system_handler.make_system_get_system_time_handler, "get_system_time")
    call(system_handler.make_system_set_system_time_handler, "set_system_time")
    call(system_handler.make_system_set_system_key_handler, "set_system_key")
    call(system_handler.make_system_file_info_handler, "file_info")
    call(system_handler.make_system_get_debug_flags_handler, "get_debug_flags")
    call(system_handler.make_system_set_debug_flags_handler, "set_debug_flags")
    call(system_handler.make_system_get_debug_string_handler, "get_debug_string")
    call(system_handler.make_system_r_u_alive_handler, "r_u_alive")
    call(system_handler.make_system_reset_smokes_handler, "reset_smokes")
    call(system_handler.make_system_set_run_handler, "set_run")
    call(system_handler.make_system_start_updt_handler, "start_updt")
    call(system_handler.make_system_reconfig_handler, "reconfig")
    call(system_handler.make_system_get_update_handler, "get_update")
