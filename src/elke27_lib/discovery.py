"""Discovery of E27 panels."""

from __future__ import annotations

import asyncio
import importlib
import json
import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from .errors import Elke27InvalidArgument
from .types import DiscoveredPanel

_LOGGER = logging.getLogger(__name__)

if TYPE_CHECKING:
    from typing_extensions import override
else:

    def override(func):  # type: ignore[no-redef] -- typing_extensions only in TYPE_CHECKING
        return func


def _discovery_sock_thread() -> Any:
    return importlib.import_module("elke27_lib.discovery_socket_thread")


@dataclass
class E27System:
    """An ELKE27 panel identity record."""

    panel_mac: str
    panel_host: str
    panel_name: str
    panel_serial: str | None
    port: int
    tls_port: int
    # Address the reply actually came from. For broadcast scans this may differ
    # from the panel_host the payload claims; see address_mismatch.
    source_host: str | None = None

    @property
    def address_mismatch(self) -> bool:
        """True when the reply's source IP differs from the IPV4_ADDR it reports."""
        return bool(self.source_host and self.panel_host and self.source_host != self.panel_host)


def _valid_port(value: object, *, allow_zero: bool = False) -> int | None:
    """Return the port as an int if it is 1..65535 (or 0 when allowed), else None."""
    if isinstance(value, bool):
        return None
    try:
        port = int(cast(Any, value))
    except (TypeError, ValueError, OverflowError):
        return None
    if port == 0 and allow_zero:
        return 0
    if 1 <= port <= 65535:
        return port
    return None


class ELKDiscovery(asyncio.DatagramProtocol):
    """Discovery main class."""

    def __init__(
        self,
        destination: tuple[str, int],
        on_response: Callable[[bytes, tuple[str, int]], None],
    ) -> None:
        self.transport: asyncio.DatagramTransport | None = None
        self.destination: tuple[str, int] = destination
        self.on_response: Callable[[bytes, tuple[str, int]], None] = on_response

    @override
    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        """Trigger on_response."""
        self.on_response(data, addr)

    @override
    def error_received(self, exc: Exception | None) -> None:
        """Handle error."""
        _LOGGER.error("ELKDiscovery error: %s", exc)

    @override
    def connection_lost(self, exc: Exception | None) -> None:
        """Do nothing on connection lost."""


def _decode_data(raw_response: bytes) -> E27System | None:
    """Decode an ELK discovery response packet."""

    try:
        data = json.loads(raw_response)
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        _LOGGER.debug("Failed to decode discovery response: %s", e)
        return None

    if not isinstance(data, dict):
        _LOGGER.debug("Ignoring discovery response: not a JSON object")
        return None
    data = cast(dict[str, Any], data)
    mac_address = str(data.get("MAC_ADDR", "")).strip().lower()
    panel_host = str(data.get("IPV4_ADDR", "")).strip()
    port = _valid_port(data.get("LISTEN_PORT"))
    tls_port = _valid_port(data.get("ENCRYPTED_LISTEN_PORT", 0), allow_zero=True)
    if port is None or tls_port is None:
        # No payload in the log: the reply is untrusted.
        _LOGGER.debug("Ignoring discovery response: port out of range (1..65535)")
        return None
    panel_name = str(data.get("NAME", "")).strip()
    panel_serial = data.get("SERIAL")
    if panel_serial is not None:
        panel_serial = str(panel_serial).strip()

    return E27System(
        panel_mac=mac_address,
        panel_host=panel_host,
        panel_name=panel_name,
        panel_serial=panel_serial or None,
        port=port,
        tls_port=tls_port,
    )


class AIOELKDiscovery:
    """A 30303 discovery scanner."""

    DISCOVERY_PORT: int = 2362
    BROADCAST_FREQUENCY: int = 3
    DISCOVER_MESSAGE: bytes = b'{"FIND":"ELKWCID"}'
    BROADCAST_ADDRESS: str = "<broadcast>"

    def __init__(self) -> None:
        self.found_devices: list[E27System] = []

    def _destinations_from_address(self, address: str | None) -> list[tuple[str, int]]:
        return _discovery_sock_thread().destinations_from_broadcasts(self.DISCOVERY_PORT, address)

    def _process_response(
        self,
        data: bytes | None,
        from_address: tuple[str, int],
        address: str | None,
        response_list: dict[tuple[str, int], E27System],
    ) -> bool:
        """Process a response.

        Returns True if processing should stop
        """
        if data is None or data == self.DISCOVER_MESSAGE or b"ELKWC2017" not in data:
            return False
        if address is not None and from_address[0] != address:
            # Unicast scan: only the host we asked may answer.
            _LOGGER.debug("Ignoring discovery reply from unexpected source %s", from_address[0])
            return False
        try:
            decoded = _decode_data(data)
        except Exception as ex:  # noqa: BLE001 -- decode failures are logged only
            _LOGGER.warning(
                "Failed to decode response from %s: %s", from_address, type(ex).__name__
            )
            return False
        if decoded is None:
            return False
        decoded.source_host = from_address[0]
        response_list[from_address] = decoded
        return from_address[0] == address

    async def _async_run_scan(
        self,
        transport: asyncio.DatagramTransport,
        destinations: list[tuple[str, int]],
        scan_duration_s: float,
        found_all_future: asyncio.Future[bool],
    ) -> None:
        """Send the scans."""
        for destination in destinations:
            _LOGGER.debug("discover: %s => %s", destination, self.DISCOVER_MESSAGE)
            transport.sendto(self.DISCOVER_MESSAGE, destination)
        quit_time = time.monotonic() + scan_duration_s
        remain_time = float(scan_duration_s)
        while True:
            time_out = min(remain_time, scan_duration_s / self.BROADCAST_FREQUENCY)
            if time_out <= 0:
                return
            try:
                await asyncio.wait_for(asyncio.shield(found_all_future), timeout=time_out)
            except TimeoutError:
                if time.monotonic() >= quit_time:
                    return
                # No response, send broadcast again in cast it got lost
                for destination in destinations:
                    _LOGGER.debug("discover: %s => %s", destination, self.DISCOVER_MESSAGE)
                    transport.sendto(self.DISCOVER_MESSAGE, destination)
            else:
                return  # found_all
            remain_time = quit_time - time.monotonic()

    async def async_scan(
        self,
        timeout: float = 10,  # noqa: ASYNC109 -- public keyword timeout stays stable
        address: str | None = None,
        *,
        sock: Any = None,
        socket_factory: Callable[[], Any] | None = None,
    ) -> list[E27System]:
        """Discover ELK devices."""
        if sock is None:
            ds = _discovery_sock_thread()
            sock = (
                socket_factory()
                if socket_factory is not None
                else await asyncio.to_thread(ds.create_udp_socket)
            )
        destinations = self._destinations_from_address(address)
        found_all_future: asyncio.Future[bool] = asyncio.Future()
        response_list: dict[tuple[str, int], E27System] = {}

        def _on_response(data: bytes, addr: tuple[str, int]) -> None:
            _LOGGER.debug("discover: %s <= %s", addr, data)
            if self._process_response(data, addr, address, response_list):
                found_all_future.set_result(True)

        transport, _ = await asyncio.get_running_loop().create_datagram_endpoint(
            lambda: ELKDiscovery(
                destination=destinations[0],
                on_response=_on_response,
            ),
            sock=sock,
        )
        try:
            await self._async_run_scan(
                transport,
                destinations,
                scan_duration_s=timeout,
                found_all_future=found_all_future,
            )
        finally:
            transport.close()

        self.found_devices = list(response_list.values())
        return self.found_devices


def normalize_panel_mac(value: object) -> str | None:
    """Return a MAC as 12 uppercase hex characters with no separators, or None.

    Accepts ``aa:bb:cc:dd:ee:ff``, ``AA-BB-CC-DD-EE-FF``, ``aabb.ccdd.eeff`` and
    bare 12-hex forms. Anything else (wrong length, non-hex, all zeros) is None.
    """
    if not isinstance(value, str):
        return None
    cleaned = "".join(ch for ch in value.strip() if ch not in ":-. ").upper()
    if len(cleaned) != 12 or any(ch not in "0123456789ABCDEF" for ch in cleaned):
        return None
    if cleaned == "000000000000":
        return None
    return cleaned


async def async_discover_host(
    host: str,
    timeout: float = 3.0,  # noqa: ASYNC109 -- public keyword timeout stays stable
    *,
    socket_factory: Callable[[], Any] | None = None,
) -> DiscoveredPanel | None:
    """Send a unicast discovery request to ``host`` and return its reply.

    Uses its own UDP socket and never touches a client session, so it is safe
    to call while connected. Returns ``None`` when no valid reply arrives within
    ``timeout`` seconds or the host cannot be resolved. ``panel_mac`` in the
    result is normalized to 12 uppercase hex characters (``None`` if invalid).
    """
    if not isinstance(host, str) or not host.strip():
        raise Elke27InvalidArgument("host must be a non-empty string.")
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not math.isfinite(timeout)
        or timeout <= 0
    ):
        raise Elke27InvalidArgument("timeout must be a finite positive number.")
    host = host.strip()
    loop = asyncio.get_running_loop()
    _socket = importlib.import_module("socket")
    try:
        infos = await loop.getaddrinfo(host, None, family=_socket.AF_INET, type=_socket.SOCK_DGRAM)
        address = str(infos[0][4][0])
    except (OSError, IndexError) as exc:
        _LOGGER.debug("discover_host: cannot resolve %s: %s", host, exc)
        return None

    scanner = AIOELKDiscovery()
    try:
        found = await scanner.async_scan(
            timeout=timeout,
            address=address,
            socket_factory=socket_factory,
        )
    except OSError as exc:
        _LOGGER.debug("discover_host: %s failed: %s", host, exc)
        return None
    if not found:
        return None
    # Only replies from the queried address are kept (see _process_response); the
    # host is the address we asked, never the IPV4_ADDR the payload claims.
    system = next((s for s in found if s.panel_host == address), found[0])
    return DiscoveredPanel(
        host=address,
        port=int(system.port),
        tls_port=int(system.tls_port) if system.tls_port else None,
        panel_name=system.panel_name or None,
        panel_serial=system.panel_serial or None,
        panel_mac=normalize_panel_mac(system.panel_mac),
    )
