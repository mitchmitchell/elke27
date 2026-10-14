"""api_link refused because the panel link table is full -> Elke27LinkSlotsFullError."""

from __future__ import annotations

from typing import Any

import pytest

import elke27_lib
from elke27_lib import Elke27Client, Elke27LinkSlotsFullError, linking
from elke27_lib.errors import E27LinkSlotsFull, E27ProtocolError
from elke27_lib.kernel import E27Kernel, KernelError


def test_bare_error_object_is_slots_full() -> None:
    with pytest.raises(E27LinkSlotsFull) as exc_info:
        linking._raise_panel_link_error({"error_message": "Not enough space"})
    assert exc_info.value.panel_error_message == "Not enough space"
    assert exc_info.value.panel_error_code is None


def test_api_link_without_keys_is_slots_full() -> None:
    with pytest.raises(E27LinkSlotsFull) as exc_info:
        linking.parse_api_link_response_json(
            {"api_link": {"error_code": 11008, "error_message": "Not enough space"}}
        )
    assert exc_info.value.panel_error_code == 11008
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
@pytest.mark.parametrize("wrap", [False, True])
async def test_async_link_raises_slots_full(monkeypatch: pytest.MonkeyPatch, wrap: bool) -> None:
    kernel = E27Kernel()
    client = Elke27Client(kernel=kernel)

    async def _link(*_a: Any, **_k: Any) -> Any:
        inner = E27LinkSlotsFull("Not enough space", 11008)
        if wrap:
            raise KernelError("link failed") from inner
        raise inner

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
    assert exc_info.value.panel_error_code == 11008
