"""Application firmware encoding from control.get_version_info ``app``."""

from __future__ import annotations

from elke27_lib.firmware_version import (
    NIGHT_ARM_MIN_APP_FIELD,
    NIGHT_ARM_MIN_FIRMWARE,
    application_firmware_tuple_from_app_field,
    format_application_firmware,
    night_arm_supported_from_app_field,
    pack_application_firmware,
    version_tuple_at_least,
)


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
