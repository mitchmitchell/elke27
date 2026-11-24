"""Keepalive stats semantics from Architect note on #95."""

from __future__ import annotations

import pytest

from test.helpers import keepalive_seam


@pytest.mark.asyncio
async def test_unsent_probe_send_error_counts_failed_not_sent() -> None:
    await keepalive_seam.run_unsent_send_error()


@pytest.mark.asyncio
async def test_unsent_probe_send_wait_timeout_counts_failed_not_sent() -> None:
    await keepalive_seam.run_unsent_send_wait_timeout()


@pytest.mark.asyncio
async def test_unsent_probe_abort_counts_failed_not_sent() -> None:
    await keepalive_seam.run_unsent_abort()


@pytest.mark.asyncio
async def test_immediate_reply_uses_confirmed_send_time_not_now() -> None:
    await keepalive_seam.run_immediate_reply_rtt()


@pytest.mark.asyncio
async def test_unsent_probe_and_unrelated_inbound_does_not_count_reply_or_rtt() -> None:
    await keepalive_seam.run_unsent_unrelated_inbound()


@pytest.mark.asyncio
async def test_stale_reply_does_not_update_newer_outstanding_probe() -> None:
    await keepalive_seam.run_stale_reply_while_newer_outstanding()


@pytest.mark.asyncio
async def test_unanswered_probe_probe_timeout_and_rescued() -> None:
    await keepalive_seam.run_probe_timeout_and_rescued()


@pytest.mark.asyncio
async def test_large_clock_offset_reports_non_negative_rtt_without_clamp() -> None:
    await keepalive_seam.run_large_clock_offset_rtt()


@pytest.mark.asyncio
async def test_non_keepalive_tracked_request_leaves_no_probe_sent_entry() -> None:
    await keepalive_seam.run_non_keepalive_tracked_request_leaves_no_probe_sent_entry()


@pytest.mark.asyncio
async def test_probe_cancelled_at_await_future_leaves_no_entry() -> None:
    await keepalive_seam.run_probe_cancelled_at_await_future_leaves_no_entry()


@pytest.mark.asyncio
async def test_late_on_sent_after_abandon_leaves_no_entry() -> None:
    await keepalive_seam.run_late_on_sent_after_abandon_leaves_no_entry()


@pytest.mark.asyncio
async def test_reused_seq_not_stale_rtt_after_session_reset() -> None:
    await keepalive_seam.run_reused_seq_not_stale_rtt_after_session_reset()


@pytest.mark.asyncio
async def test_write_confirmed_after_send_state_reset_measures_rtt() -> None:
    await keepalive_seam.run_write_confirmed_after_send_state_reset_measures_rtt()
