from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any, cast

import pytest

from elke27_lib import discovery, linking
from elke27_lib import kernel as kernel_mod
from elke27_lib import session as session_mod
from elke27_lib.errors import E27Error
from elke27_lib.kernel import (
    E27Kernel,
    KernelError,
    KernelInvalidPanelError,
    KernelMissingContextError,
    RequestRegistry,
)


class _FakeSocket:
    def __init__(self) -> None:
        self.timeout: float | None = None
        self.connected = False
        self.closed = False

    def settimeout(self, value: float) -> None:
        self.timeout = value

    def connect(self, _addr) -> None:
        self.connected = True

    def close(self) -> None:
        self.closed = True


class _FakeSession:
    def __init__(self, cfg, client_identity, link_key_hex) -> None:  # type: ignore[no-untyped-def]
        self.cfg = cfg
        self.client_identity = client_identity
        self.link_key_hex = link_key_hex
        self.state = session_mod.SessionState.ACTIVE
        self.info = session_mod.SessionInfo(
            session_id=11, session_key_hex="00", session_hmac_hex="11"
        )
        self.on_message = None
        self.on_disconnected = None
        self.on_idle = None
        self.outbound_enabled = False
        self.auto_started = False
        self.sent: list[dict[str, object]] = []
        self._outbound = None
        self.disconnected: Exception | None = None

    def connect(self) -> session_mod.SessionInfo:
        return self.info

    def enable_outbound_queue(self, **_kwargs) -> None:  # type: ignore[no-untyped-def]
        self.outbound_enabled = True

    def start_auto_receive(self) -> None:
        self.auto_started = True

    def close(self) -> None:
        return None

    def send_json(self, msg, *, priority, on_sent, on_fail):  # type: ignore[no-untyped-def]
        _ = priority, on_fail
        self.sent.append(msg)
        if on_sent is not None:
            on_sent(0.0)

    def handle_disconnect(self, err: Exception) -> None:
        self.disconnected = err


def _identity() -> linking.E27Identity:
    return linking.E27Identity("mn", "sn", "fw", "hw", "os")


def test_request_registry_require_and_get() -> None:
    registry = RequestRegistry()
    with pytest.raises(KeyError):
        registry.require(("zone", "get"))

    registry.register(("zone", "get"), lambda: {"ok": True})
    assert registry.get(("zone", "get")) is not None
    assert registry.require(("zone", "get"))() == {"ok": True}


def test_redact_value(monkeypatch: pytest.MonkeyPatch) -> None:
    data = {"pin": "1234", "nested": {"passphrase": "x"}, "ok": 1}
    monkeypatch.setattr(kernel_mod, "REDACT_DIAGNOSTICS", True)
    redacted = kernel_mod._redact_value(data)
    assert redacted["pin"] == "***"
    assert redacted["nested"]["passphrase"] == "***"

    monkeypatch.setattr(kernel_mod, "REDACT_DIAGNOSTICS", False)
    assert kernel_mod._redact_value(data) is data


def test_panel_host_port_variants() -> None:
    panel = discovery.E27System(
        panel_mac="m",
        panel_host="host",
        panel_name="n",
        panel_serial=None,
        port=2101,
        tls_port=2102,
    )
    assert kernel_mod._panel_host_port(panel) == ("host", 2101)
    assert kernel_mod._panel_host_port({"ip": "1.2.3.4", "port": 123}) == ("1.2.3.4", 123)
    with pytest.raises(KernelInvalidPanelError):
        kernel_mod._panel_host_port({"port": 1})
    with pytest.raises(KernelInvalidPanelError):
        kernel_mod._panel_host_port({"host": "x", "port": 70000})


@pytest.mark.asyncio
async def test_discover_variants(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Scanner:
        async def async_scan(self, **_k):  # type: ignore[no-untyped-def]
            return [
                discovery.E27System(
                    panel_mac="m",
                    panel_host="host",
                    panel_name="n",
                    panel_serial=None,
                    port=2101,
                    tls_port=2102,
                )
            ]

    monkeypatch.setattr(discovery, "AIOELKDiscovery", _Scanner)
    result = await E27Kernel.discover()
    assert result.panels and isinstance(result.panels[0], discovery.E27System)

    class _ScannerNone:
        async def async_scan(self, **_k):  # type: ignore[no-untyped-def]
            return None

    monkeypatch.setattr(discovery, "AIOELKDiscovery", _ScannerNone)
    result = await E27Kernel.discover()
    assert result.panels == []

    class _ScannerBad:
        async def async_scan(self, **_k):  # type: ignore[no-untyped-def]
            return "bad"

    monkeypatch.setattr(discovery, "AIOELKDiscovery", _ScannerBad)
    with pytest.raises(KernelError):
        await E27Kernel.discover()


@pytest.mark.asyncio
async def test_link_validation_and_success(monkeypatch: pytest.MonkeyPatch) -> None:
    kernel = E27Kernel()

    class _Creds:
        access_code = "1234"
        passphrase = "abcd"

    panel = {"host": "1.2.3.4", "port": 2101}
    monkeypatch.setattr(kernel_mod.socket, "socket", lambda *_a, **_k: _FakeSocket())
    monkeypatch.setattr(linking, "wait_for_discovery_nonce", lambda *_a, **_k: "nonce")
    monkeypatch.setattr(
        linking,
        "perform_api_link",
        lambda **_k: linking.E27LinkKeys("aa", "bb", "cc"),
    )

    async def _to_thread(fn, *a, **k):  # type: ignore[no-untyped-def]
        return fn(*a, **k)

    monkeypatch.setattr(asyncio, "to_thread", _to_thread)

    keys = await kernel.link(panel, _identity(), _Creds(), timeout_s=0.01)
    assert keys.linkkey_hex == "bb"

    with pytest.raises(KernelError):
        await kernel.link(panel, _identity(), None, timeout_s=0.01)

    class _BadCreds:
        access_code = ""
        passphrase = "x"

    with pytest.raises(KernelError):
        await kernel.link(panel, _identity(), _BadCreds(), timeout_s=0.01)

    class _BadCreds2:
        access_code = "1"
        passphrase = ""

    with pytest.raises(KernelError):
        await kernel.link(panel, _identity(), _BadCreds2(), timeout_s=0.01)

    monkeypatch.setattr(
        linking, "perform_api_link", lambda **_k: (_ for _ in ()).throw(E27Error("no"))
    )
    with pytest.raises(KernelError):
        await kernel.link(panel, _identity(), _Creds(), timeout_s=0.01)


@pytest.mark.asyncio
async def test_connect_validations(monkeypatch: pytest.MonkeyPatch) -> None:
    kernel = E27Kernel()
    with pytest.raises(KernelMissingContextError):
        await kernel.connect(linking.E27LinkKeys("a", "b", "c"))
    with pytest.raises(KernelMissingContextError):
        await kernel.connect(linking.E27LinkKeys("a", "b", "c"), panel={"host": "h"})

    with pytest.raises(KernelError):
        await kernel.connect(
            linking.E27LinkKeys("", "", ""),
            panel={"host": "h", "port": 1},
            client_identity=_identity(),
        )


@pytest.mark.asyncio
async def test_connect_success_and_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    kernel = E27Kernel()
    monkeypatch.setattr(kernel, "load_features_blocking", lambda _modules=None: None)

    async def _to_thread(fn, *a, **k):  # type: ignore[no-untyped-def]
        return fn(*a, **k)

    monkeypatch.setattr(asyncio, "to_thread", _to_thread)

    class _Session(_FakeSession):
        def connect(self) -> session_mod.SessionInfo:  # type: ignore[override]
            raise RuntimeError("boom")

    monkeypatch.setattr(session_mod, "Session", _Session)
    with pytest.raises(KernelError):
        await kernel.connect(
            linking.E27LinkKeys("aa", "bb", "cc"),
            panel={"host": "h", "port": 1},
            client_identity=_identity(),
        )

    class _SessionInactive(_FakeSession):
        def __init__(self, cfg, client_identity, link_key_hex) -> None:  # type: ignore[no-untyped-def]
            super().__init__(cfg, client_identity, link_key_hex)
            self.state = session_mod.SessionState.HELLO

    monkeypatch.setattr(session_mod, "Session", _SessionInactive)
    with pytest.raises(KernelError):
        await kernel.connect(
            linking.E27LinkKeys("aa", "bb", "cc"),
            panel={"host": "h", "port": 1},
            client_identity=_identity(),
        )

    class _SessionOk(_FakeSession):
        pass

    monkeypatch.setattr(session_mod, "Session", _SessionOk)
    started: dict[str, int] = {"count": 0}
    monkeypatch.setattr(
        kernel, "_start_keepalive", lambda: started.__setitem__("count", started["count"] + 1)
    )

    cfg = session_mod.SessionConfig(host="h", port=1, keepalive_enabled=True)
    state = await kernel.connect(
        linking.E27LinkKeys("aa", "bb", "cc"),
        session_config=cfg,
        client_identity=_identity(),
    )
    assert state is session_mod.SessionState.ACTIVE
    assert kernel.state.panel.connected is True
    assert started["count"] == 1


@pytest.mark.asyncio
async def test_reconnect_and_close(monkeypatch: pytest.MonkeyPatch) -> None:
    kernel = E27Kernel()
    with pytest.raises(KernelError):
        await kernel.reconnect()

    kernel._last_link_keys = linking.E27LinkKeys("aa", "bb", "cc")
    kernel._last_client_identity = _identity()
    kernel._last_session_config = session_mod.SessionConfig(host="h", port=1)

    called: dict[str, int] = {"close": 0, "connect": 0}

    async def _close():  # type: ignore[no-untyped-def]
        called["close"] += 1

    monkeypatch.setattr(kernel, "close", _close)

    async def _connect(*_a, **_k):  # type: ignore[no-untyped-def]
        called["connect"] += 1
        return session_mod.SessionState.ACTIVE

    monkeypatch.setattr(kernel, "connect", _connect)
    await kernel.reconnect()
    assert called["close"] == 1
    assert called["connect"] == 1

    kernel2 = E27Kernel()
    fake = _FakeSession(session_mod.SessionConfig(host="h"), _identity(), "aa")
    cast(Any, kernel2)._session = fake
    called = {"emit": 0}
    monkeypatch.setattr(
        kernel2,
        "_emit_connection_state",
        lambda **_k: called.__setitem__("emit", called["emit"] + 1),
    )
    await kernel2.close()
    assert called["emit"] == 1


@pytest.mark.asyncio
async def test_keepalive_loop_disconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    kernel = E27Kernel(now_monotonic=lambda: 10.0)
    kernel._keepalive_enabled = True
    kernel._keepalive_interval_s = 0.0
    kernel._keepalive_max_missed = 1
    session = _FakeSession(session_mod.SessionConfig(host="h"), _identity(), "aa")
    cast(Any, session)._outbound = SimpleNamespace(is_idle=lambda: True)
    cast(Any, kernel)._session = session
    monkeypatch.setattr(kernel, "_send_keepalive_request", lambda: asyncio.sleep(0, result=False))
    await kernel._keepalive_loop()
    assert session.disconnected is not None


@pytest.mark.asyncio
async def test_send_keepalive_request_success(monkeypatch: pytest.MonkeyPatch) -> None:
    kernel = E27Kernel(now_monotonic=lambda: 100.0)
    cast(Any, kernel)._loop = asyncio.get_running_loop()
    cast(Any, kernel)._session = _FakeSession(
        session_mod.SessionConfig(host="h"), _identity(), "aa"
    )
    kernel._last_exchange_at = 0.0
    kernel.requests.register(("system", "r_u_alive"), lambda: {})

    future: asyncio.Future[object] = cast(asyncio.AbstractEventLoop, kernel._loop).create_future()
    future.set_result({"ok": True})
    monkeypatch.setattr(kernel._pending_responses, "create", lambda *a, **k: future)
    monkeypatch.setattr(kernel, "_register_sent_event", lambda _seq, event: (event.set(), event)[1])
    monkeypatch.setattr(kernel, "_send_request_with_seq", lambda *a, **k: None)

    assert await kernel._send_keepalive_request() is True


@pytest.mark.asyncio
async def test_keepalive_request_failure_when_no_loop() -> None:
    kernel = E27Kernel()
    assert await kernel._send_keepalive_request() is False


def test_build_request_message_and_log(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    kernel = E27Kernel()
    kernel.state.panel.session_id = 7
    msg = kernel._build_request_message(5, "zone", "get", {"x": 1})
    assert msg["session_id"] == 7
    msg = kernel._build_request_message(5, "zone", "__root__", {"x": 1})
    assert msg["zone"]["x"] == 1

    caplog.set_level(logging.DEBUG, logger="elke27_lib.kernel")
    monkeypatch.setattr(kernel_mod, "REDACT_DIAGNOSTICS", True)
    kernel._log_outbound("zone", "get_attribs", {"seq": 1, "pin": "123"})
    assert "Outbound request" in caplog.text


def test_emit_and_drain(monkeypatch: pytest.MonkeyPatch) -> None:
    kernel = E27Kernel()
    ctx = kernel_mod.DispatchContext(
        kind=kernel_mod.MessageKind.UNKNOWN,
        seq=1,
        session_id=2,
        route=("zone", "get"),
        classification="LOCAL",
        response_match=None,
        raw_route=None,
    )
    evt = kernel_mod.ConnectionStateChanged(
        kind=kernel_mod.ConnectionStateChanged.KIND,
        at=kernel_mod.UNSET_AT,
        seq=kernel_mod.UNSET_SEQ,
        classification=kernel_mod.UNSET_CLASSIFICATION,
        route=kernel_mod.UNSET_ROUTE,
        session_id=kernel_mod.UNSET_SESSION_ID,
        connected=True,
        reason=None,
        error_type=None,
    )
    called: dict[str, int] = {"count": 0}
    kernel.subscribe(lambda _e: called.__setitem__("count", called["count"] + 1))
    kernel.emit(evt, ctx=ctx)
    assert kernel.drain_events()
    assert called["count"] == 1


def test_dispatch_error_envelopes() -> None:
    kernel = E27Kernel()
    ctx = kernel_mod.DispatchContext(
        kind=kernel_mod.MessageKind.UNKNOWN,
        seq=None,
        session_id=None,
        route=("__error__", "__all__"),
        classification="LOCAL",
        response_match=None,
        raw_route=None,
    )
    msg = {"__error__": {"ERR": {"message": "bad", "keys": ["a"], "payload": "p"}}}
    assert kernel._handle_dispatch_error_envelope(msg, ctx) is True

    ctx = kernel_mod.DispatchContext(
        kind=kernel_mod.MessageKind.UNKNOWN,
        seq=None,
        session_id=None,
        route=("__error__", "panel_error"),
        classification="LOCAL",
        response_match=None,
        raw_route=None,
    )
    assert kernel._handle_panel_error_envelope({"error_code": 11008}, ctx) is True
    assert (
        kernel._handle_panel_error_envelope({"error_code": 5, "error_message": "oops"}, ctx) is True
    )


def test_is_valid_attrib_id() -> None:
    kernel = E27Kernel()
    kernel.state.inventory.configured_areas = {1}
    kernel.state.table_info_by_domain["area"] = {"table_elements": 1}
    assert kernel._is_valid_attrib_id("area", 1) is True
    assert kernel._is_valid_attrib_id("area", 2) is False


def test_signal_sent_event_paths() -> None:
    kernel = E27Kernel()

    class _Loop:
        def __init__(self) -> None:
            self.called = False

        def is_running(self) -> bool:
            return True

        def call_soon_threadsafe(self, fn):  # type: ignore[no-untyped-def]
            self.called = True
            fn()

    event = asyncio.Event()
    event._loop = _Loop()  # type: ignore[attr-defined]
    kernel._register_sent_event(1, event)
    kernel._signal_sent_event(1)
    assert event.is_set()
