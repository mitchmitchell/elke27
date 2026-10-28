"""Regression for #50: recv-thread disconnect during connect() must not be lost."""

from __future__ import annotations

from typing import Any

import pytest

from elke27_lib import linking
from elke27_lib import session as session_mod
from elke27_lib.client import Elke27Client, Elke27DisconnectedError, LinkKeys
from elke27_lib.errors import Elke27ProtocolError
from elke27_lib.events import ConnectionStateChanged, Event
from elke27_lib.kernel import E27Kernel, KernelError

KEYS = linking.E27LinkKeys("aa", "bb", "cc")
IDENTITY = linking.E27Identity("mn", "sn", "fw", "hw", "os")
LINK_KEYS = LinkKeys("aa", "bb", "cc")


class _SessionDisconnectOnAutoReceive:
    """ACTIVE session whose start_auto_receive() simulates an immediate link drop."""

    def __init__(
        self,
        cfg: session_mod.SessionConfig,
        client_identity: Any,
        link_key_hex: str,
    ) -> None:
        self.cfg = cfg
        self.client_identity = client_identity
        self.link_key_hex = link_key_hex
        self.state = session_mod.SessionState.ACTIVE
        self.info = session_mod.SessionInfo(
            session_id=42,
            session_key_hex="00",
            session_hmac_hex="11",
        )
        self.on_message: Any = None
        self.on_disconnected: Any = None
        self.on_idle: Any = None
        self.wire_log_suppress_seqs: set[int] = set()

    def connect(self) -> session_mod.SessionInfo:
        return self.info

    def enable_outbound_queue(self, **_kwargs: Any) -> None:
        return None

    def start_auto_receive(self) -> None:
        if self.on_disconnected is not None:
            self.state = session_mod.SessionState.DISCONNECTED
            self.on_disconnected(
                session_mod.SessionIOError("link lost during connect"),
            )

    def close(self) -> None:
        self.state = session_mod.SessionState.DISCONNECTED


def _subscribe_conn(kernel: E27Kernel) -> list[ConnectionStateChanged]:
    events: list[ConnectionStateChanged] = []

    def _on(evt: Event) -> None:
        if isinstance(evt, ConnectionStateChanged):
            events.append(evt)

    kernel.subscribe(_on, kinds={ConnectionStateChanged.KIND})
    return events


def _patch_session_race(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_mod, "Session", _SessionDisconnectOnAutoReceive)
    monkeypatch.setattr(
        E27Kernel,
        "load_features_blocking",
        lambda _self, _modules=None: None,
    )


@pytest.mark.asyncio
async def test_disconnect_during_start_auto_receive_not_lost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Receive-thread disconnect in the connect() window emits False and raises."""
    _patch_session_race(monkeypatch)

    kernel = E27Kernel()
    events = _subscribe_conn(kernel)
    cfg = session_mod.SessionConfig(
        host="198.51.100.1",
        port=1,
        keepalive_enabled=False,
        auto_receive=True,
        auto_receive_thread_fallback=True,
    )

    with pytest.raises(KernelError, match="disconnected during connect"):
        await kernel.connect(KEYS, session_config=cfg, client_identity=IDENTITY)

    assert kernel.state.panel.connected is False
    assert len(events) == 1
    assert events[0].connected is False
    assert events[0].hello_refused is False
    assert not any(e.connected for e in events)


@pytest.mark.asyncio
async def test_async_connect_race_does_not_leave_client_connected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Public client must not treat async_connect as success after the recv race."""
    _patch_session_race(monkeypatch)

    client = Elke27Client()
    with pytest.raises(Elke27ProtocolError):
        await client.async_connect("198.51.100.1", 1, LINK_KEYS)

    assert client.state.panel.connected is False
    with pytest.raises(Elke27DisconnectedError, match="Client is not connected"):
        await client.async_refresh_csm()
