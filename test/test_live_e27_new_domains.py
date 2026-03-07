"""
Live E27 tests for expanded runtime domains.

These are env-gated by the live fixture and are safe-by-default (read-only).
Writes (set_status) run only when ELKE27_LIVE_WRITES=1.
"""

from __future__ import annotations

import os

import pytest

from elke27_lib.client import Elke27Client
from test.helpers.error_codes import describe_error, extract_error_code
from test.helpers.payload_validation import assert_payload_shape


def _write_enabled() -> bool:
    return os.environ.get("ELKE27_LIVE_WRITES", "0") == "1"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_light_barrier_lock_tstat_runtime(live_e27_client: Elke27Client) -> None:
    # Table info + configured inventory for new domains.
    domain_cmds = [
        ("light_get_table_info", "light_get_configured", "lights", "light_id"),
        ("barrier_get_table_info", "barrier_get_configured", "barriers", "barrier_id"),
        ("lock_get_table_info", "lock_get_configured", "locks", "lock_id"),
        ("tstat_get_table_info", "tstat_get_configured", "tstats", "tstat_id"),
    ]

    for table_key, configured_key, id_key, param in domain_cmds:
        table = await live_e27_client.async_execute(table_key)
        if not table.ok:
            pytest.fail(f"{table_key} failed: {describe_error(table.error)}")
        assert_payload_shape(table_key, table.data)

        configured = await live_e27_client.async_execute(configured_key)
        if not configured.ok:
            # Panels with no devices in domain may still return errors for configured calls.
            code = extract_error_code(configured.error)
            if code is not None:
                continue
            pytest.fail(f"{configured_key} failed: {describe_error(configured.error)}")
        assert_payload_shape(configured_key, configured.data)

        ids = configured.data.get(id_key) if configured.data else None
        if not isinstance(ids, list) or not ids:
            continue
        entity_id = next((item for item in ids if isinstance(item, int) and item >= 1), None)
        if entity_id is None:
            continue

        attribs_key = configured_key.replace("get_configured", "get_attribs")
        status_key = configured_key.replace("get_configured", "get_status")

        attribs = await live_e27_client.async_execute(attribs_key, **{param: entity_id})
        if attribs.ok:
            assert_payload_shape(attribs_key, attribs.data)

        status = await live_e27_client.async_execute(status_key, **{param: entity_id})
        if status.ok:
            assert_payload_shape(status_key, status.data)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_new_domain_set_status_ack_optional(live_e27_client: Elke27Client) -> None:
    if not _write_enabled():
        pytest.skip("ELKE27_LIVE_WRITES!=1; skipping live set_status for light/barrier/lock/tstat")

    # Light: set level without forcing hard on/off semantics.
    light_cfg = await live_e27_client.async_execute("light_get_configured")
    light_data = light_cfg.data
    if light_cfg.ok and isinstance(light_data, dict):
        lights = light_data.get("lights")
    else:
        lights = None
    if isinstance(lights, list) and lights:
        light_id = int(lights[0])
        light_set = await live_e27_client.async_execute(
            "light_set_status", light_id=light_id, level=50
        )
        if not light_set.ok:
            pytest.fail(f"light_set_status failed: {describe_error(light_set.error)}")
        assert_payload_shape("light_set_status", light_set.data)

    barrier_cfg = await live_e27_client.async_execute("barrier_get_configured")
    barrier_data = barrier_cfg.data
    if barrier_cfg.ok and isinstance(barrier_data, dict):
        barriers = barrier_data.get("barriers")
    else:
        barriers = None
    if isinstance(barriers, list) and barriers:
        barrier_id = int(barriers[0])
        barrier_set = await live_e27_client.async_execute(
            "barrier_set_status", barrier_id=barrier_id, status="STOP"
        )
        if not barrier_set.ok:
            pytest.fail(f"barrier_set_status failed: {describe_error(barrier_set.error)}")
        assert_payload_shape("barrier_set_status", barrier_set.data)

    lock_cfg = await live_e27_client.async_execute("lock_get_configured")
    lock_data = lock_cfg.data
    if lock_cfg.ok and isinstance(lock_data, dict):
        locks = lock_data.get("locks")
    else:
        locks = None
    if isinstance(locks, list) and locks:
        lock_id = int(locks[0])
        lock_set = await live_e27_client.async_execute(
            "lock_set_status", lock_id=lock_id, status="LOCK"
        )
        if not lock_set.ok:
            pytest.fail(f"lock_set_status failed: {describe_error(lock_set.error)}")
        assert_payload_shape("lock_set_status", lock_set.data)

    tstat_cfg = await live_e27_client.async_execute("tstat_get_configured")
    tstat_data = tstat_cfg.data
    if tstat_cfg.ok and isinstance(tstat_data, dict):
        tstats = tstat_data.get("tstats")
    else:
        tstats = None
    if isinstance(tstats, list) and tstats:
        tstat_id = int(tstats[0])
        tstat_set = await live_e27_client.async_execute(
            "tstat_set_status", tstat_id=tstat_id, mode="AUTO"
        )
        if not tstat_set.ok:
            pytest.fail(f"tstat_set_status failed: {describe_error(tstat_set.error)}")
        assert_payload_shape("tstat_set_status", tstat_set.data)
