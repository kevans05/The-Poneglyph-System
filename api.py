"""The Poneglyph System — HTTP API Server (api.py)

Single-file Python HTTP server built on stdlib http.server.  Every REST
endpoint lives in do_GET / do_POST on SCADAServer.  No framework required.

Concurrency model: single-threaded.  All state is in module-level globals
(_current_topology, _active_site, _active_session_id).  This is safe because
CPython's GIL means only one request runs at a time, and the sim_engine
mutates topology in a dedicated thread via sim_engine.mutate().

Endpoint summary
----------------
GET  /api/topology                    — computed power-flow topology
GET  /api/topology/export             — raw substation JSON download
POST /api/topology/import             — replace topology from JSON upload
GET  /api/toggle/<device>             — open/close a breaker or disconnect
POST /api/reconfigure                 — apply a topology mutation (add/delete/move/etc.)
GET  /api/sites                       — list all site databases
POST /api/sites/create                — create a new site DB
POST /api/sites/load                  — activate a site and load its latest topology
GET  /api/sites/active                — info about the currently active site
POST /api/sites/update                — patch editable site_info fields
GET  /api/tests                       — list all tests for active site
POST /api/tests/create                — create a new test
POST /api/tests/delete                — delete a test and all its sessions
POST /api/tests/status                — update test status (IN PROGRESS / COMPLETE / ARCHIVED)
POST /api/tests/capture-points        — save capture-point device list for a test
POST /api/tests/vref                  — store the reference VT for a test
POST /api/tests/drawings/add          — attach a drawing to a test
POST /api/tests/drawings/delete       — remove a drawing
GET  /api/tests/<id>/devices          — distinct device IDs with measurements for a test
GET  /api/tests/<id>/report-data      — full measurement data for report rendering
GET  /api/tests/<id>/report.xlsx      — download XLSX load-test report
POST /api/tests/ingest-report         — import hand-entered measurements from XLSX
GET  /api/db/snapshots                — list topology snapshots
GET  /api/db/snapshots/<id>           — computed topology at a snapshot
POST /api/db/snapshots/delete         — delete a snapshot
GET  /api/db/sessions                 — list all measurement sessions
POST /api/db/sessions                 — start a new measurement session
POST /api/db/sessions/delete          — delete a session and its measurements
GET  /api/db/sessions/<id>/measurements — all measurements for a session
GET  /api/db/history/<device>/<key>   — time-series measurements for one analog key
GET  /api/db/device-config-history/<id> — per-device config/snapshot audit trail
POST /api/pmm/connect                 — connect to power meter (pmm1 / pmm2 / sim)
POST /api/pmm/configure               — set channel assignments on connected meter
POST /api/pmm/disconnect              — disconnect from meter
GET  /api/pmm/ports                   — list available serial ports
GET  /api/pmm/status                  — meter connection status
GET  /api/pmm/query                   — read one set of phasor measurements
POST /api/sim/start                   — start physics simulation engine
POST /api/sim/stop                    — stop simulation engine
POST /api/sim/pause                   — pause / resume simulation
POST /api/sim/speed                   — set simulation time multiplier
POST /api/sim/fault                   — schedule a fault event
POST /api/sim/clear_fault             — clear an active fault
GET  /api/sim/frames                  — poll simulation animation frames
POST /api/redline/import              — import a .wirePlan JSON into the active site DB
POST /api/redline/rollback            — remove tracking rows for one import (soft rollback)
POST /api/redline/rollback-full       — remove tracking rows AND all content rows (full rollback)
GET  /api/redline/imports             — list all wirePlan imports for the active site
GET  /api/redline/imports/<id>/links  — all correlation links from one import
GET  /api/redline/imports/<id>/explain — human-readable audit report for one import
GET  /api/redline/device-links/<id>   — all wirePlan links pointing at a topology device
"""