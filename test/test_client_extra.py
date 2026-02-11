from __future__ import annotations

import asyncio
import logging
import queue
from datetime import UTC, datetime

import pytest

from elke27_lib import client as client_mod
from elke27_lib import discovery, linking
from elke27_lib.client import Elke27Client, Result
from elke27_lib.errors import (
    CryptoError,
    E27AuthFailed,
    E27Error,
    E27LinkInvalid,
    E27NotReady,
    E27ProtocolError,
    E27ProvisioningRequired,
    E27Timeout,
    E27TransportError,
    Elke27AuthError,
    Elke27ConnectionError,
    Elke27CryptoError,
    Elke27InvalidArgument,
    Elke27LinkRequiredError,
    Elke27PermissionError,
    Elke27PinRequiredError,
    Elke27TimeoutError,
    InvalidPinError,
    NotAuthenticatedError,
    PanelNotDisarmedError,
    ProtocolError,
)
from elke27_lib.errors import (
    Elke27ProtocolError as Elke27ProtocolErrorV2,
)
from elke27_lib.events import (
    AreaStatusUpdated,
    AreaTroublesUpdated,
    ConnectionStateChanged,
    CsmSnapshotUpdated,
)
from elke27_lib.kernel import E27Kernel, KernelError, KernelMissingContextError
from elke27_lib.permissions import PermissionLevel
from elke27_lib.session import SessionConfig, SessionNotReadyError, SessionProtocolError
from elke27_lib.states import AreaState, OutputState, ZoneState
from elke27_lib.types import ArmMode, CsmSnapshot, LinkKeys


def _identity() -> linking.E27Identity:
    return linking.E27Identity("mn", "sn", "fw", "hw", "os")


def _event_base(kind: str) -> dict[str, object]:
    return dict(
        kind=kind,
        at=0.0,
        seq=None,
        classification="LOCAL",
        route=("__local__", kind),
        session_id=1,
    )


def test_coerce_identity_and_link_keys() -> None:
    client = Elke27Client(kernel=E27Kernel())
    ident = client._coerce_identity(None)
    assert ident.mn and ident.sn
    identity = _identity()
    assert client._coerce_identity(identity) is identity
    with pytest.raises(Elke27InvalidArgument):
        client._coerce_identity(123)
    ident = client._coerce_identity({"mn": "m", "sn": "s"})
    assert ident.mn == "m"

    class _Val:
        def __bool__(self) -> bool:
            return True

        def __str__(self) -> str:
            return ""

    class _Map(dict):
        def get(self, key, default=None):  # type: ignore[no-untyped-def]
            if key in ("mn", "sn"):
                return _Val()
            return super().get(key, default)

    with pytest.raises(Elke27InvalidArgument):
        client._coerce_identity(_Map())

    keys = LinkKeys(tempkey_hex="aa", linkkey_hex="bb", linkhmac_hex="cc")
    coerced = client._coerce_link_keys(keys)
    assert coerced.linkkey_hex == "bb"


def test_raise_v2_error_mapping() -> None:
    client = Elke27Client(kernel=E27Kernel())
    with pytest.raises(Elke27LinkRequiredError):
        client._raise_v2_error(E27ProvisioningRequired("x"), phase="p")
    with pytest.raises(Elke27InvalidArgument):
        client._raise_v2_error(KernelMissingContextError("x"), phase="p")
    with pytest.raises(Elke27AuthError):
        client._raise_v2_error(E27AuthFailed("x"), phase="p")
    with pytest.raises(Elke27CryptoError):
        client._raise_v2_error(E27LinkInvalid("x"), phase="p")
    with pytest.raises(Elke27CryptoError):
        client._raise_v2_error(CryptoError("x"), phase="p")
    with pytest.raises(Elke27ProtocolErrorV2):
        client._raise_v2_error(E27ProtocolError("x"), phase="p")
    with pytest.raises(Elke27ConnectionError):
        client._raise_v2_error(E27TransportError("x"), phase="p")
    with pytest.raises(Elke27ConnectionError):
        client._raise_v2_error(TimeoutError(), phase="p")
    with pytest.raises(Elke27ConnectionError):
        client._raise_v2_error(TimeoutError("x"), phase="p")
    with pytest.raises(Elke27ProtocolErrorV2):
        client._raise_v2_error(RuntimeError("x"), phase="p")
    with pytest.raises(Elke27ProtocolErrorV2):
        client._raise_v2_error(KernelError("x"), phase="p")


def test_raise_v2_command_error_mapping() -> None:
    client = Elke27Client(kernel=E27Kernel())
    with pytest.raises(Elke27LinkRequiredError):
        client._raise_v2_command_error(E27ProvisioningRequired("x"))
    with pytest.raises(Elke27PermissionError):
        client._raise_v2_command_error(PanelNotDisarmedError("x"))
    with pytest.raises(Elke27PermissionError):
        client._raise_v2_command_error(NotAuthenticatedError("x"))
    with pytest.raises(Elke27AuthError):
        client._raise_v2_command_error(InvalidPinError("x"))
    with pytest.raises(Elke27TimeoutError):
        client._raise_v2_command_error(E27Timeout("x"))
    with pytest.raises(Elke27ConnectionError):
        client._raise_v2_command_error(E27NotReady("x"))
    with pytest.raises(Elke27CryptoError):
        client._raise_v2_command_error(CryptoError("x"))
    with pytest.raises(Elke27ProtocolErrorV2):
        client._raise_v2_command_error(E27ProtocolError("x"))
    with pytest.raises(Elke27ProtocolErrorV2):
        client._raise_v2_command_error(RuntimeError("x"))


def test_arm_mode_and_block_count_helpers() -> None:
    client = Elke27Client(kernel=E27Kernel())
    assert client._arm_mode_from_string("disarm") is ArmMode.DISARMED
    assert client._arm_mode_from_string("stay") is ArmMode.ARMED_STAY
    assert client._arm_mode_from_string("away") is ArmMode.ARMED_AWAY
    assert client._arm_mode_from_string("night") is ArmMode.ARMED_NIGHT
    assert client._arm_mode_from_string("foo") is None
    assert client._arm_mode_from_string(None) is None
    assert client._coerce_block_count("2") == 2
    assert client._coerce_block_count(0) is None


def test_build_maps_and_snapshot() -> None:
    kernel = E27Kernel()
    kernel.state.areas[1] = AreaState(area_id=1, name="A", arm_state="disarmed", ready=True)
    kernel.state.zones[1] = ZoneState(
        zone_id=1,
        name="Z",
        violated=True,
        bypassed=True,
        trouble=False,
        alarm=False,
        tamper=False,
        low_battery=True,
        attribs={"zone_type": "door", "kind": "entry"},
        definition=1,
    )
    kernel.state.zone_defs_by_id = {1: {"definition": "front"}}
    kernel.state.outputs[1] = OutputState(output_id=1, name="O", on=True)
    client = Elke27Client(kernel=kernel)
    assert client._build_area_map()[1].name == "A"
    assert client._build_zone_map()[1].bypassed is True
    assert client._build_zone_definitions()[1].definition == "front"
    assert client._build_output_map()[1].state is True
    client._replace_snapshot(
        panel_info=client._build_panel_info(),
        table_info=client._build_table_info(),
        areas=client._build_area_map(),
        zones=client._build_zone_map(),
        zone_definitions=client._build_zone_definitions(),
        outputs=client._build_output_map(),
        output_definitions=client._build_output_definitions(),
    )
    assert client.snapshot.version == 1


def test_queue_helpers() -> None:
    client = Elke27Client(kernel=E27Kernel())
    client._enqueue_event(
        client_mod.Elke27Event(
            event_type=client_mod.EventType.SYSTEM,
            data={},
            seq=1,
            timestamp=datetime.now(UTC),
            raw_type="x",
        )
    )
    client._signal_event_stream_end()
    assert client._event_queue.qsize() >= 1


def test_handle_kernel_event_connection_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    kernel = E27Kernel()
    client = Elke27Client(kernel=kernel)
    called = {"safe": 0}
    monkeypatch.setattr(
        client, "_safe_request", lambda *_a, **_k: called.__setitem__("safe", called["safe"] + 1)
    )

    client._last_disconnect_at = 0.0
    client._now_monotonic = lambda: 10.0
    evt = ConnectionStateChanged(**_event_base(ConnectionStateChanged.KIND), connected=True)
    client._handle_kernel_event(evt)
    assert called["safe"] == 1

    evt = ConnectionStateChanged(**_event_base(ConnectionStateChanged.KIND), connected=False)
    client._handle_kernel_event(evt)
    assert client._last_disconnect_at is not None


def test_handle_kernel_event_area_paths(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    kernel = E27Kernel()
    kernel.state.areas[1] = AreaState(area_id=1, num_bypassed_zones=1)
    client = Elke27Client(kernel=kernel)
    called = {"refresh": 0}
    monkeypatch.setattr(
        client,
        "_refresh_all_zone_statuses_for_bypass_change",
        lambda _area: called.__setitem__("refresh", called["refresh"] + 1),
    )
    evt = AreaStatusUpdated(**_event_base(AreaStatusUpdated.KIND), area_id=1, changed_fields=())
    client._handle_kernel_event(evt)
    assert called["refresh"] == 1

    caplog.set_level(logging.WARNING, logger="elke27_lib.client")
    evt = AreaStatusUpdated(
        **_event_base(AreaStatusUpdated.KIND),
        area_id=1,
        changed_fields=("num_bypassed_zones",),
    )
    client._handle_kernel_event(evt)
    assert "bypass count changed" in caplog.text

    trouble_base = _event_base(AreaTroublesUpdated.KIND)
    trouble_base["classification"] = "BROADCAST"
    evt = AreaTroublesUpdated(
        **trouble_base,
        area_id=1,
        troubles=(),
    )
    client._handle_kernel_event(evt)
    assert called["refresh"] >= 2


def test_handle_kernel_event_csm_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    kernel = E27Kernel()
    client = Elke27Client(kernel=kernel)
    client._awaiting_reconnect_csm_check = True
    now = datetime.now(UTC)
    client._reconnect_csm_snapshot = CsmSnapshot(
        domain_csms={"a": 1}, table_csms={}, version=1, updated_at=now
    )
    changed = CsmSnapshot(domain_csms={"a": 2}, table_csms={}, version=2, updated_at=now)
    called = {"safe": 0}
    monkeypatch.setattr(
        client, "_safe_request", lambda *_a, **_k: called.__setitem__("safe", called["safe"] + 1)
    )
    evt = CsmSnapshotUpdated(**_event_base(CsmSnapshotUpdated.KIND), snapshot=changed)
    client._handle_kernel_event(evt)
    assert called["safe"] == 1


def test_subscriber_error_logging(caplog: pytest.LogCaptureFixture) -> None:
    kernel = E27Kernel()
    client = Elke27Client(kernel=kernel)
    caplog.set_level(logging.WARNING, logger="elke27_lib.client")

    def _bad(_evt):  # type: ignore[no-untyped-def]
        raise ValueError("boom")

    client.subscribe(_bad)
    evt = ConnectionStateChanged(**_event_base(ConnectionStateChanged.KIND), connected=True)
    client._handle_kernel_event(evt)
    assert "Subscriber callback failed" in caplog.text


def test_on_kernel_event_dispatch() -> None:
    kernel = E27Kernel()
    client = Elke27Client(kernel=kernel)
    called = {"count": 0}

    class _Loop:
        def call_soon_threadsafe(self, fn, *args):  # type: ignore[no-untyped-def]
            called["count"] += 1
            fn(*args)

    client._event_loop = _Loop()  # type: ignore[assignment]
    evt = ConnectionStateChanged(**_event_base(ConnectionStateChanged.KIND), connected=True)
    client._on_kernel_event(evt)
    assert called["count"] == 1


@pytest.mark.asyncio
async def test_async_discover_link_connect_disconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    kernel = E27Kernel()
    client = Elke27Client(kernel=kernel)

    async def _discover(**_k):  # type: ignore[no-untyped-def]
        return client_mod.DiscoverResult(
            panels=[
                discovery.E27System(
                    panel_mac="m",
                    panel_host="h",
                    panel_name="n",
                    panel_serial=None,
                    port=2101,
                    tls_port=2102,
                )
            ]
        )

    monkeypatch.setattr(client_mod.E27Kernel, "discover", _discover)
    panels = await client.async_discover()
    assert panels and panels[0].host == "h"

    async def _link(*_a, **_k):  # type: ignore[no-untyped-def]
        return linking.E27LinkKeys("aa", "bb", "cc")

    monkeypatch.setattr(kernel, "link", _link)
    keys = await client.async_link(
        "h",
        2101,
        access_code="1",
        passphrase="2",
        client_identity={"mn": "m", "sn": "s"},
    )
    assert keys.linkkey_hex == "bb"

    async def _connect(*_a, **_k):  # type: ignore[no-untyped-def]
        return None

    monkeypatch.setattr(kernel, "connect", _connect)
    await client.async_connect("h", 2101, keys)
    assert client._connected is True

    async def _close():  # type: ignore[no-untyped-def]
        return None

    monkeypatch.setattr(kernel, "close", _close)
    await client.async_disconnect()
    assert client._connected is False


@pytest.mark.asyncio
async def test_async_refresh_csm(monkeypatch: pytest.MonkeyPatch) -> None:
    kernel = E27Kernel()
    client = Elke27Client(kernel=kernel)
    client._connected = True
    kernel.state.panel.connected = True
    now = datetime.now(UTC)
    snapshot = CsmSnapshot(domain_csms={"a": 1}, table_csms={}, version=1, updated_at=now)

    def _subscribe(cb, kinds=None):  # type: ignore[no-untyped-def]
        cb(CsmSnapshotUpdated(**_event_base(CsmSnapshotUpdated.KIND), snapshot=snapshot))
        return 1

    monkeypatch.setattr(kernel, "subscribe", _subscribe)
    monkeypatch.setattr(kernel, "unsubscribe", lambda _t: None)
    monkeypatch.setattr(kernel, "request_csm_refresh", lambda **_k: None)
    assert await client.async_refresh_csm() == snapshot


@pytest.mark.asyncio
async def test_async_set_output_and_arm(monkeypatch: pytest.MonkeyPatch) -> None:
    kernel = E27Kernel()
    client = Elke27Client(kernel=kernel)
    client._connected = True
    kernel.state.panel.connected = True

    async def _ok_execute(*_a, **_k):  # type: ignore[no-untyped-def]
        return Result(ok=True, data={}, error=None)

    monkeypatch.setattr(client, "async_execute", _ok_execute)
    await client.async_set_output(1, on=True)

    with pytest.raises(Elke27InvalidArgument):
        await client.async_arm_area(0, mode=ArmMode.ARMED_AWAY, pin="1")
    with pytest.raises(Elke27InvalidArgument):
        await client.async_disarm_area(1, pin="")


def test_request_authenticate_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    kernel = E27Kernel()
    client = Elke27Client(kernel=kernel)
    bad = client._request_authenticate(("control", "authenticate"), opaque=object())
    assert bad.ok is False

    q: queue.Queue[dict[str, object]] = queue.Queue(maxsize=1)
    q.put({"success": True})
    monkeypatch.setattr(kernel, "request", lambda *_a, **_k: 5)
    res = client._request_authenticate(("control", "authenticate"), opaque=q, pin="1234")
    assert res.ok is True and res.data == 5

    q = queue.Queue(maxsize=1)
    q.put({"success": False, "error_code": 5})
    res = client._request_authenticate(("control", "authenticate"), opaque=q, pin="1234")
    assert res.ok is False


def test_misc_helpers() -> None:
    client = Elke27Client(kernel=E27Kernel())
    assert client._has_expected_payload({"zone": {"get": {}}}, ("zone", "get")) is True
    assert client._extract_error_code({"zone": {"error_code": 5}}, ("zone", "get")) == 5
    payload = client._extract_response_payload({"zone": {"get": {"x": 1}}}, ("zone", "get"))
    assert payload["x"] == 1

    assert client._enforce_permissions("x", PermissionLevel.PLT_ENCRYPTION_KEY) is not None
    client._kernel.state.panel.session_id = 1
    assert client._enforce_permissions("x", PermissionLevel.PLT_ENCRYPTION_KEY) is None


def test_result_and_filtered_mapping() -> None:
    ok = client_mod.Result.success(1)
    assert ok.unwrap() == 1
    err = client_mod.Result.failure(ValueError("x"))
    with pytest.raises(ValueError):
        err.unwrap()
    with pytest.raises(E27Error):
        client_mod.Result(ok=True, data=None, error=None).unwrap()
    with pytest.raises(E27Error):
        client_mod.Result(ok=False, data=None, error=None).unwrap()

    mapping = client_mod._FilteredMapping({1: "a", 2: "b"}, {2})
    assert list(mapping) == [2]
    assert len(mapping) == 1
    assert mapping[2] == "b"
    with pytest.raises(KeyError):
        _ = mapping[1]

    state = E27Kernel().state
    state.table_info_by_domain["zone"] = {"table_elements": 2}
    assert list(client_mod._configured_ids_from_table(state, "zone")) == [1, 2]
    assert client_mod._table_elements_for_domain(state, "zone") == 2

    assert client_mod._configured_ids_from_table(state, "missing") == ()
    state.table_info_by_domain["bad"] = {"table_elements": 0}
    assert client_mod._configured_ids_from_table(state, "bad") == ()


@pytest.mark.asyncio
async def test_async_execute_single_and_paged(monkeypatch: pytest.MonkeyPatch) -> None:
    kernel = E27Kernel()
    client = Elke27Client(kernel=kernel)
    client._kernel.state.panel.session_id = 1

    class _Pending:
        def __init__(self) -> None:
            self.futures: dict[int, asyncio.Future[dict[str, object]]] = {}

        def create(self, seq, **_k):  # type: ignore[no-untyped-def]
            fut = asyncio.get_running_loop().create_future()
            self.futures[seq] = fut
            return fut

        def drop(self, seq):  # type: ignore[no-untyped-def]
            self.futures.pop(seq, None)

    pending = _Pending()
    kernel._pending_responses = pending  # type: ignore[attr-defined]
    kernel.next_seq = lambda: 1  # type: ignore[assignment]
    kernel.register_sent_event = lambda _s, event: event.set()  # type: ignore[assignment]

    def _send(seq, domain, command, payload, **_k):  # type: ignore[no-untyped-def]
        msg = {domain: {command: {"ok": True}}}
        pending.futures[seq].set_result(msg)

    kernel.send_request_with_seq = _send  # type: ignore[assignment]

    def _gen(**_k):  # type: ignore[no-untyped-def]
        return {"x": 1}, ("zone", "get")

    spec = client_mod.CommandSpec(
        key="fake_get",
        domain="zone",
        command="get",
        generator=_gen,
        handler=lambda *_a, **_k: True,  # type: ignore[no-untyped-def]
        min_permission=PermissionLevel.PLT_ENCRYPTION_KEY,
    )
    monkeypatch.setitem(client_mod.COMMANDS, "fake_get", spec)
    monkeypatch.setattr(
        client_mod, "permission_for_generator", lambda *_a, **_k: PermissionLevel.PLT_ENCRYPTION_KEY
    )

    result = await client.async_execute("fake_get")
    assert result.ok is True

    def _gen_paged(block_id: int) -> tuple[dict[str, object], tuple[str, str]]:
        return {"block_id": block_id}, ("zone", "get_configured")

    paged = client_mod.CommandSpec(
        key="fake_paged",
        domain="zone",
        command="get_configured",
        generator=_gen_paged,
        handler=lambda *_a, **_k: True,  # type: ignore[no-untyped-def]
        min_permission=PermissionLevel.PLT_ENCRYPTION_KEY,
        response_mode="paged_blocks",
        block_field="block_id",
        block_count_field="block_count",
        merge_strategy=lambda blocks, total: {"blocks": len(blocks), "block_count": total},
    )
    monkeypatch.setitem(client_mod.COMMANDS, "fake_paged", paged)

    seq_counter = {"val": 0}

    def _next_seq():  # type: ignore[no-untyped-def]
        seq_counter["val"] += 1
        return seq_counter["val"]

    kernel.next_seq = _next_seq  # type: ignore[assignment]

    def _send_paged(seq, domain, command, payload, **_k):  # type: ignore[no-untyped-def]
        block_id = payload["block_id"]
        msg = {domain: {command: {"block_id": block_id, "block_count": 2}}}
        pending.futures[seq].set_result(msg)

    kernel.send_request_with_seq = _send_paged  # type: ignore[assignment]
    result = await client.async_execute("fake_paged")
    assert result.ok is True


def test_iter_causes_and_bootstrap() -> None:
    err = RuntimeError("root")
    err.__cause__ = ValueError("child")
    assert [type(e) for e in client_mod._iter_causes(err)] == [RuntimeError, ValueError]

    kernel = E27Kernel()
    client = Elke27Client(kernel=kernel)
    assert client.bootstrap_complete_counts is False


def test_init_config_and_roles() -> None:
    config = client_mod.ClientConfig(logger_name="elke27.test", event_queue_maxlen=5)
    client = Elke27Client(config=config)
    client.set_authenticated_role("master")
    assert client._auth_role == "master"


@pytest.mark.asyncio
async def test_wait_ready_and_subscribe() -> None:
    client = Elke27Client(kernel=E27Kernel())
    client._ready_event.set()
    assert await client.wait_ready(0.01) is True

    called = {"count": 0}

    def _cb(_evt):  # type: ignore[no-untyped-def]
        called["count"] += 1

    unsub = client.subscribe(_cb)
    unsub2 = client.subscribe(_cb)
    assert unsub2() is True
    assert client.unsubscribe(_cb) is False
    assert unsub() is False

    unsub_typed = client.subscribe_typed(_cb)
    unsub_typed2 = client.subscribe_typed(_cb)
    assert unsub_typed2() is True
    assert client.unsubscribe_typed(_cb) is False
    assert unsub_typed() is False


def test_normalize_error_and_context(monkeypatch: pytest.MonkeyPatch) -> None:
    kernel = E27Kernel()
    client = Elke27Client(kernel=kernel)
    err = client._normalize_error(KernelMissingContextError("x"), phase="p")
    assert isinstance(err, E27Error)

    err = client._normalize_error(SessionNotReadyError("x"), phase="p")
    assert isinstance(err, E27NotReady)

    err = client._normalize_error(SessionProtocolError("x"), phase="p")
    assert isinstance(err, ProtocolError)

    class _Sess:
        cfg = SessionConfig(host="h", port=1)

    kernel._session = _Sess()  # type: ignore[assignment]
    ctx = client._error_context(phase="x", detail="y")
    assert ctx.host == "h" and ctx.port == 1


def test_payload_helpers() -> None:
    client = Elke27Client(kernel=E27Kernel())
    assert client._extract_error_code({"zone": 1}, ("zone", "get")) is None
    assert client._has_expected_payload({"zone": {"error_code": 1}}, ("zone", "get")) is True
    assert client._has_expected_payload({"zone": {}}, ("zone", "__root__")) is True
    payload = client._extract_response_payload({"zone": {"get": 5}}, ("zone", "get"))
    assert payload["value"] == 5


def test_pin_coercion_and_merge_helpers() -> None:
    client = Elke27Client(kernel=E27Kernel())

    def _gen(pin):  # type: ignore[no-untyped-def]
        return {"pin": pin}, ("x", "y")

    _gen.__annotations__ = {"pin": int}

    spec = client_mod.CommandSpec(
        key="x",
        domain="x",
        command="y",
        generator=_gen,
        handler=lambda *_a, **_k: True,  # type: ignore[no-untyped-def]
        min_permission=PermissionLevel.PLT_ENCRYPTION_KEY,
    )
    coerced = client._coerce_pin_for_generator(spec, {"pin": "123"})
    assert coerced["pin"] == 123

    assert (
        client._resolve_merge_strategy("output_configured") is client_mod._merge_configured_outputs
    )
    assert (
        client._resolve_merge_strategy("output_all_status")
        is client_mod._merge_output_status_strings
    )
    assert client._resolve_merge_strategy(None) is None

    blocks = [
        client_mod.PagedBlock(block_id=1, payload={"status": "A"}),
        client_mod.PagedBlock(block_id=2, payload={"status": "B"}),
    ]
    assert client_mod._merge_output_status_strings(blocks, 2)["status"] == "AB"

    blocks = [
        client_mod.PagedBlock(block_id=1, payload={"outputs": [1, 2]}),
        client_mod.PagedBlock(block_id=2, payload={"outputs": [2, 3]}),
    ]
    merged = client_mod._merge_configured_outputs(blocks, 2)
    assert merged["outputs"] == [1, 2, 3]


def test_all_areas_disarmed() -> None:
    kernel = E27Kernel()
    kernel.state.areas[1] = AreaState(area_id=1, arm_state="disarmed")
    client = Elke27Client(kernel=kernel)
    assert client._all_areas_disarmed() is True
    kernel.state.areas[2] = AreaState(area_id=2, arm_state="armed_away")
    assert client._all_areas_disarmed() is False


@pytest.mark.asyncio
async def test_async_connect_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Elke27Client(kernel=E27Kernel())
    with pytest.raises(Elke27InvalidArgument):
        await client.async_connect("", 1, LinkKeys("a", "b", "c"))

    async def _connect(*_a, **_k):  # type: ignore[no-untyped-def]
        raise E27TransportError("x")

    monkeypatch.setattr(client._kernel, "connect", _connect)
    with pytest.raises(Elke27ConnectionError):
        await client.async_connect("h", 1, LinkKeys("a", "b", "c"))


@pytest.mark.asyncio
async def test_async_disconnect_error(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Elke27Client(kernel=E27Kernel())

    async def _close():  # type: ignore[no-untyped-def]
        raise E27TransportError("x")

    monkeypatch.setattr(client._kernel, "close", _close)
    with pytest.raises(Elke27ConnectionError):
        await client.async_disconnect()


@pytest.mark.asyncio
async def test_refresh_domain_config_errors() -> None:
    client = Elke27Client(kernel=E27Kernel())
    client._connected = True
    client._kernel.state.panel.connected = True
    with pytest.raises(Elke27InvalidArgument):
        await client.async_refresh_domain_config("")
    with pytest.raises(Elke27InvalidArgument):
        await client.async_refresh_domain_config("unknown")


def test_mark_inventory_and_status(monkeypatch: pytest.MonkeyPatch) -> None:
    kernel = E27Kernel()
    client = Elke27Client(kernel=kernel)
    kernel.state.inventory.configured_areas = {1}
    kernel.state.inventory.configured_zones = {2}
    kernel.state.inventory.configured_outputs = {3}
    called = {"queue": 0, "request": 0}
    monkeypatch.setattr(
        client,
        "_queue_bootstrap_attribs",
        lambda *_a: called.__setitem__("queue", called["queue"] + 1),
    )
    monkeypatch.setattr(
        client,
        "_request_initial_statuses",
        lambda *_a: called.__setitem__("request", called["request"] + 1),
    )
    client._mark_inventory_ready("area")
    assert called["queue"] == 1 and called["request"] == 1
    client._mark_inventory_ready("area")
    assert called["queue"] == 1


def test_refresh_helpers(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    kernel = E27Kernel()
    kernel.state.zones[1] = ZoneState(zone_id=1, area_id=1, bypassed=True)
    kernel.state.zones[2] = ZoneState(zone_id=2, area_id=1, bypassed=False)
    client = Elke27Client(kernel=kernel)
    called = {"count": 0}
    monkeypatch.setattr(
        client, "_safe_request", lambda *_a, **_k: called.__setitem__("count", called["count"] + 1)
    )
    caplog.set_level(logging.DEBUG, logger="elke27_lib.client")
    client._refresh_bypassed_zones_for_area(1)
    client._refresh_unbypassed_zones_for_area(1)
    assert called["count"] == 2
    client._refresh_all_zone_statuses_for_bypass_change(1)
    assert called["count"] == 3


def test_record_and_suppress_bypass() -> None:
    kernel = E27Kernel()
    kernel.state.zones[1] = ZoneState(zone_id=1, area_id=1, bypassed=True)
    client = Elke27Client(kernel=kernel)
    client._record_local_zone_bypass(1)
    assert client._should_suppress_area_bypass_refresh(1) is True
    client._pending_bypass_by_area[1] = 0.0
    kernel.now = lambda: 10.0  # type: ignore[assignment]
    assert client._should_suppress_area_bypass_refresh(1) is False


def test_mark_status_seen() -> None:
    kernel = E27Kernel()
    client = Elke27Client(kernel=kernel)
    client._status_pending["zone"] = {1, 2}
    client._mark_status_seen("zone", [1, 2])
    assert client._status_ready["zone"] is True


def test_on_kernel_event_no_loop() -> None:
    client = Elke27Client(kernel=E27Kernel())
    client._event_loop = None
    evt = ConnectionStateChanged(**_event_base(ConnectionStateChanged.KIND), connected=True)
    client._on_kernel_event(evt)


@pytest.mark.asyncio
async def test_async_discover_and_link_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Elke27Client(kernel=E27Kernel())

    async def _discover(*_a, **_k):  # type: ignore[no-untyped-def]
        raise E27AuthFailed("x")

    monkeypatch.setattr(client_mod.E27Kernel, "discover", _discover)
    monkeypatch.setattr(client, "_raise_v2_error", lambda *_a, **_k: None)
    with pytest.raises(AssertionError):
        await client.async_discover()

    with pytest.raises(Elke27InvalidArgument):
        await client.async_link(
            "", 1, access_code="1", passphrase="2", client_identity={"mn": "m", "sn": "s"}
        )
    with pytest.raises(Elke27InvalidArgument):
        await client.async_link(
            "h", 0, access_code="1", passphrase="2", client_identity={"mn": "m", "sn": "s"}
        )
    with pytest.raises(Elke27InvalidArgument):
        await client.async_link(
            "h", 1, access_code="", passphrase="2", client_identity={"mn": "m", "sn": "s"}
        )
    with pytest.raises(Elke27InvalidArgument):
        await client.async_link(
            "h", 1, access_code="1", passphrase="", client_identity={"mn": "m", "sn": "s"}
        )
    with pytest.raises(Elke27InvalidArgument):
        await client.async_link("h", 1, access_code="1", passphrase="2", client_identity=None)

    async def _link(*_a, **_k):  # type: ignore[no-untyped-def]
        raise E27AuthFailed("x")

    monkeypatch.setattr(client._kernel, "link", _link)
    with pytest.raises(AssertionError):
        await client.async_link(
            "h", 1, access_code="1", passphrase="2", client_identity={"mn": "m", "sn": "s"}
        )


def test_request_authenticate_timeout_and_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Elke27Client(kernel=E27Kernel())
    q: queue.Queue[dict[str, object]] = queue.Queue(maxsize=1)
    monkeypatch.setattr(client._kernel, "request", lambda *_a, **_k: 5)
    result = client._request_authenticate(("control", "authenticate"), opaque=q, pin="1234")
    assert result.ok is False and isinstance(result.error, E27Timeout)

    q = queue.Queue(maxsize=1)
    q.put("bad")  # type: ignore[arg-type]
    result = client._request_authenticate(("control", "authenticate"), opaque=q, pin="1234")
    assert result.ok is False and isinstance(result.error, ProtocolError)


@pytest.mark.asyncio
async def test_async_authenticate_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Elke27Client(kernel=E27Kernel())
    client._kernel.state.panel.session_id = 1

    class _Pending:
        def create(self, *_a, **_k):  # type: ignore[no-untyped-def]
            fut = asyncio.get_running_loop().create_future()
            return fut

        def drop(self, *_a, **_k):  # type: ignore[no-untyped-def]
            return None

    client._kernel._pending_responses = _Pending()  # type: ignore[attr-defined]
    client._kernel.register_sent_event = lambda _s, event: event.set()  # type: ignore[assignment]
    client._kernel.send_request_with_seq = lambda *_a, **_k: None  # type: ignore[assignment]
    res = await client._async_authenticate(pin=1234, timeout_s=0.0)
    assert res.ok is False and isinstance(res.error, E27Timeout)


@pytest.mark.asyncio
async def test_async_execute_permission_and_disarmed(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Elke27Client(kernel=E27Kernel())
    client._kernel.state.panel.session_id = 1
    client._kernel.state.areas[1] = AreaState(area_id=1, arm_state="armed_away")
    monkeypatch.setattr(
        client_mod,
        "permission_for_generator",
        lambda *_a, **_k: PermissionLevel.PLT_ENCRYPTION_KEY_DISARMED,
    )

    spec = client_mod.CommandSpec(
        key="needs_disarmed",
        domain="zone",
        command="get",
        generator=lambda **_k: ({}, ("zone", "get")),  # type: ignore[no-untyped-def]
        handler=lambda *_a, **_k: True,  # type: ignore[no-untyped-def]
        min_permission=PermissionLevel.PLT_ENCRYPTION_KEY_DISARMED,
    )
    monkeypatch.setitem(client_mod.COMMANDS, "needs_disarmed", spec)
    result = await client.async_execute("needs_disarmed")
    assert isinstance(result.error, Elke27PermissionError)


@pytest.mark.asyncio
async def test_async_execute_pin_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Elke27Client(kernel=E27Kernel())
    client._kernel.state.panel.session_id = 1
    monkeypatch.setattr(
        client_mod, "permission_for_generator", lambda *_a, **_k: PermissionLevel.PLT_ANY_USER
    )

    spec = client_mod.CommandSpec(
        key="needs_pin",
        domain="area",
        command="set",
        generator=lambda **_k: ({}, ("area", "set")),  # type: ignore[no-untyped-def]
        handler=lambda *_a, **_k: True,  # type: ignore[no-untyped-def]
        min_permission=PermissionLevel.PLT_ANY_USER,
    )
    monkeypatch.setitem(client_mod.COMMANDS, "needs_pin", spec)
    result = await client.async_execute("needs_pin")
    assert isinstance(result.error, Elke27PinRequiredError)
    result = await client.async_execute("needs_pin", pin="abc")
    assert isinstance(result.error, InvalidPinError)


@pytest.mark.asyncio
async def test_async_execute_single_missing_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    kernel = E27Kernel()
    client = Elke27Client(kernel=kernel)
    client._kernel.state.panel.session_id = 1
    monkeypatch.setattr(
        client_mod, "permission_for_generator", lambda *_a, **_k: PermissionLevel.PLT_ENCRYPTION_KEY
    )

    class _Pending:
        def __init__(self) -> None:
            self.futures: dict[int, asyncio.Future[dict[str, object]]] = {}

        def create(self, seq, **_k):  # type: ignore[no-untyped-def]
            fut = asyncio.get_running_loop().create_future()
            self.futures[seq] = fut
            return fut

        def drop(self, seq):  # type: ignore[no-untyped-def]
            self.futures.pop(seq, None)

    pending = _Pending()
    kernel._pending_responses = pending  # type: ignore[attr-defined]
    kernel.next_seq = lambda: 1  # type: ignore[assignment]
    kernel.register_sent_event = lambda _s, event: event.set()  # type: ignore[assignment]

    def _send(seq, domain, command, payload, **_k):  # type: ignore[no-untyped-def]
        pending.futures[seq].set_result({domain: {}})

    kernel.send_request_with_seq = _send  # type: ignore[assignment]

    spec = client_mod.CommandSpec(
        key="fake_get_missing",
        domain="zone",
        command="get",
        generator=lambda **_k: ({}, ("zone", "get")),  # type: ignore[no-untyped-def]
        handler=lambda *_a, **_k: True,  # type: ignore[no-untyped-def]
        min_permission=PermissionLevel.PLT_ENCRYPTION_KEY,
    )
    monkeypatch.setitem(client_mod.COMMANDS, "fake_get_missing", spec)
    result = await client.async_execute("fake_get_missing")
    assert result.ok is False and isinstance(result.error, ProtocolError)


@pytest.mark.asyncio
async def test_async_execute_paged_block_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    kernel = E27Kernel()
    client = Elke27Client(kernel=kernel)
    client._kernel.state.panel.session_id = 1
    monkeypatch.setattr(
        client_mod, "permission_for_generator", lambda *_a, **_k: PermissionLevel.PLT_ENCRYPTION_KEY
    )

    class _Pending:
        def __init__(self) -> None:
            self.futures: dict[int, asyncio.Future[dict[str, object]]] = {}

        def create(self, seq, **_k):  # type: ignore[no-untyped-def]
            fut = asyncio.get_running_loop().create_future()
            self.futures[seq] = fut
            return fut

        def drop(self, seq):  # type: ignore[no-untyped-def]
            self.futures.pop(seq, None)

    pending = _Pending()
    kernel._pending_responses = pending  # type: ignore[attr-defined]
    kernel.register_sent_event = lambda _s, event: event.set()  # type: ignore[assignment]
    seq_counter = {"val": 0}
    kernel.next_seq = lambda: (
        seq_counter.__setitem__("val", seq_counter["val"] + 1) or seq_counter["val"]
    )  # type: ignore[assignment]

    def _send(seq, domain, command, payload, **_k):  # type: ignore[no-untyped-def]
        block_id = payload["block_id"]
        block_count = 2 if block_id == 1 else 3
        msg = {domain: {command: {"block_id": block_id, "block_count": block_count}}}
        pending.futures[seq].set_result(msg)

    kernel.send_request_with_seq = _send  # type: ignore[assignment]

    paged = client_mod.CommandSpec(
        key="fake_paged_mismatch",
        domain="zone",
        command="get_configured",
        generator=lambda block_id: ({"block_id": block_id}, ("zone", "get_configured")),  # type: ignore[no-untyped-def]
        handler=lambda *_a, **_k: True,  # type: ignore[no-untyped-def]
        min_permission=PermissionLevel.PLT_ENCRYPTION_KEY,
        response_mode="paged_blocks",
        block_field="block_id",
        block_count_field="block_count",
        merge_strategy=lambda blocks, total: {"blocks": len(blocks), "block_count": total},
    )
    monkeypatch.setitem(client_mod.COMMANDS, "fake_paged_mismatch", paged)
    result = await client.async_execute("fake_paged_mismatch")
    assert result.ok is False and isinstance(result.error, ProtocolError)


def test_request_and_pump_once_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    kernel = E27Kernel()
    client = Elke27Client(kernel=kernel)
    monkeypatch.setattr(kernel, "request", lambda *_a, **_k: (_ for _ in ()).throw(E27Error("x")))
    result = client.request(("zone", "get_status"), zone_id=1)
    assert result.ok is False

    class _Sess:
        cfg = SessionConfig(host="h", port=1)

        def pump_once(self, **_k):  # type: ignore[no-untyped-def]
            raise SessionProtocolError("x")

    kernel._session = _Sess()  # type: ignore[assignment]
    result = client.pump_once()
    assert result.ok is False and isinstance(result.error, ProtocolError)
