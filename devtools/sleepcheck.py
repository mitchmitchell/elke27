"""Freeze sleep- and wall-clock-synchronised tests and ban yield seams (ELK204).

Tests wait on a gate (``test/helpers/gates.py``: an ``asyncio.Event`` or ``Future``
the fake sets when the step happens) or drive an injected clock, never on time.
Counted in ``test`` (helpers included, fixtures excluded):

- ``asyncio.sleep(0)`` (a bare yield that hopes the other task ran);
- a ``for ... in range(...)`` loop that awaits ``asyncio.sleep`` (a yield or poll loop);
- ``time.sleep(...)``;
- ``time.monotonic()``, ``time.time()``, ``time.perf_counter()`` or ``loop.time()``
  inside an ``assert`` (a wall-clock assertion).

In ``src`` an ``asyncio.sleep(0)`` yield seam is always a finding: production code
does not add a sleep so that a test can interleave.

The count per file must equal ``SLEEP_CEILING``: above the entry (or unlisted)
fails, below it fails until the entry is lowered. Entries only go down
(``devtools/ratchet.py`` enforces that). A site that must stay needs ``# noqa:
ELK204 -- <reason> (expires YYYY-MM-DD, approved by <Name>)`` on its line (see
``devtools/allow.py``); it is then not counted.

Usage: ``python devtools/sleepcheck.py [--root DIR] [--baseline DIR] [--counts]``.
With ``--baseline`` the counts of that tree are the ceiling (to replay the check on a
past change against the tree it branched from). Prints ``path:line ELK204 message``
for each site in a file whose count is off and exits 1 when any is.
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import sys
from collections.abc import Sequence
from pathlib import Path

import allow

CODE = "ELK204"
DESCRIPTION = "Freeze sleep- and wall-clock-synchronised tests and ban yield seams."
ROOT = Path(__file__).resolve().parent.parent
SKIP = ("test/fixtures/",)
CLOCKS = {"time.monotonic", "time.time", "time.perf_counter", "time.monotonic_ns"}

SLEEP_CEILING: dict[str, int] = {
    "test/helpers/fake_session.py": 1,
    "test/helpers/keepalive_seam.py": 6,
    "test/helpers/panel_command_driver.py": 1,
    "test/helpers/panel_simulator.py": 2,
    "test/test_abandoned_future_outcomes.py": 3,
    "test/test_all_areas_disarmed_execute.py": 2,
    "test/test_area_arm_pin_regression.py": 3,
    "test/test_async_execute_panel_errors_and_pins.py": 1,
    "test/test_barrier_commands.py": 4,
    "test/test_client_close_resubscribe.py": 4,
    "test/test_client_execute_coverage.py": 3,
    "test/test_client_extra.py": 1,
    "test/test_command_outcome_unknown.py": 4,
    "test/test_dead_link_detection.py": 1,
    "test/test_disconnected_event_err_msg.py": 1,
    "test/test_e27_area_set_arm_state_async_execute.py": 7,
    "test/test_e27_area_set_status_async_execute.py": 4,
    "test/test_e27_async_execute_paged.py": 3,
    "test/test_e27_async_execute_permissions.py": 1,
    "test/test_e27_async_execute_seq.py": 3,
    "test/test_keepalive_probe_deadline.py": 2,
    "test/test_keepalive_stats.py": 1,
    "test/test_keepalive_two_miss.py": 1,
    "test/test_kernel_extra.py": 4,
    "test/test_kernel_request_state.py": 6,
    "test/test_light_status_derivation.py": 4,
    "test/test_outbound_queue.py": 3,
    "test/test_panel_errors_ready_night.py": 1,
    "test/test_pr_c_loop_fixes.py": 5,
    "test/test_publication_timeout.py": 4,
    "test/test_raw_passthrough.py": 4,
    "test/test_rule_get_rules_paging.py": 2,
    "test/test_security_round1.py": 1,
    "test/test_session_io_tstat_regression.py": 5,
    "test/test_set_status_ack_no_stale_event.py": 1,
    "test/test_snapshot_after_arm_bypass.py": 10,
    "test/test_transport_command_retry.py": 49,
    "test/test_v2_wait_ready.py": 1,
}


def _dotted(node: ast.expr) -> str | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _aliases(tree: ast.Module) -> dict[str, str]:
    names: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in {"asyncio", "time"}:
            for alias in node.names:
                names[alias.asname or alias.name] = f"{node.module}.{alias.name}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in {"asyncio", "time"} and alias.asname:
                    names[alias.asname] = alias.name
    return names


def _call(node: ast.AST, aliases: dict[str, str]) -> str | None:
    if not isinstance(node, ast.Call):
        return None
    name = _dotted(node.func)
    if name is None:
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "time"
            and isinstance(func.value, ast.Call)
            and (_dotted(func.value.func) or "").endswith(("get_running_loop", "get_event_loop"))
        ):
            return "loop.time"
        return None
    head, _, rest = name.partition(".")
    if head in aliases:
        return aliases[head] + (f".{rest}" if rest else "")
    return name


def _is_zero(call: ast.Call) -> bool:
    return (
        len(call.args) == 1
        and isinstance(call.args[0], ast.Constant)
        and call.args[0].value in (0, 0.0)
        and not isinstance(call.args[0].value, bool)
    )


def _is_range_loop(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.For | ast.AsyncFor)
        and isinstance(node.iter, ast.Call)
        and isinstance(node.iter.func, ast.Name)
        and node.iter.func.id == "range"
    )


def sites(source: str, in_src: bool, today: dt.date) -> list[tuple[int, str]]:
    """``(line, description)`` for each counted site in one file."""
    tree = ast.parse(source)
    aliases = _aliases(tree)
    markers = allow.line_markers(source.splitlines(), today)
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        name = _call(node, aliases)
        if isinstance(node, ast.Call) and name == "asyncio.sleep" and _is_zero(node):
            found.append((node.lineno, "asyncio.sleep(0) yield; wait on a gate instead"))
        if in_src:
            continue
        if isinstance(node, ast.Call) and name == "time.sleep":
            found.append((node.lineno, "time.sleep(); wait on a gate or drive the clock"))
        elif (
            isinstance(node, ast.For | ast.AsyncFor)
            and _is_range_loop(node)
            and any(
                isinstance(inner, ast.Await) and _call(inner.value, aliases) == "asyncio.sleep"
                for inner in ast.walk(node)
            )
        ):
            found.append((node.lineno, "range() loop awaiting asyncio.sleep; wait on a gate"))
        elif isinstance(node, ast.Assert):
            for inner in ast.walk(node.test):
                inner_name = _call(inner, aliases)
                if inner_name in CLOCKS or (inner_name or "").endswith("loop.time"):
                    found.append((node.lineno, f"{inner_name}() in an assert; use a fake clock"))
                    break
    kept: list[tuple[int, str]] = []
    for line, text in sorted(found):
        skip, problem = allow.verdict(markers, line, CODE)
        if not skip:
            kept.append((line, f"{text} ({problem})" if problem else text))
    return kept


def scan(root: Path, today: dt.date) -> dict[str, list[tuple[int, str]]]:
    """Counted sites by repo-relative path."""
    found: dict[str, list[tuple[int, str]]] = {}
    for base in ("src", "test"):
        for path in sorted((root / base).rglob("*.py")):
            rel = path.relative_to(root).as_posix()
            if rel.startswith(SKIP):
                continue
            hits = sites(path.read_text(encoding="utf-8"), base == "src", today)
            if hits:
                found[rel] = hits
    return found


def findings(found: dict[str, list[tuple[int, str]]], ceiling: dict[str, int]) -> list[str]:
    """Rendered findings for every file whose count differs from its ceiling."""
    out: list[str] = []
    for rel in sorted(found.keys() | ceiling.keys()):
        hits = found.get(rel, [])
        limit = 0 if rel.startswith("src/") else ceiling.get(rel, 0)
        if len(hits) > limit:
            out += [
                f"{rel}:{line} {CODE} {text} ({len(hits)} sites, ceiling {limit})"
                for line, text in hits
            ]
        elif len(hits) < limit:
            out.append(
                f"{rel}:1 {CODE} count fell to {len(hits)}; lower SLEEP_CEILING from {limit}"
            )
    return out


def main(argv: Sequence[str] | None = None) -> int:
    """Run the check; see the module docstring."""
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--counts", action="store_true", help="print current counts and exit")
    parser.add_argument(
        "--baseline", type=Path, help="use the counts of this tree as the ceiling instead"
    )
    args = parser.parse_args(argv)
    today = dt.date.today()
    found = scan(args.root.resolve(), today)
    if args.counts:
        for rel, hits in sorted(found.items()):
            print(f'    "{rel}": {len(hits)},')
        return 0
    ceiling = SLEEP_CEILING
    if args.baseline is not None:
        ceiling = {rel: len(hits) for rel, hits in scan(args.baseline.resolve(), today).items()}
    out = findings(found, ceiling)
    for line in out:
        print(line)
    print(f"sleepcheck: {len(out)} finding(s)")
    return 1 if out else 0


if __name__ == "__main__":
    sys.exit(main())
