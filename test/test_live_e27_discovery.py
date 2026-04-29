from __future__ import annotations

import pytest

from elke27_lib.client import Elke27Client
from test.conftest import get_env


@pytest.mark.live_e27
@pytest.mark.asyncio
async def test_live_discovery_finds_two_panels() -> None:
    if get_env("ELKE27_LIVE") != "1":
        pytest.skip("ELKE27_LIVE not set; skipping live E27 tests.")

    client = Elke27Client()
    try:
        panels = await client.async_discover(timeout_s=5.0)
    finally:
        await client.async_disconnect()

    discovered = [
        {
            "host": panel.host,
            "port": panel.port,
            "name": panel.panel_name,
            "serial": panel.panel_serial,
            "mac": panel.panel_mac,
        }
        for panel in panels
    ]

    assert len(panels) == 2, f"Expected 2 panels, found {len(panels)}: {discovered!r}"
