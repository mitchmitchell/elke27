"""A write confirmation from a replaced session must not touch the new session's reply deadline (#179).

Runs the real ``E27Kernel`` on the public-path ``keepalive_link`` harness: the
kernel is connected through ``E27Kernel.connect`` and commands are sent through
``E27Kernel.request``. Outcomes are read from the frames each link received and
from ``dispatcher.pending_count()``.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from test.helpers.keepalive_link import KeepaliveLink, PanelLink, keepalive_link, until

ROUTE = ("area", "get_status")
REPLY_TIMEOUT_S = 0.3
GUARD_S = 3.0


def _command_link(monkeypatch: pytest.MonkeyPatch) -> KeepaliveLink:
    link = keepalive_link(
        monkeypatch,
        kernel_options={"request_timeout_s": REPLY_TIMEOUT_S, "request_max_retries": 0},
    )
    link.kernel.requests.register(ROUTE, dict)
    return link


async def _command_written(link: KeepaliveLink, on: PanelLink, count: int) -> int:
    seq = link.kernel.request(ROUTE)
    await until(lambda: len(on.sent) >= count)
    return seq


async def _replaced_with_old_frame_unconfirmed(
    link: KeepaliveLink,
) -> tuple[PanelLink, PanelLink, int]:
    old = await link.connect()
    old_seq = await _command_written(link, old, 1)
    old.drop()
    new = await link.connect()
    return old, new, old_seq


async def _settles(cond: Callable[[], bool]) -> bool:
    try:
        await until(cond, timeout_s=GUARD_S)
    except AssertionError:
        return False
    return True


@pytest.mark.asyncio
async def test_late_confirmation_from_the_old_link_leaves_the_new_commands_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    link = _command_link(monkeypatch)
    old, new, old_seq = await _replaced_with_old_frame_unconfirmed(link)
    link.kernel.request(ROUTE)
    await until(lambda: len(new.sent) >= 1)
    new.confirm(0)
    assert link.kernel.dispatcher.pending_count() == 1
    old.confirm(0)
    assert old.seq(0) == old_seq
    assert await _settles(lambda: link.kernel.dispatcher.pending_count() == 0)
    follow_up = link.kernel.request(ROUTE)
    await until(lambda: len(new.sent) >= 2)
    assert new.seq(1) == follow_up
    await link.kernel.close()


@pytest.mark.asyncio
async def test_late_confirmation_of_an_answered_command_leaves_the_next_commands_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    link = _command_link(monkeypatch)
    session = await link.connect()
    first = await _command_written(link, session, 1)
    session.receive({"seq": first, "area": {"get_status": {}}})
    assert link.kernel.dispatcher.pending_count() == 0
    link.kernel.request(ROUTE)
    await until(lambda: len(session.sent) >= 2)
    session.confirm(1)
    assert link.kernel.dispatcher.pending_count() == 1
    session.confirm(0)
    assert await _settles(lambda: link.kernel.dispatcher.pending_count() == 0)
    await link.kernel.close()


@pytest.mark.asyncio
async def test_confirmation_from_the_current_link_still_times_the_command_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    link = _command_link(monkeypatch)
    new = await link.connect()
    await _command_written(link, new, 1)
    new.confirm(0)
    assert link.kernel.dispatcher.pending_count() == 1
    assert await _settles(lambda: link.kernel.dispatcher.pending_count() == 0)
    await link.kernel.close()


@pytest.mark.asyncio
async def test_late_confirmation_from_the_old_link_does_not_mark_an_unwritten_probe_as_written(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    link = keepalive_link(monkeypatch, send_wait_s=0.3)
    old = await link.connect()
    link.kernel.requests.register(ROUTE, dict)
    await _command_written(link, old, 1)
    old.drop()
    new = await link.connect()
    await link.check_link()
    old.confirm(0)
    assert await _settles(lambda: link.stats.probes_failed == 1)
    assert new.cancelled == [new.seq(0)]
    await link.kernel.close()


@pytest.mark.asyncio
async def test_unanswered_written_command_triggers_a_link_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    link = _command_link(monkeypatch)
    session = await link.connect()
    await _command_written(link, session, 1)
    session.confirm(0)
    assert await _settles(lambda: len(session.sent) >= 2)
    probe = session.sent[1][0]
    assert "r_u_alive" in str(probe)
    await link.kernel.close()
