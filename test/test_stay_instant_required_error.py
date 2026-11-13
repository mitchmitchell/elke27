"""Public shape of Elke27StayInstantRequiredError."""

from __future__ import annotations

import elke27_lib
from elke27_lib import Elke27StayInstantRequiredError


def test_stay_instant_required_error_is_public() -> None:
    assert elke27_lib.Elke27StayInstantRequiredError is Elke27StayInstantRequiredError
    assert "Elke27StayInstantRequiredError" in elke27_lib.__all__


def test_stay_instant_required_error_fields() -> None:
    err = Elke27StayInstantRequiredError()
    assert err.code == "stay_instant_required"
    assert err.is_transient is False
