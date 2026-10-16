"""Raw API pass-through (decision 34): Elke27Client.async_raw_request."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, cast

import pytest

from elke27_lib import Elke27CommandOutcomeUnknownError
from elke27_lib.client import Elke27Client
from elke27_lib.errors import Elke27InvalidArgument, Elke27PanelError, Elke27PermissionError
from elke27_lib.states import AreaState
from test.helpers.internal import get_kernel, get_private
from test.test_transport_command_retry import _FakeSession

FAKE_PIN = 987654
FAKE_LINKKEY = "a1b2c3d4e5f60718293a4b5c6d7e8f90"


class _Session(_FakeSession):
    class _Cfg:
        host = "test"
        port = 0

    cfg = _Cfg()


def _client(session: _FakeSession, *, enabled: bool = True, disarmed: bool = True) -> Elke27Client:
    client = Elke27Client(enable_raw_passthrough=enabled)
    kernel = get_kernel(client)
    cast(Any, kernel)._session = session
    kernel.state.panel.session_id = 4242
    cast(Any, kernel)._request_max_retries = 0
    cast(Any, kernel)._request_max_backoff_s = 0.0
    cast(Any, kernel)._loop = asyncio.get_running_loop()
    kernel.state.areas[1] = AreaState(area_id=1, arm_state="DISARMED" if disarmed else "ARMED_AWAY")
    return client


async def _reply(client: Elke27Client, session: _FakeSession, build: Any) -> None:
    for _ in range(50):
        if session.sent:
            break
        await asyncio.sleep(0)
    sent = session.sent[-1]
    get_private(get_kernel(client), "_on_message")(build(sent))


@pytest.mark.asyncio
async def test_roundtrip_injects_seq_and_session() -> None:
    session = _Session()
    client = _client(session)
    task = asyncio.create_task(client.async_raw_request({"net_dev": {"get_list": {"block_id": 1}}}))
    await _reply(
        client,
        session,
        lambda s: {
            "seq": s["seq"],
            "session_id": 4242,
            "net_dev": {"get_list": {"error_code": 0, "block_count": 1, "net_devs": [1]}},
        },
    )
    result = await asyncio.wait_for(task, 2.0)
    sent = session.sent[0]
    assert isinstance(sent["seq"], int) and sent["seq"] > 0
    assert sent["session_id"] == 4242
    assert sent["net_dev"] == {"get_list": {"block_id": 1}}
    assert result.ok
    assert result.data == {
        "net_dev": {"get_list": {"error_code": 0, "block_count": 1, "net_devs": [1]}}
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    [
        {"seq": 5, "net_dev": {"get_list": {}}},
        {"session_id": 1, "net_dev": {"get_list": {}}},
        {"net_dev": {"get_list": {"seq": 9}}},
        {"net_dev": {"get_list": {}}, "zone": {"get_status": {}}},
        {"net_dev": {"get_list": {}, "get_attribs": {}}},
        {"net_dev": {"get_list": 3}},
        {},
    ],
)
async def test_malformed_or_caller_seq_rejected_before_send(message: dict[str, Any]) -> None:
    session = _Session()
    client = _client(session)
    result = await client.async_raw_request(message, allow_installer=True)
    assert isinstance(result.error, Elke27InvalidArgument)
    assert session.sent == []


@pytest.mark.asyncio
async def test_disabled_client_refuses() -> None:
    session = _Session()
    client = _client(session, enabled=False)
    result = await client.async_raw_request({"net_dev": {"get_list": {}}})
    assert isinstance(result.error, Elke27PermissionError)
    assert session.sent == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    [
        {"net_dev": {"del_attribs": {"net_dev_id": 3}}},
        {"made_up": {"thing": {}}},  # unknown routes fail closed
    ],
)
async def test_installer_or_unknown_route_needs_opt_in(message: dict[str, Any]) -> None:
    session = _Session()
    client = _client(session)
    result = await client.async_raw_request(message)
    assert isinstance(result.error, Elke27PermissionError)
    assert session.sent == []


@pytest.mark.asyncio
async def test_disarmed_route_refused_when_armed() -> None:
    session = _Session()
    client = _client(session, disarmed=False)
    result = await client.async_raw_request(
        {"net_dev": {"del_attribs": {"net_dev_id": 3}}}, allow_installer=True
    )
    assert isinstance(result.error, Elke27PermissionError)
    assert session.sent == []


@pytest.mark.asyncio
async def test_panel_error_code() -> None:
    session = _Session()
    client = _client(session)
    task = asyncio.create_task(
        client.async_raw_request(
            {"net_dev": {"del_attribs": {"net_dev_id": 3}}}, allow_installer=True
        )
    )
    await _reply(
        client,
        session,
        lambda s: {"seq": s["seq"], "net_dev": {"del_attribs": {"error_code": 11008}}},
    )
    result = await asyncio.wait_for(task, 2.0)
    assert isinstance(result.error, Elke27PanelError)
    assert result.error.panel_error_code == 11008


@pytest.mark.asyncio
async def test_sent_without_reply_is_outcome_unknown() -> None:
    session = _Session()
    client = _client(session)
    cast(Any, client)._command_transport_wait_budget_s = lambda _t: 0.05
    result = await asyncio.wait_for(
        client.async_raw_request(
            {"net_dev": {"del_attribs": {"net_dev_id": 3}}}, allow_installer=True, timeout_s=0.02
        ),
        2.0,
    )
    assert isinstance(result.error, Elke27CommandOutcomeUnknownError)
    assert result.error.route == ("net_dev", "del_attribs")
    assert len(session.sent) == 1


@pytest.mark.asyncio
async def test_disconnected_session_fails_without_send() -> None:
    session = _Session()
    client = _client(session)
    session.handle_disconnect(None)
    result = await client.async_raw_request({"net_dev": {"get_list": {}}})
    assert not result.ok
    assert session.sent == []


@pytest.mark.asyncio
async def test_no_message_or_reply_content_in_logs(caplog: pytest.LogCaptureFixture) -> None:
    session = _Session()
    client = _client(session)
    caplog.set_level(logging.DEBUG)
    task = asyncio.create_task(
        client.async_raw_request(
            {"net_dev": {"set_creds": {"net_dev_id": 7, "pin": FAKE_PIN, "linkkey": FAKE_LINKKEY}}},
            allow_installer=True,
        )
    )
    await _reply(
        client,
        session,
        lambda s: {
            "seq": s["seq"],
            "session_id": 4242,
            "net_dev": {"set_creds": {"error_code": 0, "linkkey": FAKE_LINKKEY, "pin": FAKE_PIN}},
        },
    )
    result = await asyncio.wait_for(task, 2.0)
    assert result.ok
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert str(FAKE_PIN) not in text
    assert FAKE_LINKKEY not in text
    assert "net_dev_id" not in text
    summary = [r.getMessage() for r in caplog.records if "Raw pass-through" in r.getMessage()]
    assert len(summary) == 1
    assert "route=net_dev.set_creds outcome=ok" in summary[0]
    assert "allow_installer=True" in summary[0]
