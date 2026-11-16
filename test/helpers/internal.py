from __future__ import annotations

from typing import Any


def get_private(obj: object, name: str) -> Any:
    return getattr(obj, name)


def set_private(obj: object, name: str, value: Any) -> None:
    setattr(obj, name, value)


def get_kernel(client: object) -> Any:
    return get_private(client, "_kernel")


def deliver_panel_message(kernel: object, msg: dict[str, object]) -> None:
    get_private(kernel, "_on_message")(msg)


def inject_unconfirmed_publication_event(client: object, case_id: str, reply_seq: int) -> None:
    from elke27_lib.events import (
        UNSET_AT,
        UNSET_CLASSIFICATION,
        UNSET_SESSION_ID,
        AreaStatusUpdated,
        ZoneStatusUpdated,
    )

    event: object | None = None
    if case_id == "zone_set_status_confirmed_publication_hold":
        event = ZoneStatusUpdated(
            kind=ZoneStatusUpdated.KIND,
            at=UNSET_AT,
            seq=reply_seq,
            classification=UNSET_CLASSIFICATION,
            route=("zone", "set_status"),
            session_id=UNSET_SESSION_ID,
            zone_id=1,
            changed_fields=(),
            status_confirmed=False,
        )
    elif case_id in {"area_get_status", "zone_get_status"}:
        if case_id == "area_get_status":
            event = AreaStatusUpdated(
                kind=AreaStatusUpdated.KIND,
                at=UNSET_AT,
                seq=reply_seq,
                classification=UNSET_CLASSIFICATION,
                route=("area", "get_status"),
                session_id=UNSET_SESSION_ID,
                area_id=1,
                changed_fields=(),
                status_confirmed=False,
            )
        else:
            event = ZoneStatusUpdated(
                kind=ZoneStatusUpdated.KIND,
                at=UNSET_AT,
                seq=reply_seq,
                classification=UNSET_CLASSIFICATION,
                route=("zone", "get_status"),
                session_id=UNSET_SESSION_ID,
                zone_id=1,
                changed_fields=(),
                status_confirmed=False,
            )
    if event is not None:
        get_private(client, "_handle_kernel_event")(event)
