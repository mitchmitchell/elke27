"""Decision 55 probe for #158: a probe that fails before it has a seq."""

from __future__ import annotations

import pytest

from elke27_lib.kernel_loop import KernelError
from test.helpers.keepalive_link import keepalive_link, until


@pytest.mark.asyncio
async def test_probe_builder_error_does_not_wedge_the_next_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []

    def _builder() -> dict[str, object]:
        calls.append(1)
        if len(calls) == 1:
            raise KernelError("no builder")
        return {}

    link = keepalive_link(monkeypatch, probe_builder=_builder)
    session = await link.connect()
    link.kernel.request_link_check()
    await until(lambda: len(calls) == 1)
    assert session.sent == []
    assert link.stats.probes_failed == 0
    assert link.stats.probes_in_flight == 0
    second = await link.connect()
    await link.check_link()
    second.confirm(0)
    link.advance(0.1)
    second.reply(0)
    await until(lambda: link.stats.replies == 1)
    stats = link.stats
    assert stats.probes_sent == 1
    assert stats.last_round_trip_s == pytest.approx(0.1)
    assert stats.probes_in_flight == 0
    await link.kernel.close()
