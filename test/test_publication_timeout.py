"""A publication-wait timeout is an error, never a successful read (#147).

Drives ``Elke27Client`` through ``FakePanelSession`` with the public API only.
The client's snapshot publication runs in callbacks the kernel schedules with
``loop.call_soon_threadsafe``; holding the ones bound to the client keeps the
reply out of ``get_snapshot()`` past the command deadline, as a busy loop would.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

import pytest

from elke27_lib import ArmMode, Elke27CommandOutcomeUnknownError, Elke27SnapshotPublicationError
from elke27_lib.client import Elke27Client
from elke27_lib.const import E27ErrorCode
from elke27_lib.kernel_loop import E27Kernel
from test.helpers.fake_session import FakePanelSession, connect_with_fake_panel
from test.helpers.panel_command_driver import seed_application_firmware, seed_area_disarmed

COMMAND_TIMEOUT_S = 0.5
_PUBLICATION_TIMEOUT_LOG = "Timed out waiting for reply seq="


class _HeldPublication:
    """Holds client-bound cross-thread callbacks until ``release``."""

    def __init__(self, client: Elke27Client, loop: asyncio.AbstractEventLoop) -> None:
        self._client = client
        self._real = loop.call_soon_threadsafe
        self.held: list[tuple[Callable[..., Any], tuple[Any, ...]]] = []

    def __call__(self, fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any:
        if getattr(fn, "__self__", None) is self._client:
            self.held.append((fn, args))
            return None
        return self._real(fn, *args, **kwargs)

    def release(self) -> None:
        while self.held:
            fn, args = self.held.pop(0)
            fn(*args)


async def _connect(
    monkeypatch: pytest.MonkeyPatch,
    kernel: E27Kernel | None = None,
    client: Elke27Client | None = None,
) -> tuple[Elke27Client, FakePanelSession]:
    if kernel is None:
        kernel = E27Kernel(
            skip_connect_bootstrap=True,
            request_max_retries=0,
            request_timeout_s=COMMAND_TIMEOUT_S,
        )
    if client is None:
        client = Elke27Client(kernel=kernel)
    panel = await connect_with_fake_panel(monkeypatch, client)
    await seed_area_disarmed(panel)
    await asyncio.sleep(0)
    assert client.get_snapshot().areas[1].arm_mode is ArmMode.DISARMED
    return client, panel


async def _next_sent(panel: FakePanelSession, count: int) -> dict[str, Any]:
    async with asyncio.timeout(2.0):
        while len(panel.sent) < count:
            await asyncio.sleep(0.005)
    return dict(panel.sent[count - 1])


def _armed_away_status(seq: object) -> dict[str, Any]:
    return {
        "seq": seq,
        "area": {
            "get_status": {
                "area_id": 1,
                "arm_state": "ARMED_AWAY",
                "error_code": E27ErrorCode.ELKERR_NONE,
            }
        },
    }


@pytest.mark.asyncio
async def test_status_read_publication_timeout_returns_error_not_stale_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, panel = await _connect(monkeypatch)
    loop = asyncio.get_running_loop()
    hold = _HeldPublication(client, loop)
    monkeypatch.setattr(loop, "call_soon_threadsafe", hold)
    sent_before = len(panel.sent)

    task = asyncio.create_task(
        client.async_execute("area_get_status", area_id=1, timeout_s=COMMAND_TIMEOUT_S)
    )
    sent = await _next_sent(panel, sent_before + 1)
    await panel.deliver(_armed_away_status(sent["seq"]))
    async with asyncio.timeout(COMMAND_TIMEOUT_S + 2.0):
        result = await task

    assert client.get_snapshot().areas[1].arm_mode is ArmMode.DISARMED
    assert result.ok is False
    assert isinstance(result.error, Elke27SnapshotPublicationError)

    monkeypatch.undo()
    hold.release()
    assert client.get_snapshot().areas[1].arm_mode is ArmMode.ARMED_AWAY


@pytest.mark.asyncio
async def test_ack_only_write_reports_failed_refresh_when_publication_times_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, panel = await _connect(monkeypatch)
    loop = asyncio.get_running_loop()
    hold = _HeldPublication(client, loop)
    monkeypatch.setattr(loop, "call_soon_threadsafe", hold)
    sent_before = len(panel.sent)

    task = asyncio.create_task(
        client.async_execute(
            "area_set_arm_state",
            area_id=1,
            arm_state="ARMED_AWAY",
            pin=1234,
            timeout_s=COMMAND_TIMEOUT_S,
        )
    )
    write = await _next_sent(panel, sent_before + 1)
    await panel.deliver(
        {
            "seq": write["seq"],
            "area": {"set_arm_state": {"area_id": 1, "error_code": E27ErrorCode.ELKERR_NONE}},
        }
    )
    refresh = await _next_sent(panel, sent_before + 2)
    assert "get_status" in refresh["area"]
    await panel.deliver(_armed_away_status(refresh["seq"]))
    async with asyncio.timeout(COMMAND_TIMEOUT_S + 2.0):
        result = await task

    assert client.get_snapshot().areas[1].arm_mode is ArmMode.DISARMED
    assert result.ok is True
    assert result.status_refresh_ok is False
    assert 1 in client.get_snapshot().stale_area_ids


def _set_arm_reply(seq: object, arm_state: str) -> dict[str, Any]:
    return {
        "seq": seq,
        "area": {
            "set_arm_state": {
                "area_id": 1,
                "arm_state": arm_state,
                "error_code": E27ErrorCode.ELKERR_NONE,
            }
        },
    }


async def _hold_and_reply(
    client: Elke27Client,
    panel: FakePanelSession,
    monkeypatch: pytest.MonkeyPatch,
    call: Any,
    reply_for: Callable[[object], dict[str, Any]],
) -> asyncio.Task[Any]:
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "call_soon_threadsafe", _HeldPublication(client, loop))
    sent_before = len(panel.sent)
    task = asyncio.ensure_future(call)
    sent = await _next_sent(panel, sent_before + 1)
    await panel.deliver(reply_for(sent["seq"]))
    return task


@pytest.mark.asyncio
async def test_confirmed_disarm_publication_timeout_is_accepted_with_failed_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, panel = await _connect(monkeypatch)
    await panel.deliver(_armed_away_status(0))
    await asyncio.sleep(0)
    assert client.get_snapshot().areas[1].arm_mode is ArmMode.ARMED_AWAY

    task = await _hold_and_reply(
        client,
        panel,
        monkeypatch,
        client.async_disarm_area(1, pin=1234, return_result=True),
        lambda seq: _set_arm_reply(seq, "DISARMED"),
    )
    async with asyncio.timeout(COMMAND_TIMEOUT_S + 2.0):
        result = await task

    assert result.status_refresh_ok is False
    assert client.get_snapshot().areas[1].arm_mode is ArmMode.ARMED_AWAY
    assert 1 in client.get_snapshot().stale_area_ids


@pytest.mark.asyncio
async def test_confirmed_bypass_publication_timeout_is_accepted_with_failed_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``async_set_zone_bypass`` fixes its timeout at 15 s, so the transport budget
    is shortened to keep the publication deadline at ``COMMAND_TIMEOUT_S``."""
    kernel = E27Kernel(skip_connect_bootstrap=True, request_max_retries=0)
    client, panel = await _connect(monkeypatch, kernel)
    monkeypatch.setattr(kernel, "command_transport_wait_budget_s", lambda _: COMMAND_TIMEOUT_S)
    await panel.deliver(
        {
            "seq": 0,
            "zone": {
                "get_status": {
                    "zone_id": 1,
                    "BYPASSED": False,
                    "error_code": E27ErrorCode.ELKERR_NONE,
                }
            },
        }
    )
    await asyncio.sleep(0)
    assert client.get_snapshot().zones[1].bypassed is False

    task = await _hold_and_reply(
        client,
        panel,
        monkeypatch,
        client.async_set_zone_bypass(1, bypassed=True, pin=1234, return_result=True),
        lambda seq: {
            "seq": seq,
            "zone": {
                "set_status": {
                    "zone_id": 1,
                    "BYPASSED": True,
                    "error_code": E27ErrorCode.ELKERR_NONE,
                }
            },
        },
    )
    async with asyncio.timeout(COMMAND_TIMEOUT_S + 2.0):
        result = await task

    assert result.status_refresh_ok is False
    assert client.get_snapshot().zones[1].bypassed is False
    assert 1 in client.get_snapshot().stale_zone_ids


@pytest.mark.asyncio
async def test_confirmed_night_arm_publication_timeout_raises_outcome_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, panel = await _connect(monkeypatch)
    await seed_application_firmware(panel, 1317)
    await asyncio.sleep(0)

    task = await _hold_and_reply(
        client,
        panel,
        monkeypatch,
        client.async_arm_area(1, mode=ArmMode.ARMED_NIGHT, pin=1234),
        lambda seq: _set_arm_reply(seq, "ARMED_STAY_INST"),
    )
    with pytest.raises(Elke27CommandOutcomeUnknownError):
        async with asyncio.timeout(COMMAND_TIMEOUT_S + 2.0):
            await task
    assert 1 in client.get_snapshot().stale_area_ids


@pytest.mark.asyncio
async def test_ack_only_refresh_fails_from_publication_deadline_before_its_time_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The follow-up read's publication deadline (0.3 s) ends well before the
    refresh's own time cap (about 1.8 s), so the failed refresh must come from the
    publication wait, not from the cap.

    ``command_transport_wait_budget_s`` keeps the 2.0 s write budget and gives any
    shorter request (the follow-up read, sent at least 0.2 s later) 0.3 s.
    """
    kernel = E27Kernel(skip_connect_bootstrap=True, request_max_retries=0)
    client, panel = await _connect(monkeypatch, kernel)
    write_timeout_s = 2.0
    nested_budget_s = 0.3
    monkeypatch.setattr(
        kernel,
        "command_transport_wait_budget_s",
        lambda timeout_s: timeout_s if timeout_s >= write_timeout_s - 0.05 else nested_budget_s,
    )
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "call_soon_threadsafe", _HeldPublication(client, loop))
    sent_before = len(panel.sent)

    task = asyncio.create_task(
        client.async_execute(
            "area_set_arm_state",
            area_id=1,
            arm_state="ARMED_AWAY",
            pin=1234,
            timeout_s=write_timeout_s,
        )
    )
    write = await _next_sent(panel, sent_before + 1)
    await asyncio.sleep(0.2)
    await panel.deliver(
        {
            "seq": write["seq"],
            "area": {"set_arm_state": {"area_id": 1, "error_code": E27ErrorCode.ELKERR_NONE}},
        }
    )
    refresh = await _next_sent(panel, sent_before + 2)
    refresh_sent_at = time.monotonic()
    await panel.deliver(_armed_away_status(refresh["seq"]))
    async with asyncio.timeout(write_timeout_s + 2.0):
        result = await task
    finished_after_s = time.monotonic() - refresh_sent_at

    assert result.ok is True
    assert result.status_refresh_ok is False
    assert 1 in client.get_snapshot().stale_area_ids
    assert finished_after_s < 1.2


class _UnregisteredPublicationClient(Elke27Client):
    """Leave the publication slot unregistered so the wait takes the no-future path."""

    def _begin_reply_publication_command(
        self,
        reply_seq: int,
        expected_route: tuple[str, str] | None,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        del reply_seq, expected_route, loop


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "arm_state"),
    (
        (ArmMode.ARMED_AWAY, "ARMED_AWAY"),
        (ArmMode.ARMED_STAY, "ARMED_STAY"),
    ),
    ids=("away", "stay"),
)
async def test_confirmed_away_or_stay_arm_publication_timeout_is_accepted_with_failed_refresh(
    mode: ArmMode,
    arm_state: str,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A confirmed Away or Stay arm that misses publication is a failed refresh.

    ``async_arm_area`` returns ``CommandResult`` (the write was accepted, same as
    ``ok=True`` on ``async_execute``) and does not raise.
    """
    client, panel = await _connect(monkeypatch)
    caplog.set_level(logging.WARNING, logger="elke27_lib.client")

    task = await _hold_and_reply(
        client,
        panel,
        monkeypatch,
        client.async_arm_area(1, mode=mode, pin=1234, return_result=True),
        lambda seq, state=arm_state: _set_arm_reply(seq, state),
    )
    async with asyncio.timeout(COMMAND_TIMEOUT_S + 2.0):
        result = await task

    assert result.status_refresh_ok is False
    assert client.get_snapshot().areas[1].arm_mode is ArmMode.DISARMED
    assert 1 in client.get_snapshot().stale_area_ids
    assert any(_PUBLICATION_TIMEOUT_LOG in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_reply_publication_wait_times_out_when_deadline_already_passed(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the command deadline has already passed when the wait starts, return False.

    The first ``command_transport_wait_budget_s`` call sets the publication
    deadline to now; later calls keep a real budget so the reply can still
    arrive. Holding publication leaves the future pending, so the wait takes
    the ``remaining <= 0`` path instead of ``fut.done()``.
    """
    kernel = E27Kernel(
        skip_connect_bootstrap=True,
        request_max_retries=0,
        request_timeout_s=COMMAND_TIMEOUT_S,
    )
    client, panel = await _connect(monkeypatch, kernel)
    budgets = iter((0.0,))

    def budget_s(_timeout_s: float) -> float:
        try:
            return next(budgets)
        except StopIteration:
            return COMMAND_TIMEOUT_S

    monkeypatch.setattr(kernel, "command_transport_wait_budget_s", budget_s)
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "call_soon_threadsafe", _HeldPublication(client, loop))
    caplog.set_level(logging.WARNING, logger="elke27_lib.client")
    sent_before = len(panel.sent)
    started_at = time.monotonic()

    task = asyncio.create_task(
        client.async_execute("area_get_status", area_id=1, timeout_s=COMMAND_TIMEOUT_S)
    )
    sent = await _next_sent(panel, sent_before + 1)
    await panel.deliver(_armed_away_status(sent["seq"]))
    async with asyncio.timeout(COMMAND_TIMEOUT_S + 2.0):
        result = await task
    finished_after_s = time.monotonic() - started_at

    assert result.ok is False
    assert isinstance(result.error, Elke27SnapshotPublicationError)
    assert any(_PUBLICATION_TIMEOUT_LOG in rec.message for rec in caplog.records)
    assert finished_after_s < 0.4


@pytest.mark.asyncio
async def test_reply_publication_wait_succeeds_when_no_future_is_registered(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing publication future is treated as already published (returns True)."""
    kernel = E27Kernel(
        skip_connect_bootstrap=True,
        request_max_retries=0,
        request_timeout_s=COMMAND_TIMEOUT_S,
    )
    client = _UnregisteredPublicationClient(kernel=kernel)
    client, panel = await _connect(monkeypatch, kernel, client)
    caplog.set_level(logging.WARNING, logger="elke27_lib.client")
    sent_before = len(panel.sent)
    started_at = time.monotonic()

    task = asyncio.create_task(
        client.async_execute("area_get_status", area_id=1, timeout_s=COMMAND_TIMEOUT_S)
    )
    sent = await _next_sent(panel, sent_before + 1)
    await panel.deliver(_armed_away_status(sent["seq"]))
    async with asyncio.timeout(COMMAND_TIMEOUT_S + 2.0):
        result = await task
    finished_after_s = time.monotonic() - started_at

    assert result.ok is True
    assert result.error is None
    assert not any(_PUBLICATION_TIMEOUT_LOG in rec.message for rec in caplog.records)
    assert finished_after_s < 0.4
