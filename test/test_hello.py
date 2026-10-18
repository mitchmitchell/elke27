from __future__ import annotations

import json

import pytest

from elke27_lib import hello
from elke27_lib.errors import (
    E27HelloTimeout,
    E27ProtocolError,
    Elke27LinkRequiredError,
    Elke27ProtocolError,
)
from elke27_lib.linking import E27Identity


class _FakeSocket:
    def __init__(self, predata: bytes = b"", *, timeout: float | None = None) -> None:
        self.predata = predata
        self.timeout = timeout

    def gettimeout(self) -> float | None:
        return self.timeout

    def settimeout(self, timeout: float | None) -> None:
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
    with pytest.raises(E27HelloTimeout):
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
    with pytest.raises(E27HelloTimeout):
        hello.perform_hello(sock=sock, client_identity=_identity(), linkkey_hex="00", timeout_s=0)


def test_perform_hello_probe_recv_oserror_restores_timeout() -> None:
    io_timeout_s = 0.55

    class _ErrSocket(_FakeSocket):
        def recv(self, _size: int) -> bytes:
            raise OSError("probe recv failed")

    sock = _ErrSocket(timeout=io_timeout_s)
    with pytest.raises(OSError, match="probe recv failed"):
        hello.perform_hello(sock=sock, client_identity=_identity(), linkkey_hex="00", timeout_s=1)
    assert sock.gettimeout() == io_timeout_s


def test_perform_hello_preobjs_success(monkeypatch: pytest.MonkeyPatch) -> None:
    io_timeout_s = 0.42
    sock = _FakeSocket(predata=b"pre", timeout=io_timeout_s)
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
    assert sock.gettimeout() == io_timeout_s


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
    with pytest.raises(E27HelloTimeout):
        hello.perform_hello(sock=sock, client_identity=_identity(), linkkey_hex="00", timeout_s=1)


def test_perform_hello_deadline_without_hello_raises_hello_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sock = _FakeSocket()
    monkeypatch.setattr(hello, "send_unframed_json", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(hello, "recv_cleartext_json_objects", lambda *_a, **_k: [{"other": 1}])
    clock = {"t": 0.0}

    def _monotonic() -> float:
        if clock["t"] < 1.0:
            clock["t"] = 2.0
            return 0.0
        return 2.0

    monkeypatch.setattr(hello.time, "monotonic", _monotonic)
    with pytest.raises(E27HelloTimeout):
        hello.perform_hello(sock=sock, client_identity=_identity(), linkkey_hex="00", timeout_s=1)


def test_perform_hello_malformed_hello_object_raises_protocol_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sock = _FakeSocket()
    monkeypatch.setattr(hello, "send_unframed_json", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(hello, "recv_cleartext_json_objects", lambda *_a, **_k: [{"hello": None}])
    monkeypatch.setattr(hello.time, "monotonic", lambda: 0.0)
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


def _run_hello_with(monkeypatch: pytest.MonkeyPatch, hello_obj: dict) -> None:
    sock = _FakeSocket()
    monkeypatch.setattr(hello, "send_unframed_json", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(hello, "recv_cleartext_json_objects", lambda *_a, **_k: [hello_obj])
    monkeypatch.setattr(hello.time, "monotonic", lambda: 0.0)
    hello.perform_hello(sock=sock, client_identity=_identity(), linkkey_hex="00", timeout_s=1)


@pytest.mark.parametrize("code", [11006, "11006", 11008])
def test_perform_hello_link_error_code_raises_link_required(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, code: object
) -> None:
    from elke27_lib.errors import E27HelloLinkRequired, E27ProvisioningRequired

    caplog.set_level("DEBUG")
    hello_obj = {"hello": {"error_code": code, "error_message": "invalid_id"}}
    with pytest.raises(E27HelloLinkRequired) as ei:
        _run_hello_with(monkeypatch, hello_obj)
    assert isinstance(ei.value, E27ProvisioningRequired)
    assert ei.value.panel_error_code == int(str(code))
    assert ei.value.panel_error_message == "invalid_id"
    assert "Malformed" not in str(ei.value)
    recs = [r for r in caplog.records if "rejected HELLO" in r.getMessage()]
    assert recs and all(r.levelname == "WARNING" and r.exc_info is None for r in recs)


def test_perform_hello_other_error_code_names_code(monkeypatch: pytest.MonkeyPatch) -> None:
    from elke27_lib.errors import E27HelloRejected

    hello_obj = {"hello": {"error_code": 11016, "error_message": "in_use"}}
    with pytest.raises(E27HelloRejected) as ei:
        _run_hello_with(monkeypatch, hello_obj)
    assert ei.value.panel_error_code == 11016
    assert "11016" in str(ei.value) and "Malformed" not in str(ei.value)


@pytest.mark.parametrize("code", [0, "0"])
def test_perform_hello_error_code_zero_completes(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, code: object
) -> None:
    caplog.set_level("DEBUG")
    sock = _FakeSocket()
    hello_obj = {"hello": {"session_id": 7, "sk": "aa", "shm": "bb", "error_code": code}}
    monkeypatch.setattr(hello, "send_unframed_json", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(hello, "recv_cleartext_json_objects", lambda *_a, **_k: [hello_obj])
    monkeypatch.setattr(hello.time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(
        hello,
        "decrypt_key_field_with_linkkey",
        lambda **kw: b"\x01" * 16 if kw["ciphertext_hex"] == "aa" else b"\x02" * 32,
    )
    out = hello.perform_hello(sock=sock, client_identity=_identity(), linkkey_hex="00", timeout_s=1)
    assert out.session_id == 7
    assert out.session_key_hex == "01" * 16
    assert out.hmac_key_hex == "02" * 32
    assert not [r for r in caplog.records if "rejected HELLO" in r.getMessage()]


# --- #61: a HELLO reply without a session is a refused session, not "malformed" ---
@pytest.mark.parametrize(
    "hello_payload",
    [
        {},
        {"session_id": None},
        {"session_id": "", "sk": "", "shm": ""},
        {"sk": "aa", "shm": "bb"},  # session_id missing (the #61 log line)
        {"session_id": 5},  # no key material
        {"error_code": 0},
    ],
)
def test_perform_hello_without_session_is_refused_session(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, hello_payload: dict
) -> None:
    from elke27_lib.errors import E27HelloNoSession

    caplog.set_level("DEBUG")
    with pytest.raises(E27HelloNoSession) as ei:
        _run_hello_with(monkeypatch, {"hello": hello_payload})
    assert isinstance(ei.value, E27ProtocolError)  # existing callers still catch it
    text = str(ei.value)
    assert "Malformed" not in text and "another client may be using this link" in text
    recs = [r for r in caplog.records if "refused the session" in r.getMessage()]
    assert len(recs) == 1 and recs[0].levelname == "WARNING" and recs[0].exc_info is None


def test_refused_session_log_has_keys_not_values(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from elke27_lib.errors import E27HelloNoSession

    caplog.set_level("DEBUG")
    with pytest.raises(E27HelloNoSession):
        _run_hello_with(monkeypatch, {"hello": {"sk": "deadbeefcafe", "shm": "f00dbabe"}})
    assert "deadbeefcafe" not in caplog.text and "f00dbabe" not in caplog.text
    assert "'shm'" in caplog.text and "'sk'" in caplog.text


@pytest.mark.parametrize(
    "hello_payload",
    [
        {"session_id": "abc", "sk": "aa", "shm": "bb"},  # wrong type: still malformed
        {"session_id": 1, "sk": 5, "shm": "bb"},
    ],
)
def test_perform_hello_wrong_type_is_still_malformed(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, hello_payload: dict
) -> None:
    from elke27_lib.errors import E27HelloNoSession

    caplog.set_level("DEBUG")
    with pytest.raises(E27ProtocolError) as ei:
        _run_hello_with(monkeypatch, {"hello": hello_payload})
    assert not isinstance(ei.value, E27HelloNoSession)
    assert "Malformed" in str(ei.value)
    assert '"aa"' not in caplog.text and "'aa'" not in caplog.text  # keys only


def test_error_code_still_wins_over_missing_session(monkeypatch: pytest.MonkeyPatch) -> None:
    from elke27_lib.errors import E27HelloRejected

    with pytest.raises(E27HelloRejected):
        _run_hello_with(monkeypatch, {"hello": {"error_code": 11016}})


@pytest.mark.parametrize("error_code", ["bogus", [1], False, True, 0.0])
def test_wrong_type_error_code_without_session_is_malformed_not_refused(
    monkeypatch: pytest.MonkeyPatch, error_code: object
) -> None:
    from elke27_lib.errors import E27HelloNoSession

    with pytest.raises(E27ProtocolError) as ei:
        _run_hello_with(monkeypatch, {"hello": {"error_code": error_code}})
    assert not isinstance(ei.value, E27HelloNoSession)
    assert "Malformed" in str(ei.value)


class _ConnSocket(_FakeSocket):
    """A TCP socket that connects at once; the HELLO exchange itself is faked."""

    def connect(self, _addr: object) -> None:
        return None

    def close(self) -> None:
        return None

    def shutdown(self, _how: int) -> None:
        return None

    def fileno(self) -> int:
        return -1


def _hello_reply_on_connect(monkeypatch: pytest.MonkeyPatch, hello_obj: dict) -> None:
    """Make the real Session.connect see `hello_obj` as the panel's HELLO reply."""
    import socket
    import types

    from elke27_lib import session as session_mod

    fake_socket_mod = types.SimpleNamespace(**vars(socket))
    fake_socket_mod.socket = lambda *_a, **_k: _ConnSocket()
    monkeypatch.setattr(session_mod, "socket", fake_socket_mod)
    monkeypatch.setattr(hello, "send_unframed_json", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(hello, "recv_cleartext_json_objects", lambda *_a, **_k: [hello_obj])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("hello_payload", "expected_exc", "text"),
    [
        ({"session_id": 7}, Elke27ProtocolError, "another client may be using this link"),
        ({"error_code": 11016, "error_message": "in_use"}, Elke27ProtocolError, "11016"),
        (
            {"error_code": 11006, "error_message": "invalid_id"},
            Elke27LinkRequiredError,
            "linking required",
        ),
    ],
    ids=["no-session", "rejected", "link-required"],
)
async def test_hello_refusal_on_connect_raises_clear_error_without_connection_lost(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    hello_payload: dict,
    expected_exc: type[Exception],
    text: str,
) -> None:
    """async_connect against a panel that refuses HELLO: the real session and kernel
    connect path raises the public error, logs the connect failure at DEBUG, and
    never reports a lost connection (there was no session to lose)."""
    import logging

    from elke27_lib.client import Elke27Client, LinkKeys

    _hello_reply_on_connect(monkeypatch, {"hello": hello_payload})
    client = Elke27Client()
    with caplog.at_level(logging.DEBUG), pytest.raises(expected_exc, match=text):
        await client.async_connect("127.0.0.1", 2101, LinkKeys("aa", "bb", "cc"))
    records = caplog.records
    assert not [r for r in records if "connection lost" in r.getMessage()]
    assert [
        r
        for r in records
        if r.levelno == logging.DEBUG and "Panel connection closed" in r.getMessage()
    ]
    connect_failed = [r for r in records if "Connect failed" in r.getMessage()]
    assert connect_failed and all(r.levelno == logging.DEBUG for r in connect_failed)
    assert not [
        r for r in records if r.name.startswith("elke27_lib.client") and r.levelno >= logging.ERROR
    ]
