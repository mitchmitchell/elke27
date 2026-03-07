"""
elke27_lib/features/lock.py

Feature module: lock
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from elke27_lib.dispatcher import PagedTransferKey

if TYPE_CHECKING:
    from elke27_lib.kernel import E27Kernel

from elke27_lib.handlers.lock import (
    make_lock_configured_merge,
    make_lock_get_attribs_handler,
    make_lock_get_configured_handler,
    make_lock_get_status_handler,
    make_lock_get_table_info_handler,
    make_lock_set_status_handler,
)

ROUTE_LOCK_GET_STATUS = ("lock", "get_status")
ROUTE_LOCK_SET_STATUS = ("lock", "set_status")
ROUTE_LOCK_GET_TABLE_INFO = ("lock", "get_table_info")
ROUTE_LOCK_TABLE_INFO = ("lock", "table_info")
ROUTE_LOCK_GET_ATTRIBS = ("lock", "get_attribs")
ROUTE_LOCK_GET_CONFIGURED = ("lock", "get_configured")


def register(elk: E27Kernel) -> None:
    def request_configured_block(block_id: int, transfer_key: PagedTransferKey) -> None:
        elk.request(
            ROUTE_LOCK_GET_CONFIGURED,
            block_id=block_id,
            opaque=transfer_key,
        )

    elk.register_handler(
        ROUTE_LOCK_GET_STATUS,
        make_lock_get_status_handler(elk.state, elk.emit, elk.now),
    )
    elk.register_handler(
        ROUTE_LOCK_SET_STATUS,
        make_lock_set_status_handler(elk.state, elk.emit, elk.now),
    )
    elk.register_handler(
        ROUTE_LOCK_GET_CONFIGURED,
        make_lock_get_configured_handler(elk.state, elk.emit, elk.now),
    )
    elk.register_handler(
        ROUTE_LOCK_GET_ATTRIBS,
        make_lock_get_attribs_handler(elk.state, elk.emit, elk.now),
    )
    elk.register_handler(
        ROUTE_LOCK_GET_TABLE_INFO,
        make_lock_get_table_info_handler(elk.state, elk.emit, elk.now),
    )
    elk.register_handler(
        ROUTE_LOCK_TABLE_INFO,
        make_lock_get_table_info_handler(elk.state, elk.emit, elk.now),
    )

    elk.register_paged(
        ROUTE_LOCK_GET_CONFIGURED,
        merge_fn=make_lock_configured_merge(elk.state),
        request_block=request_configured_block,
    )

    elk.register_request(ROUTE_LOCK_GET_STATUS, build_lock_get_status_payload)
    elk.register_request(ROUTE_LOCK_SET_STATUS, build_lock_set_status_payload)
    elk.register_request(ROUTE_LOCK_GET_CONFIGURED, build_lock_get_configured_payload)
    elk.register_request(ROUTE_LOCK_GET_ATTRIBS, build_lock_get_attribs_payload)
    elk.register_request(ROUTE_LOCK_GET_TABLE_INFO, build_lock_get_table_info_payload)


def build_lock_get_status_payload(*, lock_id: int, **_kwargs: Any) -> Mapping[str, Any]:
    if lock_id < 1:
        raise ValueError(
            f"build_lock_get_status_payload: lock_id must be int >= 1 (got {lock_id!r})"
        )
    return {"lock_id": lock_id}


def build_lock_set_status_payload(
    *, lock_id: int, status: str, **_kwargs: Any
) -> Mapping[str, Any]:
    if lock_id < 1:
        raise ValueError(
            f"build_lock_set_status_payload: lock_id must be int >= 1 (got {lock_id!r})"
        )
    normalized = status.strip().upper()
    if normalized not in {"ON", "OFF"}:
        raise ValueError(f"build_lock_set_status_payload: invalid status {status!r}")
    return {"lock_id": lock_id, "status": normalized}


def build_lock_get_attribs_payload(*, lock_id: int, **_kwargs: Any) -> Mapping[str, Any]:
    if lock_id < 1:
        raise ValueError(
            f"build_lock_get_attribs_payload: lock_id must be int >= 1 (got {lock_id!r})"
        )
    return {"lock_id": lock_id}


def build_lock_get_table_info_payload(**_kwargs: Any) -> Mapping[str, Any]:
    return {}


def build_lock_get_configured_payload(*, block_id: int = 1, **_kwargs: Any) -> Mapping[str, Any]:
    if block_id < 1:
        raise ValueError(
            f"build_lock_get_configured_payload: block_id must be int >= 1 (got {block_id!r})"
        )
    return {"block_id": block_id}
