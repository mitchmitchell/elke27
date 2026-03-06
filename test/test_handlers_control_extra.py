from __future__ import annotations

from typing import Any, cast

from elke27_lib.dispatcher import DispatchContext, PendingRequest
from elke27_lib.events import (
    ApiError,
    AuthenticateResult,
    AuthorizationRequiredEvent,
    CsmSnapshotUpdated,
    DispatchRoutingError,
    DomainCsmChanged,
    PanelVersionInfoUpdated,
)
from elke27_lib.handlers import control as control_handler
from elke27_lib.states import PanelState
from test.helpers.dispatch import make_ctx


class _EmitSpy:
    def __init__(self) -> None:
        self.events: list[object] = []

    def __call__(self, evt: object, _ctx: DispatchContext) -> None:
        self.events.append(evt)


def _any_event(spy: _EmitSpy, kind: type) -> bool:
    return any(isinstance(evt, kind) for evt in spy.events)


class _Queue:
    def __init__(self) -> None:
        self.items: list[object] = []

    def put_nowait(self, item: object) -> None:
        self.items.append(item)


class _QueueFails:
    def __init__(self) -> None:
        self.items: list[object] = []

    def put_nowait(self, _item: object) -> None:
        raise RuntimeError("boom")


class _QueuePut:
    def __init__(self) -> None:
        self.items: list[object] = []

    def put(self, item: object) -> None:
        self.items.append(item)


class _QueuePutFails:
    def put(self, _item: object) -> None:
        raise RuntimeError("boom")


def test_reconcile_control_get_version_info() -> None:
    state = PanelState()
    outcome = control_handler._reconcile_control_get_version_info(
        state,
        {
            "error_code": "bad",
            "model": 123,
            "firmware": "1.2.3",
            "serial": 456,
            "panel_model": "ignored",
        },
        now=1.0,
    )
    assert state.panel.last_message_at == 1.0
    assert state.panel.model == "123"
    assert state.panel.firmware == "1.2.3"
    assert state.panel.serial is None
    assert "model" in outcome.changed_fields
    assert "firmware" in outcome.changed_fields
    assert outcome.error_code is None
    assert outcome.warnings

    outcome = control_handler._reconcile_control_get_version_info(
        state,
        {"area": "x", "model": ["bad"]},
        now=1.5,
    )
    assert outcome.warnings
    assert control_handler._first_present({"foo": 1}, ("bar",)) is None


def test_control_helpers() -> None:
    assert control_handler._domain_from_csm_key(None) is None
    assert control_handler._domain_from_csm_key("not") is None
    assert control_handler._domain_from_csm_key("_csm") is None
    assert control_handler._domain_from_csm_key("Zone_csm") == "zone"

    assert control_handler._coerce_csm_value("zone_csm", True, source="test") is None
    assert control_handler._coerce_csm_value("zone_csm", 2, source="test") == 2
    assert control_handler._coerce_csm_value("zone_csm", 2.0, source="test") == 2
    assert control_handler._coerce_csm_value("zone_csm", "3", source="test") == 3
    assert control_handler._coerce_csm_value("zone_csm", "bad", source="test") is None

    state = PanelState()
    emit = _EmitSpy()
    ctx = make_ctx()
    state.domain_csm_by_name["zone"] = 2
    control_handler._apply_auth_csm_updates(state, emit, ctx, {"zone_csm": 2})
    assert not _any_event(emit, DomainCsmChanged)


def test_control_authenticate_handler_and_opaque() -> None:
    state = PanelState()
    emit = _EmitSpy()
    handler = control_handler.make_control_authenticate_handler(state, emit, now=lambda: 2.0)

    assert handler({"nope": {}}, make_ctx()) is False
    assert handler({"control": {}}, make_ctx()) is False

    msg = {"control": {"authenticate": {"error_code": 11008}}}
    ctx = DispatchContext(
        kind=make_ctx().kind,
        seq=None,
        session_id=None,
        route=("control", "authenticate"),
        classification="RESPONSE",
        response_match=PendingRequest(seq=1, opaque=_Queue()),
    )
    assert handler(msg, ctx) is True
    assert _any_event(emit, AuthorizationRequiredEvent)
    assert _any_event(emit, AuthenticateResult)

    emit.events.clear()
    msg = {"control": {"authenticate": {"error_code": 9}}}
    ctx = DispatchContext(
        kind=make_ctx().kind,
        seq=None,
        session_id=None,
        route=("control", "authenticate"),
        classification="RESPONSE",
        response_match=PendingRequest(seq=2, opaque=_QueueFails()),
    )
    assert handler(msg, ctx) is True
    assert _any_event(emit, ApiError)
    assert _any_event(emit, AuthenticateResult)

    emit.events.clear()
    msg = {"control": {"authenticate": {"zone_csm": "10", "area_csm": True}}}
    ctx = DispatchContext(
        kind=make_ctx().kind,
        seq=None,
        session_id=None,
        route=("control", "authenticate"),
        classification="RESPONSE",
        response_match=PendingRequest(seq=3, opaque=_QueuePut()),
    )
    assert handler(msg, ctx) is True
    assert _any_event(emit, AuthenticateResult)
    assert _any_event(emit, DomainCsmChanged)
    assert _any_event(emit, CsmSnapshotUpdated)

    ctx = DispatchContext(
        kind=make_ctx().kind,
        seq=None,
        session_id=None,
        route=("control", "authenticate"),
        classification="RESPONSE",
        response_match=PendingRequest(seq=4, opaque=None),
    )
    control_handler._notify_auth_opaque(ctx, success=True, error_code=0)

    ctx = DispatchContext(
        kind=make_ctx().kind,
        seq=None,
        session_id=None,
        route=("control", "authenticate"),
        classification="RESPONSE",
        response_match=PendingRequest(seq=5, opaque=_QueuePutFails()),
    )
    control_handler._notify_auth_opaque(ctx, success=True, error_code=0)


def test_control_get_trouble_handler() -> None:
    state = PanelState()
    emit = _EmitSpy()
    handler = control_handler.make_control_get_trouble_handler(state, emit, now=lambda: 3.0)

    assert handler({"nope": {}}, make_ctx()) is False
    assert handler({"control": {}}, make_ctx()) is False

    msg = {"control": {"get_trouble": {"error_code": 11008}}}
    assert handler(msg, make_ctx(classification="BROADCAST")) is True
    assert _any_event(emit, AuthorizationRequiredEvent)

    emit.events.clear()
    msg = {"control": {"get_trouble": {"error_code": 2}}}
    assert handler(msg, make_ctx()) is True
    assert _any_event(emit, ApiError)

    msg = {"control": {"get_trouble": {"foo": "bar"}}}
    assert handler(msg, make_ctx()) is True
    assert cast(dict[str, Any], state.control_status["get_trouble"])["foo"] == "bar"
    assert state.panel.last_message_at == 3.0


def test_control_get_version_info_handler() -> None:
    state = PanelState()
    emit = _EmitSpy()
    handler = control_handler.make_control_get_version_info_handler(state, emit, now=lambda: 4.0)

    assert handler({"nope": {}}, make_ctx()) is False
    assert handler({"control": {}}, make_ctx()) is False

    msg = {"control": {"get_version_info": {"error_code": 11008}}}
    assert handler(msg, make_ctx()) is True
    assert _any_event(emit, AuthorizationRequiredEvent)

    emit.events.clear()
    msg = {"control": {"get_version_info": {"error_code": 1}}}
    assert handler(msg, make_ctx()) is True
    assert _any_event(emit, ApiError)

    emit.events.clear()
    msg = {
        "control": {
            "get_version_info": {
                "model": "X",
                "firmware": 123,
                "serial": "S1",
                "error_code": "bad",
            }
        }
    }
    assert handler(msg, make_ctx()) is True
    assert _any_event(emit, PanelVersionInfoUpdated)
    assert _any_event(emit, DispatchRoutingError)
