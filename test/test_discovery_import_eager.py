from __future__ import annotations

import importlib
import subprocess
import sys
from typing import Any

import pytest

from elke27_lib.discovery import AIOELKDiscovery, async_discover_host


def test_discovery_socket_thread_loaded_at_import() -> None:
    script = """
import sys
import elke27_lib.discovery  # noqa: F401
assert "elke27_lib.discovery_socket_thread" in sys.modules
"""
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout


@pytest.mark.asyncio
async def test_async_discover_host_never_import_module(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    real_import_module = importlib.import_module

    def tracking_import_module(name: str, package: str | None = None) -> Any:
        calls.append(name)
        return real_import_module(name, package)

    async def fake_scan(
        self: AIOELKDiscovery,
        timeout: float = 10,
        address: str | None = None,
        **kw: Any,
    ) -> list[Any]:
        return []

    monkeypatch.setattr(importlib, "import_module", tracking_import_module)
    monkeypatch.setattr(AIOELKDiscovery, "async_scan", fake_scan)

    await async_discover_host("127.0.0.1", timeout=0.1)
    assert calls == []
