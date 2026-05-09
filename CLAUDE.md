# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the App

```bash
cd ~/Coding/LoadTest
python api.py
```

Server runs on `http://localhost:8000`. `index.html` is served at the root. Requires Python 3.10+.

## Architecture

This is a **SCADA (Supervisory Control and Data Acquisition) simulator** for electrical substation equipment. It models power flow through a network of connected devices using phasor mathematics and records field measurement sessions against named tests.

### Backend (`api.py` + `phasors/`)

`api.py` is a single-file HTTP server (`http.server.BaseHTTPRequestHandler`). Key endpoints:

| Endpoint | Purpose |
|---|---|
| `GET /api/topology` | Load `substation.json`, propagate power flow, return nodes/edges |
| `GET /api/toggle/<name>` | Open/close a breaker or disconnect |
| `POST /api/reconfigure` | Device CRUD, connection edits, measurement recording, snapshots |
| `GET /api/sites` | List all site DBs |
| `POST /api/sites/create` | Create a new site DB |
| `POST /api/sites/load` | Activate a site; loads its latest topology into `substation.json` |
| `GET /api/tests` | List tests for active site |
| `POST /api/tests/create` | Create a named test |
| `POST /api/tests/drawings/add` | Add a drawing reference to a test |
| `GET /api/db/sessions` | List measurement sessions |
| `POST /api/db/sessions` | Start a new session (technician + test_id) |

**Power flow model:** Devices propagate voltage and current upstream→downstream via Python properties. Each device walks `upstream_device` to find its source. `VoltageSource` only provides current when `is_circuit_closed()` confirms a complete path to a `Load`.

**Device hierarchy:**
- `Bus` — base class; holds `connections[]` and `upstream_device`
- `VoltageSource(Bus)` — infinite source; detects open circuits
- `CircuitBreaker`, `Disconnect` — switching devices; block propagation when open
- `PowerTransformer` — scales voltage/current between HV (H-bushing) and LV (X-bushing) sides
- `CurrentTransformer` — sensor device attached to a bushing
- `PowerLine`, `Load`, `Bus` — passive devices
- `Relay`, `CTTB` — protection devices with `secondary_connections`

`DeviceFactory.create_device(data)` in `phasors/devices/factory.py` is the single entry point for deserializing `substation.json` into device objects.

**Phasor math** (`phasors/`): Voltages and currents are 3-phase wye systems (`wye_voltages`, `wye_currents`) of `VoltagePhasor`/`CurrentPhasor` objects (magnitude + angle). `PowerPhasor` holds complex power (S = V × I*).

### Persistence

**Working file:** `substation.json` — active topology for the current session. Loaded from / saved back to the active site DB. Devices stored as a flat list; connections reference device IDs. Switch state (`OPEN`/`CLOSED`) persisted on toggle.

**Site databases:** `site_db.py` manages per-site SQLite files in `sites/`. UUID primary keys allow offline copies to be merged without ID conflicts. Schema migrates automatically when an older DB is opened.

**Data hierarchy:**
```
Site DB  (sites/ALZ.db)
 ├── site_info       station code, full name, ladder code, number code, GPS
 ├── tests           named test, description, created_by, status
 │    └── test_drawings  title, URL, revision, notes
 └── sessions        technician, instrument, test_id FK
      └── measurements  device_id, key, value, epoch
```

Snapshots (full topology captures) are stored per-site DB and are independent of tests.

### Frontend (`static/` + `index.html`)

| File | Purpose |
|---|---|
| `api-client.js` | All fetch calls to the backend |
| `visualization.js` | Renders the one-line diagram (3LD) on SVG via D3 |
| `ui.js` | Device info windows, measurement wizard, PLUG telemetry sequence |
| `sites.js` | Site selector modal (list, create, load) |
| `tests.js` | Test manager modal + `pickTest()` used by wizard and PLUG sequence |
| `splash.js` | Splash screen; shows site selector on first load |
| `utils.js` | Shared helpers |

**Measurement wizard flow:**
1. Step 0 — technician name (required; remembered for session)
2. Test picker — attach session to an existing test or create one inline (skippable)
3. Step 1 — select devices to measure
4. Step 2 — enter phase measurements; SAVE ALL records to active session

`static/graph.py` and `static/power_utilities.py` are matplotlib utilities for offline phasor visualization (not used by the web server).
