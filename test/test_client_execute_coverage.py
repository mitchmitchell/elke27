from __future__ import annotations

import asyncio
import builtins
import queue
from typing import Any, Mapping

import pytest

import elke27_lib.client as client_mod
from elke27_lib.client import Elke27Client, Result
from datetime import UTC, datetime

from types import SimpleNamespace

from elke27_lib.errors import (
    AuthorizationRequired,
    Elke27Error,
    ConnectionLost,
    E27Error,
    E27Timeout,
    E27TransportError,
    InvalidPin,
    InvalidPinError,
    ProtocolError,
    Elke27ConnectionError,
    Elke27PinRequiredError,
    Elke27TimeoutError,
)
from elke27_lib.events import OutputsStatusBulkUpdated, ZoneStatusUpdated, ZonesStatusBulkUpdated
from elke27_lib.kernel import E27Kernel, KernelError
from elke27_lib.permissions import PermissionLevel
from elke27_lib.states import CsmSnapshot


def _patch_send_with_msg(
    monkeypatch: pytest.MonkeyPatch,
    kernel: E27Kernel,
    msg: Mapping[str, Any],
    *,
    exc: BaseException | None = None,
    resolve: bool = True,
) -> None:
    def _send(
        seq: int,
        domain: str,
        name: str,
        payload: Any,
        *,
        pending: bool,
        opaque: Any,
        expected_route: Any,
        priority: Any = None,
        timeout_s: float | None = None,
        expects_reply: bool = True,
    ) -> int:
        if exc is not None:
            raise exc
        kernel._signal_sent_event(seq)
        if resolve:
            kernel.pending_responses.resolve(seq, msg)
        return seq

    monkeypatch.setattr(kernel, "send_request_with_seq", _send)


def _make_command_spec(
    *,
    key: str,
    response_mode: str,
    block_field: str | None = None,
    block_count_field: str | None = None,
    merge_strategy: Any = None,
) -> client_mod.CommandSpec:
    def _gen(**_kwargs: Any) -> tuple[dict[str, Any], tuple[str, str]]:
        return {"ok": True}, ("test", "cmd")

    _gen.__name__ = f"generator_{key}"
    return client_mod.CommandSpec(
        key=key,
        domain="test",
        command="cmd",
        generator=_gen,
        handler=lambda *_a, **_k: None,  # type: ignore[no-untyped-def]
        min_permission=PermissionLevel.PLT_ENCRYPTION_KEY,
        response_mode=response_mode,
        block_field=block_field,
        block_count_field=block_count_field,
        merge_strategy=merge_strategy,
        first_block=1,
    )


def test_raise_v2_error_and_command_error_timeout_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Elke27Client(kernel=E27Kernel())

    class _CustomTimeout(Exception):
        pass

    monkeypatch.setattr(builtins, "TimeoutError", _CustomTimeout)
    with pytest.raises(Elke27TimeoutError):
        client._raise_v2_error(_CustomTimeout("x"), phase="phase")

    with pytest.raises(Elke27TimeoutError):
        client._raise_v2_command_error(E27Timeout("t"))

    with pytest.raises(Elke27Error):
        client._raise_v2_command_error(Elke27Error("boom", code="x", is_transient=False))


def test_handle_kernel_event_bulk_logging_and_mark_seen(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    kernel = E27Kernel()
    client = Elke27Client(kernel=kernel)
    marks: list[tuple[str, list[int]]] = []

    monkeypatch.setattr(
        client,
        "_mark_status_seen",
        lambda domain, ids: marks.append((domain, list(ids))),
    )

    caplog.set_level("DEBUG", logger="elke27_lib.client")
    client._handle_kernel_event(
        ZonesStatusBulkUpdated(
            kind=ZonesStatusBulkUpdated.KIND,
            at=0.0,
            seq=None,
            classification="LOCAL",
            route=("__local__", ZonesStatusBulkUpdated.KIND),
            session_id=1,
            updated_ids=(1, 2),
            updated_count=2,
        )
    )
    client._handle_kernel_event(
        OutputsStatusBulkUpdated(
            kind=OutputsStatusBulkUpdated.KIND,
            at=0.0,
            seq=None,
            classification="LOCAL",
            route=("__local__", OutputsStatusBulkUpdated.KIND),
            session_id=1,
            updated_ids=(3,),
            updated_count=1,
        )
    )
    client._handle_kernel_event(
        ZoneStatusUpdated(
            kind=ZoneStatusUpdated.KIND,
            at=0.0,
            seq=None,
            classification="LOCAL",
            route=("__local__", ZoneStatusUpdated.KIND),
            session_id=1,
            zone_id=1,
            changed_fields=("status",),
        )
    )

    assert ("zone", [1, 2]) in marks
    assert ("output", [3]) in marks


@pytest.mark.asyncio
async def test_refresh_domain_config_and_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    kernel = E27Kernel()
    kernel.state.panel.connected = True
    kernel.state.panel.session_id = 1
    client = Elke27Client(kernel=kernel)
    client._connected = True

    snapshot = CsmSnapshot(domain_csms={}, table_csms={}, version=1, updated_at=datetime.now(UTC))
    kernel.state.csm_snapshot = snapshot
    assert client.get_csm_snapshot() is snapshot

    called: list[str] = []
    monkeypatch.setattr(client, "_refresh_zone_config", lambda: called.append("zone"))
    monkeypatch.setattr(client, "_refresh_output_config", lambda: called.append("output"))
    monkeypatch.setattr(client, "_refresh_tstat_config", lambda: called.append("tstat"))

    await client.async_refresh_domain_config("zone")
    await client.async_refresh_domain_config("output")
    await client.async_refresh_domain_config("tstat")
    assert called == ["zone", "output", "tstat"]

    kernel2 = E27Kernel()
    client2 = Elke27Client(kernel=kernel2)
    requests: list[tuple[tuple[str, str], dict[str, Any]]] = []
    monkeypatch.setattr(
        client2,
        "_safe_request",
        lambda route, **kw: requests.append((route, dict(kw))),
    )
    kernel2.state.inventory.configured_zones = {2, 1}
    client2._refresh_area_config()
    client2._refresh_zone_config()
    client2._refresh_output_config()
    client2._refresh_tstat_config()
    assert ("zone", "get_table_info") in [item[0] for item in requests]
    assert ("zone", "get_configured") in [item[0] for item in requests]
    assert ("zone", "get_defs") in [item[0] for item in requests]
    assert ("zone", "get_attribs") in [item[0] for item in requests]


@pytest.mark.asyncio
async def test_async_arm_disarm_error_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    kernel = E27Kernel()
    kernel.state.panel.connected = True
    client = Elke27Client(kernel=kernel)
    client._connected = True

    with pytest.raises(client_mod.Elke27InvalidArgument):
        await client.async_arm_area(1, mode=client_mod.ArmMode.DISARMED, pin=None)

    async def _fail_execute(*_a: Any, **_k: Any) -> Result[Mapping[str, Any]]:
        return Result(ok=False, data=None, error=None)

    monkeypatch.setattr(client, "async_execute", _fail_execute)
    with pytest.raises(client_mod.Elke27ProtocolErrorV2):
        await client.async_arm_area(1, mode=client_mod.ArmMode.ARMED_AWAY, pin="1234")
    with pytest.raises(client_mod.Elke27ProtocolErrorV2):
        await client.async_disarm_area(1, pin="1234")


@pytest.mark.asyncio
async def test_discover_link_connect_close(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Elke27Client(kernel=E27Kernel())

    async def _discover(*_a: Any, **_k: Any) -> list[dict[str, Any]]:
        return [{"host": "x"}]

    monkeypatch.setattr(client_mod.E27Kernel, "discover", _discover)
    ok = await client.discover()
    assert ok.ok is True

    async def _discover_fail(*_a: Any, **_k: Any) -> list[dict[str, Any]]:
        raise E27TransportError("x")

    monkeypatch.setattr(client_mod.E27Kernel, "discover", _discover_fail)
    err = await client.discover()
    assert err.ok is False

    async def _link(*_a: Any, **_k: Any) -> dict[str, str]:
        return {"tempkey_hex": "aa", "linkkey_hex": "bb", "linkhmac_hex": "cc"}

    monkeypatch.setattr(client._kernel, "link", _link)
    identity = client_mod.E27Identity(mn="m", sn="s", fwver="f", hwver="h", osver="o")
    link_result = await client.link({}, identity, credentials="y")
    assert link_result.ok is True

    async def _link_fail(*_a: Any, **_k: Any) -> dict[str, str]:
        raise E27TransportError("x")

    monkeypatch.setattr(client._kernel, "link", _link_fail)
    link_result = await client.link({}, identity, credentials="y")
    assert link_result.ok is False

    async def _connect(*_a: Any, **_k: Any) -> None:
        return None

    monkeypatch.setattr(client._kernel, "connect", _connect)
    connect_result = await client.connect({"tempkey_hex": "aa"})
    assert connect_result.ok is True

    async def _connect_fail(*_a: Any, **_k: Any) -> None:
        raise E27TransportError("x")

    monkeypatch.setattr(client._kernel, "connect", _connect_fail)
    connect_result = await client.connect({"tempkey_hex": "aa"})
    assert connect_result.ok is False

    async def _close_fail() -> None:
        raise E27TransportError("x")

    monkeypatch.setattr(client._kernel, "close", _close_fail)
    close_result = await client.close()
    assert close_result.ok is False


@pytest.mark.asyncio
async def test_close_disconnect_request_success(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Elke27Client(kernel=E27Kernel())

    async def _close() -> None:
        return None

    monkeypatch.setattr(client._kernel, "close", _close)
    assert (await client.close()).ok is True
    assert (await client.disconnect()).ok is True

    monkeypatch.setattr(client._kernel, "request", lambda *_a, **_k: 42)
    result = client.request(("area", "get_table_info"))
    assert result.ok is True


def test_request_authenticate_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Elke27Client(kernel=E27Kernel())
    bad = client.request(("control", "authenticate"), opaque=object())
    assert bad.ok is False

    class _ImmediateEmpty:
        def get(self, *_a: Any, **_k: Any) -> dict[str, object]:
            raise queue.Empty

    monkeypatch.setattr(client._kernel, "request", lambda *_a, **_k: 5)
    result = client.request(("control", "authenticate"), opaque=_ImmediateEmpty())
    assert result.ok is False
    assert isinstance(result.error, E27Timeout)

    monkeypatch.setattr(
        client._kernel, "request", lambda *_a, **_k: (_ for _ in ()).throw(E27TransportError("x"))
    )
    result = client.request(("control", "authenticate"), opaque=queue.Queue(maxsize=1))
    assert result.ok is False

    monkeypatch.setattr(client._kernel, "request", lambda *_a, **_k: 6)
    auth_queue = queue.Queue(maxsize=1)
    auth_queue.put("nope")
    result = client.request(("control", "authenticate"), opaque=auth_queue)
    assert result.ok is False

    auth_queue = queue.Queue(maxsize=1)
    auth_queue.put({"error_code": 7})
    result = client.request(("control", "authenticate"), opaque=auth_queue)
    assert result.ok is False
    assert isinstance(result.error, InvalidPin)


@pytest.mark.asyncio
async def test_async_execute_control_authenticate_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Elke27Client(kernel=E27Kernel())
    client._kernel.state.panel.session_id = 1

    result = await client.async_execute("control_authenticate")
    assert isinstance(result.error, Elke27PinRequiredError)
    result = await client.async_execute("control_authenticate", pin="1x")
    assert isinstance(result.error, InvalidPinError)
    result = await client.async_execute("control_authenticate", pin=0)
    assert isinstance(result.error, InvalidPinError)
    result = await client.async_execute("control_authenticate", pin=object())
    assert isinstance(result.error, InvalidPinError)

    async def _ok_auth(**_k: Any) -> Result[Mapping[str, Any]]:
        return Result(ok=True, data={"ok": True}, error=None)

    monkeypatch.setattr(client, "_async_authenticate", _ok_auth)
    ok = await client.async_execute("control_authenticate", pin=1234)
    assert ok.ok is True
    ok = await client.async_execute("control_authenticate", pin="1234")
    assert ok.ok is True

    monkeypatch.setattr(
        client_mod,
        "permission_for_generator",
        lambda *_a, **_k: (_ for _ in ()).throw(client_mod.Elke27ProtocolErrorV2("bad")),
    )
    err = await client.async_execute("control_authenticate", pin="1234")
    assert isinstance(err.error, client_mod.Elke27ProtocolErrorV2)

    monkeypatch.setattr(
        client_mod,
        "permission_for_generator",
        lambda *_a, **_k: PermissionLevel.PLT_ENCRYPTION_KEY,
    )
    client._kernel.state.panel.session_id = None
    err = await client.async_execute("control_authenticate", pin="1234")
    assert err.ok is False


@pytest.mark.asyncio
async def test_async_execute_single_error_handling(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Elke27Client(kernel=E27Kernel())
    client._kernel.state.panel.session_id = 1

    spec = _make_command_spec(key="test_single", response_mode="single")
    monkeypatch.setitem(client_mod.COMMANDS, "test_single", spec)
    monkeypatch.setattr(
        client_mod,
        "permission_for_generator",
        lambda *_a, **_k: PermissionLevel.PLT_ENCRYPTION_KEY,
    )

    _patch_send_with_msg(monkeypatch, client._kernel, {"test": {"cmd": {"value": 1}}})
    ok = await client.async_execute("test_single")
    assert ok.ok is True

    _patch_send_with_msg(monkeypatch, client._kernel, {"test": {"cmd": {"error_code": 11008}}})
    err = await client.async_execute("test_single")
    assert isinstance(err.error, AuthorizationRequired)

    _patch_send_with_msg(monkeypatch, client._kernel, {"test": {"other": 1}})
    err = await client.async_execute("test_single")
    assert isinstance(err.error, ProtocolError)

    _patch_send_with_msg(
        monkeypatch,
        client._kernel,
        {"test": {"cmd": {"value": 1}}},
        exc=E27TransportError("x"),
    )
    err = await client.async_execute("test_single")
    assert isinstance(err.error, ConnectionLost)

    _patch_send_with_msg(monkeypatch, client._kernel, {"test": {"cmd": {"value": 1}}}, resolve=False)
    err = await client.async_execute("test_single", timeout_s=0.01)
    assert isinstance(err.error, E27Timeout)

    def _send_fail_future(*args: Any, **kwargs: Any) -> int:
        seq = args[0]
        client._kernel._signal_sent_event(seq)
        client._kernel.pending_responses.fail(seq, E27TransportError("x"))
        return seq

    monkeypatch.setattr(client._kernel, "send_request_with_seq", _send_fail_future)
    err = await client.async_execute("test_single")
    assert isinstance(err.error, ConnectionLost)

    monkeypatch.setattr(
        client_mod,
        "permission_for_generator",
        lambda *_a, **_k: PermissionLevel.PLT_ANY_USER,
    )
    err = await client.async_execute("test_single")
    assert isinstance(err.error, Elke27PinRequiredError)
    err = await client.async_execute("test_single", pin="abc")
    assert isinstance(err.error, InvalidPinError)
    err = await client.async_execute("test_single", pin=0)
    assert isinstance(err.error, InvalidPinError)
    err = await client.async_execute("test_single", pin=object())
    assert isinstance(err.error, InvalidPinError)

    _patch_send_with_msg(monkeypatch, client._kernel, {"test": {"cmd": {"error_code": 7}}})
    err = await client.async_execute("test_single", pin="1234")
    assert isinstance(err.error, E27Error)


@pytest.mark.asyncio
async def test_async_execute_unknown_command(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Elke27Client(kernel=E27Kernel())
    err = await client.async_execute("does_not_exist")
    assert isinstance(err.error, ProtocolError)


@pytest.mark.asyncio
async def test_async_execute_paged_error_handling(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Elke27Client(kernel=E27Kernel())
    client._kernel.state.panel.session_id = 1

    spec = _make_command_spec(
        key="test_paged",
        response_mode="paged_blocks",
        block_field="block_id",
        block_count_field="block_count",
        merge_strategy=lambda blocks, total: {"blocks": len(blocks), "total": total},
    )
    monkeypatch.setitem(client_mod.COMMANDS, "test_paged", spec)
    monkeypatch.setattr(
        client_mod,
        "permission_for_generator",
        lambda *_a, **_k: PermissionLevel.PLT_ENCRYPTION_KEY,
    )

    def _send_with_block_count(*args: Any, **kwargs: Any) -> int:
        seq = args[0]
        client._kernel._signal_sent_event(seq)
        msg = {"test": {"cmd": {"block_count": 1, "items": [1]}}}
        client._kernel.pending_responses.resolve(seq, msg)
        return seq

    monkeypatch.setattr(client._kernel, "send_request_with_seq", _send_with_block_count)
    ok = await client.async_execute("test_paged")
    assert ok.ok is True

    bad_spec = _make_command_spec(key="test_bad_mode", response_mode="stream")
    monkeypatch.setitem(client_mod.COMMANDS, "test_bad_mode", bad_spec)
    err = await client.async_execute("test_bad_mode")
    assert isinstance(err.error, ProtocolError)

    bad_spec2 = _make_command_spec(key="test_no_block", response_mode="paged_blocks")
    monkeypatch.setitem(client_mod.COMMANDS, "test_no_block", bad_spec2)
    err = await client.async_execute("test_no_block")
    assert isinstance(err.error, ProtocolError)

    bad_spec3 = _make_command_spec(
        key="test_no_merge",
        response_mode="paged_blocks",
        block_field="block_id",
        block_count_field="block_count",
        merge_strategy=None,
    )
    monkeypatch.setitem(client_mod.COMMANDS, "test_no_merge", bad_spec3)
    err = await client.async_execute("test_no_merge")
    assert isinstance(err.error, ProtocolError)

    def _send_missing_payload(*args: Any, **kwargs: Any) -> int:
        seq = args[0]
        client._kernel._signal_sent_event(seq)
        client._kernel.pending_responses.resolve(seq, {"test": {"other": 1}})
        return seq

    monkeypatch.setattr(client._kernel, "send_request_with_seq", _send_missing_payload)
    err = await client.async_execute("test_paged")
    assert isinstance(err.error, ProtocolError)

    def _send_error_code(*args: Any, **kwargs: Any) -> int:
        seq = args[0]
        client._kernel._signal_sent_event(seq)
        client._kernel.pending_responses.resolve(seq, {"test": {"cmd": {"error_code": 11008}}})
        return seq

    monkeypatch.setattr(client._kernel, "send_request_with_seq", _send_error_code)
    err = await client.async_execute("test_paged")
    assert isinstance(err.error, AuthorizationRequired)

    def _send_missing_block_count(*args: Any, **kwargs: Any) -> int:
        seq = args[0]
        client._kernel._signal_sent_event(seq)
        client._kernel.pending_responses.resolve(seq, {"test": {"cmd": {"items": [1]}}})
        return seq

    monkeypatch.setattr(client._kernel, "send_request_with_seq", _send_missing_block_count)
    err = await client.async_execute("test_paged")
    assert isinstance(err.error, ProtocolError)

    messages = iter(
        [
            {"test": {"cmd": {"block_count": 2, "items": [1]}}},
            {"test": {"cmd": {"block_count": 3, "items": [2]}}},
        ]
    )

    def _send_mismatch(*args: Any, **kwargs: Any) -> int:
        seq = args[0]
        client._kernel._signal_sent_event(seq)
        client._kernel.pending_responses.resolve(seq, next(messages))
        return seq

    monkeypatch.setattr(client._kernel, "send_request_with_seq", _send_mismatch)
    err = await client.async_execute("test_paged")
    assert isinstance(err.error, ProtocolError)

    def _send_raise(*args: Any, **kwargs: Any) -> int:
        raise E27TransportError("x")

    monkeypatch.setattr(client._kernel, "send_request_with_seq", _send_raise)
    err = await client.async_execute("test_paged")
    assert isinstance(err.error, ConnectionLost)

    def _send_fail_future(*args: Any, **kwargs: Any) -> int:
        seq = args[0]
        client._kernel._signal_sent_event(seq)
        client._kernel.pending_responses.fail(seq, E27TransportError("x"))
        return seq

    monkeypatch.setattr(client._kernel, "send_request_with_seq", _send_fail_future)
    err = await client.async_execute("test_paged")
    assert isinstance(err.error, ConnectionLost)

    def _send_timeout(*args: Any, **kwargs: Any) -> int:
        seq = args[0]
        client._kernel._signal_sent_event(seq)
        return seq

    monkeypatch.setattr(client._kernel, "send_request_with_seq", _send_timeout)
    err = await client.async_execute("test_paged", timeout_s=0.01)
    assert isinstance(err.error, E27Timeout)

    def _merge_fail(_blocks: Any, _total: Any) -> Any:
        raise RuntimeError("merge")

    merge_spec = _make_command_spec(
        key="test_merge_fail",
        response_mode="paged_blocks",
        block_field="block_id",
        block_count_field="block_count",
        merge_strategy=_merge_fail,
    )
    monkeypatch.setitem(client_mod.COMMANDS, "test_merge_fail", merge_spec)
    monkeypatch.setattr(client._kernel, "send_request_with_seq", _send_with_block_count)
    err = await client.async_execute("test_merge_fail")
    assert isinstance(err.error, ProtocolError)

    def _send_error_code_other(*args: Any, **kwargs: Any) -> int:
        seq = args[0]
        client._kernel._signal_sent_event(seq)
        client._kernel.pending_responses.resolve(seq, {"test": {"cmd": {"error_code": 7}}})
        return seq

    monkeypatch.setattr(client._kernel, "send_request_with_seq", _send_error_code_other)
    err = await client.async_execute("test_paged")
    assert isinstance(err.error, E27Error)

    def _gen_fail(**_k: Any) -> tuple[dict[str, Any], tuple[str, str]]:
        raise E27TransportError("x")

    fail_spec = client_mod.CommandSpec(
        key="test_paged_gen_fail",
        domain="test",
        command="cmd",
        generator=_gen_fail,
        handler=lambda *_a, **_k: None,  # type: ignore[no-untyped-def]
        response_mode="paged_blocks",
        block_field="block_id",
        block_count_field="block_count",
        merge_strategy=lambda blocks, total: {"blocks": len(blocks), "total": total},
        first_block=1,
        min_permission=PermissionLevel.PLT_ENCRYPTION_KEY,
    )
    monkeypatch.setitem(client_mod.COMMANDS, "test_paged_gen_fail", fail_spec)
    err = await client.async_execute("test_paged_gen_fail")
    assert isinstance(err.error, ConnectionLost)

    def _gen_not_impl(**_k: Any) -> tuple[dict[str, Any], tuple[str, str]]:
        raise NotImplementedError("nope")

    not_impl = client_mod.CommandSpec(
        key="test_paged_not_impl",
        domain="test",
        command="cmd",
        generator=_gen_not_impl,
        handler=lambda *_a, **_k: None,  # type: ignore[no-untyped-def]
        response_mode="paged_blocks",
        block_field="block_id",
        block_count_field="block_count",
        merge_strategy=lambda blocks, total: {"blocks": len(blocks), "total": total},
        first_block=1,
        min_permission=PermissionLevel.PLT_ENCRYPTION_KEY,
    )
    monkeypatch.setitem(client_mod.COMMANDS, "test_paged_not_impl", not_impl)
    err = await client.async_execute("test_paged_not_impl")
    assert isinstance(err.error, NotImplementedError)


@pytest.mark.asyncio
async def test_async_execute_attribs_inventory_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Elke27Client(kernel=E27Kernel())
    client._kernel.state.panel.session_id = 1

    async def _wrap(command_key: str, *args: Any, **kwargs: Any) -> Result[Mapping[str, Any]]:
        if command_key in {"area_get_configured", "zone_get_configured"}:
            return Result(ok=False, data=None, error=ProtocolError("fail"))
        if command_key == "output_get_configured":
            return Result(ok=True, data={"outputs": [1, 2]}, error=None)
        if command_key == "user_get_configured":
            return Result(ok=True, data={"users": [2]}, error=None)
        if command_key == "keypad_get_configured":
            return Result(ok=True, data={"keypads": [3]}, error=None)
        return await original(command_key, *args, **kwargs)

    original = client.async_execute
    monkeypatch.setattr(client, "async_execute", _wrap)
    monkeypatch.setattr(
        client_mod,
        "permission_for_generator",
        lambda *_a, **_k: PermissionLevel.PLT_ENCRYPTION_KEY,
    )

    result = await client.async_execute("area_get_attribs", area_id=1)
    assert result.ok is False
    result = await client.async_execute("zone_get_attribs", zone_id=1)
    assert result.ok is False

    def _send_for_expected(*args: Any, **kwargs: Any) -> int:
        seq = args[0]
        expected = kwargs.get("expected_route")
        client._kernel._signal_sent_event(seq)
        client._kernel.pending_responses.resolve(seq, {expected[0]: {expected[1]: {"ok": True}}})
        return seq

    monkeypatch.setattr(client._kernel, "send_request_with_seq", _send_for_expected)
    out = await client.async_execute("output_get_attribs", output_id=1)
    assert out.ok is True
    user = await client.async_execute("user_get_attribs", user_id=2)
    assert user.ok is True
    keypad = await client.async_execute("keypad_get_attribs", keypad_id=3)
    assert keypad.ok is True


@pytest.mark.asyncio
async def test_async_execute_attribs_configured_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Elke27Client(kernel=E27Kernel())
    client._kernel.state.panel.session_id = 1
    original = client.async_execute

    async def _wrap(command_key: str, *args: Any, **kwargs: Any) -> Result[Mapping[str, Any]]:
        if command_key in {
            "output_get_configured",
            "user_get_configured",
            "keypad_get_configured",
        }:
            return Result(ok=False, data=None, error=ProtocolError("fail"))
        return await original(command_key, *args, **kwargs)

    monkeypatch.setattr(client, "async_execute", _wrap)
    monkeypatch.setattr(
        client_mod,
        "permission_for_generator",
        lambda *_a, **_k: PermissionLevel.PLT_ENCRYPTION_KEY,
    )

    out = await client.async_execute("output_get_attribs", output_id=1)
    assert out.ok is False
    user = await client.async_execute("user_get_attribs", user_id=2)
    assert user.ok is False
    keypad = await client.async_execute("keypad_get_attribs", keypad_id=3)
    assert keypad.ok is False


@pytest.mark.asyncio
async def test_async_execute_generator_exceptions(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Elke27Client(kernel=E27Kernel())
    client._kernel.state.panel.session_id = 1

    def _gen_not_impl(**_k: Any) -> tuple[dict[str, Any], tuple[str, str]]:
        raise NotImplementedError("nope")

    def _gen_fail(**_k: Any) -> tuple[dict[str, Any], tuple[str, str]]:
        raise E27TransportError("x")

    not_impl = client_mod.CommandSpec(
        key="test_not_impl",
        domain="test",
        command="cmd",
        generator=_gen_not_impl,
        handler=lambda *_a, **_k: None,  # type: ignore[no-untyped-def]
        response_mode="single",
        min_permission=PermissionLevel.PLT_ENCRYPTION_KEY,
    )
    gen_fail = client_mod.CommandSpec(
        key="test_gen_fail",
        domain="test",
        command="cmd",
        generator=_gen_fail,
        handler=lambda *_a, **_k: None,  # type: ignore[no-untyped-def]
        response_mode="single",
        min_permission=PermissionLevel.PLT_ENCRYPTION_KEY,
    )

    monkeypatch.setitem(client_mod.COMMANDS, "test_not_impl", not_impl)
    monkeypatch.setitem(client_mod.COMMANDS, "test_gen_fail", gen_fail)
    monkeypatch.setattr(
        client_mod,
        "permission_for_generator",
        lambda *_a, **_k: PermissionLevel.PLT_ENCRYPTION_KEY,
    )

    err = await client.async_execute("test_not_impl")
    assert isinstance(err.error, NotImplementedError)
    err = await client.async_execute("test_gen_fail")
    assert isinstance(err.error, ConnectionLost)


@pytest.mark.asyncio
async def test_async_execute_zone_set_status_records_bypass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Elke27Client(kernel=E27Kernel())
    client._kernel.state.panel.session_id = 1
    called: list[int] = []
    monkeypatch.setattr(client, "_record_local_zone_bypass", lambda zone_id: called.append(zone_id))
    monkeypatch.setattr(
        client_mod,
        "permission_for_generator",
        lambda *_a, **_k: PermissionLevel.PLT_ENCRYPTION_KEY,
    )

    def _send_for_expected(*args: Any, **kwargs: Any) -> int:
        seq = args[0]
        expected = kwargs.get("expected_route")
        client._kernel._signal_sent_event(seq)
        client._kernel.pending_responses.resolve(seq, {expected[0]: {expected[1]: {"ok": True}}})
        return seq

    monkeypatch.setattr(client._kernel, "send_request_with_seq", _send_for_expected)
    await client.async_execute("zone_set_status", zone_id=4, pin="1234", bypassed=True)
    assert called == [4]


@pytest.mark.asyncio
async def test_async_authenticate_error_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Elke27Client(kernel=E27Kernel())

    def _send_raise(*_a: Any, **_k: Any) -> int:
        raise E27TransportError("x")

    monkeypatch.setattr(client._kernel, "send_request_with_seq", _send_raise)
    err = await client._async_authenticate(pin=1234, timeout_s=0.01)
    assert isinstance(err.error, ConnectionLost)

    def _send_fail(*args: Any, **kwargs: Any) -> int:
        seq = args[0]
        client._kernel._signal_sent_event(seq)
        client._kernel.pending_responses.fail(seq, E27TransportError("x"))
        return seq

    monkeypatch.setattr(client._kernel, "send_request_with_seq", _send_fail)
    err = await client._async_authenticate(pin=1234, timeout_s=0.01)
    assert isinstance(err.error, ConnectionLost)


@pytest.mark.asyncio
async def test_async_execute_cancellation_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Elke27Client(kernel=E27Kernel())
    client._kernel.state.panel.session_id = 1
    spec = _make_command_spec(key="test_cancel", response_mode="single")
    monkeypatch.setitem(client_mod.COMMANDS, "test_cancel", spec)
    monkeypatch.setattr(
        client_mod,
        "permission_for_generator",
        lambda *_a, **_k: PermissionLevel.PLT_ENCRYPTION_KEY,
    )

    def _send_no_resolve(*args: Any, **kwargs: Any) -> int:
        seq = args[0]
        client._kernel._signal_sent_event(seq)
        return seq

    monkeypatch.setattr(client._kernel, "send_request_with_seq", _send_no_resolve)
    task = asyncio.create_task(client.async_execute("test_cancel", timeout_s=1.0))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    paged = _make_command_spec(
        key="test_cancel_paged",
        response_mode="paged_blocks",
        block_field="block_id",
        block_count_field="block_count",
        merge_strategy=lambda blocks, total: {"blocks": len(blocks), "total": total},
    )
    monkeypatch.setitem(client_mod.COMMANDS, "test_cancel_paged", paged)
    task = asyncio.create_task(client.async_execute("test_cancel_paged", timeout_s=1.0))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_async_authenticate_cancellation(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Elke27Client(kernel=E27Kernel())

    def _send_no_resolve(*args: Any, **kwargs: Any) -> int:
        seq = args[0]
        client._kernel._signal_sent_event(seq)
        return seq

    monkeypatch.setattr(client._kernel, "send_request_with_seq", _send_no_resolve)
    task = asyncio.create_task(client._async_authenticate(pin=1234, timeout_s=1.0))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_misc_helpers_coverage(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Elke27Client(kernel=E27Kernel())
    assert client.panel_info is client._kernel.state.panel
    assert isinstance(client.table_info, Mapping)
    assert list(client.outputs.values()) == []
    assert list(client.lights.values()) == []
    assert list(client.thermostats.values()) == []

    def _pump_once(*_a: Any, **_k: Any) -> dict[str, Any]:
        return {"ok": True}

    client._kernel._session = SimpleNamespace(
        pump_once=_pump_once,
        cfg=SimpleNamespace(host="host", port=2101),
    )
    monkeypatch.setattr(client._kernel.session, "pump_once", _pump_once)
    assert client.pump_once().ok is True

    def _sig_gen(*, pin: int) -> tuple[dict[str, Any], tuple[str, str]]:
        return {"pin": pin}, ("test", "cmd")
    _sig_gen.__annotations__["pin"] = int

    spec = client_mod.CommandSpec(
        key="x",
        domain="test",
        command="cmd",
        generator=_sig_gen,
        handler=lambda *_a, **_k: None,  # type: ignore[no-untyped-def]
        min_permission=PermissionLevel.PLT_ENCRYPTION_KEY,
    )
    assert client._coerce_pin_for_generator(spec, {"pin": "123"})["pin"] == 123

    bad_spec = client_mod.CommandSpec(
        key="x2",
        domain="test",
        command="cmd",
        generator=1,  # type: ignore[arg-type]
        handler=lambda *_a, **_k: None,  # type: ignore[no-untyped-def]
        min_permission=PermissionLevel.PLT_ENCRYPTION_KEY,
    )
    client._coerce_pin_for_generator(bad_spec, {"pin": "1"})

    err = client._extract_response_payload(
        {"test": {"cmd": 7, "error_code": 5}}, ("test", "cmd")
    )
    assert err["error_code"] == 5
    assert client._coerce_block_count("nope") is None

    with pytest.raises(Elke27ConnectionError):
        client._raise_v2_error(E27TransportError("x"), phase="phase")

    try:
        raise ValueError("boom")
    except ValueError as exc:  # noqa: PERF203
        err = KernelError("kernel")
        err.__cause__ = exc
        normalized = client._normalize_error(err, phase="phase")
        assert isinstance(normalized, ProtocolError)
