"""api_link refused because the panel link table is full -> Elke27LinkSlotsFullError."""

from __future__ import annotations

import types
from typing import Any

import pytest

import elke27_lib
from elke27_lib import Elke27Client, Elke27LinkSlotsFullError, linking
from elke27_lib.errors import CryptoError, E27LinkSlotsFull, E27ProtocolError
from elke27_lib.kernel import E27Kernel, KernelError


class _Sock:
    """Socket stub: one recv chunk, then the frame comes from deframe_feed."""

    def __init__(self) -> None:
        self.sent: list[bytes] = []
        self._chunks = [b"\x00"]

    def gettimeout(self) -> float | None:
        return None

    def settimeout(self, _t: float | None) -> None:
        return None

    def recv(self, _n: int) -> bytes:
        return self._chunks.pop(0) if self._chunks else b""

    def sendall(self, data: bytes) -> None:
        self.sent.append(data)


def _link_with_reply(monkeypatch: pytest.MonkeyPatch, reply: bytes) -> linking.E27LinkKeys:
    """Run perform_api_link whose decrypted reply is ``reply``."""
    monkeypatch.setattr(
        linking,
        "deframe_feed",
        lambda _s, _c: [types.SimpleNamespace(ok=True, frame_no_crc=b"\x80\x00\x00xx")],
    )
    monkeypatch.setattr(linking, "decrypt_api_link_response", lambda **_k: (0, reply))
    return linking.perform_api_link(
        sock=_Sock(),
        client_identity=linking.E27Identity(mn="m", sn="s", fwver="f", hwver="h", osver="o"),
        access_code="a",
        passphrase="b",
        mn_for_hash="m",
        discovery_nonce=b"nonce",
        timeout_s=1.0,
    )


# Hardware (Tester report 2026-10-14, HACS #65 68618c2): the panel replied to
# api_link with the bare object below, no api_link key and no error_code. The
# match is on the message; no panel error code has been observed for it.
_BARE_SLOTS_FULL = b'{"error_message":"Not enough space"}'


def test_bare_error_reply_is_slots_full(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(E27LinkSlotsFull) as exc_info:
        _link_with_reply(monkeypatch, _BARE_SLOTS_FULL)
    assert exc_info.value.panel_error_message == "Not enough space"
    assert exc_info.value.panel_error_code is None


def test_bare_other_error_reply_is_protocol_error(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(E27ProtocolError) as exc_info:
        _link_with_reply(monkeypatch, b'{"error_message":"Something else"}')
    assert not isinstance(exc_info.value, E27LinkSlotsFull)
    assert "Something else" in str(exc_info.value)


def test_api_link_without_keys_is_slots_full() -> None:
    # Any error_code is carried through as-is (value here is arbitrary; the
    # panel's real code for this case, if any, is unconfirmed).
    with pytest.raises(E27LinkSlotsFull) as exc_info:
        linking.parse_api_link_response_json(
            {"api_link": {"error_code": 7, "error_message": "Not enough space"}}
        )
    assert exc_info.value.panel_error_code == 7
    assert exc_info.value.panel_error_message == "Not enough space"


def test_other_panel_message_stays_protocol_error() -> None:
    with pytest.raises(E27ProtocolError) as exc_info:
        linking.parse_api_link_response_json(
            {"api_link": {"error_code": 5, "error_text": "Something else"}}
        )
    assert not isinstance(exc_info.value, E27LinkSlotsFull)
    assert "Something else" in str(exc_info.value)


def test_keys_present_still_parse() -> None:
    assert linking.parse_api_link_response_json(
        {"api_link": {"enc": "aa", "hmac": "bb", "error_code": 0}}
    ) == ("aa", "bb")


def test_missing_keys_without_message_unchanged() -> None:
    with pytest.raises(E27ProtocolError):
        linking.parse_api_link_response_json({"api_link": {"error_code": 1}})


def test_public_error_is_exported() -> None:
    assert "Elke27LinkSlotsFullError" in elke27_lib.__all__
    err = Elke27LinkSlotsFullError(panel_error_message="Not enough space")
    assert err.code == "link_slots_full"
    assert err.is_transient is False
    assert err.panel_error_message == "Not enough space"


@pytest.mark.asyncio
async def test_async_link_bare_reply_raises_slots_full(monkeypatch: pytest.MonkeyPatch) -> None:
    """End to end from the decrypted panel reply through async_link."""
    kernel = E27Kernel()
    client = Elke27Client(kernel=kernel)

    async def _link(*_a: Any, **_k: Any) -> Any:
        try:
            return _link_with_reply(monkeypatch, _BARE_SLOTS_FULL)
        except E27LinkSlotsFull as exc:
            raise KernelError("link failed") from exc

    monkeypatch.setattr(kernel, "link", _link)
    with pytest.raises(Elke27LinkSlotsFullError) as exc_info:
        await client.async_link(
            "h",
            2101,
            access_code="1",
            passphrase="2",
            client_identity={"mn": "m", "sn": "s"},
        )
    assert exc_info.value.panel_error_message == "Not enough space"
    assert exc_info.value.panel_error_code is None


@pytest.mark.asyncio
@pytest.mark.parametrize("wrap", [False, True])
async def test_link_result_keeps_slots_full(monkeypatch: pytest.MonkeyPatch, wrap: bool) -> None:
    """Result-style link(): the error stays E27LinkSlotsFull, not CryptoError."""
    kernel = E27Kernel()
    client = Elke27Client(kernel=kernel)

    async def _link(*_a: Any, **_k: Any) -> Any:
        inner = E27LinkSlotsFull("Not enough space")
        if wrap:
            raise KernelError("link failed") from inner
        raise inner

    monkeypatch.setattr(kernel, "link", _link)
    result = await client.link(
        {"panel_host": "h", "port": 2101},
        linking.E27Identity(mn="m", sn="s", fwver="f", hwver="h", osver="o"),
        {"access_code": "1", "passphrase": "2"},
    )
    assert result.ok is False
    assert isinstance(result.error, E27LinkSlotsFull)
    assert not isinstance(result.error, CryptoError)
    assert result.error.panel_error_message == "Not enough space"
