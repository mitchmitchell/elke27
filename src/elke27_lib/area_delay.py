"""Derive entry/exit delay state from documented ``area.get_status`` fields (#92)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from elke27_lib.states import AreaState

_TROUBLE_ONLY_ALARMS = frozenset({"FIRE TROUBLE", "CO TROUBLE"})


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


def _arm_disarmed(arm_state: str | None) -> bool:
    if arm_state is None:
        return True
    return arm_state.strip().upper() == "DISARMED"


def _alarms_populated(
    *,
    alarms: str | list[str] | None,
    alrm_snd: str | bool | None,
    alarm_state: str | None,
) -> bool:
    raw = alarms
    entries = [raw] if isinstance(raw, str) else list(raw or [])
    for entry in entries:
        name = str(entry).strip().upper()
        if name and name not in _TROUBLE_ONLY_ALARMS:
            return True
    sound = alrm_snd
    if sound is True:
        return True
    if isinstance(sound, str):
        name = sound.strip().upper()
        if name and name not in _TROUBLE_ONLY_ALARMS:
            return True
    if alarm_state is not None and str(alarm_state).lower() not in {
        "no_alarm_active",
        "none",
        "",
    }:
        return True
    return False


def _fields_from_snapshot(
    snapshot: Mapping[str, Any] | AreaState,
) -> tuple[
    str | None,
    str | None,
    int | None,
    str | None,
    str | list[str] | None,
    str | bool | None,
    str | None,
]:
    if isinstance(snapshot, Mapping):
        arm_state = snapshot.get("arm_state") or snapshot.get("armed_state")
        arm_cmd = snapshot.get("arm_cmd_state")
        ee_timer = snapshot.get("ee_timer") if isinstance(snapshot.get("ee_timer"), int) else None
        alarm_zone = (
            snapshot.get("alarm_zone") if isinstance(snapshot.get("alarm_zone"), str) else None
        )
        alarms_raw = snapshot.get("alarms")
        if isinstance(alarms_raw, (str, list)) or alarms_raw is None:
            alarms = alarms_raw
        else:
            alarms = None
        alrm_snd_raw = snapshot.get("alrm_snd")
        if isinstance(alrm_snd_raw, (str, bool)) or alrm_snd_raw is None:
            alrm_snd = alrm_snd_raw
        else:
            alrm_snd = None
        alarm_state = (
            snapshot.get("alarm_state") if isinstance(snapshot.get("alarm_state"), str) else None
        )
        arm_state_s = arm_state if isinstance(arm_state, str) else None
        arm_cmd_s = arm_cmd if isinstance(arm_cmd, str) else None
        return arm_state_s, arm_cmd_s, ee_timer, alarm_zone, alarms, alrm_snd, alarm_state
    from elke27_lib.states import AreaState

    if isinstance(snapshot, AreaState):
        return (
            snapshot.arm_state or snapshot.armed_state,
            snapshot.arm_cmd_state,
            snapshot.ee_timer,
            snapshot.alarm_zone,
            snapshot.alarms,
            snapshot.alrm_snd,
            snapshot.alarm_state,
        )
    raise TypeError("expected Mapping or AreaState")


def delay_state_from_area_status(snapshot: Mapping[str, Any] | AreaState) -> DelayState:
    """Map one area status snapshot to a :class:`DelayState` (pure, no I/O)."""
    arm_state, arm_cmd_state, ee_timer, alarm_zone, alarms, alrm_snd, alarm_state = (
        _fields_from_snapshot(snapshot)
    )
    if _alarms_populated(alarms=alarms, alrm_snd=alrm_snd, alarm_state=alarm_state):
        return DELAY_NONE
    if (
        not _arm_disarmed(arm_state)
        and not ee_timer_blank(ee_timer)
        and not alarm_zone_blank(alarm_zone)
    ):
        assert ee_timer is not None
        assert alarm_zone is not None
        return DelayStateEntry(seconds=ee_timer, zone=alarm_zone.strip())
    if ee_timer_blank(ee_timer):
        return DELAY_NONE
    if arm_state is None or arm_cmd_state is None:
        return DELAY_NONE
    if arm_state == arm_cmd_state:
        return DELAY_NONE
    assert ee_timer is not None
    return DelayStateExit(seconds=ee_timer)
