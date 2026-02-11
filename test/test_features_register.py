from __future__ import annotations

import pytest

from elke27_lib.dispatcher import PagedTransferKey
from elke27_lib.features import (
    bus_ios,
    keypad,
    log,
    network_param,
    output,
    rule,
    system,
    tstat,
    user,
    zone,
)
from elke27_lib.states import PanelState


class _FakeKernel:
    def __init__(self) -> None:
        self.state = PanelState()
        self.handlers: list[tuple[tuple[str, str], object]] = []
        self.requests: list[tuple[tuple[str, str], object]] = []
        self.paged: list[tuple[tuple[str, str], object, object]] = []
        self.sent: list[tuple[tuple[str, str], dict[str, object]]] = []

        def _emit(_evt: object, _ctx: object) -> None:
            return None

        self.emit = _emit
        self.now = lambda: 0.0

    def register_handler(self, route: tuple[str, str], handler: object) -> None:
        self.handlers.append((route, handler))

    def register_request(self, route: tuple[str, str], builder: object) -> None:
        self.requests.append((route, builder))

    def register_paged(
        self, route: tuple[str, str], *, merge_fn: object, request_block: object
    ) -> None:
        self.paged.append((route, merge_fn, request_block))

    def request(self, route: tuple[str, str], **kwargs: object) -> None:
        self.sent.append((route, dict(kwargs)))


def _assert_registered(kernel: _FakeKernel, routes: list[tuple[str, str]]) -> None:
    registered = {route for route, _ in kernel.handlers}
    for route in routes:
        assert route in registered


def _assert_requests(kernel: _FakeKernel, routes: list[tuple[str, str]]) -> None:
    registered = {route for route, _ in kernel.requests}
    for route in routes:
        assert route in registered


def test_bus_ios_register_and_payload() -> None:
    kernel = _FakeKernel()
    bus_ios.register(kernel)
    _assert_registered(kernel, [bus_ios.ROUTE_BUS_IOS_GET_TROUBLE])
    _assert_requests(kernel, [bus_ios.ROUTE_BUS_IOS_GET_TROUBLE])
    assert bus_ios.build_bus_ios_get_trouble_payload() == {}


def test_keypad_register_and_payloads() -> None:
    kernel = _FakeKernel()
    keypad.register(kernel)
    _assert_registered(
        kernel,
        [
            keypad.ROUTE_KEYPAD_GET_CONFIGURED,
            keypad.ROUTE_KEYPAD_GET_ATTRIBS,
            keypad.ROUTE_KEYPAD_GET_TABLE_INFO,
        ],
    )
    _assert_requests(
        kernel,
        [
            keypad.ROUTE_KEYPAD_GET_CONFIGURED,
            keypad.ROUTE_KEYPAD_GET_ATTRIBS,
            keypad.ROUTE_KEYPAD_GET_TABLE_INFO,
        ],
    )
    assert keypad.build_keypad_get_configured_payload(block_id=2) == {"block_id": 2}
    assert keypad.build_keypad_get_attribs_payload(keypad_id=3) == {"keypad_id": 3}
    assert keypad.build_keypad_get_table_info_payload() == {}
    with pytest.raises(ValueError):
        keypad.build_keypad_get_configured_payload(block_id=0)
    with pytest.raises(ValueError):
        keypad.build_keypad_get_attribs_payload(keypad_id=0)


def test_log_register_and_payloads() -> None:
    kernel = _FakeKernel()
    log.register(kernel)
    _assert_registered(
        kernel,
        [
            log.ROUTE_LOG_GET_TROUBLE,
            log.ROUTE_LOG_GET_INDEX,
            log.ROUTE_LOG_GET_TABLE_INFO,
            log.ROUTE_LOG_GET_ATTRIBS,
            log.ROUTE_LOG_SET_ATTRIBS,
            log.ROUTE_LOG_GET_LIST,
            log.ROUTE_LOG_GET_LOG,
            log.ROUTE_LOG_CLEAR,
            log.ROUTE_LOG_REALLOC,
        ],
    )
    _assert_requests(
        kernel,
        [
            log.ROUTE_LOG_GET_TROUBLE,
            log.ROUTE_LOG_GET_INDEX,
            log.ROUTE_LOG_GET_TABLE_INFO,
            log.ROUTE_LOG_GET_ATTRIBS,
            log.ROUTE_LOG_GET_LIST,
            log.ROUTE_LOG_GET_LOG,
        ],
    )
    assert log.build_log_get_trouble_payload() == {}
    assert log.build_log_get_index_payload() == {}
    assert log.build_log_get_table_info_payload() == {}
    assert log.build_log_get_attribs_payload() == {}
    assert log.build_log_get_list_payload(start=1, date=2, cnt=3) == {
        "start": 1,
        "date": 2,
        "cnt": 3,
    }
    assert log.build_log_get_log_payload(log_id=4) == {"log_id": 4}


def test_network_param_register_and_payloads() -> None:
    kernel = _FakeKernel()
    network_param.register(kernel)
    _assert_registered(
        kernel,
        [
            network_param.ROUTE_NETWORK_GET_SSID,
            network_param.ROUTE_NETWORK_GET_RSSI,
            network_param.ROUTE_NETWORK_ERROR,
        ],
    )
    _assert_requests(
        kernel,
        [
            network_param.ROUTE_NETWORK_GET_SSID,
            network_param.ROUTE_NETWORK_GET_RSSI,
        ],
    )
    assert network_param.build_network_get_ssid_payload() == {}
    assert network_param.build_network_get_rssi_payload() == {}


def test_output_register_and_payloads() -> None:
    kernel = _FakeKernel()
    output.register(kernel)
    _assert_registered(
        kernel,
        [
            output.ROUTE_OUTPUT_GET_STATUS,
            output.ROUTE_OUTPUT_GET_CONFIGURED,
            output.ROUTE_OUTPUT_GET_ALL_OUTPUTS_STATUS,
            output.ROUTE_OUTPUT_GET_ATTRIBS,
            output.ROUTE_OUTPUT_GET_TABLE_INFO,
            output.ROUTE_OUTPUT_TABLE_INFO,
        ],
    )
    _assert_requests(
        kernel,
        [
            output.ROUTE_OUTPUT_GET_STATUS,
            output.ROUTE_OUTPUT_GET_CONFIGURED,
            output.ROUTE_OUTPUT_GET_ALL_OUTPUTS_STATUS,
            output.ROUTE_OUTPUT_GET_ATTRIBS,
            output.ROUTE_OUTPUT_GET_TABLE_INFO,
        ],
    )
    assert output.build_output_get_status_payload(output_id=2) == {"output_id": 2}
    assert output.build_output_get_attribs_payload(output_id=4) == {"output_id": 4}
    assert output.build_output_get_all_outputs_status_payload() is True
    assert output.build_output_get_table_info_payload() == {}
    assert output.build_output_get_configured_payload(block_id=2) == {"block_id": 2}
    with pytest.raises(ValueError):
        output.build_output_get_status_payload(output_id=0)
    with pytest.raises(ValueError):
        output.build_output_get_attribs_payload(output_id=0)
    with pytest.raises(ValueError):
        output.build_output_get_configured_payload(block_id=0)

    assert kernel.paged
    route, _merge_fn, request_block = kernel.paged[0]
    transfer_key = PagedTransferKey(session_id=1, transfer_id=2, route=route)
    request_block(3, transfer_key)
    assert kernel.sent == [
        (output.ROUTE_OUTPUT_GET_CONFIGURED, {"block_id": 3, "opaque": transfer_key})
    ]


def test_rule_register_and_payloads() -> None:
    kernel = _FakeKernel()
    rule.register(kernel)
    _assert_registered(kernel, [rule.ROUTE_RULE_GET_RULES])
    _assert_requests(kernel, [rule.ROUTE_RULE_GET_RULES])
    assert rule.build_rule_get_rules_payload(block_id=0) == {"block_id": 0}
    with pytest.raises(ValueError):
        rule.build_rule_get_rules_payload(block_id=-1)


def test_system_register_and_payloads() -> None:
    kernel = _FakeKernel()
    system.register(kernel)
    _assert_registered(
        kernel,
        [
            system.ROUTE_SYSTEM_GET_TROUBLE,
            system.ROUTE_SYSTEM_GET_TROUBLES,
            system.ROUTE_SYSTEM_GET_TABLE_INFO,
            system.ROUTE_SYSTEM_GET_ATTRIBS,
            system.ROUTE_SYSTEM_SET_ATTRIBS,
            system.ROUTE_SYSTEM_GET_CUTOFFS,
            system.ROUTE_SYSTEM_SET_CUTOFFS,
            system.ROUTE_SYSTEM_GET_SOUNDERS,
            system.ROUTE_SYSTEM_GET_SYSTEM_TIME,
            system.ROUTE_SYSTEM_SET_SYSTEM_TIME,
            system.ROUTE_SYSTEM_SET_SYSTEM_KEY,
            system.ROUTE_SYSTEM_FILE_INFO,
            system.ROUTE_SYSTEM_GET_DEBUG_FLAGS,
            system.ROUTE_SYSTEM_SET_DEBUG_FLAGS,
            system.ROUTE_SYSTEM_GET_DEBUG_STRING,
            system.ROUTE_SYSTEM_R_U_ALIVE,
            system.ROUTE_SYSTEM_RESET_SMOKES,
            system.ROUTE_SYSTEM_SET_RUN,
            system.ROUTE_SYSTEM_START_UPDT,
            system.ROUTE_SYSTEM_RECONFIG,
            system.ROUTE_SYSTEM_GET_UPDATE,
        ],
    )
    _assert_requests(
        kernel,
        [
            system.ROUTE_SYSTEM_GET_TROUBLE,
            system.ROUTE_SYSTEM_GET_TROUBLES,
            system.ROUTE_SYSTEM_GET_TABLE_INFO,
            system.ROUTE_SYSTEM_GET_ATTRIBS,
            system.ROUTE_SYSTEM_SET_ATTRIBS,
            system.ROUTE_SYSTEM_GET_CUTOFFS,
            system.ROUTE_SYSTEM_SET_CUTOFFS,
            system.ROUTE_SYSTEM_GET_SOUNDERS,
            system.ROUTE_SYSTEM_GET_SYSTEM_TIME,
            system.ROUTE_SYSTEM_SET_SYSTEM_TIME,
            system.ROUTE_SYSTEM_SET_SYSTEM_KEY,
            system.ROUTE_SYSTEM_FILE_INFO,
            system.ROUTE_SYSTEM_GET_DEBUG_FLAGS,
            system.ROUTE_SYSTEM_SET_DEBUG_FLAGS,
            system.ROUTE_SYSTEM_GET_DEBUG_STRING,
            system.ROUTE_SYSTEM_R_U_ALIVE,
            system.ROUTE_SYSTEM_RESET_SMOKES,
            system.ROUTE_SYSTEM_SET_RUN,
            system.ROUTE_SYSTEM_START_UPDT,
            system.ROUTE_SYSTEM_RECONFIG,
            system.ROUTE_SYSTEM_GET_UPDATE,
        ],
    )
    assert system.build_system_get_trouble_payload() == {}
    assert system.build_system_get_table_info_payload() == {}
    assert system.build_system_get_attribs_payload() == {}
    assert system.build_system_set_attribs_payload(foo=1) == {"foo": 1}
    assert system.build_system_get_cutoffs_payload() == {}
    assert system.build_system_set_cutoffs_payload(bar=2) == {"bar": 2}
    assert system.build_system_get_sounders_payload(sounder_id=2) == {"sounder_id": 2}
    assert system.build_system_get_sounders_payload() == {}
    assert system.build_system_get_system_time_payload() == {}
    assert system.build_system_set_system_time_payload(
        tz_offset=-5, city_index=1, gmt_seconds=10, dst_active=True
    ) == {"tz_offset": -5, "city_index": 1, "gmt_seconds": 10, "dst_active": True}
    assert system.build_system_set_system_key_payload(key=3) == {"key": 3}
    assert system.build_system_file_info_payload(file_list=True) == {"file_list": True}
    assert system.build_system_file_info_payload(file_num=1) == {"file_num": 1}
    assert system.build_system_get_debug_flags_payload() == {}
    assert system.build_system_set_debug_flags_payload(dbug=[1]) == {"dbug": [1]}
    assert system.build_system_set_debug_flags_payload(dbug_id=2) == {"dbug_id": 2}
    assert system.build_system_set_debug_flags_payload(dbug_not_id=3) == {"dbug_not_id": 3}
    assert system.build_system_get_debug_string_payload(dbug_id=4) == {"dbug_id": 4}
    assert system.build_system_r_u_alive_payload() == {}
    assert system.build_system_reset_smokes_payload() == {"reset_smokes": True}
    assert system.build_system_set_run_payload(app="foo") == {"app": "foo"}
    assert system.build_system_start_updt_payload(device_id="dev", ft=1) == {
        "device_id": "dev",
        "ft": 1,
    }
    assert system.build_system_reconfig_payload() == {}
    assert system.build_system_get_update_payload() == {}

    with pytest.raises(ValueError):
        system.build_system_set_attribs_payload()
    with pytest.raises(ValueError):
        system.build_system_set_cutoffs_payload()
    with pytest.raises(ValueError):
        system.build_system_get_sounders_payload(sounder_id=-1)
    with pytest.raises(ValueError):
        system.build_system_set_system_time_payload(
            tz_offset=0, city_index=-1, gmt_seconds=0, dst_active=False
        )
    with pytest.raises(ValueError):
        system.build_system_set_system_time_payload(
            tz_offset=0, city_index=0, gmt_seconds=-1, dst_active=False
        )
    with pytest.raises(ValueError):
        system.build_system_set_system_key_payload(key=-1)
    with pytest.raises(ValueError):
        system.build_system_file_info_payload()
    with pytest.raises(ValueError):
        system.build_system_file_info_payload(file_num=-1)
    with pytest.raises(ValueError):
        system.build_system_set_debug_flags_payload()
    with pytest.raises(ValueError):
        system.build_system_set_debug_flags_payload(dbug_id=-1)
    with pytest.raises(ValueError):
        system.build_system_set_debug_flags_payload(dbug_not_id=-1)
    with pytest.raises(ValueError):
        system.build_system_get_debug_string_payload(dbug_id=-1)
    with pytest.raises(ValueError):
        system.build_system_set_run_payload(app=" ")
    with pytest.raises(ValueError):
        system.build_system_start_updt_payload(device_id=" ", ft=1)
    with pytest.raises(ValueError):
        system.build_system_start_updt_payload(device_id="dev", ft=-1)


def test_tstat_register_and_payloads() -> None:
    kernel = _FakeKernel()
    tstat.register(kernel)
    _assert_registered(
        kernel,
        [
            tstat.ROUTE_TSTAT_GET_STATUS,
            tstat.ROUTE_TSTAT_GET_TABLE_INFO,
        ],
    )
    _assert_requests(
        kernel,
        [
            tstat.ROUTE_TSTAT_GET_STATUS,
            tstat.ROUTE_TSTAT_GET_TABLE_INFO,
        ],
    )
    assert tstat.build_tstat_get_status_payload(tstat_id=1) == {"tstat_id": 1}
    assert tstat.build_tstat_get_table_info_payload() == {}
    with pytest.raises(ValueError):
        tstat.build_tstat_get_status_payload(tstat_id=0)


def test_user_register_and_payloads() -> None:
    kernel = _FakeKernel()
    user.register(kernel)
    _assert_registered(
        kernel,
        [
            user.ROUTE_USER_GET_CONFIGURED,
            user.ROUTE_USER_GET_ATTRIBS,
        ],
    )
    _assert_requests(
        kernel,
        [
            user.ROUTE_USER_GET_CONFIGURED,
            user.ROUTE_USER_GET_ATTRIBS,
        ],
    )
    assert user.build_user_get_configured_payload(block_id=1) == {"block_id": 1}
    assert user.build_user_get_attribs_payload(user_id=1) == {"user_id": 1}
    with pytest.raises(ValueError):
        user.build_user_get_configured_payload(block_id=0)
    with pytest.raises(ValueError):
        user.build_user_get_attribs_payload(user_id=0)


def test_zone_register_and_payloads() -> None:
    kernel = _FakeKernel()
    zone.register(kernel)
    _assert_registered(
        kernel,
        [
            zone.ROUTE_ZONE_GET_CONFIGURED,
            zone.ROUTE_ZONE_GET_ATTRIBS,
            zone.ROUTE_ZONE_GET_STATUS,
            zone.ROUTE_ZONE_GET_ALL_ZONES_STATUS,
            zone.ROUTE_ZONE_GET_TABLE_INFO,
            zone.ROUTE_ZONE_TABLE_INFO,
            zone.ROUTE_ZONE_GET_DEFS,
            zone.ROUTE_ZONE_GET_DEF_FLAGS,
            zone.ROUTE_ZONE_SET_STATUS,
        ],
    )
    _assert_requests(
        kernel,
        [
            zone.ROUTE_ZONE_GET_CONFIGURED,
            zone.ROUTE_ZONE_GET_ATTRIBS,
            zone.ROUTE_ZONE_GET_STATUS,
            zone.ROUTE_ZONE_GET_ALL_ZONES_STATUS,
            zone.ROUTE_ZONE_GET_TABLE_INFO,
            zone.ROUTE_ZONE_GET_DEFS,
            zone.ROUTE_ZONE_GET_DEF_FLAGS,
            zone.ROUTE_ZONE_SET_STATUS,
        ],
    )
    assert zone.build_zone_get_configured_payload(block_id=2) == {"block_id": 2}
    assert zone.build_zone_get_all_zones_status_payload() is True
    assert zone.build_zone_get_attribs_payload(zone_id=1) == {"zone_id": 1}
    assert zone.build_zone_get_status_payload(zone_id=1) == {"zone_id": 1}
    assert zone.build_zone_get_table_info_payload() == {}
    assert zone.build_zone_get_defs_payload(block_id=1) == {"block_id": 1}
    assert zone.build_zone_get_def_flags_payload(definition="foo") == {"definition": "foo"}
    assert zone.build_zone_set_status_payload(zone_id=1, pin=1234, bypassed=True) == {
        "zone_id": 1,
        "pin": 1234,
        "BYPASSED": True,
    }
    with pytest.raises(ValueError):
        zone.build_zone_get_configured_payload(block_id=0)
    with pytest.raises(ValueError):
        zone.build_zone_get_attribs_payload(zone_id=0)
    with pytest.raises(ValueError):
        zone.build_zone_get_status_payload(zone_id=0)
    with pytest.raises(ValueError):
        zone.build_zone_get_defs_payload(block_id=0)
    with pytest.raises(ValueError):
        zone.build_zone_get_def_flags_payload(definition=" ")
    with pytest.raises(ValueError):
        zone.build_zone_set_status_payload(zone_id=0, pin=1234, bypassed=False)

    assert kernel.paged
    route, _merge_fn, request_block = kernel.paged[0]
    transfer_key = PagedTransferKey(session_id=2, transfer_id=7, route=route)
    request_block(2, transfer_key)
    assert kernel.sent == [
        (zone.ROUTE_ZONE_GET_CONFIGURED, {"block_id": 2, "opaque": transfer_key})
    ]
