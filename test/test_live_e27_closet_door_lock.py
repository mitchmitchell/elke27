from __future__ import annotations

import asyncio

import pytest

from elke27_lib.client import Elke27Client
from test.helpers.payload_validation import assert_payload_shape


def _status_token(payload: dict[str, object] | None) -> str:
    if not isinstance(payload, dict):
        return ""
    value = payload.get("status")
    if not isinstance(value, str):
        return ""
    return value.strip().upper()


async def _wait_for_status(
    client: Elke27Client,
    *,
    lock_id: int,
    expected: set[str],
    timeout_s: float = 10.0,
    poll_s: float = 1.0,
) -> dict[str, object] | None:
    deadline = asyncio.get_running_loop().time() + timeout_s
    last: dict[str, object] | None = None
    while True:
        result = await client.async_execute("lock_get_status", lock_id=lock_id)
        if result.ok:
            assert_payload_shape("lock_get_status", result.data)
            payload = result.data if isinstance(result.data, dict) else None
            last = payload
            token = _status_token(payload)
            if token in expected:
                return payload
        if asyncio.get_running_loop().time() >= deadline:
            return last
        await asyncio.sleep(poll_s)


async def _resolve_closet_door_lock_id(client: Elke27Client) -> int:
    expected_name = "closet door"

    configured = await client.async_execute("lock_get_configured")
    if not configured.ok:
        pytest.fail(f"lock_get_configured failed: {configured.error}")
    assert_payload_shape("lock_get_configured", configured.data)

    locks = configured.data.get("locks") if configured.data else None
    if not isinstance(locks, list) or not locks:
        pytest.fail(f"No configured locks found; configured locks={locks!r}")

    for lock_id in locks:
        if not isinstance(lock_id, int) or lock_id < 1:
            continue
        attribs = await client.async_execute("lock_get_attribs", lock_id=lock_id)
        if not attribs.ok:
            continue
        assert_payload_shape("lock_get_attribs", attribs.data)
        name = str((attribs.data or {}).get("name", "")).strip().lower()
        if name == expected_name:
            return lock_id

    pytest.fail(f"Unable to resolve lock '{expected_name}' from configured locks={locks!r}")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_lock_then_unlock_closet_door(live_e27_client: Elke27Client) -> None:
    lock_id = await _resolve_closet_door_lock_id(live_e27_client)

    lock_result = await live_e27_client.async_execute(
        "lock_set_status",
        lock_id=lock_id,
        status="ON",
    )
    if not lock_result.ok:
        pytest.fail(f"lock_set_status ON failed: {lock_result.error}")
    assert_payload_shape("lock_set_status", lock_result.data)

    locked_payload = await _wait_for_status(
        live_e27_client,
        lock_id=lock_id,
        expected={"LOCK", "LOCKED", "ON"},
    )
    locked_status = _status_token(locked_payload)
    if locked_status not in {"LOCK", "LOCKED", "ON"}:
        pytest.fail(
            f"Expected locked status after ON command; got status={locked_status!r} payload={locked_payload!r}"
        )

    unlock_result = await live_e27_client.async_execute(
        "lock_set_status",
        lock_id=lock_id,
        status="OFF",
    )
    if not unlock_result.ok:
        pytest.fail(f"lock_set_status OFF failed: {unlock_result.error}")
    assert_payload_shape("lock_set_status", unlock_result.data)

    unlocked_payload = await _wait_for_status(
        live_e27_client,
        lock_id=lock_id,
        expected={"UNLOCK", "UNLOCKED", "OFF"},
    )
    unlocked_status = _status_token(unlocked_payload)
    if unlocked_status not in {"UNLOCK", "UNLOCKED", "OFF"}:
        pytest.fail(
            f"Expected unlocked status after OFF command; got status={unlocked_status!r} payload={unlocked_payload!r}"
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_lock_closet_door_leave_locked(live_e27_client: Elke27Client) -> None:
    lock_id = await _resolve_closet_door_lock_id(live_e27_client)

    lock_result = await live_e27_client.async_execute(
        "lock_set_status",
        lock_id=lock_id,
        status="ON",
    )
    if not lock_result.ok:
        pytest.fail(f"lock_set_status ON failed: {lock_result.error}")
    assert_payload_shape("lock_set_status", lock_result.data)

    locked_payload = await _wait_for_status(
        live_e27_client,
        lock_id=lock_id,
        expected={"LOCK", "LOCKED", "ON"},
    )
    locked_status = _status_token(locked_payload)
    if locked_status not in {"LOCK", "LOCKED", "ON"}:
        pytest.fail(
            f"Expected locked status after ON command; got status={locked_status!r} payload={locked_payload!r}"
        )
