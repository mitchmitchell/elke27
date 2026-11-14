"""Packed ``control.get_version_info`` ``app`` values for tests."""

from __future__ import annotations

NIGHT_ARM_MIN_FIRMWARE_TUPLE = (0, 0, 5, 37)


def pack_application_firmware(a: int, b: int, c: int, d: int) -> int:
    return ((a & 0xFF) << 24) | ((b & 0xFF) << 16) | ((c & 0xFF) << 8) | (d & 0xFF)


NIGHT_ARM_MIN_APP_FIELD: int = pack_application_firmware(*NIGHT_ARM_MIN_FIRMWARE_TUPLE)