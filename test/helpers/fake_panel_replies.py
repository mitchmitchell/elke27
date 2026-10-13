"""Synthetic panel replies for faked transport tests."""

from __future__ import annotations

from typing import Any

from elke27_lib.const import E27ErrorCode


def _domain_command(sent: dict[str, Any]) -> tuple[str, str, dict[str, Any]] | None:
    for domain, body in sent.items():
        if domain in {"seq", "session_id"}:
            continue
        if not isinstance(body, dict):
            continue
        if len(body) != 1:
            continue
        command = next(iter(body))
        payload = body[command]
        if isinstance(payload, dict):
            return domain, command, payload
        if payload is True:
            return domain, command, {}
    return None


def _zone_bypass_from_sent_history(sent_history: list[dict[str, Any]], zone_id: int) -> bool | None:
    for prior in sent_history:
        parsed = _domain_command(prior)
        if parsed is None:
            continue
        domain, command, payload = parsed
        if domain == "zone" and command == "set_status" and payload.get("zone_id") == zone_id:
            bypassed = payload.get("BYPASSED")
            if isinstance(bypassed, bool):
                return bypassed
    return None


def synthetic_success_reply(
    sent: dict[str, Any],
    *,
    sent_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a minimal successful reply for a single outbound request."""
    seq = sent.get("seq")
    if not isinstance(seq, int):
        raise ValueError("sent message missing seq")
    parsed = _domain_command(sent)
    if parsed is None:
        raise ValueError(f"cannot infer route from sent message: {sent!r}")
    domain, command, request_payload = parsed
    history = sent_history or []

    if domain == "area" and command == "set_arm_state":
        area_id = request_payload.get("area_id", 1)
        return {
            "seq": seq,
            "area": {
                "set_arm_state": {
                    "area_id": area_id,
                    "error_code": E27ErrorCode.ELKERR_NONE,
                }
            },
        }

    if domain == "area" and command == "get_status":
        area_id = request_payload.get("area_id", 1)
        arm_state = "DISARMED"
        for prior in history:
            prior_parsed = _domain_command(prior)
            if prior_parsed is None:
                continue
            p_domain, p_command, p_payload = prior_parsed
            if p_domain == "area" and p_command == "set_arm_state":
                arm_state = str(p_payload.get("arm_state", arm_state))
        return {
            "seq": seq,
            "area": {
                "get_status": {
                    "area_id": area_id,
                    "error_code": E27ErrorCode.ELKERR_NONE,
                    "arm_state": arm_state,
                }
            },
        }

    if domain == "zone" and command == "set_status":
        zone_id = request_payload.get("zone_id", 1)
        return {
            "seq": seq,
            "zone": {
                "set_status": {
                    "zone_id": zone_id,
                    "error_code": E27ErrorCode.ELKERR_NONE,
                }
            },
        }

    if domain == "zone" and command == "get_status":
        zone_id = request_payload.get("zone_id", 1)
        bypassed = _zone_bypass_from_sent_history(history, zone_id)
        payload: dict[str, Any] = {
            "zone_id": zone_id,
            "error_code": E27ErrorCode.ELKERR_NONE,
        }
        if bypassed is not None:
            payload["BYPASSED"] = bypassed
        return {"seq": seq, "zone": {"get_status": payload}}

    if domain == "zone" and command == "get_all_zones_status":
        return {
            "seq": seq,
            "zone": {
                "get_all_zones_status": {"error_code": E27ErrorCode.ELKERR_NONE, "status": ""}
            },
        }

    raise ValueError(f"no synthetic reply for {domain}.{command}")
