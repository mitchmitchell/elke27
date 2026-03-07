from __future__ import annotations

from elke27_lib.dispatcher import DispatchContext, PagedBlock
from elke27_lib.events import (
    ApiError,
    AuthorizationRequiredEvent,
    BarrierConfiguredInventoryReady,
    BarrierConfiguredUpdated,
    BarrierStatusUpdated,
    BarrierTableInfoUpdated,
    BootstrapCountsReady,
    CsmSnapshotUpdated,
    TableCsmChanged,
)
from elke27_lib.handlers import barrier as barrier_handler
from elke27_lib.states import BarrierState, PanelState
from test.helpers.dispatch import make_ctx


class _EmitSpy:
    def __init__(self) -> None:
        self.events: list[object] = []

    def __call__(self, evt: object, _ctx: DispatchContext) -> None:
        self.events.append(evt)


def _any_event(spy: _EmitSpy, kind: type) -> bool:
    return any(isinstance(evt, kind) for evt in spy.events)


def test_barrier_status_handlers() -> None:
    state = PanelState()
    emit = _EmitSpy()
    get_status = barrier_handler.make_barrier_get_status_handler(state, emit, now=lambda: 1.0)
    set_status = barrier_handler.make_barrier_set_status_handler(state, emit, now=lambda: 2.0)

    assert get_status({"barrier": {"get_status": {"error_code": 2}}}, make_ctx()) is True
    assert _any_event(emit, ApiError)

    emit.events.clear()
    msg = {"barrier": {"get_status": {"barrier_id": 1, "status": "opening"}}}
    assert get_status(msg, make_ctx()) is True
    assert state.barriers[1].status == "OPENING"
    assert _any_event(emit, BarrierStatusUpdated)

    emit.events.clear()
    msg = {"barrier": {"set_status": {"barrier_id": 1, "status": "close"}}}
    assert set_status(msg, make_ctx()) is True
    assert state.barriers[1].status == "CLOSE"


def test_barrier_configured_attribs_table_handlers() -> None:
    state = PanelState()
    emit = _EmitSpy()
    configured = barrier_handler.make_barrier_get_configured_handler(state, emit, now=lambda: 3.0)
    attribs = barrier_handler.make_barrier_get_attribs_handler(state, emit, now=lambda: 4.0)
    table = barrier_handler.make_barrier_get_table_info_handler(state, emit, now=lambda: 5.0)

    msg = {"barrier": {"get_configured": {"error_code": 11008}}}
    assert configured(msg, make_ctx()) is True
    assert _any_event(emit, AuthorizationRequiredEvent)

    emit.events.clear()
    msg = {"barrier": {"get_configured": {"barriers": [1, 2], "block_id": 1, "block_count": 1}}}
    assert configured(msg, make_ctx()) is True
    assert state.inventory.configured_barriers == {1, 2}
    assert _any_event(emit, BarrierConfiguredUpdated)
    assert _any_event(emit, BarrierConfiguredInventoryReady)

    merge = barrier_handler.make_barrier_configured_merge(state)
    merged = merge(
        [
            PagedBlock(block_id=1, payload={"barriers": [1]}),
            PagedBlock(block_id=2, payload={"barrier_ids": [2]}),
        ],
        2,
    )
    assert merged == {"barriers": [1, 2], "block_count": 2}

    emit.events.clear()
    msg = {"barrier": {"get_attribs": {"barrier_id": 1, "name": " Garage ", "area_id": 1}}}
    assert attribs(msg, make_ctx()) is True
    assert state.barriers[1].name == "Garage"

    emit.events.clear()
    state.table_info_known.update({"area", "zone", "output", "tstat"})
    msg = {"barrier": {"get_table_info": {"table_elements": 1, "table_csm": "9"}}}
    assert table(msg, make_ctx()) is True
    assert _any_event(emit, BarrierTableInfoUpdated)
    assert _any_event(emit, TableCsmChanged)
    assert _any_event(emit, CsmSnapshotUpdated)
    assert _any_event(emit, BootstrapCountsReady)


def test_barrier_helpers() -> None:
    barrier = BarrierState(barrier_id=1)
    barrier_handler._apply_barrier_status_fields(barrier, {"status": "open", "x": 1})
    assert barrier.status == "OPEN"
    assert barrier.fields["x"] == 1

    barrier_handler._apply_barrier_attribs(barrier, {"name": "A", "area_id": 1, "y": 2})
    assert barrier.name == "A"
    assert barrier.area_id == 1
    assert barrier.fields["y"] == 2

    assert barrier_handler._extract_configured_ids({"barriers": [1, 2]}, ("barriers",)) == [1, 2]
    assert barrier_handler._extract_int({"table_elements": 1}, "table_elements") == 1
    assert barrier_handler._extract_table_csm({"table_csm": "3"}, domain="barrier") == 3
