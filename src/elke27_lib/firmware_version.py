"""Numeric firmware version comparison for capability gating."""

from __future__ import annotations

NIGHT_ARM_MIN_FIRMWARE: tuple[int, ...] = (0, 5, 37)


def parse_firmware_version(value: str | None) -> tuple[int, ...] | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    parts: list[int] = []
    for segment in text.split("."):
        segment = segment.strip()
        if not segment or not segment.isdigit():
            return None
        parts.append(int(segment))
    return tuple(parts) if parts else None


def firmware_at_least(value: str | None, minimum: tuple[int, ...]) -> bool:
    parsed = parse_firmware_version(value)
    if parsed is None:
        return False
    width = max(len(parsed), len(minimum))
    left = parsed + (0,) * (width - len(parsed))
    right = minimum + (0,) * (width - len(minimum))
    return left >= right
