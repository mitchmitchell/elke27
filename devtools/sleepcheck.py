"""Freeze sleep- and wall-clock-synchronised tests and ban yield seams (ELK204).

Tests wait on a gate (``test/helpers/gates.py``: an ``asyncio.Event`` or ``Future``
the fake sets when the step happens) or drive an injected clock, never on time.
Counted in ``test`` (helpers included, fixtures excluded):

- ``asyncio.sleep(0)`` (a bare yield that hopes the other task ran), including
  ``sleep(delay=0)``, ``sleep(0, result)`` and a local alias such as
  ``s = asyncio.sleep``;
- a ``for ... in range(...)`` loop or a ``while`` loop that awaits ``asyncio.sleep``
  (a yield or poll loop);
- ``time.sleep(...)``;
- every wall-clock read: ``time.monotonic()``, ``time.time()``,
  ``time.perf_counter()`` and their ``_ns`` forms, and ``loop.time()`` (including
  ``asyncio.get_running_loop().time()``), wherever it appears. A read stored first
  (``t0 = time.monotonic()``, then ``assert elapsed < 0.5``) times the test just like
  one inside the assert.

In ``src`` an ``asyncio.sleep(0)`` yield seam is always a finding: production code
does not add a sleep so that a test can interleave.

The count per file must equal ``SLEEP_CEILING``: above the entry (or unlisted)
fails, and below it fails until the entry is lowered. A site that must stay needs
``# noqa: ELK204 -- <reason> (expires YYYY-MM-DD, approved by <Name>)`` on its line
(see ``devtools/allow.py``); it is then not counted.

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
CLOCKS = {
    "time.monotonic",
    "time.monotonic_ns",
    "time.time",
    "time.time_ns",
    "time.perf_counter",
    "time.perf_counter_ns",
}
_LOOP_FACTORIES = ("get_running_loop", "get_event_loop")

SLEEP_CEILING: dict[str, int] = {
    "test/helpers/fake_session.py": 1,
    "test/helpers/keepalive_seam.py": 6,
    "test/helpers/panel_command_driver.py": 2,
    "test/helpers/panel_simulator.py": 3,
    "test/helpers/reporter.py": 1,
    "test/test_abandoned_future_outcomes.py": 4,
    "test/test_all_areas_disarmed_execute.py": 2,
    "test/test_area_arm_pin_regression.py": 4,
    "test/test_async_execute_panel_errors_and_pins.py": 2,
    "test/test_barrier_commands.py": 4,
    "test/test_client_close_resubscribe.py": 7,
    "test/test_client_execute_coverage.py": 3,
    "test/test_client_extra.py": 1,
    "test/test_command_outcome_unknown.py": 4,
    "test/test_dead_link_detection.py": 1,
    "test/test_disconnected_event_err_msg.py": 1,
    "test/test_e27_area_set_arm_state_async_execute.py": 8,
    "test/test_e27_area_set_status_async_execute.py": 4,
    "test/test_e27_async_execute_paged.py": 6,
    "test/test_e27_async_execute_permissions.py": 1,
    "test/test_e27_async_execute_seq.py": 3,
    "test/test_e27_configured_names_live.py": 7,
    "test/test_e27_link_raw_buffers.py": 3,
    "test/test_keepalive_probe_deadline.py": 11,
    "test/test_keepalive_stats.py": 2,
    "test/test_keepalive_two_miss.py": 10,
    "test/test_kernel_extra.py": 5,
    "test/test_kernel_request_state.py": 6,
    "test/test_light_status_derivation.py": 4,
    "test/test_live_e27_bypass_events.py": 2,
    "test/test_live_e27_chime.py": 3,
    "test/test_live_e27_closet_door_lock.py": 3,
    "test/test_live_e27_log.py": 3,
    "test/test_outbound_queue.py": 12,
    "test/test_panel_errors_ready_night.py": 2,
    "test/test_pr_c_loop_fixes.py": 18,
    "test/test_publication_timeout.py": 9,
    "test/test_raw_passthrough.py": 4,
    "test/test_rule_get_rules_paging.py": 5,
    "test/test_security_round1.py": 7,
    "test/test_session_io_tstat_regression.py": 15,
    "test/test_set_status_ack_no_stale_event.py": 1,
    "test/test_snapshot_after_arm_bypass.py": 27,
    "test/test_timeout_start_on_send.py": 1,
    "test/test_transport_command_retry.py": 55,
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
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], _dotted(node.value)
            if isinstance(target, ast.Name) and value is not None:
                head, _, rest = value.partition(".")
                resolved = names.get(head, head) + (f".{rest}" if rest else "")
                if resolved in {"asyncio.sleep", "time.sleep"} | CLOCKS:
                    names[target.id] = resolved
    return names


def _loop_time(func: ast.expr) -> bool:
    """``loop.time`` on a name or attribute holding a loop, or on ``get_running_loop()``."""
    if not (isinstance(func, ast.Attribute) and func.attr == "time"):
        return False
    owner = func.value
    if isinstance(owner, ast.Call):
        return (_dotted(owner.func) or "").endswith(_LOOP_FACTORIES)
    name = _dotted(owner)
    return name is not None and "loop" in name.rsplit(".", 1)[-1].lower()


def _call(node: ast.AST, aliases: dict[str, str]) -> str | None:
    if not isinstance(node, ast.Call):
        return None
    if _loop_time(node.func):
        return "loop.time"
    name = _dotted(node.func)
    if name is None:
        return None
    head, _, rest = name.partition(".")
    if head in aliases:
        return aliases[head] + (f".{rest}" if rest else "")
    return name


def _is_zero(call: ast.Call) -> bool:
    delay = call.args[0] if call.args else None
    for keyword in call.keywords:
        if keyword.arg == "delay":
            delay = keyword.value
    return (
        isinstance(delay, ast.Constant)
        and delay.value in (0, 0.0)
        and not isinstance(delay.value, bool)
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
            isinstance(node, ast.For | ast.AsyncFor | ast.While)
            and (isinstance(node, ast.While) or _is_range_loop(node))
            and any(
                isinstance(inner, ast.Await) and _call(inner.value, aliases) == "asyncio.sleep"
                for inner in ast.walk(node)
            )
        ):
            kind = "while" if isinstance(node, ast.While) else "range()"
            found.append((node.lineno, f"{kind} loop awaiting asyncio.sleep; wait on a gate"))
        elif isinstance(node, ast.Call) and (name in CLOCKS or name == "loop.time"):
            found.append((node.lineno, f"{name}() reads the wall clock; use a fake clock"))
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
