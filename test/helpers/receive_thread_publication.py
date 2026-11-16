from __future__ import annotations

from typing import cast

from elke27_lib.const import E27ErrorCode
from test.helpers.internal import get_kernel, get_private


def reply_publication_slot_count(client: object) -> int:
    inflight = getattr(client, "reply_publication_inflight_count", None)
    if callable(inflight):
        return cast(int, inflight())
    slots = getattr(client, "_reply_publication_by_seq", None)
    if slots is None:
        slots = getattr(client, "_reply_publication_waiters", {})
    return len(slots)


def deliver_panel_message(kernel: object, msg: dict[str, object]) -> None:
    get_private(kernel, "_on_message")(msg)


def inject_unconfirmed_publication_event(client: object, case_id: str, reply_seq: int) -> None:
    kernel = get_kernel(client)
    if case_id == "zone_set_status_confirmed_publication_hold":
        deliver_panel_message(
            kernel,
            {
                "seq": reply_seq,
                "zone": {
                    "set_status": {
                        "zone_id": 1,
                        "error_code": E27ErrorCode.ELKERR_NONE,
                    }
                },
            },
        )
    elif case_id == "area_get_status":
        deliver_panel_message(
            kernel,
            {
                "seq": reply_seq,
                "area": {
                    "set_arm_state": {
                        "area_id": 1,
                        "error_code": E27ErrorCode.ELKERR_NONE,
                    }
                },
            },
        )
    elif case_id == "zone_get_status":
        deliver_panel_message(
            kernel,
            {
                "seq": reply_seq,
                "zone": {
                    "set_status": {
                        "zone_id": 1,
                        "error_code": E27ErrorCode.ELKERR_NONE,
                    }
                },
            },
        )
