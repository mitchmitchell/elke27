# Elke27 v2 Public API (HA-first)

This document describes the v2 public API surface for `elke27_lib`. The v2
surface is async-only, exceptions-only, and intentionally hides protocol and
session details.

## Design guarantees

- Async-only API methods for I/O and commands.
- Exceptions-only error reporting (no Result return types).
- Immutable, typed events.
- Immutable, atomic snapshots; replace snapshots wholesale on updates.
- No protocol/session objects exposed in the public API.
- No secrets logged or emitted in diagnostics.

## Usage example

```python
from elke27_lib import (
    Elke27Client,
    ClientConfig,
    ArmMode,
    redact_for_diagnostics,
)

config = ClientConfig()
client = Elke27Client(config)

async def main():
    # discovery -> link -> connect -> wait_ready
    panels = await client.async_discover(timeout_s=10.0)
    panel = panels[0]
    link_keys = await client.async_link(
        panel.host,
        panel.port,
        access_code="1234",
        passphrase="secret",
        client_identity={"mn": "HA", "sn": "SN", "fwver": "0", "hwver": "0", "osver": "0"},
        timeout_s=10.0,
    )

    # On later starts, after loading persisted link keys, set the same client
    # identity before connecting so HELLO uses the original provisioned identity.
    client.set_client_identity(
        {"mn": "HA", "sn": "SN", "fwver": "0", "hwver": "0", "osver": "0"}
    )
    await client.async_connect(panel.host, panel.port, link_keys)
    ready = client.wait_ready(timeout_s=10.0)
    if not ready:
        raise RuntimeError("Client not ready")

    # subscribe to events
    def on_event(evt):
        print(evt.event_type, evt.data)

    unsubscribe = client.subscribe(on_event)

    # async event stream
    async for event in client.events():
        print(event.event_type, event.seq, event.timestamp)
        break

    # read snapshot
    snapshot = client.snapshot
    print(snapshot.panel, snapshot.table_info)

    # issue commands (no optimistic updates; state updates arrive via events/snapshot)
    await client.async_set_output(output_id=1, on=True)
    # barriers: sent at most once, never retried; resync with one status read
    await client.async_set_barrier(1, open=True)
    barrier = await client.async_refresh_barrier(1)  # V2BarrierState | None
    await client.async_arm_area(
        area_id=1,
        mode=ArmMode.ARMED_STAY,
        pin="1234",
        auto_stay_cancel=False,
        exit_delay_cancel=False,
    )
    await client.async_disarm_area(
        area_id=1,
        pin="1234",
        auto_stay_cancel=False,
        exit_delay_cancel=False,
    )

    # opt in to the post-command refresh outcome (default return stays None)
    result = await client.async_arm_area(
        area_id=1, mode=ArmMode.ARMED_AWAY, pin="1234", return_result=True
    )
    if result.status_refresh_ok is False:
        ...  # panel accepted, but status read failed; area is marked stale

    # cleanup
    unsubscribe()
    await client.async_disconnect()

```

## Notes

- `access_code` is only used for linking (integration authentication).
- `pin` is the runtime user PIN for authorization on privileged commands.
- Events are immutable; treat each event as a point-in-time observation.
- Snapshot updates are atomic: a new immutable PanelSnapshot is published each time.
- Snapshots include a monotonic version field and updated_at timestamp.
- Event queue is bounded; when full, the oldest event is dropped to make room.
- Subscriber callbacks are invoked synchronously and must not block.
- Diagnostic helpers such as `redact_for_diagnostics` remove likely secrets
  from structured data before logging.

## Runtime Domain APIs

The runtime domain APIs exposed through `async_execute(command_key, **kwargs)`
follow a shared pattern:

- `get_table_info`
- `get_configured`
- `get_attribs`
- `get_status`
- `set_status` (controllable domains)

Implemented controllable domains:

- `output`
- `light`
- `barrier`
- `lock`
- `tstat`

Example command keys:

- `output_set_status`
- `light_set_status`
- `barrier_set_status`
- `lock_set_status`
- `tstat_set_status`

Lock control payload semantics follow the Dealer API:

- `lock_set_status(..., status="ON")` locks
- `lock_set_status(..., status="OFF")` unlocks


## Unicast discovery of one host

`elke27_lib.async_discover_host(host, timeout=3.0) -> DiscoveredPanel | None`

Sends one unicast discovery request (resent within the timeout) to `host` on UDP
2362 using its own socket. It never touches a client or session, so it is safe
while connected. Returns `None` if no valid reply arrives or `host` cannot be
resolved; raises `Elke27InvalidArgument` for an empty host or non-positive
timeout. `panel_mac` is the discovery `MAC_ADDR` normalized by
`normalize_panel_mac()` to 12 uppercase hex characters (`None` if invalid or all
zeros). Discovery is the only source of the panel MAC.

## Barriers

- `async_set_barrier(barrier_id, *, open: bool) -> None` sends one
  `barrier.set_status` (`open` / `close`). It validates the id (>= 1 and, once
  the configured-barrier inventory is known, present in it) and the connection,
  then sends exactly once: no transport retry, no panel-busy resend and no resend
  after a missing reply. Errors: `Elke27InvalidArgument`, `Elke27DisconnectedError`,
  `Elke27PermissionError` (and other mapped panel refusals),
  `Elke27CommandOutcomeUnknownError` (sent, no reply; the panel may have acted).
- `async_refresh_barrier(barrier_id) -> V2BarrierState | None` performs one
  `barrier.get_status` read and returns the updated state.
- `V2BarrierState` fields: `barrier_id`, `name`, raw `status`, `is_open`
  (`True` for OPEN, `False` for CLOSE/CLOSED, `None` for STOPPED or anything
  else; no travel state is inferred), `tamper`, `low_batt`, `rssi`.
