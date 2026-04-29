from __future__ import annotations

from elke27_lib.dispatcher import DispatchContext, PagedBlock
from elke27_lib.events import (
    ApiError,
    AuthorizationRequiredEvent,
    BootstrapCountsReady,
    CsmSnapshotUpdated,
    LightConfiguredInventoryReady,
    LightConfiguredUpdated,
    LightStatusUpdated,
    LightTableInfoUpdated,
    TableCsmChanged,
)
from elke27_lib.handlers import light as light_handler
from elke27_lib.states import LightState, PanelState
from test.helpers.dispatch import make_ctx


class _EmitSpy:
    def __init__(self) -> None:
        self.events: list[object] = []

    def __call__(self, evt: object, _ctx: DispatchContext) -> None:
        self.events.append(evt)


def _any_event(spy: _EmitSpy, kind: type) -> bool:
    return any(isinstance(evt, kind) for evt in spy.events)


def test_light_get_status_and_set_status_handlers() -> None:
    state = PanelState()
    emit = _EmitSpy()
    get_status = light_handler.make_light_get_status_handler(state, emit, now=lambda: 1.0)
    set_status = light_handler.make_light_set_status_handler(state, emit, now=lambda: 2.0)

    assert get_status({"nope": {}}, make_ctx()) is False
    assert get_status({"light": {}}, make_ctx()) is False
    assert set_status({"nope": {}}, make_ctx()) is False
    assert set_status({"light": {}}, make_ctx()) is False

    msg = {"light": {"get_status": {"error_code": 3}}}
    assert get_status(msg, make_ctx()) is True
    assert _any_event(emit, ApiError)

    emit.events.clear()
    msg = {"light": {"get_status": {"light_id": 1, "status": "on", "level": 45}}}
    assert get_status(msg, make_ctx()) is True
    light = state.lights[1]
    assert light.status == "ON"
    assert light.on is True
    assert light.level == 45
    assert _any_event(emit, LightStatusUpdated)

    emit.events.clear()
    msg = {"light": {"set_status": {"light_id": 1, "status": "OFF", "level": 0}}}
    assert set_status(msg, make_ctx()) is True
    assert state.lights[1].on is False
    assert _any_event(emit, LightStatusUpdated)

    assert get_status({"light": {"get_status": {"light_id": 0}}}, make_ctx()) is False
    assert set_status({"light": {"set_status": {"light_id": 0}}}, make_ctx()) is False


def test_light_configured_attribs_table_handlers() -> None:
    state = PanelState()
    emit = _EmitSpy()
    configured = light_handler.make_light_get_configured_handler(state, emit, now=lambda: 3.0)
    attribs = light_handler.make_light_get_attribs_handler(state, emit, now=lambda: 4.0)
    table = light_handler.make_light_get_table_info_handler(state, emit, now=lambda: 5.0)

    msg = {"light": {"get_configured": {"error_code": 11008}}}
    assert configured(msg, make_ctx()) is True
    assert _any_event(emit, AuthorizationRequiredEvent)
    assert configured({"nope": {}}, make_ctx()) is False
    assert configured({"light": {}}, make_ctx()) is False

    emit.events.clear()
    assert configured({"light": {"get_configured": {"error_code": 7}}}, make_ctx()) is True
    assert _any_event(emit, ApiError)

    emit.events.clear()
    msg = {"light": {"get_configured": {"lights": [1, 2], "block_id": 1, "block_count": 1}}}
    assert configured(msg, make_ctx()) is True
    assert state.inventory.configured_lights == {1, 2}
    assert _any_event(emit, LightConfiguredUpdated)
    assert _any_event(emit, LightConfiguredInventoryReady)

    emit.events.clear()
    state.table_info_by_domain["light"] = {"table_elements": 1}
    msg = {"light": {"get_configured": {"lights": [1, 2], "block_id": 1, "block_count": 1}}}
    assert configured(msg, make_ctx()) is True
    assert state.inventory.configured_lights == {1}

    merge = light_handler.make_light_configured_merge(state)
    merged = merge(
        [
            PagedBlock(block_id=1, payload={"lights": [1]}),
            PagedBlock(block_id=2, payload={"light_ids": [2]}),
        ],
        2,
    )
    assert merged == {"lights": [1, 2], "block_count": 2}

    emit.events.clear()
    msg = {"light": {"get_attribs": {"light_id": 1, "name": " Porch ", "area_id": 2}}}
    assert attribs(msg, make_ctx()) is True
    assert state.lights[1].name == "Porch"
    assert state.lights[1].area_id == 2
    assert attribs({"nope": {}}, make_ctx()) is False
    assert attribs({"light": {}}, make_ctx()) is False
    assert attribs({"light": {"get_attribs": {"light_id": 0}}}, make_ctx()) is False

    emit.events.clear()
    assert (
        attribs({"light": {"get_attribs": {"error_code": 11008, "light_id": 1}}}, make_ctx())
        is True
    )
    assert _any_event(emit, AuthorizationRequiredEvent)

    emit.events.clear()
    assert attribs({"light": {"get_attribs": {"error_code": 4, "light_id": 1}}}, make_ctx()) is True
    assert _any_event(emit, ApiError)

    emit.events.clear()
    assert (
        table({"light": {"table_info": {"table_elements": 1, "increment_size": 2}}}, make_ctx())
        is True
    )
    assert _any_event(emit, LightTableInfoUpdated)

    emit.events.clear()
    state.table_info_known.update({"area", "zone", "output", "tstat"})
    msg = {"light": {"get_table_info": {"table_elements": 2, "table_csm": "7"}}}
    assert table(msg, make_ctx()) is True
    assert _any_event(emit, LightTableInfoUpdated)
    assert _any_event(emit, TableCsmChanged)
    assert _any_event(emit, CsmSnapshotUpdated)
    assert _any_event(emit, BootstrapCountsReady)
    assert table({"nope": {}}, make_ctx()) is False
    assert table({"light": {}}, make_ctx()) is False

    emit.events.clear()
    assert table({"light": {"get_table_info": {"error_code": 5}}}, make_ctx()) is True
    assert _any_event(emit, ApiError)


def test_light_helpers() -> None:
    light = LightState(light_id=1)
    light_handler._apply_light_status_fields(light, {"status": "off", "level": 0, "x": 1})
    assert light.status == "OFF"
    assert light.on is False
    assert light.level == 0
    assert light.fields["x"] == 1

    light_handler._apply_light_attribs(light, {"name": " A ", "area_id": 1, "y": 2})
    assert light.name == "A"
    assert light.area_id == 1
    assert light.fields["y"] == 2
    light_handler._apply_light_status_fields(light, {"level": 5})
    assert light.on is False or light.on is True
    light.on = None
    light_handler._apply_light_status_fields(light, {"level": 5})
    assert light.on is True
    light_handler._apply_light_status_fields(light, {"state": False})
    assert light.status == "OFF"
    light_handler._apply_light_attribs(light, {"name": "   "})
    assert light.name is None

    assert light_handler._extract_configured_ids({"lights": [1, 2, 2, 0]}, ("lights",)) == [1, 2]
    assert light_handler._extract_configured_ids({"none": []}, ("lights",)) == []
    assert light_handler._extract_int({"table_elements": 1}, "table_elements") == 1
    assert light_handler._extract_int({"table_elements": "x"}, "table_elements") is None
    assert light_handler._extract_table_csm({"table_csm": 4}, domain="light") == 4
    assert light_handler._extract_table_csm({"table_csm": "4"}, domain="light") == 4
    assert light_handler._normalize_name(None) is None
    assert light_handler._extract_table_csm({"table_csm": True}, domain="light") is None
    assert light_handler._extract_table_csm({"table_csm": 4.0}, domain="light") == 4
    assert light_handler._extract_table_csm({"table_csm": "bad"}, domain="light") is None
