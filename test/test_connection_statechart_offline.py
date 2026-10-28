"""Offline connection statechart keepalive cases O10-O15 (#79).

Maps to TLC Keepalive configs KA_A-KA_E (plan sections 3a-3e). Scenarios run in
``test.helpers.keepalive_seam`` using injectable keepalive hooks on ``E27Kernel``.
"""

from __future__ import annotations

import pytest

from test.helpers import keepalive_seam


@pytest.mark.asyncio
async def test_o10_keepalive_reply_before_timeout() -> None:
    """O10: reply D < T, quiet link, M=1 -> no disconnect; missed returns to 0."""
    await keepalive_seam.run_o10()


@pytest.mark.asyncio
async def test_o11_keepalive_tie() -> None:
    """O11: D = T tie -> timeout wins (documented miss, no disconnect at probe layer)."""
    await keepalive_seam.run_o11()


@pytest.mark.asyncio
async def test_o12_keepalive_one_miss_disconnects() -> None:
    """O12: D > T, M=1 -> disconnect after one miss."""
    await keepalive_seam.run_o12()


@pytest.mark.asyncio
async def test_o13_keepalive_two_misses_before_disconnect() -> None:
    """O13: D > T, M=2 -> disconnect only after two misses."""
    await keepalive_seam.run_o13()


@pytest.mark.asyncio
async def test_o14_keepalive_traffic_rescue() -> None:
    """O14: D > T with inbound traffic after the probe -> no disconnect."""
    await keepalive_seam.run_o14()


@pytest.mark.asyncio
async def test_o15_keepalive_task_cleared_after_expiry() -> None:
    """O15: after expiry the keepalive task is done before the next start (no double loop)."""
    await keepalive_seam.run_o15()
