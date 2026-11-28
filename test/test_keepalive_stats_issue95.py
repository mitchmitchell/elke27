"""Keepalive stats semantics from Architect note on #95, through the public API.

Each kernel is connected to a fake panel link with ``E27Kernel.connect``, probes
are started with ``request_link_check`` and outcomes come from ``keepalive_stats``.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Mapping
from typing import Any

import pytest

from elke27_lib import session_thread as session_mod
from elke27_lib.kernel_loop import KernelError
from test.helpers.keepalive_link import (
    IDLE_INTERVAL_S,
    TIMEOUT_S,
    KeepaliveLink,
    assert_keepalive_invariants,
    keepalive_link,
    until,
)


async def _finished(link: Any, field: str, value: int = 1) -> None:
    await until(lambda: getattr(link.stats, field) >= value)


@pytest.mark.asyncio
async def test_unsent_probe_send_error_counts_failed_not_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    link = keepalive_link(monkeypatch, send_wait_s=0.05, fail_sends=True)
    session = await link.connect()
    link.kernel.request_link_check()
    await _finished(link, "misses")
    stats = link.stats
    assert session.sent == []
    assert stats.probes_sent == 0
    assert stats.probes_failed == 1
    assert stats.probe_in_flight is False
    assert_keepalive_invariants(stats)


@pytest.mark.asyncio
async def test_unsent_probe_send_wait_timeout_counts_failed_not_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    link = keepalive_link(monkeypatch, send_wait_s=0.05)
    await link.connect()
    await link.check_link()
    await _finished(link, "misses")
    stats = link.stats
    assert stats.probes_sent == 0
    assert stats.probes_failed == 1
    assert stats.probe_in_flight is False
    assert_keepalive_invariants(stats)


@pytest.mark.asyncio
async def test_unsent_probe_abort_counts_failed_not_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    link = keepalive_link(monkeypatch, send_wait_s=2.0)
    session = await link.connect()
    await link.check_link()
    session.drop()
    await _finished(link, "misses")
    stats = link.stats
    assert stats.probes_sent == 0
    assert stats.probes_failed == 1
    assert stats.probe_in_flight is False
    assert_keepalive_invariants(stats)


@pytest.mark.asyncio
async def test_probe_that_cannot_be_queued_counts_failed_not_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    holder: list[Any] = []

    def _builder() -> Mapping[str, Any]:
        holder[0].session.state = session_mod.SessionState.DISCONNECTED
        return {}

    link = keepalive_link(monkeypatch, probe_builder=_builder)
    holder.append(link)
    session = await link.connect()
    link.kernel.request_link_check()
    await _finished(link, "misses")
    stats = link.stats
    assert session.sent == []
    assert stats.probes_sent == 0
    assert stats.probes_failed == 1
    assert stats.probe_in_flight is False


@pytest.mark.asyncio
async def test_immediate_reply_uses_confirmed_send_time_not_now(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    link = keepalive_link(monkeypatch)
    session = await link.connect()
    await link.check_link()
    session.confirm(0)
    assert link.stats.probe_in_flight is True
    link.advance(0.250)
    session.reply(0)
    await _finished(link, "replies")
    stats = link.stats
    assert stats.probes_sent == 1
    assert stats.replies == 1
    assert stats.last_round_trip_s == 0.250
    assert stats.max_round_trip_s == 0.250
    assert stats.probe_in_flight is False
    assert_keepalive_invariants(stats)


@pytest.mark.asyncio
async def test_unsent_probe_and_unrelated_inbound_does_not_count_reply_or_rtt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    link = keepalive_link(monkeypatch, send_wait_s=0.05)
    session = await link.connect()
    await link.check_link()
    session.receive({"seq": session.seq(0) + 99, "area": {"get_status": {"area_id": 1}}})
    await asyncio.sleep(0)
    assert link.stats.replies == 0
    assert link.stats.last_round_trip_s is None
    await _finished(link, "misses")
    stats = link.stats
    assert stats.replies == 0
    assert stats.last_round_trip_s is None
    assert stats.probes_failed == 1


@pytest.mark.asyncio
async def test_stale_reply_does_not_update_newer_outstanding_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    link = keepalive_link(monkeypatch)
    session = await link.connect(max_missed=2)
    await link.check_link()
    session.confirm(0)
    link.advance(TIMEOUT_S + 0.01)
    await until(lambda: len(session.sent) >= 2)
    assert link.stats.probe_timeouts == 1
    assert session.seq(1) != session.seq(0)
    session.reply(0)
    await asyncio.sleep(0)
    assert link.stats.replies == 0
    assert link.stats.last_round_trip_s is None
    session.confirm(1)
    link.advance(0.1)
    session.reply(1)
    await _finished(link, "replies")
    stats = link.stats
    assert stats.replies == 1
    assert stats.probe_timeouts == 1
    assert stats.last_round_trip_s == pytest.approx(0.1)
    assert stats.probe_in_flight is False
    assert_keepalive_invariants(stats)


@pytest.mark.asyncio
async def test_unanswered_probe_probe_timeout_and_rescued(monkeypatch: pytest.MonkeyPatch) -> None:
    link = keepalive_link(monkeypatch)
    session = await link.connect()
    await link.check_link()
    sent_seq = session.confirm(0)
    link.advance(TIMEOUT_S + 0.01)
    session.receive({"seq": sent_seq + 500, "area": {"get_status": {"area_id": 1}}})
    await _finished(link, "rescued")
    stats = link.stats
    assert stats.probes_sent == 1
    assert stats.probe_timeouts == 1
    assert stats.rescued == 1
    assert stats.replies == 0
    assert stats.misses == 0
    assert_keepalive_invariants(stats)


@pytest.mark.asyncio
async def test_large_clock_offset_reports_non_negative_rtt_without_clamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    link = keepalive_link(monkeypatch, start=9_000_000_000.0)
    session = await link.connect()
    await link.check_link()
    session.confirm(0)
    link.clock.advance(12.5)
    session.reply(0)
    await _finished(link, "replies")
    assert link.stats.last_round_trip_s == 12.5
    assert_keepalive_invariants(link.stats)


@pytest.mark.asyncio
async def test_non_keepalive_tracked_request_is_not_a_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    link = keepalive_link(monkeypatch)
    session = await link.connect()
    link.kernel.register_request(("area", "get_status"), lambda area_id=1: {"area_id": area_id})
    seq = link.kernel.request(("area", "get_status"), area_id=1)
    link.kernel.register_sent_event(seq, asyncio.Event())
    await until(lambda: len(session.sent) >= 1)
    assert session.confirm(0) == seq
    assert link.kernel.was_request_sent(seq)
    assert link.stats.probe_in_flight is False


@pytest.mark.asyncio
async def test_probe_cancelled_at_await_future_leaves_no_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    link = keepalive_link(monkeypatch)
    session = await link.connect()
    await link.check_link()
    session.confirm(0)
    await _finished(link, "probes_sent")
    assert link.stats.probe_in_flight is True
    await link.kernel.close()
    assert link.stats.probe_in_flight is False
    assert link.kernel.pending_responses.pending_count() == 0
    assert session.cancelled == [session.seq(0)]
    stats = link.stats
    assert stats.replies == 0
    assert stats.probe_timeouts == 0
    assert_keepalive_invariants(stats)


@pytest.mark.asyncio
async def test_late_on_sent_after_abandon_leaves_no_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    link = keepalive_link(monkeypatch, send_wait_s=0.05)
    session = await link.connect()
    await link.check_link()
    await _finished(link, "misses")
    session.confirm(0)
    stats = link.stats
    assert stats.probes_sent == 0
    assert stats.probes_failed == 1
    assert stats.probe_in_flight is False


@pytest.mark.asyncio
async def test_probe_timeout_does_not_count_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    link = keepalive_link(monkeypatch)
    session = await link.connect()
    await link.check_link()
    session.confirm(0)
    link.advance(TIMEOUT_S + 0.01)
    await _finished(link, "misses")
    stats = link.stats
    assert stats.probes_sent == 1
    assert stats.probe_timeouts == 1
    assert stats.probes_failed == 0
    assert stats.probe_in_flight is False
    assert len(session.disconnects) == 1


@pytest.mark.asyncio
async def test_written_probe_other_error_counts_neither_failed_nor_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    link = keepalive_link(monkeypatch)
    session = await link.connect()
    await link.check_link()
    seq = session.confirm(0)
    await _finished(link, "probes_sent")
    link.kernel.pending_responses.fail(seq, KernelError("post-write failure"))
    await _finished(link, "misses")
    stats = link.stats
    assert stats.probes_sent == 1
    assert stats.probes_failed == 0
    assert stats.probe_timeouts == 0
    assert stats.replies == 0
    assert stats.probe_in_flight is False


@pytest.mark.asyncio
async def test_close_clears_confirmed_send_records(monkeypatch: pytest.MonkeyPatch) -> None:
    link = keepalive_link(monkeypatch)
    session = await link.connect()
    link.kernel.register_request(("area", "arm"), dict)
    seq = link.kernel.request(("area", "arm"))
    link.kernel.register_sent_event(seq, asyncio.Event())
    session.confirm(0)
    assert link.kernel.was_request_sent(seq)
    await link.kernel.close()
    assert not link.kernel.was_request_sent(seq)


@pytest.mark.asyncio
async def test_connect_clears_confirmed_send_records(monkeypatch: pytest.MonkeyPatch) -> None:
    link = keepalive_link(monkeypatch)
    session = await link.connect()
    link.kernel.register_request(("area", "arm"), dict)
    seq = link.kernel.request(("area", "arm"))
    link.kernel.register_sent_event(seq, asyncio.Event())
    session.confirm(0)
    assert link.kernel.was_request_sent(seq)
    await link.connect()
    assert not link.kernel.was_request_sent(seq)
    await link.kernel.close()


@pytest.mark.asyncio
async def test_each_probe_gets_its_own_rtt_across_a_reconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    link = keepalive_link(monkeypatch)
    first = await link.connect()
    await link.check_link()
    first.confirm(0)
    link.advance(0.25)
    first.reply(0)
    await _finished(link, "replies")
    assert link.stats.probe_in_flight is False
    second = await link.connect()
    await link.check_link()
    second.confirm(0)
    link.advance(0.1)
    second.reply(0)
    await _finished(link, "replies", 2)
    stats = link.stats
    assert stats.probes_sent == 2
    assert stats.last_round_trip_s == pytest.approx(0.1)
    assert stats.max_round_trip_s == pytest.approx(0.25)
    assert stats.probe_in_flight is False
    assert_keepalive_invariants(stats)
    await link.kernel.close()


@pytest.mark.asyncio
async def test_probe_is_in_flight_before_its_write_is_confirmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    link = keepalive_link(monkeypatch)
    session = await link.connect()
    await link.check_link()
    assert link.stats.probe_in_flight is True
    session.confirm(0)
    session.reply(0)
    await until(lambda: link.stats.replies == 1)
    assert link.stats.probe_in_flight is False
    await link.kernel.close()


@pytest.mark.asyncio
async def test_reconnect_with_a_written_probe_outstanding_does_not_count_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    link = keepalive_link(monkeypatch)
    old = await link.connect()
    await link.check_link()
    old.confirm(0)
    await _finished(link, "probes_sent")
    new = await link.connect()
    await until(lambda: link.stats.probe_in_flight is False)
    old.reply(0)
    await asyncio.sleep(0)
    stats = link.stats
    assert stats.probes_sent == 1
    assert stats.replies == 0
    assert stats.probe_timeouts == 0
    assert stats.probes_failed == 0
    assert stats.misses == 0
    assert old.disconnects == []
    await link.check_link()
    new.confirm(0)
    link.advance(0.1)
    new.reply(0)
    await _finished(link, "replies")
    stats = link.stats
    assert stats.probes_sent == 2
    assert stats.last_round_trip_s == pytest.approx(0.1)
    assert stats.probe_in_flight is False
    assert new.disconnects == []
    assert_keepalive_invariants(stats)
    await link.kernel.close()


@pytest.mark.asyncio
async def test_reconnect_with_an_unwritten_probe_outstanding_does_not_count_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    link = keepalive_link(monkeypatch)
    old = await link.connect()
    await link.check_link()
    new = await link.connect()
    await until(lambda: link.stats.probe_in_flight is False)
    stats = link.stats
    assert stats.probes_sent == 0
    assert stats.probes_failed == 0
    assert stats.misses == 0
    await link.check_link()
    new.confirm(0)
    link.advance(0.05)
    old.confirm(0)
    link.advance(0.05)
    new.reply(0)
    await _finished(link, "replies")
    stats = link.stats
    assert stats.probes_sent == 1
    assert stats.last_round_trip_s == pytest.approx(0.1)
    assert stats.probe_in_flight is False
    assert_keepalive_invariants(stats)
    await link.kernel.close()


@pytest.mark.asyncio
async def test_unsent_probe_with_later_inbound_fails_but_keeps_the_link(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    link = keepalive_link(monkeypatch, send_wait_s=0.05)
    session = await link.connect()
    await link.check_link()
    link.clock.advance(0.01)
    session.receive({"seq": session.seq(0) + 99, "area": {"get_status": {"area_id": 1}}})
    await _finished(link, "probes_failed")
    stats = link.stats
    assert stats.probes_sent == 0
    assert stats.misses == 0
    assert stats.probe_in_flight is False
    await link.kernel.close()


@pytest.mark.asyncio
async def test_reconnect_after_the_idle_interval_sends_no_probe_on_the_old_link(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    link = keepalive_link(monkeypatch)
    old = await link.connect()
    await link.check_link()
    old.confirm(0)
    await _finished(link, "probes_sent")
    link.clock.advance(IDLE_INTERVAL_S + 1.0)
    gate = threading.Event()
    link.connect_gate = gate
    connecting = asyncio.create_task(link.connect())
    await until(lambda: len(link.links) == 2 and link.links[1].handshake_entered.is_set())
    assert link.stats.probe_in_flight is False
    assert link.kernel.pending_responses.pending_count() == 0
    assert len(old.sent) == 1
    assert old.cancelled == [old.seq(0)]
    gate.set()
    new = await asyncio.wait_for(connecting, timeout=2.0)
    assert len(old.sent) == 1
    await link.check_link()
    new.confirm(0)
    link.advance(0.2)
    new.reply(0)
    await _finished(link, "replies")
    stats = link.stats
    assert stats.probes_sent == 2
    assert stats.last_round_trip_s == pytest.approx(0.2)
    assert stats.misses == 0
    assert stats.probe_in_flight is False
    assert old.disconnects == []
    assert new.disconnects == []
    await link.kernel.close()


@pytest.mark.asyncio
async def test_connect_from_inside_the_keepalive_task_fails_loudly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    holder: list[Any] = []
    errors: list[KernelError] = []

    async def _sleep(delay: float) -> None:
        if delay < IDLE_INTERVAL_S / 2 and not errors:
            try:
                await holder[0].connect()
            except KernelError as exc:
                errors.append(exc)
        await asyncio.Event().wait()

    link = keepalive_link(monkeypatch, sleep=_sleep)
    holder.append(link)
    session = await link.connect()
    session.state = session_mod.SessionState.DISCONNECTED
    link.kernel.request_link_check()
    await until(lambda: bool(errors))
    assert "inside the keepalive task" in str(errors[0])
    assert len(link.links) == 1
    await link.kernel.close()
    assert link.stats.probe_in_flight is False


@pytest.mark.asyncio
async def test_failed_reconnect_keeps_probing_the_old_link_with_its_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    link = keepalive_link(monkeypatch)
    old = await link.connect(max_missed=1)
    link.fail_connect = True
    with pytest.raises(KernelError, match="Session connect failed"):
        await link.connect(max_missed=3, interval_s=1.0, timeout_s=TIMEOUT_S * 4)
    link.clock.advance(2.0)
    for _ in range(20):
        await asyncio.sleep(0)
    assert old.sent == []
    link.kernel.request_link_check()
    await until(lambda: len(old.sent) >= 1)
    old.confirm(0)
    link.advance(TIMEOUT_S + 0.01)
    await _finished(link, "misses")
    stats = link.stats
    assert stats.probe_timeouts == 1
    assert len(old.disconnects) == 1
    assert len(old.sent) == 1
    await link.kernel.close()


@pytest.mark.asyncio
async def test_cancelled_reconnect_keeps_probing_the_old_link(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    link = keepalive_link(monkeypatch)
    old = await link.connect()
    gate = threading.Event()
    link.connect_gate = gate
    connecting = asyncio.create_task(link.connect())
    await until(lambda: len(link.links) == 2 and link.links[1].handshake_entered.is_set())
    connecting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await connecting
    gate.set()
    link.kernel.request_link_check()
    await until(lambda: len(old.sent) >= 1)
    old.confirm(0)
    link.advance(0.1)
    old.reply(0)
    await _finished(link, "replies")
    assert link.stats.last_round_trip_s == pytest.approx(0.1)
    assert link.links[1].sent == []
    await link.kernel.close()


@pytest.mark.asyncio
async def test_failed_reconnect_does_not_start_a_loop_that_had_ended(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    link = keepalive_link(monkeypatch)
    old = await link.connect(max_missed=1)
    await link.check_link()
    old.confirm(0)
    link.advance(TIMEOUT_S + 0.01)
    await until(lambda: len(old.disconnects) == 1)
    old.state = session_mod.SessionState.ACTIVE
    link.fail_connect = True
    with pytest.raises(KernelError, match="Session connect failed"):
        await link.connect()
    link.kernel.request_link_check()
    for _ in range(20):
        await asyncio.sleep(0)
    assert len(old.sent) == 1
    await link.kernel.close()


@pytest.mark.asyncio
async def test_reconnect_cancelled_while_the_old_loop_stops_keeps_probing_the_old_link(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    link = keepalive_link(monkeypatch)
    old = await link.connect()
    await link.check_link()
    connecting = asyncio.create_task(link.connect())
    await until(lambda: len(link.links) == 2)
    connecting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await connecting
    assert not link.links[1].handshake_entered.is_set()
    assert old.cancelled == [old.seq(0)]
    link.kernel.request_link_check()
    await until(lambda: len(old.sent) >= 2)
    assert link.stats.probe_in_flight is True
    await link.kernel.close()


@pytest.mark.asyncio
async def test_close_from_inside_the_keepalive_task_fails_loudly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    holder: list[Any] = []
    errors: list[KernelError] = []

    async def _sleep(delay: float) -> None:
        if delay < IDLE_INTERVAL_S / 2 and not errors:
            try:
                await holder[0].kernel.close()
            except KernelError as exc:
                errors.append(exc)
        await asyncio.Event().wait()

    link = keepalive_link(monkeypatch, sleep=_sleep)
    holder.append(link)
    session = await link.connect()
    session.state = session_mod.SessionState.DISCONNECTED
    link.kernel.request_link_check()
    await until(lambda: bool(errors))
    assert "close() cannot run inside the keepalive task" in str(errors[0])
    await link.kernel.close()
    assert link.stats.probe_in_flight is False


def _queue_tracked_requests(link: KeepaliveLink) -> tuple[int, int]:
    """Queue a confirmed fire-and-forget request and one still awaiting its reply."""
    kernel = link.kernel
    sent_seq = kernel.next_seq()
    kernel.register_sent_event(sent_seq, asyncio.Event())
    kernel.send_request_with_seq(
        sent_seq,
        "system",
        "r_u_alive",
        {},
        pending=False,
        opaque=None,
        expected_route=None,
        expects_reply=False,
    )
    link.session.confirm(len(link.session.sent) - 1)
    reply_seq = kernel.next_seq()
    kernel.send_request_with_seq(
        reply_seq,
        "system",
        "r_u_alive",
        {},
        pending=True,
        opaque=None,
        expected_route=("system", "r_u_alive"),
        expects_reply=False,
    )
    assert kernel.was_request_sent(sent_seq)
    assert kernel.dispatcher.pending_count() == 1
    return sent_seq, reply_seq


@pytest.mark.asyncio
async def test_failed_reconnect_keeps_the_old_sessions_request_tracking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    link = keepalive_link(monkeypatch)
    old = await link.connect()
    sent_seq, reply_seq = _queue_tracked_requests(link)
    link.fail_connect = True
    with pytest.raises(KernelError, match="Session connect failed"):
        await link.connect()
    assert link.kernel.was_request_sent(sent_seq)
    assert link.kernel.dispatcher.pending_count() == 1
    old.receive({"seq": reply_seq, "system": {"r_u_alive": {}}})
    assert link.kernel.dispatcher.pending_count() == 0
    await link.kernel.close()


@pytest.mark.asyncio
async def test_successful_reconnect_drops_the_old_sessions_request_tracking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    link = keepalive_link(monkeypatch)
    await link.connect()
    sent_seq, _reply_seq = _queue_tracked_requests(link)
    await link.connect()
    assert not link.kernel.was_request_sent(sent_seq)
    assert link.kernel.dispatcher.pending_count() == 0
    await link.kernel.close()


@pytest.mark.asyncio
async def test_refused_connect_inside_the_keepalive_task_keeps_request_tracking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    holder: list[Any] = []
    errors: list[KernelError] = []

    async def _sleep(delay: float) -> None:
        if delay < IDLE_INTERVAL_S / 2 and not errors:
            try:
                await holder[0].connect()
            except KernelError as exc:
                errors.append(exc)
        await asyncio.Event().wait()

    link = keepalive_link(monkeypatch, sleep=_sleep)
    holder.append(link)
    session = await link.connect()
    sent_seq, _reply_seq = _queue_tracked_requests(link)
    feature_loads: list[object] = []
    monkeypatch.setattr(link.kernel, "load_features_blocking", feature_loads.append)
    session.state = session_mod.SessionState.DISCONNECTED
    link.kernel.request_link_check()
    await until(lambda: bool(errors))
    assert feature_loads == []
    assert link.kernel.was_request_sent(sent_seq)
    assert link.kernel.dispatcher.pending_count() == 1
    await link.kernel.close()


@pytest.mark.asyncio
async def test_misses_before_a_failed_reconnect_still_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    link = keepalive_link(monkeypatch)
    old = await link.connect(max_missed=2)
    await link.check_link()
    old.confirm(0)
    link.advance(TIMEOUT_S + 0.01)
    await until(lambda: link.stats.consecutive_missed == 1 and len(old.sent) >= 2)
    link.fail_connect = True
    with pytest.raises(KernelError, match="Session connect failed"):
        await link.connect(max_missed=2)
    assert link.stats.consecutive_missed == 1
    assert old.disconnects == []
    link.kernel.request_link_check()
    await until(lambda: len(old.sent) >= 3)
    old.confirm(2)
    link.advance(TIMEOUT_S + 0.01)
    await until(lambda: len(old.disconnects) == 1)
    assert link.stats.consecutive_missed == 2
    await link.kernel.close()


@pytest.mark.asyncio
async def test_cancelled_reconnect_keeps_the_cancel_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    link = keepalive_link(monkeypatch)
    await link.connect()
    await link.check_link()
    seen: list[str] = []

    async def _reconnect() -> None:
        try:
            await link.connect()
        except asyncio.CancelledError as exc:
            seen.append(str(exc))
            raise

    connecting = asyncio.create_task(_reconnect())
    await until(lambda: len(link.links) == 2)
    connecting.cancel("operator stop")
    with pytest.raises(asyncio.CancelledError):
        await connecting
    assert not link.links[1].handshake_entered.is_set()
    assert seen == ["operator stop"]
    await link.kernel.close()


@pytest.mark.asyncio
async def test_successful_reconnect_starts_the_miss_count_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    link = keepalive_link(monkeypatch)
    old = await link.connect(max_missed=2)
    await link.check_link()
    old.confirm(0)
    link.advance(TIMEOUT_S + 0.01)
    await until(lambda: link.stats.consecutive_missed == 1 and len(old.sent) >= 2)
    await link.connect(max_missed=2)
    assert link.stats.consecutive_missed == 0
    await link.kernel.close()


@pytest.mark.asyncio
async def test_close_starts_the_miss_count_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    link = keepalive_link(monkeypatch)
    old = await link.connect(max_missed=2)
    await link.check_link()
    old.confirm(0)
    link.advance(TIMEOUT_S + 0.01)
    await until(lambda: link.stats.consecutive_missed == 1 and len(old.sent) >= 2)
    await link.kernel.close()
    assert link.stats.consecutive_missed == 0
    assert link.stats.misses == 1


async def _finishes_within(task: asyncio.Task[Any], timeout_s: float = 2.0) -> bool:
    """Wait for ``task``; on timeout cancel every other task so the test fails instead of hanging."""
    await asyncio.wait({task}, timeout=timeout_s)
    if task.done():
        return True
    for other in asyncio.all_tasks():
        if other is not asyncio.current_task() and other is not task:
            other.cancel()
    await asyncio.wait({task}, timeout=timeout_s)
    task.cancel()
    return False


@pytest.mark.asyncio
@pytest.mark.parametrize("yields", [0, 1, 2, 3])
async def test_close_right_after_a_write_confirmation_returns(
    monkeypatch: pytest.MonkeyPatch, yields: int
) -> None:
    link = keepalive_link(monkeypatch)
    old = await link.connect()
    await link.check_link()
    old.confirm(0)
    for _ in range(yields):
        await asyncio.sleep(0)
    closing = asyncio.create_task(link.kernel.close())
    assert await _finishes_within(closing)
    assert link.stats.probe_in_flight is False
    assert old.cancelled == [old.seq(0)]
    link.advance(TIMEOUT_S + 0.01)
    for _ in range(5):
        await asyncio.sleep(0)
    assert link.stats.misses == 0
    assert link.stats.consecutive_missed == 0


@pytest.mark.asyncio
async def test_cancelled_reconnect_waits_for_a_slow_stopping_loop_before_restarting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active = [0]
    peak = [0]
    release = asyncio.Event()

    async def _sleep(_delay: float) -> None:
        active[0] += 1
        peak[0] = max(peak[0], active[0])
        try:
            await asyncio.Event().wait()
        finally:
            await release.wait()
            active[0] -= 1

    link = keepalive_link(monkeypatch, sleep=_sleep)
    old = await link.connect()
    old.state = session_mod.SessionState.DISCONNECTED
    release.set()
    link.kernel.request_link_check()
    await until(lambda: active[0] == 1)
    release.clear()
    peak[0] = 1

    async def _reconnect_cancelled_while_stopping() -> None:
        connecting = asyncio.create_task(link.connect())
        try:
            await until(lambda: len(link.links) == 2)
            connecting.cancel()
            for _ in range(20):
                await asyncio.sleep(0)
            assert peak[0] == 1
            assert not connecting.done()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await connecting
        assert not link.links[1].handshake_entered.is_set()
        await until(lambda: active[0] == 1)
        assert peak[0] == 1
        await link.kernel.close()

    scenario = asyncio.create_task(_reconnect_cancelled_while_stopping())
    finished = await _finishes_within(scenario)
    release.set()
    assert finished
    scenario.result()
