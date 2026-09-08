# The Poneglyph System
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

1. **Models** the substation topology — a mathematical model of transformers, circuit breakers, disconnects, current transformers, voltage transformers, relays, and loads. Power flows through the network via a steady-state power-flow solve; you can open and close breakers and watch voltage and current re-propagate.

2. **Records** field measurements against that model — taking readings from handheld power meters (or entering them manually), attaching them to named tests with drawing references, and attributing every session to the technician who took it.

3. **Analyses** the measurements — comparing them against the model's predictions, flagging deviations, and producing a structured field report exportable as XLSX.

---

## Getting Started

**Requirements:** Python 3.10 or later. External dependencies are listed in `requirements.txt` (`openpyxl` for Excel reports).

```bash
pip install -r requirements.txt
python api.py
```

Open a browser and navigate to `http://localhost:8000`.

Configuration is controlled via environment variables (see `config.py`):

| Variable | Default | Description |
|---|---|---|
| `PONEGLYPH_HOST` | `0.0.0.0` | Bind address |
| `PONEGLYPH_PORT` | `8000` | HTTP port |

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

##### 🔍 Search Corporate Drawings

Both the test-level and per-device drawing forms have a **🔍 SEARCH CORPORATE DRAWINGS**
button. It queries the corporate drawing system through the `drawing_search`
package and lets you pick a result to auto-fill title / revision / URL / notes.

Smart defaults, all editable:

- **Facility** is pre-filled from the loaded **site** (`number_code`, falling back
  to the station code).
- **Drawing Type** / **Subject** are pre-selected from the device type
  (a relay → Electrical · Protection & Control, a meter → Electrical · Metering, …).

Configure it in **⚙ SETTINGS → DRAWING SEARCH**: set the **Drawing Search URL**,
**Drawing Download URL**, and **Cache Refresh (hrs)**, then either

- **🔑 Grab via Windows Auth** — on Windows, pulls session cookies for the
  current domain account via PowerShell `Invoke-WebRequest -UseDefaultCredentials`
  (no password prompt), or
- paste cookies into `~/.poneglyph_drawing_search.json` yourself:
  ```json
  { "base_url": "https://drawings.example.com",
    "download_url": "https://drawings.example.com",
    "cache_refresh_hours": 4,
    "cookies": { "filenet-es": "…", "_WL_AUTHCOOKIE_filenet-es": "…" } }
  ```

**🔄 Fetch Drawing Options** pulls the facility / type / subject dropdown values
from the live form. Environment variables `PONEGLYPH_DWG_BASE_URL`,
`PONEGLYPH_DWG_DOWNLOAD_URL`, `PONEGLYPH_DWG_COOKIES`, `PONEGLYPH_DWG_CACHE_HOURS`
also work and fill any gap left by the file. Results are cached in SQLite and
re-fetched after *Cache Refresh* hours.

#### Sessions List

All measurement sessions attached to this test are listed with the date/time, technician name, instrument type, and reading count.

#### Status Management

The dropdown in the detail header lets you change the test status inline. Changing to ARCHIVED hides the test from the session picker but preserves all data.

### XLSX Report

Each test can export a structured load-test report via **↓ DOWNLOAD EXCEL**. The report is generated from `excel_report.py` using a template at `templates/load_test_template.xlsx`, with one block per device: label, Measured Secondary (fill this in by hand), Predicted Secondary, and Measured Primary.

**↑ UPLOAD EXCEL** reads the Measured Secondary values back in. It validates the whole file before writing anything — a renamed sheet, a corrupt workbook, or a file with no usable values all fail cleanly with no session created, instead of leaving a partial or empty one behind. Device names are checked against the currently loaded substation; a block whose name doesn't match anything (a typo, a renamed device) is skipped and reported, while every other device in the same file still imports. The result — what was imported, what was skipped and why, any unmatched device names — is shown in full rather than a single pass/fail alert, and re-selecting the same file after a failed attempt just works (no page reload needed).

### 🔍 Audit

Click **🔍 AUDIT** in a test's detail view to review its recorded results rather
than just list them. All the math (`test_audit.py`, `GET /api/tests/<id>/audit`)
runs server-side and is presentation-only on the client:

- **RESULTS** — every recorded value, grouped by device and session, with a
  **◈ PHASOR DIAGRAM** button per row.
- **NEUTRALS** — the phasor (vector) sum of each device's three measured phases,
  which should be near zero on a healthy, balanced circuit. Where a Neutral
  value was also measured directly, it's checked against the computed one.
  Graded ok (<5%) / caution (5–10%) / review (≥10%) against the average phase
  magnitude.
- **CHAIN** — for every device fed by others through the secondary wiring (CT →
  CTTB → Relay, etc.), the expected value is the polarity-weighted vector sum
  of what its inputs recorded in the same session — the same summation /
  differential math the relay itself performs — checked against what the
  downstream device actually recorded.
- **COMPARE** — pick any two recorded sets (the same device across two
  sessions, or two devices that should agree) for a side-by-side delta table
  and an overlaid phasor diagram.

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
- **Click a device** — opens an information window showing its state and configuration.
- **Right-click** — context menu for connection mode and device options.

### Device Information Windows

Clicking a device opens a floating draggable window showing:
- Device state (status, connection, tap position, winding config, …)
- Protection input sources and polarity (for relays / CTTBs)
- Manual measurements (if recorded)
- Device parameters (ratio, CT class, etc.)
- Per-device drawing references and analog history

Multiple windows can be open simultaneously. Windows update automatically when **RESCAN BUS** is clicked or a measurement is recorded.

> The computed per-phase phasor telemetry and polar phasor diagrams were removed
> along with the simulation engine. The power-flow model still runs server-side
> for source-sync-conflict detection and report predictions.

---

## Measurement Workflow

The field model this is built around: one probe stays on a fixed voltage
reference for the whole session; the other probe — current or voltage — is
the one that actually moves, point to point (CTTB, VT terminal blocks, iso
blocks, analog relay terminals). Digital relays aren't probed at all; you
read a number off the front-panel display and key it in. All of that is done
in Class 0 gloves, so the interface is built around large targets and as
little typing as the meter allows — not around a touchscreen.

### Starting a session

Open **TESTS**, pick a test, and click **▶ START MEASUREMENTS**. You're asked
for your name once (remembered on this device, and — if a hub is connected —
suggested from everyone signed in on it too); the test's capture points are
pre-loaded, so there's usually nothing left to pick before choosing an
instrument.

### One reading screen for every instrument

PMM-1 (Web Serial), PMM-2 (network), and manual entry are the same operation
with a different source for the number — so they're one screen, not three:

- **Live meter connected** (PMM-1 or PMM-2): **▶ QUERY METER** fills in
  MAG / ANG with zero typing; **✓ ACCEPT & LOG POINT** saves it and moves on.
- **✎ ENTER THIS ONE BY HAND** — available at any point in a live session,
  for anything a meter can't read (a digital relay's own display). It hands
  just that one reading to manual entry without disconnecting the meter or
  losing your place; the next point goes back to the meter automatically.
- Manual entry (by session choice, or the per-point override above) uses a
  large on-screen number pad — built for a gloved hand clicking with a
  mouse, not for precise physical-keyboard presses.
- Logging a point auto-advances: next phase, then the next device, in order.
  A failed save shows an error in place rather than failing silently.

The **360° LAG** toggle switches the reference-panel prediction between
leading and lagging conventions — useful when CT polarity is reversed or the
wiring follows a lagging reference. **SHORT & ISOLATE (S&I)** walks through
single-phase-injection testing, reconfiguring the meter's channel for the
injected phase and predicting what the other two phases should read.

---

## Hardware Power Meters

### Megger PMM-1 (Web Serial)

- **Connection:** RS-232, 19200 baud, 8-N-1, 9-pin connector — opened directly in the browser via the [Web Serial API](https://developer.mozilla.org/en-US/docs/Web/API/Web_Serial_API) (`static/pmm-webserial.js`). No backend serial access is used.
- **Requirements:** a Chromium-based browser (Chrome/Edge) served over HTTPS or `http://localhost`.
- **Protocol:** Semicolon-terminated ASCII commands.
- **Channels:** 0–8 (Van, Vbn, Vcn, Vab, Vbc, Vca, Ia, Ib, Ic).
- **Configure:** Press **SELECT PORT** and pick the USB-serial adapter in the browser prompt; set channel 1 (voltage) and channel 2 (current).

### Megger PMM-2 (Ethernet)

- **Connection:** TCP/IP, default port 5025.
- **Protocol:** RTS ASCII command interface.
- **Voltage ranges:** 2 V, 10 V, 100 V, 200 V, 500 V, 1000 V (6 ranges).
- **Current channels 1–3:** 1 A, 5 A, 10 A, 20 A, 50 A, 100 A, CT (7 ranges).
- **Current channel 4:** 0.002 A, 0.005 A, 0.05 A, 0.2 A, 1 A, 5 A, 30 A (7 ranges).
- **Configure:** Enter IP address; select channel assignments.

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

**EXPORT CSV** downloads the full report as a comma-separated file for import into Excel or a test management system. **EXPORT XLSX** produces a structured Excel workbook from the load-test template.

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

### Drawing revisions

Drawings attached from the corporate search carry their **drawing number**. On a
device drawing, **REVISIONS** lists every revision that number has on record
(`GET /api/drawings/revisions?number=…`, cached per site); clicking a sibling
swaps the attachment and logs the old revision. Test drawings show the same list
read-only — a test keeps the revision that was actually referenced in the field.

### Change signing

Every snapshot and per-device history row records the operator who made it
(`author` / `author_id`, the latter being the `PoneglyphIdentity` signature).
The browser registers the current operator with `POST /api/operator`; the
HISTORY list shows `◆ <name>` next to each snapshot.

---

## Poneglyph Hub (shared server)

The optional **hub** is a central server a whole team connects to. The desktop
app keeps working fully offline and syncs when a connection is available. Full
design: [`docs/poneglyph-hub.md`](docs/poneglyph-hub.md).

**Run the hub** (`hub/`):

```sh
cd hub
docker compose up -d --build
```

Open `http://<hub-host>:8900/` — first visit bootstraps an admin account (no
accounts exist yet). From its **USERS** tab, add one account per technician.
Then in the app: **⚙ SETTINGS → PONEGLYPH HUB** — set the hub URL and sign in
with those credentials. The bearer token is stored per-device and refreshed on
every sync.

### Roster-aware technician picker

Once connected, the "who are you" / "who's taking this reading" pickers show
everyone on the hub (`GET /api/hub/users` — display names only, no admin gate),
tagged with a small ☁, alongside this device's own local name history. Picking
a colleague's name works even if they've never touched this device before —
their signature stays whichever device is actually recording; only the
`technician` display name on that session changes. You can still type a
brand-new name that isn't a hub account at all.

### Hub admin GUI

`http://<hub-host>:8900/` is a small dashboard for running the hub itself:
**USERS** (add / disable / promote / reset password / delete — guarded so the
last admin can't be removed), **SUBSTATIONS** (every uploaded station, with an
expandable version history, and delete), **TESTS** (every published test, and
delete). Deleting or disabling a user never touches what they authored — it
just stops them signing in.

### Shared load tests

Publish a completed test from its detail view (**⇪ PUBLISH TO HUB**); pull other
technicians' tests from **☁ SHARED TESTS** in the Tests modal. Publishing is
idempotent by test id; pulled tests are read-only and badged **☁ SHARED**.
Endpoints: `GET /api/tests/<id>/bundle`, `POST /api/tests/import-bundle`.

### Shared substation model (branch & merge)

All of this lives in **Site Selection** (click the site indicator, or the
header) — there's no separate sync screen. Each local site's row shows its hub
state inline: **☁ synced**, **☁ n unpushed changes** (amber), or *not synced to
hub* with a **☁ LINK TO HUB** button. Clicking a linked site's **MANAGE** button
loads it and opens the full link / pull / push / conflict-resolution panel for
just that site.

Below your local sites, a **☁ ON THE HUB — NOT ON THIS MACHINE** section lists
substations that exist on the hub but have no local copy yet — check any number
of them and **⇩ PULL SELECTED →** creates and attaches each one in turn.
**☁ SYNC ALL LINKED SITES** in the footer pulls (and, where that's clean,
pushes) every locally-linked site one after another; anything that comes back
with conflicts is left for you to open and resolve individually.

Once linked, every topology change is recorded as a signed version. **PULL**
fast-forwards or runs a structural 3-way merge (`topo_merge.py`) — conflicts are
resolved device-by-field in the panel and written as a two-parent merge commit.
**PUSH** fast-forwards the hub head. The hub itself never merges; it only stores
and orders versions.
Endpoints: `GET /api/hub-sync/status`, `POST /api/hub-sync/{link,pull,resolve,push,unlink}`.

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
| `POST` | `/api/sites/update` | Patch editable `site_info` fields for the active site |

### Tests

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/tests` | List all tests for the active site |
| `GET` | `/api/tests/<id>` | Get test detail with drawings and sessions |
| `POST` | `/api/tests/create` | Create a test. Body: `name`, `description`, `created_by` |
| `POST` | `/api/tests/delete` | Delete a test. Body: `id` |
| `POST` | `/api/tests/status` | Update test status. Body: `id`, `status` |
| `POST` | `/api/tests/capture-points` | Save capture-point device list for a test. Body: `test_id`, `devices` |
| `POST` | `/api/tests/vref` | Store the reference VT for a test. Body: `test_id`, `vref_device_id` |
| `POST` | `/api/tests/drawings/add` | Add a drawing. Body: `test_id`, `title`, `url`, `revision`, `notes` |
| `POST` | `/api/tests/drawings/delete` | Remove a drawing. Body: `id` |
| `GET` | `/api/tests/<id>/devices` | Distinct device IDs that have measurements for a test |
| `GET` | `/api/tests/<id>/report-data` | Full measurement data for report rendering |
| `GET` | `/api/tests/<id>/audit` | Phasor sets, neutral/residual checks, and chain comparisons for the AUDIT view |
| `GET` | `/api/tests/<id>/report.xlsx` | Download the XLSX load-test report |
| `POST` | `/api/tests/ingest-report` | Import hand-entered measurements from an XLSX file. Validates before writing; returns `{imported, skipped, unknown_devices, measurement_count}` or a 400 with a clear error |

### Topology

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/topology` | Load `substation.json`, run power flow, return nodes/edges/reference |
| `GET` | `/api/topology/export` | Download the raw `substation.json` |
| `POST` | `/api/topology/import` | Replace the active topology from an uploaded JSON file |
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
| `rename_device` | Change a device ID everywhere (topology dict and all connection lists) |
| `add_connection` | Add a primary connection between devices |
| `add_secondary_connection` | Add a protection/secondary connection |
| `record_measurement` | Save field measurements to device and database |
| `create_snapshot` | Capture the current topology as a snapshot |
| `update_project_info` | Set station name and device under test |

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
| `GET` | `/api/db/device-config-history/<id>` | Per-device configuration and snapshot audit trail |

### Power Meters

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/pmm/status` | Connection state and model (PMM2) |
| `GET` | `/api/pmm/query` | Read current measurements from the connected PMM2 |
| `POST` | `/api/pmm/connect` | Connect to a PMM2. Body: `port` (IP, optionally `ip:port`), `model` (`pmm2`) |
| `POST` | `/api/pmm/configure` | Set channel assignments. Body: `chan1`, `chan2` |
| `POST` | `/api/pmm/disconnect` | Disconnect from meter |

> PMM1 is a serial instrument and is driven entirely in the browser over the Web Serial API — it does not use these endpoints.

### Corporate Drawing Search

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/drawing-search/config` | `{ configured, base_url, download_url, cache_refresh_hours, cookie_names, facility_default, type_hints }` |
| `POST` | `/api/drawing-search/config` | Save config. Body: `base_url`, `download_url`, `cache_refresh_hours` |
| `POST` | `/api/drawing-search/grab-cookies` | Grab session cookies via Windows Integrated Auth (Windows only) |
| `GET` | `/api/drawing-search/options` | Facility / drawing-type / drawing-subject code→label maps |
| `POST` | `/api/drawing-search/options/refresh` | Re-fetch the dropdown options from the live search form |
| `POST` | `/api/drawing-search` | Run a search. Body: `facility`, `drawing_type`, `drawing_subject`, `title`, `drawing_num`, `sheet_number`, `state`, `page` |

---

## File Structure

```
The-Poneglyph-System/
├── api.py                   # HTTP server — all endpoints, request routing
├── model_loader.py          # Shared logic for building the device graph from topology JSON
├── topology_utils.py        # Pure topology mutation helpers (add/delete/rename devices, etc.)
├── site_db.py               # Per-site SQLite persistence (UUID-keyed, auto-migrating)
├── excel_report.py          # XLSX load-test report builder and ingest
├── config.py                # Central configuration (host, port, paths)
├── redline_importer.py      # .wirePlan (Red-Line Routing) import + correlation
├── drawing_search_config.py # Glue: config + smart defaults for corporate drawing search
├── drawing_search/          # Corporate drawing-search client (search, cache, lookup tables)
├── substation.json          # Active working topology (loaded from site DB)
│
├── phasors/                 # Power-flow model and phasor mathematics
│   ├── __init__.py
│   ├── current_phasor.py    # CurrentPhasor (magnitude + angle)
│   ├── voltage_phasor.py    # VoltagePhasor (magnitude + angle)
│   ├── power_phasor.py      # PowerPhasor (complex power S = V × I*)
│   ├── wye_system.py        # 3-phase wye connection model
│   ├── delta_system.py      # 3-phase delta connection model
│   ├── phasor_operations.py # Arithmetic and multiplier constants
│   ├── utilities/
│   │   ├── formatter.py     # SI prefix formatting for display values
│   │   └── power_utilities.py
│   └── devices/
│       ├── factory.py       # DeviceFactory — deserialises substation.json
│       ├── bus.py           # Bus base class
│       ├── source_load.py   # VoltageSource, Load
│       ├── passive.py       # Passive network elements
│       ├── power_line.py    # PowerLine device
│       ├── switching.py     # CircuitBreaker, Disconnect
│       ├── transformers.py  # PowerTransformer (HV/LV bushings)
│       ├── regulator.py     # Voltage regulator
│       ├── sensors.py       # CurrentTransformer, VoltageTransformer, CTTB, Relay
│       ├── protection.py    # Protection logic
│       └── protection_elements.py  # Individual protection element models
│
├── power_meters/            # Hardware instrument drivers
│   ├── __init__.py          # Module API (api_connect, api_query, etc.)
│   └── pmm2_interface.py    # Megger PMM-2 Ethernet/TCP driver
│                            # (PMM-1 lives in static/pmm-webserial.js — Web Serial)
│
├── sites/                   # Per-site SQLite databases (created at runtime)
│   └── <STATION>.db
│
├── templates/               # Excel templates
│   └── load_test_template.xlsx
│
└── static/                  # Browser frontend
    ├── api-client.js        # All fetch() calls to the backend
    ├── visualization.js     # D3.js SVG one-line diagram renderer
    ├── windows.js           # Floating device information windows
    ├── panels.js            # Side-panel layout and tabbed content
    ├── device-ops.js        # Device add/edit/delete operations
    ├── measurement-wizard.js # Field measurement entry wizard and PLUG sequence
    ├── analog-history.js    # Analog trend history display
    ├── history-modal.js     # Snapshot history modal
    ├── protection-view.js   # Protection element status and single-injection view
    ├── relay-controls.js    # Relay trip/close DC output controls
    ├── tcc-plot.js          # Time-current characteristic coordination plot
    ├── pmm-webserial.js     # Megger PMM-1 driver over the Web Serial API
    ├── settings-modal.js    # Application settings (preferences + voltage-class palette)
    ├── config-modal.js      # Per-device configuration modal
    ├── context-menu.js      # Right-click context menu
    ├── selector.js          # Device selector / filter panel
    ├── dialogs.js           # Generic dialog helpers
    ├── serial-dialog.js     # Device asset serial-number dialog
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
