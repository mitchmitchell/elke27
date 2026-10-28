"""Public Elke27CodeRejectedError for panel user-code rejections (#76)."""

from __future__ import annotations

import pytest

import elke27_lib
from elke27_lib import Elke27CodeRejectedError, Elke27PanelError
from elke27_lib.const import E27ErrorCode
from elke27_lib.errors import CODE_REJECTED_PANEL_ERROR_CODES, panel_error_from_code


def test_code_rejected_exported_from_public_package() -> None:
    assert elke27_lib.Elke27CodeRejectedError is Elke27CodeRejectedError
    assert "Elke27CodeRejectedError" in elke27_lib.__all__


def test_code_rejected_panel_error_codes_match_hacs_set() -> None:
    assert CODE_REJECTED_PANEL_ERROR_CODES == frozenset({11004, 11008, 11037})


def test_panel_error_from_code_always_maps_invalid_pin() -> None:
    err = panel_error_from_code(int(E27ErrorCode.ELKERR_INVALID_PIN), "invalid user code")
    assert type(err) is Elke27CodeRejectedError
    assert err.panel_error_code == int(E27ErrorCode.ELKERR_INVALID_PIN)


@pytest.mark.parametrize(
    "code",
    [E27ErrorCode.ELKERR_INVALID_PARAM, E27ErrorCode.ELKERR_NOAUTH],
)
def test_panel_error_from_code_maps_11004_and_11008_only_with_user_code(code: int) -> None:
    with_code = panel_error_from_code(int(code), "reason", user_code_sent=True)
    assert type(with_code) is Elke27CodeRejectedError
    without_code = panel_error_from_code(int(code), "reason", user_code_sent=False)
    assert type(without_code) is Elke27PanelError
    assert not isinstance(without_code, Elke27CodeRejectedError)


def test_panel_error_from_code_leaves_other_codes_as_base_type() -> None:
    err = panel_error_from_code(int(E27ErrorCode.ELKERR_NOT_READY), "area not ready")
    assert type(err) is Elke27PanelError
    assert not isinstance(err, Elke27CodeRejectedError)
