from __future__ import annotations

import asyncio
import threading

import pytest

from elke27_lib import pending_loop as pending
from elke27_lib import permissions, states, util
from elke27_lib.pending_loop import PendingResponseManager


def test_parse_url_invalid_host() -> None:
    with pytest.raises(ValueError):
        util.parse_url("elk://")


def test_get_or_create_tstat() -> None:
    panel = states.PanelState()
    assert panel.tstats == {}
    tstat = panel.get_or_create_tstat(1)
    assert tstat.tstat_id == 1
    assert panel.tstats[1] is tstat


def test_pending_call_in_loop_fallback() -> None:
    called: list[str] = []

    class _Loop:
        def call_soon_threadsafe(self, _fn):  # type: ignore[no-untyped-def]
            raise RuntimeError("no loop")

    def _fn() -> None:
        called.append("ok")

    entry = pending.PendingResponse(
        seq=1,
        command_key="cmd",
        expected_route=("x", "y"),
        created_at=0.0,
        future=object(),  # type: ignore[arg-type]
        loop=_Loop(),  # type: ignore[arg-type]
    )
    pending.PendingResponseManager._call_in_loop(entry, _fn)
    assert called == ["ok"]


def test_permission_level_unknown() -> None:
    with pytest.raises(ValueError):
        permissions.required_role("BAD")  # type: ignore[arg-type]


def test_pending_manager_create_raises_under_lock_contention() -> None:
    loop = asyncio.new_event_loop()
    shared = threading.Lock()
    m = PendingResponseManager(lock=shared, lock_acquire_timeout_s=0.05)
    held = threading.Event()
    proceed = threading.Event()

    def _holder() -> None:
        shared.acquire()
        held.set()
        proceed.wait()
        shared.release()

    threading.Thread(target=_holder, name="lock-holder", daemon=True).start()
    held.wait(timeout=5.0)
    try:
        with pytest.raises(RuntimeError, match="Pending response lock contention timed out"):
            m.create(1, command_key="k", expected_route=("a", "b"), loop=loop)
    finally:
        proceed.set()
        loop.close()
