"""Numeric firmware version comparison."""

from __future__ import annotations

from elke27_lib.firmware_version import firmware_at_least, parse_firmware_version


def test_parse_firmware_version_segments() -> None:
    assert parse_firmware_version("0.5.37") == (0, 5, 37)
    assert parse_firmware_version(" 2.6.1 ") == (2, 6, 1)
    assert parse_firmware_version("") is None
    assert parse_firmware_version("beta") is None


def test_firmware_at_least_numeric_not_lexical() -> None:
    assert firmware_at_least("0.5.36", (0, 5, 37)) is False
    assert firmware_at_least("0.5.37", (0, 5, 37)) is True
    assert firmware_at_least("0.5.100", (0, 5, 37)) is True
    assert firmware_at_least("0.5.9", (0, 5, 37)) is False
