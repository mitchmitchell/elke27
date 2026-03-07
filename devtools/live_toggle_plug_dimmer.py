from __future__ import annotations

import asyncio
import os

from elke27_lib import linking
from elke27_lib.client import Elke27Client

TARGET_NAME = "plug dimmer"
TARGET_ID_HINT = 2


def req(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing env var: {name}")
    return value


async def _main() -> None:
    host = req("ELKE27_HOST")
    port = int(os.environ.get("ELKE27_PORT", "2101"))
    access_code = req("ELKE27_ACCESS_CODE")
    passphrase = req("ELKE27_PASSPHRASE")
    mn = req("ELKE27_MN")
    sn = req("ELKE27_SN")
    fwver = req("ELKE27_FWVER")
    hwver = req("ELKE27_HWVER")
    osver = req("ELKE27_OSVER")

    identity = linking.E27Identity(mn=mn, sn=sn, fwver=fwver, hwver=hwver, osver=osver)
    client = Elke27Client()

    link_keys = await client.async_link(
        host,
        port,
        access_code=access_code,
        passphrase=passphrase,
        client_identity=identity,
        timeout_s=10.0,
    )
    await client.async_connect(host, port, link_keys)

    try:
        configured = await client.async_execute("light_get_configured", timeout_s=10.0)
        if not configured.ok or not configured.data:
            raise RuntimeError(f"light_get_configured failed: {configured.error}")

        ids = configured.data.get("lights")
        if not isinstance(ids, list):
            raise RuntimeError(f"Unexpected light_get_configured payload: {configured.data}")

        names: dict[int, str] = {}
        target_id: int | None = None
        for item in ids:
            if not isinstance(item, int) or item < 1:
                continue
            attribs = await client.async_execute("light_get_attribs", light_id=item, timeout_s=10.0)
            if not attribs.ok or not attribs.data:
                continue
            name = str(attribs.data.get("name") or "").strip()
            names[item] = name
            if name.lower() == TARGET_NAME:
                target_id = item

        if target_id is None and TARGET_ID_HINT in names:
            target_id = TARGET_ID_HINT
        if target_id is None:
            raise RuntimeError(f"Did not find '{TARGET_NAME}'. Lights seen: {names}")

        print(f"Using light_id={target_id} name='{names.get(target_id, '')}'")

        on = await client.async_execute(
            "light_set_status",
            light_id=target_id,
            status="ON",
            level=100,
            timeout_s=10.0,
        )
        if not on.ok:
            raise RuntimeError(f"light_set_status ON failed: {on.error}")
        print(f"ON ack: {on.data}")

        status_on = await client.async_execute(
            "light_get_status", light_id=target_id, timeout_s=10.0
        )
        print(f"After ON status: ok={status_on.ok} data={status_on.data} err={status_on.error}")

        off = await client.async_execute(
            "light_set_status",
            light_id=target_id,
            status="OFF",
            level=0,
            timeout_s=10.0,
        )
        if not off.ok:
            raise RuntimeError(f"light_set_status OFF failed: {off.error}")
        print(f"OFF ack: {off.data}")

        status_off = await client.async_execute(
            "light_get_status", light_id=target_id, timeout_s=10.0
        )
        print(f"After OFF status: ok={status_off.ok} data={status_off.data} err={status_off.error}")
    finally:
        await client.async_disconnect()


if __name__ == "__main__":
    asyncio.run(_main())
