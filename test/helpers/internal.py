from __future__ import annotations

import asyncio
from typing import Any


def get_private(obj: object, name: str) -> Any:
    return getattr(obj, name)


def set_private(obj: object, name: str, value: Any) -> None:
    setattr(obj, name, value)


def get_kernel(client: object) -> Any:
    return get_private(client, "_kernel")


async def feed_panel_message(client: object, msg: dict[str, Any]) -> None:
    """Deliver one decrypted panel message to the client's kernel, as the transport would."""
    set_private(client, "_event_loop", asyncio.get_running_loop())
    kernel = get_kernel(client)
    if not getattr(kernel, "_features_loaded", False):
        kernel.load_features_blocking()
    get_private(kernel, "_on_message")(msg)
    await asyncio.sleep(0)
