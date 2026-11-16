from __future__ import annotations

from elke27_lib.const import E27ErrorCode
from test.helpers.internal import deliver_panel_message


def inject_unconfirmed_publication_event(kernel: object, case_id: str, reply_seq: int) -> None:
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
