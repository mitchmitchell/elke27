"""
elke27_lib/handlers/light.py

Read/observe handlers for the "light" domain.
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
    LightConfiguredInventoryReady,
    LightConfiguredUpdated,
    LightStatusUpdated,
    LightTableInfoUpdated,
    TableCsmChanged,
)
from elke27_lib.states import LightState, PanelState, update_csm_snapshot

EmitFn = Callable[[Event, DispatchContext], None]
NowFn = Callable[[], float]

LOG = logging.getLogger(__name__)


def _as_mapping(obj: object) -> Mapping[str, Any] | None:
    if isinstance(obj, Mapping):
        return cast(Mapping[str, Any], obj)
    return None


def _coerce_int(value: object) -> int | None:
    return value if isinstance(value, int) else None


def make_light_get_status_handler(state: PanelState, emit: EmitFn, now: NowFn):
    def handler_light_get_status(msg: Mapping[str, Any], ctx: DispatchContext) -> bool:
        light_obj = _as_mapping(msg.get("light"))
        if light_obj is None:
            return False
        payload = _as_mapping(light_obj.get("get_status"))
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
                    scope="light",
                    entity_id=_coerce_int(payload.get("light_id")),
                    message=None,
                ),
                ctx,
            )
            return True

        light_id = payload.get("light_id")
        if not isinstance(light_id, int) or light_id < 1:
            return False

        light = state.get_or_create_light(light_id)
        _apply_light_status_fields(light, payload)
        light.last_update_at = now()
        state.panel.last_message_at = light.last_update_at

        emit(
            LightStatusUpdated(
                kind=LightStatusUpdated.KIND,
                at=UNSET_AT,
                seq=UNSET_SEQ,
                classification=UNSET_CLASSIFICATION,
                route=UNSET_ROUTE,
                session_id=UNSET_SESSION_ID,
                light_id=light_id,
                status=light.status,
                on=light.on,
                level=light.level,
            ),
            ctx,
        )
        return True

    return handler_light_get_status


def make_light_set_status_handler(state: PanelState, emit: EmitFn, now: NowFn):
    def handler_light_set_status(msg: Mapping[str, Any], ctx: DispatchContext) -> bool:
        light_obj = _as_mapping(msg.get("light"))
        if light_obj is None:
            return False
        payload = _as_mapping(light_obj.get("set_status"))
        if payload is None:
            return False

        light_id = payload.get("light_id")
        if not isinstance(light_id, int) or light_id < 1:
            return False

        light = state.get_or_create_light(light_id)
        _apply_light_status_fields(light, payload)
        light.last_update_at = now()
        state.panel.last_message_at = light.last_update_at

        emit(
            LightStatusUpdated(
                kind=LightStatusUpdated.KIND,
                at=UNSET_AT,
                seq=UNSET_SEQ,
                classification=UNSET_CLASSIFICATION,
                route=UNSET_ROUTE,
                session_id=UNSET_SESSION_ID,
                light_id=light_id,
                status=light.status,
                on=light.on,
                level=light.level,
            ),
            ctx,
        )
        return True

    return handler_light_set_status


def make_light_get_configured_handler(state: PanelState, emit: EmitFn, now: NowFn):
    def handler_light_get_configured(msg: Mapping[str, Any], ctx: DispatchContext) -> bool:
        light_obj = _as_mapping(msg.get("light"))
        if light_obj is None:
            return False

        payload = _as_mapping(light_obj.get("get_configured"))
        if payload is None:
            return False

        error_code = payload.get("error_code", light_obj.get("error_code"))
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
                        scope="light",
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
                    scope="light",
                    entity_id=None,
                    message=None,
                ),
                ctx,
            )
            return True

        ids = _extract_configured_ids(payload, ("lights", "light_ids", "configured_lights"))
        table_info = _as_mapping(state.table_info_by_domain.get("light"))
        if table_info is not None:
            max_id = table_info.get("table_elements")
            if isinstance(max_id, int) and max_id >= 1:
                ids = [entity_id for entity_id in ids if entity_id <= max_id]

        inv = state.inventory
        inv.configured_lights = set(ids)
        inv.configured_lights_complete = True
        state.panel.last_message_at = now()

        emit(
            LightConfiguredUpdated(
                kind=LightConfiguredUpdated.KIND,
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
            LightConfiguredInventoryReady(
                kind=LightConfiguredInventoryReady.KIND,
                at=UNSET_AT,
                seq=UNSET_SEQ,
                classification=UNSET_CLASSIFICATION,
                route=UNSET_ROUTE,
                session_id=UNSET_SESSION_ID,
            ),
            ctx,
        )
        return True

    return handler_light_get_configured


def make_light_configured_merge(_state: PanelState):
    def _merge(blocks: list[PagedBlock], block_count: int) -> Mapping[str, Any]:
        merged: set[int] = set()
        for block in blocks:
            for entity_id in _extract_configured_ids(
                block.payload, ("lights", "light_ids", "configured_lights")
            ):
                merged.add(entity_id)
        return {"lights": sorted(merged), "block_count": block_count}

    return _merge


def make_light_get_attribs_handler(state: PanelState, emit: EmitFn, now: NowFn):
    def handler_light_get_attribs(msg: Mapping[str, Any], ctx: DispatchContext) -> bool:
        light_obj = _as_mapping(msg.get("light"))
        if light_obj is None:
            return False

        payload = _as_mapping(light_obj.get("get_attribs"))
        if payload is None:
            return False

        error_code = payload.get("error_code", light_obj.get("error_code"))
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
                        scope="light",
                        entity_id=_coerce_int(payload.get("light_id")),
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
                    scope="light",
                    entity_id=_coerce_int(payload.get("light_id")),
                    message=None,
                ),
                ctx,
            )
            return True

        light_id = payload.get("light_id")
        if not isinstance(light_id, int) or light_id < 1:
            return False

        light = state.get_or_create_light(light_id)
        _apply_light_attribs(light, payload)
        light.last_update_at = now()
        state.panel.last_message_at = light.last_update_at
        return True

    return handler_light_get_attribs


def make_light_get_table_info_handler(state: PanelState, emit: EmitFn, now: NowFn):
    def handler_light_get_table_info(msg: Mapping[str, Any], ctx: DispatchContext) -> bool:
        light_obj = _as_mapping(msg.get("light"))
        if light_obj is None:
            return False

        payload = _as_mapping(light_obj.get("get_table_info"))
        if payload is None:
            payload = _as_mapping(light_obj.get("table_info"))
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
                    scope="light",
                    entity_id=None,
                    message=None,
                ),
                ctx,
            )
            return True

        state.table_info_by_domain["light"] = dict(payload)
        state.panel.last_message_at = now()
        table_elements = _extract_int(payload, "table_elements")
        table_csm = _extract_table_csm(payload, domain="light")
        if table_csm is not None:
            old = state.table_csm_by_domain.get("light")
            if old != table_csm:
                state.table_csm_by_domain["light"] = table_csm
                emit(
                    TableCsmChanged(
                        kind=TableCsmChanged.KIND,
                        at=UNSET_AT,
                        seq=UNSET_SEQ,
                        classification=UNSET_CLASSIFICATION,
                        route=UNSET_ROUTE,
                        session_id=UNSET_SESSION_ID,
                        csm_domain="light",
                        old=old,
                        new=table_csm,
                    ),
                    ctx,
                )
        if table_elements is not None:
            state.table_info_known.add("light")

        emit(
            LightTableInfoUpdated(
                kind=LightTableInfoUpdated.KIND,
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

    return handler_light_get_table_info


def _apply_light_status_fields(light: LightState, payload: Mapping[str, Any]) -> None:
    status = payload.get("status")
    if isinstance(status, str):
        normalized = status.strip().upper()
        light.status = normalized
        if normalized in {"ON", "OFF"}:
            light.on = normalized == "ON"

    level = payload.get("level")
    if isinstance(level, int):
        light.level = level
        if level == 0:
            light.on = False
        elif level > 0 and light.on is None:
            light.on = True

    state_val = payload.get("state")
    if isinstance(state_val, bool):
        light.on = state_val
        light.status = "ON" if state_val else "OFF"

    for key, value in payload.items():
        if key in {"light_id", "error_code", "status", "state", "level"}:
            continue
        light.fields[key] = value


def _normalize_name(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _apply_light_attribs(light: LightState, payload: Mapping[str, Any]) -> None:
    if "name" in payload:
        light.name = _normalize_name(payload.get("name"))
    if "area_id" in payload and isinstance(payload.get("area_id"), int):
        light.area_id = cast(int, payload.get("area_id"))
    for key, value in payload.items():
        if key in {"light_id", "error_code", "name", "area_id"}:
            continue
        light.fields[key] = value


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
