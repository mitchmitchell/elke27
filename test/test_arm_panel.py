"""Shared panel arm string mapping (``arm_panel``)."""

from elke27_lib.arm_panel import arm_mode_from_panel_string
from elke27_lib.types import ArmMode


def test_armed_stay_inst_maps_to_armed_night() -> None:
    assert arm_mode_from_panel_string("ARMED_STAY_INST") is ArmMode.ARMED_NIGHT


def test_armed_stay_inst_distinct_from_stay_and_disarmed() -> None:
    night = arm_mode_from_panel_string("ARMED_STAY_INST")
    assert night is ArmMode.ARMED_NIGHT
    assert night is not arm_mode_from_panel_string("ARMED_STAY")
    assert night is not arm_mode_from_panel_string("DISARMED")
