"""
elke27_lib/handlers/lock.py

Read/observe handlers for the "lock" domain.
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
    BootstrapCountsReady,
    CsmSnapshotUpdated,
    Event,
    LockConfiguredInventoryReady,
    LockConfiguredUpdated,
    LockStatusUpdated,
    LockTableInfoUpdated,
    TableCsmChanged,
)
from elke27_lib.states import LockState, PanelState, update_csm_snapshot

EmitFn = Callable[[Event, DispatchContext], None]
NowFn = Callable[[], float]

LOG = logging.getLogger(__name__)


def _as_mapping(obj: object) -> Mapping[str, Any] | None:
    if isinstance(obj, Mapping):
        return cast(Mapping[str, Any], obj)
    return None


def _coerce_int(value: object) -> int | None:
    return value if isinstance(value, int) else None


def make_lock_get_status_handler(state: PanelState, emit: EmitFn, now: NowFn):
    def handler_lock_get_status(msg: Mapping[str, Any], ctx: DispatchContext) -> bool:
        lock_obj = _as_mapping(msg.get("lock"))
        if lock_obj is None:
            return False
        payload = _as_mapping(lock_obj.get("get_status"))
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
                    scope="lock",
                    entity_id=_coerce_int(payload.get("lock_id")),
                    message=None,
                ),
                ctx,
            )
            return True

        lock_id = payload.get("lock_id")
        if not isinstance(lock_id, int) or lock_id < 1:
            return False

        lock = state.get_or_create_lock(lock_id)
        _apply_lock_status_fields(lock, payload)
        lock.last_update_at = now()
        state.panel.last_message_at = lock.last_update_at

        emit(
            LockStatusUpdated(
                kind=LockStatusUpdated.KIND,
                at=UNSET_AT,
                seq=UNSET_SEQ,
                classification=UNSET_CLASSIFICATION,
                route=UNSET_ROUTE,
                session_id=UNSET_SESSION_ID,
                lock_id=lock_id,
                status=lock.status,
                locked=lock.locked,
            ),
            ctx,
        )
        return True

    return handler_lock_get_status


def make_lock_set_status_handler(state: PanelState, emit: EmitFn, now: NowFn):
    def handler_lock_set_status(msg: Mapping[str, Any], ctx: DispatchContext) -> bool:
        lock_obj = _as_mapping(msg.get("lock"))
        if lock_obj is None:
            return False
        payload = _as_mapping(lock_obj.get("set_status"))
        if payload is None:
            return False

        lock_id = payload.get("lock_id")
        if not isinstance(lock_id, int) or lock_id < 1:
            return False

        lock = state.get_or_create_lock(lock_id)
        _apply_lock_status_fields(lock, payload)
        lock.last_update_at = now()
        state.panel.last_message_at = lock.last_update_at

        emit(
            LockStatusUpdated(
                kind=LockStatusUpdated.KIND,
                at=UNSET_AT,
                seq=UNSET_SEQ,
                classification=UNSET_CLASSIFICATION,
                route=UNSET_ROUTE,
                session_id=UNSET_SESSION_ID,
                lock_id=lock_id,
                status=lock.status,
                locked=lock.locked,
            ),
            ctx,
        )
        return True

    return handler_lock_set_status


def make_lock_get_configured_handler(state: PanelState, emit: EmitFn, now: NowFn):
    def handler_lock_get_configured(msg: Mapping[str, Any], ctx: DispatchContext) -> bool:
        lock_obj = _as_mapping(msg.get("lock"))
        if lock_obj is None:
            return False
        payload = _as_mapping(lock_obj.get("get_configured"))
        if payload is None:
            return False

        error_code = payload.get("error_code", lock_obj.get("error_code"))
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
                        scope="lock",
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
                    scope="lock",
                    entity_id=None,
                    message=None,
                ),
                ctx,
            )
            return True

        ids = _extract_configured_ids(payload, ("locks", "lock_ids", "configured_locks"))
        table_info = _as_mapping(state.table_info_by_domain.get("lock"))
        if table_info is not None:
            max_id = table_info.get("table_elements")
            if isinstance(max_id, int) and max_id >= 1:
                ids = [entity_id for entity_id in ids if entity_id <= max_id]

        inv = state.inventory
        inv.configured_locks = set(ids)
        inv.configured_locks_complete = True
        state.panel.last_message_at = now()

        emit(
            LockConfiguredUpdated(
                kind=LockConfiguredUpdated.KIND,
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
            LockConfiguredInventoryReady(
                kind=LockConfiguredInventoryReady.KIND,
                at=UNSET_AT,
                seq=UNSET_SEQ,
                classification=UNSET_CLASSIFICATION,
                route=UNSET_ROUTE,
                session_id=UNSET_SESSION_ID,
            ),
            ctx,
        )
        return True

    return handler_lock_get_configured


def make_lock_configured_merge(_state: PanelState):
    def _merge(blocks: list[PagedBlock], block_count: int) -> Mapping[str, Any]:
        merged: set[int] = set()
        for block in blocks:
            for entity_id in _extract_configured_ids(
                block.payload, ("locks", "lock_ids", "configured_locks")
            ):
                merged.add(entity_id)
        return {"locks": sorted(merged), "block_count": block_count}

    return _merge


def make_lock_get_attribs_handler(state: PanelState, emit: EmitFn, now: NowFn):
    def handler_lock_get_attribs(msg: Mapping[str, Any], ctx: DispatchContext) -> bool:
        lock_obj = _as_mapping(msg.get("lock"))
        if lock_obj is None:
            return False
        payload = _as_mapping(lock_obj.get("get_attribs"))
        if payload is None:
            return False

        error_code = payload.get("error_code", lock_obj.get("error_code"))
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
                        scope="lock",
                        entity_id=_coerce_int(payload.get("lock_id")),
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
                    scope="lock",
                    entity_id=_coerce_int(payload.get("lock_id")),
                    message=None,
                ),
                ctx,
            )
            return True

        lock_id = payload.get("lock_id")
        if not isinstance(lock_id, int) or lock_id < 1:
            return False

        lock = state.get_or_create_lock(lock_id)
        _apply_lock_attribs(lock, payload)
        lock.last_update_at = now()
        state.panel.last_message_at = lock.last_update_at
        return True

    return handler_lock_get_attribs


def make_lock_get_table_info_handler(state: PanelState, emit: EmitFn, now: NowFn):
    def handler_lock_get_table_info(msg: Mapping[str, Any], ctx: DispatchContext) -> bool:
        lock_obj = _as_mapping(msg.get("lock"))
        if lock_obj is None:
            return False

        payload = _as_mapping(lock_obj.get("get_table_info"))
        if payload is None:
            payload = _as_mapping(lock_obj.get("table_info"))
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
                    scope="lock",
                    entity_id=None,
                    message=None,
                ),
                ctx,
            )
            return True

        state.table_info_by_domain["lock"] = dict(payload)
        state.panel.last_message_at = now()
        table_elements = _extract_int(payload, "table_elements")
        table_csm = _extract_table_csm(payload, domain="lock")
        if table_csm is not None:
            old = state.table_csm_by_domain.get("lock")
            if old != table_csm:
                state.table_csm_by_domain["lock"] = table_csm
                emit(
                    TableCsmChanged(
                        kind=TableCsmChanged.KIND,
                        at=UNSET_AT,
                        seq=UNSET_SEQ,
                        classification=UNSET_CLASSIFICATION,
                        route=UNSET_ROUTE,
                        session_id=UNSET_SESSION_ID,
                        csm_domain="lock",
                        old=old,
                        new=table_csm,
                    ),
                    ctx,
                )
        if table_elements is not None:
            state.table_info_known.add("lock")

        emit(
            LockTableInfoUpdated(
                kind=LockTableInfoUpdated.KIND,
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

    return handler_lock_get_table_info


def _apply_lock_status_fields(lock: LockState, payload: Mapping[str, Any]) -> None:
    status = payload.get("status")
    if isinstance(status, str):
        normalized = status.strip().upper()
        lock.status = normalized
        if normalized == "ON":
            lock.locked = True
        elif normalized == "OFF":
            lock.locked = False
    locked = payload.get("locked")
    if isinstance(locked, bool):
        lock.locked = locked
        lock.status = "LOCKED" if locked else "UNLOCKED"
    for key, value in payload.items():
        if key in {"lock_id", "error_code", "status", "locked"}:
            continue
        lock.fields[key] = value


def _normalize_name(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _apply_lock_attribs(lock: LockState, payload: Mapping[str, Any]) -> None:
    if "name" in payload:
        lock.name = _normalize_name(payload.get("name"))
    if "area_id" in payload and isinstance(payload.get("area_id"), int):
        lock.area_id = cast(int, payload.get("area_id"))
    for key, value in payload.items():
        if key in {"lock_id", "error_code", "name", "area_id"}:
            continue
        lock.fields[key] = value


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
