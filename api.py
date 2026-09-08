"""The Poneglyph System — HTTP API Server (api.py)

Single-file Python HTTP server built on stdlib http.server.  Every REST
endpoint lives in do_GET / do_POST on SCADAServer.  No framework required.

Concurrency model: single-threaded.  All state is in module-level globals
(_current_topology, _active_site, _active_session_id).  This is safe because
CPython's GIL means only one request runs at a time.

Endpoint summary
----------------
GET  /api/whoami                      — OS login name, for pre-filling the operator identity
POST /api/operator                    — register the current operator (name + signature id) for change attribution
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
GET  /api/tests/<id>/bundle           — self-contained test bundle for hub publish
POST /api/tests/import-bundle         — insert a test bundle pulled from the hub
GET  /api/hub-sync/status             — substation link state (linked / ahead / pending conflicts)
POST /api/hub-sync/link              — create-on-hub or attach-to-hub the active substation
POST /api/hub-sync/pull             — pull hub versions; fast-forward or structural 3-way merge
POST /api/hub-sync/resolve          — apply conflict resolutions from a pull that needed them
POST /api/hub-sync/push            — fast-forward the hub head with local commits
POST /api/hub-sync/unlink         — drop the hub link (keeps local version history)
POST /api/tests/vref                  — store the reference VT for a test
POST /api/tests/drawings/add          — attach a drawing to a test
POST /api/tests/drawings/delete       — remove a drawing
GET  /api/tests/<id>/devices          — distinct device IDs with measurements for a test
GET  /api/tests/<id>/report-data      — full measurement data for report rendering
GET  /api/tests/<id>/audit            — phasor sets, neutral/residual checks, chain comparisons
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
GET  /api/drawings/revisions?number=<n>&refresh=<0|1> — sibling revisions of a drawing number (cached per site)
POST /api/pmm/connect                 — connect to power meter (pmm2 TCP/IP only; PMM1 is Web Serial in-browser)
POST /api/pmm/configure               — set channel assignments on connected meter
POST /api/pmm/disconnect              — disconnect from meter
GET  /api/pmm/status                  — meter connection status
GET  /api/pmm/query                   — read one set of phasor measurements
POST /api/redline/import              — import a .wirePlan JSON into the active site DB
POST /api/redline/rollback            — remove tracking rows for one import (soft rollback)
POST /api/redline/rollback-full       — remove tracking rows AND all content rows (full rollback)
GET  /api/redline/imports             — list all wirePlan imports for the active site
GET  /api/redline/imports/<id>/links  — all correlation links from one import
GET  /api/redline/imports/<id>/explain — human-readable audit report for one import
GET  /api/redline/device-links/<id>   — all wirePlan links pointing at a topology device
"""

import topology_utils
from urllib.parse import urlparse, parse_qs, quote as _urlquote
import urllib.request
import urllib.error
import json
import mimetypes
import os
import re
import time
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer

import getpass
import config as _cfg
import excel_report as _xrep
import power_meters as _pmm
import site_db as _sdb
import topo_merge as _merge
import test_audit as _audit
import model_loader
import redline_importer as _rl
import drawing_search_config as _dwg

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

# The operator currently at the controls, pushed by the browser after the
# identity prompt (POST /api/operator).  Used to sign topology snapshots and
# per-device history rows so layout changes are attributable.
_current_operator: dict = {"name": "", "id": ""}

# Set while a hub pull produced conflicts the operator still has to resolve.
# {"merged": dict, "conflicts": list, "base_id": str, "ours_head": str, "theirs_head": str}
_pending_merge: dict | None = None


def _hub_request(base: str, token: str, method: str, path: str, body=None):
    """Outbound call to the Poneglyph Hub. Returns (status_int, dict)."""
    url = base.rstrip("/") + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {"error": f"HTTP {e.code}"}
    except Exception as e:
        return 0, {"error": str(e)}


def _record_hub_version(data: dict, label: str):
    """When the active site is hub-linked, append the current topology to the
    local version graph and advance the local head. No-op otherwise or when the
    content is unchanged."""
    if not _active_site:
        return
    try:
        sync = _sdb.get_hub_sync(_active_site)
        if not sync or not sync.get("substation_id"):
            return
        parent = sync.get("head_id") or sync.get("base_id") or ""
        vid = _sdb.record_version(
            _active_site, data,
            author=_current_operator.get("name", ""),
            author_id=_current_operator.get("id", ""),
            message=label, branch=sync.get("branch", "main"),
            parent_id=parent,
        )
        if vid and vid != parent:
            _sdb.set_hub_sync(_active_site, head_id=vid)
    except Exception:
        traceback.print_exc()


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
    "voltage_class_kv",   # manual voltage-class override for SLD colouring
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
    "notes",           # free-form user notes attached to a device
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


# Computed power-flow telemetry (per-phase voltages, currents, angles, power).
# These were driven by the simulation engine; with it gone they are just a
# static steady-state solve, so they are no longer sent to the frontend.
_TELEMETRY_KEY_RE = re.compile(
    r"(voltage|current|v-angle|i-angle|\bangle\b|power|watt|\bvar\b|vars|"
    r"frequency|\bfreq\b|\bpf\b|power factor|kva|mva|impedance|phasor|magnitude)",
    re.I,
)


def _strip_telemetry(summary: dict) -> dict:
    """Drop computed power-flow telemetry, keeping structural/state fields
    (Status, Connection, Ratio, Type, winding config, tap position, …)."""
    out = {}
    for k, v in summary.items():
        if v == "HEADER":
            continue
        if k.startswith("---") and k.rstrip().endswith("---"):
            continue
        if _TELEMETRY_KEY_RE.search(k):
            continue
        out[k] = v
    return out


def _build_topology_response(sources, devices, raw_devices, reference, wire_bends=None):
    raw_map = {d["id"]: d for d in raw_devices}

    # Build a lookup for explicitly-specified target bushings: {source_id: {target_id: bushing}}
    _to_bushing_map = {}
    for raw_dev in raw_devices:
        src_id = raw_dev["id"]
        for c in raw_dev.get("connections", []):
            if isinstance(c, dict) and c.get("to_bushing"):
                _to_bushing_map.setdefault(src_id, {})[c["id"]] = c["to_bushing"]

    sync_errors = _detect_sync_errors(sources, devices)
    source_error_map = {}
    for err in sync_errors:
        for sid in err["sources"]:
            source_error_map.setdefault(sid, []).append(err)

    nodes = []
    edges = []

    for did, dev in devices.items():
        summary = _strip_telemetry(dev.get_summary_dict())

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
                edge = {
                    "source": dev.name,
                    "target": conn.name,
                    "type": "primary",
                    "source_bushing": "H",
                }
                tb = _to_bushing_map.get(dev.name, {}).get(conn.name)
                if tb:
                    edge["target_bushing"] = tb
                edges.append(edge)
        if hasattr(dev, "x_connections"):
            for conn in dev.x_connections:
                edge = {
                    "source": dev.name,
                    "target": conn.name,
                    "type": "primary",
                    "source_bushing": "X",
                }
                tb = _to_bushing_map.get(dev.name, {}).get(conn.name)
                if tb:
                    edge["target_bushing"] = tb
                edges.append(edge)
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
                edge = {
                    "source": dev.name,
                    "target": dev.downstream_device.name,
                    "type": "primary",
                    "source_bushing": bushing,
                }
                tb = _to_bushing_map.get(dev.name, {}).get(dev.downstream_device.name)
                if tb:
                    edge["target_bushing"] = tb
                edges.append(edge)
        if hasattr(dev, "connections"):
            for c in dev.connections:
                if not any(
                    e["source"] == dev.name and e["target"] == c.name for e in edges
                ):
                    edge = {"source": dev.name, "target": c.name, "type": "primary"}
                    tb = _to_bushing_map.get(dev.name, {}).get(c.name)
                    if tb:
                        edge["target_bushing"] = tb
                    edges.append(edge)
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

    if wire_bends:
        for edge in edges:
            key = edge["source"] + "→" + edge["target"]
            if key in wire_bends:
                edge["bend_frac"] = wire_bends[key]

    return {
        "nodes": nodes,
        "edges": edges,
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

    Snapshots are signed with the current operator (_current_operator) so the
    layout audit trail records who made each change.
    """
    if _active_site:
        try:
            is_auto = label.startswith("auto")
            _sdb.save_snapshot(
                _active_site,
                label=label,
                topology=data,
                record_device_history=not is_auto,
                author=_current_operator.get("name", ""),
                author_id=_current_operator.get("id", ""),
            )
            _record_hub_version(data, label)
        except Exception:
            traceback.print_exc()


def _apply_pulled_topology(topo: dict, label: str):
    """Make a hub topology the live one and snapshot it."""
    global _current_topology
    topo.setdefault("reference", {"device_id": None, "phase": None})
    topo.setdefault("project_info", {"station": "", "device": ""})
    _current_topology = topo
    if _active_site:
        _sdb.save_snapshot(
            _active_site, label=label, topology=topo, record_device_history=True,
            author=_current_operator.get("name", ""),
            author_id=_current_operator.get("id", ""),
        )


def _hub_sync_status_payload():
    sync = _sdb.get_hub_sync(_active_site) or {}
    linked = bool(sync.get("substation_id"))
    ahead = 0
    if linked and sync.get("head_id") and sync.get("base_id"):
        ahead = len(_sdb.local_versions_between(
            _active_site, sync["base_id"], sync["head_id"]))
    return {
        "linked": linked,
        "hub_url": sync.get("hub_url", ""),
        "substation_id": sync.get("substation_id", ""),
        "base_id": sync.get("base_id", ""),
        "head_id": sync.get("head_id", ""),
        "branch": sync.get("branch", "main"),
        "ahead": ahead,
        "pending_conflicts": (
            len(_pending_merge["conflicts"])
            if _pending_merge and _pending_merge.get("site") == _active_site
            else 0
        ),
    }


def _ser_version(v: dict) -> dict:
    return {
        "id": v["id"], "parent_id": v.get("parent_id", ""),
        "merge_parent": v.get("merge_parent", ""), "branch": v.get("branch", "main"),
        "epoch": v.get("epoch"), "author": v.get("author", ""),
        "author_id": v.get("author_id", ""), "message": v.get("message", ""),
        "topology": v["topology"],
    }


def _handle_hub_sync(handler, action, req):
    """POST /api/hub-sync/<action>. Orchestrates create / attach / pull / merge
    / resolve / push against the hub, doing the structural merge in-process."""
    global _pending_merge

    hub_url = (req.get("hub_url") or "").strip()
    token = (req.get("token") or "").strip()
    sync = _sdb.get_hub_sync(_active_site) or {}
    if not hub_url:
        hub_url = sync.get("hub_url", "")

    if action == "unlink":
        _sdb.clear_hub_sync(_active_site)
        _pending_merge = None
        return _json_response(handler, {"ok": True})

    if action == "link":
        mode = req.get("mode", "create")
        sub_id = (req.get("substation_id") or "").strip()
        if not hub_url or not token or not sub_id:
            return _json_response(handler, {"error": "hub_url, token and substation_id required"}, 400)

        if mode == "attach":
            st, data = _hub_request(hub_url, token, "GET",
                                    f"/api/hub/substations/{_urlquote(sub_id, safe='')}?full=1")
            if st != 200:
                return _json_response(handler, {"error": data.get("error", f"hub {st}")}, 502)
            versions = data.get("versions") or []
            for v in versions:
                _sdb.add_local_version(_active_site, v)
            head_id = data.get("substation", {}).get("head_id") or (versions[-1]["id"] if versions else "")
            head_v = _sdb.get_local_version(_active_site, head_id)
            if not head_v:
                return _json_response(handler, {"error": "hub returned no head version"}, 502)
            _apply_pulled_topology(head_v["topology"], f"hub attach: {sub_id}")
            _sdb.set_hub_sync(_active_site, hub_url=hub_url, substation_id=sub_id,
                              base_id=head_id, head_id=head_id,
                              linked_epoch=int(time.time()))
            return _json_response(handler, {"ok": True, "mode": "attach",
                                            **_hub_sync_status_payload()})

        # mode == "create": push the current topology as the root version
        vid = _sdb.record_version(
            _active_site, _current_topology,
            author=_current_operator.get("name", ""),
            author_id=_current_operator.get("id", ""),
            message="root", parent_id="",
        )
        root = _sdb.get_local_version(_active_site, vid)
        st, data = _hub_request(hub_url, token, "POST", "/api/hub/substations", {
            "substation_id": sub_id, "name": req.get("name", sub_id),
            "root_version": _ser_version(root),
        })
        if st not in (200, 201):
            return _json_response(handler, {"error": data.get("error", f"hub {st}")},
                                  409 if st == 409 else 502)
        _sdb.set_hub_sync(_active_site, hub_url=hub_url, substation_id=sub_id,
                          base_id=vid, head_id=vid,
                          linked_epoch=int(time.time()))
        return _json_response(handler, {"ok": True, "mode": "create",
                                        **_hub_sync_status_payload()})

    # everything below needs an established link
    if not sync.get("substation_id"):
        return _json_response(handler, {"error": "not linked to a hub substation"}, 409)
    sub_id = sync["substation_id"]

    if action == "pull":
        st, data = _hub_request(hub_url, token, "GET",
                                f"/api/hub/substations/{_urlquote(sub_id, safe='')}?since={_urlquote(sync['base_id'], safe='')}")
        if st != 200:
            return _json_response(handler, {"error": data.get("error", f"hub {st}")}, 502)
        for v in data.get("versions") or []:
            _sdb.add_local_version(_active_site, v)
        hub_head = data.get("substation", {}).get("head_id", "")
        if not hub_head or hub_head == sync["base_id"]:
            return _json_response(handler, {"ok": True, "up_to_date": True,
                                            **_hub_sync_status_payload()})

        hub_head_v = _sdb.get_local_version(_active_site, hub_head)
        local_head = sync.get("head_id") or sync["base_id"]

        if local_head == sync["base_id"]:
            # no local commits — fast-forward
            _apply_pulled_topology(hub_head_v["topology"], f"hub pull (ff): {sub_id}")
            _sdb.set_hub_sync(_active_site, base_id=hub_head, head_id=hub_head)
            return _json_response(handler, {"ok": True, "fast_forward": True,
                                            **_hub_sync_status_payload()})

        base_v = _sdb.get_local_version(_active_site, sync["base_id"])
        merged, conflicts = _merge.merge(
            base_v["topology"], _current_topology, hub_head_v["topology"])
        if not conflicts:
            mvid = _sdb.record_version(
                _active_site, merged,
                author=_current_operator.get("name", ""),
                author_id=_current_operator.get("id", ""),
                message=f"merge hub {hub_head[:8]}",
                parent_id=local_head, merge_parent=hub_head,
            )
            _apply_pulled_topology(merged, f"hub merge: {sub_id}")
            _sdb.set_hub_sync(_active_site, base_id=hub_head, head_id=mvid)
            _pending_merge = None
            return _json_response(handler, {"ok": True, "merged": True, "conflicts": 0,
                                            **_hub_sync_status_payload()})

        _pending_merge = {
            "site": _active_site,
            "merged": merged, "conflicts": conflicts,
            "base_id": sync["base_id"], "ours_head": local_head, "theirs_head": hub_head,
        }
        return _json_response(handler, {"ok": True, "merged": False,
                                        "conflicts": conflicts,
                                        **_hub_sync_status_payload()})

    if action == "resolve":
        if not _pending_merge or _pending_merge.get("site") != _active_site:
            return _json_response(handler, {"error": "no pending merge for this site"}, 409)
        resolutions = req.get("resolutions") or _pending_merge["conflicts"]
        final = _merge.resolve(_pending_merge["merged"], resolutions)
        mvid = _sdb.record_version(
            _active_site, final,
            author=_current_operator.get("name", ""),
            author_id=_current_operator.get("id", ""),
            message=f"merge hub {_pending_merge['theirs_head'][:8]} (resolved)",
            parent_id=_pending_merge["ours_head"],
            merge_parent=_pending_merge["theirs_head"],
        )
        _apply_pulled_topology(final, f"hub merge resolved: {sub_id}")
        _sdb.set_hub_sync(_active_site, base_id=_pending_merge["theirs_head"], head_id=mvid)
        _pending_merge = None
        return _json_response(handler, {"ok": True, "merged": True,
                                        **_hub_sync_status_payload()})

    if action == "push":
        base_id = sync["base_id"]
        local_head = sync.get("head_id") or base_id
        versions = _sdb.local_versions_between(_active_site, base_id, local_head)
        if not versions:
            return _json_response(handler, {"ok": True, "up_to_date": True,
                                            **_hub_sync_status_payload()})
        st, data = _hub_request(hub_url, token, "POST",
                                f"/api/hub/substations/{_urlquote(sub_id, safe='')}/push",
                                {"base_id": base_id,
                                 "versions": [_ser_version(v) for v in versions]})
        if st == 409 or data.get("conflict"):
            return _json_response(handler, {"ok": False, "conflict": True,
                                            "hub_head": data.get("head_id", ""),
                                            "hint": "pull first, then push",
                                            **_hub_sync_status_payload()})
        if st != 200:
            return _json_response(handler, {"error": data.get("error", f"hub {st}")}, 502)
        new_head = data.get("head_id", local_head)
        _sdb.set_hub_sync(_active_site, base_id=new_head, head_id=new_head)
        return _json_response(handler, {"ok": True, "pushed": data.get("applied", len(versions)),
                                        **_hub_sync_status_payload()})

    return _json_response(handler, {"error": f"unknown hub-sync action '{action}'"}, 404)


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
        global _active_site, _active_session_id, _current_topology, _current_operator, _pending_merge
        try:
            content_length = int(self.headers["Content-Length"])
            post_data = self.rfile.read(content_length) if content_length > 0 else b'{}'
            req = json.loads(post_data) if post_data else {}

            # Browser registers who is at the controls, so topology snapshots and
            # device-history rows can be signed with the operator.
            if self.path == "/api/operator":
                _current_operator = {
                    "name": str(req.get("name", "")).strip(),
                    "id": str(req.get("id", "")).strip(),
                }
                return _json_response(self, {"ok": True, "operator": _current_operator})

            # ── PMM endpoints ──────────────────────────────────────────────────
            if self.path == "/api/pmm/connect":
                return _json_response(
                    self,
                    _pmm.api_connect(
                        port=req.get("port", ""),
                        model=req.get("model", "pmm2"),
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

            # ── Site management endpoints ──────────────────────────────────────────
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
                _pending_merge = None  # any staged hub-merge conflict belonged to the prior site
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

            # ── DB / session endpoints ─────────────────────────────────────────────
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

            if self.path == "/api/tests/import-bundle":
                if not _require_site(self):
                    return
                bundle = req.get("bundle") if isinstance(req, dict) and "bundle" in req else req
                if not isinstance(bundle, dict) or not (bundle.get("test") or {}).get("id"):
                    return _json_response(self, {"error": "bundle.test.id is required"}, 400)
                try:
                    res = _sdb.import_test_bundle(
                        _active_site, bundle, origin=str(req.get("origin", "hub"))
                    )
                except ValueError as e:
                    return _json_response(self, {"error": str(e)}, 400)
                return _json_response(self, {"ok": True, **res})

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
                    drawing_number=req.get("drawing_number", "").strip(),
                )
                return _json_response(self, {"ok": True, "drawing_id": drawing_id})

            if self.path == "/api/tests/drawings/delete":
                if not _require_site(self):
                    return
                _sdb.delete_drawing(_active_site, req.get("id", ""))
                return _json_response(self, {"ok": True})

            # ── Hub substation sync (Phase 2/3) ──────────────────────────────
            if self.path.startswith("/api/hub-sync/"):
                if not _require_site(self):
                    return
                return _handle_hub_sync(self, self.path[len("/api/hub-sync/"):], req)

            if self.path == "/api/db/sessions":
                if not _require_site(self):
                    return
                _active_session_id = _sdb.start_session(
                    _active_site,
                    label=req.get("label", ""),
                    device=req.get("device", ""),
                    instrument=req.get("instrument", "manual"),
                    technician=req.get("technician", ""),
                    technician_id=req.get("technician_id", ""),
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
                action = req.get("action")
                if _current_topology is None:
                    return _json_response(self, {"error": "No site loaded"}, 409)
                # A measurement that silently doesn't persist is worse than an
                # error — topology_utils.record_measurement no-ops without an
                # active site DB, so refuse up front rather than report {ok:true}.
                if action == "record_measurement" and not _active_site:
                    return _json_response(self, {"error": "No site loaded — reading was not saved"}, 409)

                _current_topology = topology_utils.apply_reconfiguration(
                    _current_topology, req, _active_site, _active_session_id
                )
                if action not in ["update_position", "update_rotation", "record_measurement"]:
                    _autosave(_current_topology, "reconfigure:" + action)
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
                            author=_current_operator.get("name", ""),
                            author_id=_current_operator.get("id", ""),
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
                except Exception:
                    return _json_response(self, {"error": "Uploaded data is not valid base64."}, 400)
                known_ids = {
                    d.get("id") for d in (_current_topology or {}).get("devices", []) if d.get("id")
                } or None
                try:
                    result = _xrep.ingest_load_test_report(
                        _active_site, test_id, xlsx_bytes, known_device_ids=known_ids
                    )
                    return _json_response(self, result)
                except ValueError as e:
                    # A validation failure the technician can act on — not a bug.
                    return _json_response(self, {"error": str(e)}, 400)
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

            # ── Corporate drawing search ──────────────────────────────────────
            # Body: SearchParams-style dict (facility, drawing_type, drawing_subject,
            #       title, drawing_num, sheet_number, page, …). Returns
            #       {configured, results:[...], page, total_count, has_next}.
            if self.path == "/api/drawing-search":
                return _json_response(self, _dwg.search(req if isinstance(req, dict) else {}))

            # Persist drawing-search config written from the settings modal.
            # Body: {base_url, download_url, search_path, cache_refresh_hours}
            if self.path == "/api/drawing-search/config":
                return _json_response(self, _dwg.save_config(req if isinstance(req, dict) else {}))

            # Grab session cookies via Windows Integrated Auth (Windows-only).
            if self.path == "/api/drawing-search/grab-cookies":
                return _json_response(self, _dwg.grab_windows_cookies())

            # Force a live re-fetch of the facility / type / subject dropdowns.
            if self.path == "/api/drawing-search/options/refresh":
                return _json_response(self, _dwg.get_options(refresh=True))

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
                    drawing_number=req.get("drawing_number", ""),
                )
                return _json_response(self, {"ok": True, "id": row_id})

            # Remove a device drawing.
            # Body: {id}
            if self.path == "/api/db/device-drawings/delete":
                if not _require_site(self):
                    return
                _sdb.delete_device_drawing(_active_site, req.get("id", ""))
                return _json_response(self, {"ok": True})

            # Update a device drawing's revision (logs the old one).
            # Body: {id, revision, url (optional), updated_by, notes}
            if self.path == "/api/db/device-drawings/update":
                if not _require_site(self):
                    return
                drawing_id = req.get("id", "").strip()
                revision   = req.get("revision", "").strip()
                if not drawing_id or not revision:
                    return _json_response(self, {"error": "id and revision required"}, 400)
                log_id = _sdb.update_device_drawing(
                    _active_site,
                    drawing_id=drawing_id,
                    new_revision=revision,
                    new_url=req.get("url") if "url" in req else None,
                    updated_by=req.get("updated_by", ""),
                    notes=req.get("notes", ""),
                )
                return _json_response(self, {"ok": True, "log_id": log_id})

            # ── Red-Line-Routing integration ───────────────────────────────────
            #
            # POST /api/redline/import
            #   Accept a .wirePlan JSON body and import it into the active site DB.
            #   Body: the full .wirePlan JSON object (same format as the file).
            #   Optional header X-Imported-By: <name> to tag the import.
            #   Returns: {ok, import_id, summary: {...}}
            #
            # POST /api/redline/rollback
            #   Delete a previous import's tracking rows (soft rollback).
            #   Body: {import_id}
            #   Returns: {ok, links_deleted}
            #
            # POST /api/redline/rollback-full
            #   Full rollback: delete tracking rows AND all content rows
            #   (device_drawings, maintenance_log, tests) created by the import.
            #   Body: {import_id}
            #   Returns: {ok, deleted: {device_drawings, maintenance_log, tests}}

            if self.path == "/api/redline/import":
                if not _require_site(self):
                    return
                imported_by = self.headers.get("X-Imported-By", "")
                try:
                    result = _rl.import_wireplan_from_dict(
                        req,
                        _active_site,
                        topology=_current_topology,
                        imported_by=imported_by,
                        source_label="<api-upload>",
                    )
                    return _json_response(self, {
                        "ok": True,
                        "import_id": result.import_id,
                        "summary": {
                            "project":                   result.project,
                            "tests_created":             len(result.tests_created),
                            "device_drawings_created":   len(result.device_drawings_created),
                            "maintenance_entries_created": len(result.maintenance_entries_created),
                            "links_created":             len(result.links_created),
                            "unmatched_devices":         result.unmatched_devices,
                            "warnings":                  result.warnings,
                        },
                    })
                except Exception as exc:
                    return _json_response(self, {"error": str(exc)}, 400)

            if self.path == "/api/redline/rollback":
                if not _require_site(self):
                    return
                import_id = req.get("import_id", "").strip()
                if not import_id:
                    return _json_response(self, {"error": "import_id required"}, 400)
                deleted = _rl.rollback_import(_active_site, import_id)
                return _json_response(self, {"ok": True, "links_deleted": deleted})

            if self.path == "/api/redline/rollback-full":
                if not _require_site(self):
                    return
                import_id = req.get("import_id", "").strip()
                if not import_id:
                    return _json_response(self, {"error": "import_id required"}, 400)
                deleted = _rl.rollback_import_full(_active_site, import_id)
                return _json_response(self, {"ok": True, "deleted": deleted})

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
        try:
            # OS login name — used to pre-fill the operator identity prompt.
            if self.path == "/api/whoami":
                try:
                    user = getpass.getuser()
                except Exception:
                    user = ""
                return _json_response(self, {"user": user})

            # ── Corporate drawing search ──────────────────────────────────────────
            if self.path == "/api/drawing-search/config":
                info = _sdb.get_site_info(_active_site) if _active_site else None
                facility = ""
                if info:
                    facility = (info.get("number_code") or info.get("station") or "").strip()
                out = dict(_dwg.get_public_config())
                out["facility_default"] = facility
                out["type_hints"] = _dwg.DEVICE_TYPE_HINTS
                return _json_response(self, out)

            if self.path == "/api/drawing-search/options":
                return _json_response(self, _dwg.get_options())

            # Sibling-revision set for one drawing number.  Served from the
            # per-site cache; ?refresh=1 (or a stale cache) re-queries the
            # corporate drawing system by drawing number.
            if self.path.startswith("/api/drawings/revisions"):
                if not _require_site(self):
                    return
                q = parse_qs(urlparse(self.path).query)
                number = (q.get("number", [""])[0] or "").strip()
                if not number:
                    return _json_response(self, {"error": "number required"}, 400)
                force = q.get("refresh", ["0"])[0] in ("1", "true", "yes")
                cached = _sdb.get_drawing_revision_set(_active_site, number)
                try:
                    ttl_h = float(_dwg._resolve_config().get("cache_refresh_hours", 4.0))
                except Exception:
                    ttl_h = 4.0
                stale = (
                    cached is None
                    or force
                    or (time.time() - (cached.get("fetched_epoch") or 0)) > ttl_h * 3600
                )
                if stale:
                    res = _dwg.list_revisions(number)
                    if res.get("configured") and not res.get("error"):
                        _sdb.save_drawing_revision_set(
                            _active_site, number, res.get("revisions", []))
                        cached = _sdb.get_drawing_revision_set(_active_site, number)
                    elif cached is None:
                        return _json_response(self, {
                            "drawing_number": number, "revisions": [],
                            "configured": res.get("configured", False),
                            "error": res.get("error", ""),
                            "cached": False,
                        })
                return _json_response(self, {
                    "drawing_number": number,
                    "revisions": (cached or {}).get("revisions", []),
                    "fetched_epoch": (cached or {}).get("fetched_epoch", 0),
                    "cached": True,
                })

            # ── PMM GET endpoints ──────────────────────────────────────────────────
            if self.path == "/api/pmm/status":
                return _json_response(self, _pmm.api_status())

            if self.path == "/api/pmm/query":
                return _json_response(self, _pmm.api_query())

            # ── Site endpoints ───────────────────────────────────────────────────
            if self.path == "/api/sites":
                return _json_response(self, {"sites": _sdb.list_sites()})

            if self.path == "/api/sites/active":
                if _active_site:
                    info = _sdb.get_site_info(_active_site)
                    return _json_response(self, {"active": True, "info": info})
                return _json_response(self, {"active": False})

            if self.path == "/api/hub-sync/status":
                if not _require_site(self):
                    return
                return _json_response(self, _hub_sync_status_payload())

            # ── Test GET endpoints ─────────────────────────────────────────────────
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

            if self.path.startswith("/api/tests/") and self.path.endswith("/bundle"):
                if not _require_site(self):
                    return
                test_id = self.path.split("/")[3]
                info = _sdb.get_site_info(_active_site) or {}
                sub_id = (info.get("number_code") or info.get("station") or "").strip()
                bundle = _sdb.export_test_bundle(_active_site, test_id, substation_id=sub_id)
                if bundle is None:
                    return _json_response(self, {"error": "test not found"}, 404)
                return _json_response(self, bundle)

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

            if self.path.startswith("/api/tests/") and self.path.endswith("/audit"):
                if not _require_site(self):
                    return
                test_id = self.path.split("/")[3]
                report = _sdb.get_test_report_data(_active_site, test_id)
                if not report:
                    return _json_response(self, {"error": "test not found"}, 404)
                devices = (_current_topology or {}).get("devices", [])
                result = _audit.build_audit(report, devices)
                return _json_response(self, {
                    "test": report["test"],
                    "sessions": [
                        {k: s[k] for k in ("id", "epoch", "technician", "instrument", "label")}
                        for s in report["sessions"]
                    ],
                    **result,
                })

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

            # ── DB GET endpoints ─────────────────────────────────────────────────────
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

            # Revision history for a single drawing
            # GET /api/db/drawing-history/<drawing_id>
            if self.path.startswith("/api/db/drawing-history/"):
                if not _require_site(self):
                    return
                drawing_id = self.path.split("/", 4)[-1]
                rows = _sdb.get_drawing_revision_history(_active_site, drawing_id)
                return _json_response(self, {"history": rows})

            # Drawings attached to a device
            # GET /api/db/device-drawings/<device_id>
            if self.path.startswith("/api/db/device-drawings/"):
                if not _require_site(self):
                    return
                device_id = self.path.split("/", 4)[-1]
                rows = _sdb.list_device_drawings(_active_site, device_id)
                return _json_response(self, {"drawings": rows})

            # ── Red-Line-Routing query endpoints ──────────────────────────────
            #
            # GET /api/redline/imports
            #   List all .wirePlan imports for the active site, newest first.
            #
            # GET /api/redline/imports/<import_id>/links
            #   All correlation links created by one import.
            #
            # GET /api/redline/imports/<import_id>/explain
            #   Human-readable audit report for one import.
            #
            # GET /api/redline/device-links/<device_id>
            #   All wirePlan links that point at a specific topology device
            #   (joined with project name for context).

            if self.path == "/api/redline/imports":
                if not _require_site(self):
                    return
                return _json_response(self, {"imports": _rl.list_imports(_active_site)})

            if self.path.startswith("/api/redline/imports/"):
                if not _require_site(self):
                    return
                parts = self.path.rstrip("/").split("/")
                # /api/redline/imports/<id>/links  or  /api/redline/imports/<id>/explain
                if len(parts) >= 5:
                    import_id   = parts[4]
                    sub_command = parts[5] if len(parts) > 5 else ""
                    if sub_command == "links":
                        links = _rl.get_import_links(_active_site, import_id)
                        return _json_response(self, {"links": links})
                    if sub_command == "explain":
                        report = _rl.explain_import(_active_site, import_id)
                        return _json_response(self, {"report": report})
                self.send_response(404)
                self.end_headers()
                return

            if self.path.startswith("/api/redline/device-links/"):
                if not _require_site(self):
                    return
                device_id = self.path.split("/", 5)[-1]
                links = _rl.get_device_wireplan_links(_active_site, device_id)
                return _json_response(self, {"links": links})

            if self.path == "/api/topology":
                sources, devices, raw_devices, reference, project_info = (
                    load_substation()
                )
                resp = _build_topology_response(
                    sources, devices, raw_devices, reference,
                    _current_topology.get("wire_bends", {}) if _current_topology else None
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
                # Retired — its own key-naming scheme ("A_mag"/"A_ang") never
                # matched the canonical measurement keys, so readings logged
                # from it were silently invisible to reports/audit/export.
                # The main measurement screen is the one flow now; send
                # anyone with the old URL bookmarked back to it.
                self.send_response(302)
                self.send_header("Location", "/")
                self.end_headers()
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
                        data = f.read()
                        self.send_response(200)
                        self.send_header("Content-type", content_type or "application/octet-stream")
                        # Never let JS/CSS sit in the browser cache — always serve fresh
                        if local_path.endswith((".js", ".css")):
                            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
                            self.send_header("Pragma", "no-cache")
                        self.end_headers()
                        self.wfile.write(data)
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
    httpd = HTTPServer((_cfg.HOST, _cfg.PORT), SCADAServer)
    print(f"SCADA Server on {_cfg.HOST}:{_cfg.PORT}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.server_close()
