from __future__ import annotations

from typing import Any, cast

import pytest

from elke27_lib import generators
from elke27_lib.features import area as features_area
from elke27_lib.features import control as features_control
from elke27_lib.states import PanelState


def test_generators_dunder_getattr() -> None:
    commands = generators.COMMANDS
    assert isinstance(commands, dict)
    assert generators.CommandSpec is not None
    with pytest.raises(AttributeError):
        _ = generators.NOT_A_REAL_ATTR


def test_generator_area_validations() -> None:
    payload, route = generators.area.generator_area_get_configured(block_id=2)
    assert payload == {"block_id": 2}
    assert route == ("area", "get_configured")
    payload, route = generators.area.generator_area_set_arm_state(
        area_id=1, arm_state="ARMED_STAY", pin=1234
    )
    assert payload == {
        "area_id": 1,
        "arm_state": "ARMED_STAY",
        "pin": 1234,
        "auto_stay_cancel": False,
        "exit_delay_cancel": False,
    }
    assert route == ("area", "set_arm_state")
    with pytest.raises(ValueError):
        generators.area.generator_area_set_arm_state(area_id=0, arm_state="ARMED_STAY", pin=1234)
    with pytest.raises(ValueError):
        generators.area.generator_area_get_configured(block_id=0)
    with pytest.raises(ValueError):
        generators.area.generator_area_get_status(area_id=0)
    with pytest.raises(ValueError):
        generators.area.generator_area_get_attribs(area_id=0)
    with pytest.raises(ValueError):
        generators.area.generator_area_set_status(area_id=0, chime=True)
    with pytest.raises(ValueError):
        generators.area.generator_area_set_arm_state(area_id=1, arm_state="BAD", pin=1234)
    with pytest.raises(ValueError):
        generators.area.generator_area_set_arm_state(area_id=1, arm_state="ARMED_STAY", pin=0)


def test_generator_control_authenticate_validations() -> None:
    payload, route = generators.control.generator_control_authenticate(pin=0)
    assert payload == {"pin": 0}
    assert route == ("control", "authenticate")
    with pytest.raises(ValueError):
        generators.control.generator_control_authenticate(pin=-1)
    with pytest.raises(ValueError):
        generators.control.generator_control_authenticate(pin=1_000_000)


def test_generator_keypad_validations() -> None:
    payload, route = generators.keypad.generator_keypad_get_configured(block_id=1)
    assert payload == {"block_id": 1}
    assert route == ("keypad", "get_configured")
    payload, route = generators.keypad.generator_keypad_get_table_info()
    assert payload == {}
    assert route == ("keypad", "get_table_info")
    with pytest.raises(ValueError):
        generators.keypad.generator_keypad_get_configured(block_id=0)
    with pytest.raises(ValueError):
        generators.keypad.generator_keypad_get_attribs(keypad_id=0)


def test_generator_network_param() -> None:
    payload, route = generators.network_param.generator_network_param_get_ssid()
    assert payload == {}
    assert route == ("network", "get_ssid")
    payload, route = generators.network_param.generator_network_param_get_rssi()
    assert payload == {}
    assert route == ("network", "get_rssi")


def test_generator_output_validations() -> None:
    payload, route = generators.output.generator_output_get_configured(block_id=1)
    assert payload == {"block_id": 1}
    assert route == ("output", "get_configured")
    payload, route = generators.output.generator_output_set_status(output_id=1, status="ON")
    assert payload == {"output_id": 1, "status": "ON"}
    assert route == ("output", "set_status")
    with pytest.raises(ValueError):
        generators.output.generator_output_set_status(output_id=0, status="ON")
    with pytest.raises(ValueError):
        generators.output.generator_output_get_configured(block_id=0)
    with pytest.raises(ValueError):
        generators.output.generator_output_get_status(output_id=0)
    with pytest.raises(ValueError):
        generators.output.generator_output_set_status(output_id=1, status="BAD")
    with pytest.raises(ValueError):
        generators.output.generator_output_get_attribs(output_id=0)
    with pytest.raises(ValueError):
        generators.output.generator_output_get_all_outputs_status(block_id=0)
    payload, route = generators.output.generator_output_get_available()
    assert payload == {}
    assert route == ("output", "get_available")


def test_generator_rule_validations() -> None:
    payload, route = generators.rule.generator_rule_get_rules(block_id=0)
    assert payload == {"block_id": 0}
    assert route == ("rule", "get_rules")
    with pytest.raises(ValueError):
        generators.rule.generator_rule_get_rules(block_id=-1)


def test_generator_tstat_validations() -> None:
    payload, route = generators.tstat.generator_tstat_get_table_info()
    assert payload == {}
    assert route == ("tstat", "get_table_info")
    payload, route = generators.tstat.generator_tstat_get_status(tstat_id=1)
    assert payload == {"tstat_id": 1}
    assert route == ("tstat", "get_status")
    payload, route = generators.tstat.generator_tstat_get_configured(block_id=1)
    assert payload == {"block_id": 1}
    assert route == ("tstat", "get_configured")
    payload, route = generators.tstat.generator_tstat_get_attribs(tstat_id=1)
    assert payload == {"tstat_id": 1}
    assert route == ("tstat", "get_attribs")
    payload, route = generators.tstat.generator_tstat_set_status(tstat_id=1, mode="COOL")
    assert payload == {"tstat_id": 1, "mode": "COOL"}
    assert route == ("tstat", "set_status")
    with pytest.raises(ValueError):
        generators.tstat.generator_tstat_get_status(tstat_id=0)
    with pytest.raises(ValueError):
        generators.tstat.generator_tstat_get_configured(block_id=0)
    with pytest.raises(ValueError):
        generators.tstat.generator_tstat_get_attribs(tstat_id=0)
    with pytest.raises(ValueError):
        generators.tstat.generator_tstat_set_status(tstat_id=1)


def test_generator_light_validations() -> None:
    payload, route = generators.light.generator_light_get_table_info()
    assert payload == {}
    assert route == ("light", "get_table_info")
    payload, route = generators.light.generator_light_get_configured(block_id=1)
    assert payload == {"block_id": 1}
    assert route == ("light", "get_configured")
    payload, route = generators.light.generator_light_get_attribs(light_id=1)
    assert payload == {"light_id": 1}
    assert route == ("light", "get_attribs")
    payload, route = generators.light.generator_light_get_status(light_id=1)
    assert payload == {"light_id": 1}
    assert route == ("light", "get_status")
    payload, route = generators.light.generator_light_set_status(light_id=1, status="ON", level=50)
    assert payload == {"light_id": 1, "status": "ON", "level": 50}
    assert route == ("light", "set_status")
    with pytest.raises(ValueError):
        generators.light.generator_light_get_configured(block_id=0)
    with pytest.raises(ValueError):
        generators.light.generator_light_get_attribs(light_id=0)
    with pytest.raises(ValueError):
        generators.light.generator_light_get_status(light_id=0)
    with pytest.raises(ValueError):
        generators.light.generator_light_set_status(light_id=1)


def test_generator_barrier_validations() -> None:
    payload, route = generators.barrier.generator_barrier_get_table_info()
    assert payload == {}
    assert route == ("barrier", "get_table_info")
    payload, route = generators.barrier.generator_barrier_get_configured(block_id=1)
    assert payload == {"block_id": 1}
    assert route == ("barrier", "get_configured")
    payload, route = generators.barrier.generator_barrier_get_attribs(barrier_id=1)
    assert payload == {"barrier_id": 1}
    assert route == ("barrier", "get_attribs")
    payload, route = generators.barrier.generator_barrier_get_status(barrier_id=1)
    assert payload == {"barrier_id": 1}
    assert route == ("barrier", "get_status")
    payload, route = generators.barrier.generator_barrier_set_status(barrier_id=1, status="OPEN")
    assert payload == {"barrier_id": 1, "status": "OPEN"}
    assert route == ("barrier", "set_status")
    with pytest.raises(ValueError):
        generators.barrier.generator_barrier_get_configured(block_id=0)
    with pytest.raises(ValueError):
        generators.barrier.generator_barrier_get_attribs(barrier_id=0)
    with pytest.raises(ValueError):
        generators.barrier.generator_barrier_get_status(barrier_id=0)
    with pytest.raises(ValueError):
        generators.barrier.generator_barrier_set_status(barrier_id=1, status="BAD")


def test_generator_lock_validations() -> None:
    payload, route = generators.lock.generator_lock_get_table_info()
    assert payload == {}
    assert route == ("lock", "get_table_info")
    payload, route = generators.lock.generator_lock_get_configured(block_id=1)
    assert payload == {"block_id": 1}
    assert route == ("lock", "get_configured")
    payload, route = generators.lock.generator_lock_get_attribs(lock_id=1)
    assert payload == {"lock_id": 1}
    assert route == ("lock", "get_attribs")
    payload, route = generators.lock.generator_lock_get_status(lock_id=1)
    assert payload == {"lock_id": 1}
    assert route == ("lock", "get_status")
    payload, route = generators.lock.generator_lock_set_status(lock_id=1, status="ON")
    assert payload == {"lock_id": 1, "status": "ON"}
    assert route == ("lock", "set_status")
    with pytest.raises(ValueError):
        generators.lock.generator_lock_get_configured(block_id=0)
    with pytest.raises(ValueError):
        generators.lock.generator_lock_get_attribs(lock_id=0)
    with pytest.raises(ValueError):
        generators.lock.generator_lock_get_status(lock_id=0)
    with pytest.raises(ValueError):
        generators.lock.generator_lock_set_status(lock_id=1, status="BAD")


def test_generator_user_validations() -> None:
    payload, route = generators.user.generator_user_get_configured(block_id=1)
    assert payload == {"block_id": 1}
    assert route == ("user", "get_configured")
    with pytest.raises(ValueError):
        generators.user.generator_user_get_configured(block_id=0)
    with pytest.raises(ValueError):
        generators.user.generator_user_get_attribs(user_id=0)


def test_generator_zone_validations() -> None:
    payload, route = generators.zone.generator_zone_get_configured(block_id=1)
    assert payload == {"block_id": 1}
    assert route == ("zone", "get_configured")
    payload, route = generators.zone.generator_zone_get_all_zones_status()
    assert payload == {}
    assert route == ("zone", "get_all_zones_status")
    payload, route = generators.zone.generator_zone_get_def_flags(definition="FOO")
    assert payload == {"definition": "FOO"}
    assert route == ("zone", "get_def_flags")
    payload, route = generators.zone.generator_zone_get_defs(block_id=1)
    assert payload == {"block_id": 1}
    assert route == ("zone", "get_defs")
    payload, route = generators.zone.generator_zone_set_status(zone_id=1, pin=1234, bypassed=True)
    assert payload == {"zone_id": 1, "pin": 1234, "BYPASSED": True}
    assert route == ("zone", "set_status")
    with pytest.raises(ValueError):
        generators.zone.generator_zone_set_status(zone_id=0, pin=1234, bypassed=True)
    with pytest.raises(ValueError):
        generators.zone.generator_zone_get_configured(block_id=0)
    with pytest.raises(ValueError):
        generators.zone.generator_zone_get_status(zone_id=0)
    with pytest.raises(ValueError):
        generators.zone.generator_zone_get_attribs(zone_id=0)
    with pytest.raises(ValueError):
        generators.zone.generator_zone_get_defs(block_id=0)
    with pytest.raises(ValueError):
        generators.zone.generator_zone_get_def_flags(definition=" ")


def test_generator_system_validations() -> None:
    payload, route = generators.system.generator_system_get_trouble()
    assert payload == {}
    assert route == ("system", "get_trouble")
    payload, route = generators.system.generator_system_get_troubles()
    assert payload == {}
    assert route == ("system", "get_troubles")
    payload, route = generators.system.generator_system_get_table_info()
    assert payload == {}
    assert route == ("system", "get_table_info")
    payload, route = generators.system.generator_system_get_attribs()
    assert payload == {}
    assert route == ("system", "get_attribs")
    payload, route = generators.system.generator_system_set_attribs(foo=1)
    assert payload == {"foo": 1}
    assert route == ("system", "set_attribs")
    payload, route = generators.system.generator_system_get_cutoffs()
    assert payload == {}
    assert route == ("system", "get_cutoffs")
    payload, route = generators.system.generator_system_set_cutoffs(bar=2)
    assert payload == {"bar": 2}
    assert route == ("system", "set_cutoffs")
    payload, route = generators.system.generator_system_get_sounders(sounder_id=2)
    assert payload == {"sounder_id": 2}
    assert route == ("system", "get_sounders")
    payload, route = generators.system.generator_system_get_system_time()
    assert payload == {}
    assert route == ("system", "get_system_time")
    payload, route = generators.system.generator_system_set_system_time(
        tz_offset=-5, city_index=1, gmt_seconds=10, dst_active=True
    )
    assert payload == {
        "tz_offset": -5,
        "city_index": 1,
        "gmt_seconds": 10,
        "dst_active": True,
    }
    assert route == ("system", "set_system_time")
    payload, route = generators.system.generator_system_set_system_key(key=1)
    assert payload == {"key": 1}
    assert route == ("system", "set_system_key")
    payload, route = generators.system.generator_system_file_info(file_list=True)
    assert payload == {"file_list": True}
    assert route == ("system", "file_info")
    payload, route = generators.system.generator_system_file_info(file_num=2)
    assert payload == {"file_num": 2}
    assert route == ("system", "file_info")
    payload, route = generators.system.generator_system_get_debug_flags()
    assert payload == {}
    assert route == ("system", "get_debug_flags")
    payload, route = generators.system.generator_system_set_debug_flags(dbug=[1, 2])
    assert payload == {"dbug": [1, 2]}
    assert route == ("system", "set_debug_flags")
    payload, route = generators.system.generator_system_set_debug_flags(dbug_id=3)
    assert payload == {"dbug_id": 3}
    payload, route = generators.system.generator_system_set_debug_flags(dbug_not_id=4)
    assert payload == {"dbug_not_id": 4}
    payload, route = generators.system.generator_system_get_debug_string(dbug_id=5)
    assert payload == {"dbug_id": 5}
    assert route == ("system", "get_debug_string")
    payload, route = generators.system.generator_system_r_u_alive()
    assert payload == {}
    assert route == ("system", "r_u_alive")
    payload, route = generators.system.generator_system_reset_smokes()
    assert payload == {"reset_smokes": True}
    assert route == ("system", "reset_smokes")
    payload, route = generators.system.generator_system_set_run(app="ELK")
    assert payload == {"app": "ELK"}
    assert route == ("system", "set_run")
    payload, route = generators.system.generator_system_start_updt(device_id="dev", ft=0)
    assert payload == {"device_id": "dev", "ft": 0}
    assert route == ("system", "start_updt")
    payload, route = generators.system.generator_system_reconfig()
    assert payload == {}
    assert route == ("system", "reconfig")
    payload, route = generators.system.generator_system_get_update()
    assert payload == {}
    assert route == ("system", "get_update")
    with pytest.raises(ValueError):
        generators.system.generator_system_get_sounders(sounder_id=-1)
    with pytest.raises(ValueError):
        generators.system.generator_system_set_attribs()
    with pytest.raises(ValueError):
        generators.system.generator_system_set_cutoffs()
    with pytest.raises(ValueError):
        generators.system.generator_system_set_system_time(
            tz_offset=0, city_index=-1, gmt_seconds=0, dst_active=False
        )
    with pytest.raises(ValueError):
        generators.system.generator_system_set_system_time(
            tz_offset=0, city_index=0, gmt_seconds=-1, dst_active=False
        )
    with pytest.raises(ValueError):
        generators.system.generator_system_set_system_key(key=-1)
    with pytest.raises(ValueError):
        generators.system.generator_system_file_info()
    with pytest.raises(ValueError):
        generators.system.generator_system_file_info(file_num=-1)
    with pytest.raises(ValueError):
        generators.system.generator_system_set_debug_flags()
    with pytest.raises(ValueError):
        generators.system.generator_system_set_debug_flags(dbug_id=-1)
    with pytest.raises(ValueError):
        generators.system.generator_system_set_debug_flags(dbug_not_id=-1)
    with pytest.raises(ValueError):
        generators.system.generator_system_get_debug_string(dbug_id=-1)
    with pytest.raises(ValueError):
        generators.system.generator_system_set_run(app=" ")
    with pytest.raises(ValueError):
        generators.system.generator_system_start_updt(device_id=" ", ft=1)
    with pytest.raises(ValueError):
        generators.system.generator_system_start_updt(device_id="ok", ft=-1)


class _KernelStub:
    def __init__(self) -> None:
        self.state = PanelState()
        self.emit = lambda *args, **kwargs: None
        self.now = lambda: 0.0
        self.registered_handlers: list[tuple[tuple[str, str], object]] = []
        self.registered_requests: list[tuple[tuple[str, str], object]] = []
        self.registered_paged: list[tuple[tuple[str, str], object, object]] = []

    def register_handler(self, route: tuple[str, str], handler: object) -> None:
        self.registered_handlers.append((route, handler))

    def register_request(self, route: tuple[str, str], builder: object) -> None:
        self.registered_requests.append((route, builder))

    def register_paged(
        self, route: tuple[str, str], merge_fn: object, request_block: object
    ) -> None:
        self.registered_paged.append((route, merge_fn, request_block))


def test_features_area_register_and_builders() -> None:
    elk = _KernelStub()
    features_area.register(cast(Any, elk))
    assert features_area.ROUTE_AREA_GET_CONFIGURED in [
        route for route, _, _ in elk.registered_paged
    ]
    route, _, request_block = elk.registered_paged[0]
    requested: list[tuple[tuple[str, str], dict[str, object]]] = []
    cast(Any, elk).request = lambda r, **kw: requested.append((r, kw))
    cast(Any, request_block)(2, object())
    assert requested
    handler_routes = [route for route, _ in elk.registered_handlers]
    assert features_area.ROUTE_AREA_GET_STATUS in handler_routes
    assert features_area.ROUTE_AREA_GET_ATTRIBS in handler_routes
    assert features_area.ROUTE_AREA_GET_CONFIGURED in handler_routes
    assert features_area.ROUTE_AREA_GET_TABLE_INFO in handler_routes
    assert features_area.ROUTE_AREA_TABLE_INFO in handler_routes
    assert features_area.ROUTE_AREA_GET_TROUBLES in handler_routes
    assert features_area.ROUTE_AREA_GET_TROUBLE in handler_routes
    assert features_area.ROUTE_AREA_SET_STATUS in handler_routes
    assert features_area.ROUTE_AREA_ROOT in handler_routes
    request_routes = [route for route, _ in elk.registered_requests]
    assert features_area.ROUTE_AREA_GET_STATUS in request_routes
    assert features_area.ROUTE_AREA_GET_ATTRIBS in request_routes
    assert features_area.ROUTE_AREA_GET_CONFIGURED in request_routes
    assert features_area.ROUTE_AREA_GET_TABLE_INFO in request_routes
    assert features_area.ROUTE_AREA_GET_TROUBLES in request_routes
    assert features_area.build_area_get_status_payload(area_id=1) == {"area_id": 1}
    assert features_area.build_area_get_attribs_payload(area_id=1) == {"area_id": 1}
    assert features_area.build_area_get_configured_payload(block_id=1) == {"block_id": 1}
    assert features_area.build_area_get_troubles_payload(area_id=1) == {"area_id": 1}
    assert features_area.build_area_get_table_info_payload() == {}
    with pytest.raises(ValueError):
        features_area.build_area_get_status_payload(area_id=0)
    with pytest.raises(ValueError):
        features_area.build_area_get_attribs_payload(area_id=0)
    with pytest.raises(ValueError):
        features_area.build_area_get_configured_payload(block_id=0)
    with pytest.raises(ValueError):
        features_area.build_area_get_troubles_payload(area_id=0)


def test_features_control_register_and_builders() -> None:
    elk = _KernelStub()
    features_control.register(cast(Any, elk))
    handler_routes = [route for route, _ in elk.registered_handlers]
    assert features_control.ROUTE_CONTROL_GET_VERSION_INFO in handler_routes
    assert features_control.ROUTE_CONTROL_AUTHENTICATE in handler_routes
    assert features_control.ROUTE_CONTROL_GET_TROUBLE in handler_routes
    request_routes = [route for route, _ in elk.registered_requests]
    assert features_control.ROUTE_CONTROL_GET_VERSION_INFO in request_routes
    assert features_control.ROUTE_CONTROL_AUTHENTICATE in request_routes
    assert features_control.ROUTE_CONTROL_GET_TROUBLE in request_routes
    assert features_control.build_control_get_version_info_payload() == {}
    assert features_control.build_control_authenticate_payload(pin="1234") == {"pin": 1234}
    assert features_control.build_control_get_trouble_payload() == {}
    with pytest.raises(ValueError):
        features_control.build_control_authenticate_payload(pin="12ab")
    with pytest.raises(ValueError):
        features_control.build_control_authenticate_payload(pin=1_000_000)
