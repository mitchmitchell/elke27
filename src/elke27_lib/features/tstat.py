"""
elke27_lib/features/tstat.py

Feature module: tstat
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from elke27_lib.dispatcher import PagedTransferKey

if TYPE_CHECKING:
    from elke27_lib.kernel import E27Kernel

from elke27_lib.handlers.tstat import (
    make_tstat_configured_merge,
    make_tstat_get_attribs_handler,
    make_tstat_get_configured_handler,
    make_tstat_get_status_handler,
    make_tstat_get_table_info_handler,
    make_tstat_set_status_handler,
)

ROUTE_TSTAT_GET_STATUS = ("tstat", "get_status")
ROUTE_TSTAT_SET_STATUS = ("tstat", "set_status")
ROUTE_TSTAT_GET_CONFIGURED = ("tstat", "get_configured")
ROUTE_TSTAT_GET_ATTRIBS = ("tstat", "get_attribs")
ROUTE_TSTAT_GET_TABLE_INFO = ("tstat", "get_table_info")
ROUTE_TSTAT_TABLE_INFO = ("tstat", "table_info")


def register(elk: E27Kernel) -> None:
    def request_configured_block(block_id: int, transfer_key: PagedTransferKey) -> None:
        elk.request(
            ROUTE_TSTAT_GET_CONFIGURED,
            block_id=block_id,
            opaque=transfer_key,
        )

    elk.register_handler(
        ROUTE_TSTAT_GET_STATUS,
        make_tstat_get_status_handler(elk.state, elk.emit, elk.now),
    )
    elk.register_handler(
        ROUTE_TSTAT_SET_STATUS,
        make_tstat_set_status_handler(elk.state, elk.emit, elk.now),
    )
    elk.register_handler(
        ROUTE_TSTAT_GET_CONFIGURED,
        make_tstat_get_configured_handler(elk.state, elk.emit, elk.now),
    )
    elk.register_handler(
        ROUTE_TSTAT_GET_ATTRIBS,
        make_tstat_get_attribs_handler(elk.state, elk.emit, elk.now),
    )
    elk.register_handler(
        ROUTE_TSTAT_GET_TABLE_INFO,
        make_tstat_get_table_info_handler(elk.state, elk.emit, elk.now),
    )
    elk.register_handler(
        ROUTE_TSTAT_TABLE_INFO,
        make_tstat_get_table_info_handler(elk.state, elk.emit, elk.now),
    )
    elk.register_paged(
        ROUTE_TSTAT_GET_CONFIGURED,
        merge_fn=make_tstat_configured_merge(elk.state),
        request_block=request_configured_block,
    )
    elk.register_request(
        ROUTE_TSTAT_GET_STATUS,
        build_tstat_get_status_payload,
    )
    elk.register_request(
        ROUTE_TSTAT_SET_STATUS,
        build_tstat_set_status_payload,
    )
    elk.register_request(
        ROUTE_TSTAT_GET_CONFIGURED,
        build_tstat_get_configured_payload,
    )
    elk.register_request(
        ROUTE_TSTAT_GET_ATTRIBS,
        build_tstat_get_attribs_payload,
    )
    elk.register_request(
        ROUTE_TSTAT_GET_TABLE_INFO,
        build_tstat_get_table_info_payload,
    )


def build_tstat_get_status_payload(*, tstat_id: int, **_kwargs: Any) -> Mapping[str, Any]:
    if tstat_id < 1:
        raise ValueError(
            f"build_tstat_get_status_payload: tstat_id must be int >= 1 (got {tstat_id!r})"
        )
    return {"tstat_id": tstat_id}


def build_tstat_set_status_payload(
    *,
    tstat_id: int,
    mode: str | None = None,
    fan_mode: str | None = None,
    cool_setpoint: int | None = None,
    heat_setpoint: int | None = None,
    **_kwargs: Any,
) -> Mapping[str, Any]:
    if tstat_id < 1:
        raise ValueError(
            f"build_tstat_set_status_payload: tstat_id must be int >= 1 (got {tstat_id!r})"
        )
    payload: dict[str, Any] = {"tstat_id": tstat_id}
    if mode is not None:
        payload["mode"] = mode
    if fan_mode is not None:
        payload["fan_mode"] = fan_mode
    if cool_setpoint is not None:
        payload["cool_setpoint"] = cool_setpoint
    if heat_setpoint is not None:
        payload["heat_setpoint"] = heat_setpoint
    if len(payload) == 1:
        raise ValueError("build_tstat_set_status_payload requires at least one status field")
    return payload


def build_tstat_get_configured_payload(*, block_id: int = 1, **_kwargs: Any) -> Mapping[str, Any]:
    if block_id < 1:
        raise ValueError(
            f"build_tstat_get_configured_payload: block_id must be int >= 1 (got {block_id!r})"
        )
    return {"block_id": block_id}


def build_tstat_get_attribs_payload(*, tstat_id: int, **_kwargs: Any) -> Mapping[str, Any]:
    if tstat_id < 1:
        raise ValueError(
            f"build_tstat_get_attribs_payload: tstat_id must be int >= 1 (got {tstat_id!r})"
        )
    return {"tstat_id": tstat_id}


def build_tstat_get_table_info_payload(**_kwargs: Any) -> Mapping[str, Any]:
    return {}
