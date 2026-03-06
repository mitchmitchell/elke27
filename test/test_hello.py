from __future__ import annotations

import json

import pytest

from elke27_lib import hello
from elke27_lib.errors import E27ProtocolError
from elke27_lib.linking import E27Identity


class _FakeSocket:
    def __init__(self, predata: bytes = b"") -> None:
        self.predata = predata
        self.timeout: float | None = None

    def settimeout(self, timeout: float) -> None:
        self.timeout = timeout

    def recv(self, _size: int) -> bytes:
        return self.predata

    def sendall(self, _data: bytes, _flags: int = 0) -> None:
        return None


def _identity() -> E27Identity:
    return E27Identity(mn="mn", sn="sn", fwver="fw", hwver="hw", osver="os")


def test_select_hello_object_and_coerce_helpers() -> None:
    obj = {"hello": {"session_id": 1}}
    assert hello._select_hello_object([obj]) is obj
    with pytest.raises(E27ProtocolError):
        hello._select_hello_object([{"no": "hello"}])
    assert hello._coerce_intish(1, field="f") == 1
    assert hello._coerce_intish("123", field="f") == 123
    with pytest.raises(ValueError):
        hello._coerce_intish("abc", field="f")
    assert hello._coerce_required_str("x", field="f") == "x"
    with pytest.raises(ValueError):
        hello._coerce_required_str("", field="f")


def test_perform_hello_missing_hello(monkeypatch: pytest.MonkeyPatch) -> None:
    sock = _FakeSocket()
    monkeypatch.setattr(hello, "send_unframed_json", lambda *_args, **_kwargs: None)
    with pytest.raises(E27ProtocolError):
        hello.perform_hello(sock=sock, client_identity=_identity(), linkkey_hex="00", timeout_s=0)


def test_perform_hello_recv_error(monkeypatch: pytest.MonkeyPatch) -> None:
    sock = _FakeSocket()

    def _recv(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise ValueError("bad")

    monkeypatch.setattr(hello, "send_unframed_json", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(hello, "recv_cleartext_json_objects", _recv)
    monkeypatch.setattr(hello.time, "monotonic", lambda: 0.0)
    with pytest.raises(E27ProtocolError):
        hello.perform_hello(sock=sock, client_identity=_identity(), linkkey_hex="00", timeout_s=1)


def test_perform_hello_predata_parse_error(monkeypatch: pytest.MonkeyPatch) -> None:
    sock = _FakeSocket(predata=b"junk")

    def _raise(_data: bytes):  # type: ignore[no-untyped-def]
        raise json.JSONDecodeError("bad", "x", 0)

    monkeypatch.setattr(hello, "send_unframed_json", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(hello, "recv_cleartext_json_objects_from_bytes", _raise)
    with pytest.raises(E27ProtocolError):
        hello.perform_hello(sock=sock, client_identity=_identity(), linkkey_hex="00", timeout_s=0)


def test_perform_hello_preobjs_success(monkeypatch: pytest.MonkeyPatch) -> None:
    sock = _FakeSocket(predata=b"pre")
    hello_obj = {"hello": {"session_id": 1, "sk": "aa", "shm": "bb", "error_code": 0}}
    monkeypatch.setattr(hello, "recv_cleartext_json_objects_from_bytes", lambda _d: [hello_obj])
    monkeypatch.setattr(hello, "send_unframed_json", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        hello,
        "decrypt_key_field_with_linkkey",
        lambda **_kwargs: b"\x00" * 16 if _kwargs["ciphertext_hex"] == "aa" else b"\x00" * 32,
    )
    out = hello.perform_hello(sock=sock, client_identity=_identity(), linkkey_hex="00", timeout_s=0)
    assert out.session_id == 1


def test_perform_hello_parse_error(monkeypatch: pytest.MonkeyPatch) -> None:
    sock = _FakeSocket()
    monkeypatch.setattr(hello, "send_unframed_json", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(hello, "recv_cleartext_json_objects", lambda *_a, **_k: [{"hello": None}])
    monkeypatch.setattr(hello.time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(hello, "_select_hello_object", lambda _objs: {"hello": None})
    with pytest.raises(E27ProtocolError):
        hello.perform_hello(sock=sock, client_identity=_identity(), linkkey_hex="00", timeout_s=1)


def test_perform_hello_timeout_continue(monkeypatch: pytest.MonkeyPatch) -> None:
    sock = _FakeSocket()
    calls = {"n": 0}

    def _fake_monotonic() -> float:
        calls["n"] += 1
        return 0.0 if calls["n"] <= 2 else 1.1

    monkeypatch.setattr(hello, "send_unframed_json", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        hello,
        "recv_cleartext_json_objects",
        lambda *_a, **_k: (_ for _ in ()).throw(hello.E27Timeout()),
    )
    monkeypatch.setattr(hello.time, "monotonic", _fake_monotonic)
    with pytest.raises(E27ProtocolError):
        hello.perform_hello(sock=sock, client_identity=_identity(), linkkey_hex="00", timeout_s=1)


def test_perform_hello_error_code(monkeypatch: pytest.MonkeyPatch) -> None:
    sock = _FakeSocket()
    hello_obj = {"hello": {"session_id": 1, "sk": "aa", "shm": "bb", "error_code": 1}}
    monkeypatch.setattr(hello, "send_unframed_json", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(hello, "recv_cleartext_json_objects", lambda *_a, **_k: [hello_obj])
    monkeypatch.setattr(hello.time, "monotonic", lambda: 0.0)
    with pytest.raises(E27ProtocolError):
        hello.perform_hello(sock=sock, client_identity=_identity(), linkkey_hex="00", timeout_s=1)


def test_perform_hello_decrypt_error(monkeypatch: pytest.MonkeyPatch) -> None:
    sock = _FakeSocket()
    hello_obj = {"hello": {"session_id": 1, "sk": "aa", "shm": "bb", "error_code": 0}}
    monkeypatch.setattr(hello, "send_unframed_json", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(hello, "recv_cleartext_json_objects", lambda *_a, **_k: [hello_obj])
    monkeypatch.setattr(hello.time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(
        hello,
        "decrypt_key_field_with_linkkey",
        lambda **_kwargs: (_ for _ in ()).throw(ValueError("bad")),
    )
    with pytest.raises(E27ProtocolError):
        hello.perform_hello(sock=sock, client_identity=_identity(), linkkey_hex="00", timeout_s=1)


def test_perform_hello_bad_session_key_length(monkeypatch: pytest.MonkeyPatch) -> None:
    sock = _FakeSocket()
    hello_obj = {"hello": {"session_id": 1, "sk": "aa", "shm": "bb", "error_code": 0}}
    monkeypatch.setattr(hello, "send_unframed_json", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(hello, "recv_cleartext_json_objects", lambda *_a, **_k: [hello_obj])
    monkeypatch.setattr(hello.time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(
        hello,
        "decrypt_key_field_with_linkkey",
        lambda **_kwargs: b"\x00" * 15 if _kwargs["ciphertext_hex"] == "aa" else b"\x00" * 32,
    )
    with pytest.raises(E27ProtocolError):
        hello.perform_hello(sock=sock, client_identity=_identity(), linkkey_hex="00", timeout_s=1)


def test_perform_hello_bad_hmac_key_length(monkeypatch: pytest.MonkeyPatch) -> None:
    sock = _FakeSocket()
    hello_obj = {"hello": {"session_id": 1, "sk": "aa", "shm": "bb", "error_code": 0}}
    monkeypatch.setattr(hello, "send_unframed_json", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(hello, "recv_cleartext_json_objects", lambda *_a, **_k: [hello_obj])
    monkeypatch.setattr(hello.time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(
        hello,
        "decrypt_key_field_with_linkkey",
        lambda **_kwargs: b"\x00" * 16 if _kwargs["ciphertext_hex"] == "aa" else b"\x00" * 31,
    )
    with pytest.raises(E27ProtocolError):
        hello.perform_hello(sock=sock, client_identity=_identity(), linkkey_hex="00", timeout_s=1)
