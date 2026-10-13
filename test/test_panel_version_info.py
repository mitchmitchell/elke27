"""E1: control.get_version_info after HELLO fills panel serial/mac/model/firmware."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, cast

import pytest

from elke27_lib.client import Elke27Client
from elke27_lib.handlers.control import make_control_get_version_info_handler
from elke27_lib.kernel import E27Kernel
from elke27_lib.states import PanelState
from elke27_lib.types import LinkKeys

_KEYS = LinkKeys("aa", "bb", "cc")


def _client_with_fake_connect(monkeypatch: pytest.MonkeyPatch) -> tuple[Elke27Client, list[Any]]:
    client = Elke27Client(kernel=E27Kernel())
    client._kernel.load_features_blocking(None)  # real kernel.connect loads these
    requests: list[Any] = []

    async def _connect(*_a: Any, **_k: Any) -> None:
        return None

    def _send(seq: int, domain: str, name: str, payload: Any, **kwargs: Any) -> int:
        requests.append(((domain, name), kwargs))
        return seq

    monkeypatch.setattr(client._kernel, "connect", _connect)
    monkeypatch.setattr(client._kernel, "send_request_with_seq", _send)
    return client, requests


@pytest.mark.asyncio
async def test_connect_requests_version_info(monkeypatch: pytest.MonkeyPatch) -> None:
    client, requests = _client_with_fake_connect(monkeypatch)
    await client.async_connect("h", 1, _KEYS)
    routes = [r for r, kw in requests if kw.get("expects_reply") is False]
    assert routes == [("control", "get_version_info")]  # no reply wait/retry/queue slot
    panel = client.snapshot.panel
    assert (panel.serial, panel.mac, panel.model, panel.firmware) == (None, None, None, None)


@pytest.mark.asyncio
async def test_version_info_request_failure_does_not_break_connect(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    client, _ = _client_with_fake_connect(monkeypatch)

    def _boom(*_a: Any, **_k: Any) -> int:
        raise RuntimeError("send failed")

    monkeypatch.setattr(client._kernel, "send_request_with_seq", _boom)
    with caplog.at_level(logging.DEBUG, logger=client._log.name):
        await client.async_connect("h", 1, _KEYS)
    assert cast(Any, client)._connected is True
    assert client.snapshot.panel.serial is None
    msgs = [r for r in caplog.records if "get_version_info" in r.getMessage()]
    assert msgs and all(r.levelno == logging.DEBUG for r in msgs)


def _run_handler(payload: dict[str, Any]) -> tuple[PanelState, list[Any]]:
    state = PanelState()
    emitted: list[Any] = []
    handler = make_control_get_version_info_handler(
        state, lambda evt, _ctx: emitted.append(evt), lambda: 0.0
    )
    handler({"control": {"get_version_info": payload}}, cast(Any, object()))
    return state, emitted


def test_version_info_fills_identity_fields() -> None:
    state, emitted = _run_handler(
        {"serial": "E27123456", "mac": "00:40:9D:AA:BB:CC", "model": "E27", "firmware": "1.2.3"}
    )
    assert state.panel.serial == "E27123456"
    assert state.panel.mac == "00:40:9D:AA:BB:CC"
    assert state.panel.model == "E27"
    assert state.panel.firmware == "1.2.3"
    assert any(set(getattr(e, "changed_fields", ())) >= {"serial", "mac"} for e in emitted)


def test_version_info_missing_fields_stay_none() -> None:
    state, _ = _run_handler({"error_code": 0})
    assert (state.panel.serial, state.panel.mac, state.panel.model, state.panel.firmware) == (
        None,
        None,
        None,
        None,
    )


def test_version_info_error_reply_leaves_identity_none() -> None:
    state, _ = _run_handler({"error_code": 11008})
    assert state.panel.serial is None and state.panel.mac is None


def test_snapshot_panel_info_exposes_mac() -> None:
    client = Elke27Client(kernel=E27Kernel())
    panel = client._kernel.state.panel
    panel.mac = "00:40:9D:AA:BB:CC"
    panel.serial = "E27123456"
    info = client._build_panel_info()
    assert info.mac == "00:40:9D:AA:BB:CC"
    assert info.serial == "E27123456"


@pytest.mark.asyncio
async def test_identity_cleared_when_connecting_to_a_different_panel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = _client_with_fake_connect(monkeypatch)
    await client.async_connect("panel-a", 2101, _KEYS)
    panel = client._kernel.state.panel
    panel.serial, panel.mac, panel.model, panel.firmware = "A1", "aa:aa", "E27", "1.0"
    client._replace_snapshot(panel_info=client._build_panel_info())
    assert client.snapshot.panel.serial == "A1"

    # Reconnect to the same panel keeps identity until a new reply arrives.
    await client.async_connect("panel-a", 2101, _KEYS)
    assert panel.serial == "A1"

    # A different panel must not inherit A's identity.
    await client.async_connect("panel-b", 2101, _KEYS)
    assert (panel.serial, panel.mac, panel.model, panel.firmware) == (None, None, None, None)
    snap = client.snapshot.panel
    assert (snap.serial, snap.mac, snap.model, snap.firmware) == (None, None, None, None)


# --- Hardware RC report 2026-10-13: placeholder serial, real field mapping ---

_HW_REPLY = {
    "sn": "00000001",
    "hw": 260,
    "boot": 536,
    "app": 1540,
    "SSP": "2.6.1",
    "BUILD_DATETIME": "2026/03/02,15:54:54",
    "schema": 1,
    "db1": "ELK 900 MHz",
    "db1ver": [1795, 65545, 66151],
    "error_code": 0,
}


def test_hardware_reply_maps_model_firmware_and_drops_placeholder_serial() -> None:
    state, emitted = _run_handler(dict(_HW_REPLY))
    assert state.panel.serial is None  # "00000001" is a factory placeholder
    assert state.panel.mac is None  # MAC only comes from UDP discovery
    assert state.panel.model == "260"
    assert state.panel.firmware == "2.6.1"
    changed = [e.changed_fields for e in emitted if hasattr(e, "changed_fields")]
    assert changed == [("firmware", "model")]


@pytest.mark.parametrize(
    "sn", ["", "  ", "0", "00000000", "00000001", "1", "0001", "FFFFFFFF", "ffff"]
)
def test_placeholder_serials_stay_none(sn: str) -> None:
    from elke27_lib.handlers.control import is_placeholder_serial

    assert is_placeholder_serial(sn)
    state, _ = _run_handler({"sn": sn, "error_code": 0})
    assert state.panel.serial is None


@pytest.mark.parametrize("sn", ["00000002", "1234ABCD", "A0000001", "10", "\u00b2", "9" * 5000])
def test_real_serials_are_kept(sn: str) -> None:
    state, _ = _run_handler({"sn": sn, "error_code": 0})
    assert state.panel.serial == sn


@pytest.mark.asyncio
async def test_version_info_request_registers_reply_correlation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, requests = _client_with_fake_connect(monkeypatch)
    await client.async_connect("h", 1, _KEYS)
    kw = next(kw for r, kw in requests if r == ("control", "get_version_info"))
    assert kw["pending"] is True
    assert kw["expected_route"] == ("control", "get_version_info")


def test_fire_and_forget_pending_reply_is_classified_response() -> None:
    from types import SimpleNamespace

    from elke27_lib.kernel import E27Kernel
    from elke27_lib.session import SessionState

    kernel = E27Kernel()
    cast(Any, kernel)._session = SimpleNamespace(
        state=SessionState.ACTIVE, send_json=lambda *_a, **_k: None
    )
    route = ("control", "get_version_info")
    kernel._send_request_with_seq(
        17, *route, {}, pending=True, opaque=None, expected_route=route, expects_reply=False
    )
    result = kernel.dispatcher.dispatch(
        {"seq": 17, "session_id": 1, "control": {"get_version_info": dict(_HW_REPLY)}}
    )
    assert result.classification == "RESPONSE"


def test_unicode_digit_serial_does_not_drop_reply() -> None:
    state, _ = _run_handler({"sn": "\u00b2", "hw": 260, "SSP": "2.6.1", "error_code": 0})
    assert state.panel.serial == "\u00b2"
    assert (state.panel.model, state.panel.firmware) == ("260", "2.6.1")


def test_fire_and_forget_correlation_is_dropped_on_close_and_connect() -> None:
    from types import SimpleNamespace

    from elke27_lib.kernel import E27Kernel
    from elke27_lib.session import SessionState

    kernel = E27Kernel()
    cast(Any, kernel)._session = SimpleNamespace(
        state=SessionState.ACTIVE, send_json=lambda *_a, **_k: None
    )
    route = ("control", "get_version_info")
    kernel._send_request_with_seq(
        17, *route, {}, pending=True, opaque=None, expected_route=route, expects_reply=False
    )
    assert kernel.dispatcher.pending_count() == 1
    cast(Any, kernel)._session = None
    asyncio.run(kernel.close())  # teardown (also runs at the start of every connect)
    assert kernel.dispatcher.pending_count() == 0
    # A later message reusing seq 17 is no longer read as our RESPONSE.
    result = kernel.dispatcher.dispatch(
        {"seq": 17, "session_id": 1, "control": {"get_version_info": dict(_HW_REPLY)}}
    )
    assert result.classification == "UNSOLICITED"


@pytest.mark.asyncio
async def test_connect_drops_stale_fire_and_forget_correlation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from elke27_lib.dispatcher import PendingRequest
    from elke27_lib.kernel import E27Kernel, KernelMissingContextError

    kernel = E27Kernel()
    kernel.dispatcher.add_pending(PendingRequest(seq=5))
    cast(Any, kernel)._fire_and_forget_pending_seqs.add(5)
    monkeypatch.setattr(kernel, "load_features_blocking", lambda *_a: None)
    with pytest.raises(KernelMissingContextError):
        await kernel.connect(cast(Any, None))  # fails after the cleanup step
    assert kernel.dispatcher.pending_count() == 0
