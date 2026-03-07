"""
elke27_lib/handlers/barrier.py

Read/observe handlers for the "barrier" domain.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Any, cast

from elke27_lib.dispatcher import DispatchContext, PagedBlock
from elke27_lib.events import (
    UNSET_AT,
    UNSET_CLASSIFICATION,
    UNSET_ROUTE,
    UNSET_SEQ,
    UNSET_SESSION_ID,
    ApiError,
    AuthorizationRequiredEvent,
    BarrierConfiguredInventoryReady,
    BarrierConfiguredUpdated,
    BarrierStatusUpdated,
    BarrierTableInfoUpdated,
    BootstrapCountsReady,
    CsmSnapshotUpdated,
    Event,
    TableCsmChanged,
)
from elke27_lib.states import BarrierState, PanelState, update_csm_snapshot

EmitFn = Callable[[Event, DispatchContext], None]
NowFn = Callable[[], float]

LOG = logging.getLogger(__name__)


def _as_mapping(obj: object) -> Mapping[str, Any] | None:
    if isinstance(obj, Mapping):
        return cast(Mapping[str, Any], obj)
    return None


def _coerce_int(value: object) -> int | None:
    return value if isinstance(value, int) else None


def make_barrier_get_status_handler(state: PanelState, emit: EmitFn, now: NowFn):
    def handler_barrier_get_status(msg: Mapping[str, Any], ctx: DispatchContext) -> bool:
        barrier_obj = _as_mapping(msg.get("barrier"))
        if barrier_obj is None:
            return False
        payload = _as_mapping(barrier_obj.get("get_status"))
        if payload is None:
            return False

        error_code = payload.get("error_code")
        if isinstance(error_code, int) and error_code != 0:
            emit(
                ApiError(
                    kind=ApiError.KIND,
                    at=UNSET_AT,
                    seq=UNSET_SEQ,
                    classification=UNSET_CLASSIFICATION,
                    route=UNSET_ROUTE,
                    session_id=UNSET_SESSION_ID,
                    error_code=error_code,
                    scope="barrier",
                    entity_id=_coerce_int(payload.get("barrier_id")),
                    message=None,
                ),
                ctx,
            )
            return True

        barrier_id = payload.get("barrier_id")
        if not isinstance(barrier_id, int) or barrier_id < 1:
            return False

        barrier = state.get_or_create_barrier(barrier_id)
        _apply_barrier_status_fields(barrier, payload)
        barrier.last_update_at = now()
        state.panel.last_message_at = barrier.last_update_at

        emit(
            BarrierStatusUpdated(
                kind=BarrierStatusUpdated.KIND,
                at=UNSET_AT,
                seq=UNSET_SEQ,
                classification=UNSET_CLASSIFICATION,
                route=UNSET_ROUTE,
                session_id=UNSET_SESSION_ID,
                barrier_id=barrier_id,
                status=barrier.status,
            ),
            ctx,
        )
        return True

    return handler_barrier_get_status


def make_barrier_set_status_handler(state: PanelState, emit: EmitFn, now: NowFn):
    def handler_barrier_set_status(msg: Mapping[str, Any], ctx: DispatchContext) -> bool:
        barrier_obj = _as_mapping(msg.get("barrier"))
        if barrier_obj is None:
            return False
        payload = _as_mapping(barrier_obj.get("set_status"))
        if payload is None:
            return False

        barrier_id = payload.get("barrier_id")
        if not isinstance(barrier_id, int) or barrier_id < 1:
            return False

        barrier = state.get_or_create_barrier(barrier_id)
        _apply_barrier_status_fields(barrier, payload)
        barrier.last_update_at = now()
        state.panel.last_message_at = barrier.last_update_at

        emit(
            BarrierStatusUpdated(
                kind=BarrierStatusUpdated.KIND,
                at=UNSET_AT,
                seq=UNSET_SEQ,
                classification=UNSET_CLASSIFICATION,
                route=UNSET_ROUTE,
                session_id=UNSET_SESSION_ID,
                barrier_id=barrier_id,
                status=barrier.status,
            ),
            ctx,
        )
        return True

    return handler_barrier_set_status


def make_barrier_get_configured_handler(state: PanelState, emit: EmitFn, now: NowFn):
    def handler_barrier_get_configured(msg: Mapping[str, Any], ctx: DispatchContext) -> bool:
        barrier_obj = _as_mapping(msg.get("barrier"))
        if barrier_obj is None:
            return False
        payload = _as_mapping(barrier_obj.get("get_configured"))
        if payload is None:
            return False

        error_code = payload.get("error_code", barrier_obj.get("error_code"))
        if isinstance(error_code, int) and error_code != 0:
            if error_code == 11008:
                emit(
                    AuthorizationRequiredEvent(
                        kind=AuthorizationRequiredEvent.KIND,
                        at=UNSET_AT,
                        seq=UNSET_SEQ,
                        classification=UNSET_CLASSIFICATION,
                        route=UNSET_ROUTE,
                        session_id=UNSET_SESSION_ID,
                        error_code=error_code,
                        scope="barrier",
                        entity_id=None,
                        message=None,
                    ),
                    ctx,
                )
                return True
            emit(
                ApiError(
                    kind=ApiError.KIND,
                    at=UNSET_AT,
                    seq=UNSET_SEQ,
                    classification=UNSET_CLASSIFICATION,
                    route=UNSET_ROUTE,
                    session_id=UNSET_SESSION_ID,
                    error_code=error_code,
                    scope="barrier",
                    entity_id=None,
                    message=None,
                ),
                ctx,
            )
            return True

        ids = _extract_configured_ids(payload, ("barriers", "barrier_ids", "configured_barriers"))
        table_info = _as_mapping(state.table_info_by_domain.get("barrier"))
        if table_info is not None:
            max_id = table_info.get("table_elements")
            if isinstance(max_id, int) and max_id >= 1:
                ids = [entity_id for entity_id in ids if entity_id <= max_id]

        inv = state.inventory
        inv.configured_barriers = set(ids)
        inv.configured_barriers_complete = True
        state.panel.last_message_at = now()

        emit(
            BarrierConfiguredUpdated(
                kind=BarrierConfiguredUpdated.KIND,
                at=UNSET_AT,
                seq=UNSET_SEQ,
                classification=UNSET_CLASSIFICATION,
                route=UNSET_ROUTE,
                session_id=UNSET_SESSION_ID,
                configured_ids=tuple(sorted(ids)),
            ),
            ctx,
        )
        emit(
            BarrierConfiguredInventoryReady(
                kind=BarrierConfiguredInventoryReady.KIND,
                at=UNSET_AT,
                seq=UNSET_SEQ,
                classification=UNSET_CLASSIFICATION,
                route=UNSET_ROUTE,
                session_id=UNSET_SESSION_ID,
            ),
            ctx,
        )
        return True

    return handler_barrier_get_configured


def make_barrier_configured_merge(_state: PanelState):
    def _merge(blocks: list[PagedBlock], block_count: int) -> Mapping[str, Any]:
        merged: set[int] = set()
        for block in blocks:
            for entity_id in _extract_configured_ids(
                block.payload, ("barriers", "barrier_ids", "configured_barriers")
            ):
                merged.add(entity_id)
        return {"barriers": sorted(merged), "block_count": block_count}

    return _merge


def make_barrier_get_attribs_handler(state: PanelState, emit: EmitFn, now: NowFn):
    def handler_barrier_get_attribs(msg: Mapping[str, Any], ctx: DispatchContext) -> bool:
        barrier_obj = _as_mapping(msg.get("barrier"))
        if barrier_obj is None:
            return False
        payload = _as_mapping(barrier_obj.get("get_attribs"))
        if payload is None:
            return False

        error_code = payload.get("error_code", barrier_obj.get("error_code"))
        if isinstance(error_code, int) and error_code != 0:
            if error_code == 11008:
                emit(
                    AuthorizationRequiredEvent(
                        kind=AuthorizationRequiredEvent.KIND,
                        at=UNSET_AT,
                        seq=UNSET_SEQ,
                        classification=UNSET_CLASSIFICATION,
                        route=UNSET_ROUTE,
                        session_id=UNSET_SESSION_ID,
                        error_code=error_code,
                        scope="barrier",
                        entity_id=_coerce_int(payload.get("barrier_id")),
                        message=None,
                    ),
                    ctx,
                )
                return True
            emit(
                ApiError(
                    kind=ApiError.KIND,
                    at=UNSET_AT,
                    seq=UNSET_SEQ,
                    classification=UNSET_CLASSIFICATION,
                    route=UNSET_ROUTE,
                    session_id=UNSET_SESSION_ID,
                    error_code=error_code,
                    scope="barrier",
                    entity_id=_coerce_int(payload.get("barrier_id")),
                    message=None,
                ),
                ctx,
            )
            return True

        barrier_id = payload.get("barrier_id")
        if not isinstance(barrier_id, int) or barrier_id < 1:
            return False

        barrier = state.get_or_create_barrier(barrier_id)
        _apply_barrier_attribs(barrier, payload)
        barrier.last_update_at = now()
        state.panel.last_message_at = barrier.last_update_at
        return True

    return handler_barrier_get_attribs


def make_barrier_get_table_info_handler(state: PanelState, emit: EmitFn, now: NowFn):
    def handler_barrier_get_table_info(msg: Mapping[str, Any], ctx: DispatchContext) -> bool:
        barrier_obj = _as_mapping(msg.get("barrier"))
        if barrier_obj is None:
            return False

        payload = _as_mapping(barrier_obj.get("get_table_info"))
        if payload is None:
            payload = _as_mapping(barrier_obj.get("table_info"))
        if payload is None:
            return False

        error_code = payload.get("error_code")
        if isinstance(error_code, int) and error_code != 0:
            emit(
                ApiError(
                    kind=ApiError.KIND,
                    at=UNSET_AT,
                    seq=UNSET_SEQ,
                    classification=UNSET_CLASSIFICATION,
                    route=UNSET_ROUTE,
                    session_id=UNSET_SESSION_ID,
                    error_code=error_code,
                    scope="barrier",
                    entity_id=None,
                    message=None,
                ),
                ctx,
            )
            return True

        state.table_info_by_domain["barrier"] = dict(payload)
        state.panel.last_message_at = now()
        table_elements = _extract_int(payload, "table_elements")
        table_csm = _extract_table_csm(payload, domain="barrier")
        if table_csm is not None:
            old = state.table_csm_by_domain.get("barrier")
            if old != table_csm:
                state.table_csm_by_domain["barrier"] = table_csm
                emit(
                    TableCsmChanged(
                        kind=TableCsmChanged.KIND,
                        at=UNSET_AT,
                        seq=UNSET_SEQ,
                        classification=UNSET_CLASSIFICATION,
                        route=UNSET_ROUTE,
                        session_id=UNSET_SESSION_ID,
                        csm_domain="barrier",
                        old=old,
                        new=table_csm,
                    ),
                    ctx,
                )
        if table_elements is not None:
            state.table_info_known.add("barrier")

        emit(
            BarrierTableInfoUpdated(
                kind=BarrierTableInfoUpdated.KIND,
                at=UNSET_AT,
                seq=UNSET_SEQ,
                classification=UNSET_CLASSIFICATION,
                route=UNSET_ROUTE,
                session_id=UNSET_SESSION_ID,
                table_elements=table_elements,
                increment_size=_extract_int(payload, "increment_size"),
                table_csm=table_csm,
            ),
            ctx,
        )

        snapshot = update_csm_snapshot(state)
        if snapshot is not None:
            emit(
                CsmSnapshotUpdated(
                    kind=CsmSnapshotUpdated.KIND,
                    at=UNSET_AT,
                    seq=UNSET_SEQ,
                    classification=UNSET_CLASSIFICATION,
                    route=UNSET_ROUTE,
                    session_id=UNSET_SESSION_ID,
                    snapshot=snapshot,
                ),
                ctx,
            )

        if not state.bootstrap_counts_ready and {"area", "zone", "output", "tstat"}.issubset(
            state.table_info_known
        ):
            state.bootstrap_counts_ready = True
            emit(
                BootstrapCountsReady(
                    kind=BootstrapCountsReady.KIND,
                    at=UNSET_AT,
                    seq=UNSET_SEQ,
                    classification=UNSET_CLASSIFICATION,
                    route=UNSET_ROUTE,
                    session_id=UNSET_SESSION_ID,
                ),
                ctx,
            )
        return True

    return handler_barrier_get_table_info


def _apply_barrier_status_fields(barrier: BarrierState, payload: Mapping[str, Any]) -> None:
    status = payload.get("status")
    if isinstance(status, str):
        barrier.status = status.strip().upper()
    for key, value in payload.items():
        if key in {"barrier_id", "error_code", "status"}:
            continue
        barrier.fields[key] = value


def _normalize_name(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _apply_barrier_attribs(barrier: BarrierState, payload: Mapping[str, Any]) -> None:
    if "name" in payload:
        barrier.name = _normalize_name(payload.get("name"))
    if "area_id" in payload and isinstance(payload.get("area_id"), int):
        barrier.area_id = cast(int, payload.get("area_id"))
    for key, value in payload.items():
        if key in {"barrier_id", "error_code", "name", "area_id"}:
            continue
        barrier.fields[key] = value


def _extract_configured_ids(payload: Mapping[str, Any], keys: tuple[str, ...]) -> list[int]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            ids = [
                item for item in cast(list[object], value) if isinstance(item, int) and item >= 1
            ]
            return sorted(set(ids))
    return []


def _extract_int(payload: Mapping[str, Any], key: str) -> int | None:
    value = payload.get(key)
    return value if isinstance(value, int) else None


def _extract_table_csm(payload: Mapping[str, Any], *, domain: str) -> int | None:
    if "table_csm" not in payload:
        return None
    value = payload.get("table_csm")
    if isinstance(value, bool):
        LOG.warning("%s.get_table_info table_csm has invalid bool value.", domain)
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return int(text)
    LOG.warning("%s.get_table_info table_csm has non-int value %r.", domain, value)
    return None
