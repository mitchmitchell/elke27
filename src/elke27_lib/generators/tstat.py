"""Tstat request generators."""

from __future__ import annotations

ResponseKey = tuple[str, str]
Setpoint = int | float


def generator_tstat_get_table_info() -> tuple[dict[str, object], ResponseKey]:
    return {}, ("tstat", "get_table_info")


def generator_tstat_get_status(*, tstat_id: int) -> tuple[dict[str, object], ResponseKey]:
    if tstat_id < 1:
        raise ValueError(f"tstat_id must be an int >= 1 (got {tstat_id!r})")
    return {"tstat_id": tstat_id}, ("tstat", "get_status")


def generator_tstat_get_configured(*, block_id: int = 1) -> tuple[dict[str, object], ResponseKey]:
    if block_id < 1:
        raise ValueError(f"block_id must be an int >= 1 (got {block_id!r})")
    return {"block_id": block_id}, ("tstat", "get_configured")


def generator_tstat_get_attribs(*, tstat_id: int) -> tuple[dict[str, object], ResponseKey]:
    if tstat_id < 1:
        raise ValueError(f"tstat_id must be an int >= 1 (got {tstat_id!r})")
    return {"tstat_id": tstat_id}, ("tstat", "get_attribs")


def generator_tstat_set_status(
    *,
    tstat_id: int,
    mode: str | None = None,
    fan_mode: str | None = None,
    cool_setpoint: Setpoint | None = None,
    heat_setpoint: Setpoint | None = None,
) -> tuple[dict[str, object], ResponseKey]:
    if tstat_id < 1:
        raise ValueError(f"tstat_id must be an int >= 1 (got {tstat_id!r})")
    payload: dict[str, object] = {"tstat_id": tstat_id}
    if mode is not None:
        payload["mode"] = mode
    if fan_mode is not None:
        payload["fan_mode"] = fan_mode
    if cool_setpoint is not None:
        payload["cool_setpoint"] = _encode_setpoint(cool_setpoint)
    if heat_setpoint is not None:
        payload["heat_setpoint"] = _encode_setpoint(heat_setpoint)
    if len(payload) == 1:
        raise ValueError("tstat_set_status requires at least one status field")
    return payload, ("tstat", "set_status")


def _encode_setpoint(value: Setpoint) -> int:
    """Encode public Fahrenheit setpoint degrees to E27 protocol tenths."""
    return round(value * 10)
