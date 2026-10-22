"""Replying fake panel for client re-auth tests (shared by test_security_round1 and
the offline statechart cases). Only ``session.Session`` is replaced; kernel,
dispatch and client are real. Dummy values only."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

from elke27_lib import session as session_mod
from elke27_lib.client import Elke27Client
from elke27_lib.kernel import E27Kernel
from elke27_lib.session import SessionInfo
from elke27_lib.types import ClientConfig, LinkKeys

DUMMY_PIN = 424242
HOST = "198.51.100.1"
KEYS = LinkKeys("aa", "bb", "cc")


class _FakePanel:
    """The panel behind a fake transport: records the wire and answers requests.

    Only ``session.Session`` is replaced; the kernel, dispatch and client are real.
    """

    def __init__(self) -> None:
        self.sessions: list[_FakeSession] = []
        # accept | refuse | silent | hold
        self.auth: str = "accept"
        self.held: list[tuple[_FakeSession, dict[str, Any]]] = []
        # (domain, name) -> reply builder; overrides the default empty ack.
        self.overrides: dict[tuple[str, str], Callable[[dict[str, Any]], dict[str, Any]]] = {}

    @property
    def session(self) -> _FakeSession:
        return self.sessions[-1]

    def wire(self) -> list[dict[str, Any]]:
        return [m for s in self.sessions for m in s.sent]

    def auth_requests(self, session: _FakeSession | None = None) -> list[dict[str, Any]]:
        sent = (session or self.session).sent
        return [m for m in sent if "authenticate" in m]

    def drop_link(self) -> None:
        self.session.on_disconnected(session_mod.SessionIOError("link dropped"))

    def release_held(self) -> None:
        for session, reply in self.held:
            session.on_message(reply)
        self.held.clear()

    def reply(self, session: _FakeSession, msg: dict[str, Any]) -> None:
        loop = asyncio.get_running_loop()
        seq = msg["seq"]
        if "authenticate" in msg:
            if self.auth == "silent":
                return
            code = 11008 if self.auth == "refuse" else 0
            reply = {"seq": seq, "authenticate": {"error_code": code}}
            if self.auth == "hold":
                self.held.append((session, reply))
                return
            loop.call_soon(session.on_message, reply)
            return
        domain = next(k for k in msg if k not in ("seq", "session_id"))
        name = next(iter(msg[domain]))
        build = self.overrides.get((domain, name))
        if build is not None:
            reply = build(msg)
        elif name == "get_configured":
            body = {"block_id": 1, "block_count": 1, "error_code": 0}
            reply = {"seq": seq, domain: {name: body}}
        else:
            reply = {"seq": seq, domain: {name: {"error_code": 0}}}
        loop.call_soon(session.on_message, reply)


class _FakeSession:
    def __init__(self, panel: _FakePanel) -> None:
        self.panel = panel
        self.state = session_mod.SessionState.ACTIVE
        self.info = SessionInfo(
            session_id=11 + len(panel.sessions), session_key_hex="00", session_hmac_hex="11"
        )
        self.wire_log_suppress_seqs: object = None
        self.on_message: Any = None
        self.on_disconnected: Any = None
        self.on_idle: Any = None
        self.sent: list[dict[str, Any]] = []
        panel.sessions.append(self)

    def connect(self) -> SessionInfo:
        return self.info

    def enable_outbound_queue(self, **_kwargs: object) -> None:
        return None

    def start_auto_receive(self) -> None:
        return None

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
            on_sent(time.monotonic())
        self.panel.reply(self, msg)

    def close(self) -> None:
        self.state = session_mod.SessionState.DISCONNECTED


class _Clock:
    """Monotonic clock with a settable outage jump."""

    def __init__(self) -> None:
        self.offset = 0.0

    def __call__(self) -> float:
        return time.monotonic() + self.offset


async def _connected(
    *, reauth: bool = False, request_timeout_s: float = 5.0, kernel: E27Kernel | None = None
) -> tuple[Elke27Client, _Clock]:
    clock = _Clock()
    config = ClientConfig(reauth_on_reconnect=reauth, request_timeout_s=request_timeout_s)
    client = Elke27Client(config, kernel=kernel, now_monotonic=clock)
    await client.async_connect(HOST, 2101, KEYS)
    return client, clock


async def _authenticate(client: Elke27Client) -> bool:
    result = await client.async_execute("control_authenticate", pin=DUMMY_PIN)
    return result.ok


async def _drop_and_reconnect(
    client: Elke27Client, panel: _FakePanel, clock: _Clock, *, outage_s: float = 1000.0
) -> None:
    """Link loss, then a reconnect ``outage_s`` seconds later."""
    panel.drop_link()
    clock.offset += outage_s
    await client.async_connect(HOST, 2101, KEYS)
