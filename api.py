"""
The Poneglyph System — HTTP API Server (api.py)

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
"""

import topology_utils
import sim_engine as _sim
from urllib.parse import urlparse, parse_qs
import json
import mimetypes
import os
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer

import excel_report as _xrep
import power_meters as _pmm
import site_db as _sdb
import model_loader

# In-memory substation topology.  Loaded from the active site DB on /api/sites/load
# and kept in sync by every /api/reconfigure call.  Persisted to the DB via _autosave().
_current_topology: dict | None = None

# Path to the active site's SQLite file (e.g. "sites/ALZ.db").
# None when no site has been loaded this session.
_active_site: str | None = None

# UUID of the most recently started measurement session.  Measurements recorded
# via record_measurement are tagged with this session so they appear together in
# the history view.
_active_session_id: str | None = None


def load_substation(data=None):
    """Load the substation model from provided data or the current in-memory topology."""
    if data is None: data = _current_topology
    if data is None: return [], {}, [], {}, {}
    devices = model_loader.load_substation_model(data)
    sources = [dev for dev in devices.values() if getattr(dev, "type", "") == "VoltageSource" or dev.__class__.__name__ == "VoltageSource"]
    return sources, devices, data.get("devices", []), data.get("reference", {}), data.get("project_info", {"station": "", "device": ""})

# Raw topology keys forwarded to the frontend as device.params.
# Only fields listed here are exposed — keeps the JSON payload small and
# prevents leaking internal computed state.
_PARAM_KEYS = [
    "nominal_voltage_kv",
    "nominal_power_mva",
    "pf",
    "continuous_amps",
    "interrupt_ka",
    "pri_kv",
    "sec_kv",
    "h_winding",
    "x_winding",
    "polarity_reversed",
    "load_mva",
    "ratio",
    "sec2_ratio",
    "bushing",
    "location",
    "position",
    "polarity_facing",
    "polarity_normal",
    "is_balanced",
    "is_single_pole",
    "output_manual_overrides",
    "dc_output_state_manual",
    "manual_closed_phases",
    "category",
    "target_dropped",
    "logic",
    "settings",
    "digital_inputs",
    "digital_outputs",
    "phase_va",
    "phase_pf",
    "mode",
    "secondary_wiring",
    "secondary2_wiring",
    "function",
    "tap_ratios",
    "selected_tap",
    "tap_configs",
    "selected_tap_index",
    "phase_shift_deg",
    "winding_type",
    "mvar_rating",
    "kv_rating",
    "impedance_ohm",
    "mvar_min",
    "mvar_max",
    "mvar_setting",
    "resistance_ohm",
    "carrier_frequency_hz",
    "input_polarities",
    "serial_number",   # physical asset serial; stored in topology JSON and tracked in device_serials table
    # VoltageRegulator
    "nominal_kv",
    "tap_pos",
    "step_percent",
    "max_steps",
    "avr_enabled",
    "avr_deadband_pct",
    "avr_delay_ms",
    # VoltageTransformer primary winding
    "primary_winding",
]


def _detect_sync_errors(sources, devices):
    """Find pairs of VoltageSource devices that are electrically connected
    through closed switches and have incompatible configurations."""
    if len(sources) < 2:
        return []

    def _is_open(dev):
        return hasattr(dev, "is_closed") and not dev.is_closed

    # Build undirected adjacency through closed-switch paths only.
    adj = {name: set() for name in devices}
    for name, dev in devices.items():
        for attr in ("connections", "h_connections", "x_connections"):
            for c in getattr(dev, attr, []):
                if c.name in adj and not _is_open(dev) and not _is_open(c):
                    adj[name].add(c.name)
                    adj[c.name].add(name)
        up = getattr(dev, "upstream_device", None)
        if up and up.name in adj and not _is_open(dev) and not _is_open(up):
            adj[name].add(up.name)
            adj[up.name].add(name)

    def get_component(start):
        visited, queue = set(), [start]
        while queue:
            n = queue.pop()
            if n in visited:
                continue
            visited.add(n)
            queue.extend(adj.get(n, set()) - visited)
        return visited

    errors = []
    checked = set()
    for i, s1 in enumerate(sources):
        comp = get_component(s1.name)
        for s2 in sources[i + 1 :]:
            key = (min(s1.name, s2.name), max(s1.name, s2.name))
            if key in checked or s2.name not in comp:
                continue
            checked.add(key)

            issues = []
            w1 = getattr(s1, "winding_type", "Y")
            w2 = getattr(s2, "winding_type", "Y")
            if w1 != w2:
                issues.append(f"Winding mismatch ({w1} vs {w2})")

            v1 = s1._voltage.a.magnitude if s1._voltage else 0
            v2 = s2._voltage.a.magnitude if s2._voltage else 0
            if v1 > 0 and v2 > 0:
                diff_pct = abs(v1 - v2) / max(v1, v2) * 100
                if diff_pct > 1.0:
                    issues.append(f"Voltage magnitude mismatch ({diff_pct:.1f}%)")

            a1 = s1._voltage.a.angle_degrees if s1._voltage else 0
            a2 = s2._voltage.a.angle_degrees if s2._voltage else 0
            angle_diff = abs(((a1 - a2) + 180) % 360 - 180)
            if angle_diff > 1.0:
                issues.append(f"Phase angle mismatch ({angle_diff:.1f}°)")

            if issues:
                errors.append({"sources": [s1.name, s2.name], "issues": issues})

    return errors


def _build_topology_response(sources, devices, raw_devices, reference):
    raw_map = {d["id"]: d for d in raw_devices}

    ref_angle = 0
    ref_dev_id = reference.get("device_id")
    ref_phase = reference.get("phase", "A")
    if ref_dev_id in devices:
        ref_summary = devices[ref_dev_id].get_summary_dict()
        target_key = f"Phase {ref_phase} V-Angle"
        if target_key in ref_summary:
            ref_angle = ref_summary[target_key]
        else:
            for k, v in ref_summary.items():
                if ref_phase in k and "Angle" in k and isinstance(v, (int, float)):
                    ref_angle = v
                    break

    sync_errors = _detect_sync_errors(sources, devices)
    source_error_map = {}
    for err in sync_errors:
        for sid in err["sources"]:
            source_error_map.setdefault(sid, []).append(err)

    nodes = []
    edges = []

    for did, dev in devices.items():
        summary = dev.get_summary_dict()

        if ref_angle != 0:
            for k, v in list(summary.items()):
                if "Angle" in k and isinstance(v, (int, float)):
                    summary[k] = (v - ref_angle + 180) % 360 - 180

        raw = raw_map.get(did, {})
        status = str(summary.get("Status", "UNKNOWN")).split(" ")[0]
        nodes.append(
            {
                "id": dev.name,
                "type": dev.__class__.__name__,
                "status": status,
                "summary": summary,
                "params": {k: raw[k] for k in _PARAM_KEYS if k in raw},
                "gx": getattr(dev, "gx", None),
                "gy": getattr(dev, "gy", None),
                "rotation": getattr(dev, "rotation", 0),
                "inputs": [inp.name for inp in getattr(dev, "inputs", [])],
                "sync_errors": source_error_map.get(dev.name, []),
            }
        )

    for did, dev in devices.items():
        if hasattr(dev, "h_connections"):
            for conn in dev.h_connections:
                edges.append(
                    {
                        "source": dev.name,
                        "target": conn.name,
                        "type": "primary",
                        "source_bushing": "H",
                    }
                )
        if hasattr(dev, "x_connections"):
            for conn in dev.x_connections:
                edges.append(
                    {
                        "source": dev.name,
                        "target": conn.name,
                        "type": "primary",
                        "source_bushing": "X",
                    }
                )
        if hasattr(dev, "downstream_device") and dev.downstream_device:
            bushing = None
            if (
                hasattr(dev, "h_connections")
                and dev.downstream_device in dev.h_connections
            ):
                bushing = "H"
            elif (
                hasattr(dev, "x_connections")
                and dev.downstream_device in dev.x_connections
            ):
                bushing = "X"
            if not any(
                e["source"] == dev.name and e["target"] == dev.downstream_device.name
                for e in edges
            ):
                edges.append(
                    {
                        "source": dev.name,
                        "target": dev.downstream_device.name,
                        "type": "primary",
                        "source_bushing": bushing,
                    }
                )
        if hasattr(dev, "connections"):
            for c in dev.connections:
                if not any(
                    e["source"] == dev.name and e["target"] == c.name for e in edges
                ):
                    edges.append(
                        {"source": dev.name, "target": c.name, "type": "primary"}
                    )
        if hasattr(dev, "secondary_connections"):
            for s in dev.secondary_connections:
                edges.append(
                    {"source": dev.name, "target": s.name, "type": "protection"}
                )
        if hasattr(dev, "secondary2_connections"):
            for s in dev.secondary2_connections:
                edges.append(
                    {"source": dev.name, "target": s.name, "type": "protection2"}
                )
        if hasattr(dev, "dc_output_conns"):
            for conn in dev.dc_output_conns:
                edges.append({
                    "source": dev.name,
                    "target": conn["device"].name,
                    "type": "dc",
                    "from_terminal": conn["from"],
                    "to_terminal": conn["to"]
                })
        if hasattr(dev, "trip_dc_inputs"):
            for s in dev.trip_dc_inputs:
                if not any(e["source"] == s.name and e["target"] == dev.name and e["type"] == "trip" for e in edges):
                    edges.append({"source": s.name, "target": dev.name, "type": "trip"})
        if hasattr(dev, "close_dc_inputs"):
            for s in dev.close_dc_inputs:
                if not any(e["source"] == s.name and e["target"] == dev.name and e["type"] == "close" for e in edges):
                    edges.append({"source": s.name, "target": dev.name, "type": "close"})

    return {
        "nodes": nodes,
        "edges": edges,
        "reference": reference,
        "sync_errors": sync_errors,
    }


def save_substation(devices, reference=None, label: str = "auto:toggle"):
    """Update the in-memory topology and persist it to the site DB."""
    global _current_topology
    if _current_topology is None:
        return

    data = _current_topology
    for d in data.get("devices", []):
        did = d["id"]
        if did in devices:
            dev = devices[did]
            if hasattr(dev, "is_closed"):
                d["status"] = "CLOSED" if dev.is_closed else "OPEN"
            if hasattr(dev, "output_manual_overrides"):
                d["output_manual_overrides"] = dev.output_manual_overrides
            # Switches use _manual_closed for their state persistence
            if hasattr(dev, "_manual_closed"):
                d["status"] = "CLOSED" if all(dev._manual_closed.values()) else "OPEN"
                d["manual_closed_phases"] = dev._manual_closed
            if hasattr(dev, "target_dropped"):
                d["target_dropped"] = dev.target_dropped

    if reference is not None:
        data["reference"] = reference

    _autosave(data, label=label)


def _autosave(data: dict, label: str = "auto"):
    """Save the current topology to the active site DB.

    Auto-saves run on every structural change, so we skip writing per-device
    history rows for them — `device_history` would otherwise grow by N rows
    per click. Explicit named snapshots still record the full per-device audit.
    """
    if _active_site:
        try:
            is_auto = label.startswith("auto")
            _sdb.save_snapshot(
                _active_site,
                label=label,
                topology=data,
                record_device_history=not is_auto,
            )
        except Exception:
            traceback.print_exc()


def _require_site(handler) -> bool:
    """Return True if an active site is set; otherwise send 409 and return False."""
    if _active_site:
        return True
    _json_response(handler, {"error": "No site loaded. Load a site first."}, 409)
    return False


def _json_response(handler, data, status=200):
    try:
        body = json.dumps(data).encode("utf-8")
        handler.send_response(status)
        handler.send_header("Content-type", "application/json")
        handler.send_header("Access-Control-Allow-Origin", "*")
        handler.end_headers()
        handler.wfile.write(body)
    except (BrokenPipeError, ConnectionResetError):
        pass # Client disconnected before response could be sent


class SCADAServer(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        global _active_site, _active_session_id, _current_topology
        try:
            content_length = int(self.headers["Content-Length"])
            post_data = self.rfile.read(content_length) if content_length > 0 else b'{}'
            req = json.loads(post_data) if post_data else {}
            # ── Simulation endpoints ──────────────────────────────────────────
            if self.path == "/api/sim/start":
                _sim.sim_engine.start(_current_topology)
                return _json_response(self, {"ok": True})
            if self.path == "/api/sim/stop":
                _sim.sim_engine.stop()
                return _json_response(self, {"ok": True})
            if self.path == "/api/sim/pause":
                _sim.sim_engine.pause(req.get("paused", True))
                return _json_response(self, {"ok": True})
            if self.path == "/api/sim/speed":
                _sim.sim_engine.set_speed(req.get("multiplier", 1.0))
                return _json_response(self, {"ok": True})
            if self.path == "/api/sim/fault":
                _sim.sim_engine.schedule_event(0, "FAULT", req)
                return _json_response(self, {"ok": True})
            if self.path == "/api/sim/clear_fault":
                _sim.sim_engine.schedule_event(0, "CLEAR_FAULT", req)
                return _json_response(self, {"ok": True})

            if self.path == "/api/sim/relay_settings":
                ok = _sim.sim_engine.update_relay_settings(
                    req.get("device_id", ""),
                    req.get("settings", {})
                )
                return _json_response(self, {"ok": ok})


            # ── PMM endpoints ──────────────────────────────────────────────────
            if self.path == "/api/pmm/connect":
                return _json_response(
                    self,
                    _pmm.api_connect(
                        port=req.get("port", ""),
                        model=req.get("model", "pmm1"),
                    ),
                )

            if self.path == "/api/pmm/configure":
                return _json_response(
                    self,
                    _pmm.api_configure(
                        chan1=int(req.get("chan1", 0)),
                        chan2=int(req.get("chan2", 6)),
                    ),
                )

            if self.path == "/api/pmm/disconnect":
                return _json_response(self, _pmm.api_disconnect())

            # ── Site management endpoints ──────────────────────────────────────
            if self.path == "/api/sites/create":
                station = req.get("station", "").strip().upper()
                if not station:
                    return _json_response(self, {"error": "station name required"}, 400)
                seed_topology = None
                if req.get("seed_current"):
                    seed_topology = _current_topology
                gps_lat = req.get("gps_lat")
                gps_lon = req.get("gps_lon")
                try:
                    path = _sdb.create_site(
                        station=station,
                        site_name=req.get("site_name", "").strip(),
                        description=req.get("description", "").strip(),
                        number_code=req.get("number_code", "").strip(),
                        gps_lat=float(gps_lat) if gps_lat is not None else None,
                        gps_lon=float(gps_lon) if gps_lon is not None else None,
                        topology=seed_topology,
                    )
                except FileExistsError:
                    return _json_response(
                        self, {"error": f"Site '{station}' already exists"}, 409
                    )
                return _json_response(
                    self, {"ok": True, "db_path": path, "station": station}
                )

            if self.path == "/api/sites/load":
                station = req.get("station", "").strip()
                db_path = _sdb.db_path_for(station)
                if not os.path.exists(db_path):
                    return _json_response(
                        self, {"error": f"Site '{station}' not found"}, 404
                    )
                _sdb.init_db(db_path)
                _active_site = db_path
                _active_session_id = None
                topology = _sdb.get_latest_topology(db_path)
                if topology:
                    topology.setdefault("project_info", {})
                    topology["project_info"]["station"] = station
                    _current_topology = topology
                else:
                    _current_topology = {
                        "devices": [],
                        "reference": {"device_id": None, "phase": None},
                        "project_info": {"station": station, "device": ""},
                    }
                info = _sdb.get_site_info(db_path)
                return _json_response(
                    self, {"ok": True, "station": station, "info": info}
                )

            # ── DB / session endpoints ─────────────────────────────────────────
            if self.path == "/api/tests/create":
                if not _require_site(self):
                    return
                test_id = _sdb.create_test(
                    _active_site,
                    name=req.get("name", "").strip(),
                    description=req.get("description", "").strip(),
                    created_by=req.get("created_by", "").strip(),
                )
                return _json_response(self, {"ok": True, "test_id": test_id})

            if self.path == "/api/tests/delete":
                if not _require_site(self):
                    return
                _sdb.delete_test(_active_site, req.get("id", ""))
                return _json_response(self, {"ok": True})

            if self.path == "/api/tests/status":
                if not _require_site(self):
                    return
                _sdb.update_test_status(
                    _active_site, req.get("id", ""), req.get("status", "IN PROGRESS")
                )
                return _json_response(self, {"ok": True})

            if self.path == "/api/tests/capture-points":
                if not _require_site(self):
                    return
                _sdb.update_test_capture_points(
                    _active_site, req.get("id", ""), req.get("devices", [])
                )
                return _json_response(self, {"ok": True})

            if self.path == "/api/tests/vref":
                if not _require_site(self):
                    return
                test_id = (req.get("test_id") or "").strip()
                if not test_id:
                    return _json_response(self, {"error": "missing test_id"}, 400)
                mag_raw = req.get("magnitude")
                magnitude = None
                if mag_raw not in (None, ""):
                    try:
                        magnitude = float(mag_raw)
                    except (TypeError, ValueError):
                        return _json_response(self, {"error": "magnitude must be numeric"}, 400)
                _sdb.set_test_vref(
                    _active_site, test_id,
                    (req.get("label") or "").strip(),
                    magnitude,
                )
                return _json_response(self, {"ok": True})

            if self.path == "/api/tests/drawings/add":
                if not _require_site(self):
                    return
                drawing_id = _sdb.add_drawing(
                    _active_site,
                    test_id=req.get("test_id", ""),
                    title=req.get("title", "").strip(),
                    url=req.get("url", "").strip(),
                    revision=req.get("revision", "").strip(),
                    notes=req.get("notes", "").strip(),
                )
                return _json_response(self, {"ok": True, "drawing_id": drawing_id})

            if self.path == "/api/tests/drawings/delete":
                if not _require_site(self):
                    return
                _sdb.delete_drawing(_active_site, req.get("id", ""))
                return _json_response(self, {"ok": True})

            if self.path == "/api/db/sessions":
                if not _require_site(self):
                    return
                _active_session_id = _sdb.start_session(
                    _active_site,
                    label=req.get("label", ""),
                    device=req.get("device", ""),
                    instrument=req.get("instrument", "manual"),
                    technician=req.get("technician", ""),
                    test_id=req.get("test_id"),
                    snapshot_id=req.get("snapshot_id"),
                )
                return _json_response(self, {"session_id": _active_session_id})

            if self.path == "/api/db/snapshots/delete":
                if not _require_site(self):
                    return
                _sdb.delete_snapshot(_active_site, req.get("id", ""))
                return _json_response(self, {"ok": True})

            if self.path == "/api/db/sessions/delete":
                if not _require_site(self):
                    return
                _sdb.delete_session(_active_site, req.get("id", ""))
                return _json_response(self, {"ok": True})

            if self.path == "/api/reconfigure":
                if _sim.sim_engine.running:
                    _sim.sim_engine.mutate(req)
                    return _json_response(self, {"ok": True})
                
                if _current_topology is None:
                    return _json_response(self, {"error": "No site loaded"}, 409)

                _current_topology = topology_utils.apply_reconfiguration(
                    _current_topology, req, _active_site, _active_session_id
                )
                if req.get("action") not in ["update_position", "update_rotation", "record_measurement"]:
                    _autosave(_current_topology, "reconfigure:" + req.get("action", "unknown"))
                return _json_response(self, {"ok": True})

            if self.path == "/api/topology/import":
                if not _require_site(self):
                    return
                # `req` was already JSON-parsed at the top of do_POST; if it's
                # a {"topology": {...}} envelope unwrap it, otherwise treat the
                # whole body as the topology payload.
                payload = req.get("topology") if isinstance(req, dict) and "topology" in req else req
                if not isinstance(payload, dict) or not isinstance(payload.get("devices"), list):
                    return _json_response(
                        self,
                        {"error": "Invalid topology: expected an object with a 'devices' list"},
                        400,
                    )
                payload.setdefault("reference", {"device_id": None, "phase": None})
                payload.setdefault("project_info", {"station": "", "device": ""})
                _current_topology = payload
                # Imports are user-initiated milestones — record per-device history.
                if _active_site:
                    try:
                        _sdb.save_snapshot(
                            _active_site,
                            label="Imported topology",
                            topology=_current_topology,
                            record_device_history=True,
                        )
                    except Exception:
                        traceback.print_exc()
                return _json_response(self, {"status": "success"})

            
            if self.path == "/api/tests/ingest-report":
                if not _require_site(self):
                    return
                test_id = req.get("test_id")
                b64_data = req.get("data") # Base64 encoded .xlsx
                if not test_id or not b64_data:
                    return _json_response(self, {"error": "test_id and data required"}, 400)
                
                import base64
                try:
                    xlsx_bytes = base64.b64decode(b64_data)
                    sess_id = _xrep.ingest_load_test_report(_active_site, test_id, xlsx_bytes)
                    return _json_response(self, {"ok": True, "session_id": sess_id})
                except Exception as e:
                    traceback.print_exc()
                    return _json_response(self, {"error": str(e)}, 500)

            if self.path == "/api/sites/update":
                if not _require_site(self):
                    return
                info = _sdb.update_site_info(_active_site, req or {})
                return _json_response(self, {"ok": True, "info": info})

            # Record a serial number or swap for a device.
            # Body: {device_id, serial, notes, technician, manufacturer,
            #        model_number, asset_tag, manufacture_date,
            #        installation_date, in_service_date, firmware_version, status}
            if self.path == "/api/db/serials/record":
                if not _require_site(self):
                    return
                device_id = req.get("device_id", "").strip()
                serial    = req.get("serial", "").strip()
                if not device_id or not serial:
                    return _json_response(self, {"error": "device_id and serial required"}, 400)
                row_id = _sdb.record_device_serial(
                    _active_site,
                    device_id=device_id,
                    serial=serial,
                    notes=req.get("notes", ""),
                    technician=req.get("technician", ""),
                    manufacturer=req.get("manufacturer", ""),
                    model_number=req.get("model_number", ""),
                    asset_tag=req.get("asset_tag", ""),
                    manufacture_date=req.get("manufacture_date", ""),
                    installation_date=req.get("installation_date", ""),
                    in_service_date=req.get("in_service_date", ""),
                    firmware_version=req.get("firmware_version", ""),
                    status=req.get("status", "active"),
                )
                # Also store the serial_number on the in-memory topology device so
                # it appears in the params panel and persists on the next snapshot.
                if _current_topology:
                    for d in _current_topology.get("devices", []):
                        if d["id"] == device_id:
                            d["serial_number"] = serial
                            break
                    _autosave(_current_topology, label=f"serial:{device_id}")
                return _json_response(self, {"ok": True, "id": row_id})

            # Update inventory fields on an existing serial row (does not create a new row).
            # Body: {id, ...fields}
            if self.path == "/api/db/serials/update":
                if not _require_site(self):
                    return
                row_id = req.get("id", "").strip()
                if not row_id:
                    return _json_response(self, {"error": "id required"}, 400)
                updated = _sdb.update_device_serial(_active_site, row_id, req)
                return _json_response(self, {"ok": updated})

            # Append a maintenance log entry for a device.
            # Body: {device_id, work_performed, serial, technician, notes}
            if self.path == "/api/db/maintenance/record":
                if not _require_site(self):
                    return
                device_id      = req.get("device_id", "").strip()
                work_performed = req.get("work_performed", "").strip()
                if not device_id or not work_performed:
                    return _json_response(
                        self, {"error": "device_id and work_performed required"}, 400
                    )
                row_id = _sdb.add_maintenance_log(
                    _active_site,
                    device_id=device_id,
                    work_performed=work_performed,
                    serial=req.get("serial", ""),
                    technician=req.get("technician", ""),
                    notes=req.get("notes", ""),
                )
                return _json_response(self, {"ok": True, "id": row_id})

            # Attach a drawing reference to a device.
            # Body: {device_id, title, url, revision, notes}
            if self.path == "/api/db/device-drawings/add":
                if not _require_site(self):
                    return
                device_id = req.get("device_id", "").strip()
                title     = req.get("title", "").strip()
                if not device_id or not title:
                    return _json_response(self, {"error": "device_id and title required"}, 400)
                row_id = _sdb.add_device_drawing(
                    _active_site,
                    device_id=device_id,
                    title=title,
                    url=req.get("url", ""),
                    revision=req.get("revision", ""),
                    notes=req.get("notes", ""),
                )
                return _json_response(self, {"ok": True, "id": row_id})

            # Remove a device drawing.
            # Body: {id}
            if self.path == "/api/db/device-drawings/delete":
                if not _require_site(self):
                    return
                _sdb.delete_device_drawing(_active_site, req.get("id", ""))
                return _json_response(self, {"ok": True})

            else:
                self.send_response(404)
                self.end_headers()
        except (BrokenPipeError, ConnectionResetError):
            pass # Client disconnected
        except Exception as e:
            traceback.print_exc()
            try:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(f"Server Error: {e}".encode("utf-8"))
            except (BrokenPipeError, ConnectionResetError):
                pass

    def do_GET(self):
        parsed_path = urlparse(self.path)
        path = parsed_path.path
        params = parse_qs(parsed_path.query)
        if path == "/api/sim/frames":
            since = int(params.get("since", [-1])[0])
            frames = _sim.sim_engine.get_frames(since)
            return _json_response(self, {
                "frames": frames, 
                "sim_time": _sim.sim_engine.sim_time_ms, 
                "running": _sim.sim_engine.running, 
                "paused": _sim.sim_engine.paused
            })

        try:
            # ── PMM GET endpoints ──────────────────────────────────────────────
            if self.path == "/api/pmm/ports":
                return _json_response(self, {"ports": _pmm.api_list_ports()})

            if self.path == "/api/pmm/status":
                return _json_response(self, _pmm.api_status())

            if self.path == "/api/pmm/query":
                return _json_response(self, _pmm.api_query())

            # ── Site endpoints ─────────────────────────────────────────────────
            if self.path == "/api/sites":
                return _json_response(self, {"sites": _sdb.list_sites()})

            if self.path == "/api/sites/active":
                if _active_site:
                    info = _sdb.get_site_info(_active_site)
                    return _json_response(self, {"active": True, "info": info})
                return _json_response(self, {"active": False})

            # ── Test GET endpoints ─────────────────────────────────────────────
            if self.path == "/api/tests":
                if not _require_site(self):
                    return
                return _json_response(self, {"tests": _sdb.list_tests(_active_site)})

            if self.path.startswith("/api/tests/") and self.path.endswith("/devices"):
                if not _require_site(self):
                    return
                test_id = self.path.split("/")[3]
                device_ids = _sdb.get_test_device_ids(_active_site, test_id)
                return _json_response(self, {"device_ids": device_ids})

            if self.path.startswith("/api/tests/") and self.path.endswith("/report-data"):
                if not _require_site(self):
                    return
                test_id = self.path.split("/")[3]
                report = _sdb.get_test_report_data(_active_site, test_id)
                if not report:
                    self.send_response(404)
                    self.end_headers()
                    return
                return _json_response(self, report)

            if self.path.startswith("/api/tests/") and "/report.xlsx" in self.path:
                if not _require_site(self):
                    return
                parts = self.path.split("/")
                test_id = parts[3]
                # Parse query for angle convention
                query = urlparse(self.path).query
                params = parse_qs(query)
                use360 = params.get("use360", ["true"])[0].lower() == "true"
                
                xlsx = _xrep.build_load_test_report(_active_site, test_id, use360=use360)
                if xlsx is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header(
                    "Content-Type",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
                self.send_header(
                    "Content-Disposition",
                    f'attachment; filename="load_test_{test_id}.xlsx"',
                )
                self.send_header("Content-Length", str(len(xlsx)))
                self.end_headers()
                self.wfile.write(xlsx)
                return

            if self.path.startswith("/api/tests/") and not any(
                self.path.startswith(p)
                for p in (
                    "/api/tests/create",
                    "/api/tests/delete",
                    "/api/tests/status",
                    "/api/tests/drawings",
                )
            ):
                if not _require_site(self):
                    return
                test_id = self.path.split("/")[3]
                test = _sdb.get_test(_active_site, test_id)
                if test is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                drawings = _sdb.list_drawings(_active_site, test_id)
                sessions = _sdb.list_sessions(_active_site, test_id=test_id)
                return _json_response(
                    self, {"test": test, "drawings": drawings, "sessions": sessions}
                )

            # ── DB GET endpoints ───────────────────────────────────────────────
            if self.path == "/api/db/snapshots":
                if not _require_site(self):
                    return
                return _json_response(
                    self, {"snapshots": _sdb.list_snapshots(_active_site)}
                )

            if self.path.startswith("/api/db/snapshots/"):
                if not _require_site(self):
                    return
                snap_id = self.path.split("/")[-1]
                topology = _sdb.get_snapshot_topology(_active_site, snap_id)
                if topology is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                sources, devices, raw_devices, reference, _ = load_substation(
                    data=topology
                )
                return _json_response(
                    self,
                    _build_topology_response(sources, devices, raw_devices, reference),
                )

            if self.path == "/api/db/sessions":
                if not _require_site(self):
                    return
                return _json_response(
                    self, {"sessions": _sdb.list_sessions(_active_site)}
                )

            if (
                self.path.startswith("/api/db/sessions/")
                and "/measurements" in self.path
            ):
                if not _require_site(self):
                    return
                sess_id = self.path.split("/")[4]
                sess = _sdb.get_session(_active_site, sess_id)
                by_device = _sdb.get_session_measurements(_active_site, sess_id)
                return _json_response(self, {"session": sess, "by_device": by_device})

            if self.path.startswith("/api/db/history/"):
                if not _require_site(self):
                    return
                parts = self.path.split("/")
                device_id = parts[4] if len(parts) > 4 else ""
                key = "/".join(parts[5:]) if len(parts) > 5 else ""
                return _json_response(
                    self,
                    {"history": _sdb.get_device_history(_active_site, device_id, key)},
                )

            if self.path.startswith("/api/db/device-config-history/"):
                if not _require_site(self):
                    return
                device_id = self.path.split("/", 4)[-1]
                rows = _sdb.get_device_config_history(_active_site, device_id)
                # Decode the stored JSON config blob so the client gets an object.
                for r in rows:
                    cfg = r.get("config")
                    if isinstance(cfg, str):
                        try:
                            r["config"] = json.loads(cfg)
                        except Exception:
                            pass
                return _json_response(self, {"history": rows})

            # Serial number + inventory history for a device
            # GET /api/db/serials/<device_id>
            if self.path.startswith("/api/db/serials/"):
                if not _require_site(self):
                    return
                device_id = self.path.split("/", 4)[-1]
                rows = _sdb.get_device_serials(_active_site, device_id)
                latest = _sdb.get_latest_serial(_active_site, device_id)
                return _json_response(self, {"serials": rows, "current": latest})

            # Maintenance log for a device
            # GET /api/db/maintenance/<device_id>
            if self.path.startswith("/api/db/maintenance/"):
                if not _require_site(self):
                    return
                device_id = self.path.split("/", 4)[-1]
                rows = _sdb.get_maintenance_log(_active_site, device_id)
                return _json_response(self, {"maintenance": rows})

            # Drawings attached to a device
            # GET /api/db/device-drawings/<device_id>
            if self.path.startswith("/api/db/device-drawings/"):
                if not _require_site(self):
                    return
                device_id = self.path.split("/", 4)[-1]
                rows = _sdb.list_device_drawings(_active_site, device_id)
                return _json_response(self, {"drawings": rows})

            if self.path == "/api/topology":
                sources, devices, raw_devices, reference, project_info = (
                    load_substation()
                )
                resp = _build_topology_response(
                    sources, devices, raw_devices, reference
                )
                resp["project_info"] = project_info
                resp["site"] = (
                    _sdb.get_site_info(_active_site) if _active_site else None
                )
                return _json_response(self, resp)

            if self.path == "/api/topology/export":
                if _current_topology is None:
                    return _json_response(self, {"error": "No topology loaded"}, 404)
                body = json.dumps(_current_topology, indent=2).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-type", "application/json")
                self.send_header(
                    "Content-Disposition", 'attachment; filename="substation.json"'
                )
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)
                return

            if self.path.startswith("/api/toggle/"):
                _, devices, _, _, _ = load_substation()
                device_name = self.path.split("/")[-1].replace("%20", " ")
                toggled = False
                if device_name in devices:
                    dev = devices[device_name]
                    if hasattr(dev, "open"):
                        if dev.is_closed:
                            dev.open()
                        else:
                            dev.close()
                        save_substation(devices, label=f"auto:toggle:{device_name}")
                        toggled = True
                    elif node_type := getattr(dev, "type", None) or dev.__class__.__name__:
                        if node_type == "Relay":
                            # For Relay, toggle the TRIP manual override
                            current_trip = dev.output_manual_overrides.get("TRIP", False)
                            dev.output_manual_overrides["TRIP"] = not current_trip
                            save_substation(devices, label=f"auto:toggle:{device_name}")
                            toggled = True
                if toggled:
                    return _json_response(self, {"status": "toggled"})
                else:
                    self.send_response(404)
                    self.end_headers()
            elif self.path == "/mobile":
                with open("mobile.html", "rb") as f:
                    self.send_response(200)
                    self.send_header("Content-type", "text/html")
                    self.end_headers()
                    self.wfile.write(f.read())
            elif self.path == "/" or self.path == "/index.html":
                with open("index.html", "rb") as f:
                    self.send_response(200)
                    self.send_header("Content-type", "text/html")
                    self.end_headers()
                    self.wfile.write(f.read())
            elif self.path.startswith("/static/"):
                local_path = self.path.split("?")[0].lstrip("/")
                if os.path.exists(local_path) and os.path.isfile(local_path):
                    content_type, _ = mimetypes.guess_type(local_path)
                    with open(local_path, "rb") as f:
                        self.send_response(200)
                        self.send_header(
                            "Content-type", content_type or "application/octet-stream"
                        )
                        self.end_headers()
                        self.wfile.write(f.read())
                else:
                    self.send_response(404)
                    self.end_headers()
            elif self.path == "/favicon.ico":
                self.send_response(404)
                self.end_headers()
            else:
                self.send_response(404)
                self.end_headers()
        except (BrokenPipeError, ConnectionResetError):
            pass # Client disconnected
        except Exception as e:
            traceback.print_exc()
            try:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(f"Server Error: {e}".encode("utf-8"))
            except (BrokenPipeError, ConnectionResetError):
                pass

    def log_message(self, format, *args):
        pass  # suppress per-request console noise


if __name__ == "__main__":
    httpd = HTTPServer(("0.0.0.0", 8000), SCADAServer)
    print("SCADA Server on port 8000")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.server_close()
