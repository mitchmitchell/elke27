"""Lock domain request generators."""

from __future__ import annotations

ResponseKey = tuple[str, str]


def generator_lock_get_table_info() -> tuple[dict[str, object], ResponseKey]:
    return {}, ("lock", "get_table_info")


def generator_lock_get_configured(*, block_id: int = 1) -> tuple[dict[str, object], ResponseKey]:
    if block_id < 1:
        raise ValueError(f"block_id must be an int >= 1 (got {block_id!r})")
    return {"block_id": block_id}, ("lock", "get_configured")


def generator_lock_get_attribs(*, lock_id: int) -> tuple[dict[str, object], ResponseKey]:
    if lock_id < 1:
        raise ValueError(f"lock_id must be an int >= 1 (got {lock_id!r})")
    return {"lock_id": lock_id}, ("lock", "get_attribs")


def generator_lock_get_status(*, lock_id: int) -> tuple[dict[str, object], ResponseKey]:
    if lock_id < 1:
        raise ValueError(f"lock_id must be an int >= 1 (got {lock_id!r})")
    return {"lock_id": lock_id}, ("lock", "get_status")


def generator_lock_set_status(
    *, lock_id: int, status: str
) -> tuple[dict[str, object], ResponseKey]:
    if lock_id < 1:
        raise ValueError(f"lock_id must be an int >= 1 (got {lock_id!r})")
    normalized = status.strip().upper()
    if normalized not in {"ON", "OFF"}:
        raise ValueError(f"status must be ON/OFF (got {status!r})")
    return {"lock_id": lock_id, "status": normalized}, ("lock", "set_status")
