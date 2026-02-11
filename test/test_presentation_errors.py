from __future__ import annotations

import pytest

from elke27_lib import presentation
from elke27_lib.errors import E27ProtocolError


def test_require_helpers_and_iv_length() -> None:
    with pytest.raises(E27ProtocolError):
        presentation._require_len("ciphertext", b"", 16)
    with pytest.raises(E27ProtocolError):
        presentation._require_key_16(b"\x00" * 15, context_phase="x")
    with pytest.raises(E27ProtocolError):
        presentation._aes128_cbc_decrypt(key=b"\x00" * 16, iv=b"\x00", ciphertext=b"\x00" * 16)
    with pytest.raises(E27ProtocolError):
        presentation._aes128_cbc_encrypt(key=b"\x00" * 16, iv=b"\x00", plaintext=b"\x00" * 16)


def test_decrypt_schema0_envelope_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(E27ProtocolError):
        presentation.decrypt_schema0_envelope(
            protocol_byte=0x01, ciphertext=b"\x00" * 16, session_key=b"\x00" * 16
        )

    monkeypatch.setattr(presentation, "swap_endianness", lambda b: b)
    monkeypatch.setattr(presentation, "_aes128_cbc_decrypt", lambda **_k: b"\x00" * 8)
    with pytest.raises(E27ProtocolError):
        presentation.decrypt_schema0_envelope(
            protocol_byte=0x80, ciphertext=b"\x00" * 16, session_key=b"\x00" * 16
        )

    monkeypatch.setattr(presentation, "_aes128_cbc_decrypt", lambda **_k: b"\x00" * 16)
    monkeypatch.setattr(presentation, "protocol_padding_len", lambda _p: 16)
    with pytest.raises(E27ProtocolError):
        presentation.decrypt_schema0_envelope(
            protocol_byte=0x80, ciphertext=b"\x00" * 16, session_key=b"\x00" * 16
        )

    monkeypatch.setattr(presentation, "protocol_padding_len", lambda _p: 3)
    monkeypatch.setattr(presentation, "_aes128_cbc_decrypt", lambda **_k: b"\x00" * 10)
    with pytest.raises(E27ProtocolError):
        presentation.decrypt_schema0_envelope(
            protocol_byte=0x80 | 0x03, ciphertext=b"\x00" * 16, session_key=b"\x00" * 16
        )


def test_encrypt_schema0_envelope_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(E27ProtocolError):
        presentation.encrypt_schema0_envelope(payload=b"", session_key=b"\x00" * 16, src=256)
    with pytest.raises(E27ProtocolError):
        presentation.encrypt_schema0_envelope(
            payload=b"", session_key=b"\x00" * 16, envelope_seq=-1
        )

    monkeypatch.setattr(presentation, "calculate_block_padding", lambda _n: 16)
    with pytest.raises(E27ProtocolError):
        presentation.encrypt_schema0_envelope(payload=b"", session_key=b"\x00" * 16)

    monkeypatch.setattr(presentation, "calculate_block_padding", lambda _n: 1)
    with pytest.raises(E27ProtocolError):
        presentation.encrypt_schema0_envelope(payload=b"", session_key=b"\x00" * 16)


def test_decrypt_api_link_response_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(E27ProtocolError):
        presentation.decrypt_api_link_response(
            protocol_byte=0x80, ciphertext=b"\x00" * 16, tempkey_hex="zz"
        )

    monkeypatch.setattr(presentation, "swap_endianness", lambda b: b)
    monkeypatch.setattr(presentation, "_aes128_cbc_decrypt", lambda **_k: b"\x00" * 5)
    with pytest.raises(E27ProtocolError):
        presentation.decrypt_api_link_response(
            protocol_byte=0x80, ciphertext=b"\x00" * 16, tempkey_hex="00" * 16
        )

    monkeypatch.setattr(presentation, "_aes128_cbc_decrypt", lambda **_k: b"\x00" * 10)
    monkeypatch.setattr(presentation, "protocol_padding_len", lambda _p: 5)
    with pytest.raises(E27ProtocolError):
        presentation.decrypt_api_link_response(
            protocol_byte=0x80, ciphertext=b"\x00" * 16, tempkey_hex="00" * 16
        )

    pt = b"\x00" * 8 + b"\x00\x00"
    monkeypatch.setattr(presentation, "protocol_padding_len", lambda _p: 0)
    monkeypatch.setattr(presentation, "_aes128_cbc_decrypt", lambda **_k: pt)
    with pytest.raises(E27ProtocolError):
        presentation.decrypt_api_link_response(
            protocol_byte=0x80, ciphertext=b"\x00" * 16, tempkey_hex="00" * 16
        )


def test_decrypt_key_field_with_linkkey_hex_errors() -> None:
    with pytest.raises(E27ProtocolError):
        presentation.decrypt_key_field_with_linkkey(linkkey_hex="zz", ciphertext_hex="00")
    with pytest.raises(E27ProtocolError):
        presentation.decrypt_key_field_with_linkkey(linkkey_hex="00" * 16, ciphertext_hex="zz")
