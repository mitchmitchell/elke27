from __future__ import annotations

from elke27_lib.dispatcher import DispatchContext
from elke27_lib.events import (
    ApiError,
    AuthorizationRequiredEvent,
    CsmSnapshotUpdated,
    TableCsmChanged,
)
from elke27_lib.handlers import log as log_handler
from elke27_lib.states import PanelState
from test.helpers.dispatch import make_ctx


class _EmitSpy:
    def __init__(self) -> None:
        self.events: list[object] = []

    def __call__(self, evt: object, _ctx: DispatchContext) -> None:
        self.events.append(evt)


def _any_event(spy: _EmitSpy, kind: type) -> bool:
    return any(isinstance(evt, kind) for evt in spy.events)


def test_log_handlers_store_status_and_errors() -> None:
    state = PanelState()
    emit = _EmitSpy()

    trouble = log_handler.make_log_get_trouble_handler(state, emit, now=lambda: 1.0)
    index = log_handler.make_log_get_index_handler(state, emit, now=lambda: 2.0)
    attribs = log_handler.make_log_get_attribs_handler(state, emit, now=lambda: 3.0)
    set_attribs = log_handler.make_log_set_attribs_handler(state, emit, now=lambda: 4.0)
    get_list = log_handler.make_log_get_list_handler(state, emit, now=lambda: 5.0)
    get_log = log_handler.make_log_get_log_handler(state, emit, now=lambda: 6.0)
    clear = log_handler.make_log_clear_handler(state, emit, now=lambda: 7.0)
    realloc = log_handler.make_log_realloc_handler(state, emit, now=lambda: 8.0)

    assert trouble({"nope": {}}, make_ctx()) is False
    assert trouble({"log": {}}, make_ctx()) is False
    assert index({"nope": {}}, make_ctx()) is False
    assert index({"log": {}}, make_ctx()) is False
    assert attribs({"nope": {}}, make_ctx()) is False
    assert attribs({"log": {}}, make_ctx()) is False
    assert set_attribs({"nope": {}}, make_ctx()) is False
    assert set_attribs({"log": {}}, make_ctx()) is False
    assert get_list({"nope": {}}, make_ctx()) is False
    assert get_list({"log": {}}, make_ctx()) is False
    assert get_log({"nope": {}}, make_ctx()) is False
    assert get_log({"log": {}}, make_ctx()) is False
    assert clear({"nope": {}}, make_ctx()) is False
    assert clear({"log": {}}, make_ctx()) is False
    assert realloc({"nope": {}}, make_ctx()) is False
    assert realloc({"log": {}}, make_ctx()) is False

    msg = {"log": {"get_trouble": {"error_code": 11008}}}
    assert trouble(msg, make_ctx(classification="BROADCAST")) is True
    assert _any_event(emit, AuthorizationRequiredEvent)

    emit.events.clear()
    msg = {"log": {"get_index": {"error_code": 11008}}}
    assert index(msg, make_ctx()) is True
    assert _any_event(emit, AuthorizationRequiredEvent)

    emit.events.clear()
    msg = {"log": {"get_attribs": {"error_code": 11008}}}
    assert attribs(msg, make_ctx()) is True
    assert _any_event(emit, AuthorizationRequiredEvent)

    emit.events.clear()
    msg = {"log": {"set_attribs": {"error_code": 11008}}}
    assert set_attribs(msg, make_ctx()) is True
    assert _any_event(emit, AuthorizationRequiredEvent)

    emit.events.clear()
    msg = {"log": {"get_list": {"error_code": 11008}}}
    assert get_list(msg, make_ctx()) is True
    assert _any_event(emit, AuthorizationRequiredEvent)

    emit.events.clear()
    msg = {"log": {"get_log": {"error_code": 11008}}}
    assert get_log(msg, make_ctx()) is True
    assert _any_event(emit, AuthorizationRequiredEvent)

    emit.events.clear()
    msg = {"log": {"clear": {"error_code": 11008}}}
    assert clear(msg, make_ctx()) is True
    assert _any_event(emit, AuthorizationRequiredEvent)

    emit.events.clear()
    msg = {"log": {"realloc": {"error_code": 11008}}}
    assert realloc(msg, make_ctx()) is True
    assert _any_event(emit, AuthorizationRequiredEvent)

    emit.events.clear()
    msg = {"log": {"get_trouble": {"error_code": 5}}}
    assert trouble(msg, make_ctx()) is True
    assert _any_event(emit, ApiError)

    emit.events.clear()
    msg = {"log": {"get_trouble": {"foo": "bar"}}}
    assert trouble(msg, make_ctx()) is True
    assert state.log_status["get_trouble"]["foo"] == "bar"
    assert state.panel.last_message_at == 1.0

    msg = {"log": {"get_index": {"idx": 1}}}
    assert index(msg, make_ctx()) is True
    assert state.log_status["get_index"]["idx"] == 1
    assert state.panel.last_message_at == 2.0

    msg = {"log": {"get_attribs": {"a": 1}}}
    assert attribs(msg, make_ctx()) is True
    assert state.log_status["get_attribs"]["a"] == 1

    msg = {"log": {"set_attribs": {"b": 2}}}
    assert set_attribs(msg, make_ctx()) is True
    assert state.log_status["set_attribs"]["b"] == 2

    msg = {"log": {"get_list": {"c": 3}}}
    assert get_list(msg, make_ctx()) is True
    assert state.log_status["get_list"]["c"] == 3

    msg = {"log": {"get_log": {"d": 4}}}
    assert get_log(msg, make_ctx()) is True
    assert state.log_status["get_log"]["d"] == 4

    msg = {"log": {"clear": {"e": 5}}}
    assert clear(msg, make_ctx()) is True
    assert state.log_status["clear"]["e"] == 5

    msg = {"log": {"realloc": {"f": 6}}}
    assert realloc(msg, make_ctx()) is True
    assert state.log_status["realloc"]["f"] == 6


def test_log_table_info_and_helpers() -> None:
    state = PanelState()
    emit = _EmitSpy()
    handler = log_handler.make_log_get_table_info_handler(state, emit, now=lambda: 9.0)

    assert handler({"nope": {}}, make_ctx()) is False
    assert handler({"log": {}}, make_ctx()) is False

    msg = {"log": {"get_table_info": {"error_code": 11008}}}
    assert handler(msg, make_ctx()) is True
    assert _any_event(emit, AuthorizationRequiredEvent)

    emit.events.clear()
    msg = {"log": {"get_table_info": {"table_csm": 12, "table_elements": 2}}}
    assert handler(msg, make_ctx()) is True
    assert state.table_info_by_domain["log"]["table_elements"] == 2
    assert _any_event(emit, TableCsmChanged)
    assert _any_event(emit, CsmSnapshotUpdated)

    assert log_handler._extract_table_csm({"table_csm": True}, domain="log") is None
    assert log_handler._extract_table_csm({"table_csm": 2}, domain="log") == 2
    assert log_handler._extract_table_csm({"table_csm": "3"}, domain="log") == 3
    assert log_handler._extract_table_csm({"table_csm": "bad"}, domain="log") is None
    assert log_handler._extract_table_csm({"other": 1}, domain="log") is None
