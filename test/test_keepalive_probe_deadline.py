"""A keepalive probe's reply deadline starts when it is sent, not queued (#151).

Runs the real ``Session`` and ``E27Kernel`` against
``test.helpers.panel_simulator`` and checks public results only: connection
events, ``keepalive_stats``, and when the panel actually received each probe.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass

import pytest

from elke27_lib.events import ConnectionStateChanged, Event
from elke27_lib.kernel_loop import E27Kernel
from test.helpers.panel_simulator import IDENTITY, LINK_KEYS, PanelSimulator

PROBE_TIMEOUT_S = 0.25
COMMAND_TIMEOUT_S = 1.0


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
