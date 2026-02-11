from __future__ import annotations

import importlib

import pytest

from elke27_lib import encryption as enc


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


def test_crypto_backend_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    module = importlib.import_module("elke27_lib.encryption")
    monkeypatch.setattr(module, "_has_crypto", False)
    monkeypatch.setattr(module, "Cipher", None)
    monkeypatch.setattr(module, "algorithms", None)
    monkeypatch.setattr(module, "modes", None)
    monkeypatch.setattr(module, "default_backend", None)
    with pytest.raises(enc.E27CryptoError):
        module._aes_cbc_encrypt_no_padding(b"\x00" * 16, enc.API_LINK_IV, b"\x00" * 16)
    with pytest.raises(enc.E27CryptoError):
        module._aes_cbc_decrypt_no_padding(b"\x00" * 16, enc.API_LINK_IV, b"\x00" * 16)


def test_require_helpers_errors() -> None:
    with pytest.raises(enc.E27CryptoError):
        enc._require_block_multiple(None, 16, "data")  # type: ignore[arg-type]
    with pytest.raises(enc.E27CryptoError):
        enc._require_block_multiple(b"", 16, "data")
    with pytest.raises(enc.E27CryptoError):
        enc._require_block_multiple(b"\x00" * 3, 4, "data")
    with pytest.raises(enc.E27CryptoError):
        enc._require_len(None, 16, "key")  # type: ignore[arg-type]


def test_import_without_crypto(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def _fake_import(name, globals=None, locals=None, fromlist=(), level=0):  # type: ignore[no-untyped-def]
        if name.startswith("cryptography"):
            raise ImportError("no crypto")
        return real_import(name, globals, locals, fromlist, level)

    with monkeypatch.context() as m:
        m.setattr(builtins, "__import__", _fake_import)
        module = importlib.reload(enc)
        assert module._has_crypto is False
        assert module.Cipher is None
        assert module.algorithms is None
        assert module.modes is None
        assert module.default_backend is None

    importlib.reload(enc)
