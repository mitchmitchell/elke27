from __future__ import annotations

import pytest

from elke27_lib.client import Elke27Client
from test.helpers.payload_validation import assert_payload_shape


async def _resolve_file_room_tstat_id(client: Elke27Client) -> int:
    expected_name = "file room"

    configured = await client.async_execute("tstat_get_configured")
    if not configured.ok:
        pytest.fail(f"tstat_get_configured failed: {configured.error}")
    assert_payload_shape("tstat_get_configured", configured.data)

    tstats = configured.data.get("tstats") if configured.data else None
    if not isinstance(tstats, list) or not tstats:
        pytest.fail(f"No configured thermostats found; configured tstats={tstats!r}")

    for tstat_id in tstats:
        if not isinstance(tstat_id, int) or tstat_id < 1:
            continue
        attribs = await client.async_execute("tstat_get_attribs", tstat_id=tstat_id)
        if not attribs.ok:
            continue
        assert_payload_shape("tstat_get_attribs", attribs.data)
        name = str((attribs.data or {}).get("name", "")).strip().lower()
        if name == expected_name:
            return tstat_id

    pytest.fail(f"Unable to resolve thermostat '{expected_name}' from configured tstats={tstats!r}")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_file_room_tstat_status_and_set_mode(live_e27_client: Elke27Client) -> None:
    tstat_id = await _resolve_file_room_tstat_id(live_e27_client)

    attribs = await live_e27_client.async_execute("tstat_get_attribs", tstat_id=tstat_id)
    if not attribs.ok:
        pytest.fail(f"tstat_get_attribs failed: {attribs.error}")
    assert_payload_shape("tstat_get_attribs", attribs.data)

    status_before = await live_e27_client.async_execute("tstat_get_status", tstat_id=tstat_id)
    if not status_before.ok:
        pytest.fail(f"tstat_get_status (before) failed: {status_before.error}")
    assert_payload_shape("tstat_get_status", status_before.data)

    before_mode_obj = (status_before.data or {}).get("mode")
    mode = before_mode_obj if isinstance(before_mode_obj, str) and before_mode_obj else "AUTO"
    set_result = await live_e27_client.async_execute(
        "tstat_set_status",
        tstat_id=tstat_id,
        mode=mode,
    )
    if not set_result.ok:
        pytest.fail(f"tstat_set_status failed: {set_result.error}")
    assert_payload_shape("tstat_set_status", set_result.data)

    status_after = await live_e27_client.async_execute("tstat_get_status", tstat_id=tstat_id)
    if not status_after.ok:
        pytest.fail(f"tstat_get_status (after) failed: {status_after.error}")
    assert_payload_shape("tstat_get_status", status_after.data)
