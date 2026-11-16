from __future__ import annotations

from typing import Any

from elke27_lib.client import Elke27Client


def get_private(obj: object, name: str) -> Any:
    return getattr(obj, name)


def set_private(obj: object, name: str, value: Any) -> None:
    setattr(obj, name, value)


def get_kernel(client: object) -> Any:
    return get_private(client, "_kernel")


def deliver_panel_message(kernel: object, msg: dict[str, object]) -> None:
    get_private(kernel, "_on_message")(msg)


def reply_publication_slot_count(client: object) -> int:
    if not isinstance(client, Elke27Client):
        raise TypeError(f"expected Elke27Client, got {type(client).__name__}")
    return len(get_private(client, "_reply_publication_by_seq"))
