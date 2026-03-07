"""Light domain request generators."""

from __future__ import annotations

ResponseKey = tuple[str, str]


def generator_light_get_table_info() -> tuple[dict[str, object], ResponseKey]:
    return {}, ("light", "get_table_info")


def generator_light_get_configured(*, block_id: int = 1) -> tuple[dict[str, object], ResponseKey]:
    if block_id < 1:
        raise ValueError(f"block_id must be an int >= 1 (got {block_id!r})")
    return {"block_id": block_id}, ("light", "get_configured")


def generator_light_get_attribs(*, light_id: int) -> tuple[dict[str, object], ResponseKey]:
    if light_id < 1:
        raise ValueError(f"light_id must be an int >= 1 (got {light_id!r})")
    return {"light_id": light_id}, ("light", "get_attribs")


def generator_light_get_status(*, light_id: int) -> tuple[dict[str, object], ResponseKey]:
    if light_id < 1:
        raise ValueError(f"light_id must be an int >= 1 (got {light_id!r})")
    return {"light_id": light_id}, ("light", "get_status")


def generator_light_set_status(
    *,
    light_id: int,
    status: str | None = None,
    level: int | None = None,
) -> tuple[dict[str, object], ResponseKey]:
    if light_id < 1:
        raise ValueError(f"light_id must be an int >= 1 (got {light_id!r})")
    payload: dict[str, object] = {"light_id": light_id}
    if status is not None:
        normalized = status.strip().upper()
        if normalized not in {"ON", "OFF"}:
            raise ValueError(f"status must be 'ON' or 'OFF' (got {status!r})")
        payload["status"] = normalized
    if level is not None:
        if not isinstance(level, int) or level < 0 or level > 100:
            raise ValueError(f"level must be int in [0, 100] (got {level!r})")
        payload["level"] = level
    if len(payload) == 1:
        raise ValueError("light_set_status requires status and/or level")
    return payload, ("light", "set_status")
