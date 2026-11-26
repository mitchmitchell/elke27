"""Decision 55 probe for #158: a probe that fails before it has a seq."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from elke27_lib.kernel_loop import KernelError
from test.helpers import keepalive_seam


@pytest.mark.asyncio
async def test_probe_builder_error_does_not_wedge_the_next_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seam, kernel, session = keepalive_seam.stats_probing_seam()

    def _raise(*_a: Any, **_k: Any) -> None:
        raise KernelError("no builder")

    monkeypatch.setattr(kernel.requests, "require", _raise)
    with pytest.raises(KernelError, match="no builder"):
        await keepalive_seam.send_keepalive(kernel, force=True)
    assert session.sent == []
    assert kernel.keepalive_stats.probes_failed == 0
    monkeypatch.undo()
    task = asyncio.create_task(keepalive_seam.send_keepalive(kernel, force=True))
    await keepalive_seam.until_probe_sent(session)
    keepalive_seam.confirm_probe_sent_and_maybe_reply(seam, session, 0, reply_after_s=0.1)
    assert await asyncio.wait_for(task, timeout=2.0) is True
    assert kernel.keepalive_stats.probes_sent == 1
    assert kernel.keepalive_stats.last_round_trip_s == pytest.approx(0.1)
