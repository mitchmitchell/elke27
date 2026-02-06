from __future__ import annotations

import asyncio
import types
from types import SimpleNamespace
from typing import Any, Mapping

import pytest

import elke27_lib.kernel as kernel_mod
from elke27_lib.errors import ConnectionLost, E27Error, E27Timeout
from elke27_lib.events import ConnectionStateChanged
from elke27_lib.kernel import E27Kernel, KernelError, KernelMissingContextError
from elke27_lib.linking import E27Identity, E27LinkKeys
from elke27_lib.outbound import OutboundPriority
from elke27_lib.permissions import PermissionLevel
from elke27_lib.session import SessionError, SessionIOError, SessionProtocolError, SessionState


def test_as_mapping_and_redact_value(monkeypatch: pytest.MonkeyPatch) -> None:
    assert kernel_mod._as_mapping({"a": 1}) is not None
    assert kernel_mod._as_mapping(1) is None

    monkeypatch.setattr(kernel_mod, "REDACT_DIAGNOSTICS", True)
    redacted = kernel_mod._redact_value([{"pin": "123"}])
    assert redacted == [{"pin": "***"}]
    redacted_tuple = kernel_mod._redact_value(({"pin": "123"},))
    assert redacted_tuple == ({"pin": "***"},)


def test_session_property_raises() -> None:
    kernel = E27Kernel()
    with pytest.raises(KernelError):
        _ = kernel.session


@pytest.mark.asyncio
async def test_discover_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Scanner:
        async def async_scan(self, *_a: Any, **_k: Any) -> list[object]:
            raise RuntimeError("boom")

    monkeypatch.setattr(kernel_mod.discovery, "AIOELKDiscovery", _Scanner)
    with pytest.raises(KernelError):
        await E27Kernel.discover()

    class _Scanner2:
        async def async_scan(self, *_a: Any, **_k: Any) -> list[object]:
            return [object()]

    monkeypatch.setattr(kernel_mod.discovery, "AIOELKDiscovery", _Scanner2)
    with pytest.raises(KernelError):
        await E27Kernel.discover()


@pytest.mark.asyncio
async def test_connect_missing_context() -> None:
    kernel = E27Kernel()
    link_keys = E27LinkKeys(tempkey_hex="aa", linkkey_hex="bb", linkhmac_hex="cc")
    identity = E27Identity(mn="m", sn="s", fwver="f", hwver="h", osver="o")
    with pytest.raises(KernelMissingContextError):
        await kernel.connect(link_keys, client_identity=identity, session_config=None, panel=None)

    bad_identity = E27Identity(mn="", sn="s", fwver="f", hwver="h", osver="o")
    with pytest.raises(KernelMissingContextError):
        await kernel.connect(
            link_keys,
            client_identity=bad_identity,
            session_config=kernel_mod.session_mod.SessionConfig(host="h", port=1),
        )


@pytest.mark.asyncio
async def test_close_paths(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    kernel = E27Kernel()
    await kernel.close()

    class _Session:
        info = SimpleNamespace(session_id=1)
        state = SessionState.ACTIVE

        def close(self) -> None:
            raise OSError("boom")

    kernel._session = _Session()
    caplog.set_level("DEBUG", logger="elke27_lib.kernel")
    await kernel.close()


def test_start_stop_keepalive(monkeypatch: pytest.MonkeyPatch) -> None:
    kernel = E27Kernel()
    kernel._loop = None
    kernel._start_keepalive()

    class _Task:
        def done(self) -> bool:
            return False

        def cancel(self) -> None:
            return None

    def _create_task(coro: Any) -> _Task:
        coro.close()
        return _Task()

    kernel._loop = SimpleNamespace(create_task=_create_task)
    kernel._keepalive_task = None
    kernel._start_keepalive()
    kernel._keepalive_task = _Task()
    kernel._start_keepalive()

    kernel._keepalive_task = None
    kernel._stop_keepalive()
    kernel._keepalive_task = _Task()
    kernel._stop_keepalive()


@pytest.mark.asyncio
async def test_keepalive_loop_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    kernel = E27Kernel()
    kernel._keepalive_enabled = True
    kernel._closing = True
    await kernel._keepalive_loop()

    kernel._closing = False
    kernel._keepalive_enabled = False
    await kernel._keepalive_loop()

    async def _sleep_cancel(_delay: float) -> None:
        raise asyncio.CancelledError()

    monkeypatch.setattr(kernel_mod.asyncio, "sleep", _sleep_cancel)
    kernel._keepalive_enabled = True
    kernel._last_exchange_at = kernel.now()
    await kernel._keepalive_loop()

    kernel._keepalive_interval_s = 0.0
    kernel._last_exchange_at = 0.0
    kernel._session = None
    await kernel._keepalive_loop()

    kernel._session = SimpleNamespace(state=SessionState.ACTIVE)
    kernel._request_state = kernel_mod._RequestState.IN_FLIGHT
    await kernel._keepalive_loop()

    kernel._request_state = kernel_mod._RequestState.IDLE
    kernel._session = SimpleNamespace(
        state=SessionState.ACTIVE, _outbound=SimpleNamespace(is_idle=lambda: False)
    )
    await kernel._keepalive_loop()

    kernel._session = SimpleNamespace(state=SessionState.ACTIVE)
    kernel._keepalive_inflight = True
    await kernel._keepalive_loop()

    kernel._keepalive_inflight = False
    async def _send_keepalive() -> bool:
        kernel._closing = True
        return True

    monkeypatch.setattr(kernel, "_send_keepalive_request", _send_keepalive)
    kernel._closing = False
    await kernel._keepalive_loop()


@pytest.mark.asyncio
async def test_keepalive_loop_sleep_cancellations(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _sleep_cancel(_delay: float) -> None:
        raise asyncio.CancelledError()

    monkeypatch.setattr(kernel_mod.asyncio, "sleep", _sleep_cancel)

    kernel = E27Kernel()
    kernel._keepalive_enabled = True
    kernel._last_exchange_at = kernel.now()
    kernel._keepalive_interval_s = 100.0
    await kernel._keepalive_loop()

    kernel._keepalive_interval_s = 0.0
    kernel._last_exchange_at = 0.0
    kernel._session = None
    await kernel._keepalive_loop()

    kernel._session = SimpleNamespace(state=SessionState.ACTIVE)
    kernel._request_state = kernel_mod._RequestState.IN_FLIGHT
    await kernel._keepalive_loop()

    kernel._request_state = kernel_mod._RequestState.IDLE
    kernel._session = SimpleNamespace(
        state=SessionState.ACTIVE, _outbound=SimpleNamespace(is_idle=lambda: False)
    )
    await kernel._keepalive_loop()

    kernel._session = SimpleNamespace(state=SessionState.ACTIVE)
    kernel._keepalive_inflight = True
    await kernel._keepalive_loop()


@pytest.mark.asyncio
async def test_keepalive_loop_wait_cancel_line_659(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _sleep_cancel(_delay: float) -> None:
        raise asyncio.CancelledError()

    monkeypatch.setattr(kernel_mod.asyncio, "sleep", _sleep_cancel)
    kernel = E27Kernel()
    kernel._keepalive_enabled = True
    kernel._last_exchange_at = kernel.now()
    kernel._keepalive_interval_s = 100.0
    await kernel._keepalive_loop()


@pytest.mark.asyncio
async def test_keepalive_loop_session_cancel_line_666(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _sleep_cancel(_delay: float) -> None:
        raise asyncio.CancelledError()

    monkeypatch.setattr(kernel_mod.asyncio, "sleep", _sleep_cancel)
    kernel = E27Kernel()
    kernel._keepalive_enabled = True
    kernel._keepalive_interval_s = 0.0
    kernel._last_exchange_at = 0.0
    kernel._session = None
    await kernel._keepalive_loop()


@pytest.mark.asyncio
async def test_keepalive_loop_request_cancel_line_676(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _sleep_cancel(_delay: float) -> None:
        raise asyncio.CancelledError()

    monkeypatch.setattr(kernel_mod.asyncio, "sleep", _sleep_cancel)
    kernel = E27Kernel()
    kernel._keepalive_enabled = True
    kernel._keepalive_interval_s = 0.0
    kernel._last_exchange_at = 0.0
    kernel._session = SimpleNamespace(state=SessionState.ACTIVE)
    kernel._request_state = kernel_mod._RequestState.IN_FLIGHT
    await kernel._keepalive_loop()


@pytest.mark.asyncio
async def test_keepalive_loop_outbound_cancel_line_683(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _sleep_cancel(_delay: float) -> None:
        raise asyncio.CancelledError()

    monkeypatch.setattr(kernel_mod.asyncio, "sleep", _sleep_cancel)
    kernel = E27Kernel()
    kernel._keepalive_enabled = True
    kernel._keepalive_interval_s = 0.0
    kernel._last_exchange_at = 0.0
    kernel._session = SimpleNamespace(
        state=SessionState.ACTIVE, _outbound=SimpleNamespace(is_idle=lambda: False)
    )
    await kernel._keepalive_loop()


@pytest.mark.asyncio
async def test_keepalive_loop_inflight_cancel_line_689(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _sleep_cancel(_delay: float) -> None:
        raise asyncio.CancelledError()

    monkeypatch.setattr(kernel_mod.asyncio, "sleep", _sleep_cancel)
    kernel = E27Kernel()
    kernel._keepalive_enabled = True
    kernel._keepalive_interval_s = 0.0
    kernel._last_exchange_at = 0.0
    kernel._session = SimpleNamespace(state=SessionState.ACTIVE)
    kernel._keepalive_inflight = True
    await kernel._keepalive_loop()


@pytest.mark.asyncio
async def test_keepalive_loop_continue_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    kernel = E27Kernel()
    kernel._keepalive_enabled = True

    async def _sleep_noop(_delay: float) -> None:
        kernel._closing = True

    monkeypatch.setattr(kernel_mod.asyncio, "sleep", _sleep_noop)

    kernel._closing = False
    kernel._last_exchange_at = kernel.now()
    kernel._keepalive_interval_s = 100.0
    await kernel._keepalive_loop()

    kernel._closing = False
    kernel._keepalive_interval_s = 0.0
    kernel._last_exchange_at = 0.0
    kernel._session = None
    await kernel._keepalive_loop()

    kernel._closing = False
    kernel._session = SimpleNamespace(state=SessionState.ACTIVE)
    kernel._request_state = kernel_mod._RequestState.IN_FLIGHT
    await kernel._keepalive_loop()

    kernel._closing = False
    kernel._request_state = kernel_mod._RequestState.IDLE
    kernel._session = SimpleNamespace(
        state=SessionState.ACTIVE, _outbound=SimpleNamespace(is_idle=lambda: False)
    )
    await kernel._keepalive_loop()

    kernel._closing = False
    kernel._session = SimpleNamespace(state=SessionState.ACTIVE)
    kernel._keepalive_inflight = True
    await kernel._keepalive_loop()


@pytest.mark.asyncio
async def test_send_keepalive_request_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    kernel = E27Kernel()
    monkeypatch.setattr(kernel, "_set_loop_if_needed", lambda: None)
    assert await kernel._send_keepalive_request() is False

    kernel._loop = asyncio.get_running_loop()
    kernel._session = SimpleNamespace(state=SessionState.ACTIVE)
    kernel._last_exchange_at = kernel.now()
    kernel._keepalive_interval_s = 10.0
    assert await kernel._send_keepalive_request() is True

    kernel._keepalive_inflight = True
    kernel._last_exchange_at = 0.0
    kernel._keepalive_interval_s = 0.0
    assert await kernel._send_keepalive_request() is True
    kernel._keepalive_inflight = False

    kernel.requests.register(("system", "r_u_alive"), lambda: {})

    def _send_raise(*_a: Any, **_k: Any) -> int:
        raise RuntimeError("boom")

    monkeypatch.setattr(kernel, "_send_request_with_seq", _send_raise)
    kernel._last_exchange_at = 0.0
    kernel._keepalive_interval_s = 0.0
    assert await kernel._send_keepalive_request() is False

    def _send_timeout(seq: int, *_a: Any, **_k: Any) -> int:
        kernel._signal_sent_event(seq)
        kernel._pending_responses.fail(seq, E27Timeout("t"))
        return seq

    monkeypatch.setattr(kernel, "_send_request_with_seq", _send_timeout)
    assert await kernel._send_keepalive_request() in {True, False}

    def _send_fail(seq: int, *_a: Any, **_k: Any) -> int:
        kernel._signal_sent_event(seq)
        kernel._pending_responses.fail(seq, RuntimeError("boom"))
        return seq

    monkeypatch.setattr(kernel, "_send_request_with_seq", _send_fail)
    assert await kernel._send_keepalive_request() in {True, False}


def test_load_features_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    kernel = E27Kernel()
    called = {"load": 0}

    def _fake_blocking(mods: Any) -> None:
        called["load"] += 1

    monkeypatch.setattr(kernel, "load_features_blocking", _fake_blocking)
    kernel.load_features(["x"])
    assert called["load"] == 1

    fake_mod = types.ModuleType("fake")
    monkeypatch.setattr(kernel_mod.importlib, "import_module", lambda name: fake_mod)
    kernel2 = E27Kernel()
    with pytest.raises(RuntimeError):
        kernel2.load_features_blocking(["fake"])


def test_bootstrap_requests_and_csm_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    kernel = E27Kernel()
    kernel._bootstrap_requests()

    kernel._session = SimpleNamespace(state=SessionState.ACTIVE)
    monkeypatch.setattr(kernel.requests, "get", lambda *_a, **_k: True)
    monkeypatch.setattr(kernel, "request", lambda *_a, **_k: (_ for _ in ()).throw(E27Error("x")))
    kernel._bootstrap_requests()

    kernel._session = None
    with pytest.raises(KernelError):
        kernel.request_csm_refresh()

    kernel._session = SimpleNamespace(state=SessionState.ACTIVE)
    monkeypatch.setattr(
        kernel.requests,
        "get",
        lambda route: True if route == ("control", "authenticate") else None,
    )
    monkeypatch.setattr(kernel, "request", lambda *_a, **_k: (_ for _ in ()).throw(E27Error("x")))
    kernel.request_csm_refresh(auth_pin=1234, domains=["area"])

    monkeypatch.setattr(kernel.requests, "get", lambda *_a, **_k: True)
    kernel.request_csm_refresh(auth_pin=1234, domains=["area"])


def test_on_message_paths(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    kernel = E27Kernel()
    kernel._request_state = kernel_mod._RequestState.IN_FLIGHT
    kernel._active_seq = 99
    caplog.set_level("DEBUG", logger="elke27_lib.kernel")
    kernel._on_message(types.MappingProxyType({"authenticate": {"seq": 1, "session_id": 2}}))
    kernel._on_message(types.MappingProxyType({"seq": "x", "authenticate": {"seq": 2, "session_id": 3}}))
    assert kernel.state.panel.session_id == 3

    kernel._on_message({"seq": 1, "session_id": 2})


def test_on_idle_and_disconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    kernel = E27Kernel()
    called = {"try": 0, "abort": 0, "paged": 0}
    monkeypatch.setattr(kernel, "_try_send_next", lambda: called.__setitem__("try", 1))
    kernel._on_idle()
    assert called["try"] == 1

    kernel._closing = True
    kernel._on_session_disconnected(RuntimeError("x"))

    kernel._closing = False
    kernel._closed_explicitly = True
    kernel._on_session_disconnected(SessionIOError("x"))

    kernel._closed_explicitly = False
    monkeypatch.setattr(kernel, "_abort_requests", lambda *_a, **_k: called.__setitem__("abort", 1))
    monkeypatch.setattr(
        kernel.dispatcher, "abort_paged_transfers", lambda *_a, **_k: called.__setitem__("paged", 1)
    )
    kernel._on_session_disconnected(SessionProtocolError("x"))
    assert called["abort"] == 1
    assert called["paged"] == 1


def test_is_valid_attrib_id() -> None:
    kernel = E27Kernel()
    assert kernel._is_valid_attrib_id("area", 0) is False
    inv = kernel.state.inventory
    inv.area_discovery_max_id = 1
    assert kernel._is_valid_attrib_id("area", 2) is False
    inv.configured_areas = {1}
    assert kernel._is_valid_attrib_id("area", 2) is False
    inv.zone_discovery_max_id = 1
    assert kernel._is_valid_attrib_id("zone", 2) is False
    inv.zone_discovery_max_id = None
    inv.configured_zones = {1}
    assert kernel._is_valid_attrib_id("zone", 2) is False
    inv.configured_outputs = {1}
    assert kernel._is_valid_attrib_id("output", 2) is False
    inv.configured_users = {1}
    assert kernel._is_valid_attrib_id("user", 2) is False
    inv.configured_keypads = {1}
    assert kernel._is_valid_attrib_id("keypad", 2) is False
    kernel.state.table_info_by_domain["area"] = {"table_elements": 1}
    inv.area_discovery_max_id = None
    inv.configured_areas = set()
    assert kernel._is_valid_attrib_id("area", 2) is False


def test_signal_sent_event_exception_path() -> None:
    kernel = E27Kernel()

    class _Event:
        def __init__(self) -> None:
            self._loop = None
            self.calls = 0

        def set(self) -> None:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("boom")

    event = _Event()
    with kernel._sent_event_lock:
        kernel._sent_events[1] = event  # type: ignore[assignment]
    kernel._signal_sent_event(1)


def test_enqueue_kick_and_try_send_next(monkeypatch: pytest.MonkeyPatch) -> None:
    kernel = E27Kernel()
    item = kernel_mod._QueuedRequest(
        seq=1,
        domain="test",
        name="cmd",
        payload={},
        pending=True,
        opaque=None,
        expected_route=None,
        priority=OutboundPriority.HIGH,
        timeout_s=1.0,
    )
    called = {"try": 0}
    monkeypatch.setattr(kernel, "_try_send_next", lambda: called.__setitem__("try", 1))
    kernel._enqueue_request(item)
    assert kernel._request_queue_high

    kernel._loop = SimpleNamespace(is_running=lambda: False)
    kernel._kick_scheduler()
    assert called["try"] == 1

    class _Loop:
        def is_running(self) -> bool:
            return True

        def call_soon_threadsafe(self, fn: Any) -> None:
            fn()

    kernel._loop = _Loop()
    kernel._kick_scheduler()

    kernel._request_state = kernel_mod._RequestState.IN_FLIGHT
    kernel._try_send_next()
    kernel._request_state = kernel_mod._RequestState.IDLE
    kernel._request_queue_high.clear()
    kernel._request_queue_normal.clear()
    kernel._try_send_next()
    kernel._session = None
    kernel._request_queue_high.append(item)
    kernel._try_send_next()
    kernel._session = SimpleNamespace(state=SessionState.DISCONNECTED)
    kernel._request_queue_high.append(item)
    kernel._try_send_next()


def test_try_send_next_session_not_active() -> None:
    kernel = E27Kernel()
    kernel._request_state = kernel_mod._RequestState.IDLE
    item = kernel_mod._QueuedRequest(
        seq=1,
        domain="test",
        name="cmd",
        payload={},
        pending=True,
        opaque=None,
        expected_route=None,
        priority=OutboundPriority.NORMAL,
        timeout_s=1.0,
    )
    kernel._request_queue_high.append(item)
    kernel._session = SimpleNamespace(state=SessionState.DISCONNECTED)
    kernel._try_send_next()


def test_try_send_next_paged_and_send_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    kernel = E27Kernel()
    kernel._session = SimpleNamespace(state=SessionState.ACTIVE, send_json=lambda *_a, **_k: None)
    kernel.dispatcher.is_paged = lambda *_a, **_k: True  # type: ignore[assignment]
    kernel.dispatcher.add_pending = lambda *_a, **_k: None  # type: ignore[assignment]
    kernel.state.panel.session_id = 1

    item = kernel_mod._QueuedRequest(
        seq=1,
        domain="zone",
        name="get_configured",
        payload={"block_id": 1},
        pending=True,
        opaque=None,
        expected_route=("zone", "get_configured"),
        priority=OutboundPriority.NORMAL,
        timeout_s=1.0,
    )
    kernel._request_queue_high.append(item)

    def _send_json(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("boom")

    kernel._session.send_json = _send_json  # type: ignore[assignment]
    kernel._log.setLevel("DEBUG")
    kernel._try_send_next()


def test_reply_timeout_and_abort(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    kernel = E27Kernel()
    kernel._request_state = kernel_mod._RequestState.IN_FLIGHT
    kernel._active_seq = 1
    kernel._active_request = None
    caplog.set_level("WARNING", logger="elke27_lib.kernel")
    kernel._on_reply_timeout(1)

    kernel._active_request = kernel_mod._QueuedRequest(
        seq=1,
        domain="zone",
        name="get_status",
        payload={},
        pending=True,
        opaque=None,
        expected_route=("zone", "get_status"),
        priority=OutboundPriority.NORMAL,
        timeout_s=1.0,
    )
    kernel.dispatcher.drop_pending = lambda *_a, **_k: None  # type: ignore[assignment]
    kernel._pending_responses.fail = lambda *_a, **_k: None  # type: ignore[assignment]
    kernel._on_reply_timeout(1)

    kernel._active_seq = 2
    kernel._request_state = kernel_mod._RequestState.IN_FLIGHT
    kernel._active_released = False
    kernel._handle_send_failure(1, RuntimeError("boom"))

    kernel._request_state = kernel_mod._RequestState.IN_FLIGHT
    kernel._active_seq = 3
    kernel._active_released = False
    kernel._request_queue_high.append(
        kernel_mod._QueuedRequest(
            seq=4,
            domain="zone",
            name="get_status",
            payload={},
            pending=True,
            opaque=None,
            expected_route=("zone", "get_status"),
            priority=OutboundPriority.NORMAL,
            timeout_s=1.0,
        )
    )
    kernel._abort_requests(ConnectionLost("x"))

    kernel._active_released = True
    kernel._complete_active(reason="noop")


def test_mark_send_failed_request_and_next_seq(monkeypatch: pytest.MonkeyPatch) -> None:
    kernel = E27Kernel()
    kernel._pending_responses.fail = lambda *_a, **_k: None  # type: ignore[assignment]
    kernel.dispatcher.drop_pending = lambda *_a, **_k: None  # type: ignore[assignment]
    kernel._mark_send_failed(1, RuntimeError("x"))

    kernel.requests.require = lambda *_a, **_k: (lambda **_kw: {"ok": True})  # type: ignore[assignment]
    monkeypatch.setattr(kernel, "_send_request", lambda *_a, **_k: 5)
    assert kernel.request(("zone", "get_status")) == 5

    kernel._seq = 0
    assert kernel._next_seq() == 10

    kernel._active_timeout_handle = SimpleNamespace(cancel=lambda: None)
    kernel._loop = SimpleNamespace(call_later=lambda *_a, **_k: None)
    kernel._arm_reply_timeout(1, 0)
    kernel._arm_reply_timeout(1, 1)
    kernel._request_state = kernel_mod._RequestState.IN_FLIGHT
    kernel._active_seq = 1
    kernel._active_released = True
    kernel._on_reply_timeout(1)


def test_send_request_with_seq_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    kernel = E27Kernel()
    with pytest.raises(KernelError):
        kernel._send_request_with_seq(1, "zone", "get_status", {}, pending=True, opaque=None, expected_route=None)

    kernel._session = SimpleNamespace(state=SessionState.DISCONNECTED)
    with pytest.raises(KernelError):
        kernel._send_request_with_seq(1, "zone", "get_status", {}, pending=True, opaque=None, expected_route=None)

    def _send_json(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("boom")

    kernel._session = SimpleNamespace(state=SessionState.ACTIVE, send_json=_send_json)
    with pytest.raises(KernelError):
        kernel._send_request_with_seq(
            1,
            "zone",
            "get_status",
            {"x": 1},
            pending=False,
            opaque=None,
            expected_route=None,
            expects_reply=False,
        )

    kernel._session = SimpleNamespace(state=SessionState.ACTIVE, send_json=lambda *_a, **_k: None)
    assert (
        kernel._send_request_with_seq(
            2,
            "zone",
            "get_status",
            {"x": 1},
            pending=False,
            opaque=None,
            expected_route=None,
            expects_reply=False,
        )
        == 2
    )

    monkeypatch.setattr(kernel, "_send_request_with_seq", lambda *_a, **_k: 7)
    assert kernel._send_request("zone", "get_status", {"x": 1}, pending=False, opaque=None, expected_route=None) == 7


def test_build_request_and_emit_and_envelopes(caplog: pytest.LogCaptureFixture) -> None:
    kernel = E27Kernel()
    msg = kernel._build_request_message(1, "zone", "get_status", "payload")
    assert msg["zone"]["get_status"] == "payload"

    kernel._log_outbound("control", "r_u_alive", msg)

    token = kernel.subscribe(lambda *_a, **_k: None, kinds={"other"})
    kernel.emit(
        ConnectionStateChanged(
            kind=ConnectionStateChanged.KIND,
            at=0.0,
            seq=None,
            classification="LOCAL",
            route=("__local__", "connection_state"),
            session_id=None,
            connected=True,
        ),
        ctx=kernel_mod.DispatchContext(
            kind=kernel_mod.MessageKind.UNKNOWN,
            seq=None,
            session_id=None,
            route=("__local__", "connection_state"),
            classification="LOCAL",
            response_match=None,
            raw_route=None,
        ),
    )
    kernel.unsubscribe(token)

    token = kernel.subscribe(lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")))
    caplog.set_level("WARNING", logger="elke27_lib.kernel")
    kernel.emit(
        ConnectionStateChanged(
            kind=ConnectionStateChanged.KIND,
            at=0.0,
            seq=None,
            classification="LOCAL",
            route=("__local__", "connection_state"),
            session_id=None,
            connected=True,
        ),
        ctx=kernel_mod.DispatchContext(
            kind=kernel_mod.MessageKind.UNKNOWN,
            seq=None,
            session_id=None,
            route=("__local__", "connection_state"),
            classification="LOCAL",
            response_match=None,
            raw_route=None,
        ),
    )
    kernel.unsubscribe(token)

    assert kernel._handle_dispatch_error_envelope({}, kernel_mod.DispatchContext(
        kind=kernel_mod.MessageKind.UNKNOWN,
        seq=None,
        session_id=None,
        route=("__local__", "connection_state"),
        classification="LOCAL",
        response_match=None,
        raw_route=None,
    )) is False
    assert kernel._handle_dispatch_error_envelope({"__error__": {"x": "y"}}, kernel_mod.DispatchContext(
        kind=kernel_mod.MessageKind.UNKNOWN,
        seq=None,
        session_id=None,
        route=("__local__", "connection_state"),
        classification="LOCAL",
        response_match=None,
        raw_route=None,
    )) is False

    assert kernel._handle_panel_error_envelope({"error_code": "x"}, kernel_mod.DispatchContext(
        kind=kernel_mod.MessageKind.UNKNOWN,
        seq=None,
        session_id=None,
        route=("__local__", "connection_state"),
        classification="LOCAL",
        response_match=None,
        raw_route=None,
    )) is False
    assert kernel._handle_panel_error_envelope({"error_code": "1", "error_message": 2}, kernel_mod.DispatchContext(
        kind=kernel_mod.MessageKind.UNKNOWN,
        seq=None,
        session_id=None,
        route=("__local__", "connection_state"),
        classification="LOCAL",
        response_match=None,
        raw_route=None,
    )) is True
