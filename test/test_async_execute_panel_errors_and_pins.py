"""0.3.11: async_execute panel errors and ASCII-only PIN validation."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any, cast

import pytest

from elke27_lib import Elke27PanelError
from elke27_lib.client import ArmMode, Elke27Client
from elke27_lib.const import E27ErrorCode
from elke27_lib.errors import Elke27InvalidArgument
from test.helpers.internal import get_kernel, get_private


class _FakeSession:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    def send_json(
        self,
        msg: dict[str, Any],
        *,
        priority: object = None,
        on_sent: Callable[[float], None] | None = None,
        on_fail: Callable[[BaseException], None] | None = None,
    ) -> None:
        del priority, on_fail
        self.sent.append(msg)
        if on_sent is not None:
            on_sent(0.0)


def _make_client() -> tuple[Elke27Client, _FakeSession]:
    client = Elke27Client()
    kernel = get_kernel(client)
    session = _FakeSession()
    cast(Any, kernel)._session = session
    kernel.state.panel.session_id = 1
    area = kernel.state.get_or_create_area(1)
    area.arm_state = "disarmed"
    return client, session


async def _run_async_execute(
    client: Elke27Client,
    session: _FakeSession,
    command_key: str,
    *,
    reply_domain: str,
    reply_command: str,
    reply_payload: dict[str, Any],
    **params: Any,
) -> Any:
    task = asyncio.create_task(client.async_execute(command_key, **params))
    for _ in range(20):
        if session.sent or task.done():
            break
        await asyncio.sleep(0)
    if task.done():
        return await task
    sent = session.sent[0]
    on_message = get_private(get_kernel(client), "_on_message")
    on_message({"seq": sent["seq"], reply_domain: {reply_command: reply_payload}})
    return await task


@pytest.mark.asyncio
async def test_async_execute_light_set_status_panel_error_is_public(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, session = _make_client()
    caplog.set_level(logging.WARNING)

    result = await _run_async_execute(
        client,
        session,
        "light_set_status",
        reply_domain="light",
        reply_command="set_status",
        reply_payload={"light_id": 1, "error_code": E27ErrorCode.ELKERR_NOAUTH},
        light_id=1,
        status="ON",
    )

    assert result.ok is False
    assert isinstance(result.error, Elke27PanelError)
    err = result.error
    assert err.panel_error_code == E27ErrorCode.ELKERR_NOAUTH
    assert err.reason == "not authorized"
    assert str(err) == (
        f"Panel rejected the request: not authorized (error {E27ErrorCode.ELKERR_NOAUTH})."
    )
    with pytest.raises(Elke27PanelError):
        result.unwrap()
    assert any(
        "Panel rejected light_set_status" in record.message and "not authorized" in record.message
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_async_execute_paged_panel_error_is_public(caplog: pytest.LogCaptureFixture) -> None:
    client, session = _make_client()
    caplog.set_level(logging.WARNING)

    result = await _run_async_execute(
        client,
        session,
        "zone_get_configured",
        reply_domain="zone",
        reply_command="get_configured",
        reply_payload={"block_id": 1, "block_count": 1, "error_code": E27ErrorCode.ELKERR_NOAUTH},
    )

    assert result.ok is False
    assert isinstance(result.error, Elke27PanelError)
    assert result.error.panel_error_code == E27ErrorCode.ELKERR_NOAUTH
    assert result.error.reason == "not authorized"
    with pytest.raises(Elke27PanelError):
        result.unwrap()
    assert any("Panel rejected zone_get_configured" in record.message for record in caplog.records)


@pytest.mark.parametrize(
    "pin",
    [
        pytest.param("²", id="superscript"),
        pytest.param("١٢٣", id="arabic-indic"),
        pytest.param("１２３４", id="fullwidth"),
    ],
)
@pytest.mark.asyncio
async def test_async_execute_rejects_non_ascii_digit_pin_before_send(pin: str) -> None:
    client, session = _make_client()
    result = await client.async_execute(
        "area_set_arm_state",
        area_id=1,
        arm_state="ARMED_AWAY",
        pin=pin,
    )
    assert result.ok is False
    assert isinstance(result.error, Elke27InvalidArgument)
    assert session.sent == []


@pytest.mark.parametrize(
    "pin",
    [
        pytest.param("²", id="superscript"),
        pytest.param("١٢٣", id="arabic-indic"),
        pytest.param("１２３４", id="fullwidth"),
    ],
)
@pytest.mark.asyncio
async def test_async_execute_zone_set_status_rejects_non_ascii_digit_pin(
    pin: str,
) -> None:
    client, session = _make_client()
    result = await client.async_execute(
        "zone_set_status",
        zone_id=1,
        pin=pin,
        bypassed=True,
    )
    assert result.ok is False
    assert isinstance(result.error, Elke27InvalidArgument)
    assert session.sent == []


@pytest.mark.parametrize(
    ("pin", "action"),
    [
        pytest.param("²", "arm", id="arm-superscript"),
        pytest.param("１２３４", "disarm", id="disarm-fullwidth"),
        pytest.param("²", "bypass", id="bypass-superscript"),
    ],
)
@pytest.mark.asyncio
async def test_v2_helpers_reject_non_ascii_digit_pin_before_send(pin: str, action: str) -> None:
    client, session = _make_client()
    with pytest.raises(Elke27InvalidArgument):
        if action == "arm":
            await client.async_arm_area(1, mode=ArmMode.ARMED_AWAY, pin=pin)
        elif action == "disarm":
            await client.async_disarm_area(1, pin=pin)
        else:
            await client.async_set_zone_bypass(1, pin=pin, bypassed=True)
    assert session.sent == []


@pytest.mark.asyncio
@pytest.mark.parametrize("pin", ["1234", "0123"])
async def test_async_execute_accepts_ascii_digit_pins(pin: str) -> None:
    client, session = _make_client()
    wire_pin = int(pin)
    result = await _run_async_execute(
        client,
        session,
        "area_set_arm_state",
        reply_domain="area",
        reply_command="set_arm_state",
        reply_payload={"area_id": 1, "error_code": E27ErrorCode.ELKERR_NONE},
        area_id=1,
        arm_state="ARMED_AWAY",
        pin=pin,
    )
    assert result.ok is True
    sent = session.sent[0]["area"]["set_arm_state"]
    assert sent["pin"] == wire_pin
