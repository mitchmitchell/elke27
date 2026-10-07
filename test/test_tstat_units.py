from __future__ import annotations

from typing import Any, cast

import pytest

from elke27_lib.client import Elke27Client
from elke27_lib.kernel import E27Kernel
from elke27_lib.states import TstatState
from elke27_lib.tstat_units import decode_value, encode_setpoint, precision_from_prec

# "prec" byte from the E27 Dealer API tstat_get_status example: [9,9,9,0].
# 9 = 0b00001001 -> precision 0 (b5-b7), scale 1 (b3-b4), size 1 (b0-b2).
PREC_WHOLE = 9
# Same scale/size with precision 1 (one decimal place).
PREC_TENTHS = PREC_WHOLE | (1 << 5)


@pytest.mark.parametrize(
    ("value", "expected"),
    [(68, 68), (68.0, 68), (70.4, 70), (70.5, 71), (-40, -40), (150, 150)],
)
def test_encode_setpoint_whole_degrees(value: float, expected: int) -> None:
    assert encode_setpoint(value) == expected


@pytest.mark.parametrize("value", [680, 151, -41, True, "68", None])
def test_encode_setpoint_rejects_out_of_range_or_non_numeric(value: Any) -> None:
    with pytest.raises(ValueError):
        encode_setpoint(value)


def test_precision_from_prec() -> None:
    assert precision_from_prec(PREC_WHOLE) == 0
    assert precision_from_prec(PREC_TENTHS) == 1


def test_decode_value() -> None:
    assert decode_value(None, [PREC_TENTHS], 0) is None
    assert decode_value(67, None, 0) == 67
    assert decode_value(67, [], 0) == 67
    assert decode_value(67, [PREC_WHOLE], 1) == 67
    assert decode_value(67, [PREC_WHOLE, PREC_WHOLE, PREC_WHOLE, 0], 0) == 67
    assert decode_value(715, [PREC_TENTHS], 0) == 71.5


def test_snapshot_thermostat_values_follow_prec() -> None:
    kernel = E27Kernel()
    kernel.state.tstats = cast(
        Any,
        {
            1: TstatState(
                tstat_id=1,
                temperature=67,
                cool_setpoint=75,
                heat_setpoint=60,
                humidity=0,
                prec=[PREC_WHOLE, PREC_WHOLE, PREC_WHOLE, 0],
            ),
            2: TstatState(
                tstat_id=2,
                temperature=715,
                cool_setpoint=760,
                heat_setpoint=680,
                humidity=40,
                prec=[PREC_TENTHS, PREC_TENTHS, PREC_TENTHS, 0],
            ),
        },
    )
    client = Elke27Client(kernel=kernel)
    tstats = client._build_thermostat_map()
    assert (tstats[1].temperature, tstats[1].cool_setpoint, tstats[1].heat_setpoint) == (
        67,
        75,
        60,
    )
    assert (tstats[2].temperature, tstats[2].cool_setpoint, tstats[2].heat_setpoint) == (
        71.5,
        76.0,
        68.0,
    )
    assert tstats[2].humidity == 40
