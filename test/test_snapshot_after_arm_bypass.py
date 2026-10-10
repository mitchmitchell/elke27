"""Regression for issue #15: snapshot must track panel after arm/bypass."""

from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest

from elke27_lib.client import ArmMode, Elke27Client
from elke27_lib.const import E27ErrorCode
from test.helpers.fake_panel_replies import synthetic_success_reply
from test.helpers.internal import get_kernel, get_private
from test.test_panel_errors_ready_night import _FakeSession, _make_client


async def _drive_until_done(
    client: Elke27Client,
    session: _FakeSession,
    call: Any,
    *,
    first_reply: dict[str, Any] | None = None,
) -> None:
    task = asyncio.ensure_future(call)
    on_message = get_private(get_kernel(client), "_on_message")
    seen = 0
    cast(Any, client)._connected = True
    client._event_loop = asyncio.get_running_loop()
    while not task.done():
        await asyncio.sleep(0)
        while seen < len(session.sent):
            sent = session.sent[seen]
            if seen == 0 and first_reply is not None:
                reply = dict(first_reply)
                reply["seq"] = sent["seq"]
                on_message(reply)
            else:
                on_message(synthetic_success_reply(sent, sent_history=session.sent[:seen]))
            seen += 1
    await task


@pytest.mark.asyncio
async def test_arm_ack_only_then_get_status_updates_snapshot() -> None:
    client, session = _make_client()
    kernel = get_kernel(client)
    area = kernel.state.get_or_create_area(1)
    area.arm_state = "DISARMED"

    await _drive_until_done(
        client,
        session,
        client.async_arm_area(1, mode=ArmMode.ARMED_AWAY, pin="1234"),
        first_reply={
            "seq": 0,
            "area": {"set_arm_state": {"area_id": 1, "error_code": E27ErrorCode.ELKERR_NONE}},
        },
    )

    assert len(session.sent) == 2
    assert "get_status" in session.sent[1]["area"]
    assert client.snapshot.areas[1].arm_mode == ArmMode.ARMED_AWAY


@pytest.mark.asyncio
async def test_zone_bypass_ack_only_then_get_status_updates_snapshot() -> None:
    client, session = _make_client()
    kernel = get_kernel(client)
    zone = kernel.state.get_or_create_zone(17)
    zone.area_id = 1
    zone.bypassed = False

    await _drive_until_done(
        client,
        session,
        client.async_set_zone_bypass(17, bypassed=True, pin="1234"),
        first_reply={
            "seq": 0,
            "zone": {"set_status": {"zone_id": 17, "error_code": E27ErrorCode.ELKERR_NONE}},
        },
    )

    assert len(session.sent) == 2
    assert "get_status" in session.sent[1]["zone"]
    assert client.snapshot.zones[17].bypassed is True


@pytest.mark.asyncio
async def test_set_arm_state_reply_with_arm_state_updates_before_refresh() -> None:
    client, session = _make_client()
    kernel = get_kernel(client)
    kernel.state.get_or_create_area(1).arm_state = "DISARMED"

    await _drive_until_done(
        client,
        session,
        client.async_arm_area(1, mode=ArmMode.ARMED_STAY, pin="1234"),
        first_reply={
            "seq": 0,
            "area": {
                "set_arm_state": {
                    "area_id": 1,
                    "error_code": E27ErrorCode.ELKERR_NONE,
                    "arm_state": "ARMED_STAY",
                }
            },
        },
    )

    assert client.snapshot.areas[1].arm_mode == ArmMode.ARMED_STAY
