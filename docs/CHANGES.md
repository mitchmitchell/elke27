  Fast Dead-Link Detection, Quieter Connection Logs, async_execute Panel Errors (0.3.11)

  - A dead panel link is detected within seconds instead of ~2 minutes (#18,
    #20). Keepalive probes are scheduled from the last inbound traffic (sends
    no longer postpone them), the first unanswered probe disconnects
    (`keepalive_max_missed` default 2 -> 1), and `keepalive_timeout_s` default
    is 5 s (was 10 s).
  - A request that times out with no inbound traffic since it was sent
    triggers an immediate probe. New `Elke27Client.request_link_check()` lets
    callers do the same (no-op when not connected).
  - Connection loss logs `Panel connection lost` once at WARNING (not the only
    message: `E27 reply timeout`, an in-flight request abort or an interrupted
    keepalive check may also log a WARNING, and each failed reconnect attempt logs
    `Connect failed (attempt n/2)` at ERROR, #21; list not exhaustive); restore
    logs at INFO; a deliberate close/unload logs at DEBUG. `Session disconnect`
    and `keepalive response missing` are INFO (#19, #20).

  - `async_execute` now returns `Elke27PanelError` (with `panel_error_code`,
    `reason`, and a warning log) when the panel answers with a non-zero
    `error_code`, including single and paged responses. Helpers that already
    mapped panel errors via `_raise_v2_command_error` are unchanged.
  - String PIN validation for `async_execute` and wire coercion now requires
    ASCII digits only (`0`–`9`). Unicode numerals and other non-digit strings
    raise `Elke27InvalidArgument` before anything is sent instead of escaping
    as `ValueError`.
  - Behavior change: the `async_execute` special case that turned panel error
    11008 into the internal `AuthorizationRequired` is removed. A 11008 reply now
    comes back as `Elke27PanelError` with `panel_error_code == 11008` and reason
    "not authorized", like every other panel code.
  - Behavior change: callers of `async_execute` (including
    `control_authenticate`) now get `Elke27InvalidArgument` instead of the
    internal `InvalidPinError` for a bad PIN (non-ASCII-digit string, zero,
    negative, `bool`, or non-integer type). Nothing is sent to the panel (#11).

  Panel Error Reasons, Area Ready, Arm Night, Lights, Zone Bypass (0.3.10)

  - Commands rejected by the panel with a non-zero `error_code` now raise the new
    `Elke27PanelError` (a subclass of `Elke27ProtocolError`) with
    `panel_error_code` and a short `reason` (e.g. "invalid user code", "area not
    ready (open or faulted zones)", "area is in alarm; disarm to clear it first")
    instead of the generic "Operation failed.", and log a warning (#5).
  - `AreaState.ready` is derived from the panel's `ready_status` (`RDY_NOT` ->
    False, other `RDY_*` -> True) when no `ready` boolean is reported, and
    `AreaState.ready_status` is exposed (#6).
  - `async_arm_area(mode=ArmMode.ARMED_NIGHT)` raises `Elke27InvalidArgument`
    before sending: the E27 has Away and Stay arming only (#4).
  - A wrong user code on arm/disarm is answered with 11004; its reason now reads
    "invalid parameter (check the user code)" (#5).
  - `async_set_zone_bypass` sends the PIN as a JSON integer, like arm/disarm (a
    string PIN was answered with 11008), and a panel 11008 reply raises
    `Elke27PanelError` with reason "not authorized" instead of "Operation
    failed." (#10).
  - Light `set_status` acks (`{light_id, error_code}` with no state) no longer
    emit a stale `LightStatusUpdated`; `on` is derived from `level > 0` whenever
    a status reply reports a level (`get_status` sends only `level`), so the
    follow-up `get_status` updates the light (#7). Light status payloads are
    logged at debug level.

  Arm/Disarm PIN Handling (0.3.9)

  - Fixed `async_arm_area` / `async_disarm_area` failing with
    `Elke27ProtocolError: Operation failed` for every string PIN. The generator
    module uses postponed annotations, so the `pin: int` check in
    `_coerce_pin_for_generator` never matched and the generator compared a `str`
    to `0`. Annotations are now resolved with `typing.get_type_hints` (falling
    back to parsing `"int"` / `"int | str"` text).
  - `area.set_arm_state` carries `pin` as a JSON integer, so leading zeros are
    accepted and dropped on the wire (`"0123"` is sent as `123`). All-zero PINs,
    non-digit strings, `bool`, and non-positive ints raise `Elke27InvalidArgument`
    before anything is sent.
  - `async_arm_area` / `async_disarm_area` accept `str | int` PINs; int PINs keep
    their previous behavior.

  Thermostat Setpoint Units (0.3.8)

  - `tstat.set_status` setpoints are sent as whole degrees, as documented in the
    E27 Dealer API, instead of tenths (0.3.5-0.3.7 sent 68 F as 680, which the
    panel stored and the Elk app displayed). Fractional input rounds half up;
    values outside -40..150 raise `ValueError` to reject pre-scaled tenths.
  - Public thermostat temperature, setpoints, and humidity are scaled by the
    precision bits of the status `prec` array (no change for precision 0).

  Panel Snapshot Metadata

  - Added `PanelInfo.panel_name` so public runtime snapshots expose the panel
    display name when the kernel has panel-name metadata.
  - `system.get_attribs` now updates the panel display name in kernel state and
    refreshes the public client snapshot when the panel name changes.

  Zone Area Metadata

  - Added `ZoneState.area_id` to public panel snapshots. The library already tracked
    zone area assignments internally from `zone.get_attribs`; snapshots now expose
    that metadata so consumers can scope zone behavior, such as bypass operations,
    to the correct area.

  Runtime Domain Expansion + Arm/Disarm Flags

  - Added runtime domain support for:
    - lights
    - barriers (garage doors)
    - locks
    - outputs (extended coverage)
    - thermostats (extended coverage)
  - Added full per-domain runtime API shape across the new domains:
    - get_table_info
    - get_configured (paged where applicable)
    - get_attribs
    - get_status
    - set_status (controllable domains)
  - Canonical snapshot and event coverage now include:
    - barriers
    - locks
    - lights
    - outputs
    - thermostats
  - Added/updated live tests for:
    - Plug Dimmer light control
    - Closet Door lock control
    - File Room thermostat status/control
    - new-domain runtime coverage
  - Updated lock command semantics to match Dealer API:
    - set_status status=ON to lock
    - set_status status=OFF to unlock
  - Extended area arm/disarm payload support and public helper signatures with:
    - auto_stay_cancel (default false)
    - exit_delay_cancel (default false)

  Public Client Surface (stable import path)

  - Public import path is elke27_lib.client and HA should use from elke27_lib.client import Elke27Client, Result only. I kept this as the single public entry point
    and avoided HA importing internals.
  - Client construction is lightweight and non‑blocking; feature module imports are deferred to connect() and run off‑loop in async contexts. Docs updated to make
    this explicit.

  Connect/Identity/Stateless Behavior

  - Elke27Client.connect() now requires explicit context every time (panel or session_config, plus protocol identity), and does not rely on any prior link() state or
    stored panel info. The Elk layer no longer stores panel/identity between connects.
  - Protocol identity is consistently named client_identity (no “identity” alias); error messages say “client_identity”.
  - The library explicitly does not store persistence or link keys on disk; HA owns panel info and persistence.

  Readiness Semantics

  - is_ready is now strictly defined and documented as: Session ACTIVE + panel_info present + table_info structure present. It’s monotonic until disconnect.
  - table_info may be placeholders; HA must tolerate missing counts.
  - Added bootstrap_complete_counts (Option A) to indicate when real table_info counts for all domains are available. This flips False→True when real counts arrive.
    (Optional “counts ready” event emitted.)

  Events / Subscription

  - Subscription callbacks receive semantic events only (no raw frames/bytes).
  - subscribe() / unsubscribe() are safe during dispatch; callbacks should not block.
  - Authorization required is surfaced as semantic event (and/or typed exception on command, depending on the command); no PIN prompting in library.

  Typed Error Taxonomy

  - Stable typed errors exposed: AuthorizationRequired, InvalidCredentials (or InvalidLinkKeys), ConnectionLost, ProtocolError/CryptoError. HA sees these via raised
    exceptions and/or semantic events.
  - Missing connect context now maps to a specific missing‑context error code, not AUTH_REQUIRED.

  Snapshots / Inventory Filtering

  - Snapshots are views (not deep copies) for panel_info, table_info, areas, zones, outputs, lights, thermostats.
  - Areas/zones snapshots are filtered to configured IDs only. No capacity slots are exposed to HA.
  - Configured inventory is fetched via area.get_configured / zone.get_configured with paging (block_id/block_count), reassembled in dispatcher with ADR‑0013 rules.
  - Authorization‑required on get_configured surfaces an AuthorizationRequired event; inventory remains partial and HA must tolerate missing configured sets.

  Name Loading

  - Names are loaded via per‑ID area.get_attribs / zone.get_attribs after configured inventory completes.
  - Added AreaState.name / ZoneState.name (Optional[str]) with normalization.
  - Rate‑limited/queued attrib requests to avoid floods; invalid_id is treated as terminal (no retries).

  Discovery Output

  - discovery returns panel identity only: panel_mac, panel_name, panel_serial, panel_host/port; no protocol client identity and no ambiguous “identity” key.

  Sequencing & Paging Reliability (HA‑visible stability)

  - JSON seq now wraps per ADR‑0013, never zero for requests.
  - Encrypted envelope sequence is per‑session and monotonic.
  - Paging reassembly is correlation‑keyed, out‑of‑order safe, and only dispatches fully assembled payloads.
  - Transfers time out and abort cleanly on disconnect; keepalive responses are internal.

  Recent Fixes Directly Impacting HA

  - Paged configured responses now treat string block_id/block_count as paged data, preventing fallback to bitmask and eliminating phantom zones 51‑64 on panels that
    send numeric strings.
  - Added guard for ids above known table sizes and invalid_id streak handling to stop probing.
  - Added inflight window and retry policy: invalid_id is terminal; timeouts retry with backoff.
  - Root‑empty responses now include payload in diagnostic events.
