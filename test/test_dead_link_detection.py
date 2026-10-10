"""Fast dead-link detection (HACS PR #42 hardware run, failure 1)."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any, cast

import pytest

import elke27_lib.kernel as kernel_mod
from elke27_lib.errors import E27Timeout
from elke27_lib.kernel import E27Kernel
from elke27_lib.outbound import OutboundPriority
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


def test_link_loss_logs_disconnect_at_info(caplog: pytest.LogCaptureFixture) -> None:
    s = Session(
        cfg=SessionConfig(host="192.0.2.1"), client_identity=cast(Any, None), link_key_hex="00"
    )
    with caplog.at_level(logging.DEBUG, logger="elke27_lib.session"):
        s._handle_disconnect(SessionProtocolError("Keepalive timed out"))
    recs = [r for r in caplog.records if "Session disconnect" in r.getMessage()]
    assert recs and all(r.levelno == logging.INFO for r in recs)


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


def _probing_kernel() -> E27Kernel:
    kernel = E27Kernel()
    kernel._keepalive_enabled = True
    cast(Any, kernel)._session = _FakeSession()
    kernel.requests.register(("system", "r_u_alive"), lambda: {})
    return kernel


@pytest.mark.asyncio
async def test_request_link_check_wakes_sleeping_loop() -> None:
    kernel = _probing_kernel()
    kernel._loop = asyncio.get_running_loop()
    kernel._keepalive_interval_s = 3600.0
    kernel._last_rx_at = kernel.now()
    calls: list[bool] = []

    async def _probe(*, force: bool = False) -> bool:
        calls.append(force)
        kernel._closing = True
        return True

    cast(Any, kernel)._send_keepalive_request = _probe
    kernel._start_keepalive()
    task = kernel._keepalive_task
    assert task is not None
    await asyncio.sleep(0.05)
    assert not task.done()  # sleeping for the hour-long interval
    kernel.request_link_check()
    await asyncio.wait_for(task, timeout=1.0)
    assert calls == [True]


def test_keepalive_restarts_on_fresh_event_loop() -> None:
    """connect -> close -> reconnect on a new loop must not reuse the old Event."""
    kernel = _probing_kernel()
    kernel._keepalive_interval_s = 3600.0
    calls: list[bool] = []

    async def _probe(*, force: bool = False) -> bool:
        calls.append(force)
        kernel._closing = True
        return True

    cast(Any, kernel)._send_keepalive_request = _probe

    async def _first() -> None:
        kernel._loop = asyncio.get_running_loop()
        kernel._last_rx_at = kernel.now()
        kernel._start_keepalive()
        await asyncio.sleep(0.05)  # loop is now waiting on the first Event
        kernel._stop_keepalive()  # close()
        await asyncio.sleep(0)

    asyncio.run(_first())
    assert kernel._keepalive_wake is None

    # A stale Event bound to the closed loop makes every wait fail instantly,
    # so the loop would busy-spin instead of sleeping. Count the sleeps.
    sleeps = {"n": 0}
    real_sleep = kernel._keepalive_sleep

    async def _counting_sleep(delay: float) -> None:
        sleeps["n"] += 1
        await real_sleep(delay)

    cast(Any, kernel)._keepalive_sleep = _counting_sleep

    async def _second() -> None:
        kernel._loop = asyncio.get_running_loop()
        kernel._last_rx_at = kernel.now()
        kernel._start_keepalive()
        task = kernel._keepalive_task
        assert task is not None
        await asyncio.sleep(0.05)
        assert sleeps["n"] == 1  # one long sleep, no spinning
        kernel.request_link_check()
        await asyncio.wait_for(task, timeout=1.0)

    asyncio.run(_second())
    assert calls == [True]


@pytest.mark.asyncio
async def test_probe_timeout_with_other_traffic_counts_as_alive() -> None:
    kernel = _probing_kernel()
    kernel._loop = asyncio.get_running_loop()
    kernel._last_rx_at = 0.0
    kernel._keepalive_interval_s = 0.0

    def _send(seq: int, *_a: Any, **_k: Any) -> int:
        kernel._signal_sent_event(seq)
        kernel._last_rx_at = kernel.now() + 1000.0  # other panel traffic arrived
        kernel._pending_responses.fail(seq, E27Timeout("t"))
        return seq

    cast(Any, kernel)._send_request_with_seq = _send
    assert await kernel._send_keepalive_request() is True


@pytest.mark.asyncio
async def test_probe_timeout_without_traffic_is_a_miss() -> None:
    kernel = _probing_kernel()
    kernel._loop = asyncio.get_running_loop()
    kernel._last_rx_at = 0.0
    kernel._keepalive_interval_s = 0.0

    def _send(seq: int, *_a: Any, **_k: Any) -> int:
        kernel._signal_sent_event(seq)
        kernel._pending_responses.fail(seq, E27Timeout("t"))
        return seq

    cast(Any, kernel)._send_request_with_seq = _send
    assert await kernel._send_keepalive_request() is False


@pytest.mark.asyncio
async def test_forced_probe_is_high_priority_while_command_queued() -> None:
    kernel = _probing_kernel()
    kernel._loop = asyncio.get_running_loop()
    kernel._last_rx_at = kernel.now()  # interval not reached
    kernel._request_state = kernel_mod._RequestState.IN_FLIGHT
    cast(Any, kernel)._request_queue_normal.append(object())
    seen: dict[str, Any] = {}

    def _send(seq: int, *_a: Any, **kw: Any) -> int:
        seen["priority"] = kw.get("priority")
        kernel._signal_sent_event(seq)
        kernel._pending_responses.resolve(seq, {"seq": seq, "system": {"r_u_alive": {}}})
        return seq

    cast(Any, kernel)._send_request_with_seq = _send
    # Not forced: deferred because a command is in flight and one is queued.
    assert await kernel._send_keepalive_request() is True
    assert "priority" not in seen
    # Forced: sent anyway, at HIGH priority so it goes ahead of the queue.
    assert await kernel._send_keepalive_request(force=True) is True
    assert seen["priority"] is OutboundPriority.HIGH


@pytest.mark.asyncio
async def test_wedged_outbound_does_not_hang_forced_probe() -> None:
    kernel = _probing_kernel()
    kernel._loop = asyncio.get_running_loop()
    kernel._last_rx_at = 0.0
    kernel._keepalive_send_wait_s = 0.05

    def _send(seq: int, *_a: Any, **_k: Any) -> int:
        return seq  # never leaves the outbound queue

    cast(Any, kernel)._send_request_with_seq = _send
    result = await asyncio.wait_for(kernel._send_keepalive_request(force=True), timeout=2.0)
    assert result is False
    assert kernel._keepalive_inflight is False


def test_close_resets_closing_flag_when_it_raises() -> None:
    s = Session(
        cfg=SessionConfig(host="192.0.2.1"), client_identity=cast(Any, None), link_key_hex="00"
    )

    def _boom() -> None:
        raise RuntimeError("receiver stop failed")

    cast(Any, s)._stop_receiver = _boom
    with pytest.raises(RuntimeError):
        s.close()
    assert s._closing is False
