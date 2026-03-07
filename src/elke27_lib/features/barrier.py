"""
elke27_lib/features/barrier.py

Feature module: barrier
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from elke27_lib.dispatcher import PagedTransferKey

if TYPE_CHECKING:
    from elke27_lib.kernel import E27Kernel

from elke27_lib.handlers.barrier import (
    make_barrier_configured_merge,
    make_barrier_get_attribs_handler,
    make_barrier_get_configured_handler,
    make_barrier_get_status_handler,
    make_barrier_get_table_info_handler,
    make_barrier_set_status_handler,
)

ROUTE_BARRIER_GET_STATUS = ("barrier", "get_status")
ROUTE_BARRIER_SET_STATUS = ("barrier", "set_status")
ROUTE_BARRIER_GET_TABLE_INFO = ("barrier", "get_table_info")
ROUTE_BARRIER_TABLE_INFO = ("barrier", "table_info")
ROUTE_BARRIER_GET_ATTRIBS = ("barrier", "get_attribs")
ROUTE_BARRIER_GET_CONFIGURED = ("barrier", "get_configured")


def register(elk: E27Kernel) -> None:
    def request_configured_block(block_id: int, transfer_key: PagedTransferKey) -> None:
        elk.request(
            ROUTE_BARRIER_GET_CONFIGURED,
            block_id=block_id,
            opaque=transfer_key,
        )

    elk.register_handler(
        ROUTE_BARRIER_GET_STATUS,
        make_barrier_get_status_handler(elk.state, elk.emit, elk.now),
    )
    elk.register_handler(
        ROUTE_BARRIER_SET_STATUS,
        make_barrier_set_status_handler(elk.state, elk.emit, elk.now),
    )
    elk.register_handler(
        ROUTE_BARRIER_GET_CONFIGURED,
        make_barrier_get_configured_handler(elk.state, elk.emit, elk.now),
    )
    elk.register_handler(
        ROUTE_BARRIER_GET_ATTRIBS,
        make_barrier_get_attribs_handler(elk.state, elk.emit, elk.now),
    )
    elk.register_handler(
        ROUTE_BARRIER_GET_TABLE_INFO,
        make_barrier_get_table_info_handler(elk.state, elk.emit, elk.now),
    )
    elk.register_handler(
        ROUTE_BARRIER_TABLE_INFO,
        make_barrier_get_table_info_handler(elk.state, elk.emit, elk.now),
    )

    elk.register_paged(
        ROUTE_BARRIER_GET_CONFIGURED,
        merge_fn=make_barrier_configured_merge(elk.state),
        request_block=request_configured_block,
    )

    elk.register_request(ROUTE_BARRIER_GET_STATUS, build_barrier_get_status_payload)
    elk.register_request(ROUTE_BARRIER_SET_STATUS, build_barrier_set_status_payload)
    elk.register_request(ROUTE_BARRIER_GET_CONFIGURED, build_barrier_get_configured_payload)
    elk.register_request(ROUTE_BARRIER_GET_ATTRIBS, build_barrier_get_attribs_payload)
    elk.register_request(ROUTE_BARRIER_GET_TABLE_INFO, build_barrier_get_table_info_payload)


def build_barrier_get_status_payload(*, barrier_id: int, **_kwargs: Any) -> Mapping[str, Any]:
    if barrier_id < 1:
        raise ValueError(
            f"build_barrier_get_status_payload: barrier_id must be int >= 1 (got {barrier_id!r})"
        )
    return {"barrier_id": barrier_id}


def build_barrier_set_status_payload(
    *, barrier_id: int, status: str, **_kwargs: Any
) -> Mapping[str, Any]:
    if barrier_id < 1:
        raise ValueError(
            f"build_barrier_set_status_payload: barrier_id must be int >= 1 (got {barrier_id!r})"
        )
    normalized = status.strip().upper()
    if normalized not in {"OPEN", "CLOSE", "STOP"}:
        raise ValueError(f"build_barrier_set_status_payload: invalid status {status!r}")
    return {"barrier_id": barrier_id, "status": normalized}


def build_barrier_get_attribs_payload(*, barrier_id: int, **_kwargs: Any) -> Mapping[str, Any]:
    if barrier_id < 1:
        raise ValueError(
            f"build_barrier_get_attribs_payload: barrier_id must be int >= 1 (got {barrier_id!r})"
        )
    return {"barrier_id": barrier_id}


def build_barrier_get_table_info_payload(**_kwargs: Any) -> Mapping[str, Any]:
    return {}


def build_barrier_get_configured_payload(*, block_id: int = 1, **_kwargs: Any) -> Mapping[str, Any]:
    if block_id < 1:
        raise ValueError(
            f"build_barrier_get_configured_payload: block_id must be int >= 1 (got {block_id!r})"
        )
    return {"block_id": block_id}
