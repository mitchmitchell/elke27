from __future__ import annotations

from elke27_lib.dispatcher import DispatchContext, PagedBlock
from elke27_lib.events import (
    ApiError,
    AuthorizationRequiredEvent,
    BootstrapCountsReady,
    CsmSnapshotUpdated,
    DispatchRoutingError,
    TableCsmChanged,
    ZoneAttribsUpdated,
    ZoneConfiguredInventoryReady,
    ZoneConfiguredUpdated,
    ZoneDefFlagsUpdated,
    ZoneDefsUpdated,
    ZonesStatusBulkUpdated,
    ZoneStatusUpdated,
    ZoneTableInfoUpdated,
)
from elke27_lib.handlers import zone as zone_handler
from elke27_lib.states import PanelState, ZoneState
from test.helpers.dispatch import make_ctx


class _EmitSpy:
    def __init__(self) -> None:
        self.events: list[object] = []

    def __call__(self, evt: object, _ctx: DispatchContext) -> None:
        self.events.append(evt)


def _any_event(spy: _EmitSpy, kind: type) -> bool:
    return any(isinstance(evt, kind) for evt in spy.events)


def test_zone_get_configured_handler_and_merge() -> None:
    state = PanelState()
    emit = _EmitSpy()
    handler = zone_handler.make_zone_get_configured_handler(state, emit, now=lambda: 1.0)
    import logging

    logging.getLogger("elke27_lib.handlers.zone").setLevel(logging.DEBUG)

    assert handler({"nope": {}}, make_ctx()) is False
    assert handler({"zone": {}}, make_ctx()) is False

    msg = {"zone": {"get_configured": {"error_code": 11008}}}
    assert handler(msg, make_ctx()) is True
    assert _any_event(emit, AuthorizationRequiredEvent)

    emit.events.clear()
    msg = {"zone": {"get_configured": {"error_code": 9}}}
    assert handler(msg, make_ctx()) is True
    assert _any_event(emit, ApiError)

    emit.events.clear()
    msg = {"zone": {"get_configured": {"zones": [1, 2], "block_id": 1, "block_count": 1}}}
    assert handler(msg, make_ctx()) is True
    assert state.inventory.configured_zones == {1, 2}
    assert _any_event(emit, ZoneConfiguredUpdated)
    assert _any_event(emit, ZoneConfiguredInventoryReady)

    emit.events.clear()
    msg = {"zone": {"get_configured": {"block_id": 1, "block_count": 1, "bitmask": 1}}}
    assert handler(msg, make_ctx()) is True
    assert _any_event(emit, DispatchRoutingError)

    merge = zone_handler.make_zone_configured_merge(state)
    merged = merge(
        [
            PagedBlock(block_id=1, payload={"zones": [1]}),
            PagedBlock(block_id=2, payload={"zones": [2]}),
        ],
        2,
    )
    assert merged["zones"] == [1, 2]


def test_zone_get_attribs_handler_paths() -> None:
    state = PanelState()
    emit = _EmitSpy()
    handler = zone_handler.make_zone_get_attribs_handler(state, emit, now=lambda: 2.0)

    assert handler({"nope": {}}, make_ctx()) is False
    assert handler({"zone": {}}, make_ctx()) is False

    msg = {"zone": {"get_attribs": {"error_code": 11008, "zone_id": 1}}}
    assert handler(msg, make_ctx()) is True
    assert _any_event(emit, AuthorizationRequiredEvent)

    emit.events.clear()
    inv = state.inventory
    inv.invalid_id_streak_threshold = 2
    inv.configured_zones = {1, 2, 3}
    inv.zone_attribs_requested = {1, 2, 3}
    msg = {"zone": {"get_attribs": {"error_code": 11006, "zone_id": 1}}}
    assert handler(msg, make_ctx()) is True
    msg = {"zone": {"get_attribs": {"error_code": 11006, "zone_id": 2}}}
    assert handler(msg, make_ctx()) is True
    assert inv.zone_discovery_max_id == 0
    assert inv.configured_zones == set()
    assert inv.zone_attribs_requested == set()

    emit.events.clear()
    msg = {"zone": {"get_attribs": {"error_code": 9, "zone_id": 1}}}
    assert handler(msg, make_ctx()) is True
    assert _any_event(emit, ApiError)

    msg = {"zone": {"get_attribs": {"zone_id": 0}}}
    assert handler(msg, make_ctx()) is False

    emit.events.clear()
    msg = {
        "zone": {
            "get_attribs": {
                "zone_id": 1,
                "name": "  Front ",
                "area_id": 2,
                "definition": "Entry",
                "flags": [1],
                "extra": "x",
            }
        }
    }
    assert handler(msg, make_ctx()) is True
    zone = state.zones[1]
    assert zone.name == "Front"
    assert zone.area_id == 2
    assert zone.definition == "Entry"
    assert zone.flags == [1]
    assert zone.attribs["extra"] == "x"
    assert _any_event(emit, ZoneAttribsUpdated)


def test_zone_get_all_zones_status_handler() -> None:
    state = PanelState()
    emit = _EmitSpy()
    handler = zone_handler.make_zone_get_all_zones_status_handler(state, emit, now=lambda: 3.0)

    assert handler({"nope": {}}, make_ctx()) is False
    assert handler({"zone": {}}, make_ctx()) is False

    msg = {"zone": {"get_all_zones_status": {"error_code": 1}}}
    assert handler(msg, make_ctx()) is True
    assert _any_event(emit, ApiError)

    emit.events.clear()
    state.get_or_create_zone(1)
    state.get_or_create_zone(2)
    msg = {"zone": {"get_all_zones_status": {"status": "1F"}}}
    assert handler(msg, make_ctx()) is True
    assert state.zones[1].bypassed is False
    assert state.zones[2].bypassed is True
    assert _any_event(emit, ZonesStatusBulkUpdated)

    emit.events.clear()
    msg = {"zone": {"get_all_zones_status": {"status": {"zones": []}}}}
    assert handler(msg, make_ctx()) is True
    assert _any_event(emit, DispatchRoutingError)


def test_zone_get_status_and_set_status_handlers() -> None:
    state = PanelState()
    emit = _EmitSpy()
    get_status = zone_handler.make_zone_get_status_handler(state, emit, now=lambda: 4.0)
    set_status = zone_handler.make_zone_set_status_handler(state, emit, now=lambda: 5.0)
    import logging

    logging.getLogger("elke27_lib.handlers.zone").setLevel(logging.DEBUG)

    msg = {"zone": {"get_status": {"error_code": 11008, "zone_id": 1}}}
    assert get_status(msg, make_ctx()) is True
    assert _any_event(emit, AuthorizationRequiredEvent)

    emit.events.clear()
    msg = {"zone": {"get_status": {"error_code": 9, "zone_id": 1}}}
    assert get_status(msg, make_ctx()) is True
    assert _any_event(emit, ApiError)

    assert get_status({"nope": {}}, make_ctx()) is False
    assert get_status({"zone": {}}, make_ctx()) is False
    msg = {"zone": {"get_status": {"zone_id": 0}}}
    assert get_status(msg, make_ctx()) is False

    emit.events.clear()
    msg = {"zone": {"get_status": {"zone_id": 1, "BYPASSED": True, "trouble": "bad"}}}
    assert get_status(msg, make_ctx()) is True
    assert _any_event(emit, ZoneStatusUpdated)

    emit.events.clear()
    assert set_status({"nope": {}}, make_ctx()) is False
    assert set_status({"zone": {}}, make_ctx()) is False
    msg = {"zone": {"set_status": {"error_code": 2, "zone_id": 1}}}
    assert set_status(msg, make_ctx()) is True
    assert _any_event(emit, ApiError)

    msg = {"zone": {"set_status": {"zone_id": 0}}}
    assert set_status(msg, make_ctx()) is False

    emit.events.clear()
    msg = {"zone": {"set_status": {"zone_id": 1, "violated": True, "BYPASSED": True}}}
    assert set_status(msg, make_ctx()) is True
    assert _any_event(emit, ZoneStatusUpdated)


def test_zone_get_table_info_and_defs() -> None:
    state = PanelState()
    emit = _EmitSpy()
    handler = zone_handler.make_zone_get_table_info_handler(state, emit, now=lambda: 6.0)
    import logging

    logging.getLogger("elke27_lib.handlers.zone").setLevel(logging.DEBUG)

    assert handler({"nope": {}}, make_ctx()) is False
    assert handler({"zone": {}}, make_ctx()) is False

    msg = {"zone": {"get_table_info": {"error_code": 1}}}
    assert handler(msg, make_ctx()) is True
    assert _any_event(emit, ApiError)

    emit.events.clear()
    state.table_info_known.update({"area", "output", "tstat"})
    state.inventory.configured_zones = {1, 2, 3}
    state.inventory.zone_attribs_requested = {1, 2, 3}
    msg = {"zone": {"table_info": {"table_elements": 2, "table_csm": "4"}}}
    assert handler(msg, make_ctx()) is True
    assert _any_event(emit, ZoneTableInfoUpdated)
    assert _any_event(emit, TableCsmChanged)
    assert _any_event(emit, CsmSnapshotUpdated)
    assert _any_event(emit, ZoneConfiguredUpdated)
    assert _any_event(emit, BootstrapCountsReady)
    assert state.inventory.configured_zones == {1, 2}

    defs_handler = zone_handler.make_zone_get_defs_handler(state, emit, now=lambda: 7.0)
    assert defs_handler({"nope": {}}, make_ctx()) is False
    assert defs_handler({"zone": {}}, make_ctx()) is False
    msg = {"zone": {"get_defs": {"error_code": 2}}}
    assert defs_handler(msg, make_ctx()) is True
    assert _any_event(emit, ApiError)

    emit.events.clear()
    msg = {"zone": {"get_defs": {"definitions": "bad"}}}
    assert defs_handler(msg, make_ctx()) is False
    msg = {"zone": {"get_defs": {"definitions": ["A", "B"], "block_id": 2}}}
    assert defs_handler(msg, make_ctx()) is True
    assert state.zone_defs_by_id[3]["definition"] == "A"
    assert _any_event(emit, ZoneDefsUpdated)

    emit.events.clear()
    msg = {"zone": {"get_defs": {"definitions": [None], "block_id": 1}}}
    assert defs_handler(msg, make_ctx()) is True

    flags_handler = zone_handler.make_zone_get_def_flags_handler(state, emit, now=lambda: 8.0)
    assert flags_handler({"nope": {}}, make_ctx()) is False
    assert flags_handler({"zone": {}}, make_ctx()) is False
    msg = {"zone": {"get_def_flags": {"error_code": 3}}}
    assert flags_handler(msg, make_ctx()) is True
    assert _any_event(emit, ApiError)

    msg = {"zone": {"get_def_flags": {"definition": None}}}
    assert flags_handler(msg, make_ctx()) is False

    emit.events.clear()
    msg = {"zone": {"get_def_flags": {"definition": "A", "flags": [1]}}}
    assert flags_handler(msg, make_ctx()) is True
    assert state.zone_def_flags_by_name["A"]["flags"] == [1]
    assert _any_event(emit, ZoneDefFlagsUpdated)


def test_zone_helpers() -> None:
    import logging

    logging.getLogger("elke27_lib.handlers.zone").setLevel(logging.DEBUG)
    assert zone_handler._extract_table_csm({"table_csm": True}, domain="zone") is None
    assert zone_handler._extract_table_csm({"table_csm": 2}, domain="zone") == 2
    assert zone_handler._extract_table_csm({"table_csm": 2.0}, domain="zone") == 2
    assert zone_handler._extract_table_csm({"table_csm": "3"}, domain="zone") == 3
    assert zone_handler._extract_table_csm({"table_csm": "bad"}, domain="zone") is None
    assert zone_handler._extract_table_csm({"other": 1}, domain="zone") is None

    state = PanelState()
    warnings: list[str] = []
    payload = {"configured": [1, 2], "block_id": 1, "block_count": 1}
    outcome = zone_handler._reconcile_configured_zones(state, payload, now=9.0)
    assert outcome.configured_ids == (1, 2)

    state.table_info_by_domain["zone"] = {"table_elements": 1}
    outcome = zone_handler._reconcile_configured_zones(state, payload, now=9.0)
    assert outcome.configured_ids == (1,)

    warnings.clear()
    ids = zone_handler._extract_configured_zone_ids({"bitmask": 0x3}, warnings)
    assert ids == [1, 2]
    warnings.clear()
    ids = zone_handler._extract_configured_zone_ids(
        {"block_id": 1, "block_count": 2, "bitmask": 1}, warnings
    )
    assert ids == []
    assert "bitmask ignored" in warnings[0]

    assert zone_handler._parse_zone_id_container(None, warnings) == []
    assert zone_handler._parse_zone_id_container([1, "2", 0], warnings) == [1, 2]
    assert zone_handler._parse_zone_id_container({"1": True, "2": False}, warnings) == [1]
    assert zone_handler._parse_zone_id_container({"x": {"zone_id": 3}}, warnings) == [3]
    assert zone_handler._parse_zone_id_container({"x": "bad"}, warnings) == []
    assert zone_handler._parse_zone_id_container(0x3, warnings) == [1, 2]
    assert zone_handler._parse_zone_id_container("0x2", warnings) == [2]
    assert zone_handler._parse_zone_id_container("zz", warnings) == []
    assert zone_handler._parse_zone_id_container(object(), warnings) == []

    assert zone_handler._coerce_intish(2) == 2
    assert zone_handler._coerce_intish("3") == 3
    assert zone_handler._coerce_intish("bad") is None
    assert zone_handler._ids_from_bitmask(0b101) == [1, 3]

    zone = ZoneState(zone_id=1)
    state.zones[1] = zone
    state.zones[2] = ZoneState(zone_id=2)
    state.inventory.configured_zones = set()
    warnings.clear()
    outcome = zone_handler._reconcile_bulk_zone_status(state, {"status": "1X"}, now=10.0)
    assert 1 in outcome.updated_ids
    assert outcome.warnings

    warnings.clear()
    outcome = zone_handler._reconcile_bulk_zone_status(state, {"zones": []}, now=10.0)
    assert outcome.updated_ids == ()
    assert outcome.warnings

    warnings.clear()
    state.inventory.configured_zones = {2}
    outcome = zone_handler._reconcile_bulk_zone_status(state, {"zones": [{"zone_id": 1}]}, now=10.0)
    assert outcome.updated_ids == ()

    warnings.clear()
    state.inventory.configured_zones = set()
    outcome = zone_handler._reconcile_bulk_zone_status(
        state, {"zones": [{"zone_id": 99}]}, now=10.0
    )
    assert outcome.updated_ids == ()

    warnings.clear()
    outcome = zone_handler._reconcile_bulk_zone_status(
        state,
        {"zones": [{"zone_id": 1, "violated": True}, {"id": 2, "enabled": "bad"}]},
        now=11.0,
    )
    assert 1 in outcome.updated_ids
    assert outcome.warnings

    assert zone_handler._should_apply_bulk_zone(state, 1) is True
    state.inventory.configured_zones = {2}
    assert zone_handler._should_apply_bulk_zone(state, 1) is False
    state.inventory.configured_zones = set()
    state.inventory.zone_discovery_max_id = 1
    assert zone_handler._should_apply_bulk_zone(state, 1) is True

    assert zone_handler._coerce_bool(True) is True
    assert zone_handler._coerce_bool(0) is False
    assert zone_handler._coerce_bool("yes") is True
    assert zone_handler._coerce_bool("no") is False
    assert zone_handler._coerce_bool("bad") is None

    changed: set[str] = set()
    zone_handler._update_zone_bool(zone, "bypassed", True, changed)
    assert zone.bypassed is True
    assert "bypassed" in changed

    changed.clear()
    warnings.clear()
    zone_handler._apply_zone_status_payload(
        zone,
        {"BYPASSED": True, "low_battery": True, "secure_state": "ALARM"},
        changed,
        warnings,
    )
    assert zone.alarm is True

    changed.clear()
    warnings.clear()
    zone_handler._apply_zone_status_payload(
        zone,
        {"secure_state": "VIOLATED"},
        changed,
        warnings,
    )
    zone_handler._apply_zone_status_payload(
        zone,
        {"secure_state": "TROUBLE"},
        changed,
        warnings,
    )
    zone_handler._apply_zone_status_payload(
        zone,
        {"secure_state": "BYPASS"},
        changed,
        warnings,
    )
    zone_handler._apply_zone_status_payload(
        zone,
        {"secure_state": "UNKNOWN"},
        changed,
        warnings,
    )

    warnings.clear()
    assert zone_handler._apply_zone_status_char(zone, "Z", warnings) is False
    assert warnings
    assert zone_handler._apply_zone_status_char(zone, "1", warnings) is True
    assert zone_handler._apply_zone_status_char(zone, "5", warnings) is True

    warnings.clear()
    assert zone_handler._extract_zone_status_items({"zones": []}, warnings) == []
    assert zone_handler._extract_zone_status_items({"zones": [{"zone_id": 1}]}, warnings) == [
        {"zone_id": 1}
    ]
    assert zone_handler._extract_zone_status_items({"status": {"zone_id": 1}}, warnings) == [
        {"zone_id": 1}
    ]
    assert zone_handler._extract_zone_status_items({"status": 3}, warnings) == []

    warnings.clear()
    assert zone_handler._coerce_zone_items([{"zone_id": 1}], warnings) == [{"zone_id": 1}]
    assert zone_handler._coerce_zone_items({"a": {"zone_id": 1}}, warnings) == [{"zone_id": 1}]
    assert zone_handler._coerce_zone_items({"zone_id": 1}, warnings) == [{"zone_id": 1}]
    assert zone_handler._coerce_zone_items(None, warnings) == []
    assert zone_handler._coerce_zone_items(3, warnings) == []

    zone_handler._apply_zone_fields(zone, {"name": "Z", "enabled": True}, warnings)
    assert zone.name == "Z"

    changed.clear()
    zone_handler._apply_zone_attribs(
        zone, {"name": "  New ", "area_id": 2, "definition": "Entry", "flags": [1], "x": 1}, changed
    )
    assert zone.name == "New"
    assert zone.area_id == 2
    assert zone.definition == "Entry"
    assert zone.flags == [1]
    assert zone.attribs["x"] == 1

    assert zone_handler._coerce_zone_id(1) == 1
    assert zone_handler._coerce_zone_id("2") == 2
    assert zone_handler._coerce_zone_id({"zone_id": 3}) == 3
    assert zone_handler._coerce_zone_id(0) is None

    assert zone_handler._normalize_name(None) is None
    assert zone_handler._normalize_name("   ") is None
    assert zone_handler._normalize_name(" Name ") == "Name"

    assert zone_handler._dedupe_sorted([2, 1, 1, 0]) == [1, 2]
    assert zone_handler._extract_int({"table_elements": 2}, "table_elements") == 2
    assert zone_handler._extract_int({"table_elements": "bad"}, "table_elements") is None

    state.zone_defs_by_id[1] = {"definition": "Entry"}
    assert zone_handler._resolve_zone_def_id(state, "Entry") == 1
    assert zone_handler._resolve_zone_def_id(state, "Missing") is None
    assert zone_handler._has_configured_zone_ids({"zones": []}) is True
