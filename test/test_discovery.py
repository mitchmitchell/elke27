from __future__ import annotations

import asyncio
import json
import socket
from typing import cast

import pytest

from elke27_lib import discovery


def test_decode_data_invalid() -> None:
    assert discovery._decode_data(b"nope") is None


def test_decode_data_valid() -> None:
    payload = {
        "MAC_ADDR": "AA:BB:CC:DD:EE:FF",
        "IPV4_ADDR": "192.0.2.1",
        "LISTEN_PORT": 2101,
        "ENCRYPTED_LISTEN_PORT": 2601,
        "NAME": "Panel",
        "SERIAL": "123",
    }
    raw = json.dumps(payload).encode("utf-8")
    system = discovery._decode_data(raw)
    assert system is not None
    assert system.panel_mac == "aa:bb:cc:dd:ee:ff"
    assert system.panel_host == "192.0.2.1"
    assert system.panel_name == "Panel"
    assert system.panel_serial == "123"
    assert system.port == 2101
    assert system.tls_port == 2601


def test_process_response_filters() -> None:
    scanner = discovery.AIOELKDiscovery()
    results: dict[tuple[str, int], discovery.E27System] = {}
    addr = ("192.0.2.5", 1234)

    assert scanner._process_response(None, addr, None, results) is False
    assert scanner._process_response(scanner.DISCOVER_MESSAGE, addr, None, results) is False
    assert scanner._process_response(b"HELLO", addr, None, results) is False

    payload = {
        "MAC_ADDR": "AA",
        "IPV4_ADDR": "192.0.2.5",
        "LISTEN_PORT": 2101,
        "ENCRYPTED_LISTEN_PORT": 2601,
        "NAME": "P",
        "SERIAL": "",
        "MAGIC": "ELKWC2017",
    }
    raw = json.dumps(payload).encode("utf-8")
    assert scanner._process_response(raw, addr, None, results) is False
    assert addr in results

    results.clear()
    assert scanner._process_response(raw, addr, "192.0.2.5", results) is True


@pytest.mark.asyncio
async def test_async_run_scan_respects_future() -> None:
    scanner = discovery.AIOELKDiscovery()
    sent: list[tuple[bytes, tuple[str, int]]] = []

    class _Transport:
        def sendto(self, data: bytes, dest: tuple[str, int]) -> None:
            sent.append((data, dest))

    fut: asyncio.Future[bool] = asyncio.Future()
    fut.set_result(True)
    await scanner._async_run_scan(
        cast(asyncio.DatagramTransport, _Transport()), ("255.255.255.255", 2362), 1, fut
    )
    assert sent


def test_destination_from_address() -> None:
    scanner = discovery.AIOELKDiscovery()
    assert scanner._destination_from_address(None) == (
        scanner.BROADCAST_ADDRESS,
        scanner.DISCOVERY_PORT,
    )
    assert scanner._destination_from_address("192.0.2.1") == ("192.0.2.1", scanner.DISCOVERY_PORT)


def test_create_udp_socket_nonblocking() -> None:
    sock = discovery.create_udp_socket()
    try:
        assert isinstance(sock, socket.socket)
        assert sock.getblocking() is False
    finally:
        sock.close()


def test_discovery_protocol_callbacks() -> None:
    seen: list[tuple[bytes, tuple[str, int]]] = []

    def on_response(data: bytes, addr: tuple[str, int]) -> None:
        seen.append((data, addr))

    proto = discovery.ELKDiscovery(("255.255.255.255", 2362), on_response=on_response)
    proto.datagram_received(b"payload", ("192.0.2.2", 1234))
    assert seen == [(b"payload", ("192.0.2.2", 1234))]
    proto.error_received(Exception("boom"))
    proto.connection_lost(None)


def test_process_response_decode_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    scanner = discovery.AIOELKDiscovery()
    results: dict[tuple[str, int], discovery.E27System] = {}

    def _raise(_raw: bytes) -> discovery.E27System:
        raise RuntimeError("bad")

    monkeypatch.setattr(discovery, "_decode_data", _raise)
    raw = b'{"MAGIC":"ELKWC2017"}'
    assert scanner._process_response(raw, ("192.0.2.5", 1234), None, results) is False
    assert not results


def test_process_response_decoded_none(monkeypatch: pytest.MonkeyPatch) -> None:
    scanner = discovery.AIOELKDiscovery()
    results: dict[tuple[str, int], discovery.E27System] = {}

    monkeypatch.setattr(discovery, "_decode_data", lambda _raw: None)
    raw = b'{"MAGIC":"ELKWC2017"}'
    assert scanner._process_response(raw, ("192.0.2.5", 1234), None, results) is False
    assert not results


@pytest.mark.asyncio
async def test_async_run_scan_zero_timeout() -> None:
    scanner = discovery.AIOELKDiscovery()
    sent: list[tuple[bytes, tuple[str, int]]] = []

    class _Transport:
        def sendto(self, data: bytes, dest: tuple[str, int]) -> None:
            sent.append((data, dest))

    fut: asyncio.Future[bool] = asyncio.Future()
    await scanner._async_run_scan(
        cast(asyncio.DatagramTransport, _Transport()), ("255.255.255.255", 2362), 0, fut
    )
    assert sent


@pytest.mark.asyncio
async def test_async_run_scan_timeout_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    scanner = discovery.AIOELKDiscovery()
    sent: list[tuple[bytes, tuple[str, int]]] = []

    class _Transport:
        def sendto(self, data: bytes, dest: tuple[str, int]) -> None:
            sent.append((data, dest))

    async def _wait_for(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise TimeoutError

    times = [0.0, 0.5, 0.6, 1.1]

    def _fake_monotonic() -> float:
        return times.pop(0) if times else 1.1

    monkeypatch.setattr(asyncio, "wait_for", _wait_for)
    monkeypatch.setattr(discovery.time, "monotonic", _fake_monotonic)
    fut: asyncio.Future[bool] = asyncio.Future()
    await scanner._async_run_scan(
        cast(asyncio.DatagramTransport, _Transport()), ("255.255.255.255", 2362), 1, fut
    )
    assert len(sent) >= 2


@pytest.mark.asyncio
async def test_async_scan_uses_socket_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    scanner = discovery.AIOELKDiscovery()
    created: dict[str, object] = {}

    class _Transport:
        def close(self) -> None:
            created["closed"] = True

    async def _create_datagram_endpoint(self, factory, **kwargs):  # type: ignore[no-untyped-def]
        created["sock"] = kwargs.get("sock")
        proto = factory()
        proto.datagram_received(b'{"MAGIC":"ELKWC2017"}', ("192.0.2.5", 1234))
        return _Transport(), proto

    async def _fake_run_scan(*_args, **_kwargs) -> None:
        created["ran"] = True

    monkeypatch.setattr(
        asyncio,
        "get_running_loop",
        lambda: type("L", (), {"create_datagram_endpoint": _create_datagram_endpoint})(),
    )
    monkeypatch.setattr(scanner, "_async_run_scan", _fake_run_scan)
    monkeypatch.setattr(
        scanner,
        "_process_response",
        lambda *_args, **_kwargs: (created.setdefault("processed", True) or True),
    )

    def _socket_factory() -> socket.socket:
        created["factory_used"] = True
        return socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    result = await scanner.async_scan(timeout=1, socket_factory=_socket_factory)
    assert result == []
    assert created.get("factory_used") is True
    assert created.get("ran") is True
    assert created.get("closed") is True
