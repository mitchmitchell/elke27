"""Canonical panel ``arm_state`` / ``arm_cmd_state`` string to :class:`ArmMode` mapping."""

from __future__ import annotations

from collections.abc import Mapping

from elke27_lib.types import ArmMode

_ARM_STATE_TO_MODE: Mapping[str, ArmMode] = {
    "DISARMED": ArmMode.DISARMED,
    "ARMED_STAY": ArmMode.ARMED_STAY,
    "ARMED_STAY_INST": ArmMode.ARMED_STAY,
    "ARMED_AWAY": ArmMode.ARMED_AWAY,
    "ARMED_VACATION": ArmMode.ARMED_VACATION,
    "ARMED_NIGHT": ArmMode.ARMED_NIGHT,
}


def arm_mode_from_panel_string(value: str | None) -> ArmMode | None:
    """Map a panel arm string to an :class:`ArmMode`; unknown strings return ``None``."""
    if not isinstance(value, str):
        return None
    return _ARM_STATE_TO_MODE.get(value.strip().upper())
