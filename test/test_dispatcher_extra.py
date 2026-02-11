from __future__ import annotations

import logging

import pytest

from elke27_lib.dispatcher import (
    DispatchContext,
    Dispatcher,
    MessageKind,
    PagedRouteSpec,
    PagedTransfer,
    PagedTransferKey,
    PendingRequest,
    _payload_preview,
)


def test_payload_preview_non_serializable_and_truncate() -> None:
    msg = {"a": {1, 2, 3}}
    text = _payload_preview(msg, limit=5)
    assert text.endswith("...")


def test_register_domain_and_unregister() -> None:
    dispatcher = Dispatcher()

    def handler(_msg, _ctx):  # type: ignore[no-untyped-def]
        return True

    def handler2(_msg, _ctx):  # type: ignore[no-untyped-def]
        return False

    dispatcher.register_domain("zone", handler)
    assert ("zone", "__root__") in dispatcher._handlers

    dispatcher.unregister(("zone", "__root__"), handler2)
    dispatcher.unregister(("zone", "__root__"), handler)
    assert ("zone", "__root__") not in dispatcher._handlers
    dispatcher.unregister(("zone", "__root__"), handler)


def test_pending_count_and_drop() -> None:
    dispatcher = Dispatcher()
    pending = PendingRequest(seq=1)
    dispatcher.add_pending(pending)
    assert dispatcher.pending_count() == 1
    dispatcher.drop_pending(1)
    assert dispatcher.pending_count() == 0


def test_extract_route_errors() -> None:
    dispatcher = Dispatcher()
    route, errors = dispatcher._extract_route({"seq": 1})
    assert errors and route[0] == "__root__"

    route, errors = dispatcher._extract_route({"a": {}, "b": {}})
    assert errors and route[1] == "__multi__"

    route, errors = dispatcher._extract_route({"zone": {}})
    assert errors and route[1] == "__empty__"

    route, errors = dispatcher._extract_route({"zone": {"a": 1, "b": 2}})
    assert errors and route[1] == "__root__"

    route, errors = dispatcher._extract_route({"zone": 1})
    assert errors and route[1] == "__value__"


def test_domain_root_error_and_root_error_envelope() -> None:
    dispatcher = Dispatcher()
    assert dispatcher._is_domain_root_error({"error_code": "abc"}) is False
    assert dispatcher._is_domain_root_error({"error_code": "5", "foo": {"bar": 1}}) is False
    assert dispatcher._is_domain_root_error({"error_code": "5"}) is True

    assert dispatcher._is_root_error_envelope({"error_code": "abc", "error_message": "x"}) is False
    assert dispatcher._is_root_error_envelope({"error_code": 5, "error_message": ""}) is False
    assert dispatcher._is_root_error_envelope({"error_code": 5, "error_message": "bad"}) is True


def test_classify_kind_variants() -> None:
    dispatcher = Dispatcher()
    seq, kind, errors = dispatcher._classify_kind({})
    assert kind is MessageKind.UNKNOWN and not errors
    seq, kind, errors = dispatcher._classify_kind({"seq": "x"})
    assert kind is MessageKind.UNKNOWN and errors
    seq, kind, errors = dispatcher._classify_kind({"seq": 0})
    assert kind is MessageKind.BROADCAST
    seq, kind, errors = dispatcher._classify_kind({"seq": 5})
    assert kind is MessageKind.DIRECTED
    seq, kind, errors = dispatcher._classify_kind({"seq": -1})
    assert kind is MessageKind.UNKNOWN and errors


def test_paged_transfer_key_and_extract_payload() -> None:
    dispatcher = Dispatcher()
    key = PagedTransferKey(session_id=1, transfer_id=2, route=("zone", "get_configured"))
    pending = PendingRequest(seq=2, opaque=key)
    assert dispatcher._paged_transfer_key(("zone", "get_configured"), 1, pending) is key

    pending2 = PendingRequest(seq=3)
    key2 = dispatcher._paged_transfer_key(("zone", "get_configured"), 1, pending2)
    assert key2 is not None

    assert dispatcher._paged_transfer_key(("zone", "get_configured"), None, None) is None

    assert dispatcher._extract_paged_payload({"zone": 1}, ("zone", "get_configured")) is None
    assert (
        dispatcher._extract_paged_payload(
            {"zone": {"get_configured": 1}}, ("zone", "get_configured")
        )
        is None
    )


def test_expire_paged_transfers_and_abort() -> None:
    dispatcher = Dispatcher(now=lambda: 10.0, paged_timeout_s=1.0)
    route = ("zone", "get_configured")
    dispatcher._paged_routes[route] = PagedRouteSpec(
        merge_fn=lambda *_a: {}, request_block=None, timeout_s=1.0
    )
    key = PagedTransferKey(session_id=1, transfer_id=1, route=route)
    dispatcher._paged_transfers[key] = PagedTransfer(
        key=key, total_count=1, created_at=0.0, last_update_at=0.0
    )
    dispatcher._expire_paged_transfers()
    assert key not in dispatcher._paged_transfers
    dispatcher._paged_transfers[key] = PagedTransfer(
        key=key, total_count=1, created_at=0.0, last_update_at=9.5
    )
    dispatcher.abort_paged_transfers()
    assert dispatcher._paged_transfers == {}


def test_maybe_reassemble_paged_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    dispatcher = Dispatcher()
    route = ("zone", "get_configured")
    dispatcher.register_paged(route, merge_fn=lambda blocks, total: {"blocks": len(blocks)})

    ctx = DispatchContext(
        kind=MessageKind.DIRECTED,
        seq=1,
        session_id=1,
        route=route,
        classification="RESPONSE",
        response_match=None,
        raw_route=route,
    )
    response_match = PendingRequest(seq=1)
    msg = {"zone": {"get_configured": {"block_id": 0}}}
    assert dispatcher._maybe_reassemble_paged(msg, ctx, response_match) is None

    msg = {"zone": {"get_configured": {"block_id": 1, "block_count": 0}}}
    assert dispatcher._maybe_reassemble_paged(msg, ctx, response_match) is None

    msg = {"zone": {"get_configured": {"block_id": 3, "block_count": 2}}}
    assert dispatcher._maybe_reassemble_paged(msg, ctx, response_match) is None

    msg = {"zone": {"get_configured": 1}}
    assert dispatcher._maybe_reassemble_paged(msg, ctx, response_match) is msg

    msg = {"zone": {"error_code": 11008, "get_configured": {"block_id": 1, "block_count": 1}}}
    assert dispatcher._maybe_reassemble_paged(msg, ctx, response_match) is msg

    msg = {"zone": {"get_configured": {"block_id": 1, "block_count": 1, "error_code": 11008}}}
    assert dispatcher._maybe_reassemble_paged(msg, ctx, response_match) is msg

    def _req(_block, _key):  # type: ignore[no-untyped-def]
        raise RuntimeError("fail")

    dispatcher._paged_routes[route] = PagedRouteSpec(
        merge_fn=lambda blocks, total: {"blocks": len(blocks)}, request_block=_req, timeout_s=1.0
    )
    msg = {"zone": {"get_configured": {"block_id": 1, "block_count": 2}}}
    assert dispatcher._maybe_reassemble_paged(msg, ctx, response_match) is None

    transfer_key = dispatcher._paged_transfer_key(route, 1, response_match)
    assert transfer_key is not None
    dispatcher._paged_transfers[transfer_key] = PagedTransfer(
        key=transfer_key, total_count=1, created_at=0.0, last_update_at=0.0
    )
    msg = {"zone": {"get_configured": {"block_id": 1, "block_count": 2}}}
    assert dispatcher._maybe_reassemble_paged(msg, ctx, response_match) is msg

    dispatcher._paged_transfers[transfer_key] = PagedTransfer(
        key=transfer_key, total_count=1, created_at=0.0, last_update_at=0.0, received_blocks={1: {}}
    )
    msg = {"zone": {"get_configured": {"block_id": 1, "block_count": 1}}}
    assert dispatcher._maybe_reassemble_paged(msg, ctx, response_match) is None

    def _req_ok(_block, _key):  # type: ignore[no-untyped-def]
        return None

    dispatcher._paged_routes[route] = PagedRouteSpec(
        merge_fn=lambda blocks, total: {"blocks": len(blocks)}, request_block=_req_ok, timeout_s=1.0
    )
    dispatcher._paged_transfers[transfer_key] = PagedTransfer(
        key=transfer_key,
        total_count=None,
        created_at=0.0,
        last_update_at=0.0,
        requested_blocks={1},
    )
    msg = {"zone": {"get_configured": {"block_id": 1, "block_count": 2}}}
    assert dispatcher._maybe_reassemble_paged(msg, ctx, response_match) is None


def test_dispatch_zone_debug_and_error_emit(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    dispatcher = Dispatcher()
    route = ("zone", "get_configured")
    dispatcher.register_paged(route, merge_fn=lambda blocks, total: {"blocks": len(blocks)})

    def _handler(_msg, _ctx):  # type: ignore[no-untyped-def]
        return True

    dispatcher.register(route, _handler)
    caplog.set_level(logging.DEBUG, logger="elke27_lib.dispatcher")
    msg = {"seq": "bad", "zone": {"get_configured": {"block_id": 0}}}
    result = dispatcher.dispatch(msg)
    assert result.handled is True


def test_dispatch_paged_emits_errors_when_partial(monkeypatch: pytest.MonkeyPatch) -> None:
    dispatcher = Dispatcher()
    route = ("zone", "__root__")
    dispatcher.register_paged(route, merge_fn=lambda blocks, total: {"blocks": len(blocks)})

    called: dict[str, int] = {"count": 0}

    def _emit_errors(_ctx, _errors, msg=None):  # type: ignore[no-untyped-def]
        called["count"] += 1

    monkeypatch.setattr(dispatcher, "_emit_errors", _emit_errors)

    dispatcher.add_pending(PendingRequest(seq=1))
    msg = {
        "seq": 1,
        "session_id": 1,
        "zone": {
            "__root__": {"block_id": 0, "block_count": 2},
            "other": {},
        },
    }
    result = dispatcher.dispatch(msg)

    assert result.handled is True
    assert called["count"] == 1


def test_maybe_reassemble_paged_skips_requested_block(monkeypatch: pytest.MonkeyPatch) -> None:
    dispatcher = Dispatcher()
    route = ("zone", "get_configured")

    def _req(_block, _key):  # type: ignore[no-untyped-def]
        return None

    dispatcher.register_paged(
        route, merge_fn=lambda blocks, total: {"blocks": len(blocks)}, request_block=_req
    )

    ctx = DispatchContext(
        kind=MessageKind.DIRECTED,
        seq=2,
        session_id=1,
        route=route,
        classification="RESPONSE",
        response_match=None,
        raw_route=route,
    )
    response_match = PendingRequest(seq=2)
    transfer_key = dispatcher._paged_transfer_key(route, 1, response_match)
    assert transfer_key is not None

    dispatcher._paged_transfers[transfer_key] = PagedTransfer(
        key=transfer_key,
        total_count=2,
        created_at=0.0,
        last_update_at=0.0,
        requested_blocks={1},
        received_blocks={},
    )

    msg = {"zone": {"get_configured": {"block_id": 2, "block_count": 2}}}
    assert dispatcher._maybe_reassemble_paged(msg, ctx, response_match) is None
