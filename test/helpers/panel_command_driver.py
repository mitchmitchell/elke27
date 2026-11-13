"""Drive ``Elke27Client`` async commands through ``FakePanelSession`` (public API only)."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

import pytest

from elke27_lib.client import Elke27Client
from elke27_lib.const import E27ErrorCode
from test.helpers.fake_panel_replies import synthetic_success_reply
from test.helpers.fake_session import FakePanelSession, connect_with_fake_panel


async def connect_panel(
    monkeypatch: pytest.MonkeyPatch, *, enable_raw_passthrough: bool = False
) -> tuple[Elke27Client, FakePanelSession]:
    client = Elke27Client(
        enable_raw_passthrough=enable_raw_passthrough,
        skip_connect_bootstrap=True,
    )
    panel = await connect_with_fake_panel(monkeypatch, client)
    return client, panel


async def seed_application_firmware(
    panel: FakePanelSession,
    app: int,
    *,
    ssp: str = "2.6.1",
) -> None:
    await panel.deliver(
        {
            "seq": 0,
            "session_id": panel.info.session_id,
            "control": {
                "get_version_info": {
                    "app": app,
                    "SSP": ssp,
                    "error_code": E27ErrorCode.ELKERR_NONE,
                }
            },
        }
    )


async def seed_area_disarmed(panel: FakePanelSession, area_id: int = 1) -> None:
    await panel.deliver(
        {
            "seq": 0,
            "session_id": panel.info.session_id,
            "area": {
                "get_status": {
                    "area_id": area_id,
                    "arm_state": "DISARMED",
                    "error_code": E27ErrorCode.ELKERR_NONE,
                }
            },
        }
    )


async def connect_with_app_firmware(
    monkeypatch: pytest.MonkeyPatch,
    app: int,
    *,
    ssp: str = "2.6.1",
) -> tuple[Elke27Client, FakePanelSession]:
    client, panel = await connect_panel(monkeypatch)
    await seed_application_firmware(panel, app, ssp=ssp)
    await seed_area_disarmed(panel)
    return client, panel


async def drive_until_done(
    client: Elke27Client,
    panel: FakePanelSession,
    call: Coroutine[Any, Any, Any],
    *,
    custom_replies: dict[int, dict[str, Any]] | None = None,
    max_replies: int | None = None,
) -> Any:
    base = len(panel.sent)
    task = asyncio.create_task(call)
    seen = base
    while not task.done():
        await asyncio.sleep(0)
        if max_replies is not None and seen >= base + max_replies:
            continue
        while seen < len(panel.sent):
            sent = panel.sent[seen]
            command_index = seen - base
            if custom_replies is not None and command_index in custom_replies:
                reply = dict(custom_replies[command_index])
                reply["seq"] = sent["seq"]
                if "session_id" not in reply:
                    reply["session_id"] = sent.get("session_id", panel.info.session_id)
                await panel.deliver(reply)
            else:
                await panel.deliver(
                    synthetic_success_reply(
                        dict(sent),
                        sent_history=[dict(item) for item in panel.sent[:seen]],
                    )
                )
            seen += 1
    return await task
