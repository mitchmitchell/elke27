from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def deliver_panel_message(kernel: object, msg: Mapping[str, Any]) -> None:
    get_private(kernel, "_on_message")(msg)


def get_private(obj: object, name: str) -> Any:
    return getattr(obj, name)


def set_private(obj: object, name: str, value: Any) -> None:
    setattr(obj, name, value)


def get_kernel(client: object) -> Any:
    return get_private(client, "_kernel")
