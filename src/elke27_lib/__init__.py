"""Elke27 v2 public API surface."""

import importlib
from typing import Any

from .errors import (
    Elke27AuthError,
    Elke27ConnectionError,
    Elke27CryptoError,
    Elke27DisconnectedError,
    Elke27Error,
    Elke27InvalidArgument,
    Elke27LinkRequiredError,
    Elke27PermissionError,
    Elke27PinRequiredError,
    Elke27ProtocolError,
    Elke27TimeoutError,
    Elke27TransientError,
)
from .redact import redact_for_diagnostics
from .types import (
    Area,
    AreaState,
    ArmMode,
    BarrierState,
    ClientConfig,
    CsmSnapshot,
    DiscoveredPanel,
    Elke27Event,
    EventType,
    LightState,
    LinkKeys,
    LockState,
    OutputDefinition,
    OutputState,
    PanelInfo,
    PanelSnapshot,
    Snapshot,
    TableInfo,
    ThermostatState,
    Zone,
    ZoneDefinition,
    ZoneState,
)


def __getattr__(name: str) -> Any:
    if name == "Elke27Client":
        module = importlib.import_module(".client", __name__)
        return module.Elke27Client
    if name == "Elke27Hub":
        module = importlib.import_module(".hub", __name__)
        return module.Elke27Hub
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ClientConfig",
    "DiscoveredPanel",
    "LinkKeys",
    "Snapshot",
    "PanelSnapshot",
    "CsmSnapshot",
    "PanelInfo",
    "TableInfo",
    "Area",
    "AreaState",
    "Zone",
    "ZoneState",
    "OutputState",
    "LightState",
    "BarrierState",
    "LockState",
    "ThermostatState",
    "ZoneDefinition",
    "OutputDefinition",
    "ArmMode",
    "Elke27Event",
    "EventType",
    "Elke27Error",
    "Elke27TransientError",
    "Elke27ConnectionError",
    "Elke27TimeoutError",
    "Elke27DisconnectedError",
    "Elke27AuthError",
    "Elke27LinkRequiredError",
    "Elke27PinRequiredError",
    "Elke27PermissionError",
    "Elke27ProtocolError",
    "Elke27CryptoError",
    "Elke27InvalidArgument",
    "Elke27Hub",
    "redact_for_diagnostics",
]
