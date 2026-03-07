"""
elke27_lib/features/light.py

Feature module: light
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from elke27_lib.dispatcher import PagedTransferKey

if TYPE_CHECKING:
    from elke27_lib.kernel import E27Kernel

from elke27_lib.handlers.light import (
    make_light_configured_merge,
    make_light_get_attribs_handler,
    make_light_get_configured_handler,
    make_light_get_status_handler,
    make_light_get_table_info_handler,
    make_light_set_status_handler,
)

ROUTE_LIGHT_GET_STATUS = ("light", "get_status")
ROUTE_LIGHT_SET_STATUS = ("light", "set_status")
ROUTE_LIGHT_GET_TABLE_INFO = ("light", "get_table_info")
ROUTE_LIGHT_TABLE_INFO = ("light", "table_info")
ROUTE_LIGHT_GET_ATTRIBS = ("light", "get_attribs")
ROUTE_LIGHT_GET_CONFIGURED = ("light", "get_configured")


def register(elk: E27Kernel) -> None:
    def request_configured_block(block_id: int, transfer_key: PagedTransferKey) -> None:
        elk.request(
            ROUTE_LIGHT_GET_CONFIGURED,
            block_id=block_id,
            opaque=transfer_key,
        )

    elk.register_handler(
        ROUTE_LIGHT_GET_STATUS,
        make_light_get_status_handler(elk.state, elk.emit, elk.now),
    )
    elk.register_handler(
        ROUTE_LIGHT_SET_STATUS,
        make_light_set_status_handler(elk.state, elk.emit, elk.now),
    )
    elk.register_handler(
        ROUTE_LIGHT_GET_CONFIGURED,
        make_light_get_configured_handler(elk.state, elk.emit, elk.now),
    )
    elk.register_handler(
        ROUTE_LIGHT_GET_ATTRIBS,
        make_light_get_attribs_handler(elk.state, elk.emit, elk.now),
    )
    elk.register_handler(
        ROUTE_LIGHT_GET_TABLE_INFO,
        make_light_get_table_info_handler(elk.state, elk.emit, elk.now),
    )
    elk.register_handler(
        ROUTE_LIGHT_TABLE_INFO,
        make_light_get_table_info_handler(elk.state, elk.emit, elk.now),
    )

    elk.register_paged(
        ROUTE_LIGHT_GET_CONFIGURED,
        merge_fn=make_light_configured_merge(elk.state),
        request_block=request_configured_block,
    )

    elk.register_request(ROUTE_LIGHT_GET_STATUS, build_light_get_status_payload)
    elk.register_request(ROUTE_LIGHT_SET_STATUS, build_light_set_status_payload)
    elk.register_request(ROUTE_LIGHT_GET_CONFIGURED, build_light_get_configured_payload)
    elk.register_request(ROUTE_LIGHT_GET_ATTRIBS, build_light_get_attribs_payload)
    elk.register_request(ROUTE_LIGHT_GET_TABLE_INFO, build_light_get_table_info_payload)


def build_light_get_status_payload(*, light_id: int, **_kwargs: Any) -> Mapping[str, Any]:
    if light_id < 1:
        raise ValueError(
            f"build_light_get_status_payload: light_id must be int >= 1 (got {light_id!r})"
        )
    return {"light_id": light_id}


def build_light_set_status_payload(
    *,
    light_id: int,
    status: str | None = None,
    level: int | None = None,
    **_kwargs: Any,
) -> Mapping[str, Any]:
    if light_id < 1:
        raise ValueError(
            f"build_light_set_status_payload: light_id must be int >= 1 (got {light_id!r})"
        )
    payload: dict[str, Any] = {"light_id": light_id}
    if status is not None:
        normalized = status.strip().upper()
        if normalized not in {"ON", "OFF"}:
            raise ValueError(f"build_light_set_status_payload: invalid status {status!r}")
        payload["status"] = normalized
    if level is not None:
        if not isinstance(level, int) or not (0 <= level <= 100):
            raise ValueError(
                f"build_light_set_status_payload: level must be 0..100 (got {level!r})"
            )
        payload["level"] = level
    if len(payload) == 1:
        raise ValueError("build_light_set_status_payload: status or level required")
    return payload


def build_light_get_attribs_payload(*, light_id: int, **_kwargs: Any) -> Mapping[str, Any]:
    if light_id < 1:
        raise ValueError(
            f"build_light_get_attribs_payload: light_id must be int >= 1 (got {light_id!r})"
        )
    return {"light_id": light_id}


def build_light_get_table_info_payload(**_kwargs: Any) -> Mapping[str, Any]:
    return {}


def build_light_get_configured_payload(*, block_id: int = 1, **_kwargs: Any) -> Mapping[str, Any]:
    if block_id < 1:
        raise ValueError(
            f"build_light_get_configured_payload: block_id must be int >= 1 (got {block_id!r})"
        )
    return {"block_id": block_id}
