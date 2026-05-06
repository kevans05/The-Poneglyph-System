# Advanced Network Analysis & Load-Tester
### SCADA Pro Console — Field Protection Test Platform

A browser-based SCADA simulator and field measurement platform for electrical substation equipment. It combines a live power-flow model of a substation with tools for recording, organising, and analysing real-world protection relay test measurements taken in the field.

---

## Table of Contents

1. [Overview](#overview)
2. [Getting Started](#getting-started)
3. [Core Concepts](#core-concepts)
4. [Site Management](#site-management)
5. [Test Management](#test-management)
6. [The One-Line Diagram](#the-one-line-diagram)
7. [Measurement Workflow](#measurement-workflow)
8. [Hardware Power Meters](#hardware-power-meters)
9. [Field Report](#field-report)
10. [History & Snapshots](#history--snapshots)
11. [Database Architecture](#database-architecture)
12. [API Reference](#api-reference)
13. [File Structure](#file-structure)
14. [Power Flow Model](#power-flow-model)
15. [Phasor Mathematics](#phasor-mathematics)

---

## Overview

This tool was built to solve a real problem: running protection relay load tests on high-voltage transmission lines between substations — proving that relay analogs (current transformer ratios, voltage transformer ratios, wiring polarity) match the design intent before energising equipment. Field work happens in remote locations with no internet, multiple engineers working simultaneously, and a need to compare live measurements against engineering drawings.

The system does three things:

1. **Simulates** the substation topology — a mathematical model of transformers, circuit breakers, disconnects, current transformers, voltage transformers, relays, and loads. Power flows through the network in real time; you can open and close breakers and watch voltage and current re-propagate.

2. **Records** field measurements against that model — taking readings from handheld power meters (or entering them manually), attaching them to named tests with drawing references, and attributing every session to the technician who took it.

3. **Analyses** the measurements — comparing them against the model's predictions, flagging deviations, and producing a structured field report.

---

## Getting Started

**Requirements:** Python 3.10 or later. No external Python packages are required — the server uses only the standard library.

```bash
cd ~/Coding/LoadTest
python api.py
```

Open a browser and navigate to `http://localhost:8000`.

On first load, the splash screen appears for three seconds and then the **Site Selector** opens automatically. You must load or create a site before the main diagram is accessible.

---

## Core Concepts

The data model has four levels of hierarchy:

```
Site  (one SQLite database file per physical substation)
 └── Test  (a named test campaign, e.g. "500kV Protection Analog Proof")
      ├── Drawings  (engineering drawing references with URL and revision)
      └── Session  (one instrument connection / measurement run, attributed to a technician)
           └── Measurements  (individual phase readings: voltage, current, angle)
```

Additionally, each site holds **Snapshots** — complete captures of the substation topology at a point in time, independent of any test.

A **substation.json** working file sits alongside the database. It holds the active topology (device list, connections, switch states) and is loaded from and saved back to the site database.

---

## Site Management

Sites are accessed via the **`SITE: ___`** badge in the top-left of the header (red when no site is loaded, green when active) or the site selector that appears on startup.

### Creating a New Site

Click **+ NEW SITE** in the site selector. The form requires:

| Field | Description |
|---|---|
| **Station Code** | Short uppercase identifier used as the database filename (e.g. `ALZ`). Alphanumeric, hyphens, underscores only. |
| **Site Number Code** | Asset management or work-order reference (e.g. `SS-2847`). |
| **Site Name** | Full descriptive name (e.g. `Alhambra Zone 230kV Substation`). |
| **Site Ladder Code** | Drawing ladder reference code (e.g. `LDR-01`). |
| **Description** | Optional free-text notes. |
| **GPS Location** | Latitude and longitude. Enter manually or click **▶ USE MY LOCATION** to request the browser's geolocation API. Accuracy is shown in metres after acquisition. |
| **Seed with current topology** | If checked, copies the current `substation.json` into the new site as its initial snapshot. Useful when building a new site from an existing template. |

The site database is created immediately at `sites/<STATION_CODE>.db`.

### Loading a Site

Click any row in the site list and then **LOAD SITE**. The server:
1. Sets the site as active.
2. Loads the site's most recent snapshot into `substation.json`.
3. Returns site metadata to the browser, which updates the green badge and refreshes the diagram.

If the site has no snapshots (brand new), a blank topology is written instead.

### Site Database Files

Each site is a self-contained SQLite file in the `sites/` directory. Files can be:
- **Copied** to a laptop for offline field use.
- **Shared** between engineers — UUID primary keys mean two independent copies of the same site DB can be merged by inserting rows from one into the other with no ID conflicts.
- **Backed up** by simply copying the `.db` file.

---

## Test Management

Click the **TESTS** button (green, in the header) to open the test manager.

### What Is a Test?

A test represents a named campaign of work — for example *"500kV Line Protection Analog Proof — ALZ to XYZ"*. A test groups together:
- A set of **engineering drawings** that define the expected wiring and ratios.
- All **measurement sessions** taken as part of that campaign.

Tests have a status: **IN PROGRESS**, **COMPLETE**, or **ARCHIVED**. Archived tests are hidden from the session picker.

### Creating a Test

Click **+ NEW TEST**. Enter:
- **Test Name** (required) — descriptive title, e.g. *500kV Protection Analog Proof — ALZ to XYZ*.
- **Description** — objective, scope, or method notes.
- **Created By** — pre-filled from the remembered technician name.

### Test Detail View

Click any test in the list to open its detail view. This shows:

#### Drawings & References Table

Each row represents one engineering document used to design the test. Columns:

| Column | Description |
|---|---|
| **Drawing / Title** | Drawing number or descriptive title (e.g. `25B1 Protection Schematic`). Optional notes below. |
| **Rev** | Revision identifier (e.g. `Rev C`, `4`, `2024-01-15`). Shown in amber. |
| **URL / Reference** | Clickable hyperlink to the document management system, shared drive, or file server path. |

Click **+ ADD** to log a new drawing. Both **Title** and **Revision** are required. The URL field accepts any string — HTTP links open in a new tab; file paths can be copied manually.

#### Sessions List

All measurement sessions attached to this test are listed with the date/time, technician name, instrument type, and reading count.

#### Status Management

The dropdown in the detail header lets you change the test status inline. Changing to ARCHIVED hides the test from the session picker but preserves all data.

---

## The One-Line Diagram

The main canvas shows a **Single-Line Diagram (SLD)** — also called a one-line or three-line diagram (3LD) depending on context. This is the standard representation used in electrical engineering to show how equipment is connected.

### Device Symbols

Each device type has a distinct visual symbol:

| Device | Symbol |
|---|---|
| **Circuit Breaker (CB)** | Rectangle with a horizontal line. Dashed when OPEN, solid when CLOSED. |
| **Disconnect (DS)** | Rectangle with a diagonal slash indicating isolation. |
| **Power Transformer (TX)** | Two circles side by side representing primary and secondary coils. |
| **Current Transformer (CT)** | Three concentric circles, one per phase (red / yellow / blue), each with a semicircle arc. |
| **Voltage Transformer (VT)** | Three phase circles with a small filled disc below each. |
| **Relay (RLY)** | Dark rectangle with green border; function code shown in green (e.g. `87` for differential, `21` for distance). |
| **CTTB** | Gold rectangle labelled `CTTB` with terminal connection ports. |
| **Load** | Circle with dark fill. |
| **Bus / VoltageSource** | Circle with dark fill and grey border. |

### Navigation

- **Pan** — click and drag on empty canvas.
- **Zoom** — mouse wheel or trackpad pinch.
- **Click a device** — opens an information window showing all calculated phasor values for that device.
- **Right-click** — context menu for connection mode and device options.

### Device Information Windows

Clicking a device opens a floating draggable window showing:
- Calculated voltages (kV, per phase, angle in degrees)
- Calculated currents (A, per phase, angle in degrees)
- Power (MVA, MW, MVAR)
- Manual measurements (if recorded)
- Device parameters (ratio, CT class, etc.)

Multiple windows can be open simultaneously. Windows update automatically when **RESCAN BUS** is clicked or a measurement is recorded.

### Reference Angle

The status bar at the top shows the current reference phasor. When a reference device and phase are set (via **PROJECT SETUP**), all angles on the diagram are displayed relative to that reference — making phase comparisons straightforward.

---

## Measurement Workflow

### Step 1 — Identify Technician

When you click **FIELD METERS** (or **[ Initialize P.L.U.G. Telemetry ]**), the first screen asks for your **full name**. This name is attached to the session and all measurements recorded during it.

The name is remembered for the rest of the browser session — subsequent opens pre-fill it. You can change it by editing the field.

### Step 2 — Attach to a Test

After entering your name, the **ATTACH TO TEST** picker opens. This lists all active (non-archived) tests for the current site. Options:

- **Select an existing test** — click a row to highlight it, then **ATTACH TO TEST →**.
- **+ CREATE NEW TEST** — enter a name and description inline; creates the test and immediately attaches the session to it.
- **SKIP** — session is not linked to any test (measurements are still recorded).

### Step 3 — Select Devices (Field Meters)

The wizard shows a filterable list of all devices in the current topology. Devices are grouped by type:
- ALL / RELAYS / CT / VT / CTTB / BREAKERS / SOURCES

Check one or more devices, then click **NEXT →**.

### Step 4 — Enter Measurements

For each selected device, a measurement table shows:

| Column | Description |
|---|---|
| **Label** | Measurement name (Phase A Voltage, Phase A I-Angle, etc.) |
| **PRED** | Predicted value from the power-flow model (blue) |
| **MEAS (A/B/C)** | Input fields for measured values from your meter |

The **360° LAG** toggle switches the prediction between leading and lagging conventions — useful when CT polarity is reversed or the wiring follows a lagging reference.

Click **SAVE ALL** to record all entered values. They are:
1. Written into `substation.json` under the device's `manual_measurements` field (so they appear on the diagram).
2. Written to the site database in the `measurements` table, linked to the current session.

### P.L.U.G. Telemetry (Hardware Meters)

The **[ Initialize P.L.U.G. Telemetry ]** button starts a hardware-connected measurement session. After the technician name and test picker:

1. **Select Instrument** — choose from PMM1 (serial), PMM2 (Ethernet), or Simulator.
2. **Configure Channels** — assign input channels to voltage and current phases.
3. **Live Readings** — the console streams live readings from the meter.
4. **Single-Injection Mode (SI)** — for single-phase injection testing, select the injected phase; the system applies the correct geometric correction to predict what the other phases should read.

---

## Hardware Power Meters

### Megger PMM-1 (Serial)

- **Connection:** RS-232 serial, 19200 baud, 8-N-1, 9-pin connector.
- **Protocol:** Semicolon-terminated ASCII commands.
- **Channels:** 0–8 (Van, Vbn, Vcn, Vab, Vbc, Vca, Ia, Ib, Ic).
- **Platform:** Windows (`COM1`, `COM2`, …), Linux/Raspberry Pi (`/dev/ttyUSB0`, `/dev/ttyAMA0`, `/dev/ttyACM0`).
- **Configure:** Select port from the detected list; set channel 1 (voltage) and channel 2 (current).

### Megger PMM-2 (Ethernet)

- **Connection:** TCP/IP, default port 5025.
- **Protocol:** RTS ASCII command interface.
- **Voltage ranges:** 2 V, 10 V, 100 V, 200 V, 500 V, 1000 V (6 ranges).
- **Current channels 1–3:** 1 A, 5 A, 10 A, 20 A, 50 A, 100 A, CT (7 ranges).
- **Current channel 4:** 0.002 A, 0.005 A, 0.05 A, 0.2 A, 1 A, 5 A, 30 A (7 ranges).
- **Configure:** Enter IP address; select channel assignments.

### Simulation Driver

A built-in mock driver that generates realistic 60 Hz three-phase power measurements with random jitter. Used for:
- Development and testing without hardware.
- Demonstrating the system to engineers before field deployment.
- Training new technicians on the workflow.

Simulated channels return: voltage (kV), current (A), real power (W), reactive power (var), apparent power (VA), phase angle (degrees), and frequency (Hz).

---

## Field Report

Click **FIELD REPORT** in the header to open the measurement analysis report.

The report processes every device that has manual measurements recorded and produces:

### Per-Device Analysis

For each measured device:
- **PRED column** — the value predicted by the power-flow model.
- **MEAS column** — the field-recorded value.
- **Δ column** — absolute difference.
- **% column** — percentage deviation.
- **STATUS badge** — `PASS` (green), `WARNING` (amber), or `FAULT` (red) based on deviation thresholds.

### Sanity Checks

In addition to direct comparison, the report runs cross-checks:
- Current transformer ratios (nameplate vs. measured)
- Phase angle consistency (are all three phases ~120° apart?)
- Power factor range (is it within expected bounds?)
- Polarity checks (are secondary currents in the correct direction?)

### Overall Assessment

A summary verdict at the top of the report:
- **PASS** — all checks within tolerance.
- **WARNING** — one or more checks outside preferred range but within limits.
- **FAULT** — one or more checks outside acceptable limits.

The report includes a count of total checks, passed, warnings, and faults.

### Export

**EXPORT CSV** downloads the full report as a comma-separated file for import into Excel or a test management system.

---

## History & Snapshots

Click **HISTORY** in the header to manage topology snapshots.

A snapshot is a complete capture of `substation.json` at a point in time — every device, its parameters, connections, and switch states. Snapshots are stored in the active site database.

### Taking a Snapshot

Click **+ TAKE NEW SNAPSHOT**. Enter a label; the system prefixes it automatically with `YYYYMMDD-STATION-DEVICE-`. Snapshots are a good practice at:
- The start of each test session (baseline state).
- After any switching operation.
- At the end of the day (final as-left state).

### Comparing Snapshots

Click **COMPARE** next to any snapshot. The diagram loads the historical topology and highlights differences against the current state — useful for seeing what changed between sessions or verifying a fault was cleared.

### Deleting Snapshots

Click **DELETE** next to a snapshot. This removes only the topology record; measurement sessions and their data are not affected.

---

## Database Architecture

Each site is a self-contained SQLite database at `sites/<STATION_CODE>.db`.

### Tables

#### `site_info`
One row per database. Stores the site's identity.

| Column | Type | Description |
|---|---|---|
| `id` | INTEGER | Always 1 (single-row sentinel) |
| `station` | TEXT | Short station code (e.g. `ALZ`) |
| `site_name` | TEXT | Full site name |
| `description` | TEXT | Free-text notes |
| `leader_code` | TEXT | Site ladder code |
| `number_code` | TEXT | Site number code |
| `gps_lat` | REAL | Latitude (decimal degrees) |
| `gps_lon` | REAL | Longitude (decimal degrees) |
| `created_epoch` | INTEGER | Unix timestamp of creation |
| `last_epoch` | INTEGER | Unix timestamp of last activity |

#### `tests`
Named test campaigns.

| Column | Type | Description |
|---|---|---|
| `id` | TEXT | UUID |
| `epoch` | INTEGER | Unix timestamp |
| `name` | TEXT | Test name |
| `description` | TEXT | Objective / scope |
| `created_by` | TEXT | Technician who created the test |
| `status` | TEXT | `IN PROGRESS` / `COMPLETE` / `ARCHIVED` |

#### `test_drawings`
Engineering drawing references linked to a test.

| Column | Type | Description |
|---|---|---|
| `id` | TEXT | UUID |
| `test_id` | TEXT | FK → `tests.id` (CASCADE DELETE) |
| `title` | TEXT | Drawing number or title |
| `url` | TEXT | URL or file path |
| `revision` | TEXT | Revision identifier (e.g. `Rev C`) |
| `notes` | TEXT | Optional notes |

#### `snapshots`
Full topology captures.

| Column | Type | Description |
|---|---|---|
| `id` | TEXT | UUID |
| `epoch` | INTEGER | Unix timestamp |
| `label` | TEXT | User-assigned label |
| `topology` | TEXT | Full `substation.json` JSON blob |

#### `sessions`
One row per instrument connection / measurement run.

| Column | Type | Description |
|---|---|---|
| `id` | TEXT | UUID |
| `epoch` | INTEGER | Unix timestamp |
| `label` | TEXT | Auto-generated timestamp label |
| `device` | TEXT | Device under test (from project info) |
| `instrument` | TEXT | `manual` / `pmm1` / `pmm2` / `sim` |
| `technician` | TEXT | Full name of the engineer |
| `test_id` | TEXT | FK → `tests.id` (nullable) |
| `snapshot_id` | TEXT | FK → `snapshots.id` (nullable) |

#### `measurements`
Individual phase readings.

| Column | Type | Description |
|---|---|---|
| `id` | TEXT | UUID |
| `session_id` | TEXT | FK → `sessions.id` (CASCADE DELETE) |
| `epoch` | INTEGER | Unix timestamp of reading |
| `device_id` | TEXT | Device ID (e.g. `Relay-649`) |
| `key` | TEXT | Measurement key (e.g. `Phase A Current`) |
| `value` | REAL | Numeric value in engineering units |

### Schema Migration

The `_init()` function in `site_db.py` runs automatically every time a database is opened. It applies a migrations list that adds any new columns introduced since the database was created — using `ALTER TABLE ADD COLUMN`. This means older databases are upgraded transparently without any manual action.

### Offline Use & Merging

Because every primary key is a UUID, two engineers can each take a copy of `ALZ.db` into the field, work independently, and later merge their data by copying rows from one database into the other. No ID collisions are possible.

---

## API Reference

All endpoints are served by `api.py` on port 8000. All POST endpoints accept and return JSON. All responses include `Access-Control-Allow-Origin: *`.

### Sites

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/sites` | List all site databases with metadata |
| `GET` | `/api/sites/active` | Return active site info or `{"active": false}` |
| `POST` | `/api/sites/create` | Create a new site DB. Body: `station`, `site_name`, `leader_code`, `number_code`, `description`, `gps_lat`, `gps_lon`, `seed_current` |
| `POST` | `/api/sites/load` | Activate a site and load its topology. Body: `station` |

### Tests

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/tests` | List all tests for the active site |
| `GET` | `/api/tests/<id>` | Get test detail with drawings and sessions |
| `POST` | `/api/tests/create` | Create a test. Body: `name`, `description`, `created_by` |
| `POST` | `/api/tests/delete` | Delete a test. Body: `id` |
| `POST` | `/api/tests/status` | Update test status. Body: `id`, `status` |
| `POST` | `/api/tests/drawings/add` | Add a drawing. Body: `test_id`, `title`, `url`, `revision`, `notes` |
| `POST` | `/api/tests/drawings/delete` | Remove a drawing. Body: `id` |

### Topology

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/topology` | Load `substation.json`, run power flow, return nodes/edges/reference |
| `GET` | `/api/toggle/<name>` | Toggle a breaker or disconnect open/closed |
| `POST` | `/api/reconfigure` | Device and topology mutations (see actions below) |

**`/api/reconfigure` actions:**

| `action` | Description |
|---|---|
| `update_device` | Update device parameters |
| `update_position` | Move a device on the canvas (`gx`, `gy`) |
| `update_rotation` | Rotate a device symbol |
| `add_device` | Insert a new device |
| `delete_device` | Remove a device and clean up its connections |
| `add_connection` | Add a primary connection between devices |
| `add_secondary_connection` | Add a protection/secondary connection |
| `record_measurement` | Save field measurements to device and database |
| `create_snapshot` | Capture the current topology as a snapshot |
| `update_project_info` | Set station name and device under test |
| `set_reference` | Set the phasor reference device and phase |

### Database

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/db/snapshots` | List snapshots for active site |
| `GET` | `/api/db/snapshots/<id>` | Load and render a snapshot topology |
| `POST` | `/api/db/snapshots/delete` | Delete a snapshot. Body: `id` |
| `GET` | `/api/db/sessions` | List sessions for active site |
| `POST` | `/api/db/sessions` | Start a new session. Body: `label`, `device`, `instrument`, `technician`, `test_id` |
| `POST` | `/api/db/sessions/delete` | Delete a session. Body: `id` |
| `GET` | `/api/db/sessions/<id>/measurements` | Get all measurements for a session |
| `GET` | `/api/db/history/<device_id>/<key>` | Time-series for one device+key across all sessions (max 200 readings) |

### Power Meters

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/pmm/ports` | List available serial ports |
| `GET` | `/api/pmm/status` | Connection state and model |
| `GET` | `/api/pmm/query` | Read current measurements from connected meter |
| `POST` | `/api/pmm/connect` | Connect to a meter. Body: `port`, `model` (`pmm1`/`pmm2`/`sim`) |
| `POST` | `/api/pmm/configure` | Set channel assignments. Body: `chan1`, `chan2` |
| `POST` | `/api/pmm/disconnect` | Disconnect from meter |

---

## File Structure

```
LoadTest/
├── api.py                   # HTTP server — all endpoints, request routing
├── site_db.py               # Per-site SQLite persistence (UUID-keyed)
├── substation.json          # Active working topology (loaded from site DB)
├── CLAUDE.md                # Architecture notes for Claude Code
├── README.md                # This file
│
├── phasors/                 # Power-flow model and phasor mathematics
│   ├── __init__.py
│   ├── current_phasor.py    # CurrentPhasor (magnitude + angle)
│   ├── voltage_phasor.py    # VoltagePhasor (magnitude + angle)
│   ├── power_phasor.py      # PowerPhasor (complex power S = V × I*)
│   ├── wye_system.py        # 3-phase wye connection model
│   ├── delta_system.py      # 3-phase delta connection model
│   ├── phasor_operations.py # Arithmetic and multiplier constants
│   └── devices/
│       ├── factory.py       # DeviceFactory — deserialises substation.json
│       ├── bus.py           # Bus base class
│       ├── source_load.py   # VoltageSource, Load, PowerLine
│       ├── switching.py     # CircuitBreaker, Disconnect
│       ├── transformers.py  # PowerTransformer (HV/LV bushings)
│       ├── sensors.py       # CurrentTransformer, VoltageTransformer, CTTB, Relay
│       └── protection.py    # Protection logic
│
├── power_meters/            # Hardware instrument drivers
│   ├── __init__.py          # Module API (api_connect, api_query, etc.)
│   ├── pmm1_interface.py    # Megger PMM-1 RS-232 serial driver
│   ├── pmm2_interface.py    # Megger PMM-2 Ethernet/TCP driver
│   └── sim_driver.py        # Simulation driver (60 Hz, random jitter)
│
├── sites/                   # Per-site SQLite databases (created at runtime)
│   └── <STATION>.db
│
└── static/                  # Browser frontend
    ├── api-client.js        # All fetch() calls to the backend
    ├── visualization.js     # D3.js SVG one-line diagram renderer
    ├── ui.js                # Device windows, measurement wizard, PLUG sequence, reports
    ├── sites.js             # Site selector modal
    ├── tests.js             # Test manager modal and session test picker
    ├── splash.js            # Splash screen and startup flow
    ├── utils.js             # SI formatting, grid snap, units map, type abbreviations
    └── styles.css           # All styles (dark terminal theme)
```

---

## Power Flow Model

The model is a directed graph of device objects. Power flows **upstream → downstream** — from `VoltageSource` through breakers, disconnects, transformers, and buses to `Load` devices.

### How Propagation Works

Each device exposes `voltage` and `current` as computed properties. When accessed, a device walks its `upstream_device` pointer until it reaches a `VoltageSource` (or an open switch). The source multiplies its nominal values through each transformer ratio it encounters on the way.

A `VoltageSource` only provides current if `is_circuit_closed()` returns `True` — which requires tracing a complete path from source to a `Load` without crossing any open switches. If the path is broken, voltage is present at the source side of the open device but current drops to zero downstream.

### PowerTransformer Bushings

Transformers connect via named bushings:
- **H-bushing** — high-voltage primary side.
- **X-bushing** — low-voltage secondary side.

Connections in `substation.json` use `{"id": "...", "via_bushing": "H"}` notation. This lets the loader correctly identify which side of the transformer is upstream.

### Current Transformers

CTs are modelled as sensors: they have an `upstream_device` (the primary conductor they are mounted on) and apply their `ratio` (e.g. `2000:1`) to report a scaled secondary current. The `location` field in `substation.json` identifies which device they are mounted on.

---

## Phasor Mathematics

All voltages and currents are represented as **three-phase wye systems** at the device level.

A `WyeSystem` holds three `VoltagePhasor` or `CurrentPhasor` objects — one per phase (A, B, C). Each phasor has a `magnitude` (in volts or amps) and an `angle` (in degrees).

`PowerPhasor` computes complex power: **S = V × I\*** where I\* is the complex conjugate of current. This gives:
- **P** (real power, watts) = |V| × |I| × cos(θ)
- **Q** (reactive power, vars) = |V| × |I| × sin(θ)
- **S** (apparent power, VA) = √(P² + Q²)

The reference angle feature subtracts a chosen phasor's angle from all other angles before display — setting one phase of one device to 0° and showing everything else relative to it. This is the standard convention in relay test work.

### Units Displayed

| Quantity | Unit |
|---|---|
| Voltage (transmission) | kV |
| Voltage (secondary) | V |
| Current (primary) | A (kA for fault levels) |
| Current (CT secondary) | A |
| Power | MVA / MW / MVAR |
| Angle | degrees (°) |
| Frequency | Hz |
