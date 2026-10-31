"""Keepalive round-trip DEBUG line and counters, through the public API.

Only ``session.Session`` is replaced by a fake; dummy values only.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

import pytest

from elke27_lib import linking
from elke27_lib import session as session_mod
from elke27_lib.kernel import E27Kernel, KeepaliveStats

KEYS = linking.E27LinkKeys("aa", "bb", "cc")
IDENTITY = linking.E27Identity("mn", "sn", "fw", "hw", "os")
_NO_IDS = re.compile(r"seq|session_id|mac|serial|pin|key|code|\d{6,}", re.IGNORECASE)


class _FakeSession:
    def __init__(self, answer: bool, rescue: bool = False) -> None:
        self.answer = answer
        self.rescue = rescue
        self.state = session_mod.SessionState.DISCONNECTED
        self.info = session_mod.SessionInfo(
            session_id=1, session_key_hex="00", session_hmac_hex="11"
        )
        self.wire_log_suppress_seqs: object = None
        self.on_message: Any = None
        self.on_disconnected: Any = None
        self.on_idle: Any = None
        self.disconnects: list[Exception | None] = []

    def connect(self) -> session_mod.SessionInfo:
        self.state = session_mod.SessionState.ACTIVE
        return self.info

    def enable_outbound_queue(self, **_kwargs: object) -> None:
        return None

    def start_auto_receive(self) -> None:
        return None

    def send_json(self, msg: dict[str, Any], **kwargs: Any) -> None:
        on_sent = kwargs.get("on_sent")
        if on_sent is not None:
            on_sent(time.monotonic())
        if self.answer and self.on_message is not None:
            self.on_message(dict(msg))
        elif self.rescue and self.on_message is not None:
            handler = self.on_message
            asyncio.get_running_loop().call_later(0.01, handler, {"seq": 0})

    def handle_disconnect(self, err: Exception | None) -> None:
        self.disconnects.append(err)
        self.state = session_mod.SessionState.DISCONNECTED

    def close(self) -> None:
        self.state = session_mod.SessionState.DISCONNECTED


def _kernel(
    monkeypatch: pytest.MonkeyPatch, *, answer: bool, rescue: bool = False
) -> tuple[E27Kernel, list[_FakeSession]]:
    made: list[_FakeSession] = []

    def _factory(**_kwargs: object) -> _FakeSession:
        made.append(_FakeSession(answer, rescue))
        return made[-1]

    monkeypatch.setattr(session_mod, "Session", _factory)
    kernel = E27Kernel()
    monkeypatch.setattr(kernel, "load_features_blocking", lambda _modules=None: None)
    kernel.requests.register(("system", "r_u_alive"), lambda: {})
    return kernel, made


def _cfg() -> session_mod.SessionConfig:
    return session_mod.SessionConfig(
        host="198.51.100.1",
        port=1,
        keepalive_enabled=True,
        keepalive_interval_s=0.05,
        keepalive_timeout_s=0.05,
        keepalive_max_missed=1,
    )


async def _wait(cond: Any) -> None:
    for _ in range(400):
        if cond():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("condition never met")


def test_stats_start_at_zero() -> None:
    assert E27Kernel().keepalive_stats == KeepaliveStats()


def test_default_miss_budget_is_one() -> None:
    assert session_mod.SessionConfig(host="198.51.100.1", port=1).keepalive_max_missed == 1


@pytest.mark.asyncio
async def test_round_trips_log_debug_and_count(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    kernel, _made = _kernel(monkeypatch, answer=True)
    with caplog.at_level(logging.DEBUG, logger="elke27_lib.kernel"):
        await kernel.connect(KEYS, session_config=_cfg(), client_identity=IDENTITY)
        await _wait(lambda: kernel.keepalive_stats.replies >= 2)
        await kernel.close()
    stats = kernel.keepalive_stats
    assert stats.misses == 0
    assert stats.consecutive_missed == 0
    assert isinstance(stats.last_round_trip_s, float)
    assert stats.max_round_trip_s is not None
    assert stats.max_round_trip_s >= stats.last_round_trip_s
    ok = [r for r in caplog.records if "keepalive round-trip ok" in r.getMessage()]
    sent = [r for r in caplog.records if "keepalive probe sent" in r.getMessage()]
    assert len(ok) >= 2 and len(sent) >= 2
    armed = [r for r in caplog.records if "keepalive armed" in r.getMessage()]
    assert "max_missed=1" in armed[0].getMessage()
    assert "timeout=" in ok[-1].getMessage()
    for r in ok + sent + armed:
        assert r.levelno == logging.DEBUG
        assert not _NO_IDS.search(r.getMessage())


@pytest.mark.asyncio
async def test_unanswered_probe_counts_miss_and_logs(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    kernel, made = _kernel(monkeypatch, answer=False)
    with caplog.at_level(logging.DEBUG, logger="elke27_lib.kernel"):
        await kernel.connect(KEYS, session_config=_cfg(), client_identity=IDENTITY)
        await _wait(lambda: bool(made[0].disconnects))
    stats = kernel.keepalive_stats
    assert stats.probes_sent == 1
    assert stats.replies == 0
    assert stats.misses == 1
    msgs = [r.getMessage() for r in caplog.records]
    assert any("keepalive missed (missed=1 of 1)" in m for m in msgs)
    await kernel.close()


@pytest.mark.asyncio
async def test_unanswered_probe_rescued_by_later_traffic(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    kernel, made = _kernel(monkeypatch, answer=False, rescue=True)
    with caplog.at_level(logging.DEBUG, logger="elke27_lib.kernel"):
        await kernel.connect(KEYS, session_config=_cfg(), client_identity=IDENTITY)
        await _wait(lambda: kernel.keepalive_stats.rescued >= 1)
        stats = kernel.keepalive_stats
        assert made[0].disconnects == []
        await kernel.close()
    assert stats.probes_sent >= 1
    assert stats.replies == 0
    assert stats.misses == 0
    assert stats.consecutive_missed == 0
    rescued = [r for r in caplog.records if "later traffic kept the link" in r.getMessage()]
    assert rescued
    for r in rescued:
        assert r.levelno == logging.DEBUG
        assert not _NO_IDS.search(r.getMessage())
