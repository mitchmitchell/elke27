"""A stand-in for ``elke27_lib.session_thread.Session`` that lets tests act as the panel."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from typing import Any

import pytest

from elke27_lib import session_thread as session_mod
from elke27_lib.client import Elke27Client
from elke27_lib.types import LinkKeys


class FakePanelSession:
    """Accepts the kernel's session wiring; ``deliver`` plays a decrypted panel message."""

    instances: list[FakePanelSession] = []

    def __init__(self, cfg: Any, client_identity: Any, link_key_hex: str) -> None:
        self.cfg = cfg
        self.state = session_mod.SessionState.ACTIVE
        self.info = session_mod.SessionInfo(
            session_id=1, session_key_hex="00", session_hmac_hex="11"
        )
        self.sent: list[Mapping[str, Any]] = []
        self.on_message: Callable[[Mapping[str, Any]], None] | None = None
        self.on_disconnected: Callable[..., None] | None = None
        self.on_idle: Callable[..., None] | None = None
        self.wire_log_suppress_seqs: Any = None
        FakePanelSession.instances.append(self)

    def connect(self) -> session_mod.SessionInfo:
        return self.info

    def enable_outbound_queue(self, *, loop: asyncio.AbstractEventLoop, **_kwargs: object) -> None:
        self._loop_ref = loop

    def start_auto_receive(self) -> None:
        return None

    def send_json(self, obj: Mapping[str, Any], *args: object, **kwargs: object) -> None:
        self.sent.append(obj)

    def handle_disconnect(self, err: Exception | None) -> None:
        self.state = session_mod.SessionState.DISCONNECTED

    def close(self) -> None:
        self.state = session_mod.SessionState.DISCONNECTED

    async def deliver(self, msg: Mapping[str, Any]) -> None:
        """Hand one decrypted message to the kernel, as the receive loop would."""
        assert self.on_message is not None
        self.on_message(msg)
        await asyncio.sleep(0)


async def connect_with_fake_panel(
    monkeypatch: pytest.MonkeyPatch, client: Elke27Client
) -> FakePanelSession:
    """Connect ``client`` through its public API to a ``FakePanelSession``."""
    FakePanelSession.instances.clear()
    monkeypatch.setattr(session_mod, "Session", FakePanelSession)
    await client.async_connect("panel.invalid", 2101, LinkKeys("aa", "bb", "cc"))
    return FakePanelSession.instances[-1]
