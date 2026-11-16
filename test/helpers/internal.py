from __future__ import annotations

import asyncio
import threading
import types
from collections.abc import Mapping
from typing import Any, cast

from elke27_lib.client import Elke27Client, Result
from elke27_lib.const import E27ErrorCode
from elke27_lib.events import (
    UNSET_AT,
    UNSET_CLASSIFICATION,
    UNSET_SESSION_ID,
    AreaStatusUpdated,
)


def get_private(obj: object, name: str) -> Any:
    return getattr(obj, name)


def set_private(obj: object, name: str, value: Any) -> None:
    setattr(obj, name, value)


def get_kernel(client: object) -> Any:
    return get_private(client, "_kernel")


def deliver_panel_message(kernel: object, msg: dict[str, object]) -> None:
    get_private(kernel, "_on_message")(msg)


def reply_publication_slot_count(client: object) -> int:
    if not isinstance(client, Elke27Client):
        raise TypeError(f"expected Elke27Client, got {type(client).__name__}")
    return len(get_private(client, "_reply_publication_by_seq"))


def _prepare_armed_away_area_snapshot(client: Elke27Client, kernel: object) -> None:
    get_private(kernel, "state").get_or_create_area(1).arm_state = "ARMED_AWAY"
    get_private(client, "_replace_snapshot")(areas=get_private(client, "_build_area_map")())


def _prepare_zones_ready_snapshot(
    client: Elke27Client, kernel: object, zone_ids: tuple[int, ...]
) -> None:
    state = get_private(kernel, "state")
    for zone_id in zone_ids:
        zone = state.get_or_create_zone(zone_id)
        zone.area_id = 1
        zone.bypassed = False
    get_private(client, "_replace_snapshot")(zones=get_private(client, "_build_zone_map")())


def bind_client_connected_on_loop(client: Elke27Client, loop: asyncio.AbstractEventLoop) -> None:
    set_private(client, "_connected", True)
    set_private(client, "_event_loop", loop)


def reply_publication_future_for_seq(
    client: Elke27Client, reply_seq: int
) -> asyncio.Future[None] | None:
    slots = get_private(client, "_reply_publication_by_seq")
    fut = slots.get(reply_seq)
    if fut is None:
        return None
    return cast(asyncio.Future[None], fut)


def deliver_confirmed_area_arm_publication(
    client: Elke27Client, reply_seq: int, *, area_id: int = 1
) -> None:
    get_private(client, "_handle_kernel_event")(
        AreaStatusUpdated(
            kind=AreaStatusUpdated.KIND,
            at=UNSET_AT,
            seq=reply_seq,
            classification=UNSET_CLASSIFICATION,
            route=("area", "set_arm_state"),
            session_id=UNSET_SESSION_ID,
            area_id=area_id,
            changed_fields=("arm_state",),
            status_confirmed=True,
        )
    )


async def run_arm_set_publication_completes_before_transport_reply(
    client: Elke27Client,
    session: object,
    *,
    track_publication: list[asyncio.Future[None] | None],
) -> Result[Mapping[str, Any]]:
    kernel = get_kernel(client)
    _prepare_armed_away_area_snapshot(client, kernel)
    loop = asyncio.get_running_loop()
    bind_client_connected_on_loop(client, loop)
    task = asyncio.create_task(
        client.async_execute(
            "area_set_arm_state",
            area_id=1,
            arm_state="ARMED_AWAY",
            pin=1234,
        )
    )
    sent = get_private(session, "sent")
    while not sent:
        await asyncio.sleep(0)
    reply_seq = sent[0]["seq"]
    track_publication.clear()
    track_publication.append(reply_publication_future_for_seq(client, reply_seq))
    deliver_confirmed_area_arm_publication(client, reply_seq, area_id=1)
    reply = {
        "seq": reply_seq,
        "area": {
            "set_arm_state": {
                "area_id": 1,
                "error_code": E27ErrorCode.ELKERR_NONE,
                "arm_state": "ARMED_AWAY",
            }
        },
    }

    def receive_thread() -> None:
        deliver_panel_message(kernel, reply)

    threading.Thread(target=receive_thread, daemon=True).start()
    return cast(Result[Mapping[str, Any]], await task)


async def run_zone_get_all_zones_status_bulk_without_dispatch_flush(
    client: Elke27Client,
    session: object,
    *,
    status: str = "F",
    zone_ids: tuple[int, ...] = (1,),
) -> tuple[Result[Mapping[str, Any]], bool]:
    kernel = get_kernel(client)
    _prepare_zones_ready_snapshot(client, kernel, zone_ids)
    loop = asyncio.get_running_loop()
    bind_client_connected_on_loop(client, loop)
    client.bind_kernel_loop_thread_for_tests(loop)
    dispatch_deferred: list[tuple[Any, tuple[Any, ...]]] = []
    real_call_soon_threadsafe = loop.call_soon_threadsafe

    def intercept_call_soon_threadsafe(fn: Any, /, *args: Any) -> None:
        fn_name = fn.__name__
        fn_self = fn.__self__ if isinstance(fn, types.MethodType) else None
        if fn_self is client and fn_name == "_complete_dispatch_only_reply_publication":
            dispatch_deferred.append((fn, args))
            return
        real_call_soon_threadsafe(fn, *args)

    set_private(loop, "call_soon_threadsafe", intercept_call_soon_threadsafe)

    task = asyncio.create_task(client.async_execute("zone_get_all_zones_status"))
    sent = get_private(session, "sent")
    while not sent:
        await asyncio.sleep(0)
    reply = {
        "seq": sent[0]["seq"],
        "zone": {
            "get_all_zones_status": {
                "status": status,
                "error_code": E27ErrorCode.ELKERR_NONE,
            }
        },
    }

    def receive_thread() -> None:
        deliver_panel_message(get_kernel(client), reply)

    threading.Thread(target=receive_thread, daemon=True).start()
    result = await task
    set_private(loop, "call_soon_threadsafe", real_call_soon_threadsafe)
    return cast(Result[Mapping[str, Any]], result), bool(dispatch_deferred)
