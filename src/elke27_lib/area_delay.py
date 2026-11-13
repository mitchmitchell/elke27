"""Derive entry/exit delay state from documented ``area.get_status`` fields (#92)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from elke27_lib.states import AreaState
    from elke27_lib.types import ArmMode


@dataclass(frozen=True, slots=True)
class DelayStateNone:
    """No entry or exit delay is active."""


@dataclass(frozen=True, slots=True)
class DelayStateEntry:
    """Entry delay while armed after a zone trip."""

    seconds: int
    zone: str


@dataclass(frozen=True, slots=True)
class DelayStateExit:
    """Exit delay before the commanded arm mode takes effect."""

    seconds: int


DelayState = DelayStateNone | DelayStateEntry | DelayStateExit

DELAY_NONE = DelayStateNone()


def ee_timer_blank(value: int | None) -> bool:
    """``ee_timer`` is blank when missing, zero, or non-positive."""
    if value is None or isinstance(value, bool):
        return True
    return value <= 0


def alarm_zone_blank(value: str | None) -> bool:
    """``alarm_zone`` is blank when missing or empty after trim."""
    if value is None:
        return True
    return not str(value).strip()


def _panel_arm_mode(value: str | None) -> ArmMode | None:
    from elke27_lib.types import ArmMode

    if not isinstance(value, str):
        return None
    return {
        "DISARMED": ArmMode.DISARMED,
        "ARMED_STAY": ArmMode.ARMED_STAY,
        "ARMED_STAY_INST": ArmMode.ARMED_STAY,
        "ARMED_AWAY": ArmMode.ARMED_AWAY,
        "ARMED_VACATION": ArmMode.ARMED_VACATION,
        "ARMED_NIGHT": ArmMode.ARMED_NIGHT,
    }.get(value.strip().upper())


def delay_state_from_area_status(area: AreaState) -> DelayState:
    """Map one reconciled area state to a :class:`DelayState` (pure, no I/O)."""
    from elke27_lib.handlers.area import area_alarm_active
    from elke27_lib.types import ArmMode

    if area_alarm_active(area):
        return DELAY_NONE

    arm_value = area.arm_state or area.armed_state
    arm_mode = _panel_arm_mode(arm_value)
    cmd_mode = _panel_arm_mode(area.arm_cmd_state)

    if (
        arm_mode is not None
        and arm_mode is not ArmMode.DISARMED
        and not ee_timer_blank(area.ee_timer)
        and not alarm_zone_blank(area.alarm_zone)
    ):
        seconds = area.ee_timer
        zone = area.alarm_zone
        if seconds is None or zone is None:
            return DELAY_NONE
        return DelayStateEntry(seconds=seconds, zone=zone.strip())

    if ee_timer_blank(area.ee_timer):
        return DELAY_NONE
    if cmd_mode is None or cmd_mode is ArmMode.DISARMED:
        return DELAY_NONE
    if arm_mode is None:
        return DELAY_NONE
    if arm_mode == cmd_mode:
        return DELAY_NONE
    seconds = area.ee_timer
    if seconds is None:
        return DELAY_NONE
    return DelayStateExit(seconds=seconds)
