from __future__ import annotations

from elke27_lib.dispatcher import DispatchContext, PagedBlock
from elke27_lib.events import (
    ApiError,
    AuthorizationRequiredEvent,
    BootstrapCountsReady,
    CsmSnapshotUpdated,
    DispatchRoutingError,
    OutputConfiguredInventoryReady,
    OutputConfiguredUpdated,
    OutputsStatusBulkUpdated,
    OutputStatusUpdated,
    OutputTableInfoUpdated,
    TableCsmChanged,
)
from elke27_lib.handlers import output as output_handler
from elke27_lib.states import OutputState, PanelState
from test.helpers.dispatch import make_ctx


class _EmitSpy:
    def __init__(self) -> None:
        self.events: list[object] = []

    def __call__(self, evt: object, _ctx: DispatchContext) -> None:
        self.events.append(evt)


def _any_event(spy: _EmitSpy, kind: type) -> bool:
    return any(isinstance(evt, kind) for evt in spy.events)


def test_output_get_status_handler() -> None:
    state = PanelState()
    emit = _EmitSpy()
    handler = output_handler.make_output_get_status_handler(state, emit, now=lambda: 1.0)

    assert handler({"nope": {}}, make_ctx()) is False
    assert handler({"output": {}}, make_ctx()) is False

    msg = {"output": {"get_status": {"error_code": 3}}}
    assert handler(msg, make_ctx()) is True
    assert _any_event(emit, ApiError)

    msg = {"output": {"get_status": {"output_id": 0}}}
    assert handler(msg, make_ctx()) is False

    emit.events.clear()
    msg = {"output": {"get_status": {"output_id": 1, "status": "on", "extra": 1}}}
    assert handler(msg, make_ctx()) is True
    output = state.outputs[1]
    assert output.status == "ON"
    assert output.on is True
    assert output.fields["extra"] == 1
    assert _any_event(emit, OutputStatusUpdated)
    assert state.panel.last_message_at == 1.0


def test_output_set_status_and_get_available_handlers() -> None:
    state = PanelState()
    emit = _EmitSpy()
    set_status = output_handler.make_output_set_status_handler(state, emit, now=lambda: 1.5)
    get_available = output_handler.make_output_get_available_handler(state, emit, now=lambda: 1.6)

    assert set_status({"nope": {}}, make_ctx()) is False
    assert set_status({"output": {}}, make_ctx()) is False
    assert set_status({"output": {"set_status": {"output_id": 0}}}, make_ctx()) is False

    msg = {"output": {"set_status": {"output_id": 1, "status": "ON"}}}
    assert set_status(msg, make_ctx()) is True
    assert state.outputs[1].on is True
    assert _any_event(emit, OutputStatusUpdated)

    assert get_available({"nope": {}}, make_ctx()) is False
    assert get_available({"output": {}}, make_ctx()) is False
    msg = {"output": {"get_available": {"outputs": [1, 2]}}}
    assert get_available(msg, make_ctx()) is True
    assert state.inventory.configured_outputs == {1, 2}
    assert state.panel.last_message_at == 1.6


def test_output_get_configured_handler() -> None:
    state = PanelState()
    emit = _EmitSpy()
    handler = output_handler.make_output_get_configured_handler(state, emit, now=lambda: 2.0)

    assert handler({"nope": {}}, make_ctx()) is False
    assert handler({"output": {}}, make_ctx()) is False

    msg = {"output": {"get_configured": {"error_code": 11008}}}
    assert handler(msg, make_ctx()) is True
    assert _any_event(emit, AuthorizationRequiredEvent)

    emit.events.clear()
    msg = {"output": {"get_configured": {"error_code": 9}}}
    assert handler(msg, make_ctx()) is True
    assert _any_event(emit, ApiError)

    emit.events.clear()
    state.table_info_by_domain["output"] = {"table_elements": 2}
    msg = {"output": {"get_configured": {"outputs": [1, 2, 3]}}}
    assert handler(msg, make_ctx()) is True
    assert state.inventory.configured_outputs == {1, 2}
    assert state.inventory.configured_outputs_complete is True
    assert _any_event(emit, OutputConfiguredUpdated)
    assert _any_event(emit, OutputConfiguredInventoryReady)
    assert state.panel.last_message_at == 2.0


def test_output_get_all_outputs_status_handler() -> None:
    state = PanelState()
    emit = _EmitSpy()
    handler = output_handler.make_output_get_all_outputs_status_handler(
        state, emit, now=lambda: 3.0
    )

    assert handler({"nope": {}}, make_ctx()) is False
    assert handler({"output": {}}, make_ctx()) is False

    msg = {"output": {"get_all_outputs_status": {"error_code": 1}}}
    assert handler(msg, make_ctx()) is True
    assert _any_event(emit, ApiError)

    emit.events.clear()
    msg = {"output": {"get_all_outputs_status": {"foo": "bar"}}}
    assert handler(msg, make_ctx()) is True
    assert _any_event(emit, DispatchRoutingError)

    emit.events.clear()
    msg = {"output": {"get_all_outputs_status": {"status": "1 0 1x"}}}
    assert handler(msg, make_ctx()) is True
    assert state.outputs[1].on is True
    assert state.outputs[2].on is False
    assert state.outputs[3].on is True
    assert _any_event(emit, OutputsStatusBulkUpdated)
    assert state.panel.last_message_at == 3.0


def test_output_configured_merge_and_attribs() -> None:
    state = PanelState()
    merge = output_handler.make_output_configured_merge(state)
    merged = merge(
        [
            PagedBlock(block_id=1, payload={"outputs": [1, 2]}),
            PagedBlock(block_id=2, payload={"output_ids": [2, 3]}),
        ],
        2,
    )
    assert merged == {"outputs": [1, 2, 3], "block_count": 2}

    emit = _EmitSpy()
    attribs = output_handler.make_output_get_attribs_handler(state, emit, now=lambda: 4.0)
    assert attribs({"nope": {}}, make_ctx()) is False
    assert attribs({"output": {}}, make_ctx()) is False

    msg = {"output": {"get_attribs": {"error_code": 11008, "output_id": 1}}}
    assert attribs(msg, make_ctx()) is True
    assert _any_event(emit, AuthorizationRequiredEvent)

    emit.events.clear()
    msg = {"output": {"get_attribs": {"error_code": 9, "output_id": 1}}}
    assert attribs(msg, make_ctx()) is True
    assert _any_event(emit, ApiError)

    msg = {"output": {"get_attribs": {"output_id": 0}}}
    assert attribs(msg, make_ctx()) is False

    msg = {"output": {"get_attribs": {"output_id": 1, "name": "  Test "}}}
    assert attribs(msg, make_ctx()) is True
    assert state.outputs[1].name == "Test"
    assert state.panel.last_message_at == 4.0


def test_output_get_table_info_handler_and_helpers() -> None:
    state = PanelState()
    emit = _EmitSpy()
    handler = output_handler.make_output_get_table_info_handler(state, emit, now=lambda: 5.0)

    assert handler({"nope": {}}, make_ctx()) is False
    assert handler({"output": {}}, make_ctx()) is False

    msg = {"output": {"get_table_info": {"error_code": 3}}}
    assert handler(msg, make_ctx()) is True
    assert _any_event(emit, ApiError)

    emit.events.clear()
    state.table_info_known.update({"area", "zone", "tstat"})
    msg = {"output": {"table_info": {"table_elements": 2, "table_csm": "4"}}}
    assert handler(msg, make_ctx()) is True
    assert _any_event(emit, OutputTableInfoUpdated)
    assert _any_event(emit, TableCsmChanged)
    assert _any_event(emit, CsmSnapshotUpdated)
    assert _any_event(emit, BootstrapCountsReady)
    assert state.table_info_by_domain["output"]["table_elements"] == 2

    assert output_handler._extract_table_csm({"table_csm": True}, domain="output") is None
    assert output_handler._extract_table_csm({"table_csm": 2}, domain="output") == 2
    assert output_handler._extract_table_csm({"table_csm": 2.0}, domain="output") == 2
    assert output_handler._extract_table_csm({"table_csm": "3"}, domain="output") == 3
    assert output_handler._extract_table_csm({"table_csm": "bad"}, domain="output") is None
    assert output_handler._extract_table_csm({"other": 1}, domain="output") is None


def test_output_helper_functions() -> None:
    output = OutputState(output_id=1)
    changed: set[str] = set()
    output_handler._apply_output_status_fields(output, {"status": " off ", "extra": 1}, changed)
    assert output.status == "OFF"
    assert output.on is False
    assert output.fields["extra"] == 1
    assert output_handler._extract_configured_output_ids({"outputs": [1, 2, 2, 0, "x"]}) == [
        1,
        2,
    ]
    assert output_handler._extract_configured_output_ids({"output_ids": [3]}) == [3]
    assert output_handler._extract_configured_output_ids({"configured_outputs": [4]}) == [4]
    assert output_handler._extract_configured_output_ids({"configured_output_ids": [5]}) == [5]
    assert output_handler._extract_configured_output_ids({"none": []}) == []

    assert output_handler._apply_output_status_char(output, "x") is False
    assert output_handler._apply_output_status_char(output, "1") is True
    assert output.status == "ON"
    assert output.on is True

    assert output_handler._normalize_name(None) is None
    assert output_handler._normalize_name("   ") is None
    assert output_handler._normalize_name(" Name ") == "Name"

    assert output_handler._extract_int({"table_elements": 2}, "table_elements") == 2
    assert output_handler._extract_int({"table_elements": "bad"}, "table_elements") is None
