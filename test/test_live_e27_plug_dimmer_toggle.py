from __future__ import annotations

import pytest

from elke27_lib.client import Elke27Client
from test.helpers.payload_validation import assert_payload_shape


async def _resolve_plug_dimmer_light_id(client: Elke27Client) -> int:
    expected_name = "plug dimmer"
    target_zw_id = 2

    configured = await client.async_execute("light_get_configured")
    if not configured.ok:
        pytest.fail(f"light_get_configured failed: {configured.error}")
    assert_payload_shape("light_get_configured", configured.data)

    lights = configured.data.get("lights") if configured.data else None
    if not isinstance(lights, list) or not lights:
        pytest.fail(f"No configured lights found; configured lights={lights!r}")

    for light_id in lights:
        if not isinstance(light_id, int) or light_id < 1:
            continue
        attribs = await client.async_execute("light_get_attribs", light_id=light_id)
        if not attribs.ok:
            continue
        assert_payload_shape("light_get_attribs", attribs.data)
        name = str((attribs.data or {}).get("name", "")).strip().lower()
        source_id = (attribs.data or {}).get("source_id")
        zw_id = source_id - 256 if isinstance(source_id, int) and source_id >= 256 else None
        if name == expected_name or zw_id == target_zw_id:
            return light_id

    pytest.fail(
        f"Unable to resolve '{expected_name}' / ZW-ID {target_zw_id} from configured lights={lights!r}"
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_light_set_on_level_plug_dimmer_zw_id_2(
    live_e27_client: Elke27Client,
) -> None:
    target_id = await _resolve_plug_dimmer_light_id(live_e27_client)

    set_on = await live_e27_client.async_execute(
        "light_set_status",
        light_id=target_id,
        status="ON",
        level=50,
    )
    if not set_on.ok:
        pytest.fail(f"light_set_status ON failed: {set_on.error}")
    assert_payload_shape("light_set_status", set_on.data)

    status_on = await live_e27_client.async_execute("light_get_status", light_id=target_id)
    if not status_on.ok:
        pytest.fail(f"light_get_status after ON failed: {status_on.error}")
    assert_payload_shape("light_get_status", status_on.data)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_light_set_off_plug_dimmer_zw_id_2(live_e27_client: Elke27Client) -> None:
    target_id = await _resolve_plug_dimmer_light_id(live_e27_client)

    set_off = await live_e27_client.async_execute(
        "light_set_status",
        light_id=target_id,
        status="OFF",
        level=0,
    )
    if not set_off.ok:
        pytest.fail(f"light_set_status OFF failed: {set_off.error}")
    assert_payload_shape("light_set_status", set_off.data)

    status_off = await live_e27_client.async_execute("light_get_status", light_id=target_id)
    if not status_off.ok:
        pytest.fail(f"light_get_status after OFF failed: {status_off.error}")
    assert_payload_shape("light_get_status", status_off.data)
