from __future__ import annotations

from elke27_lib.dispatcher import DispatchContext
from elke27_lib.events import (
    ApiError,
    AuthorizationRequiredEvent,
    CsmSnapshotUpdated,
    KeypadConfiguredInventoryReady,
    TableCsmChanged,
)
from elke27_lib.handlers import keypad as keypad_handler
from elke27_lib.states import KeypadState, PanelState
from test.helpers.dispatch import make_ctx


class _EmitSpy:
    def __init__(self) -> None:
        self.events: list[object] = []

    def __call__(self, evt: object, _ctx: DispatchContext) -> None:
        self.events.append(evt)


def _any_event(spy: _EmitSpy, kind: type) -> bool:
    return any(isinstance(evt, kind) for evt in spy.events)


def test_keypad_get_configured_handler() -> None:
    state = PanelState()
    emit = _EmitSpy()
    handler = keypad_handler.make_keypad_get_configured_handler(state, emit, now=lambda: 1.0)

    assert handler({"nope": {}}, make_ctx()) is False
    assert handler({"keypad": {}}, make_ctx()) is False

    msg = {"keypad": {"get_configured": {"error_code": 11008}}}
    assert handler(msg, make_ctx()) is True
    assert _any_event(emit, AuthorizationRequiredEvent)

    emit.events.clear()
    msg = {"keypad": {"get_configured": {"error_code": 9}}}
    assert handler(msg, make_ctx()) is True
    assert _any_event(emit, ApiError)

    emit.events.clear()
    msg = {"keypad": {"get_configured": {"keypads": [1, 2], "block_id": 1, "block_count": 1}}}
    assert handler(msg, make_ctx()) is True
    assert state.inventory.configured_keypads == {1, 2}
    assert state.inventory.configured_keypads_complete is True
    assert _any_event(emit, KeypadConfiguredInventoryReady)
    assert state.panel.last_message_at == 1.0


def test_keypad_get_attribs_handler() -> None:
    state = PanelState()
    emit = _EmitSpy()
    handler = keypad_handler.make_keypad_get_attribs_handler(state, emit, now=lambda: 2.0)

    assert handler({"nope": {}}, make_ctx()) is False
    assert handler({"keypad": {}}, make_ctx()) is False

    msg = {"keypad": {"get_attribs": {"error_code": 11008, "keypad_id": 1}}}
    assert handler(msg, make_ctx()) is True
    assert _any_event(emit, AuthorizationRequiredEvent)

    emit.events.clear()
    msg = {"keypad": {"get_attribs": {"error_code": 7, "keypad_id": 1}}}
    assert handler(msg, make_ctx()) is True
    assert _any_event(emit, ApiError)

    msg = {"keypad": {"get_attribs": {"keypad_id": 0}}}
    assert handler(msg, make_ctx()) is False

    msg = {
        "keypad": {
            "get_attribs": {
                "keypad_id": 1,
                "name": "  Front ",
                "area": 2,
                "zone_id": 3,
                "source_id": 4,
                "device_id": "dev",
                "flags": [1],
                "extra": "x",
            }
        }
    }
    assert handler(msg, make_ctx()) is True
    keypad = state.keypads[1]
    assert keypad.name == "Front"
    assert keypad.area == 2
    assert keypad.zone_id == 3
    assert keypad.source_id == 4
    assert keypad.device_id == "dev"
    assert keypad.flags == [1]
    assert keypad.fields["extra"] == "x"
    assert state.panel.last_message_at == 2.0


def test_keypad_get_table_info_handler_and_helpers() -> None:
    state = PanelState()
    emit = _EmitSpy()
    handler = keypad_handler.make_keypad_get_table_info_handler(state, emit, now=lambda: 3.0)

    assert handler({"nope": {}}, make_ctx()) is False
    assert handler({"keypad": {}}, make_ctx()) is False

    msg = {"keypad": {"get_table_info": {"error_code": 4}}}
    assert handler(msg, make_ctx()) is True
    assert _any_event(emit, ApiError)

    emit.events.clear()
    msg = {"keypad": {"table_info": {"table_csm": "6"}}}
    assert handler(msg, make_ctx()) is True
    assert _any_event(emit, TableCsmChanged)
    assert _any_event(emit, CsmSnapshotUpdated)

    assert keypad_handler._extract_configured_ids({"keypads": [1, 2, "x"]}) == {1, 2}
    assert keypad_handler._extract_configured_ids({"keypad_ids": [3]}) == {3}
    assert keypad_handler._extract_configured_ids({"configured_keypads": [4]}) == {4}
    assert keypad_handler._extract_configured_ids({"configured_keypad_ids": [5]}) == {5}
    assert keypad_handler._extract_configured_ids({"none": []}) == set()

    assert keypad_handler._normalize_name(None) is None
    assert keypad_handler._normalize_name("   ") is None
    assert keypad_handler._normalize_name(" Name ") == "Name"

    keypad_state = KeypadState(keypad_id=1)
    changed: set[str] = set()
    keypad_handler._apply_keypad_attribs(
        keypad_state,
        {
            "name": " Bob ",
            "area": 1,
            "zone_id": 2,
            "source_id": 3,
            "device_id": "d",
            "flags": [1],
            "extra": "x",
        },
        changed,
    )
    assert keypad_state.name == "Bob"
    assert keypad_state.area == 1
    assert keypad_state.zone_id == 2
    assert keypad_state.source_id == 3
    assert keypad_state.device_id == "d"
    assert keypad_state.flags == [1]
    assert keypad_state.fields["extra"] == "x"

    assert keypad_handler._extract_table_csm({"table_csm": True}, domain="keypad") is None
    assert keypad_handler._extract_table_csm({"table_csm": 2}, domain="keypad") == 2
    assert keypad_handler._extract_table_csm({"table_csm": 2.0}, domain="keypad") == 2
    assert keypad_handler._extract_table_csm({"table_csm": "3"}, domain="keypad") == 3
    assert keypad_handler._extract_table_csm({"table_csm": "bad"}, domain="keypad") is None
    assert keypad_handler._extract_table_csm({"other": 1}, domain="keypad") is None
