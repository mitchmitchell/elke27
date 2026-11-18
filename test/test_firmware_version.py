"""Application firmware encoding from control.get_version_info ``app``."""

from __future__ import annotations

from typing import Any, cast

import pytest

from elke27_lib.firmware_version import (
    NIGHT_ARM_MIN_FIRMWARE,
    application_firmware_tuple_from_app_field,
    format_application_firmware,
    night_arm_supported_from_app_field,
    version_tuple_at_least,
)
from test.helpers.firmware_fixtures import NIGHT_ARM_MIN_APP_FIELD, pack_application_firmware


def test_app_field_decodes_hardware_capture() -> None:
    """Hardware RC report in test_panel_version_info: app 1540 -> 0.0.6.4."""
    assert format_application_firmware(1540) == "0.0.6.4"
    assert application_firmware_tuple_from_app_field(1540) == (0, 0, 6, 4)


def test_night_minimum_app_field() -> None:
    assert pack_application_firmware(0, 0, 5, 37) == NIGHT_ARM_MIN_APP_FIELD == 1317


def test_version_tuple_compare_is_numeric_not_lexical() -> None:
    assert version_tuple_at_least((0, 0, 5, 36), NIGHT_ARM_MIN_FIRMWARE) is False
    assert version_tuple_at_least((0, 0, 5, 37), NIGHT_ARM_MIN_FIRMWARE) is True
    assert version_tuple_at_least((0, 0, 5, 100), NIGHT_ARM_MIN_FIRMWARE) is True


def test_night_supported_from_app_field() -> None:
    assert night_arm_supported_from_app_field(pack_application_firmware(0, 0, 5, 36)) is False
    assert night_arm_supported_from_app_field(NIGHT_ARM_MIN_APP_FIELD) is True
    assert night_arm_supported_from_app_field(pack_application_firmware(0, 0, 5, 100)) is True


@pytest.mark.parametrize(
    ("app", "expected_tuple"),
    [
        (-1, None),
        (True, None),
        (0x01020304, (1, 2, 3, 4)),
    ],
)
def test_application_firmware_tuple_invalid_or_packed(app: object, expected_tuple: object) -> None:
    assert application_firmware_tuple_from_app_field(cast(Any, app)) == expected_tuple


@pytest.mark.parametrize(
    ("app", "night_supported"),
    [
        (None, False),
        (1540, True),
        (0x00010000, True),
        (1316, False),
    ],
)
def test_night_arm_supported_from_app_field_edges(app: int | None, night_supported: bool) -> None:
    assert night_arm_supported_from_app_field(app) is night_supported


@pytest.mark.parametrize(
    ("current", "expected"),
    [
        (None, False),
        ((0, 0, 5), False),
        ((0, 0, 6), True),
        ((0, 0, 5, 37, 0), True),
    ],
)
def test_version_tuple_at_least_padding(current: tuple[int, ...] | None, expected: bool) -> None:
    assert version_tuple_at_least(current, NIGHT_ARM_MIN_FIRMWARE) is expected
