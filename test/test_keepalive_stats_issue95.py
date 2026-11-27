"""Keepalive stats semantics from Architect note on #95, through the public API.

Each kernel is connected to a fake panel link with ``E27Kernel.connect``, probes
are started with ``request_link_check`` and outcomes come from ``keepalive_stats``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

import pytest

from elke27_lib import session_thread as session_mod
from elke27_lib.kernel_loop import KernelError
from test.helpers.keepalive_link import (
    TIMEOUT_S,
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
    assert session.disconnects == []
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
    assert session.disconnects == []
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
    assert session.disconnects == []
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
    await until(lambda: link.stats.probe_in_flight is False)
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
    assert link.stats.probes_sent == 0
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
    assert session.disconnects == []
    await link.kernel.close()
