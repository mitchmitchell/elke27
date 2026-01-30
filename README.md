# elke27

# elke27_lib

`elke27_lib` is a Python 3.11+ library for interfacing with the **Elk Products E27 Alarm Engine** over the E27 IP protocol. It is designed to be consumed by **Home Assistant** (and standalone tools) while keeping the protocol implementation encapsulated behind a stable client API.

This repository also includes:
- a comprehensive pytest suite (unit + live-on-panel tests)
- example programs for discovery, linking, connecting, event monitoring, and basic API usage
- ADRs and protocol notes used to guide implementation

---

## What this library does

### Core capabilities
- **Discovery**: Find E27 panels on the LAN and return identity details (panel name, MAC, serial, host/port, etc.).
- **Linking (provisioning)**: Perform the E27 *API_LINK* flow to obtain long-lived link keys (encryption + HMAC keys) used to establish trusted sessions.
- **Session establishment**: Connect to a panel, perform HELLO + session bootstrap, and transition to a ready state.
- **Event-driven updates**: Receive unsolicited panel messages and dispatch them as structured events.
- **Command execution**: Send API requests and receive responses using a strict one-in-flight model (request/response sequencing).
- **Snapshots**: Provide read-only state “snapshots” for Home Assistant (or other clients) to read stable views of current panel state.

### Stable public surface for Home Assistant
Home Assistant is intended to import and use **only** the public client API defined in:

- `docs/CLIENT_CONTRACT.md`

As described there:
- Home Assistant imports only:
  - `from elke27_lib.client import Elke27Client, Result`
- Home Assistant must **not** import internal modules (session, dispatcher, features, handlers, etc.).
- The contract is treated as stable during refactors.

If you are building a Home Assistant integration, start by reading:
- `docs/CLIENT_CONTRACT.md`
- `docs/PERMISSIONS.md`
- `docs/adr/*`

---

## High-level architecture (mental model)

### 1) Discovery
Discovery is used to locate panels and present them to the user by **panel name**, while binding identity definitively by **MAC address**.

Implementation entry points:
- `elke27_lib.discovery`
- `Elk.discover()` (facade used in examples)

### 2) Linking (API_LINK provisioning)
Linking is a provisioning-time operation that produces long-lived keys. These keys are persisted externally (for example, by Home Assistant) and reused on subsequent connections.

Implementation entry points:
- `Elke27Client.async_link(...)`
- `Elk.link(...)` (facade used in examples)

### 3) Session connect + readiness
Connecting establishes a framed/encrypted session, performs session bootstrap, and transitions the client to “ready”.

Per the client contract, readiness is defined by:
- Session ACTIVE, AND
- `panel_info.session_id` present, AND
- `table_info` present

Implementation entry points:
- `Elke27Client.async_connect(host, port, link_keys)`
- `Elke27Client.wait_ready(timeout_s=...)`

### 4) Features (domain APIs)
The library exposes “feature” modules (domains) that implement E27 API handlers such as:
- areas, zones, outputs, thermostats, keypads, control/system, network parameters, rules, logs, users, etc.

These are internal to the library; Home Assistant should not import them directly and should rely on the client contract and snapshots/events.

---

## Installation / Development setup

The project is packaged via `pyproject.toml` and requires Python >=3.11.

Typical development setup (example):
- create a virtual environment
- install with development extras
- run pytest

(Exact tooling choice is up to you; the repository includes standard pyproject-based metadata and pytest configuration.)

---

## Example programs

Examples live under `examples/` and are intended to be runnable against a real panel on your LAN.

### Environment setup (required)

Before running any example programs **or live tests**, you should:

1. Edit the file:
   - `elk-e27-env-vars.sh`

2. Set the appropriate values for your environment, such as:
   - panel host / port
   - access code
   - passphrase
   - optional identity fields

3. Source the file into your shell:
   - `source elk-e27-env-vars.sh`

This ensures all required environment variables are defined consistently for
example programs and pytest live tests.

### 1) Discover panels (no linking, no connect)
- `examples/e27_aioscanner.py`
  - Scans the LAN and prints discovered panels.

### 2) Provisioning (link only)
- `examples/e27_api_link.py`
  - Performs API_LINK and prints the resulting link credentials.
  - Does not start a full session or send operational requests.

### 3) Minimal “hello world” connect + version info
- `examples/e27_simple_program.py`
  - Discover → link → connect → request `control.get_version_info` → pump events until results arrive.

### 4) Monitor unsolicited messages/events
- `examples/e27_unsolicited_monitor.py`
  - Link → connect → print unsolicited messages/events.

### 5) Client contract examples (Home Assistant–style usage)
- `examples/e27_client_contract.py`
- `examples/e27_client_contract_example.py`
  - Demonstrate the “stable client contract” flow:
    - create client → connect → wait_ready → subscribe → receive event → read a snapshot

### 6) Network parameter example with authorization retry
- `examples/e27_network_param_live.py`
  - Demonstrates a privileged call path that may require PIN authorization.

### 7) Live version info printout
- `examples/e27_live_version_info.py`
  - End-to-end link/connect/version info with PanelState printing.

### Common environment variables used by examples
Examples rely on environment variables typically defined via
`elk-e27-env-vars.sh`, including:
- `ELKE27_HOST`, `ELKE27_PORT`
- `ELKE27_ACCESS_CODE`, `ELKE27_PASSPHRASE`
- Identity fields (optional): `ELKE27_MN`, `ELKE27_SN`, `ELKE27_FWVER`,
  `ELKE27_HWVER`, `ELKE27_OSVER`

Many examples also accept command-line arguments (for example, `--host`,
`--port`) which override environment defaults.

---

## Tests

Tests live under `test/` and are split into:
- **unit tests** (run without a live panel)
- **live tests** (require a real E27 panel and credentials)

### Running unit tests
Unit tests should run with a normal pytest invocation.

### Running live tests
Live tests are gated and will skip unless enabled. In addition to sourcing
`elk-e27-env-vars.sh`, live tests must be explicitly enabled via environment
configuration.

If required environment values are missing, tests are skipped with a message
indicating what is needed.

### Test artifacts / reporting
The test harness supports writing artifacts for each pytest invocation, typically
in JSONL and optionally YAML.

Relevant pytest options:
- `--e27-report` : `jsonl` (default), `yaml`, `both`, or `none`
- `--e27-artifacts-dir` : output directory (default: `artifacts/test_runs`)

You can also set:
- `ELK_E27_REPORT_FORMAT`
- `ELK_E27_ARTIFACTS_DIR`

Artifacts are designed to support debugging and regression tracking across
protocol changes.

### Notable test coverage areas
The test suite includes coverage for:
- framing and presentation layer behavior
- sequence handling and request/response correlation
- bootstrap readiness
- configured inventory enumeration
- paging behavior and dispatcher correctness
- keepalive and reconnect-adjacent behaviors
- permissions and authorization flows (including live tests)

---

## Documentation

Key documents:
- `docs/CLIENT_CONTRACT.md` — the stable Home Assistant–facing API contract
- `docs/PERMISSIONS.md` — permission and authorization semantics
- `docs/adr/` — architecture decision records guiding behavior and boundaries

If you are working on a Home Assistant integration:
- follow the import boundary rules in `CLIENT_CONTRACT.md`
- prefer consuming snapshots and events rather than internal protocol details

---

## Notes for Home Assistant integration authors

- This library is event-driven and designed for a “hub” style Home Assistant
  integration.
- Linking keys are long-lived and should be persisted by Home Assistant.
- Session keys and `session_id` are ephemeral and should not be persisted.
- Privileged authorization is temporary (vendor-defined behavior); Home Assistant
  should be prepared to re-authorize as needed and should not assume privilege
  persists indefinitely.
- Request concurrency should remain conservative (one request at a time per
  panel session) to avoid exhausting panel resources.

---

## Repository layout (high level)

- `src/elke27_lib/` — library implementation
- `docs/` — client contract, permissions, and ADRs
- `examples/` — runnable sample programs
- `test/` — pytest suite (unit + live)

---

## Support / Contributing

- Keep Home Assistant–facing changes aligned with `docs/CLIENT_CONTRACT.md`.
- Prefer small, testable changes.
- When adding new feature coverage, consider:
  - unit tests for parsing, dispatch, and mapping
  - live tests for end-to-end behavior (when hardware is available)
  - updating documentation or ADRs if behavior changes

---

* * *

## Project Docs

For how to install uv and Python, see [installation.md](docs/installation.md).

For development workflows, see [development.md](docs/development.md).

For instructions on publishing to PyPI, see [publishing.md](docs/publishing.md).

* * *

*This project was built from
[simple-modern-uv](https://github.com/jlevy/simple-modern-uv).*
