from __future__ import annotations

from elke27_lib.const import E27ErrorCode
from elke27_lib.dispatcher_loop import DispatchContext, MessageKind
from elke27_lib.handlers.zone import make_zone_get_status_handler
from elke27_lib.states import PanelState


class _EmitSpy:
    def __init__(self) -> None:
        self.events: list[object] = []

    def __call__(self, evt: object, ctx: DispatchContext) -> None:
        self.events.append(evt)


def _ctx(route: tuple[str, str]) -> DispatchContext:
    return DispatchContext(
        kind=MessageKind.DIRECTED,
        seq=None,
        session_id=None,
        route=route,
        classification="RESPONSE",
    )


def test_zone_status_flags_all_false() -> None:
    state = PanelState()
    emit = _EmitSpy()
    handler = make_zone_get_status_handler(state, emit, now=lambda: 123.0)

    msg = {
        "zone": {
            "get_status": {
                "zone_id": 1,
                "BYPASSED": False,
                "secure_state": "NORMAL",
                "low_batt": False,
                "error_code": E27ErrorCode.ELKERR_NONE,
            }
        }
    }
    assert handler(msg, _ctx(("zone", "get_status"))) is True
    zone = state.zones[1]
    assert zone.bypassed is False
    assert zone.trouble is False
    assert zone.tamper is False
    assert zone.alarm is False
    assert zone.low_battery is False


def test_zone_status_violated_char_b_sets_violated() -> None:
    from elke27_lib.handlers.zone import make_zone_get_all_zones_status_handler

    state = PanelState()
    state.get_or_create_zone(1)
    emit = _EmitSpy()
    handler = make_zone_get_all_zones_status_handler(state, emit, now=lambda: 1.0)
    msg = {
        "zone": {"get_all_zones_status": {"status": "B", "error_code": E27ErrorCode.ELKERR_NONE}}
    }
    assert handler(msg, _ctx(("zone", "get_all_zones_status"))) is True
    assert state.zones[1].violated is True
    assert state.panel.last_message_at == 1.0


def test_zone_status_flags_multiple_true() -> None:
    state = PanelState()
    emit = _EmitSpy()
    handler = make_zone_get_status_handler(state, emit, now=lambda: 123.0)

    msg = {
        "zone": {
            "get_status": {
                "zone_id": 2,
                "BYPASSED": True,
                "secure_state": "TAMPER",
                "trouble": True,
                "alarm": True,
                "low_batt": True,
                "error_code": E27ErrorCode.ELKERR_NONE,
            }
        }
    }
    assert handler(msg, _ctx(("zone", "get_status"))) is True
    zone = state.zones[2]
    assert zone.bypassed is True
    assert zone.trouble is True
    assert zone.tamper is True
    assert zone.alarm is True
    assert zone.low_battery is True
