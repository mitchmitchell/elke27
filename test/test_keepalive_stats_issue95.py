"""Keepalive stats semantics from Architect note on #95."""

from __future__ import annotations

import pytest

from test.helpers import keepalive_stats_semantics as semantics


@pytest.mark.asyncio
async def test_unsent_probe_send_error_counts_failed_not_sent() -> None:
    await semantics.run_unsent_send_error()


@pytest.mark.asyncio
async def test_unsent_probe_send_wait_timeout_counts_failed_not_sent() -> None:
    await semantics.run_unsent_send_wait_timeout()


@pytest.mark.asyncio
async def test_unsent_probe_abort_counts_failed_not_sent() -> None:
    await semantics.run_unsent_abort()


@pytest.mark.asyncio
async def test_immediate_reply_uses_confirmed_send_time_not_now() -> None:
    await semantics.run_immediate_reply_rtt()


@pytest.mark.asyncio
async def test_unsent_probe_and_unrelated_inbound_does_not_count_reply_or_rtt() -> None:
    await semantics.run_unsent_unrelated_inbound()


@pytest.mark.asyncio
async def test_stale_reply_does_not_update_newer_outstanding_probe() -> None:
    await semantics.run_stale_reply_while_newer_outstanding()


@pytest.mark.asyncio
async def test_unanswered_probe_probe_timeout_and_rescued() -> None:
    await semantics.run_probe_timeout_and_rescued()


@pytest.mark.asyncio
async def test_large_clock_offset_reports_non_negative_rtt_without_clamp() -> None:
    await semantics.run_large_clock_offset_rtt()
