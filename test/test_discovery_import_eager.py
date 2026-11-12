from __future__ import annotations

import asyncio
import importlib
import socket
import subprocess
import sys
from typing import Any

import pytest

from elke27_lib import discovery_socket_thread
from elke27_lib.discovery import async_discover_host


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

    def fake_create_udp_socket() -> socket.socket:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.1", 0))
        sock.setblocking(False)
        return sock

    def fake_destinations_from_broadcasts(
        destination_port: int,
        address: str | None,
    ) -> list[tuple[str, int]]:
        if address is not None:
            return [(address, destination_port)]
        return [("127.0.0.1", destination_port)]

    class _Transport:
        def sendto(self, data: bytes, dest: tuple[str, int]) -> None:
            pass

        def close(self) -> None:
            pass

    loop = asyncio.get_running_loop()

    async def fake_create_datagram_endpoint(
        protocol_factory: Any,
        *_args: Any,
        **_kwargs: Any,
    ) -> tuple[_Transport, Any]:
        return _Transport(), protocol_factory()

    monkeypatch.setattr(importlib, "import_module", tracking_import_module)
    monkeypatch.setattr(discovery_socket_thread, "create_udp_socket", fake_create_udp_socket)
    monkeypatch.setattr(
        discovery_socket_thread,
        "destinations_from_broadcasts",
        fake_destinations_from_broadcasts,
    )
    monkeypatch.setattr(loop, "create_datagram_endpoint", fake_create_datagram_endpoint)

    await async_discover_host("127.0.0.1", timeout=0.05)
    assert calls == []
