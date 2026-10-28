"""Public Elke27CodeRejectedError for panel user-code rejections (#76)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, cast

import pytest

from elke27_lib import Elke27CodeRejectedError, Elke27PanelError
from elke27_lib import session as session_mod
from elke27_lib.client import ArmMode, Elke27Client
from elke27_lib.const import E27ErrorCode
from elke27_lib.errors import CODE_REJECTED_PANEL_ERROR_CODES, panel_error_from_code
from test.helpers.fake_panel_replies import synthetic_success_reply
from test.helpers.internal import get_kernel, get_private


class _FakeSession:
    state = session_mod.SessionState.ACTIVE

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
    kernel.load_features_blocking()
    session = _FakeSession()
    cast(Any, kernel)._session = session
    kernel.state.panel.session_id = 1
    return client, session


async def _reply(
    client: Elke27Client,
    session: _FakeSession,
    call: Any,
    domain: str,
    command: str,
    payload: dict[str, Any],
) -> Any:
    task = asyncio.ensure_future(call)
    on_message = get_private(get_kernel(client), "_on_message")
    seen = 0
    client._event_loop = asyncio.get_running_loop()
    while not task.done():
        await asyncio.sleep(0)
        while seen < len(session.sent):
            sent = session.sent[seen]
            if seen == 0:
                on_message({"seq": sent["seq"], domain: {command: payload}})
            else:
                on_message(synthetic_success_reply(sent, sent_history=session.sent[:seen]))
            seen += 1
    return await task


def test_code_rejected_panel_error_codes_match_hacs_set() -> None:
    assert CODE_REJECTED_PANEL_ERROR_CODES == frozenset({11004, 11008, 11037})


def test_panel_error_from_code_factory() -> None:
    rejected = panel_error_from_code(11037, "invalid user code")
    assert isinstance(rejected, Elke27CodeRejectedError)
    assert isinstance(rejected, Elke27PanelError)
    assert rejected.panel_error_code == 11037

    other = panel_error_from_code(int(E27ErrorCode.ELKERR_NOT_READY), "area not ready")
    assert type(other) is Elke27PanelError
    assert not isinstance(other, Elke27CodeRejectedError)


@pytest.mark.parametrize(
    "panel_code",
    [
        E27ErrorCode.ELKERR_INVALID_PARAM,
        E27ErrorCode.ELKERR_NOAUTH,
        E27ErrorCode.ELKERR_INVALID_PIN,
    ],
)
@pytest.mark.asyncio
async def test_arm_raises_code_rejected_for_panel_codes(panel_code: int) -> None:
    client, session = _make_client()
    with pytest.raises(Elke27CodeRejectedError) as exc_info:
        await _reply(
            client,
            session,
            client.async_arm_area(1, mode=ArmMode.ARMED_AWAY, pin="1234"),
            "area",
            "set_arm_state",
            {"area_id": 1, "error_code": int(panel_code)},
        )
    err = exc_info.value
    assert err.panel_error_code == int(panel_code)
    assert isinstance(err, Elke27PanelError)


@pytest.mark.asyncio
async def test_arm_other_panel_error_stays_base_panel_error() -> None:
    client, session = _make_client()
    with pytest.raises(Elke27PanelError) as exc_info:
        await _reply(
            client,
            session,
            client.async_arm_area(1, mode=ArmMode.ARMED_AWAY, pin="1234"),
            "area",
            "set_arm_state",
            {"area_id": 1, "error_code": int(E27ErrorCode.ELKERR_NOT_READY)},
        )
    assert type(exc_info.value) is Elke27PanelError
    assert not isinstance(exc_info.value, Elke27CodeRejectedError)


@pytest.mark.asyncio
async def test_async_execute_code_rejected_on_noauth() -> None:
    client, session = _make_client()
    task = asyncio.create_task(
        client.async_execute(
            "light_set_status",
            light_id=1,
            status="ON",
        )
    )
    on_message = get_private(get_kernel(client), "_on_message")
    client._event_loop = asyncio.get_running_loop()
    while not task.done():
        await asyncio.sleep(0)
        if session.sent:
            sent = session.sent[0]
            on_message(
                {
                    "seq": sent["seq"],
                    "light": {
                        "set_status": {
                            "light_id": 1,
                            "error_code": int(E27ErrorCode.ELKERR_NOAUTH),
                        }
                    },
                }
            )
    result = await task
    assert result.ok is False
    assert isinstance(result.error, Elke27CodeRejectedError)
    assert result.error.panel_error_code == int(E27ErrorCode.ELKERR_NOAUTH)
