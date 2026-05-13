"""
Live E27 tests for the Home Assistant integration contract.

Run:
  source ~/elk-e27-env-vars.sh
  ELKE27_LIVE=1 pytest -q -m live_e27 test/test_live_e27_home_assistant_contract.py -s
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import Mapping

import pytest

from elke27_lib.client import Elke27Client
from elke27_lib.events import Event, ZoneStatusUpdated

_LIVE_TIMEOUT_S = 30.0


def _first_env(*names: str, default: str | None = None) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return default


def _env_zone_id() -> int:
    zone_id_raw = _first_env("ELKE27_LIVE_ZONE_ID", "ELKE27_ZONE_ID")
    if not zone_id_raw:
        pytest.skip("Set ELKE27_LIVE_ZONE_ID or ELKE27_ZONE_ID to run zone bypass test.")
    if not zone_id_raw.strip().isdigit():
        pytest.fail("Zone id must be a positive integer.")
    zone_id = int(zone_id_raw)
    if zone_id <= 0:
        pytest.fail("Zone id must be a positive integer.")
    return zone_id


def _env_pin() -> int:
    pin_raw = _first_env("ELKE27_LIVE_PIN", "ELKE27_PIN")
    if not pin_raw:
        pytest.skip("Set ELKE27_LIVE_PIN or ELKE27_PIN to run zone bypass test.")
    if not pin_raw.strip().isdigit():
        pytest.fail("PIN must be numeric.")
    pin = int(pin_raw)
    if pin <= 0:
        pytest.fail("PIN must be a positive integer.")
    return pin


def _get_zone_bypassed(client: Elke27Client, zone_id: int) -> bool | None:
    zone = client.snapshot.zones.get(zone_id)
    if zone is None:
        zone = client.state.zones.get(zone_id)
    if zone is None:
        return None
    bypassed = getattr(zone, "bypassed", None)
    return bypassed if isinstance(bypassed, bool) else None


async def _wait_for_bypass_state(
    client: Elke27Client,
    zone_id: int,
    expected: bool,
    timeout_s: float,
) -> None:
    loop = asyncio.get_running_loop()
    event = asyncio.Event()

    def _on_evt(evt: Event) -> None:
        if not isinstance(evt, ZoneStatusUpdated):
            return
        if evt.zone_id != zone_id or "bypassed" not in evt.changed_fields:
            return
        if _get_zone_bypassed(client, zone_id) is expected:
            loop.call_soon_threadsafe(event.set)

    unsubscribe = client.subscribe_typed(_on_evt)
    try:
        if _get_zone_bypassed(client, zone_id) is expected:
            return
        await asyncio.wait_for(event.wait(), timeout=timeout_s)
    finally:
        unsubscribe()


@pytest.mark.live_e27
@pytest.mark.asyncio
async def test_live_home_assistant_contract_snapshot(
    live_e27_client: Elke27Client,
) -> None:
    """Verify the client exposes the snapshot surface Home Assistant consumes."""
    assert live_e27_client.is_ready
    snapshot = live_e27_client.snapshot

    assert snapshot.version > 0
    assert snapshot.panel is not None
    assert snapshot.table_info is not None
    assert isinstance(snapshot.areas, Mapping)
    assert isinstance(snapshot.zones, Mapping)


@pytest.mark.live_e27
@pytest.mark.asyncio
async def test_live_home_assistant_contract_zone_bypass_events(
    live_e27_client: Elke27Client,
) -> None:
    """Verify bypass changes update client state through zone events."""
    if _first_env("ELKE27_LIVE_BYPASS_TOGGLE", "ELKE27_BYPASS_TOGGLE") != "1":
        pytest.skip("Set ELKE27_LIVE_BYPASS_TOGGLE=1 to allow bypass toggles.")

    zone_id = _env_zone_id()
    pin = _env_pin()
    timeout_s = float(
        _first_env(
            "ELKE27_LIVE_EVENT_TIMEOUT",
            "ELKE27_EVENT_TIMEOUT",
            default=str(_LIVE_TIMEOUT_S),
        )
        or _LIVE_TIMEOUT_S
    )

    status_result = await live_e27_client.async_execute(
        "zone_get_status",
        zone_id=zone_id,
        timeout_s=timeout_s,
    )
    if not status_result.ok:
        pytest.skip(f"zone_get_status failed: {status_result.error}")

    initial = _get_zone_bypassed(live_e27_client, zone_id)
    if initial is None:
        pytest.skip("Zone not present in snapshot or bypass state unavailable.")

    target = not initial
    restored = False
    try:
        set_result = await live_e27_client.async_execute(
            "zone_set_status",
            zone_id=zone_id,
            pin=pin,
            bypassed=target,
            timeout_s=timeout_s,
        )
        if not set_result.ok:
            pytest.fail(f"zone_set_status bypass failed: {set_result.error}")
        await _wait_for_bypass_state(live_e27_client, zone_id, target, timeout_s)

        restore_result = await live_e27_client.async_execute(
            "zone_set_status",
            zone_id=zone_id,
            pin=pin,
            bypassed=initial,
            timeout_s=timeout_s,
        )
        if not restore_result.ok:
            pytest.fail(f"zone_set_status restore failed: {restore_result.error}")
        restored = True
        await _wait_for_bypass_state(live_e27_client, zone_id, initial, timeout_s)
    finally:
        if not restored:
            with contextlib.suppress(Exception):
                await live_e27_client.async_execute(
                    "zone_set_status",
                    zone_id=zone_id,
                    pin=pin,
                    bypassed=initial,
                    timeout_s=timeout_s,
                )
