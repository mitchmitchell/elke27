from __future__ import annotations

import asyncio
import json
import socket

import pytest

from elke27_lib import Elke27InvalidArgument, async_discover_host, normalize_panel_mac
from elke27_lib.discovery import AIOELKDiscovery, E27System


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("aa:bb:cc:dd:ee:ff", "AABBCCDDEEFF"),
        ("AA-BB-CC-DD-EE-FF", "AABBCCDDEEFF"),
        ("aabb.ccdd.eeff", "AABBCCDDEEFF"),
        (" 2ccf67ca1ae0 ", "2CCF67CA1AE0"),
        ("000000000000", None),
        ("zzbbccddeeff", None),
        ("aabbcc", None),
        ("", None),
        (None, None),
    ],
)
def test_normalize_panel_mac(raw: object, expected: str | None) -> None:
    assert normalize_panel_mac(raw) == expected


def _system(host: str, mac: str = "aa:bb:cc:dd:ee:ff") -> E27System:
    return E27System(
        panel_mac=mac,
        panel_host=host,
        panel_name="E27 (EEFF)",
        panel_serial=None,
        port=2101,
        tls_port=2601,
    )


@pytest.mark.asyncio
async def test_discover_host_returns_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[object, object]] = []

    async def fake_scan(self, timeout=10, address=None, **kw):  # type: ignore[no-untyped-def]
        calls.append((timeout, address))
        return [_system("192.0.2.9", "11:11:11:11:11:11"), _system("192.0.2.5")]

    monkeypatch.setattr(AIOELKDiscovery, "async_scan", fake_scan)
    panel = await async_discover_host("192.0.2.5", timeout=1.5)
    assert panel is not None
    assert panel.panel_mac == "AABBCCDDEEFF"
    assert panel.host == "192.0.2.5"
    assert panel.port == 2101 and panel.tls_port == 2601
    assert panel.panel_name == "E27 (EEFF)"
    assert calls == [(1.5, "192.0.2.5")]


@pytest.mark.asyncio
async def test_discover_host_no_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_scan(self, timeout=10, address=None, **kw):  # type: ignore[no-untyped-def]
        return []

    monkeypatch.setattr(AIOELKDiscovery, "async_scan", fake_scan)
    assert await async_discover_host("192.0.2.5", timeout=0.1) is None


@pytest.mark.asyncio
async def test_discover_host_oserror(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_scan(self, timeout=10, address=None, **kw):  # type: ignore[no-untyped-def]
        raise OSError("network unreachable")

    monkeypatch.setattr(AIOELKDiscovery, "async_scan", fake_scan)
    assert await async_discover_host("192.0.2.5") is None


@pytest.mark.asyncio
async def test_discover_host_unresolvable() -> None:
    assert await async_discover_host("no-such-host.invalid", timeout=0.1) is None


@pytest.mark.asyncio
async def test_discover_host_invalid_args() -> None:
    with pytest.raises(Elke27InvalidArgument):
        await async_discover_host("  ")
    with pytest.raises(Elke27InvalidArgument):
        await async_discover_host("192.0.2.5", timeout=0)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), "3", None, True])
async def test_discover_host_rejects_non_finite_or_non_numeric_timeout(bad: object) -> None:
    with pytest.raises(Elke27InvalidArgument):
        await async_discover_host("192.0.2.5", timeout=bad)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_discover_host_real_udp_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    """End to end over loopback with a fake panel responder."""
    loop = asyncio.get_running_loop()
    reply = json.dumps(
        {
            "ELKWC2017": "x",
            "MAC_ADDR": "2c:cf:67:ca:1a:e0",
            "IPV4_ADDR": "127.0.0.1",
            "LISTEN_PORT": 2101,
            "ENCRYPTED_LISTEN_PORT": 2601,
            "NAME": "Panel (1AE0)",
        }
    ).encode()

    class Responder(asyncio.DatagramProtocol):
        def connection_made(self, transport):  # type: ignore[no-untyped-def]
            self.transport = transport

        def datagram_received(self, data, addr):  # type: ignore[no-untyped-def]
            self.transport.sendto(reply, addr)

    transport, _ = await loop.create_datagram_endpoint(Responder, local_addr=("127.0.0.1", 0))
    port = transport.get_extra_info("sockname")[1]
    monkeypatch.setattr(AIOELKDiscovery, "DISCOVERY_PORT", port)
    try:

        def factory() -> socket.socket:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.bind(("127.0.0.1", 0))
            s.setblocking(False)
            return s

        panel = await async_discover_host("127.0.0.1", timeout=2, socket_factory=factory)
    finally:
        transport.close()
    assert panel is not None
    assert panel.panel_mac == "2CCF67CA1AE0"
