from __future__ import annotations

import pytest

from elke27_lib import pending, permissions, states, util


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
