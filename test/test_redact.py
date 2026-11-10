from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pytest

from elke27_lib import redact


class _Color(Enum):
    RED = "red"


@dataclass
class _Inner:
    token: str
    value: int


def test_should_redact() -> None:
    assert redact.should_redact("passphrase") is True
    assert redact.should_redact("apiToken") is True
    assert redact.should_redact("secret_key") is True
    assert redact.should_redact("monkey") is False
    assert redact.should_redact("cloud_pw") is True
    assert redact.should_redact("CLOUD_URL") is True
    assert redact.should_redact("pw") is True
    assert redact.should_redact("pwd") is True
    assert redact.should_redact("relay_pw") is True
    assert redact.should_redact("access") is True
    assert redact.should_redact("lat") is True
    assert redact.should_redact("long") is True
    assert redact.should_redact("long_name") is False
    assert redact.should_redact("paperwork") is False
    assert redact.should_redact("password_required") is True


SYSTEM_GET_ATTRIBS_DUMMY: dict[str, object] = {
    "name": "Demo Panel Alpha",
    "lat": 40.123456,
    "long": -105.654321,
    "cloud_pw": "dummy-cloud-pw-value",
    "cloud_url": "https://example.invalid/cloud",
    "access": "dummy-access-token",
    "pw": "dummy-pw",
    "pwd": "dummy-pwd",
    "relay_pw": "dummy-relay-pw",
    "tz_offset": -7,
    "flags": 0,
    "error_code": 0,
    "long_name": "Lobby entry",
    "password_required": False,
}


def test_redact_system_get_attribs_reply_shape() -> None:
    out = redact.redact_for_diagnostics(SYSTEM_GET_ATTRIBS_DUMMY)
    for sensitive in (
        "cloud_pw",
        "cloud_url",
        "access",
        "pw",
        "pwd",
        "relay_pw",
        "lat",
        "long",
    ):
        assert out[sensitive] == "***"
    assert out["name"] == "Demo Panel Alpha"
    assert out["long_name"] == "Lobby entry"
    assert out["password_required"] == "***"


def test_normalize_for_diagnostics() -> None:
    obj = _Inner(token="abc", value=3)
    out = redact._normalize_for_diagnostics(obj)
    assert out["token"] == "abc"
    assert out["value"] == 3
    assert redact._normalize_for_diagnostics(None) is None
    assert redact._normalize_for_diagnostics({"a": 1}) == {"a": 1}
    assert redact._normalize_for_diagnostics([b"\x00", _Color.RED]) == ["<bytes:1>", "red"]
    assert "object at" in redact._normalize_for_diagnostics(object())


def test_redact_for_diagnostics(monkeypatch: pytest.MonkeyPatch) -> None:
    data = {"passphrase": "secret", "safe": 1}
    out = redact.redact_for_diagnostics(data)
    assert out["passphrase"] == "***"
    assert out["safe"] == 1
    out_dc = redact.redact_for_diagnostics(_Inner(token="secret", value=2))
    assert out_dc["token"] == "***"
    assert out_dc["value"] == 2
    assert redact.redact_for_diagnostics(_Color.RED) == "red"
    assert redact.redact_for_diagnostics(b"\x00") == "<bytes:1>"

    monkeypatch.setattr(redact, "REDACT_DIAGNOSTICS", False)
    out2 = redact.redact_for_diagnostics(data)
    assert out2["passphrase"] == "secret"
