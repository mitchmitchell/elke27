"""Thermostat value conversions for the E27 tstat API.

Per the E27 Dealer API (``tstat_set_status`` / ``tstat_get_status`` examples),
setpoints are sent as plain whole degrees, e.g. ``"cool_setpoint": 75``.
Status values carry a ``prec`` array for ``[temp, cool, heat, humidity]`` where
each byte packs precision (b5-b7, number of decimal places), scale (b3-b4) and
size (b0-b2). A precision of 0 means the value is already whole degrees.
"""

from __future__ import annotations

import math

Setpoint = int | float

# Generous bounds for a whole-degree setpoint (F or C). Anything outside this is
# almost certainly a caller passing protocol tenths (e.g. 680 for 68 F).
MIN_SETPOINT = -40
MAX_SETPOINT = 150

_PRECISION_SHIFT = 5
_PRECISION_MASK = 0b111


def encode_setpoint(value: Setpoint) -> int:
    """Return a setpoint as whole degrees for ``tstat_set_status``.

    Fractional values are rounded half up. Values outside a plausible
    whole-degree range raise ``ValueError`` so pre-scaled (tenths) input is
    rejected instead of being written to the panel.
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"setpoint must be a number (got {value!r})")
    degrees = math.floor(value + 0.5)
    if not MIN_SETPOINT <= degrees <= MAX_SETPOINT:
        raise ValueError(
            f"setpoint must be whole degrees between {MIN_SETPOINT} and "
            f"{MAX_SETPOINT} (got {value!r}); do not pre-scale to tenths"
        )
    return degrees


def precision_from_prec(prec: int) -> int:
    """Return the number of decimal places encoded in a ``prec`` byte."""
    return (prec >> _PRECISION_SHIFT) & _PRECISION_MASK


def decode_value(raw: int | None, prec: list[int] | None, index: int) -> int | float | None:
    """Scale a raw ``tstat_get_status`` value using its ``prec`` entry.

    ``index`` is 0 for temperature, 1 for cool setpoint, 2 for heat setpoint,
    3 for humidity. Values are returned unchanged when no precision applies.
    """
    if raw is None or not prec or index >= len(prec):
        return raw
    precision = precision_from_prec(prec[index])
    if precision == 0:
        return raw
    return raw / (10**precision)
