  Security Hardening, Barriers, Link Slots, Raw Pass-through (0.3.15)

  - Connection events (#80): when HELLO fails for a reason other than a panel
    refusal, the kernel no longer emits an unflagged `ConnectionStateChanged`
    with `connected=False` if the session never reached `connected=True` (same
    pair invariant as a TCP connect failure). Panel HELLO refusals still emit
    `connected=False` with `hello_refused=True`.
  - Dev/CI only (no library change): repeat review findings are now checks.
    Ruff enables `SLF001` (private member access; legacy test files are listed
    in per-file-ignores and the list may only shrink) and `BLE001` (blind
    except; the 14 existing library sites carry a line-level `noqa`). pytest
    runs with `xfail_strict = true`. New `test/test_review_guards.py` fails on
    private library access via helpers/imports in new tests, helpers imported
    from another test module, xfails without `raises=` or a linked issue,
    retry/resend wording in a public docstring without a registered behaviour
    test, and new literal-name `getattr`/`hasattr` calls in the library.
  - Dev/CI only: review guards hardened. Ruff `PGH004` (no bare noqa) is on.
    A tokenized noqa ceiling stops new SLF001/BLE001 escapes (any case, comma or
    space separated, bare, and file-level). The cross-test-module import check
    covers every import form, including relative ones. The ruff per-file-ignores
    table is frozen, each legacy test file has a shrink-only private-access
    ceiling (new test files must have none), and only the existing helper
    module may touch private members. Flake8-style file-level noqa headers
    count too. The stale pylint comment in discovery is gone.
  - Linking (security): a link reply with a non-zero ACK byte is now
    logged at WARNING with the ACK byte and payload length only. The decrypted
    reply (which carries the link key and HMAC) is never decoded into or printed
    in any log line.
  - Security round 1 (D2-D8, #71):
    - Secrets out of repr: `LinkKeys`, `E27LinkKeys`, `SessionKeys`,
      `SessionInfo`, `provisioning.Credentials` and the client's internal link
      credentials no longer show key, credential or PIN fields in
      `repr()`/`str()`. `LinkKeys.to_json()` is unchanged (its docstring now
      says it contains secrets).
    - Inbound DEBUG log: the kernel's "Inbound message" line is redacted with
      `redact_for_diagnostics` and is only built when DEBUG is enabled. The
      kernel's redaction now uses the single key set in `redact.py`
      (`redact.SECRET_KEYS`).
    - User PINs are no longer stored. `UserState.pin` is kept for API
      compatibility but is always `None` (deprecated; removal planned for the
      next minor). New `UserState.has_pin: bool` says whether the panel
      reported a PIN.
    - Behaviour change, authenticate PIN cache: the client caches the PIN only
      after the panel accepts `control.authenticate`, and forgets it on
      disconnect, close, an auth failure, a link drop or a session change.
      Re-sending it after a reconnect is now opt-in via the new
      `ClientConfig.reauth_on_reconnect` (default `False`); with it on, the PIN
      is re-sent once per accepted authenticate, on every reconnect whatever the
      outage length. `async_disconnect`, `close` or a link drop cancel a re-auth
      still in flight, and its outcome never restores the PIN. If that re-sent
      authenticate is
      refused, returns an error, or gets no reply within the normal request
      timeout (no reply counts as a refusal), the client logs one WARNING with
      the error code only (never the PIN), marks itself not authenticated (new
      `Elke27Client.authenticated` property is `False`; the authenticated role
      is cleared) and never re-sends the PIN. A link drop that cancels a re-auth
      in flight logs one WARNING (no PIN); later reconnects send no authenticate
      until the caller authenticates again. An unexpected exception in the
      re-auth is a bug, not a refusal: it is logged at ERROR with its traceback
      and the client is marked not authenticated. The CSM refresh after a
      reconnect no longer carries the PIN.
    - Discovery: a unicast `async_discover_host` reply is accepted only from
      the queried address, and the result's `host` is always that address
      (never the address the reply reports). Replies whose listen port is not
      1..65535 (or whose encrypted listen port is not 0..65535) are ignored and
      logged at DEBUG without the payload. Broadcast results are kept;
      `E27System` gains `source_host` and `address_mismatch`.
    - Inbound envelope sequence: the session now tracks the real
      inbound frame sequence number (it was never recorded). A non-increasing value logs one
      WARNING per session (later repeats count at DEBUG); frames are not
      dropped. Tracking resets on each new HELLO session.
    - Limits: the linking discovery buffer is capped at 8 KiB (the newest
      8 KiB are kept) and a JSON object
      split across reads waits for more data instead of failing (a complete
      object that is not valid JSON raises `E27ProtocolError`); a paged
      reply's `block_count` above 256 (`client.MAX_PAGED_BLOCK_COUNT`) is a
      `ProtocolError`; the kernel event deque now defaults to `maxlen=4096`
      (`kernel.DEFAULT_EVENT_QUEUE_MAXLEN`, drop oldest, first drop logged once at
      DEBUG, count in `events_dropped`; subscribers still receive every event). An explicit `event_queue_maxlen` still wins and `0`
      still means unbounded; `ClientConfig.event_queue_maxlen` now defaults to
      `None` (library default).
    - Dependencies: `cryptography>=50.0.0` (46.0.7 to 49.x have OSV
      advisories; 50.0.0 is at or below Home Assistant core's pin, 50.0.2);
      lock updated (cryptography 50.0.2, pytest 9.1.1, pygments 2.21.0). CI
      gains a pip-audit job over the locked dependencies; ignored advisories:
      none.
  - `features.control.build_control_authenticate_payload` now applies the
    client's PIN rules (#67, #68): an all-zero PIN (`0`, `"0000"`), a `bool`, and
    strings with non-ASCII digits (e.g. full-width `"１２３４"`) raise
    `ValueError`. Valid PINs 1..999999 build the same payload as before.
  - Raw pass-through: `async_raw_request` now accepts any JSON value as the
    verb's value, not only a mapping (for example a plain number or boolean),
    and sends it unchanged. Only dict, list,
    str, int, float (finite), bool and None are accepted, by exact type; bytes,
    sets, tuples, NaN/Infinity and other objects raise `Elke27InvalidArgument`
    before sending. Permission still keys only on the exact (domain, verb) pair,
    and the value is never logged.
  - Events (#62, #64): an `output.set_status` or `tstat.set_status` ack that carries
    no new state (usually just the id and `error_code`) no longer emits
    `OutputStatusUpdated` / `TstatStatusUpdated` with the stale cached value.
    The panel's status broadcast (or a re-read) emits the update. An ack that
    does change state still emits. Matches the light ack handling.
  - HELLO (#61, #65): a HELLO reply with no error code but no session (session_id,
    sk or shm absent, null or empty), as seen when two clients contend for the
    same link, now raises the new `E27HelloNoSession` (a `E27ProtocolError`)
    with "Panel refused the session ... (another client may be using this
    link)" instead of "Malformed hello response JSON". It is logged once at
    WARNING with the reply's keys only, and `async_connect` surfaces it as
    `Elke27ProtocolError` with the same text. A field with the wrong type is
    still reported as malformed. The malformed-reply DEBUG line now logs keys
    only, never the encrypted session key values. `ConnectionStateChanged`
    gains `hello_refused` (default `False`), set when session setup failed
    because the panel refused HELLO, so the client does not also log
    "Panel connection lost" for a session that never existed.
  - Barriers (#48): new `async_set_barrier(barrier_id, *, open)` sends one
    `barrier.set_status` (lowercase `open`/`close`) and never retries it (the
    kernel disables transport retries for the route and panel-busy replies are not resent); a
    missing reply raises `Elke27CommandOutcomeUnknownError`. New optional
    `async_refresh_barrier(barrier_id)` does one status read and returns the
    state. `V2BarrierState` gains `is_open` (OPEN -> True, CLOSE/CLOSED -> False,
    anything else -> None), `tamper`, `low_batt` and `rssi`; raw `status` is kept.
  - Linking (#49): linking fails when the panel has no free link slots; the
    link reply then carries an error message and no link keys.
    `async_link` now raises the new public `Elke27LinkSlotsFullError`
    (code `link_slots_full`, not transient) with the panel's raw text in
    `panel_error_message` and its `error_code`, if any, in `panel_error_code`,
    instead of a generic protocol error. Any other panel message in a keyless
    link reply is now included in the protocol error text.
    `Elke27LinkSlotsFullError` subclasses `Elke27Error`, not
    `Elke27ProtocolError`; callers that caught `Elke27ProtocolError` from
    `async_link` for a full link table must also catch the new error.
  - New opt-in raw pass-through that lets an application implement API
    messages the library doesn't natively support, over the library's
    connection. It is off by default, and message and reply contents are
    never logged (#60, #63).
  - Logging: link and authentication frames are no longer hex-dumped in
    debug logs (#60).
  - Framing: the `deframe discard: waiting for startchar` message for bytes
    that arrive before the first frame on a new link is now logged at DEBUG
    instead of ERROR; a discard after the first good frame is logged at
    WARNING (#52, #54).
  - Area status: the `area.get_status no changes` message after a re-read that
    finds nothing new (for example after a disarm) is now logged at DEBUG
    instead of WARNING (#53, #55).
  - Area bypass: the bypass-count message during normal bypass and unbypass
    is now logged at DEBUG instead of WARNING (#57, #58).

  Public Command Result, Typed Package (0.3.14)

  - New public `CommandResult` (frozen dataclass, exported from `elke27_lib`)
    for arm, disarm and zone bypass, so callers no longer need private client
    internals to learn whether the panel status refreshed after a write. Opt in
    with `return_result=True` on `async_arm_area`, `async_disarm_area` and
    `async_set_zone_bypass`; the default still returns `None` (no break).
    Fields: `route` (`"area_set_arm_state"` / `"zone_set_status"`) and
    `status_refresh_ok` (`True` refreshed or confirmed in the reply, `False`
    panel accepted but the follow-up read failed and the entity is marked stale,
    `None` no refresh applied); property `refreshed` is `status_refresh_ok is
    True`. Failures still raise the existing public `Elke27*` exceptions.

  - Ship `py.typed` (PEP 561) in the wheel so type checkers such as mypy
    --strict use the package's inline types.

  Panel MAC Discovery, HELLO Link Errors, Session Close (0.3.13)

  - New public helper `async_discover_host(host, timeout=3.0)` (E1a, panel MAC
    from discovery): sends the discovery request directly to the host's
    discovery port on its own socket, never touching a client session, and
    returns a `DiscoveredPanel` (MAC, IPv4 address, ports, name and serial from
    the discovery reply) or `None` when no valid reply arrives within the
    timeout or the host cannot be resolved.
    `panel_mac` is normalized to 12 uppercase hex characters with no separators.
    Also exported: `normalize_panel_mac(value)`.

  - HELLO errors (refs Tester hardware report 2026-10-13): a HELLO reply that
    carries `error_code` is checked before `session_id` is parsed. 11006
    (`invalid_id`: the client is not linked, or its link was revoked) and 11008
    (the session is not authorized) now raise `Elke27LinkRequiredError` (new optional attributes
    `panel_error_code` / `panel_error_message`) so callers start reauth instead of
    retrying. Other codes raise `Elke27ProtocolError` naming the code. Before, the
    reply surfaced as `Malformed hello response JSON: hello.session_id must be an
    int…` with an ERROR traceback; it is now one WARNING line. The `Result`
    `connect()` path returns `E27HelloLinkRequired` with the codes, not
    `AuthorizationRequired`.

  - Session: a receiver stopped by a deliberate close no longer reports a link
    loss when its blocked `recv` fails after the socket closes (refs #8). Before,
    it could log `Session disconnect: err=SessionIOError` with stale `rx_age`/`tx_age`
    and call `on_disconnected`, which could tear down a session that had already
    reconnected.

  Command Reliability, Fresh Status After Arm/Bypass, Panel Identity (0.3.12)

  - Panel identity (E1 follow-up, refs #40): a placeholder serial from
    the panel's version info request (empty, all zeros, the fixed placeholder the
    panel reports on hardware, all F) is ignored and `PanelInfo.serial` stays `None`, so it is never used as an
    identity. `model` and `firmware` come from the panel's version info; `mac`
    stays `None` (the MAC is only in the discovery reply).
    The version-info reply is now classified RESPONSE, not UNSOLICITED.

  - Panel identity (E1): after HELLO, `async_connect` sends the panel's version info request
    (fire-and-forget: no reply wait, retry or queue slot). The reply fills `PanelSnapshot.panel` `serial`, `mac` (new on
    `PanelMetaState`), `model` and `firmware`. A send failure, an error reply or
    missing fields never break connect: fields not yet known stay `None`, a
    reconnect to the same host:port keeps the last-known values, and a send failure
    is logged at DEBUG. Connecting to a different host:port clears the cached
    identity first. Payload keys were checked on hardware; see the follow-up
    entry above for the field mapping.

  - New public `Elke27CommandOutcomeUnknownError` (subclass of
    `Elke27TimeoutError`, carries `route=(domain, command)`). `async_execute` and the
    command helpers return/raise it when a write was confirmed sent (`on_sent`) but no
    reply arrived before the command deadline; the panel may have applied it, so
    re-read the entity. If the caller cancels after the confirmed send,
    `asyncio.CancelledError` still propagates, with this error as `__cause__`.
    Timeouts before the frame was sent, and read timeouts (the explicit
    `elke27_lib.command_kinds.READ_ONLY_ROUTES` list), stay plain
    `Elke27TimeoutError`. Existing `except Elke27TimeoutError` handlers keep working.

  - After a successful `area_set_arm_state` or `zone_set_status`, the client issues
    a follow-up `area_get_status` / `zone_get_status` (unless the command reply
    already included confirmed arm or bypass fields) so `get_snapshot()` reflects
    panel state when the command returns. The write still succeeds if that read
    fails; `Result.status_refresh_ok` is `False` and the affected area or zone id
    is tracked in `PanelSnapshot.stale_area_ids` / `stale_zone_ids` (with
    `PanelSnapshot.stale` true when any id is stale). Arm/bypass helpers wait
    for the touched entity's status event (not any snapshot version bump), within
    the command timeout (#15).

  - Command transport failures are retried with bounded exponential backoff using
    the existing `request_max_retries` / `request_max_backoff_s` kernel settings
    (#12). Retries apply to reply timeouts and send failures while the session
    stays up, and to panel busy (`ELKERR_ZWAVE_BUSY`, 11039) on `async_execute`.
    Session loss fails queued and in-flight commands immediately for every command
    (reads included), surfaces as `Elke27DisconnectedError` on v2 exception paths,
    and is never automatically resent after reconnect. Each command gets an
    absolute deadline; `async_execute`
    waits for the full transport budget (~16.5 s with defaults: `(retries+1) ×
    5 s timeout + 0.5 s + 1 s backoff`) and cancels kernel retries if the
    caller times out. Transport retries reuse the same JSON `seq` on resend.
    Panel refusals (any other non-zero `error_code`, permission, auth, or invalid
    argument) are never retried. After a confirmed send (`on_sent`), only
    `get_*` read routes and `area.set_arm_state` with `arm_state=DISARMED` may
    retry on reply timeout; every other command (locks, lights, thermostats,
    barriers, other arm states, all `set_*` writes, system mutations, etc.) is
    at-most-once and fails without resend: writes with
    `Elke27CommandOutcomeUnknownError` (#35), reads in `READ_ONLY_ROUTES` that are
    not `get_*` with plain `Elke27TimeoutError`. Pre-send transport
    failures keep the normal retry policy. Disarm is
    always `OutboundPriority.HIGH`, is requeued immediately on transport retry
    (no backoff), and is not delayed behind other commands waiting to retry.
    `kernel.close()` fails every pending command (including send-confirmation
    waiters and transport backoff waiters) before clearing retry timers.

  - Area exit delay: `area.get_status` and periodic status broadcasts expose
    `arm_cmd_state`, `ee_timer`, and `alarm_zone` during the arm exit countdown.
    Public `arming` is `True` only when all four fields are present on the
    snapshot, `alarm_zone == ""` exactly (missing/`None` is not empty),
    `ee_timer` > 0, and the area is disarmed with a pending away/stay command.
    Partial payloads clear any of the four exit-delay fields not included, except
    an `ee_timer`-only tick after a complete four-field payload: accept when
    `0 < new <= previous` (duplicates allowed), ignore when `new > previous`,
    and clear when `new == 0`. A restarted exit timer requires a fresh full
    four-field payload. Reconnect and client snapshot reset clear pending
    exit-delay fields. A stay→away command change without a fresh full
    `get_status` leaves `arming` false; consumers should treat exit-delay skip
    logic only after a full four-field status read.

  - HELLO: restore the socket read timeout after the short pre-HELLO probe;
    `Session.connect()` reapplies `io_timeout_s` when HELLO finishes so the
    receive pump keeps the configured cadence (#33). Pre-HELLO greeting bytes
    log at DEBUG instead of WARNING.

  - Session transport: serialize outbound `send()` with a send-only lock (recv
    stays unlocked on its worker thread), enforce write deadlines with a
    monotonic `io_write_timeout_s` without changing socket `settimeout` (so
    read cadence stays at `io_timeout_s`), log partial sends, tear down the
    session on kernel outbound `SessionIOError` (including no-reply sends), and
    emit a single disconnect when both teardown and the recv thread observe a
    dead socket (#8).
  - Behavior change: commands sent while not connected (no session / encryption
    key) now raise `Elke27DisconnectedError` (transient) from v2 command helpers
    instead of `Elke27PermissionError`. `ConnectionLost` during a command now
    raises `Elke27DisconnectedError` instead of `Elke27TimeoutError`. Callers
    that catch those errors for these cases must update (#13).
  - `async_connect` no longer retries panel auth or link refusals (wrong
    credentials, invalid link keys, and related non-transient errors); those fail
    on the first attempt (#14). Transport-class failures may still be retried
    once. `asyncio.CancelledError` propagates instead of being swallowed during
    connect. A transport failure that will be retried logs `Connect failed
    (attempt 1/2)` at DEBUG only; the final attempt keeps the policy below.
  - Reconnect `async_connect` attempts while the panel is unreachable no longer
    log `Connect failed (attempt n/2)` at ERROR every few seconds (#21). After
    `Panel connection lost`, further transient failures log at DEBUG; the first
    transient failure when the panel was never up logs once at WARNING, then
    DEBUG. Non-transient failures (e.g. invalid link keys) and unrecognized
    connect errors remain ERROR with traceback. The first successful connect
    after warned transient failures logs INFO (`Panel connection established
    after connect failures`); link restore still uses `Panel connection restored`.
    See ADR-0013 keepalive / connection logging notes.
  - Connect error mapping: `E27Timeout` during connect now raises
    `Elke27TimeoutError` (previously `Elke27ProtocolError`). `E27NotReady`
    during connect now raises `Elke27ConnectionError`. Failures wrapped by the
    kernel during connect now map to `Elke27ConnectionError`,
    `Elke27TimeoutError`, `Elke27AuthError`, or `Elke27CryptoError` when the
    underlying cause matches (previously `Elke27ProtocolError`).
  - A HELLO deadline timeout is now retried as transient (`E27HelloTimeout`); a
    malformed HELLO is still permanent.

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
