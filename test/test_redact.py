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
    assert redact._should_redact("passphrase") is True
    assert redact._should_redact("apiToken") is True
    assert redact._should_redact("secret_key") is True
    assert redact._should_redact("monkey") is False


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
