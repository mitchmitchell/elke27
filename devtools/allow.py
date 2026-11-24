"""Line exceptions for the devtools review checks (ELK2xx).

A finding is skipped only when its line carries a marker in this form::

    # noqa: ELK2nn -- <reason of three or more words> (expires YYYY-MM-DD, approved by <Name>)

The reason needs at least three words, the expiry date must not have passed and may
be at most ``MAX_DAYS`` (90) days out, and the approver must be a person listed in
``APPROVERS``. A marker that names the code but
breaks one of those rules is itself reported, so a stale or unapproved exception
fails the check instead of hiding the finding.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterable
from dataclasses import dataclass

APPROVERS = frozenset({"Mitch Mitchell"})
MAX_DAYS = 90

_MARKER = re.compile(
    r"#\s*noqa:\s*(?P<codes>ELK2\d\d(?:\s*,\s*ELK2\d\d)*)\s*(?P<rest>.*)$", re.IGNORECASE
)
_FORM = re.compile(
    r"^--\s+(?P<reason>.+?)\s+\(expires\s+(?P<date>\d{4}-\d{2}-\d{2}),\s+approved by\s+"
    r"(?P<who>[^)]+?)\)\s*$"
)


@dataclass(frozen=True)
class Marker:
    """One parsed exception marker."""

    codes: frozenset[str]
    problem: str | None


def parse(comment: str, today: dt.date) -> Marker | None:
    """Parse one comment; ``None`` when it names no ELK2xx code."""
    match = _MARKER.search(comment)
    if match is None:
        return None
    codes = frozenset(c.strip().upper() for c in match.group("codes").split(","))
    form = _FORM.match(match.group("rest").strip())
    if form is None:
        return Marker(
            codes, "exception needs '-- <reason> (expires YYYY-MM-DD, approved by <Name>)'"
        )
    if len(form.group("reason").split()) < 3:
        return Marker(codes, "exception reason needs three or more words")
    try:
        expires = dt.date.fromisoformat(form.group("date"))
    except ValueError:
        return Marker(codes, f"exception expiry {form.group('date')!r} is not a date")
    if expires < today:
        return Marker(codes, f"exception expired on {expires.isoformat()}")
    if expires > today + dt.timedelta(days=MAX_DAYS):
        return Marker(
            codes, f"exception expiry {expires.isoformat()} is more than {MAX_DAYS} days out"
        )
    if form.group("who").strip() not in APPROVERS:
        return Marker(codes, f"exception approver must be one of {sorted(APPROVERS)}")
    return Marker(codes, None)


def line_markers(lines: Iterable[str], today: dt.date) -> dict[int, Marker]:
    """Markers by 1-based line number, from raw source lines (any file type)."""
    found: dict[int, Marker] = {}
    for number, line in enumerate(lines, start=1):
        if "#" in line and (marker := parse(line, today)) is not None:
            found[number] = marker
    return found


def verdict(markers: dict[int, Marker], line: int, code: str) -> tuple[bool, str | None]:
    """``(skip, problem)`` for a finding with ``code`` on ``line``."""
    marker = markers.get(line)
    if marker is None or code not in marker.codes:
        return False, None
    if marker.problem is not None:
        return False, marker.problem
    return True, None
