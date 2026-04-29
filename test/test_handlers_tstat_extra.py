from __future__ import annotations

from elke27_lib.dispatcher import DispatchContext, PagedBlock
from elke27_lib.events import (
    ApiError,
    AuthorizationRequiredEvent,
    BootstrapCountsReady,
    CsmSnapshotUpdated,
    TableCsmChanged,
    TstatConfiguredInventoryReady,
    TstatConfiguredUpdated,
    TstatStatusUpdated,
    TstatTableInfoUpdated,
)
from elke27_lib.handlers import tstat as tstat_handler
from elke27_lib.states import PanelState, TstatState
from test.helpers.dispatch import make_ctx


class _EmitSpy:
    def __init__(self) -> None:
        self.events: list[object] = []

    def __call__(self, evt: object, _ctx: DispatchContext) -> None:
        self.events.append(evt)


def _any_event(spy: _EmitSpy, kind: type) -> bool:
    return any(isinstance(evt, kind) for evt in spy.events)


def test_tstat_get_status_and_set_status_handlers() -> None:
    state = PanelState()
    emit = _EmitSpy()
    get_status = tstat_handler.make_tstat_get_status_handler(state, emit, now=lambda: 1.0)
    set_status = tstat_handler.make_tstat_set_status_handler(state, emit, now=lambda: 2.0)

    assert get_status({"nope": {}}, make_ctx()) is False
    assert get_status({"tstat": {}}, make_ctx()) is False
    assert set_status({"nope": {}}, make_ctx()) is False
    assert set_status({"tstat": {}}, make_ctx()) is False

    msg = {"tstat": {"get_status": {"error_code": 3}}}
    assert get_status(msg, make_ctx()) is True
    assert _any_event(emit, ApiError)

    emit.events.clear()
    msg = {
        "tstat": {
            "get_status": {
                "tstat_id": 1,
                "temperature": 70,
                "mode": "HEAT",
                "fan_mode": "AUTO",
                "battery level": 95,
            }
        }
    }
    assert get_status(msg, make_ctx()) is True
    tstat = state.tstats[1]
    assert tstat.temperature == 70
    assert tstat.mode == "HEAT"
    assert tstat.fan_mode == "AUTO"
    assert tstat.battery_level == 95
    assert _any_event(emit, TstatStatusUpdated)

    emit.events.clear()
    msg = {"tstat": {"set_status": {"tstat_id": 1, "mode": "COOL", "cool_setpoint": 72}}}
    assert set_status(msg, make_ctx()) is True
    assert state.tstats[1].mode == "COOL"
    assert state.tstats[1].cool_setpoint == 72
    assert _any_event(emit, TstatStatusUpdated)
    emit.events.clear()
    assert (
        set_status({"tstat": {"set_status": {"error_code": 4, "tstat_id": 1}}}, make_ctx()) is True
    )
    assert _any_event(emit, ApiError)
    assert get_status({"tstat": {"get_status": {"tstat_id": 0}}}, make_ctx()) is False
    assert set_status({"tstat": {"set_status": {"tstat_id": 0}}}, make_ctx()) is False


def test_tstat_configured_attribs_table_handlers() -> None:
    state = PanelState()
    emit = _EmitSpy()
    configured = tstat_handler.make_tstat_get_configured_handler(state, emit, now=lambda: 3.0)
    attribs = tstat_handler.make_tstat_get_attribs_handler(state, emit, now=lambda: 4.0)
    table = tstat_handler.make_tstat_get_table_info_handler(state, emit, now=lambda: 5.0)

    msg = {"tstat": {"get_configured": {"error_code": 11008}}}
    assert configured(msg, make_ctx()) is True
    assert _any_event(emit, AuthorizationRequiredEvent)
    assert configured({"nope": {}}, make_ctx()) is False
    assert configured({"tstat": {}}, make_ctx()) is False

    emit.events.clear()
    assert configured({"tstat": {"get_configured": {"error_code": 7}}}, make_ctx()) is True
    assert _any_event(emit, ApiError)

    emit.events.clear()
    msg = {"tstat": {"get_configured": {"tstats": [1, 2], "block_id": 1, "block_count": 1}}}
    assert configured(msg, make_ctx()) is True
    assert state.inventory.configured_tstats == {1, 2}
    assert state.inventory.configured_tstats_complete is True
    assert _any_event(emit, TstatConfiguredUpdated)
    assert _any_event(emit, TstatConfiguredInventoryReady)

    emit.events.clear()
    state.table_info_by_domain["tstat"] = {"table_elements": 1}
    msg = {"tstat": {"get_configured": {"tstats": [1, 2], "block_id": 1, "block_count": 1}}}
    assert configured(msg, make_ctx()) is True
    assert state.inventory.configured_tstats == {1}

    merge = tstat_handler.make_tstat_configured_merge(state)
    merged = merge(
        [
            PagedBlock(block_id=1, payload={"tstats": [1]}),
            PagedBlock(block_id=2, payload={"tstat_ids": [2]}),
        ],
        2,
    )
    assert merged == {"tstats": [1, 2], "block_count": 2}

    emit.events.clear()
    msg = {"tstat": {"get_attribs": {"tstat_id": 1, "name": " Upstairs ", "x": 1}}}
    assert attribs(msg, make_ctx()) is True
    assert state.tstats[1].name == "Upstairs"
    assert state.tstats[1].fields["x"] == 1
    assert attribs({"nope": {}}, make_ctx()) is False
    assert attribs({"tstat": {}}, make_ctx()) is False
    assert attribs({"tstat": {"get_attribs": {"tstat_id": 0}}}, make_ctx()) is False

    emit.events.clear()
    assert (
        attribs({"tstat": {"get_attribs": {"error_code": 11008, "tstat_id": 1}}}, make_ctx())
        is True
    )
    assert _any_event(emit, AuthorizationRequiredEvent)

    emit.events.clear()
    assert attribs({"tstat": {"get_attribs": {"error_code": 4, "tstat_id": 1}}}, make_ctx()) is True
    assert _any_event(emit, ApiError)

    emit.events.clear()
    assert (
        table({"tstat": {"table_info": {"table_elements": 1, "increment_size": 2}}}, make_ctx())
        is True
    )
    assert _any_event(emit, TstatTableInfoUpdated)

    emit.events.clear()
    state.table_info_known.update({"area", "zone", "output"})
    msg = {"tstat": {"get_table_info": {"table_elements": 1, "table_csm": "6"}}}
    assert table(msg, make_ctx()) is True
    assert _any_event(emit, TstatTableInfoUpdated)
    assert _any_event(emit, TableCsmChanged)
    assert _any_event(emit, CsmSnapshotUpdated)
    assert _any_event(emit, BootstrapCountsReady)
    assert table({"nope": {}}, make_ctx()) is False
    assert table({"tstat": {}}, make_ctx()) is False

    emit.events.clear()
    assert table({"tstat": {"get_table_info": {"error_code": 5}}}, make_ctx()) is True
    assert _any_event(emit, ApiError)


def test_tstat_helpers() -> None:
    tstat = TstatState(tstat_id=1)
    changed: set[str] = set()
    tstat_handler._apply_tstat_status_fields(
        tstat,
        {
            "temperature": 71,
            "cool_setpoint": 73,
            "heat_setpoint": 67,
            "mode": "HEAT",
            "fan_mode": "AUTO",
            "humidity": 40,
            "rssi": -55,
            "battery_level": 93,
            "prec": [1, 2],
            "extra": 1,
        },
        changed,
    )
    assert tstat.temperature == 71
    assert tstat.cool_setpoint == 73
    assert tstat.heat_setpoint == 67
    assert tstat.battery_level == 93
    assert tstat.prec == [1, 2]
    assert tstat.fields["extra"] == 1
    assert "extra" in changed

    changed.clear()
    tstat_handler._apply_tstat_status_fields(tstat, {"prec": [1, "bad"]}, changed)
    assert "prec" not in changed

    changed.clear()
    tstat_handler._apply_tstat_attribs(tstat, {"name": " Main ", "a": 1}, changed)
    assert tstat.name == "Main"
    assert tstat.fields["a"] == 1
    changed.clear()
    tstat_handler._apply_tstat_attribs(tstat, {"name": "   "}, changed)
    assert tstat.name is None
    assert "name" in changed
    changed.clear()
    tstat_handler._maybe_set(tstat, "mode", None, changed)
    assert changed == set()

    assert tstat_handler._extract_configured_tstat_ids({"tstats": [1, 2, 2]}) == [1, 2]
    assert tstat_handler._extract_configured_tstat_ids({"none": []}) == []
    assert tstat_handler._extract_table_csm({"table_csm": "3"}, domain="tstat") == 3
    assert tstat_handler._extract_table_csm({"table_csm": True}, domain="tstat") is None
    assert tstat_handler._extract_table_csm({"table_csm": 3.0}, domain="tstat") == 3
    assert tstat_handler._extract_table_csm({"table_csm": "bad"}, domain="tstat") is None
