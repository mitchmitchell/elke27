from __future__ import annotations

from elke27_lib.dispatcher import DispatchContext, PagedBlock
from elke27_lib.events import (
    ApiError,
    AuthorizationRequiredEvent,
    BootstrapCountsReady,
    CsmSnapshotUpdated,
    LockConfiguredInventoryReady,
    LockConfiguredUpdated,
    LockStatusUpdated,
    LockTableInfoUpdated,
    TableCsmChanged,
)
from elke27_lib.handlers import lock as lock_handler
from elke27_lib.states import LockState, PanelState
from test.helpers.dispatch import make_ctx


class _EmitSpy:
    def __init__(self) -> None:
        self.events: list[object] = []

    def __call__(self, evt: object, _ctx: DispatchContext) -> None:
        self.events.append(evt)


def _any_event(spy: _EmitSpy, kind: type) -> bool:
    return any(isinstance(evt, kind) for evt in spy.events)


def test_lock_status_handlers() -> None:
    state = PanelState()
    emit = _EmitSpy()
    get_status = lock_handler.make_lock_get_status_handler(state, emit, now=lambda: 1.0)
    set_status = lock_handler.make_lock_set_status_handler(state, emit, now=lambda: 2.0)

    assert get_status({"lock": {"get_status": {"error_code": 2}}}, make_ctx()) is True
    assert _any_event(emit, ApiError)
    assert get_status({"nope": {}}, make_ctx()) is False
    assert get_status({"lock": {}}, make_ctx()) is False
    assert set_status({"nope": {}}, make_ctx()) is False
    assert set_status({"lock": {}}, make_ctx()) is False

    emit.events.clear()
    msg = {"lock": {"get_status": {"lock_id": 1, "status": "ON"}}}
    assert get_status(msg, make_ctx()) is True
    assert state.locks[1].locked is True
    assert _any_event(emit, LockStatusUpdated)

    emit.events.clear()
    msg = {"lock": {"set_status": {"lock_id": 1, "status": "OFF"}}}
    assert set_status(msg, make_ctx()) is True
    assert state.locks[1].locked is False
    assert get_status({"lock": {"get_status": {"lock_id": 0}}}, make_ctx()) is False
    assert set_status({"lock": {"set_status": {"lock_id": 0}}}, make_ctx()) is False


def test_lock_configured_attribs_table_handlers() -> None:
    state = PanelState()
    emit = _EmitSpy()
    configured = lock_handler.make_lock_get_configured_handler(state, emit, now=lambda: 3.0)
    attribs = lock_handler.make_lock_get_attribs_handler(state, emit, now=lambda: 4.0)
    table = lock_handler.make_lock_get_table_info_handler(state, emit, now=lambda: 5.0)

    msg = {"lock": {"get_configured": {"error_code": 11008}}}
    assert configured(msg, make_ctx()) is True
    assert _any_event(emit, AuthorizationRequiredEvent)
    assert configured({"nope": {}}, make_ctx()) is False
    assert configured({"lock": {}}, make_ctx()) is False

    emit.events.clear()
    assert configured({"lock": {"get_configured": {"error_code": 7}}}, make_ctx()) is True
    assert _any_event(emit, ApiError)

    emit.events.clear()
    msg = {"lock": {"get_configured": {"locks": [1, 2], "block_id": 1, "block_count": 1}}}
    assert configured(msg, make_ctx()) is True
    assert state.inventory.configured_locks == {1, 2}
    assert _any_event(emit, LockConfiguredUpdated)
    assert _any_event(emit, LockConfiguredInventoryReady)

    emit.events.clear()
    state.table_info_by_domain["lock"] = {"table_elements": 1}
    msg = {"lock": {"get_configured": {"locks": [1, 2], "block_id": 1, "block_count": 1}}}
    assert configured(msg, make_ctx()) is True
    assert state.inventory.configured_locks == {1}

    merge = lock_handler.make_lock_configured_merge(state)
    merged = merge(
        [
            PagedBlock(block_id=1, payload={"locks": [1]}),
            PagedBlock(block_id=2, payload={"lock_ids": [2]}),
        ],
        2,
    )
    assert merged == {"locks": [1, 2], "block_count": 2}

    emit.events.clear()
    msg = {"lock": {"get_attribs": {"lock_id": 1, "name": " Front ", "area_id": 1}}}
    assert attribs(msg, make_ctx()) is True
    assert state.locks[1].name == "Front"
    assert attribs({"nope": {}}, make_ctx()) is False
    assert attribs({"lock": {}}, make_ctx()) is False
    assert attribs({"lock": {"get_attribs": {"lock_id": 0}}}, make_ctx()) is False

    emit.events.clear()
    assert (
        attribs({"lock": {"get_attribs": {"error_code": 11008, "lock_id": 1}}}, make_ctx()) is True
    )
    assert _any_event(emit, AuthorizationRequiredEvent)

    emit.events.clear()
    assert attribs({"lock": {"get_attribs": {"error_code": 4, "lock_id": 1}}}, make_ctx()) is True
    assert _any_event(emit, ApiError)

    emit.events.clear()
    assert (
        table({"lock": {"table_info": {"table_elements": 1, "increment_size": 2}}}, make_ctx())
        is True
    )
    assert _any_event(emit, LockTableInfoUpdated)

    emit.events.clear()
    state.table_info_known.update({"area", "zone", "output", "tstat"})
    msg = {"lock": {"get_table_info": {"table_elements": 1, "table_csm": "5"}}}
    assert table(msg, make_ctx()) is True
    assert _any_event(emit, LockTableInfoUpdated)
    assert _any_event(emit, TableCsmChanged)
    assert _any_event(emit, CsmSnapshotUpdated)
    assert _any_event(emit, BootstrapCountsReady)
    assert table({"nope": {}}, make_ctx()) is False
    assert table({"lock": {}}, make_ctx()) is False

    emit.events.clear()
    assert table({"lock": {"get_table_info": {"error_code": 5}}}, make_ctx()) is True
    assert _any_event(emit, ApiError)


def test_lock_helpers() -> None:
    lock = LockState(lock_id=1)
    lock_handler._apply_lock_status_fields(lock, {"status": "ON", "x": 1})
    assert lock.locked is True
    assert lock.fields["x"] == 1
    lock_handler._apply_lock_status_fields(lock, {"status": "OFF"})
    assert lock.locked is False

    lock_handler._apply_lock_status_fields(lock, {"locked": False})
    assert lock.locked is False
    lock_handler._apply_lock_status_fields(lock, {"locked": True})
    assert lock.locked is True

    lock_handler._apply_lock_attribs(lock, {"name": "A", "area_id": 1, "y": 2})
    assert lock.name == "A"
    assert lock.area_id == 1
    assert lock.fields["y"] == 2
    lock_handler._apply_lock_attribs(lock, {"name": "   "})
    assert lock.name is None

    assert lock_handler._extract_configured_ids({"locks": [1, 2]}, ("locks",)) == [1, 2]
    assert lock_handler._extract_configured_ids({"none": []}, ("locks",)) == []
    assert lock_handler._extract_int({"table_elements": 1}, "table_elements") == 1
    assert lock_handler._extract_table_csm({"table_csm": 3}, domain="lock") == 3
    assert lock_handler._extract_table_csm({"table_csm": "3"}, domain="lock") == 3
    assert lock_handler._normalize_name(None) is None
    assert lock_handler._extract_table_csm({"table_csm": True}, domain="lock") is None
    assert lock_handler._extract_table_csm({"table_csm": 3.0}, domain="lock") == 3
    assert lock_handler._extract_table_csm({"table_csm": "bad"}, domain="lock") is None
