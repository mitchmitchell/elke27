"""Derive entry/exit delay state from documented ``area.get_status`` fields (#92)."""

from __future__ import annotations

from typing import TypeGuard

from elke27_lib.arm_panel import arm_mode_from_panel_string
from elke27_lib.handlers.area import area_alarm_active
from elke27_lib.states import AreaState
from elke27_lib.types import (
    DELAY_NONE,
    ArmMode,
    DelayState,
    DelayStateEntry,
    DelayStateExit,
)


def ee_timer_set(value: int | None) -> TypeGuard[int]:
    """True when ``ee_timer`` is a positive panel countdown integer."""
    if value is None or isinstance(value, bool):
        return False
    return value > 0


def alarm_zone_set(value: str | None) -> TypeGuard[str]:
    """True when ``alarm_zone`` is present and non-empty after trim."""
    if value is None:
        return False
    return bool(str(value).strip())


def delay_state_from_area_status(area: AreaState) -> DelayState:
    """Map one reconciled area state to a :class:`DelayState` (pure, no I/O)."""
    if area_alarm_active(area):
        return DELAY_NONE

    arm_value = area.arm_state or area.armed_state
    arm_mode = arm_mode_from_panel_string(arm_value)
    cmd_mode = arm_mode_from_panel_string(area.arm_cmd_state)

    timer = area.ee_timer
    zone = area.alarm_zone
    if (
        arm_mode is not None
        and arm_mode is not ArmMode.DISARMED
        and ee_timer_set(timer)
        and alarm_zone_set(zone)
    ):
        return DelayStateEntry(seconds=timer, zone=zone.strip())

    if not ee_timer_set(timer):
        return DELAY_NONE
    if cmd_mode is None or cmd_mode is ArmMode.DISARMED:
        return DELAY_NONE
    if arm_mode is None:
        return DELAY_NONE
    if arm_mode == cmd_mode:
        return DELAY_NONE
    return DelayStateExit(seconds=timer)
