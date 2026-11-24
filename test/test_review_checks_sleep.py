"""Tests for devtools/sleepcheck.py and the gated helpers in test/helpers/gates.py."""

from __future__ import annotations

import asyncio
import datetime as dt
import importlib.util
import subprocess
import sys
import threading
from pathlib import Path
from types import ModuleType

import pytest

from test.helpers.gates import Checkpoint, wait_event, wait_future, wait_thread_event

ROOT = Path(__file__).resolve().parent.parent
DEVTOOLS = ROOT / "devtools"
TODAY = dt.date(2026, 11, 24)


def _load(name: str) -> ModuleType:
    """Load a devtools script by path; sys.path is restored and only devtools modules are dropped."""
    saved_path = list(sys.path)
    saved_modules = set(sys.modules)
    sys.path.insert(0, str(DEVTOOLS))
    try:
        spec = importlib.util.spec_from_file_location(f"devtools_{name}", DEVTOOLS / f"{name}.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path[:] = saved_path
        for added in set(sys.modules) - saved_modules:
            origin = getattr(sys.modules[added], "__file__", None)
            if added == f"devtools_{name}" or (origin and Path(origin).parent == DEVTOOLS):
                del sys.modules[added]


sleepcheck = _load("sleepcheck")

TEST_SOURCE = """
import asyncio
import time
from asyncio import sleep as nap
from time import monotonic

async def test_x(loop):
    await asyncio.sleep(0)
    await nap(0.0)
    await asyncio.sleep(0.5)
    for _ in range(20):
        await asyncio.sleep(0.01)
    time.sleep(0.1)
    start = monotonic()
    assert monotonic() - start < 1.0
    assert loop.time() > 0
    assert time.time()
    assert True

async def test_y():
    import asyncio as aio
    await aio.sleep(0)
    assert asyncio.get_running_loop().time() > 0
"""


def test_counts_yields_loops_sleeps_and_clock_asserts_in_tests() -> None:
    lines = [line for line, _ in sleepcheck.sites(TEST_SOURCE, False, TODAY)]
    assert lines == [8, 9, 11, 13, 15, 16, 17, 22, 23]


def test_src_counts_only_the_yield_seam() -> None:
    assert [line for line, _ in sleepcheck.sites(TEST_SOURCE, True, TODAY)] == [8, 9, 22]


def test_src_yield_has_no_ceiling() -> None:
    found = {"src/elke27_lib/client.py": [(9, "asyncio.sleep(0) yield; wait on a gate instead")]}
    assert sleepcheck.findings(found, {"src/elke27_lib/client.py": 1}) == [
        "src/elke27_lib/client.py:9 ELK204 asyncio.sleep(0) yield; wait on a gate instead"
        " (1 sites, ceiling 0)"
    ]


def test_findings_fail_above_and_below_the_ceiling() -> None:
    found = {"test/a.py": [(3, "time.sleep(); wait on a gate or drive the clock")]}
    assert sleepcheck.findings(found, {"test/a.py": 1}) == []
    assert sleepcheck.findings(found, {"test/a.py": 2}) == [
        "test/a.py:1 ELK204 count fell to 1; lower SLEEP_CEILING from 2"
    ]


def test_exception_marker_drops_the_site() -> None:
    marker = "# noqa: ELK204 -- live panel needs settle time (expires 2026-12-01, approved by Mitch Mitchell)"
    source = f"import time\ntime.sleep(1)  {marker}\n"
    assert sleepcheck.sites(source, False, TODAY) == []


def test_repository_matches_sleep_ceiling() -> None:
    """The same command CI runs through devtools/lint.py."""
    result = subprocess.run(
        [sys.executable, "devtools/sleepcheck.py"], cwd=ROOT, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr


async def test_checkpoint_orders_fake_and_test_without_yields() -> None:
    checkpoint = Checkpoint("send")
    done = asyncio.Event()

    async def fake() -> None:
        await checkpoint.arrive()
        done.set()

    task = asyncio.create_task(fake())
    await checkpoint.wait_reached()
    assert checkpoint.reached and not done.is_set()
    checkpoint.release()
    await wait_event(done, "fake finished")
    await task
    assert checkpoint.arrivals == 1


async def test_gates_fail_fast_with_the_step_name() -> None:
    with pytest.raises(AssertionError, match="reply did not happen within 0.01s"):
        await wait_event(asyncio.Event(), "reply", timeout_s=0.01)
    future: asyncio.Future[int] = asyncio.get_running_loop().create_future()
    with pytest.raises(AssertionError, match="ack did not resolve"):
        await wait_future(future, "ack", timeout_s=0.01)
    assert not future.cancelled()
    future.set_result(7)
    assert await wait_future(future, "ack") == 7


def test_thread_gate() -> None:
    event = threading.Event()
    with pytest.raises(AssertionError, match="worker did not happen"):
        wait_thread_event(event, "worker", timeout_s=0.01)
    event.set()
    wait_thread_event(event, "worker")
