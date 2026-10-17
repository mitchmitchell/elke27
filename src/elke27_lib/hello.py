"""
E27 hello exchange (per-TCP-connection) — cleartext JSON request/response, with
session key material decrypted via presentation layer helpers.

This module MUST NOT import cryptography primitives. All crypto operations
belong in presentation.py.

Flow:
  1) send hello JSON (clear, UNFRAMED)
  2) receive cleartext JSON response containing hello.session_id + encrypted sk/shm
  3) decrypt sk/shm using linkkey via presentation.decrypt_key_field_with_linkkey()
  4) return SessionKeys

Related DDRs:
- DDR-0019: Provisioning vs Runtime Responsibilities and Module Boundaries
- DDR-0017: Ack/Head Byte Before JSON (not used for hello response; hello is clear JSON)
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from .errors import (
    E27ErrorContext,
    E27HelloLinkRequired,
    E27HelloNoSession,
    E27HelloRejected,
    E27HelloTimeout,
    E27ProtocolError,
    E27ProvisioningTimeout,
    E27Timeout,
)
from .linking import (
    E27Identity,
    SocketLike,
    recv_cleartext_json_objects,
    recv_cleartext_json_objects_from_bytes,
    send_unframed_json,
)
from .presentation import decrypt_key_field_with_linkkey

LOG = logging.getLogger(__name__)

# HELLO error codes that mean the client sn is not linked (or its link was revoked)
# or not authorized: recovery is to re-link, not to retry.
#   11006 ELKERR_INVALID_ID (seen on hardware for an unlinked/revoked sn)
#   11008 ELKERR_NOAUTH
HELLO_LINK_REQUIRED_ERROR_CODES: frozenset[int] = frozenset({11006, 11008})


@dataclass(frozen=True, slots=True)
class SessionKeys:
    """Session keys derived from hello response."""

    session_id: int
    session_key_hex: str  # 16 bytes => 32 hex chars (lowercase)
    hmac_key_hex: str  # 32 bytes => 64 hex chars (lowercase)


def build_hello_request(*, seq: int, client_identity: E27Identity) -> str:
    """
    Build the hello request JSON.

    Note: hello is cleartext and UNFRAMED (per your confirmed live behavior).
    """
    msg = {
        "seq": int(seq),
        "hello": {
            "mn": client_identity.mn,
            "sn": client_identity.sn,
            "fwver": client_identity.fwver,
            "hwver": client_identity.hwver,
            "osver": client_identity.osver,
        },
    }
    return json.dumps(msg, separators=(",", ":"))


def _as_mapping(obj: object) -> Mapping[str, object] | None:
    if isinstance(obj, Mapping):
        return cast(Mapping[str, object], obj)
    return None


def _select_hello_object(objs: list[Mapping[str, object]]) -> Mapping[str, object]:
    for obj in objs:
        hello = _as_mapping(obj.get("hello"))
        if hello is not None:
            return obj
    raise E27ProtocolError(
        "Hello response not found in cleartext JSON stream.",
        context=E27ErrorContext(phase="hello_recv"),
    )


def perform_hello(
    *,
    sock: SocketLike,
    client_identity: E27Identity,
    linkkey_hex: str,
    seq: int = 110,
    timeout_s: float = 5.0,
) -> SessionKeys:
    """
    Execute hello sequence for a single TCP connection.

    Raises:
      - E27HelloTimeout when the HELLO deadline expires with no hello object
      - E27Timeout on recv timeout during other hello reads
      - E27TransportError on socket failure
      - E27ProtocolError on malformed JSON or decrypt failure
    """
    req = build_hello_request(seq=seq, client_identity=client_identity)

    # Check for any pre-hello bytes already queued by the panel.
    pre_objs: list[Mapping[str, object]] = []
    prev_timeout = sock.gettimeout()
    try:
        sock.settimeout(0.05)
        try:
            predata = sock.recv(4096)
            if predata:
                LOG.debug("Pre-HELLO bytes received: %s", predata.hex())
                try:
                    pre_batch = recv_cleartext_json_objects_from_bytes(predata)
                    pre_objs = [cast(Mapping[str, object], obj) for obj in pre_batch]
                except (ValueError, json.JSONDecodeError) as e:
                    LOG.warning("Pre-HELLO JSON parse failed: %s", e)
        except (TimeoutError, BlockingIOError):
            pass
    finally:
        sock.settimeout(prev_timeout)

    # Send clear, UNFRAMED JSON
    LOG.debug("Hello request payload: %s", req)
    send_unframed_json(sock, req)

    # Receive clear, UNFRAMED JSON (may be concatenated objects). Some panels emit
    # discovery/LOCAL objects before hello; keep reading until hello or timeout.
    deadline = time.monotonic() + float(timeout_s)
    objs: list[Mapping[str, object]] = []
    if pre_objs:
        objs.extend(pre_objs)

    while time.monotonic() < deadline:
        remaining = max(0.0, deadline - time.monotonic())
        try:
            batch = recv_cleartext_json_objects(sock, timeout_s=remaining)
        except (E27Timeout, E27ProvisioningTimeout):
            continue
        except (ValueError, TypeError, json.JSONDecodeError) as e:
            raise E27ProtocolError(
                f"Unexpected error receiving hello response: {e}",
                context=E27ErrorContext(phase="hello_recv"),
                cause=e,
            ) from e

        batch_objs = [cast(Mapping[str, object], obj) for obj in batch]
        objs.extend(batch_objs)
        if any("hello" in o for o in objs):
            break

    if not any("hello" in o for o in objs):
        raw_preview = json.dumps(objs, separators=(",", ":"), ensure_ascii=True)
        LOG.debug("HELLO response missing 'hello': %s", raw_preview)
        raise E27HelloTimeout(
            "Hello response not found in cleartext JSON stream.",
            context=E27ErrorContext(phase="hello_recv", detail=f"objs={raw_preview}"),
        )

    hello_obj = _select_hello_object(objs)

    # A rejected HELLO carries error_code (and no session_id/sk/shm); check it
    # before parsing the session fields so it is not reported as malformed JSON.
    _raise_for_hello_error(hello_obj)
    _raise_for_hello_without_session(hello_obj)

    # Parse fields
    try:
        hello = _as_mapping(hello_obj.get("hello"))
        if hello is None:
            raise KeyError("hello")
        session_id = _coerce_intish(hello.get("session_id"), field="session_id")
        sk_hex = _coerce_required_str(hello.get("sk"), field="sk")
        shm_hex = _coerce_required_str(hello.get("shm"), field="shm")
        err = _coerce_intish(hello.get("error_code", 0) or 0, field="error_code")
    except (KeyError, TypeError, ValueError) as e:
        hello_payload = _as_mapping(hello_obj.get("hello")) or {}
        # Keys only: the values include encrypted session key material.
        LOG.debug("Malformed hello response keys: %s", sorted(hello_payload))
        raise E27ProtocolError(
            f"Malformed hello response JSON: {e}",
            context=E27ErrorContext(phase="hello_parse"),
            cause=e,
        ) from e

    if err != 0:
        raise E27ProtocolError(
            f"hello returned error_code={err}",
            context=E27ErrorContext(phase="hello_parse", detail=f"error_code={err}"),
        )

    # Decrypt session key material using presentation layer (no crypto imports here)
    try:
        session_key_bytes = decrypt_key_field_with_linkkey(
            linkkey_hex=linkkey_hex,
            ciphertext_hex=sk_hex,
        )
        hmac_key_bytes = decrypt_key_field_with_linkkey(
            linkkey_hex=linkkey_hex,
            ciphertext_hex=shm_hex,
        )
    except (TypeError, ValueError) as e:
        raise E27ProtocolError(
            f"Failed to decrypt hello session keys: {e}",
            context=E27ErrorContext(phase="hello_decrypt"),
            cause=e,
        ) from e

    # Normalize to lowercase hex for consistency across the library
    session_key_hex = session_key_bytes.hex()
    hmac_key_hex = hmac_key_bytes.hex()

    # Light sanity checks (don’t over-assume sizes, but these are observed invariants)
    if len(session_key_bytes) != 16:
        raise E27ProtocolError(
            f"hello session key decrypted to {len(session_key_bytes)} bytes (expected 16).",
            context=E27ErrorContext(
                phase="hello_decrypt", detail=f"sk_len={len(session_key_bytes)}"
            ),
        )
    if len(hmac_key_bytes) != 32:
        raise E27ProtocolError(
            f"hello hmac key decrypted to {len(hmac_key_bytes)} bytes (expected 32).",
            context=E27ErrorContext(
                phase="hello_decrypt", detail=f"hmac_len={len(hmac_key_bytes)}"
            ),
        )

    return SessionKeys(
        session_id=session_id,
        session_key_hex=session_key_hex,
        hmac_key_hex=hmac_key_hex,
    )


def _raise_for_hello_error(hello_obj: Mapping[str, object]) -> None:
    hello = _as_mapping(hello_obj.get("hello"))
    if hello is None:
        return
    raw_code = hello.get("error_code")
    if raw_code in (None, 0, "0", ""):
        return
    try:
        code = _coerce_intish(raw_code, field="error_code")
    except ValueError:
        return  # left to the regular parser
    if code == 0:
        return
    raw_msg = hello.get("error_message")
    message = raw_msg if isinstance(raw_msg, str) and raw_msg else None
    context = E27ErrorContext(phase="hello_parse", detail=f"error_code={code}")
    if code in HELLO_LINK_REQUIRED_ERROR_CODES:
        LOG.warning(
            "Panel rejected HELLO: error_code=%s (%s); the client is not linked or the "
            "link was revoked, re-link required",
            code,
            message or "no message",
        )
        raise E27HelloLinkRequired(code, message, context=context)
    LOG.warning("Panel rejected HELLO: error_code=%s (%s)", code, message or "no message")
    raise E27HelloRejected(code, message, context=context)


_HELLO_SESSION_FIELDS = ("session_id", "sk", "shm")


def _raise_for_hello_without_session(hello_obj: Mapping[str, object]) -> None:
    """A HELLO reply with no error code but a session field (session_id, sk,
    shm) absent, null or empty is a refused session, not malformed JSON (#61).

    A field that is present but has the wrong type is still reported as malformed.
    """
    hello = _as_mapping(hello_obj.get("hello"))
    if hello is None:
        return
    # Only when the error code is absent or a valid zero; a wrong-type error_code
    # stays a malformed reply, not link contention.
    if hello.get("error_code") not in (None, 0, "0", ""):
        return
    missing = tuple(f for f in _HELLO_SESSION_FIELDS if hello.get(f) in (None, ""))
    if not missing:
        return
    context = E27ErrorContext(phase="hello_parse", detail=f"missing={','.join(missing)}")
    LOG.warning(
        "Panel refused the session: HELLO reply had no %s (another client may be using "
        "this link); reply keys=%s",
        "/".join(missing),
        sorted(hello),
    )
    raise E27HelloNoSession(missing, context=context)


def _coerce_intish(value: object, *, field: str) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    raise ValueError(f"hello.{field} must be an int or digit string")


def _coerce_required_str(value: object, *, field: str) -> str:
    if isinstance(value, str) and value:
        return value
    raise ValueError(f"hello.{field} must be a non-empty string")
