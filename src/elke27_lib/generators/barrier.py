"""Barrier domain request generators."""

from __future__ import annotations

ResponseKey = tuple[str, str]


def generator_barrier_get_table_info() -> tuple[dict[str, object], ResponseKey]:
    return {}, ("barrier", "get_table_info")


def generator_barrier_get_configured(*, block_id: int = 1) -> tuple[dict[str, object], ResponseKey]:
    if block_id < 1:
        raise ValueError(f"block_id must be an int >= 1 (got {block_id!r})")
    return {"block_id": block_id}, ("barrier", "get_configured")


def generator_barrier_get_attribs(*, barrier_id: int) -> tuple[dict[str, object], ResponseKey]:
    if barrier_id < 1:
        raise ValueError(f"barrier_id must be an int >= 1 (got {barrier_id!r})")
    return {"barrier_id": barrier_id}, ("barrier", "get_attribs")


def generator_barrier_get_status(*, barrier_id: int) -> tuple[dict[str, object], ResponseKey]:
    if barrier_id < 1:
        raise ValueError(f"barrier_id must be an int >= 1 (got {barrier_id!r})")
    return {"barrier_id": barrier_id}, ("barrier", "get_status")


def generator_barrier_set_status(
    *, barrier_id: int, status: str
) -> tuple[dict[str, object], ResponseKey]:
    if barrier_id < 1:
        raise ValueError(f"barrier_id must be an int >= 1 (got {barrier_id!r})")
    normalized = status.strip().upper()
    if normalized not in {"OPEN", "CLOSE", "STOP"}:
        raise ValueError(f"status must be OPEN/CLOSE/STOP (got {status!r})")
    return {"barrier_id": barrier_id, "status": normalized}, ("barrier", "set_status")
