"""Regression for #80: HELLO setup failures must not emit unflagged disconnects."""

from __future__ import annotations

import socket
import types
from typing import Any

import pytest

from elke27_lib import hello, linking
from elke27_lib import session as session_mod
from elke27_lib.errors import E27ErrorContext, E27HelloNoSession, E27ProtocolError
from elke27_lib.events import ConnectionStateChanged, Event
from elke27_lib.kernel import E27Kernel, KernelError

KEYS = linking.E27LinkKeys("aa", "bb", "cc")
IDENTITY = linking.E27Identity("mn", "sn", "fw", "hw", "os")
CFG = session_mod.SessionConfig(host="198.51.100.1", port=1, keepalive_enabled=False)


class _ConnSocket:
    def connect(self, _addr: object) -> None:
        return None

    def settimeout(self, _value: float) -> None:
        return None

    def gettimeout(self) -> float | None:
        return None

    def close(self) -> None:
        return None


def _pairs_ok(events: list[ConnectionStateChanged]) -> bool:
    """At most one connected=False per connected=True (refusals excepted)."""
    up = False
    for evt in events:
        if evt.connected:
            up = True
        elif up:
            up = False
        elif not evt.hello_refused:
            return False
    return True


def _subscribe_conn(kernel: E27Kernel) -> list[ConnectionStateChanged]:
    events: list[ConnectionStateChanged] = []

    def _on(evt: Event) -> None:
        if isinstance(evt, ConnectionStateChanged):
            events.append(evt)

    kernel.subscribe(_on, kinds={ConnectionStateChanged.KIND})
    return events


def _patch_connect_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_socket_mod = types.SimpleNamespace(**vars(socket))
    fake_socket_mod.socket = lambda *_a, **_k: _ConnSocket()
    monkeypatch.setattr(session_mod, "socket", fake_socket_mod)


@pytest.mark.asyncio
async def test_hello_refusal_emits_flagged_false_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """O7a: refused HELLO yields hello_refused connected=False, never connected=True."""
    _patch_connect_socket(monkeypatch)

    def _refuse(**_kwargs: Any) -> hello.SessionKeys:
        raise E27HelloNoSession(("session_id", "sk", "shm"))

    monkeypatch.setattr(session_mod, "perform_hello", _refuse)

    kernel = E27Kernel()
    monkeypatch.setattr(kernel, "load_features_blocking", lambda _modules=None: None)
    events = _subscribe_conn(kernel)

    with pytest.raises(KernelError):
        await kernel.connect(KEYS, session_config=CFG, client_identity=IDENTITY)

    assert not any(e.connected for e in events)
    assert events and all(e.hello_refused for e in events)
    assert _pairs_ok(events)


@pytest.mark.asyncio
async def test_non_refusal_hello_failure_emits_no_unflagged_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """O7b (#80): non-refusal HELLO failure must not emit unflagged connected=False."""
    _patch_connect_socket(monkeypatch)

    def _fail_hello(**_kwargs: Any) -> hello.SessionKeys:
        raise E27ProtocolError(
            "Hello response not found in cleartext JSON stream.",
            context=E27ErrorContext(phase="hello_recv"),
        )

    monkeypatch.setattr(session_mod, "perform_hello", _fail_hello)

    kernel = E27Kernel()
    monkeypatch.setattr(kernel, "load_features_blocking", lambda _modules=None: None)
    events = _subscribe_conn(kernel)

    with pytest.raises(KernelError):
        await kernel.connect(KEYS, session_config=CFG, client_identity=IDENTITY)

    assert _pairs_ok(events)
    assert events == []


@pytest.mark.asyncio
async def test_hello_no_session_error_emits_flagged_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_connect_socket(monkeypatch)

    def _refuse(**_kwargs: Any) -> hello.SessionKeys:
        raise E27HelloNoSession(("session_id",))

    monkeypatch.setattr(session_mod, "perform_hello", _refuse)

    kernel = E27Kernel()
    monkeypatch.setattr(kernel, "load_features_blocking", lambda _modules=None: None)
    events = _subscribe_conn(kernel)

    with pytest.raises(KernelError):
        await kernel.connect(KEYS, session_config=CFG, client_identity=IDENTITY)

    assert len(events) == 1
    assert events[0].connected is False
    assert events[0].hello_refused is True
