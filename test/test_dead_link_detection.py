"""Fast dead-link detection (HACS PR #42 hardware run, failure 1)."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any, cast

import pytest

import elke27_lib.kernel as kernel_mod
from elke27_lib.kernel import E27Kernel
from elke27_lib.session import Session, SessionConfig, SessionProtocolError, SessionState


def test_session_config_defaults_detect_quickly() -> None:
    cfg = SessionConfig(host="192.0.2.1")
    assert cfg.keepalive_timeout_s <= 5.0
    assert cfg.keepalive_max_missed == 1


class _FakeSession:
    def __init__(self) -> None:
        self.state = SessionState.ACTIVE
        self.disconnects: list[Exception | None] = []

    def handle_disconnect(self, err: Exception | None) -> None:
        self.disconnects.append(err)


@pytest.mark.asyncio
async def test_single_missed_keepalive_disconnects() -> None:
    kernel = E27Kernel()
    kernel._keepalive_enabled = True
    kernel._keepalive_interval_s = 30.0
    kernel._keepalive_max_missed = 1
    fake = _FakeSession()
    cast(Any, kernel)._session = fake
    now = kernel.now()
    kernel._last_rx_at = now - 31.0  # panel silent past the interval
    kernel._last_exchange_at = now  # we just sent something; must not postpone probe

    calls: list[bool] = []

    async def _probe(*, force: bool = False) -> bool:
        calls.append(force)
        return False

    cast(Any, kernel)._send_keepalive_request = _probe
    await kernel._keepalive_loop()
    assert calls == [False]
    assert len(fake.disconnects) == 1
    assert isinstance(fake.disconnects[0], SessionProtocolError)


@pytest.mark.asyncio
async def test_silent_reply_timeout_requests_link_check() -> None:
    kernel = E27Kernel()
    kernel._keepalive_enabled = True
    cast(Any, kernel)._session = _FakeSession()
    kernel._request_state = kernel_mod._RequestState.IN_FLIGHT
    kernel._active_seq = 115
    kernel._active_released = False
    kernel._active_request = cast(Any, SimpleNamespace(expected_route=("light", "set_status")))
    kernel._active_sent_at = kernel.now()
    kernel._last_rx_at = kernel._active_sent_at - 1.0
    kernel._on_reply_timeout(115)
    assert kernel._keepalive_probe_requested is True


@pytest.mark.asyncio
async def test_reply_timeout_with_inbound_traffic_does_not_probe() -> None:
    kernel = E27Kernel()
    kernel._keepalive_enabled = True
    cast(Any, kernel)._session = _FakeSession()
    kernel._request_state = kernel_mod._RequestState.IN_FLIGHT
    kernel._active_seq = 7
    kernel._active_released = False
    kernel._active_request = cast(Any, SimpleNamespace(expected_route=("light", "set_status")))
    kernel._active_sent_at = kernel.now() - 2.0
    kernel._last_rx_at = kernel.now()  # panel is talking; just this reply was lost
    kernel._on_reply_timeout(7)
    assert kernel._keepalive_probe_requested is False


@pytest.mark.asyncio
async def test_forced_probe_skips_wait_and_busy_queue() -> None:
    kernel = E27Kernel()
    kernel._keepalive_enabled = True
    fake = _FakeSession()
    cast(Any, kernel)._session = fake
    kernel._last_rx_at = kernel.now()  # interval not yet reached
    kernel._request_state = kernel_mod._RequestState.IN_FLIGHT  # busy with a command
    kernel.request_link_check()

    calls: list[bool] = []

    async def _probe(*, force: bool = False) -> bool:
        calls.append(force)
        return False

    cast(Any, kernel)._send_keepalive_request = _probe
    await kernel._keepalive_loop()
    assert calls == [True]
    assert len(fake.disconnects) == 1


def test_deliberate_close_logs_disconnect_at_debug(caplog: pytest.LogCaptureFixture) -> None:
    s = Session(
        cfg=SessionConfig(host="192.0.2.1"), client_identity=cast(Any, None), link_key_hex="00"
    )
    s._closing = True
    with caplog.at_level(logging.DEBUG, logger="elke27_lib.session"):
        s._handle_disconnect(None)
    recs = [r for r in caplog.records if "Session disconnect" in r.getMessage()]
    assert recs and all(r.levelno == logging.DEBUG for r in recs)


def test_link_loss_logs_disconnect_at_warning(caplog: pytest.LogCaptureFixture) -> None:
    s = Session(
        cfg=SessionConfig(host="192.0.2.1"), client_identity=cast(Any, None), link_key_hex="00"
    )
    with caplog.at_level(logging.DEBUG, logger="elke27_lib.session"):
        s._handle_disconnect(SessionProtocolError("Keepalive timed out"))
    recs = [r for r in caplog.records if "Session disconnect" in r.getMessage()]
    assert recs and all(r.levelno == logging.WARNING for r in recs)


def test_client_request_link_check_delegates() -> None:
    from elke27_lib.client import Elke27Client

    kernel = E27Kernel()
    client = Elke27Client(kernel=kernel)
    client.request_link_check()  # not connected: no-op
    assert kernel._keepalive_probe_requested is False
    kernel._keepalive_enabled = True
    cast(Any, kernel)._session = _FakeSession()
    client.request_link_check()
    assert kernel._keepalive_probe_requested is True
