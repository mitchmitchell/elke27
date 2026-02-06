from __future__ import annotations

from collections.abc import Mapping

import logging
import pytest

from elke27_lib.dispatcher import DispatchContext, PagedBlock
from elke27_lib.events import (
    ApiError,
    AreaAttribsUpdated,
    AreaConfiguredInventoryReady,
    AreaConfiguredUpdated,
    AreaStatusUpdated,
    AreaTableInfoUpdated,
    AreaTroublesUpdated,
    AuthorizationRequiredEvent,
    BootstrapCountsReady,
    CsmSnapshotUpdated,
    DispatchRoutingError,
    TableCsmChanged,
    UnknownMessage,
)
from elke27_lib.handlers import area as area_handler
from elke27_lib.states import AreaState, InventoryState, PanelState
from test.helpers.dispatch import make_ctx


class _EmitSpy:
    def __init__(self) -> None:
        self.events: list[object] = []

    def __call__(self, evt: object, _ctx: DispatchContext) -> None:
        self.events.append(evt)


class _EmitRaiser:
    def __call__(self, _evt: object, _ctx: DispatchContext) -> None:
        raise RuntimeError("emit failed")


def _any_event(spy: _EmitSpy, kind: type) -> bool:
    return any(isinstance(evt, kind) for evt in spy.events)


def test_reconcile_area_state_and_helpers() -> None:
    state = PanelState()
    outcome = area_handler._reconcile_area_state(state, {"area_id": 0}, now=1.0, _source="test")
    assert outcome.area_id == -1
    assert outcome.warnings

    outcome = area_handler._reconcile_area_state(
        state,
        {"area_id": 1, "arm_state": "ARMED", "ready": "bad", "num_bypassed_zones": 2},
        now=2.0,
        _source="test",
    )
    assert outcome.area_id == 1
    assert "arm_state" in outcome.changed_fields
    assert "num_bypassed_zones" in outcome.changed_fields
    assert outcome.warnings

    assert area_handler._coerce_intish(2) == 2
    assert area_handler._coerce_intish("3") == 3
    assert area_handler._coerce_intish("bad") is None
    assert area_handler._has_configured_area_ids({"areas": []}) is True
    assert area_handler._has_configured_area_ids({"other": 1}) is False

    warnings: list[str] = []
    assert area_handler._parse_area_id_container(None, warnings) == []
    assert area_handler._parse_area_id_container([1, "2", 0], warnings) == [1, 2]
    assert area_handler._parse_area_id_container({"1": True, "2": False}, warnings) == [1]
    assert area_handler._parse_area_id_container({"x": {"area_id": 3}}, warnings) == [3]
    assert area_handler._parse_area_id_container({"x": "bad"}, warnings) == []
    assert area_handler._parse_area_id_container(0x3, warnings) == [1, 2]
    assert area_handler._parse_area_id_container("0x2", warnings) == [2]
    assert area_handler._parse_area_id_container("zz", warnings) == []
    assert area_handler._parse_area_id_container(object(), warnings) == []

    assert area_handler._ids_from_bitmask(0b101) == [1, 3]
    assert area_handler._coerce_area_id(" 4 ") == 4
    assert area_handler._coerce_area_id("   ") is None
    assert area_handler._coerce_area_id("bad") is None
    assert area_handler._coerce_area_id(-1) is None
    assert area_handler._dedupe_sorted([2, 1, 1]) == [1, 2]

    assert area_handler._extract_troubles_list({"troubles": ["a", None]}) == ["a"]
    assert area_handler._extract_troubles_list({"trouble": "x"}) == ["x"]
    assert area_handler._extract_troubles_list({"list": " "}) == []
    assert area_handler._extract_troubles_list({"none": 1}) == []

    assert area_handler._normalize_name(None) is None
    assert area_handler._normalize_name("   ") is None
    assert area_handler._normalize_name(" Name ") == "Name"

    area = AreaState(area_id=1)
    changed: set[str] = set()
    area_handler._apply_area_attribs(area, {"name": " Main "}, changed)
    assert area.name == "Main"
    assert "name" in changed

    assert area_handler._extract_int({"table_elements": 2}, "table_elements") == 2
    assert area_handler._extract_int({"table_elements": "bad"}, "table_elements") is None
    assert area_handler._type_name((int, str)) == "int | str"


def test_area_get_status_handler_paths() -> None:
    state = PanelState()
    emit = _EmitSpy()
    handler = area_handler.make_area_get_status_handler(state, emit, now=lambda: 3.0)

    assert handler({"nope": {}}, make_ctx()) is False
    assert handler({"area": {}}, make_ctx()) is False

    msg = {"area": {"get_status": {"error_code": 4, "area_id": 1}}}
    assert handler(msg, make_ctx()) is True
    assert _any_event(emit, ApiError)

    emit.events.clear()
    state.debug_last_raw_by_route_enabled = True
    msg = {"area": {"get_status": {"area_id": 0}}}
    assert handler(msg, make_ctx()) is False
    assert _any_event(emit, DispatchRoutingError)
    assert "area.get_status" in state.debug_last_raw_by_route

    emit.events.clear()
    msg = {"area": {"get_status": {"area_id": 1, "ready": "bad"}}}
    assert handler(msg, make_ctx()) is True
    assert _any_event(emit, DispatchRoutingError)

    emit.events.clear()
    msg = {"area": {"get_status": {"area_id": 1, "ready": True}}}
    assert handler(msg, make_ctx()) is True
    assert _any_event(emit, AreaStatusUpdated)

    # emit failure path
    handler_raise = area_handler.make_area_get_status_handler(state, _EmitRaiser(), now=lambda: 4.0)
    assert handler_raise({"area": {"get_status": {"area_id": 1}}}, make_ctx()) is True


def test_area_get_attribs_handler_paths() -> None:
    state = PanelState()
    emit = _EmitSpy()
    handler = area_handler.make_area_get_attribs_handler(state, emit, now=lambda: 5.0)

    assert handler({"nope": {}}, make_ctx()) is False
    assert handler({"area": {}}, make_ctx()) is False

    msg = {"area": {"get_attribs": {"error_code": 11008, "area_id": 1}}}
    assert handler(msg, make_ctx()) is True
    assert _any_event(emit, AuthorizationRequiredEvent)

    emit.events.clear()
    inv = state.inventory
    inv.invalid_id_streak_threshold = 2
    inv.configured_areas = {1, 2, 3}
    inv.area_attribs_requested = {1, 2, 3}
    msg = {"area": {"get_attribs": {"error_code": 11006, "area_id": 1}}}
    assert handler(msg, make_ctx()) is True
    msg = {"area": {"get_attribs": {"error_code": 11006, "area_id": 2}}}
    assert handler(msg, make_ctx()) is True
    assert inv.area_discovery_max_id == 0
    assert inv.configured_areas == set()
    assert inv.area_attribs_requested == set()

    emit.events.clear()
    msg = {"area": {"get_attribs": {"error_code": 9, "area_id": 1}}}
    assert handler(msg, make_ctx()) is True
    assert _any_event(emit, ApiError)

    msg = {"area": {"get_attribs": {"area_id": 0}}}
    assert handler(msg, make_ctx()) is False

    emit.events.clear()
    msg = {"area": {"get_attribs": {"area_id": 1, "name": "  Home "}}}
    assert handler(msg, make_ctx()) is True
    assert state.areas[1].name == "Home"
    assert _any_event(emit, AreaAttribsUpdated)
    assert state.panel.last_message_at == 5.0


def test_area_get_configured_handler_and_merge() -> None:
    state = PanelState()
    emit = _EmitSpy()
    handler = area_handler.make_area_get_configured_handler(state, emit, now=lambda: 6.0)
    logging.getLogger("elke27_lib.handlers.area").setLevel(logging.DEBUG)

    assert handler({"nope": {}}, make_ctx()) is False
    assert handler({"area": {}}, make_ctx()) is False

    msg = {"area": {"get_configured": {"error_code": 11008}}}
    assert handler(msg, make_ctx()) is True
    assert _any_event(emit, AuthorizationRequiredEvent)

    emit.events.clear()
    msg = {"area": {"get_configured": {"error_code": 9}}}
    assert handler(msg, make_ctx()) is True
    assert _any_event(emit, ApiError)

    emit.events.clear()
    msg = {"area": {"get_configured": {"block_id": 0, "block_count": 1}}}
    assert handler(msg, make_ctx()) is True

    msg = {"area": {"get_configured": {"block_id": 1, "block_count": 0}}}
    assert handler(msg, make_ctx()) is True

    emit.events.clear()
    msg = {"area": {"get_configured": {"areas": [1, 2], "block_id": 1, "block_count": 1}}}
    assert handler(msg, make_ctx()) is True
    assert state.inventory.configured_areas == {1, 2}
    assert _any_event(emit, AreaConfiguredUpdated)
    assert _any_event(emit, AreaConfiguredInventoryReady)

    emit.events.clear()
    msg = {"area": {"get_configured": {"block_id": 1, "block_count": 1, "bitmask": 1}}}
    assert handler(msg, make_ctx()) is True
    assert _any_event(emit, DispatchRoutingError)

    merge = area_handler.make_area_configured_merge(state)
    merged = merge(
        [
            PagedBlock(block_id=1, payload={"areas": [1], "block_size": 1}),
            PagedBlock(block_id=2, payload={"areas": [1], "block_size": 1}),
        ],
        2,
    )
    assert merged["areas"] == [1, 2]


def test_area_set_status_and_troubles() -> None:
    state = PanelState()
    emit = _EmitSpy()
    set_status = area_handler.make_area_set_status_handler(state, emit, now=lambda: 7.0)

    assert set_status({"nope": {}}, make_ctx()) is False
    assert set_status({"area": {}}, make_ctx()) is False

    msg = {"area": {"set_status": {"area_id": 0}}}
    assert set_status(msg, make_ctx()) is False
    assert _any_event(emit, DispatchRoutingError)

    emit.events.clear()
    msg = {"area": {"set_status": {"area_id": 1, "arm_state": "ARMED", "error_code": 2}}}
    assert set_status(msg, make_ctx()) is True
    assert _any_event(emit, AreaStatusUpdated)
    assert _any_event(emit, ApiError)

    emit.events.clear()
    msg = {"area": {"set_status": {"area_id": 1, "ready": "bad"}}}
    assert set_status(msg, make_ctx()) is True
    assert _any_event(emit, DispatchRoutingError)

    troubles = area_handler.make_area_get_troubles_handler(state, emit, now=lambda: 8.0)
    assert troubles({"nope": {}}, make_ctx()) is False
    assert troubles({"area": {}}, make_ctx()) is False

    msg = {"area": {"get_trouble": {"error_code": 3}}}
    assert troubles(msg, make_ctx(classification="BROADCAST")) is True
    assert _any_event(emit, ApiError)

    emit.events.clear()
    msg = {"area": {"get_troubles": {"area_id": 0}}}
    assert troubles(msg, make_ctx()) is False

    emit.events.clear()
    msg = {"area": {"get_troubles": {"area_id": 1, "troubles": ["x"]}}}
    assert troubles(msg, make_ctx()) is True
    assert _any_event(emit, AreaTroublesUpdated)
    assert state.areas[1].troubles == ["x"]


def test_area_get_table_info_and_root_handler() -> None:
    state = PanelState()
    emit = _EmitSpy()
    handler = area_handler.make_area_get_table_info_handler(state, emit, now=lambda: 9.0)
    logging.getLogger("elke27_lib.handlers.area").setLevel(logging.DEBUG)

    assert handler({"nope": {}}, make_ctx()) is False
    assert handler({"area": {}}, make_ctx()) is False

    msg = {"area": {"get_table_info": {"error_code": 1}}}
    assert handler(msg, make_ctx()) is True
    assert _any_event(emit, ApiError)

    emit.events.clear()
    state.table_info_known.update({"zone", "output", "tstat"})
    state.inventory.configured_areas = {1, 2, 3}
    state.inventory.area_attribs_requested = {1, 2, 3}
    msg = {"area": {"table_info": {"table_elements": 2, "table_csm": "5"}}}
    assert handler(msg, make_ctx()) is True
    assert _any_event(emit, AreaTableInfoUpdated)
    assert _any_event(emit, TableCsmChanged)
    assert _any_event(emit, CsmSnapshotUpdated)
    assert _any_event(emit, AreaConfiguredUpdated)
    assert _any_event(emit, BootstrapCountsReady)
    assert state.inventory.configured_areas == {1, 2}

    state.debug_last_raw_by_route_enabled = True
    root_handler = area_handler.make_area___root___handler(state, emit, lambda: 0.0)
    msg = {"area": {"foo": "bar", "baz": "qux"}}
    assert root_handler(msg, make_ctx()) is True
    assert _any_event(emit, UnknownMessage)
    assert "area.__root__" in state.debug_last_raw_by_route

    assert root_handler({"nope": {}}, make_ctx()) is False


def test_area_configured_helpers() -> None:
    state = PanelState()
    import logging
    logging.getLogger("elke27_lib.handlers.area").setLevel(logging.DEBUG)
    warnings: list[str] = []
    payload = {"configured": [1, 2], "block_id": 1, "block_count": 1}
    outcome = area_handler._reconcile_configured_areas(state, payload, now=10.0)
    assert outcome.configured_ids == (1, 2)

    state.table_info_by_domain["area"] = {"table_elements": 1}
    outcome = area_handler._reconcile_configured_areas(state, payload, now=10.0)
    assert outcome.configured_ids == (1,)

    warnings.clear()
    ids = area_handler._extract_configured_area_ids({"bitmask": 0x3}, warnings)
    assert ids == [1, 2]
    assert "no configured area ids found" not in warnings

    warnings.clear()
    ids = area_handler._extract_configured_area_ids(
        {"block_id": 1, "block_count": 2, "bitmask": 1}, warnings
    )
    assert ids == []
    assert "bitmask ignored" in warnings[0]

    block_size = area_handler._configured_block_size({"block_size": 2}, state, 2, domain="area")
    assert block_size == 2
    state.table_info_by_domain["area"] = {"table_elements": 5}
    assert area_handler._configured_block_size({}, state, 2, domain="area") == 3
    state.table_info_by_domain["area"] = {"table_elements": 0}
    assert area_handler._configured_block_size({}, state, 2, domain="area") is None

    assert area_handler._apply_configured_block_offset([1], block_id=2, block_size=2) == [3]
    assert area_handler._apply_configured_block_offset([], block_id=2, block_size=2) == []
    assert area_handler._apply_configured_block_offset([3], block_id=2, block_size=2) == [3]
    assert area_handler._apply_configured_block_offset([1], block_id=2, block_size=None) == [1]

    assert area_handler._extract_table_csm({"table_csm": True}, domain="area") is None
    assert area_handler._extract_table_csm({"table_csm": 2}, domain="area") == 2
    assert area_handler._extract_table_csm({"table_csm": 2.0}, domain="area") == 2
    assert area_handler._extract_table_csm({"table_csm": "3"}, domain="area") == 3
    assert area_handler._extract_table_csm({"table_csm": "bad"}, domain="area") is None
    assert area_handler._extract_table_csm({"other": 1}, domain="area") is None
