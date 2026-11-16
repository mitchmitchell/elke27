from __future__ import annotations

from typing import Any


def get_private(obj: object, name: str) -> Any:
    return getattr(obj, name)


def set_private(obj: object, name: str, value: Any) -> None:
    setattr(obj, name, value)


def get_kernel(client: object) -> Any:
    return get_private(client, "_kernel")


def deliver_panel_message(kernel: object, msg: dict[str, object]) -> None:
    get_private(kernel, "_on_message")(msg)


def session_disconnect(kernel: object, err: BaseException) -> None:
    get_private(kernel, "state").panel.connected = True
    get_private(kernel, "_on_session_disconnected")(err)
