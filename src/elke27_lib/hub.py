"""High-level public hub API for Elke27 consumers."""

from __future__ import annotations

from collections.abc import Callable

from .client import Elke27Client
from .events import Event
from .types import Area, ArmMode, ClientConfig, LinkKeys, Snapshot, Zone


class Elke27Hub:
    """Own connection settings and expose typed panel state."""

    def __init__(
        self,
        host: str,
        port: int,
        link_keys: LinkKeys,
        client_id: str,
        *,
        config: ClientConfig | None = None,
        client: Elke27Client | None = None,
    ) -> None:
        """Initialize the hub."""
        self._host = host
        self._port = port
        self._link_keys = link_keys
        self._client_id = client_id
        self._client = client or Elke27Client(config)
        self._client.set_client_identity({"mn": "222", "sn": client_id})

    @property
    def client(self) -> Elke27Client:
        """Return the underlying public client."""
        return self._client

    async def connect(self) -> None:
        """Connect to the configured panel."""
        await self._client.async_connect(self._host, self._port, self._link_keys)

    async def disconnect(self) -> None:
        """Disconnect from the configured panel."""
        await self._client.async_disconnect()

    def get_snapshot(self) -> Snapshot:
        """Return the latest typed snapshot."""
        return self._client.get_snapshot()

    def get_area(self, area_id: int) -> Area | None:
        """Return a typed area snapshot by id."""
        return self._client.get_area(area_id)

    def get_zone(self, zone_id: int) -> Zone | None:
        """Return a typed zone snapshot by id."""
        return self._client.get_zone(zone_id)

    async def set_zone_bypass(
        self, zone_id: int, *, bypassed: bool, pin: str | None = None
    ) -> None:
        """Set a zone bypass state."""
        await self._client.async_set_zone_bypass(zone_id, bypassed=bypassed, pin=pin)

    async def arm_area(
        self,
        area_id: int,
        *,
        mode: ArmMode,
        pin: str | None = None,
        auto_stay_cancel: bool = False,
        exit_delay_cancel: bool = False,
    ) -> None:
        """Arm an area."""
        await self._client.async_arm_area(
            area_id,
            mode=mode,
            pin=pin,
            auto_stay_cancel=auto_stay_cancel,
            exit_delay_cancel=exit_delay_cancel,
        )

    async def disarm_area(
        self,
        area_id: int,
        *,
        pin: str,
        auto_stay_cancel: bool = False,
        exit_delay_cancel: bool = False,
    ) -> None:
        """Disarm an area."""
        await self._client.async_disarm_area(
            area_id,
            pin=pin,
            auto_stay_cancel=auto_stay_cancel,
            exit_delay_cancel=exit_delay_cancel,
        )

    def subscribe(self, callback: Callable[[Event], None]) -> Callable[[], bool]:
        """Subscribe to typed events."""
        return self._client.subscribe_typed(callback)
