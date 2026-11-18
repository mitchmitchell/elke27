"""A keepalive probe's reply deadline starts when it is sent, not queued (#151).

Runs the real ``Session`` and ``E27Kernel`` against
``test.helpers.panel_simulator`` and checks public results only: connection
events, ``keepalive_stats``, and when the panel actually received each probe.
The one documented exception, a probe stuck in the queue past the send wait, is
exercised with a short ``KeepaliveTestHooks.send_wait_s``.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass

import pytest

from elke27_lib.events import ConnectionStateChanged, Event
from elke27_lib.kernel_loop import E27Kernel, KeepaliveTestHooks
from test.helpers.panel_simulator import IDENTITY, LINK_KEYS, PanelSimulator

PROBE_TIMEOUT_S = 0.25
COMMAND_TIMEOUT_S = 1.0
SEND_WAIT_S = 0.4
WEDGED_COMMAND_TIMEOUT_S = 100.0
DISCONNECT_MARGIN_S = 0.6


@dataclass
class _FirstMiss:
    at: float | None = None
    probes_seen_by_panel: int = 0


async def _wait_for(cond: Callable[[], bool], *, timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if cond():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("condition not met in time")


@pytest.mark.asyncio
async def test_probe_queued_behind_unanswered_command_is_not_a_miss_until_sent() -> None:
    with PanelSimulator() as panel:
        panel.drop_probe_replies = 2
        kernel = E27Kernel(
            skip_connect_bootstrap=True,
            request_timeout_s=COMMAND_TIMEOUT_S,
            request_max_retries=0,
        )
        drops: list[tuple[float, int]] = []

        def _on_event(evt: Event) -> None:
            if isinstance(evt, ConnectionStateChanged) and not evt.connected:
                drops.append((time.monotonic(), panel.probes))

        kernel.subscribe(_on_event, kinds=[ConnectionStateChanged.KIND])
        await kernel.connect(
            LINK_KEYS,
            client_identity=IDENTITY,
            session_config=panel.session_config(interval_s=30.0, timeout_s=PROBE_TIMEOUT_S),
        )
        first_miss = _FirstMiss()

        async def _watch_misses() -> None:
            while first_miss.at is None:
                if kernel.keepalive_stats.misses >= 1:
                    first_miss.at = time.monotonic()
                    first_miss.probes_seen_by_panel = panel.probes
                    return
                await asyncio.sleep(0.002)

        watcher = asyncio.create_task(_watch_misses())
        try:
            kernel.request(("area", "get_status"), area_id=1)
            kernel.request_link_check()
            await asyncio.sleep(COMMAND_TIMEOUT_S * 0.8)
            assert panel.probes == 0
            assert kernel.keepalive_stats.misses == 0
            assert drops == []

            await _wait_for(lambda: bool(drops), timeout_s=5.0)
            assert panel.probes == 2
            assert kernel.keepalive_stats.misses == 2
            assert first_miss.at is not None
            assert first_miss.probes_seen_by_panel >= 1
            assert first_miss.at >= panel.probe_times[0] + PROBE_TIMEOUT_S * 0.8
            drop_at, probes_at_drop = drops[0]
            assert probes_at_drop == 2
            assert drop_at >= panel.probe_times[1] + PROBE_TIMEOUT_S * 0.8
        finally:
            watcher.cancel()
            await kernel.close()


async def _connect_wedged(
    panel: PanelSimulator,
    *,
    send_wait_s: float = SEND_WAIT_S,
    command_timeout_s: float = WEDGED_COMMAND_TIMEOUT_S,
) -> tuple[E27Kernel, list[tuple[float, int]]]:
    """Connect with a short send wait, then hold the queue with an unanswered command."""
    kernel = E27Kernel(
        skip_connect_bootstrap=True,
        request_timeout_s=command_timeout_s,
        request_max_retries=0,
        keepalive_test_hooks=KeepaliveTestHooks(send_wait_s=send_wait_s),
    )
    drops: list[tuple[float, int]] = []

    def _on_event(evt: Event) -> None:
        if isinstance(evt, ConnectionStateChanged) and not evt.connected:
            drops.append((time.monotonic(), panel.probes))

    kernel.subscribe(_on_event, kinds=[ConnectionStateChanged.KIND])
    await kernel.connect(
        LINK_KEYS,
        client_identity=IDENTITY,
        session_config=panel.session_config(interval_s=30.0, timeout_s=PROBE_TIMEOUT_S),
    )
    kernel.request(("area", "get_status"), area_id=1)
    return kernel, drops


@pytest.mark.asyncio
async def test_probe_stuck_past_send_wait_counts_as_miss_and_disconnects() -> None:
    """Wedged queue: two send waits, two misses, then a disconnect.

    The bound is ``2 * SEND_WAIT_S + DISCONNECT_MARGIN_S`` (0.8 s + 0.6 s) from
    the link check. The 0.6 s margin covers event-loop and thread scheduling lag
    under heavy CPU load and is still well short of a third send wait.
    """
    with PanelSimulator() as panel:
        kernel, drops = await _connect_wedged(panel)
        try:
            requested_at = time.monotonic()
            kernel.request_link_check()
            await _wait_for(lambda: bool(drops), timeout_s=5.0)
            drop_at, probes_at_drop = drops[0]
            assert probes_at_drop == 0
            assert panel.probes == 0
            assert kernel.keepalive_stats.misses == 2
            assert drop_at - requested_at >= 2 * SEND_WAIT_S * 0.95
            assert drop_at - requested_at <= 2 * SEND_WAIT_S + DISCONNECT_MARGIN_S
        finally:
            await kernel.close()


@pytest.mark.asyncio
async def test_inbound_after_probe_queued_rescues_send_wait_miss() -> None:
    """Same wedge, but the panel sends something after the probe is queued."""
    with PanelSimulator() as panel:
        kernel, drops = await _connect_wedged(panel)
        try:
            kernel.request_link_check()
            await asyncio.sleep(SEND_WAIT_S / 2)
            panel.send_unsolicited()
            await asyncio.sleep(3 * SEND_WAIT_S + DISCONNECT_MARGIN_S)
            assert drops == []
            assert panel.probes == 0
            assert kernel.keepalive_stats.misses == 0
        finally:
            await kernel.close()


async def _assert_next_probe_goes_out_alone(kernel: E27Kernel, panel: PanelSimulator) -> None:
    """A fresh link check sends exactly one probe, so no stale probe is left queued."""
    probes_before = panel.probes
    sent_before = kernel.keepalive_stats.probes_sent
    replies_before = kernel.keepalive_stats.replies
    kernel.request_link_check()
    await _wait_for(lambda: kernel.keepalive_stats.replies > replies_before, timeout_s=5.0)
    await asyncio.sleep(0.2)
    assert panel.probes == probes_before + 1
    assert kernel.keepalive_stats.probes_sent == sent_before + 1


@pytest.mark.asyncio
async def test_probe_abandoned_after_send_wait_miss_never_reaches_panel() -> None:
    """After a send-wait miss, releasing the wedge sends only the follow-up probe.

    Send wait 1.0 s; the panel answers the blocking command 1.5 s after receiving
    it. The first probe misses at about 1.0 s, the follow-up is queued, and the
    command reply frees the queue about 0.5 s before the follow-up's own send wait
    would end.
    """
    with PanelSimulator() as panel:
        panel.answer_commands_after_s = 1.5
        kernel, drops = await _connect_wedged(panel, send_wait_s=1.0)
        try:
            kernel.request_link_check()
            await _wait_for(lambda: kernel.keepalive_stats.replies >= 1, timeout_s=5.0)
            await asyncio.sleep(0.5)
            assert drops == []
            assert kernel.keepalive_stats.misses == 1
            assert panel.probes == 1
            assert kernel.keepalive_stats.probes_sent == panel.probes
            await _assert_next_probe_goes_out_alone(kernel, panel)
            assert kernel.keepalive_stats.probes_sent == panel.probes
        finally:
            await kernel.close()


@pytest.mark.asyncio
async def test_probe_abandoned_after_rescue_never_reaches_panel() -> None:
    """After a rescued send wait, the blocking command timing out sends no stale probe.

    Send wait 0.4 s, rescue traffic at 0.2 s, and the blocking command times out
    about 1.0 s after it was sent, which frees the queue.
    """
    with PanelSimulator() as panel:
        kernel, drops = await _connect_wedged(panel, command_timeout_s=1.0)
        try:
            kernel.request_link_check()
            await asyncio.sleep(SEND_WAIT_S / 2)
            panel.send_unsolicited()
            await asyncio.sleep(2.0)
            assert drops == []
            assert kernel.keepalive_stats.misses == 0
            assert panel.probes == 0
            assert kernel.keepalive_stats.probes_sent == panel.probes
            await _assert_next_probe_goes_out_alone(kernel, panel)
            assert kernel.keepalive_stats.probes_sent == panel.probes
        finally:
            await kernel.close()
