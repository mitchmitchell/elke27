"""0.3.10 regressions from PR #24 hardware testing.

Drives the real generators and response handling with only the transport faked.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any, cast

import pytest

from elke27_lib import Elke27PanelError, Elke27ProtocolError
from elke27_lib import client as client_mod
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
    return client, session


async def _reply(
    client: Elke27Client,
    session: _FakeSession,
    call: Coroutine[Any, Any, Any],
    domain: str,
    command: str,
    payload: dict[str, Any],
) -> Any:
    task = asyncio.ensure_future(call)
    for _ in range(20):
        if session.sent or task.done():
            break
        await asyncio.sleep(0)
    if task.done():
        return task.result()
    sent = session.sent[0]
    on_message = get_private(get_kernel(client), "_on_message")
    on_message({"seq": sent["seq"], domain: {command: payload}})
    return await task


@pytest.mark.asyncio
async def test_arm_night_rejected_with_clear_error_before_send() -> None:
    client, session = _make_client()
    with pytest.raises(Elke27InvalidArgument, match="does not support arm mode 'armed_night'"):
        await client.async_arm_area(1, mode=ArmMode.ARMED_NIGHT, pin="1234")
    assert session.sent == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("code", "reason"),
    [
        (E27ErrorCode.ELKERR_INVALID_PIN, "invalid user code"),
        (E27ErrorCode.ELKERR_NOT_READY, "area not ready (open or faulted zones)"),
        (E27ErrorCode.ELKERR_IN_ALARM, "area is in alarm; disarm to clear it first"),
        (E27ErrorCode.ELKERR_ID_EXISTS, "id exists"),
        (54321, "unknown panel error"),
    ],
)
async def test_arm_panel_error_code_surfaces_reason(code: int, reason: str) -> None:
    client, session = _make_client()
    with pytest.raises(Elke27PanelError) as exc_info:
        await _reply(
            client,
            session,
            client.async_arm_area(1, mode=ArmMode.ARMED_AWAY, pin="1234"),
            "area",
            "set_arm_state",
            {"area_id": 1, "error_code": int(code)},
        )
    err = exc_info.value
    assert isinstance(err, Elke27ProtocolError)  # backward compatible
    assert err.panel_error_code == int(code)
    assert err.reason == reason
    assert err.code == "panel_error"
    assert str(err) == f"Panel rejected the request: {reason} (error {int(code)})."
    assert "1234" not in repr(err)


@pytest.mark.asyncio
async def test_disarm_panel_error_code_surfaces_reason() -> None:
    client, session = _make_client()
    with pytest.raises(Elke27PanelError, match="invalid user code"):
        await _reply(
            client,
            session,
            client.async_disarm_area(1, pin="1234"),
            "area",
            "set_arm_state",
            {"area_id": 1, "error_code": int(E27ErrorCode.ELKERR_INVALID_PIN)},
        )


@pytest.mark.asyncio
async def test_zone_bypass_panel_error_code_surfaces_reason() -> None:
    client, session = _make_client()
    cast(Any, client)._connected = True
    with pytest.raises(Elke27PanelError, match="zone cannot be bypassed"):
        await _reply(
            client,
            session,
            client.async_set_zone_bypass(3, bypassed=True, pin="1234"),
            "zone",
            "set_status",
            {"zone_id": 3, "error_code": int(E27ErrorCode.ELKERR_NOT_BYPASSABLE)},
        )


@pytest.mark.parametrize(
    ("ready", "ready_status", "expected"),
    [
        (None, "RDY_AWAY", True),
        (None, "RDY_STAY", True),
        (None, "rdy_not", False),
        (None, "RDY_NOT", False),
        (None, "SOMETHING", None),
        (None, None, None),
        (False, "RDY_AWAY", False),
        (True, "RDY_NOT", True),
    ],
)
def test_area_ready_derivation(
    ready: bool | None, ready_status: str | None, expected: bool | None
) -> None:
    assert cast(Any, client_mod)._area_ready(ready, ready_status) is expected


def test_snapshot_area_ready_from_ready_status() -> None:
    client = Elke27Client()
    kernel = get_kernel(client)
    area = kernel.state.get_or_create_area(1)
    area.ready_status = "RDY_NOT"
    area_map = get_private(client, "_build_area_map")()
    assert area_map[1].ready is False
    assert area_map[1].ready_status == "RDY_NOT"
    area.ready_status = "RDY_STAY"
    area_map = get_private(client, "_build_area_map")()
    assert area_map[1].ready is True
