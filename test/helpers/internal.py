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


def trigger_session_disconnect(kernel: Any, err: Exception) -> None:
    get_private(kernel, "_on_session_disconnected")(err)


def reply_publication_seq_active(client: object, seq: int) -> bool:
    return seq in get_private(client, "_reply_publication_by_seq")


def reply_publication_pending(client: object, seq: int) -> bool:
    fut = get_private(client, "_reply_publication_by_seq").get(seq)
    return fut is not None and not fut.done()
