"""Feature-map coverage expansion (Tester, 2026-10-17, hardware-free).

F3 / #62 (feature-map HW report 2026-10-16): the bare-ack cases are covered by
test_set_status_ack_no_stale_event.py (PR #64); only the ack-with-status case
stays here.
Also pins the light 0..100 scale (HACS #91) and tstat mode/fan payloads.
"""

from __future__ import annotations

import pytest

from elke27_lib.events import LightStatusUpdated, OutputStatusUpdated
from elke27_lib.features.light import build_light_set_status_payload
from elke27_lib.features.tstat import build_tstat_set_status_payload
from elke27_lib.handlers import light as light_handler
from elke27_lib.handlers import output as output_handler
from elke27_lib.states import PanelState
from test.helpers.dispatch import EmitSpy, make_ctx


def _of(spy: EmitSpy, kind: type) -> list:
    return [e for e in spy.events if isinstance(e, kind)]


# --- light scale (#91) -------------------------------------------------------


@pytest.mark.parametrize("level", [0, 1, 50, 99, 100])
def test_light_set_status_accepts_full_0_to_100(level: int) -> None:
    assert build_light_set_status_payload(light_id=1, status="ON", level=level)["level"] == level


@pytest.mark.parametrize("level", [-1, 101, 255])
def test_light_set_status_rejects_out_of_range(level: int) -> None:
    with pytest.raises(ValueError, match="level must be 0..100"):
        build_light_set_status_payload(light_id=1, level=level)


def test_light_get_status_level_100_kept() -> None:
    state = PanelState()
    spy = EmitSpy()
    handler = light_handler.make_light_get_status_handler(state, spy, now=lambda: 1.0)
    handler({"light": {"get_status": {"light_id": 1, "status": "ON", "level": 100}}}, make_ctx())
    assert state.lights[1].level == 100


# --- tstat payloads (HVAC + fan modes) --------------------------------------


@pytest.mark.parametrize("mode", ["OFF", "HEAT", "COOL", "AUTO"])
def test_tstat_mode_payload(mode: str) -> None:
    assert build_tstat_set_status_payload(tstat_id=1, mode=mode) == {"tstat_id": 1, "mode": mode}


@pytest.mark.parametrize("fan", ["AUTO", "ON"])
def test_tstat_fan_payload(fan: str) -> None:
    assert build_tstat_set_status_payload(tstat_id=1, fan_mode=fan) == {
        "tstat_id": 1,
        "fan_mode": fan,
    }


def test_tstat_payload_requires_a_field() -> None:
    with pytest.raises(ValueError, match="requires at least one status field"):
        build_tstat_set_status_payload(tstat_id=1)


# --- F3 (#62): set_status ack with a new status -----------------------------------


def _prime_output(state: PanelState) -> None:
    spy = EmitSpy()
    output_handler.make_output_get_status_handler(state, spy, now=lambda: 1.0)(
        {"output": {"get_status": {"output_id": 1, "status": "OFF"}}}, make_ctx()
    )


def test_output_set_status_ack_with_status_reports_new_value() -> None:
    state = PanelState()
    _prime_output(state)
    spy = EmitSpy()
    handler = output_handler.make_output_set_status_handler(state, spy, now=lambda: 2.0)
    handler(
        {"output": {"set_status": {"output_id": 1, "status": "ON", "error_code": 0}}}, make_ctx()
    )
    (evt,) = _of(spy, OutputStatusUpdated)
    assert evt.on is True


def test_light_bare_ack_emits_no_status_event() -> None:
    """A bare light set_status ack keeps the cached level and emits nothing (#89 context)."""
    state = PanelState()
    light_handler.make_light_get_status_handler(state, EmitSpy(), now=lambda: 1.0)(
        {"light": {"get_status": {"light_id": 1, "status": "ON", "level": 100}}}, make_ctx()
    )
    spy = EmitSpy()
    light_handler.make_light_set_status_handler(state, spy, now=lambda: 2.0)(
        {"light": {"set_status": {"light_id": 1, "error_code": 0}}}, make_ctx()
    )
    assert state.lights[1].level == 100  # a bare ack must not zero the cached level
    assert _of(spy, LightStatusUpdated) == []
