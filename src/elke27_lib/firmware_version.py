"""Numeric application firmware comparison for capability gating."""

from __future__ import annotations

NIGHT_ARM_MIN_FIRMWARE: tuple[int, ...] = (0, 0, 5, 37)


def application_firmware_tuple_from_app_field(app: int | None) -> tuple[int, ...] | None:
    if app is None or type(app) is not int or app < 0:
        return None
    return (
        (app >> 24) & 0xFF,
        (app >> 16) & 0xFF,
        (app >> 8) & 0xFF,
        app & 0xFF,
    )


def format_application_firmware(app: int) -> str | None:
    parts = application_firmware_tuple_from_app_field(app)
    if parts is None:
        return None
    return ".".join(str(p) for p in parts)


def version_tuple_at_least(current: tuple[int, ...] | None, minimum: tuple[int, ...]) -> bool:
    if current is None:
        return False
    width = max(len(current), len(minimum))
    left = current + (0,) * (width - len(current))
    right = minimum + (0,) * (width - len(minimum))
    return left >= right


def night_arm_supported_from_app_field(app: int | None) -> bool:
    return version_tuple_at_least(
        application_firmware_tuple_from_app_field(app), NIGHT_ARM_MIN_FIRMWARE
    )
