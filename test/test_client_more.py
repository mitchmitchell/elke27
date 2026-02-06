from __future__ import annotations

import builtins
import asyncio
import logging
import queue
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from elke27_lib import client as client_mod
from elke27_lib.client import Elke27Client, Result
from elke27_lib.errors import (
    AuthorizationRequired,
    ConnectionLost,
    CryptoError,
    E27AuthFailed,
    E27Error,
    E27LinkInvalid,
    E27MissingContext,
    E27NotReady,
    E27ProtocolError,
    E27ProvisioningRequired,
    E27Timeout,
    E27TransportError,
    Elke27AuthError,
    Elke27ConnectionError,
    Elke27CryptoError,
    Elke27DisconnectedError,
    Elke27InvalidArgument,
    Elke27LinkRequiredError,
    Elke27PermissionError,
    Elke27ProtocolError as Elke27ProtocolErrorV2,
    Elke27TimeoutError,
    InvalidPin,
    InvalidPinError,
    InvalidCredentials,
    InvalidLinkKeys,
    MissingContext,
    NotAuthenticatedError,
    PanelNotDisarmedError,
    ProtocolError,
)
from elke27_lib.events import (
    AreaAttribsUpdated,
    AreaConfiguredInventoryReady,
    AreaStatusUpdated,
    AreaTroublesUpdated,
    ConnectionStateChanged,
    CsmSnapshotUpdated,
    KeypadConfiguredInventoryReady,
    OutputConfiguredInventoryReady,
    OutputStatusUpdated,
    OutputsStatusBulkUpdated,
    PanelVersionInfoUpdated,
    TstatTableInfoUpdated,
    ZoneAttribsUpdated,
    ZoneConfiguredInventoryReady,
    ZoneDefFlagsUpdated,
    ZoneDefsUpdated,
    ZonesStatusBulkUpdated,
    ZoneStatusUpdated,
)
from elke27_lib.kernel import E27Kernel
from elke27_lib.kernel import KernelError, KernelInvalidPanelError, KernelMissingContextError, KernelNotLinkedError
from elke27_lib.permissions import PermissionLevel
from elke27_lib.session import SessionConfig, SessionIOError, SessionNotReadyError, SessionProtocolError
from elke27_lib.states import AreaState, CsmSnapshot, OutputState, ZoneState, update_csm_snapshot
from elke27_lib.types import ArmMode, LinkKeys
from test.helpers.internal import get_kernel


def _event_base(kind: str, *, classification: str = "LOCAL") -> dict[str, object]:
    return dict(
        kind=kind,
        at=0.0,
        seq=None,
        classification=classification,
        route=("__local__", kind),
        session_id=1,
    )


def test_bootstrap_complete_counts_and_events() -> None:
    kernel = E27Kernel()
    client = Elke27Client(kernel=kernel)
    kernel.state.bootstrap_counts_ready = True
    assert client.bootstrap_complete_counts is True

    kernel.state.bootstrap_counts_ready = False
    kernel.state.table_info_by_domain = {
        "area": {"table_elements": 1},
        "zone": {"table_elements": 1},
        "output": {"table_elements": None},
        "tstat": {"table_elements": 1},
    }
    assert client.bootstrap_complete_counts is False

    kernel.state.table_info_by_domain = {
        "area": {"table_elements": 1},
        "zone": {"table_elements": 1},
        "output": {"table_elements": 1},
        "tstat": {"table_elements": 1},
    }
    assert client.bootstrap_complete_counts is False

    list(client.iter_events())
    client.drain_events()


def test_request_initial_statuses_and_attribs_exceptions(monkeypatch: pytest.MonkeyPatch) -> None:
    kernel = E27Kernel()
    client = Elke27Client(kernel=kernel)

    def _raise(*_a, **_k):  # type: ignore[no-untyped-def]
        raise E27Error("boom")

    monkeypatch.setattr(kernel, "request", _raise)
    client._request_initial_statuses("area", {1})
    client._request_initial_statuses("zone", {1})
    client._request_initial_statuses("output", {1})

    inv = kernel.state.inventory
    inv.configured_areas = {1}
    inv.configured_zones = {1}
    inv.configured_outputs = {1}
    inv.configured_users = {1}
    inv.configured_keypads = {1}
    client._queue_bootstrap_attribs("area")
    client._queue_bootstrap_attribs("zone")
    client._queue_bootstrap_attribs("output")
    client._queue_bootstrap_attribs("user")
    client._queue_bootstrap_attribs("keypad")


def test_refresh_helpers_and_bypass_tracking(monkeypatch: pytest.MonkeyPatch) -> None:
    kernel = E27Kernel()
    client = Elke27Client(kernel=kernel)
    calls: list[tuple[tuple[str, str], dict[str, object]]] = []

    def _safe(route, **kwargs):  # type: ignore[no-untyped-def]
        calls.append((route, dict(kwargs)))

    monkeypatch.setattr(client, "_safe_request", _safe)

    client._refresh_bypassed_zones_for_area(0)
    client._refresh_unbypassed_zones_for_area(0)
    client._refresh_all_zone_statuses_for_bypass_change(0)

    kernel.state.zones[1] = ZoneState(zone_id=1, area_id=1, bypassed=True)
    kernel.state.zones[2] = ZoneState(zone_id=2, area_id=1, bypassed=False)
    client._refresh_bypassed_zones_for_area(1)
    client._refresh_unbypassed_zones_for_area(1)
    client._refresh_all_zone_statuses_for_bypass_change(1)
    assert calls

    client._record_local_zone_bypass(99)
    client._record_local_zone_bypass(1)
    assert client._pending_bypass_by_area[1] >= 0

    client._pending_bypass_by_area[1] = 0.0
    client._kernel.now = lambda: 4.0  # type: ignore[assignment]
    assert client._should_suppress_area_bypass_refresh(1) is True
    client._kernel.now = lambda: 10.0  # type: ignore[assignment]
    assert client._should_suppress_area_bypass_refresh(1) is False

    client._mark_status_seen("missing", {1})


def test_event_queue_full_and_types() -> None:
    config = client_mod.ClientConfig(event_queue_maxlen=1)
    client = Elke27Client(config=config)
    client._event_queue = asyncio.Queue(maxsize=1)
    evt = client_mod.Elke27Event(
        event_type=client_mod.EventType.SYSTEM,
        data={},
        seq=1,
        timestamp=datetime.now(UTC),
        raw_type="x",
    )
    client._enqueue_event(evt)
    client._enqueue_event(evt)
    client._signal_event_stream_end()
    assert client._event_queue.qsize() == 1

    seq1 = client._next_event_seq(SimpleNamespace(seq=None, session_id=1))
    seq2 = client._next_event_seq(SimpleNamespace(seq=None, session_id=1))
    assert seq2 == seq1 + 1
    assert client._next_event_seq(SimpleNamespace(seq=5, session_id=1)) == 5
    assert client._next_event_seq(SimpleNamespace(seq=None, session_id=2)) == 1


def test_handle_kernel_event_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    kernel = E27Kernel()
    client = Elke27Client(kernel=kernel)
    calls = {"safe": 0}
    monkeypatch.setattr(client, "_safe_request", lambda *_a, **_k: calls.__setitem__("safe", calls["safe"] + 1))

    client._last_disconnect_at = 0.0
    client._now_monotonic = lambda: 1000.0
    kernel.request_csm_refresh = lambda **_k: (_ for _ in ()).throw(RuntimeError("x"))  # type: ignore[assignment]
    evt = ConnectionStateChanged(**_event_base(ConnectionStateChanged.KIND), connected=True)
    client._handle_kernel_event(evt)
    assert client._awaiting_reconnect_csm_check is True

    evt = ConnectionStateChanged(**_event_base(ConnectionStateChanged.KIND), connected=False)
    client._handle_kernel_event(evt)

    snapshot = update_csm_snapshot(kernel.state)
    client._awaiting_reconnect_csm_check = True
    client._reconnect_csm_snapshot = snapshot
    evt = CsmSnapshotUpdated(**_event_base(CsmSnapshotUpdated.KIND), snapshot=snapshot)  # type: ignore[arg-type]
    client._handle_kernel_event(evt)

    snapshot2 = CsmSnapshot(
        domain_csms={"zone": 1},
        table_csms={},
        version=1,
        updated_at=datetime.now(UTC),
    )
    client._awaiting_reconnect_csm_check = True
    client._reconnect_csm_snapshot = snapshot
    evt = CsmSnapshotUpdated(**_event_base(CsmSnapshotUpdated.KIND), snapshot=snapshot2)  # type: ignore[arg-type]
    client._handle_kernel_event(evt)
    assert calls["safe"] >= 1

    area_evt = AreaStatusUpdated(**_event_base(AreaStatusUpdated.KIND), area_id=1, changed_fields=())  # type: ignore[arg-type]
    client._handle_kernel_event(area_evt)
    troubles_evt = AreaTroublesUpdated(
        **_event_base(AreaTroublesUpdated.KIND, classification="BROADCAST"),
        area_id=1,
        troubles=(),
    )  # type: ignore[arg-type]
    client._handle_kernel_event(troubles_evt)

    client.subscribe(lambda _e: (_ for _ in ()).throw(ValueError("x")))  # type: ignore[arg-type]
    client.subscribe_typed(lambda _e: (_ for _ in ()).throw(RuntimeError("x")))  # type: ignore[arg-type]
    client._handle_kernel_event(ZoneStatusUpdated(**_event_base(ZoneStatusUpdated.KIND), zone_id=1, changed_fields=()))  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_async_discover_link_connect_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Elke27Client(kernel=E27Kernel())

    async def _discover(*_a, **_k):  # type: ignore[no-untyped-def]
        raise E27TransportError("x")

    monkeypatch.setattr(E27Kernel, "discover", _discover)
    with pytest.raises(Elke27ConnectionError):
        await client.async_discover()

    with pytest.raises(Elke27InvalidArgument):
        await client.async_link("", 1, access_code="a", passphrase="b", client_identity={"mn": "m", "sn": "s"})
    with pytest.raises(Elke27InvalidArgument):
        await client.async_link("h", 0, access_code="a", passphrase="b", client_identity={"mn": "m", "sn": "s"})
    with pytest.raises(Elke27InvalidArgument):
        await client.async_link("h", 1, access_code="", passphrase="b", client_identity={"mn": "m", "sn": "s"})
    with pytest.raises(Elke27InvalidArgument):
        await client.async_link("h", 1, access_code="a", passphrase="", client_identity={"mn": "m", "sn": "s"})
    with pytest.raises(Elke27InvalidArgument):
        await client.async_link("h", 1, access_code="a", passphrase="b", client_identity=None)

    with pytest.raises(Elke27InvalidArgument):
        await client.async_connect("", 1, LinkKeys("a", "b", "c"))
    with pytest.raises(Elke27InvalidArgument):
        await client.async_connect("h", 0, LinkKeys("a", "b", "c"))

    kernel = get_kernel(client)

    async def _connect(*_a, **_k):  # type: ignore[no-untyped-def]
        raise E27TransportError("x")

    monkeypatch.setattr(kernel, "connect", _connect)
    with pytest.raises(Elke27ConnectionError):
        await client.async_connect("h", 1, LinkKeys("a", "b", "c"))


@pytest.mark.asyncio
async def test_async_refresh_csm_and_domain_config(monkeypatch: pytest.MonkeyPatch) -> None:
    kernel = E27Kernel()
    client = Elke27Client(kernel=kernel)
    with pytest.raises(Elke27DisconnectedError):
        await client.async_refresh_csm()

    client._connected = True
    kernel.state.panel.connected = True

    def _raise_refresh(**_k):  # type: ignore[no-untyped-def]
        raise E27TransportError("x")

    monkeypatch.setattr(kernel, "request_csm_refresh", _raise_refresh)
    with pytest.raises(Elke27ConnectionError):
        await client.async_refresh_csm()

    monkeypatch.setattr(kernel, "request_csm_refresh", lambda **_k: None)
    monkeypatch.setattr(client_mod, "update_csm_snapshot", lambda *_a, **_k: None)
    kernel.state.csm_snapshot = None
    with pytest.raises(Elke27ProtocolErrorV2):
        await client.async_refresh_csm()

    with pytest.raises(Elke27InvalidArgument):
        await client.async_refresh_domain_config(" ")
    with pytest.raises(Elke27DisconnectedError):
        client._connected = False
        await client.async_refresh_domain_config("area")
    client._connected = True
    kernel.state.panel.connected = True

    called = {"area": 0}
    monkeypatch.setattr(client, "_refresh_area_config", lambda: called.__setitem__("area", called["area"] + 1))
    await client.async_refresh_domain_config("area")
    assert called["area"] == 1
    with pytest.raises(Elke27InvalidArgument):
        await client.async_refresh_domain_config("bad")


def test_safe_request_and_set_output(monkeypatch: pytest.MonkeyPatch) -> None:
    kernel = E27Kernel()
    client = Elke27Client(kernel=kernel)
    monkeypatch.setattr(kernel.requests, "get", lambda *_a, **_k: object())

    def _raise(*_a, **_k):  # type: ignore[no-untyped-def]
        raise E27TransportError("x")

    monkeypatch.setattr(kernel, "request", _raise)
    with pytest.raises(Elke27ConnectionError):
        client._safe_request(("zone", "get_status"))


@pytest.mark.asyncio
async def test_async_set_output_and_arm_disarm(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Elke27Client(kernel=E27Kernel())
    with pytest.raises(Elke27InvalidArgument):
        await client.async_set_output(0, on=True)
    with pytest.raises(Elke27DisconnectedError):
        await client.async_set_output(1, on=True)

    client._connected = True
    client._kernel.state.panel.connected = True

    async def _exec_fail(*_a, **_k):  # type: ignore[no-untyped-def]
        return Result(ok=False, data=None, error=None)

    monkeypatch.setattr(client, "async_execute", _exec_fail)
    with pytest.raises(Elke27ProtocolErrorV2):
        await client.async_set_output(1, on=True)

    async def _exec_err(*_a, **_k):  # type: ignore[no-untyped-def]
        return Result(ok=False, data=None, error=E27AuthFailed("x"))

    monkeypatch.setattr(client, "async_execute", _exec_err)
    with pytest.raises(Elke27AuthError):
        await client.async_set_output(1, on=True)

    with pytest.raises(Elke27InvalidArgument):
        await client.async_arm_area(0, mode=ArmMode.ARMED_STAY, pin="1234")
    with pytest.raises(Elke27InvalidArgument):
        await client.async_arm_area(1, mode=ArmMode.ARMED_NIGHT, pin="1234")
    with pytest.raises(Elke27InvalidArgument):
        await client.async_arm_area(1, mode=ArmMode.ARMED_STAY, pin="")
    with pytest.raises(Elke27InvalidArgument):
        await client.async_arm_area(1, mode=ArmMode.ARMED_STAY, pin="bad")

    called = {"disarm": 0}

    async def _disarm(*_a, **_k):  # type: ignore[no-untyped-def]
        called["disarm"] += 1

    monkeypatch.setattr(client, "async_disarm_area", _disarm)
    await client.async_arm_area(1, mode=ArmMode.DISARMED, pin="1234")
    assert called["disarm"] == 1

    async def _exec_err_perm(*_a, **_k):  # type: ignore[no-untyped-def]
        return Result(ok=False, data=None, error=NotAuthenticatedError("x"))

    monkeypatch.setattr(client, "async_execute", _exec_err_perm)
    with pytest.raises(Elke27PermissionError):
        await client.async_arm_area(1, mode=ArmMode.ARMED_STAY, pin="1234")

    client2 = Elke27Client(kernel=E27Kernel())
    client2._connected = True
    client2._kernel.state.panel.connected = True
    monkeypatch.setattr(client2, "async_execute", _exec_err_perm)
    with pytest.raises(Elke27InvalidArgument):
        await client2.async_disarm_area(0, pin="1234")
    with pytest.raises(Elke27InvalidArgument):
        await client2.async_disarm_area(1, pin="")
    with pytest.raises(Elke27InvalidArgument):
        await client2.async_disarm_area(1, pin="bad")

    with pytest.raises(Elke27PermissionError):
        await client2.async_disarm_area(1, pin="1234")


def test_request_authenticate_and_payload_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    kernel = E27Kernel()
    client = Elke27Client(kernel=kernel)
    monkeypatch.setattr(kernel, "request", lambda *_a, **_k: 5)
    result = client._request_authenticate(("control", "authenticate"), opaque=object(), pin="1234")
    assert result.ok is False and isinstance(result.error, ProtocolError)

    q = queue.Queue(maxsize=1)
    q.put({"success": True, "error_code": 0})
    result = client._request_authenticate(("control", "authenticate"), opaque=q, pin=1234)
    assert result.ok is True and client._last_auth_pin == 1234

    q = queue.Queue(maxsize=1)
    q.put({"success": False, "error_code": 2})
    result = client._request_authenticate(("control", "authenticate"), opaque=q, pin="1234")
    assert result.ok is False and isinstance(result.error, InvalidPin)

    q = queue.Queue(maxsize=1)
    q.put({"success": False})
    result = client._request_authenticate(("control", "authenticate"), opaque=q, pin="1234")
    assert result.ok is False and isinstance(result.error, InvalidPin)

    assert client._extract_error_code({"zone": {"get": {"error_code": 5}}}, ("zone", "get")) == 5
    assert client._extract_error_code({"zone": {"error_code": 6}}, ("zone", "get")) == 6
    assert client._extract_error_code({"zone": {"get": {"error_code": 0}}}, ("zone", "get")) is None
    assert client._has_expected_payload({}, ("zone", "get")) is False
    assert client._has_expected_payload({"zone": {}}, ("zone", "get")) is False
    assert client._extract_response_payload({"zone": {"get": {"x": 1}}}, ("zone", "get"))["x"] == 1
    assert client._extract_response_payload({"zone": {"get": 5}}, ("zone", "get"))["value"] == 5
    assert client._extract_response_payload({"zone": {"get": None}}, ("zone", "get")) == {"get": None}
    assert client._extract_response_payload({"zone": {"foo": 1}}, ("zone", "__root__"))["foo"] == 1
    assert client._extract_response_payload({"zone": 1}, ("zone", "get")) == {"zone": 1}


@pytest.mark.asyncio
async def test_async_authenticate_error_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    kernel = E27Kernel()
    client = Elke27Client(kernel=kernel)
    client._kernel.state.panel.session_id = 1

    class _Pending:
        def __init__(self) -> None:
            self.future: asyncio.Future[dict[str, object]] | None = None

        def create(self, *_a, **_k):  # type: ignore[no-untyped-def]
            self.future = asyncio.get_running_loop().create_future()
            return self.future

        def drop(self, *_a, **_k):  # type: ignore[no-untyped-def]
            return None

    pending = _Pending()
    kernel._pending_responses = pending  # type: ignore[attr-defined]
    kernel.register_sent_event = lambda _s, event: event.set()  # type: ignore[assignment]

    def _send(*_a, **_k):  # type: ignore[no-untyped-def]
        pending.future.set_result({"authenticate": 1})

    kernel.send_request_with_seq = _send  # type: ignore[assignment]
    res = await client._async_authenticate(pin=1234, timeout_s=1.0)
    assert res.ok is False and isinstance(res.error, ProtocolError)

    def _send_err(*_a, **_k):  # type: ignore[no-untyped-def]
        pending.future.set_result({"authenticate": {"__root__": {"error_code": 11008}}})

    kernel.send_request_with_seq = _send_err  # type: ignore[assignment]
    res = await client._async_authenticate(pin=1234, timeout_s=1.0)
    assert res.ok is False and isinstance(res.error, AuthorizationRequired)

    def _send_err2(*_a, **_k):  # type: ignore[no-untyped-def]
        pending.future.set_result({"authenticate": {"__root__": {"error_code": 9}}})

    kernel.send_request_with_seq = _send_err2  # type: ignore[assignment]
    res = await client._async_authenticate(pin=1234, timeout_s=1.0)
    assert res.ok is False and isinstance(res.error, E27Error)


def test_misc_helpers_and_permissions(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Elke27Client(kernel=E27Kernel())
    client._kernel.state.panel.session_id = None
    assert isinstance(client._enforce_permissions("x", PermissionLevel.PLT_ENCRYPTION_KEY), NotAuthenticatedError)

    def _gen_no_pin() -> tuple[dict[str, object], tuple[str, str]]:
        return {}, ("x", "y")

    spec = client_mod.CommandSpec(
        key="x",
        domain="x",
        command="y",
        generator=_gen_no_pin,
        handler=lambda *_a, **_k: True,  # type: ignore[no-untyped-def]
        min_permission=PermissionLevel.PLT_ENCRYPTION_KEY,
    )
    coerced = client._coerce_pin_for_generator(spec, {"pin": "123"})
    assert "pin" not in coerced

    def _gen_pin(pin: str) -> tuple[dict[str, object], tuple[str, str]]:
        return {"pin": pin}, ("x", "y")

    spec = client_mod.CommandSpec(
        key="x2",
        domain="x",
        command="y",
        generator=_gen_pin,
        handler=lambda *_a, **_k: True,  # type: ignore[no-untyped-def]
        min_permission=PermissionLevel.PLT_ENCRYPTION_KEY,
    )
    coerced = client._coerce_pin_for_generator(spec, {"pin": "123"})
    assert coerced["pin"] == "123"

    assert client._all_areas_disarmed() is False
    client._kernel.state.areas[1] = AreaState(area_id=1, arm_state=None)
    assert client._all_areas_disarmed() is False

    assert client._resolve_merge_strategy("area_configured")
    assert client._resolve_merge_strategy("zone_configured")
    assert client._resolve_merge_strategy("rule_blocks")
    assert client._resolve_merge_strategy("user_configured")
    assert client._resolve_merge_strategy("keypad_configured")

    assert client._coerce_block_count(-1) is None
    assert client._coerce_block_count("0") is None
    assert client._coerce_block_count("2") == 2

    err = client._normalize_error(E27ProvisioningRequired("x"), phase="p")
    assert isinstance(err, AuthorizationRequired)
    err = client._normalize_error(E27LinkInvalid("x"), phase="p")
    assert isinstance(err, InvalidLinkKeys)
    err = client._normalize_error(E27AuthFailed("x"), phase="p")
    assert isinstance(err, InvalidCredentials)
    err = client._normalize_error(E27MissingContext("x"), phase="p")
    assert isinstance(err, E27MissingContext)
    err = client._normalize_error(E27ProtocolError("x"), phase="p")
    assert isinstance(err, CryptoError)
    err = client._normalize_error(E27TransportError("x"), phase="p")
    assert isinstance(err, ConnectionLost)
    class _CustomTimeout(Exception):
        pass

    monkeypatch.setattr(builtins, "TimeoutError", _CustomTimeout)
    err = client._normalize_error(_CustomTimeout("x"), phase="p")
    assert isinstance(err, E27Timeout)
    err = client._normalize_error(KernelNotLinkedError("x"), phase="p")
    assert isinstance(err, MissingContext)
    err = client._normalize_error(KernelMissingContextError("x"), phase="p")
    assert isinstance(err, MissingContext)
    err = client._normalize_error(KernelInvalidPanelError("x"), phase="p")
    assert isinstance(err, ProtocolError)
    err = client._normalize_error(SessionNotReadyError("x"), phase="p")
    assert isinstance(err, E27NotReady)
    err = client._normalize_error(SessionIOError("x"), phase="p")
    assert isinstance(err, ConnectionLost)
    err = client._normalize_error(SessionProtocolError("x"), phase="p")
    assert isinstance(err, ProtocolError)
    err = client._normalize_error(KernelError("x"), phase="p")
    assert isinstance(err, E27Error)
    err = client._normalize_error(RuntimeError("x"), phase="p")
    assert isinstance(err, E27Error)
