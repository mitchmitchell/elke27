from __future__ import annotations

from typing import Any

from elke27_lib.client import Elke27Client
from elke27_lib.const import E27ErrorCode


def get_private(obj: object, name: str) -> Any:
    return getattr(obj, name)


def set_private(obj: object, name: str, value: Any) -> None:
    setattr(obj, name, value)


def get_kernel(client: object) -> Any:
    return get_private(client, "_kernel")


def reply_publication_slot_count(client: object) -> int:
    if isinstance(client, Elke27Client):
        return client.reply_publication_inflight_count()
    raise TypeError(f"expected Elke27Client, got {type(client).__name__}")


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
