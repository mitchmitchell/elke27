from __future__ import annotations

from pathlib import Path

import pytest

from elke27_lib import encryption_loop as enc

_REPO_ROOT = Path(__file__).resolve().parents[1]
_ENCRYPTION_LOOP_SRC = _REPO_ROOT / "src" / "elke27_lib" / "encryption_loop.py"


def test_hex_to_bytes_valid() -> None:
    assert enc.hex_to_bytes("00ff") == bytes([0x00, 0xFF])


@pytest.mark.parametrize("value", [None, "", " ", "0", "abc", "zz"])
def test_hex_to_bytes_invalid(value: str | None) -> None:
    with pytest.raises(enc.E27CryptoError):
        enc.hex_to_bytes(value)  # type: ignore[arg-type]


def test_swap_endianness_basic() -> None:
    assert enc.swap_endianness(b"\x01\x02\x03\x04") == b"\x04\x03\x02\x01"
    assert (
        enc.swap_endianness(b"\x01\x02\x03\x04\x10\x11\x12\x13")
        == b"\x04\x03\x02\x01\x13\x12\x11\x10"
    )


@pytest.mark.parametrize("value", [None, b"", b"\x01", b"\x01\x02"])
def test_swap_endianness_invalid(value: bytes | None) -> None:
    with pytest.raises(enc.E27CryptoError):
        enc.swap_endianness(value)  # type: ignore[arg-type]


def test_calculate_block_padding() -> None:
    assert enc.calculate_block_padding(0) == 0
    assert enc.calculate_block_padding(1) == 15
    assert enc.calculate_block_padding(16) == 0


def test_calculate_block_padding_negative() -> None:
    with pytest.raises(enc.E27CryptoError):
        enc.calculate_block_padding(-1)


def test_schema0_encrypt_decrypt_roundtrip() -> None:
    key = b"\x00" * 16
    pt = b"\x01" * 16
    ct = enc.encrypt_schema0_plaintext(key=key, plaintext=pt)
    assert ct != pt
    out = enc.decrypt_schema0_ciphertext(key=key, ciphertext=ct)
    assert out == pt


def test_schema0_invalid_lengths() -> None:
    key = b"\x00" * 16
    with pytest.raises(enc.E27CryptoError):
        enc.encrypt_schema0_plaintext(key=key, plaintext=b"")
    with pytest.raises(enc.E27CryptoError):
        enc.decrypt_schema0_ciphertext(key=key, ciphertext=b"")


def test_key_conversions() -> None:
    raw = bytes(range(16)).hex()
    assert enc.tempkey_hex_to_aes_key(raw) == enc.swap_endianness(bytes(range(16)))
    assert enc.linkkey_hex_to_aes_key(raw) == enc.swap_endianness(bytes(range(16)))
    assert enc.sessionkey_hex_to_aes_key(raw) == bytes(range(16))


def test_key_conversions_invalid_length() -> None:
    with pytest.raises(enc.E27CryptoError):
        enc.tempkey_hex_to_aes_key("00")
    with pytest.raises(enc.E27CryptoError):
        enc.linkkey_hex_to_aes_key("00")
    with pytest.raises(enc.E27CryptoError):
        enc.sessionkey_hex_to_aes_key("00")


def test_decrypt_hello_field_roundtrip() -> None:
    key_hex = "00112233445566778899aabbccddeeff"
    key = enc.linkkey_hex_to_aes_key(key_hex)
    pt = b"\x10" * 16
    ct = enc._aes_cbc_encrypt_no_padding(key, enc.API_LINK_IV, enc.swap_endianness(pt))
    ct_hex = enc.swap_endianness(ct).hex()
    out = enc.decrypt_hello_field(linkkey_hex=key_hex, field_hex=ct_hex)
    assert out == pt


def test_require_helpers_errors() -> None:
    with pytest.raises(enc.E27CryptoError):
        enc._require_block_multiple(None, 16, "data")  # type: ignore[arg-type]
    with pytest.raises(enc.E27CryptoError):
        enc._require_block_multiple(b"", 16, "data")
    with pytest.raises(enc.E27CryptoError):
        enc._require_block_multiple(b"\x00" * 3, 4, "data")
    with pytest.raises(enc.E27CryptoError):
        enc._require_len(None, 16, "key")  # type: ignore[arg-type]


def test_encryption_loop_no_optional_crypto_fallback() -> None:
    text = _ENCRYPTION_LOOP_SRC.read_text(encoding="utf-8")
    assert "except ImportError" not in text
    assert "_has_crypto" not in text


def test_encryption_loop_no_default_backend() -> None:
    text = _ENCRYPTION_LOOP_SRC.read_text(encoding="utf-8")
    assert "default_backend" not in text
