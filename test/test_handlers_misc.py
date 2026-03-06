from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from elke27_lib.dispatcher import DispatchContext
from elke27_lib.events import (
    ApiError,
    AuthorizationRequiredEvent,
    BootstrapCountsReady,
    CsmSnapshotUpdated,
    NetworkRssiUpdated,
    NetworkSsidResultsUpdated,
    TableCsmChanged,
    TstatStatusUpdated,
    TstatTableInfoUpdated,
    UserConfiguredInventoryReady,
)
from elke27_lib.handlers import bus_ios, network_param, rule, tstat, user
from elke27_lib.states import PanelState, TstatState, UserState
from test.helpers.dispatch import make_ctx


class _EmitSpy:
    def __init__(self) -> None:
        self.events: list[object] = []

    def __call__(self, evt: object, _ctx: DispatchContext) -> None:
        self.events.append(evt)


def _any_event(spy: _EmitSpy, kind: type) -> bool:
    return any(isinstance(evt, kind) for evt in spy.events)


def test_bus_ios_get_trouble_handler_paths() -> None:
    state = PanelState()
    emit = _EmitSpy()
    handler = bus_ios.make_bus_ios_get_trouble_handler(state, emit, now=lambda: 1.0)

    assert handler({"nope": {}}, make_ctx()) is False
    assert handler({"bus_io_dev": {}}, make_ctx()) is False

    msg = {"bus_ios": {"get_trouble": {"error_code": 11008}}}
    assert handler(msg, make_ctx()) is True
    assert _any_event(emit, AuthorizationRequiredEvent)

    emit.events.clear()
    msg = {"bus_io_dev": {"get_trouble": {"error_code": 42}}}
    assert handler(msg, make_ctx()) is True
    assert _any_event(emit, ApiError)

    emit.events.clear()
    msg = {"bus_io_dev": {"get_trouble": {"foo": "bar"}}}
    assert handler(msg, make_ctx(classification="BROADCAST")) is True
    assert cast(dict[str, Any], state.bus_io_status["get_trouble"])["foo"] == "bar"
    assert state.panel.last_message_at == 1.0


def test_rule_get_rules_handler_paths() -> None:
    state = PanelState()
    emit = _EmitSpy()
    handler = rule.make_rule_get_rules_handler(state, emit, now=lambda: 2.0)

    assert handler({"nope": {}}, make_ctx()) is False
    assert handler({"rule": {}}, make_ctx()) is False

    msg = {"rule": {"get_rules": {"error_code": 11008}}}
    assert handler(msg, make_ctx()) is True
    assert _any_event(emit, AuthorizationRequiredEvent)

    emit.events.clear()
    msg = {"rule": {"get_rules": {"error_code": 9}}}
    assert handler(msg, make_ctx()) is True
    assert _any_event(emit, ApiError)

    msg = {"rule": {"get_rules": {"block_id": "x"}}}
    assert handler(msg, make_ctx()) is False

    msg = {"rule": {"get_rules": {"block_id": 0, "block_count": 2}}}
    assert handler(msg, make_ctx()) is True
    assert state.rules == {}
    assert state.rules_block_count == 2

    msg = {"rule": {"get_rules": {"block_id": 1, "block_count": 2, "data": "rule1"}}}
    assert handler(msg, make_ctx()) is True
    assert state.rules[1]["data"] == "rule1"
    assert state.panel.last_message_at == 2.0


def test_network_param_get_ssid_handler_paths() -> None:
    state = PanelState()
    emit = _EmitSpy()
    handler = network_param.make_network_param_get_ssid_handler(state, emit, now=lambda: 3.0)

    assert handler({"nope": {}}, make_ctx()) is False

    msg = {"network": {"get_ssid": {"error_code": 11008}}}
    assert handler(msg, make_ctx()) is True
    assert _any_event(emit, AuthorizationRequiredEvent)

    emit.events.clear()
    msg = {"network": {"error_code": 9, "get_ssid": {"error_code": 9}}}
    assert handler(msg, make_ctx()) is True
    assert _any_event(emit, ApiError)

    emit.events.clear()
    msg = {"network": {"get_ssid": {"ssids": ["a", {"ssid": "b"}, 4]}}}
    assert handler(msg, make_ctx()) is True
    assert state.network.ssid_scan_results == [{"ssid": "a"}, {"ssid": "b"}]
    assert _any_event(emit, NetworkSsidResultsUpdated)

    msg = {"network": {"get_ssid": {"ssid": "single"}}}
    assert handler(msg, make_ctx()) is True
    assert state.network.ssid_scan_results == [{"ssid": "single"}]

    msg = {"network": {"get_ssid": {"foo": "bar"}}}
    assert handler(msg, make_ctx()) is True
    assert state.network.ssid_scan_results == [{"foo": "bar"}]

    msg = {"network": {"get_ssid": ["x", "y"]}}
    assert handler(msg, make_ctx()) is True
    assert state.network.last_update_at == 3.0


def test_network_param_get_rssi_and_error_handler() -> None:
    state = PanelState()
    emit = _EmitSpy()
    handler = network_param.make_network_param_get_rssi_handler(state, emit, now=lambda: 4.0)

    assert handler({"nope": {}}, make_ctx()) is False

    msg = {"network": {"get_rssi": {"error_code": 11008}}}
    assert handler(msg, make_ctx()) is True
    assert _any_event(emit, AuthorizationRequiredEvent)

    emit.events.clear()
    msg = {"network": {"error_code": 8, "get_rssi": {"error_code": 8}}}
    assert handler(msg, make_ctx()) is True
    assert _any_event(emit, ApiError)

    emit.events.clear()
    msg = {"network": {"get_rssi": {"rssi": "12"}}}
    assert handler(msg, make_ctx()) is True
    assert state.network.rssi == 12
    assert _any_event(emit, NetworkRssiUpdated)

    msg = {"network": {"rssi": 5}}
    assert handler(msg, make_ctx()) is True
    assert state.network.rssi == 5

    error_handler = network_param.make_network_error_handler(state, emit, lambda: 0.0)
    assert error_handler({"nope": {}}, make_ctx()) is False
    assert (
        error_handler({"network": {"error_code": "11008", "error_message": "no"}}, make_ctx())
        is True
    )
    assert _any_event(emit, AuthorizationRequiredEvent)
    emit.events.clear()
    assert error_handler({"network": {"error_code": 7, "error_message": "bad"}}, make_ctx()) is True
    assert _any_event(emit, ApiError)
    assert error_handler({"network": {"error_code": "notint"}}, make_ctx()) is False


def test_network_param_helpers() -> None:
    net_obj: Mapping[str, object] = {"get_ssid": ["foo", {"ssid": "bar"}, 1]}
    assert network_param._normalize_ssid_results(None, net_obj) == []
    assert network_param._normalize_ssid_results(["a", {"ssid": "b"}], net_obj) == [
        {"ssid": "a"},
        {"ssid": "b"},
    ]
    assert network_param._normalize_ssid_results("solo", net_obj) == [{"ssid": "solo"}]
    assert network_param._normalize_ssid_results({"ssid": "named"}, net_obj) == [{"ssid": "named"}]
    assert network_param._normalize_ssid_results({"foo": "bar"}, net_obj) == [{"foo": "bar"}]
    assert network_param._normalize_ssid_results({"scan": ["x", "y"]}, net_obj) == [
        {"ssid": "x"},
        {"ssid": "y"},
    ]
    assert network_param._normalize_ssid_results(123, net_obj) == [{"ssid": "foo"}, {"ssid": "bar"}]
    assert network_param._normalize_ssid_results(None, {"get_ssid": "bad"}) == []
    assert network_param._normalize_ssid_results(123, {"get_ssid": "bad"}) == []

    assert network_param._extract_rssi({"rssi": 7}, {}) == 7
    assert network_param._extract_rssi({"rssi": "9"}, {}) == 9
    assert network_param._extract_rssi({"rssi": "bad"}, {}) is None
    assert network_param._extract_rssi({"rssi": {}}, {}) is None
    assert network_param._extract_rssi(None, {"rssi": 11}) == 11


def test_tstat_get_status_and_table_info() -> None:
    state = PanelState()
    emit = _EmitSpy()

    status_handler = tstat.make_tstat_get_status_handler(state, emit, now=lambda: 5.0)
    assert status_handler({"nope": {}}, make_ctx()) is False
    assert status_handler({"tstat": {}}, make_ctx()) is False

    msg = {"tstat": {"get_status": {"error_code": 10}}}
    assert status_handler(msg, make_ctx()) is True
    assert _any_event(emit, ApiError)

    msg = {"tstat": {"get_status": {"tstat_id": 0}}}
    assert status_handler(msg, make_ctx()) is False

    emit.events.clear()
    msg = {
        "tstat": {
            "get_status": {
                "tstat_id": 1,
                "temperature": 70,
                "fan_mode": "AUTO",
                "battery level": 99,
                "prec": [1, 2],
                "custom": "x",
            }
        }
    }
    assert status_handler(msg, make_ctx()) is True
    assert state.tstats[1].temperature == 70
    assert state.tstats[1].battery_level == 99
    assert state.tstats[1].prec == [1, 2]
    assert state.tstats[1].fields["custom"] == "x"
    assert _any_event(emit, TstatStatusUpdated)

    table_handler = tstat.make_tstat_get_table_info_handler(state, emit, now=lambda: 6.0)
    assert table_handler({"nope": {}}, make_ctx()) is False
    assert table_handler({"tstat": {}}, make_ctx()) is False

    msg = {"tstat": {"get_table_info": {"error_code": 8}}}
    assert table_handler(msg, make_ctx()) is True
    assert _any_event(emit, ApiError)

    emit.events.clear()
    state.table_info_known.update({"area", "zone", "output"})
    msg = {"tstat": {"table_info": {"table_elements": 2, "table_csm": 4}}}
    assert table_handler(msg, make_ctx()) is True
    assert state.table_info_by_domain["tstat"]["table_elements"] == 2
    assert _any_event(emit, TableCsmChanged)
    assert _any_event(emit, TstatTableInfoUpdated)
    assert _any_event(emit, CsmSnapshotUpdated)
    assert _any_event(emit, BootstrapCountsReady)


def test_tstat_helpers() -> None:
    tstat_state = TstatState(tstat_id=1)
    changed: set[str] = set()
    tstat._apply_tstat_status_fields(
        tstat_state,
        {
            "temperature": 70,
            "cool_setpoint": 68,
            "heat_setpoint": 72,
            "mode": "AUTO",
            "fan_mode": "ON",
            "humidity": 50,
            "rssi": -40,
            "battery_level": 80,
            "prec": [1, "bad"],
            "extra": "x",
        },
        changed,
    )
    assert tstat_state.temperature == 70
    assert tstat_state.cool_setpoint == 68
    assert tstat_state.heat_setpoint == 72
    assert tstat_state.fan_mode == "ON"
    assert tstat_state.humidity == 50
    assert tstat_state.rssi == -40
    assert tstat_state.battery_level == 80
    assert tstat_state.prec is None
    assert tstat_state.fields["extra"] == "x"

    assert tstat._extract_table_csm({"table_csm": True}, domain="tstat") is None
    assert tstat._extract_table_csm({"table_csm": 5}, domain="tstat") == 5
    assert tstat._extract_table_csm({"table_csm": 3.0}, domain="tstat") == 3
    assert tstat._extract_table_csm({"table_csm": "4"}, domain="tstat") == 4
    assert tstat._extract_table_csm({"table_csm": "bad"}, domain="tstat") is None
    assert tstat._extract_table_csm({"other": 1}, domain="tstat") is None


def test_user_handlers() -> None:
    state = PanelState()
    emit = _EmitSpy()
    handler = user.make_user_get_configured_handler(state, emit, now=lambda: 7.0)

    assert handler({"nope": {}}, make_ctx()) is False
    assert handler({"user": {}}, make_ctx()) is False

    msg = {"user": {"get_configured": {"error_code": 11008}}}
    assert handler(msg, make_ctx()) is True
    assert _any_event(emit, AuthorizationRequiredEvent)

    emit.events.clear()
    msg = {"user": {"get_configured": {"error_code": 9}}}
    assert handler(msg, make_ctx()) is True
    assert _any_event(emit, ApiError)

    emit.events.clear()
    msg = {"user": {"get_configured": {"users": [1, 2], "block_id": 1, "block_count": 1}}}
    assert handler(msg, make_ctx()) is True
    assert state.inventory.configured_users == {1, 2}
    assert state.inventory.configured_users_complete is True
    assert _any_event(emit, UserConfiguredInventoryReady)
    assert state.panel.last_message_at == 7.0

    attribs_handler = user.make_user_get_attribs_handler(state, emit, now=lambda: 8.0)
    assert attribs_handler({"nope": {}}, make_ctx()) is False
    assert attribs_handler({"user": {}}, make_ctx()) is False

    msg = {"user": {"get_attribs": {"error_code": 11008, "user_id": 1}}}
    assert attribs_handler(msg, make_ctx()) is True
    assert _any_event(emit, AuthorizationRequiredEvent)

    emit.events.clear()
    msg = {"user": {"get_attribs": {"error_code": 3, "user_id": 1}}}
    assert attribs_handler(msg, make_ctx()) is True
    assert _any_event(emit, ApiError)

    msg = {"user": {"get_attribs": {"user_id": 0}}}
    assert attribs_handler(msg, make_ctx()) is False

    msg = {
        "user": {
            "get_attribs": {
                "user_id": 1,
                "name": "  Alice ",
                "group_id": 2,
                "enabled": True,
                "pin": 1234,
                "flags": [1],
                "extra": "x",
            }
        }
    }
    assert attribs_handler(msg, make_ctx()) is True
    user_state = state.users[1]
    assert user_state.name == "Alice"
    assert user_state.group_id == 2
    assert user_state.enabled is True
    assert user_state.pin == 1234
    assert user_state.flags == [1]
    assert user_state.fields["extra"] == "x"
    assert state.panel.last_message_at == 8.0


def test_user_helpers() -> None:
    assert user._extract_configured_ids({"users": [1, 0, 2, "x"]}) == {1, 2}
    assert user._extract_configured_ids({"user_ids": [3]}) == {3}
    assert user._extract_configured_ids({"configured_users": [4]}) == {4}
    assert user._extract_configured_ids({"configured_user_ids": [5]}) == {5}
    assert user._extract_configured_ids({"none": []}) == set()
    assert user._normalize_name(None) is None
    assert user._normalize_name("   ") is None
    assert user._normalize_name(" Bob ") == "Bob"

    user_state = UserState(user_id=1)
    changed: set[str] = set()
    user._apply_user_attribs(
        user_state,
        {"name": " Alice ", "group_id": 2, "enabled": True, "pin": 1234, "flags": [1], "x": 1},
        changed,
    )
    assert user_state.name == "Alice"
    assert user_state.group_id == 2
    assert user_state.enabled is True
    assert user_state.pin == 1234
    assert user_state.flags == [1]
    assert user_state.fields["x"] == 1
