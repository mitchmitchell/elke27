"""Keepalive miss policy and liveness source against a loopback panel (#149).

Every case runs the real ``Session`` and ``E27Kernel`` against
``test.helpers.panel_simulator`` and checks only public results: connection
events, ``keepalive_stats``, the client's warning, and what the panel saw.

Timing is scaled down from production (30 s idle interval, 5 s reply timeout) so
the suite stays fast. ``SCALE`` maps the production figures in the issue onto the
test clock; the ratios between interval, timeout and loop delay are kept.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any

import pytest

from elke27_lib.client import Elke27Client
from elke27_lib.events import ConnectionStateChanged, Event
from elke27_lib.kernel_loop import E27Kernel, KeepaliveStats
from test.helpers.panel_simulator import IDENTITY, LINK_KEYS, PanelSimulator
from test.helpers.timers_first_loop import TimersFirstEventLoop

SCALE = 0.2
REPLY_TIMEOUT_S = 5.0 * SCALE
FAST_INTERVAL_S = 0.5
FAST_TIMEOUT_S = 0.25


def _record_connection_events(kernel: E27Kernel) -> list[ConnectionStateChanged]:
    events: list[ConnectionStateChanged] = []

    def _on_event(evt: Event) -> None:
        if isinstance(evt, ConnectionStateChanged):
            events.append(evt)

    kernel.subscribe(_on_event, kinds=[ConnectionStateChanged.KIND])
    return events


def _drops(events: list[ConnectionStateChanged]) -> list[ConnectionStateChanged]:
    return [evt for evt in events if not evt.connected]


async def _wait_for(cond: Callable[[], bool], *, timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if cond():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not met in time")


async def _connected_kernel(
    panel: PanelSimulator, *, interval_s: float, timeout_s: float
) -> tuple[E27Kernel, list[ConnectionStateChanged]]:
    kernel = E27Kernel(skip_connect_bootstrap=True)
    events = _record_connection_events(kernel)
    await kernel.connect(
        LINK_KEYS,
        client_identity=IDENTITY,
        session_config=panel.session_config(interval_s=interval_s, timeout_s=timeout_s),
    )
    return kernel, events


def _run(
    factory: Callable[[], asyncio.AbstractEventLoop],
    scenario: Callable[[], Coroutine[Any, Any, None]],
) -> None:
    with asyncio.Runner(loop_factory=factory) as runner:
        runner.run(scenario())


@dataclass
class _DelayOutcome:
    stats: KeepaliveStats = field(default_factory=KeepaliveStats)
    drops: list[ConnectionStateChanged] = field(default_factory=list)
    probes: int = 0


@pytest.mark.asyncio
async def test_one_missed_probe_then_prompt_second_probe_stays_connected() -> None:
    with PanelSimulator() as panel:
        panel.drop_probe_replies = 1
        kernel, events = await _connected_kernel(
            panel, interval_s=FAST_INTERVAL_S, timeout_s=FAST_TIMEOUT_S
        )
        try:
            await _wait_for(lambda: kernel.keepalive_stats.replies >= 1, timeout_s=5.0)
            stats = kernel.keepalive_stats
            assert _drops(events) == []
            assert stats.misses == 1
            assert stats.consecutive_missed == 0
            assert panel.probes >= 2
            second_probe_gap = panel.probe_times[1] - panel.probe_times[0]
            assert second_probe_gap < FAST_TIMEOUT_S + FAST_INTERVAL_S / 2
        finally:
            await kernel.close()


@pytest.mark.asyncio
async def test_second_probe_after_a_miss_is_not_held_behind_queued_commands() -> None:
    """A command queued during the first probe must not delay the second probe
    past that command's own reply: the follow-up probe goes out next."""
    loop = asyncio.get_running_loop()
    with PanelSimulator() as panel:
        panel.drop_probe_replies = 1
        panel.answer_commands_after_s = 0.05
        kernel, events = await _connected_kernel(
            panel, interval_s=FAST_INTERVAL_S, timeout_s=FAST_TIMEOUT_S
        )

        def _queue_command_during_first_probe() -> None:
            if panel.probes == 1:
                loop.call_soon_threadsafe(lambda: kernel.request(("area", "get_status"), area_id=1))

        panel.on_probe = _queue_command_during_first_probe
        try:
            await _wait_for(lambda: kernel.keepalive_stats.replies >= 1, timeout_s=5.0)
            assert _drops(events) == []
            second_probe_gap = panel.probe_times[1] - panel.probe_times[0]
            assert second_probe_gap < FAST_TIMEOUT_S + 0.3
        finally:
            await kernel.close()


@pytest.mark.asyncio
async def test_two_consecutive_missed_probes_disconnect() -> None:
    with PanelSimulator() as panel:
        panel.drop_probe_replies = 2
        started = time.monotonic()
        kernel, events = await _connected_kernel(
            panel, interval_s=FAST_INTERVAL_S, timeout_s=FAST_TIMEOUT_S
        )
        try:
            await _wait_for(lambda: bool(_drops(events)), timeout_s=5.0)
            detected_after = time.monotonic() - started
            assert panel.probes == 2
            assert kernel.keepalive_stats.misses == 2
            assert detected_after < FAST_INTERVAL_S + 2 * FAST_TIMEOUT_S + 0.75
            assert _drops(events)[0].error_type == "SessionProtocolError"
        finally:
            await kernel.close()


@pytest.mark.asyncio
async def test_any_inbound_after_the_probe_rescues_a_missing_reply() -> None:
    with PanelSimulator() as panel:
        panel.drop_probe_replies = 1
        panel.unsolicited_after_probe_s = FAST_TIMEOUT_S / 5
        kernel, events = await _connected_kernel(
            panel, interval_s=FAST_INTERVAL_S, timeout_s=FAST_TIMEOUT_S
        )
        try:
            await _wait_for(lambda: kernel.keepalive_stats.rescued >= 1, timeout_s=5.0)
            stats = kernel.keepalive_stats
            assert stats.misses == 0
            assert stats.consecutive_missed == 0
            assert _drops(events) == []
        finally:
            await kernel.close()


@pytest.mark.parametrize(
    "loop_factory",
    [asyncio.new_event_loop, TimersFirstEventLoop],
    ids=["asyncio-loop", "timers-first-loop"],
)
@pytest.mark.parametrize(
    "loop_delay_s",
    [6.0 * SCALE, 20.0 * SCALE],
    ids=["loop-delayed-6s", "loop-delayed-20s"],
)
def test_prompt_reply_while_loop_is_delayed_is_not_a_miss(
    loop_factory: Callable[[], asyncio.AbstractEventLoop], loop_delay_s: float
) -> None:
    """The panel replies 0.2 s after the probe, while the bound loop is blocked
    past the reply timeout. The receive thread saw the reply, so it is not a miss."""
    outcome = _DelayOutcome()

    async def _scenario() -> None:
        loop = asyncio.get_running_loop()
        with PanelSimulator() as panel:
            panel.probe_reply_delay_s = 0.2

            def _block_loop_after_probe() -> None:
                loop.call_soon_threadsafe(loop.call_later, 0.02, time.sleep, loop_delay_s)

            panel.on_probe = _block_loop_after_probe
            kernel, events = await _connected_kernel(
                panel, interval_s=30.0, timeout_s=REPLY_TIMEOUT_S
            )
            try:
                kernel.request_link_check()
                await _wait_for(lambda: panel.probes >= 1, timeout_s=5.0)
                await asyncio.sleep(loop_delay_s + 0.3)
                outcome.stats = kernel.keepalive_stats
                outcome.drops = _drops(events)
                outcome.probes = panel.probes
            finally:
                await kernel.close()

    _run(loop_factory, _scenario)
    assert outcome.drops == []
    assert outcome.probes == 1
    assert outcome.stats.misses == 0
    assert outcome.stats.replies + outcome.stats.rescued == 1


@pytest.mark.asyncio
async def test_keepalive_disconnect_carries_err_msg_on_event_and_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with PanelSimulator() as panel:
        panel.drop_probe_replies = 2
        client = Elke27Client(skip_connect_bootstrap=True)
        events: list[ConnectionStateChanged] = []

        def _on_event(evt: Event) -> None:
            if isinstance(evt, ConnectionStateChanged):
                events.append(evt)

        client.subscribe_typed(_on_event)
        with caplog.at_level(logging.WARNING):
            result = await client.connect(
                LINK_KEYS,
                client_identity=IDENTITY,
                session_config=panel.session_config(
                    interval_s=FAST_INTERVAL_S, timeout_s=FAST_TIMEOUT_S
                ),
            )
            assert result.ok
            try:
                await _wait_for(lambda: bool(_drops(events)), timeout_s=5.0)
            finally:
                await client.close()
        drop = _drops(events)[0]
        assert drop.err_msg == "Keepalive timed out"
        assert drop.error_type == "SessionProtocolError"
        lost = [r for r in caplog.records if "Panel connection lost" in r.getMessage()]
        assert len(lost) == 1
        assert "err_msg=Keepalive timed out" in lost[0].getMessage()
