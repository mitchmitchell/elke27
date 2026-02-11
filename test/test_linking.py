from __future__ import annotations

import json
import types

import pytest

from elke27_lib import linking
from elke27_lib.errors import E27ProtocolError, E27ProvisioningTimeout, E27TransportError


class _FakeSocket:
    def __init__(self, recv_items: list[object] | None = None) -> None:
        self._recv_items = list(recv_items or [])
        self.sent: list[bytes] = []
        self.timeouts: list[float] = []

    def settimeout(self, t: float) -> None:
        self.timeouts.append(t)

    def recv(self, _n: int) -> bytes:
        if not self._recv_items:
            return b""
        item = self._recv_items.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item  # type: ignore[return-value]

    def sendall(self, data: bytes) -> None:
        self.sent.append(data)


def _monotonic_gen(values: list[float]):
    it = iter(values)

    def _monotonic() -> float:
        try:
            return next(it)
        except StopIteration:
            return values[-1]

    return _monotonic


def test_parse_concatenated_json_objects() -> None:
    s = '{"a":1}{"b":"{x}"}{"c":"\\""}'
    parts = linking._parse_concatenated_json_objects(s)
    assert parts == ['{"a":1}', '{"b":"{x}"}', '{"c":"\\""}']


def test_parse_concatenated_json_objects_unbalanced() -> None:
    with pytest.raises(ValueError):
        linking._parse_concatenated_json_objects('{"a":1')


def test_recv_cleartext_json_objects() -> None:
    sock = _FakeSocket([b'{"a":1}{"b":2}'])
    objs = linking.recv_cleartext_json_objects(sock, timeout_s=1.0)
    assert objs == [{"a": 1}, {"b": 2}]


def test_recv_cleartext_json_objects_decode_error(monkeypatch: pytest.MonkeyPatch) -> None:
    sock = _FakeSocket([b"{}"])
    monkeypatch.setattr(linking, "_parse_concatenated_json_objects", lambda _s: ["{bad}"])
    with pytest.raises(E27ProtocolError):
        linking.recv_cleartext_json_objects(sock, timeout_s=1.0)


def test_recv_cleartext_json_objects_timeout() -> None:
    sock = _FakeSocket([TimeoutError()])
    with pytest.raises(E27ProvisioningTimeout):
        linking.recv_cleartext_json_objects(sock, timeout_s=1.0)


def test_recv_cleartext_json_objects_oserror() -> None:
    sock = _FakeSocket([OSError("boom")])
    with pytest.raises(E27TransportError):
        linking.recv_cleartext_json_objects(sock, timeout_s=1.0)


def test_recv_cleartext_json_objects_empty() -> None:
    sock = _FakeSocket([b""])
    with pytest.raises(E27TransportError):
        linking.recv_cleartext_json_objects(sock, timeout_s=1.0)


def test_wait_for_discovery_nonce(monkeypatch: pytest.MonkeyPatch) -> None:
    hello = b'{"ELKWC2017":"Hello","nonce":"abc"}{"LOCAL":"now"}'
    sock = _FakeSocket([b"nope", hello])
    monkeypatch.setattr(linking.time, "monotonic", _monotonic_gen([0.0, 0.1, 0.2, 0.3]))
    assert linking.wait_for_discovery_nonce(sock, timeout_s=1.0) == "abc"


def test_wait_for_discovery_nonce_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    sock = _FakeSocket([TimeoutError(), TimeoutError()])
    monkeypatch.setattr(linking.time, "monotonic", _monotonic_gen([0.0, 2.0, 3.0]))
    with pytest.raises(E27ProvisioningTimeout):
        linking.wait_for_discovery_nonce(sock, timeout_s=1.0)


def test_wait_for_discovery_nonce_oserror(monkeypatch: pytest.MonkeyPatch) -> None:
    sock = _FakeSocket([TimeoutError(), OSError("boom")])
    monkeypatch.setattr(linking.time, "monotonic", _monotonic_gen([0.0, 0.1, 0.2]))
    with pytest.raises(E27TransportError):
        linking.wait_for_discovery_nonce(sock, timeout_s=1.0)


def test_wait_for_discovery_nonce_socket_closed() -> None:
    sock = _FakeSocket([b""])
    with pytest.raises(E27TransportError):
        linking.wait_for_discovery_nonce(sock, timeout_s=1.0)


def test_parse_discovery_hello_and_local() -> None:
    data = b'{"nonce":"n"}{"LOCAL":"ts"}'
    nonce, local = linking.parse_discovery_hello_and_local(data)
    assert nonce == "n"
    assert local == "ts"


def test_recv_cleartext_json_objects_from_bytes_skips_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(linking, "_parse_concatenated_json_objects", lambda _s: ["", "{}"])
    assert linking.recv_cleartext_json_objects_from_bytes(b"{}") == [{}]


def test_derive_pass_tempkey_with_cnonce() -> None:
    p, t = linking.derive_pass_tempkey_with_cnonce(
        access_code="a",
        passphrase="b",
        nonce="c",
        cnonce="d",
        mn="m",
        sn="s",
    )
    assert len(p) == 8
    assert len(t) == 32


def test_derive_pass_and_tempkey_requires_cnonce() -> None:
    with pytest.raises(RuntimeError):
        linking.derive_pass_and_tempkey(access_code="a", passphrase="b", nonce="c", mn="m", sn="s")


def test_build_api_link_request() -> None:
    ident = linking.E27Identity(mn="m", sn="s", fwver="f", hwver="h", osver="o")
    req = linking.build_api_link_request(
        seq=1, client_identity=ident, pass_hex8="12345678", cnonce_hex="00"
    )
    obj = json.loads(req)
    assert obj["seq"] == 1
    assert obj["api_link"]["mn"] == "m"


def test_send_unframed_json_error() -> None:
    sock = _FakeSocket()
    sock.sendall = types.MethodType(lambda _self, _data: (_ for _ in ()).throw(OSError()), sock)  # type: ignore[assignment]
    with pytest.raises(E27TransportError):
        linking.send_unframed_json(sock, "{}")


def test_parse_api_link_response_json_errors() -> None:
    with pytest.raises(E27ProtocolError):
        linking.parse_api_link_response_json({})
    with pytest.raises(E27ProtocolError):
        linking.parse_api_link_response_json({"api_link": {"error_code": 1}})


def _fake_deframe_result(frame: bytes):
    return types.SimpleNamespace(ok=True, frame_no_crc=frame)


def test_perform_api_link_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    sock = _FakeSocket([])
    monkeypatch.setattr(linking.time, "monotonic", _monotonic_gen([0.0, 0.0, 1.0]))
    with pytest.raises(E27ProvisioningTimeout):
        linking.perform_api_link(
            sock=sock,
            client_identity=linking.E27Identity(mn="m", sn="s", fwver="f", hwver="h", osver="o"),
            access_code="a",
            passphrase="b",
            mn_for_hash="m",
            discovery_nonce=b"nonce",
            timeout_s=0.0,
        )


def test_perform_api_link_timeout_default(monkeypatch: pytest.MonkeyPatch) -> None:
    sock = _FakeSocket([TimeoutError(), TimeoutError()])
    monkeypatch.setattr(linking.time, "monotonic", _monotonic_gen([0.0, 0.0, 6.0]))
    with pytest.raises(E27ProvisioningTimeout):
        linking.perform_api_link(
            sock=sock,
            client_identity=linking.E27Identity(mn="m", sn="s", fwver="f", hwver="h", osver="o"),
            access_code="a",
            passphrase="b",
            mn_for_hash="m",
            discovery_nonce=b"nonce",
            timeout_s=None,
        )


def test_perform_api_link_short_frame(monkeypatch: pytest.MonkeyPatch) -> None:
    sock = _FakeSocket([b"\x00"])
    monkeypatch.setattr(linking, "deframe_feed", lambda _s, _c: [_fake_deframe_result(b"\x01\x02")])
    with pytest.raises(E27ProtocolError):
        linking.perform_api_link(
            sock=sock,
            client_identity=linking.E27Identity(mn="m", sn="s", fwver="f", hwver="h", osver="o"),
            access_code="a",
            passphrase="b",
            mn_for_hash="m",
            discovery_nonce=b"nonce",
            timeout_s=1.0,
        )


def test_perform_api_link_empty_ciphertext(monkeypatch: pytest.MonkeyPatch) -> None:
    sock = _FakeSocket([b"\x00"])
    monkeypatch.setattr(
        linking, "deframe_feed", lambda _s, _c: [_fake_deframe_result(b"\x80\x00\x00")]
    )
    with pytest.raises(E27ProtocolError):
        linking.perform_api_link(
            sock=sock,
            client_identity=linking.E27Identity(mn="m", sn="s", fwver="f", hwver="h", osver="o"),
            access_code="a",
            passphrase="b",
            mn_for_hash="m",
            discovery_nonce=b"nonce",
            timeout_s=1.0,
        )


def test_perform_api_link_decode_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    sock = _FakeSocket([b"\x00"])
    monkeypatch.setattr(
        linking, "deframe_feed", lambda _s, _c: [_fake_deframe_result(b"\x80\x00\x00" + b"xx")]
    )
    monkeypatch.setattr(linking, "decrypt_api_link_response", lambda **_k: (0x00, b"\xff"))
    with pytest.raises(E27ProtocolError):
        linking.perform_api_link(
            sock=sock,
            client_identity=linking.E27Identity(mn="m", sn="s", fwver="f", hwver="h", osver="o"),
            access_code="a",
            passphrase="b",
            mn_for_hash="m",
            discovery_nonce=b"nonce",
            timeout_s=1.0,
        )


def test_perform_api_link_no_api_link(monkeypatch: pytest.MonkeyPatch) -> None:
    sock = _FakeSocket([b"\x00"])
    monkeypatch.setattr(
        linking, "deframe_feed", lambda _s, _c: [_fake_deframe_result(b"\x80\x00\x00" + b"xx")]
    )
    monkeypatch.setattr(linking, "decrypt_api_link_response", lambda **_k: (0x00, b'{"x":1}'))
    with pytest.raises(E27ProtocolError):
        linking.perform_api_link(
            sock=sock,
            client_identity=linking.E27Identity(mn="m", sn="s", fwver="f", hwver="h", osver="o"),
            access_code="a",
            passphrase="b",
            mn_for_hash="m",
            discovery_nonce=b"nonce",
            timeout_s=1.0,
        )


def test_perform_api_link_success(monkeypatch: pytest.MonkeyPatch) -> None:
    sock = _FakeSocket([b"\x00"])
    monkeypatch.setattr(
        linking, "deframe_feed", lambda _s, _c: [_fake_deframe_result(b"\x80\x00\x00" + b"xx")]
    )
    payload = b'{"api_link":{"enc":"aa","hmac":"bb","error_code":0}}'
    monkeypatch.setattr(linking, "decrypt_api_link_response", lambda **_k: (0x01, payload))
    keys = linking.perform_api_link(
        sock=sock,
        client_identity=linking.E27Identity(mn="m", sn="s", fwver="f", hwver="h", osver="o"),
        access_code="a",
        passphrase="b",
        mn_for_hash="m",
        discovery_nonce=b"nonce",
        timeout_s=1.0,
    )
    assert keys.linkkey_hex == "aa"
    assert keys.linkhmac_hex == "bb"


def test_perform_api_link_socket_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    sock = _FakeSocket([TimeoutError(), OSError("boom")])
    monkeypatch.setattr(linking.time, "monotonic", _monotonic_gen([0.0, 0.1, 0.2]))
    with pytest.raises(E27TransportError):
        linking.perform_api_link(
            sock=sock,
            client_identity=linking.E27Identity(mn="m", sn="s", fwver="f", hwver="h", osver="o"),
            access_code="a",
            passphrase="b",
            mn_for_hash="m",
            discovery_nonce=b"nonce",
            timeout_s=1.0,
        )


def test_perform_api_link_socket_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    sock = _FakeSocket([b""])
    monkeypatch.setattr(linking.time, "monotonic", _monotonic_gen([0.0, 0.1]))
    with pytest.raises(E27TransportError):
        linking.perform_api_link(
            sock=sock,
            client_identity=linking.E27Identity(mn="m", sn="s", fwver="f", hwver="h", osver="o"),
            access_code="a",
            passphrase="b",
            mn_for_hash="m",
            discovery_nonce=b"nonce",
            timeout_s=1.0,
        )


def test_perform_api_link_no_json_objects(monkeypatch: pytest.MonkeyPatch) -> None:
    sock = _FakeSocket([b"\x00"])
    monkeypatch.setattr(
        linking, "deframe_feed", lambda _s, _c: [_fake_deframe_result(b"\x80\x00\x00" + b"xx")]
    )
    monkeypatch.setattr(linking, "decrypt_api_link_response", lambda **_k: (0x01, b""))
    monkeypatch.setattr(linking, "_parse_concatenated_json_objects", lambda _s: [])
    with pytest.raises(E27ProtocolError):
        linking.perform_api_link(
            sock=sock,
            client_identity=linking.E27Identity(mn="m", sn="s", fwver="f", hwver="h", osver="o"),
            access_code="a",
            passphrase="b",
            mn_for_hash="m",
            discovery_nonce=b"nonce",
            timeout_s=1.0,
        )


def test_coerce_intish_default_and_invalid() -> None:
    assert linking._coerce_intish(None, default=0) == 0
    assert linking._coerce_intish("12") == 12
    with pytest.raises(ValueError):
        linking._coerce_intish("bad")
