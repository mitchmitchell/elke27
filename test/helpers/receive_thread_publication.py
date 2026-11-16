from __future__ import annotations

import asyncio
from collections.abc import Mapping

from elke27_lib.client import Elke27Client, Result
from elke27_lib.const import E27ErrorCode
from test.helpers.internal import deliver_panel_message
from test.helpers.internal import (
    run_arm_set_publication_completes_before_transport_reply as _run_arm_set_publication_completes_before_transport_reply,
)
from test.helpers.internal import (
    run_zone_get_all_zones_status_bulk_without_dispatch_flush as _run_zone_get_all_zones_status_bulk_without_dispatch_flush,
)


async def run_arm_set_publication_completes_before_transport_reply(
    client: Elke27Client,
    session: object,
    *,
    track_publication: list[asyncio.Future[None] | None],
) -> Result[Mapping[str, object]]:
    return await _run_arm_set_publication_completes_before_transport_reply(
        client, session, track_publication=track_publication
    )


async def run_zone_get_all_zones_status_bulk_without_dispatch_flush(
    client: Elke27Client,
    session: object,
    *,
    status: str = "F",
    zone_ids: tuple[int, ...] = (1,),
) -> tuple[Result[Mapping[str, object]], bool]:
    return await _run_zone_get_all_zones_status_bulk_without_dispatch_flush(
        client, session, status=status, zone_ids=zone_ids
    )


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
