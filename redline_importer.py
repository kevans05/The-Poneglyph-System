"""
redline_importer.py  —  Red-Line-Routing ↔ Poneglyph System integration bridge.

Reads a .wirePlan JSON produced by Red-Line-Routing and enriches the active
Poneglyph site database with the following imported content:

  relay_settings   →  device_drawings (one per relay record, linked to topology)
  drawing_registry →  device_drawings (on every topology device that appears as
                        a wire endpoint citing that drawing)
  TESTING jobs     →  poneglyph tests (description + notes carry-over)
  BLOCK/UNBLOCK    →  maintenance_log entries on the isolated protection device
  CROWs            →  maintenance_log entries (tagged with outage number + URL)
  ADD/REMOVE/MOVE  →  maintenance_log entries on all topology devices touched
                        by the wire-change endpoints

Cross-system correlation uses a layered "clue" strategy.  Every candidate
pair is scored and the top match above a threshold is accepted.  All accepted
links are written to the `redline_links` table so the audit trail is complete
and the import is fully reversible (delete the import row to cascade-delete
every derived row).

Clue tiers (higher confidence = more specific evidence):

  Tier         Source field              Target field              Confidence
  ───────────  ────────────────────────  ──────────────────────    ──────────
  ID_EXACT     relay_settings.device_id  topology device id        1.00
  WO_LINK      relay_settings.wo_device  topology device id        0.95
  PROT_EQUIP   protection.equipment      topology relay device id   0.90
  NORM_NAME    endpoint.device (norm)    topology device id (norm) 0.80
  SEC_LOCATION endpoint.device           CT/VT .location field     0.75
  PANEL_HIT    endpoint.panel            device.panel (history)    0.65
  DRAWING_REF  endpoint.drawing          drawing_registry entry    0.60

Public API
──────────
  import_wireplan(wireplan_path, db_path, topology=None, imported_by="")
      Main entry point.  Returns an ImportResult namedtuple.

  list_imports(db_path) → list[dict]
      All redline_imports rows for a site.

  get_import_links(db_path, import_id) → list[dict]
      All correlation links created by one import.

  rollback_import(db_path, import_id)
      Delete all DB rows created by one import (cascade via FK).

  explain_import(db_path, import_id) → str
      Human-readable summary of what one import created.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import site_db as _sdb

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────────
# Schema additions  (appended to the site DB on first use)
# ─────────────────────────────────────────────────────────────────────────────────

_REDLINE_SCHEMA = """
-- One row per .wirePlan file ever imported into this site.
CREATE TABLE IF NOT EXISTS redline_imports (
    id              TEXT    PRIMARY KEY,   -- UUID
    epoch           INTEGER NOT NULL,
    wireplan_path   TEXT    NOT NULL,      -- absolute path of the .wirePlan file
    project_name    TEXT    DEFAULT '',
    station_guess   TEXT    DEFAULT '',    -- station name inferred from plan, if any
    imported_by     TEXT    DEFAULT '',
    job_count       INTEGER DEFAULT 0,
    relay_count     INTEGER DEFAULT 0,
    drawing_count   INTEGER DEFAULT 0,
    crow_count      INTEGER DEFAULT 0,
    linked_device_count INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_rl_import_epoch ON redline_imports(epoch DESC);

-- Every cross-system correlation link produced by one import.
-- Deleting the parent redline_imports row cascades here, giving clean rollback.
CREATE TABLE IF NOT EXISTS redline_links (
    id              TEXT    PRIMARY KEY,
    import_id       TEXT    NOT NULL REFERENCES redline_imports(id) ON DELETE CASCADE,
    epoch           INTEGER NOT NULL,
    -- Source side (Red-Line-Routing)
    rl_entity_type  TEXT    NOT NULL,  -- relay_setting | drawing | job | crow | endpoint
    rl_entity_key   TEXT    NOT NULL,  -- device_id / drawing name / job index / outage_number
    -- Target side (Poneglyph)
    pg_entity_type  TEXT    NOT NULL,  -- device | test | maintenance_log | device_drawing
    pg_entity_id    TEXT    NOT NULL,  -- topology device id or DB row UUID
    -- How the link was established
    clue_tier       TEXT    NOT NULL,  -- ID_EXACT | WO_LINK | PROT_EQUIP | NORM_NAME | etc.
    confidence      REAL    NOT NULL,  -- 0.0–1.0
    clue_detail     TEXT    DEFAULT '' -- human-readable description of the clue
);
CREATE INDEX IF NOT EXISTS idx_rl_link_import   ON redline_links(import_id);
CREATE INDEX IF NOT EXISTS idx_rl_link_pg_id    ON redline_links(pg_entity_id);
CREATE INDEX IF NOT EXISTS idx_rl_link_rl_key   ON redline_links(rl_entity_key);
"""

# Columns that might need adding to pre-existing redline_imports rows
_REDLINE_MIGRATIONS: list[tuple[str, str, str]] = [
    ("redline_imports", "station_guess",       "TEXT    DEFAULT ''"),
    ("redline_imports", "linked_device_count", "INTEGER DEFAULT 0"),
]


def _ensure_redline_schema(db_path: str) -> None:
    """Create redline tables / migrate columns if needed."""
    with _conn(db_path) as c:
        c.executescript(_REDLINE_SCHEMA)
        existing: dict[str, set] = {}
        for table, col, typedef in _REDLINE_MIGRATIONS:
            if table not in existing:
                rows = c.execute(f"PRAGMA table_info({table})").fetchall()
                existing[table] = {r[1] for r in rows}
            if col not in existing[table]:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typedef}")
                existing[table].add(col)


def _conn(db_path: str) -> sqlite3.Connection:
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    return c


# ─────────────────────────────────────────────────────────────────────────────────
# WirePlan data structures (plain dicts from JSON, typed for clarity)
# ─────────────────────────────────────────────────────────────────────────────────

@dataclass
class WireEndpoint:
    device: str = ""
    location: str = ""
    pin: str = ""
    panel: str = ""
    drawing: str = ""
    drawing_rev: str = ""
    drawing_url: str = ""
    drawing_cell: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "WireEndpoint":
        return cls(
            device      = d.get("device", ""),
            location    = d.get("location", ""),
            pin         = d.get("pin", ""),
            panel       = d.get("panel", ""),
            drawing     = d.get("drawing", ""),
            drawing_rev = d.get("drawing_rev", ""),
            drawing_url = d.get("drawing_url", ""),
            drawing_cell= d.get("drawing_cell", ""),
        )

    def is_blank(self) -> bool:
        return not any([self.device, self.location, self.pin, self.panel])


@dataclass
class ProtectionBlock:
    equipment: str = ""
    location: str = ""
    panel: str = ""
    notes: str = ""
    drawings: list[dict] = field(default_factory=list)
    iso_points: list[dict] = field(default_factory=list)
    mb_enabled: bool = False
    mb_remote: str = ""
    mb_notes: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "ProtectionBlock":
        return cls(
            equipment  = d.get("equipment", ""),
            location   = d.get("location", ""),
            panel      = d.get("panel", ""),
            notes      = d.get("notes", ""),
            drawings   = d.get("drawings", []),
            iso_points = d.get("iso_points", []),
            mb_enabled = bool(d.get("mb_enabled", False)),
            mb_remote  = d.get("mb_remote", ""),
            mb_notes   = d.get("mb_notes", ""),
        )


@dataclass
class WirePlanJob:
    index: int = 0
    job_type: str = ""          # REMOVE | ADD | MOVE | BLOCK | UNBLOCK | TESTING
    description: str = ""
    wire: str = ""
    start: WireEndpoint = field(default_factory=WireEndpoint)
    end: WireEndpoint = field(default_factory=WireEndpoint)
    add_wire: str = ""
    add_start: WireEndpoint = field(default_factory=WireEndpoint)
    add_end: WireEndpoint = field(default_factory=WireEndpoint)
    protection: ProtectionBlock = field(default_factory=ProtectionBlock)
    notes: str = ""             # TESTING only

    @classmethod
    def from_dict(cls, d: dict, index: int) -> "WirePlanJob":
        job = cls(
            index       = index,
            job_type    = d.get("type", ""),
            description = d.get("description", ""),
            wire        = d.get("wire", ""),
            notes       = d.get("notes", ""),
        )
        if "start" in d:
            job.start = WireEndpoint.from_dict(d["start"])
        if "end" in d:
            job.end = WireEndpoint.from_dict(d["end"])
        if "add_start" in d:
            job.add_start = WireEndpoint.from_dict(d["add_start"])
        if "add_end" in d:
            job.add_end = WireEndpoint.from_dict(d["add_end"])
        job.add_wire = d.get("add_wire", "")
        if "protection" in d:
            job.protection = ProtectionBlock.from_dict(d["protection"])
        return job

    def all_endpoints(self) -> list[WireEndpoint]:
        eps = []
        for ep in (self.start, self.end, self.add_start, self.add_end):
            if not ep.is_blank():
                eps.append(ep)
        return eps


@dataclass
class WirePlan:
    project: str = ""
    title_notes: str = ""
    crows: list[dict] = field(default_factory=list)
    drawing_registry: dict[str, dict] = field(default_factory=dict)
    relay_settings: dict[str, dict] = field(default_factory=dict)
    history: dict[str, list] = field(default_factory=dict)
    jobs: list[WirePlanJob] = field(default_factory=list)

    @classmethod
    def from_file(cls, path: str) -> "WirePlan":
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: dict) -> "WirePlan":
        tp = raw.get("title_page", {})
        plan = cls(
            project         = raw.get("project", ""),
            title_notes     = tp.get("notes", ""),
            crows           = tp.get("crows", []),
            drawing_registry= raw.get("drawing_registry", {}),
            relay_settings  = raw.get("relay_settings", {}),
            history         = raw.get("history", {}),
            jobs            = [
                WirePlanJob.from_dict(j, i)
                for i, j in enumerate(raw.get("jobs", []))
            ],
        )
        return plan


# ─────────────────────────────────────────────────────────────────────────────────
# Topology helper — extract device index once and reuse
# ─────────────────────────────────────────────────────────────────────────────────

@dataclass
class TopoIndex:
    """Lightweight index built from a Poneglyph topology dict."""
    by_id: dict[str, dict]                  = field(default_factory=dict)
    by_norm: dict[str, list[str]]           = field(default_factory=dict)  # norm_name → [ids]
    by_type: dict[str, list[str]]           = field(default_factory=dict)  # type → [ids]
    by_location: dict[str, list[str]]       = field(default_factory=dict)  # location → [ids]
    relay_ids: set[str]                     = field(default_factory=set)
    ct_ids: set[str]                        = field(default_factory=set)
    vt_ids: set[str]                        = field(default_factory=set)

    @classmethod
    def build(cls, topology: dict | None) -> "TopoIndex":
        idx = cls()
        if not topology:
            return idx
        for d in topology.get("devices", []):
            did = d.get("id", "")
            if not did:
                continue
            idx.by_id[did] = d
            norm = _norm(did)
            idx.by_norm.setdefault(norm, []).append(did)
            dtype = d.get("type", "")
            idx.by_type.setdefault(dtype, []).append(did)
            loc = d.get("location", "")
            if loc:
                idx.by_location.setdefault(loc, []).append(did)
            dtype_lo = dtype.lower()
            if "relay" in dtype_lo:
                idx.relay_ids.add(did)
            if "currenttransformer" in dtype_lo or dtype == "CT":
                idx.ct_ids.add(did)
            if "voltagetransformer" in dtype_lo or "vt" in dtype_lo or "dualwindingvt" in dtype_lo.replace(" ", ""):
                idx.vt_ids.add(did)
        return idx

    def find_device(self, name: str) -> list[tuple[str, float, str]]:
        """Return (device_id, confidence, clue_tier) candidates for a name string."""
        if not name:
            return []
        candidates: list[tuple[str, float, str]] = []

        # Tier 1 — exact id match
        if name in self.by_id:
            candidates.append((name, 1.00, "ID_EXACT"))
            return candidates          # perfect match, no need to check further

        # Tier 2 — case-insensitive exact
        name_lo = name.strip().lower()
        for did in self.by_id:
            if did.lower() == name_lo:
                candidates.append((did, 0.92, "ID_CASE"))
                return candidates

        # Tier 3 — normalized name match (strip punctuation)
        norm = _norm(name)
        if norm in self.by_norm:
            for did in self.by_norm[norm]:
                candidates.append((did, 0.80, "NORM_NAME"))

        # Tier 4 — device appears as a CT/VT location host
        if name in self.by_location:
            for did in self.by_location[name]:
                candidates.append((did, 0.75, "SEC_LOCATION"))

        # Tier 5 — prefix / suffix containment (partial match)
        if not candidates:
            norm_tokens = set(norm.split())
            for did, dev in self.by_id.items():
                did_norm = _norm(did)
                did_tokens = set(did_norm.split())
                overlap = norm_tokens & did_tokens
                if overlap and len(overlap) / max(len(norm_tokens), 1) >= 0.6:
                    candidates.append((did, 0.55, "TOKEN_MATCH"))

        return candidates


# ─────────────────────────────────────────────────────────────────────────────────
# Clue helpers
# ─────────────────────────────────────────────────────────────────────────────────

def _norm(s: str) -> str:
    """Normalise a device name for fuzzy comparison."""
    return re.sub(r"[^a-z0-9]", " ", s.strip().lower()).strip()


def _best_match(
    candidates: list[tuple[str, float, str]],
    threshold: float = 0.55,
) -> tuple[str, float, str] | None:
    """Return the highest-confidence candidate above the threshold, or None."""
    if not candidates:
        return None
    best = max(candidates, key=lambda t: t[1])
    return best if best[1] >= threshold else None


def _drawing_clue_detail(ep: WireEndpoint, drawing_name: str) -> str:
    parts = [f"drawing '{drawing_name}'"]
    if ep.device:
        parts.append(f"at device '{ep.device}'")
    if ep.panel:
        parts.append(f"panel '{ep.panel}'")
    if ep.pin:
        parts.append(f"pin '{ep.pin}'")
    return ", ".join(parts)


# ─────────────────────────────────────────────────────────────────────────────────
# ImportResult
# ─────────────────────────────────────────────────────────────────────────────────

@dataclass
class ImportResult:
    import_id: str
    project: str
    tests_created: list[str]               = field(default_factory=list)
    device_drawings_created: list[str]     = field(default_factory=list)
    maintenance_entries_created: list[str] = field(default_factory=list)
    links_created: list[dict]             = field(default_factory=list)
    unmatched_devices: list[str]           = field(default_factory=list)
    warnings: list[str]                    = field(default_factory=list)

    @property
    def summary(self) -> str:
        return (
            f"Import '{self.project}' (id={self.import_id}):\n"
            f"  Tests created:            {len(self.tests_created)}\n"
            f"  Device drawings created:  {len(self.device_drawings_created)}\n"
            f"  Maintenance log entries:  {len(self.maintenance_entries_created)}\n"
            f"  Cross-system links:       {len(self.links_created)}\n"
            f"  Unmatched device names:   {len(self.unmatched_devices)}\n"
            + (f"  Warnings ({len(self.warnings)}):\n" +
               "\n".join(f"    - {w}" for w in self.warnings)
               if self.warnings else "")
        )


# ─────────────────────────────────────────────────────────────────────────────────
# Link recorder
# ─────────────────────────────────────────────────────────────────────────────────

def _record_link(
    conn: sqlite3.Connection,
    import_id: str,
    rl_entity_type: str,
    rl_entity_key: str,
    pg_entity_type: str,
    pg_entity_id: str,
    clue_tier: str,
    confidence: float,
    clue_detail: str = "",
) -> str:
    row_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO redline_links
           (id, import_id, epoch, rl_entity_type, rl_entity_key,
            pg_entity_type, pg_entity_id, clue_tier, confidence, clue_detail)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (row_id, import_id, int(time.time()),
         rl_entity_type, rl_entity_key,
         pg_entity_type, pg_entity_id,
         clue_tier, round(confidence, 4), clue_detail),
    )
    return row_id


# ─────────────────────────────────────────────────────────────────────────────────
# Sub-importers
# ─────────────────────────────────────────────────────────────────────────────────

def _import_relay_settings(
    conn: sqlite3.Connection,
    plan: WirePlan,
    topo: TopoIndex,
    import_id: str,
    result: ImportResult,
    now: int,
) -> None:
    """
    For each relay_settings entry in the .wirePlan:
      1. Identify the matching topology device (ID_EXACT → WO_LINK → NORM_NAME).
      2. Create a device_drawing record with the relay sheet URL + revision.
      3. Record the cross-system link with the matching clue tier.

    The relay engineer and contact are embedded in the drawing notes so the
    Poneglyph side has the full paper trail even without the .wirePlan file.
    """
    for device_id, rec in plan.relay_settings.items():
        title     = rec.get("title", "") or device_id
        revision  = rec.get("revision", "")
        url       = rec.get("url", "")
        engineer  = rec.get("engineer", "")
        contact   = rec.get("contact", "")
        wo_device = rec.get("wo_device", "")

        notes_parts = []
        if engineer:
            notes_parts.append(f"Engineer: {engineer}")
        if contact:
            notes_parts.append(f"Contact: {contact}")
        notes_parts.append(f"Imported from Red-Line-Routing project '{plan.project}'")
        notes = " | ".join(notes_parts)

        # ── Find matching topology device ──────────────────────────────────────────────────
        matched_did: str | None = None
        clue_tier: str = "UNMATCHED"
        confidence: float = 0.0
        clue_detail: str = ""

        # Tier 1 — device_id from relay_settings matches topology id exactly
        if device_id in topo.by_id:
            matched_did = device_id
            clue_tier   = "ID_EXACT"
            confidence  = 1.00
            clue_detail = f"relay_settings key '{device_id}' == topology device id"

        # Tier 2 — relay record has an explicit wo_device link
        if not matched_did and wo_device:
            hit = _best_match(topo.find_device(wo_device), threshold=0.75)
            if hit:
                matched_did = hit[0]
                clue_tier   = "WO_LINK"
                confidence  = hit[1]
                clue_detail = (
                    f"relay_settings.wo_device='{wo_device}' matched "
                    f"topology device '{matched_did}' (tier {hit[2]})"
                )

        # Tier 3 — fuzzy match on the device_id string itself
        if not matched_did:
            hit = _best_match(topo.find_device(device_id), threshold=0.60)
            if hit:
                matched_did = hit[0]
                clue_tier   = hit[2]
                confidence  = hit[1]
                clue_detail = (
                    f"relay_settings key '{device_id}' fuzzy-matched "
                    f"topology device '{matched_did}'"
                )

        if matched_did is None:
            result.unmatched_devices.append(device_id)
            result.warnings.append(
                f"relay_settings '{device_id}': no topology device match found; "
                "device_drawing created without a topology anchor"
            )

        # ── Create device_drawing ───────────────────────────────────────────────────────────
        target_device = matched_did or device_id
        drawing_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO device_drawings (id, device_id, title, url, revision, notes)
               VALUES (?,?,?,?,?,?)""",
            (drawing_id, target_device, title, url, revision, notes),
        )
        result.device_drawings_created.append(drawing_id)

        # ── Record link ────────────────────────────────────────────────────────────────────────────────
        if matched_did:
            link_detail = clue_detail or f"relay_settings['{device_id}'] → device_drawing on '{matched_did}'"
            link_id = _record_link(
                conn, import_id,
                "relay_setting", device_id,
                "device_drawing", drawing_id,
                clue_tier, confidence, link_detail,
            )
            result.links_created.append({
                "link_id": link_id, "rl_key": device_id,
                "pg_id": matched_did, "tier": clue_tier,
                "confidence": confidence,
            })
            # Also record the device itself as a linked target
            _record_link(
                conn, import_id,
                "relay_setting", device_id,
                "device", matched_did,
                clue_tier, confidence, link_detail,
            )


def _import_drawing_registry(
    conn: sqlite3.Connection,
    plan: WirePlan,
    topo: TopoIndex,
    import_id: str,
    result: ImportResult,
    now: int,
) -> dict[str, set[str]]:
    """
    For each drawing in the registry, find every topology device that appears
    as an endpoint *citing* that drawing across all wire jobs.  Create a
    device_drawing row for each such device.

    Returns: drawing_name → {matched topology device ids}  (for later use)
    """
    # Build a reverse index: drawing_name → set of WireEndpoints that cite it
    drawing_to_endpoints: dict[str, list[WireEndpoint]] = defaultdict(list)
    for job in plan.jobs:
        for ep in job.all_endpoints():
            if ep.drawing and ep.drawing in plan.drawing_registry:
                drawing_to_endpoints[ep.drawing].append(ep)

    drawing_to_devices: dict[str, set[str]] = {}

    for drawing_name, dreg in plan.drawing_registry.items():
        title    = dreg.get("title", drawing_name)
        revision = dreg.get("rev", dreg.get("revision", ""))
        url      = dreg.get("url", "")
        notes    = f"Imported from Red-Line-Routing project '{plan.project}'"

        endpoints_citing = drawing_to_endpoints.get(drawing_name, [])
        matched_devices: set[str] = set()

        for ep in endpoints_citing:
            candidates = topo.find_device(ep.device) if ep.device else []
            hit = _best_match(candidates, threshold=0.55)
            if hit:
                matched_devices.add(hit[0])
                # Create a device_drawing on this device
                drawing_id = str(uuid.uuid4())
                conn.execute(
                    """INSERT INTO device_drawings (id, device_id, title, url, revision, notes)
                       VALUES (?,?,?,?,?,?)""",
                    (drawing_id, hit[0], title, url, revision, notes),
                )
                result.device_drawings_created.append(drawing_id)

                clue_detail = _drawing_clue_detail(ep, drawing_name)
                link_id = _record_link(
                    conn, import_id,
                    "drawing", drawing_name,
                    "device_drawing", drawing_id,
                    hit[2], hit[1], clue_detail,
                )
                result.links_created.append({
                    "link_id": link_id, "rl_key": drawing_name,
                    "pg_id": hit[0], "tier": hit[2],
                    "confidence": hit[1],
                })

        drawing_to_devices[drawing_name] = matched_devices

        # If the drawing is in the registry but no endpoints cite it, record a
        # stub link anyway so it's traceable
        if not endpoints_citing:
            result.warnings.append(
                f"Drawing '{drawing_name}' is in drawing_registry but not cited "
                "by any job endpoint; no device_drawing created"
            )

    return drawing_to_devices


def _import_testing_jobs(
    conn: sqlite3.Connection,
    plan: WirePlan,
    topo: TopoIndex,
    import_id: str,
    result: ImportResult,
    now: int,
) -> None:
    """
    Each TESTING job in the .wirePlan becomes a Poneglyph test.
    The job's description becomes the test name; notes become the description.
    The import_id is woven into the description so the link back to the
    wirePlan is never lost even if the redline_links table is dropped.
    """
    for job in plan.jobs:
        if job.job_type != "TESTING":
            continue

        name = job.description or f"Testing step #{job.index + 1}"
        desc_parts = []
        if job.notes:
            desc_parts.append(job.notes)
        desc_parts.append(
            f"[Imported from Red-Line-Routing project '{plan.project}', "
            f"job #{job.index + 1}, import_id={import_id}]"
        )
        description = "\n".join(desc_parts)

        test_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO tests (id, epoch, name, description, created_by, status)
               VALUES (?,?,?,?,?,?)""",
            (test_id, now, name, description, f"redline:{plan.project}", "IN PROGRESS"),
        )
        result.tests_created.append(test_id)

        link_id = _record_link(
            conn, import_id,
            "job", str(job.index),
            "test", test_id,
            "JOB_TYPE_TESTING", 1.00,
            f"TESTING job #{job.index + 1}: '{name}'",
        )
        result.links_created.append({
            "link_id": link_id, "rl_key": f"job:{job.index}",
            "pg_id": test_id, "tier": "JOB_TYPE_TESTING",
            "confidence": 1.00,
        })


def _import_block_unblock_jobs(
    conn: sqlite3.Connection,
    plan: WirePlan,
    topo: TopoIndex,
    import_id: str,
    result: ImportResult,
    now: int,
) -> None:
    """
    BLOCK and UNBLOCK jobs describe isolation of protection equipment.
    For each job:
      - The protection.equipment field is matched to a topology relay device.
      - A maintenance_log entry is created on that device recording the isolation
        event, all associated drawings, isolation points, and motorised-breaker info.
      - Every drawing cited in the protection block is linked via redline_links.

    Clue tiers used:
      PROT_EQUIP   protection.equipment == relay device id (high confidence)
      NORM_NAME    normalized name match
    """
    for job in plan.jobs:
        if job.job_type not in ("BLOCK", "UNBLOCK"):
            continue

        prot = job.protection
        equipment = prot.equipment.strip()
        action    = job.job_type   # "BLOCK" or "UNBLOCK"
        desc      = job.description or f"{action} — {equipment}"

        # ── Find topology device for protected equipment ──────────────────────────────────
        matched_did: str | None = None
        clue_tier: str = "PROT_EQUIP"
        confidence: float = 0.0
        clue_detail: str = ""

        if equipment:
            # Primary: exact match to relay device ids
            if equipment in topo.relay_ids:
                matched_did = equipment
                clue_tier   = "PROT_EQUIP"
                confidence  = 0.90
                clue_detail = (
                    f"protection.equipment='{equipment}' is a Relay device in topology"
                )
            # Secondary: any topology device (relay or not)
            elif equipment in topo.by_id:
                matched_did = equipment
                clue_tier   = "ID_EXACT"
                confidence  = 1.00
                clue_detail = (
                    f"protection.equipment='{equipment}' == topology device id"
                )
            else:
                hit = _best_match(topo.find_device(equipment), threshold=0.55)
                if hit:
                    matched_did = hit[0]
                    clue_tier   = hit[2]
                    confidence  = hit[1]
                    clue_detail = (
                        f"protection.equipment='{equipment}' fuzzy-matched "
                        f"topology device '{matched_did}'"
                    )

        if matched_did is None:
            if equipment:
                result.unmatched_devices.append(equipment)
                result.warnings.append(
                    f"{action} job #{job.index + 1}: protection.equipment='{equipment}' "
                    "not matched to any topology device"
                )
            matched_did = equipment or f"UNKNOWN_{job.index}"

        # ── Build work_performed text ─────────────────────────────────────────────────────────
        work_parts = [f"{action}: {desc}"]
        if prot.location:
            work_parts.append(f"Location: {prot.location}")
        if prot.panel:
            work_parts.append(f"Panel: {prot.panel}")
        if prot.notes:
            work_parts.append(f"Notes: {prot.notes}")
        if prot.iso_points:
            iso_strs = [
                f"{ip.get('iso_type','')}:{ip.get('reference','')}"
                for ip in prot.iso_points
            ]
            work_parts.append("Isolation points: " + "; ".join(iso_strs))
        if prot.mb_enabled:
            work_parts.append(
                f"Motorised breaker required on remote device '{prot.mb_remote}'. "
                + (f"MB notes: {prot.mb_notes}" if prot.mb_notes else "")
            )
        for drw in prot.drawings:
            dname = drw.get("drawing", "")
            drev  = drw.get("drawing_rev", "")
            dcell = drw.get("drawing_cell", "")
            if dname:
                ref = dname
                if drev:
                    ref += f" rev {drev}"
                if dcell:
                    ref += f" cell {dcell}"
                work_parts.append(f"Drawing ref: {ref}")
        work_parts.append(
            f"[Red-Line-Routing project '{plan.project}', job #{job.index + 1}]"
        )

        work_performed = "\n".join(work_parts)

        # ── Create maintenance_log entry ────────────────────────────────────────────────────────
        maint_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO maintenance_log
               (id, device_id, epoch, technician, work_performed, notes)
               VALUES (?,?,?,?,?,?)""",
            (maint_id, matched_did, now, f"redline:{plan.project}",
             work_performed, prot.notes),
        )
        result.maintenance_entries_created.append(maint_id)

        # ── Record links ────────────────────────────────────────────────────────────────────────────────
        link_id = _record_link(
            conn, import_id,
            "job", str(job.index),
            "maintenance_log", maint_id,
            clue_tier, confidence,
            clue_detail or f"{action} job on '{matched_did}'",
        )
        result.links_created.append({
            "link_id": link_id, "rl_key": f"job:{job.index}",
            "pg_id": matched_did, "tier": clue_tier,
            "confidence": confidence,
        })

        # Link every protection drawing to the device_drawing table too
        for drw in prot.drawings:
            dname = drw.get("drawing", "")
            durl  = drw.get("drawing_url", "")
            drev  = drw.get("drawing_rev", "")
            if dname and matched_did in topo.by_id:
                dd_id = str(uuid.uuid4())
                conn.execute(
                    """INSERT INTO device_drawings (id, device_id, title, url, revision, notes)
                       VALUES (?,?,?,?,?,?)""",
                    (dd_id, matched_did, dname, durl, drev,
                     f"Protection drawing for {action} job #{job.index+1}"),
                )
                result.device_drawings_created.append(dd_id)
                _record_link(
                    conn, import_id,
                    "drawing", dname,
                    "device_drawing", dd_id,
                    "PROT_DRAWING", 0.85,
                    f"Protection drawing for {action} job on '{matched_did}'",
                )


def _import_wire_jobs(
    conn: sqlite3.Connection,
    plan: WirePlan,
    topo: TopoIndex,
    import_id: str,
    result: ImportResult,
    now: int,
) -> None:
    """
    ADD, REMOVE, and MOVE wire jobs document physical wiring changes.
    For each endpoint that resolves to a topology device, a maintenance_log
    entry is created capturing:
      - The wire number
      - Start and end device/location/pin/panel
      - Associated drawing references

    Multiple clues are used per endpoint:
      NORM_NAME    endpoint.device name matched to topology id
      SEC_LOCATION endpoint.device matches as a CT/VT host
      DRAWING_REF  endpoint.drawing linked to drawing_registry entry
    """
    for job in plan.jobs:
        if job.job_type not in ("ADD", "REMOVE", "MOVE"):
            continue

        endpoints = job.all_endpoints()
        if not endpoints:
            continue

        # Describe the full wire job for the notes field
        wire_label = f"Wire {job.wire}" if job.wire else "Wire (unlabelled)"
        action_label = {
            "ADD":    "ADD wire",
            "REMOVE": "REMOVE wire",
            "MOVE":   "MOVE wire",
        }.get(job.job_type, job.job_type)

        def _ep_str(ep: WireEndpoint) -> str:
            parts = []
            if ep.device:   parts.append(ep.device)
            if ep.location: parts.append(f"loc:{ep.location}")
            if ep.panel:    parts.append(f"panel:{ep.panel}")
            if ep.pin:      parts.append(f"pin:{ep.pin}")
            return " / ".join(parts) if parts else "(blank)"

        start_str = _ep_str(job.start) if not job.start.is_blank() else ""
        end_str   = _ep_str(job.end)   if not job.end.is_blank()   else ""

        for ep in endpoints:
            if ep.is_blank() or not ep.device:
                continue

            candidates = topo.find_device(ep.device)
            hit = _best_match(candidates, threshold=0.55)
            if not hit:
                result.unmatched_devices.append(ep.device)
                continue

            matched_did, confidence, tier = hit

            work_parts = [
                f"{action_label}: {job.description or wire_label}",
                f"{wire_label}",
            ]
            if start_str:
                work_parts.append(f"From: {start_str}")
            if end_str:
                work_parts.append(f"To:   {end_str}")
            if ep.panel:
                work_parts.append(f"Panel: {ep.panel}  Pin: {ep.pin}")
            if ep.drawing:
                dreg = plan.drawing_registry.get(ep.drawing, {})
                drev = ep.drawing_rev or dreg.get("rev", "")
                durl = ep.drawing_url or dreg.get("url", "")
                ref  = ep.drawing
                if drev:
                    ref += f" rev {drev}"
                if ep.drawing_cell:
                    ref += f" cell {ep.drawing_cell}"
                work_parts.append(f"Drawing: {ref}")
            work_parts.append(
                f"[Red-Line-Routing project '{plan.project}', "
                f"job #{job.index + 1} ({job.job_type})]"
            )

            maint_id = str(uuid.uuid4())
            conn.execute(
                """INSERT INTO maintenance_log
                   (id, device_id, epoch, technician, work_performed, notes)
                   VALUES (?,?,?,?,?,?)""",
                (maint_id, matched_did, now, f"redline:{plan.project}",
                 "\n".join(work_parts), ""),
            )
            result.maintenance_entries_created.append(maint_id)

            clue_detail = (
                f"endpoint.device='{ep.device}' matched topology device "
                f"'{matched_did}' via {tier}"
            )
            link_id = _record_link(
                conn, import_id,
                "job", str(job.index),
                "maintenance_log", maint_id,
                tier, confidence, clue_detail,
            )
            result.links_created.append({
                "link_id": link_id, "rl_key": f"job:{job.index}",
                "pg_id": matched_did, "tier": tier,
                "confidence": confidence,
            })

            # If the endpoint cites a drawing from the registry, record that
            # as a DRAWING_REF link too
            if ep.drawing and ep.drawing in plan.drawing_registry:
                _record_link(
                    conn, import_id,
                    "drawing", ep.drawing,
                    "device", matched_did,
                    "DRAWING_REF", 0.60,
                    _drawing_clue_detail(ep, ep.drawing),
                )


def _import_crows(
    conn: sqlite3.Connection,
    plan: WirePlan,
    topo: TopoIndex,
    import_id: str,
    result: ImportResult,
    now: int,
) -> None:
    """
    CROWs (outage records) become maintenance_log entries.
    They are attached to a sentinel device_id "STATION" because CROWs are
    station-level events, not device-specific.  If a topology device can be
    inferred from the project's history device list, a secondary link is also
    recorded.

    All CROWs cite the outage_number so the outage management system record
    can always be cross-referenced from the Poneglyph maintenance log.
    """
    for crow in plan.crows:
        outage_num = crow.get("outage_number", "").strip()
        url        = crow.get("url", "").strip()
        if not outage_num:
            continue

        work_performed = (
            f"CROW outage: {outage_num}"
            + (f"\nURL: {url}" if url else "")
            + f"\n[Red-Line-Routing project '{plan.project}', import_id={import_id}]"
        )

        maint_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO maintenance_log
               (id, device_id, epoch, technician, work_performed, notes)
               VALUES (?,?,?,?,?,?)""",
            (maint_id, "STATION", now, f"redline:{plan.project}",
             work_performed, outage_num),
        )
        result.maintenance_entries_created.append(maint_id)

        link_id = _record_link(
            conn, import_id,
            "crow", outage_num,
            "maintenance_log", maint_id,
            "CROW_OUTAGE", 1.00,
            f"CROW outage number '{outage_num}' → maintenance_log",
        )
        result.links_created.append({
            "link_id": link_id, "rl_key": f"crow:{outage_num}",
            "pg_id": "STATION", "tier": "CROW_OUTAGE",
            "confidence": 1.00,
        })


# ─────────────────────────────────────────────────────────────────────────────────
# Station name inference
# ─────────────────────────────────────────────────────────────────────────────────

def _infer_station(plan: WirePlan, db_path: str) -> str:
    """
    Try to determine which Poneglyph station the wirePlan belongs to.

    Strategy (highest confidence first):
      1. project_info.station in the topology JSON (if topology was passed in)
      2. Station code appears in the project name string
      3. Known site DB station name appears in any device name or drawing name
    """
    try:
        info = _sdb.get_site_info(db_path)
        if info:
            station = info.get("station", "")
            proj_lo = plan.project.lower()
            # Check if the station code appears in the project name
            if station and station.lower() in proj_lo:
                return station
            # Check device history names
            devices_mentioned = set()
            for job in plan.jobs:
                for ep in job.all_endpoints():
                    if ep.device:
                        devices_mentioned.add(ep.device.upper())
            for dev_name in devices_mentioned:
                if station and station.upper() in dev_name:
                    return station
    except Exception:
        pass
    return ""


# ─────────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────────

def import_wireplan(
    wireplan_path: str,
    db_path: str,
    topology: dict | None = None,
    imported_by: str = "",
) -> ImportResult:
    """
    Import a .wirePlan file into the Poneglyph site DB at db_path.

    Parameters
    ----------
    wireplan_path : str
        Absolute or relative path to the .wirePlan JSON file.
    db_path : str
        Path to the site SQLite DB (e.g. sites/ALZ.db).
    topology : dict | None
        The current topology dict (from substation.json or the DB snapshot).
        If None, the module will try to load the latest snapshot from db_path.
    imported_by : str
        Name or identifier of the user triggering the import.

    Returns
    -------
    ImportResult
        Counts and IDs of everything created.
    """
    wireplan_path = os.path.abspath(wireplan_path)
    if not os.path.exists(wireplan_path):
        raise FileNotFoundError(f"wirePlan not found: {wireplan_path}")
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Site DB not found: {db_path}")

    _sdb.init_db(db_path)
    _ensure_redline_schema(db_path)

    plan = WirePlan.from_file(wireplan_path)
    log.info("Loaded wirePlan '%s' (%d jobs, %d relay settings, %d drawings, %d CROWs)",
             plan.project, len(plan.jobs),
             len(plan.relay_settings), len(plan.drawing_registry), len(plan.crows))

    if topology is None:
        topology = _sdb.get_latest_topology(db_path)
    topo = TopoIndex.build(topology)

    now = int(time.time())
    import_id = str(uuid.uuid4())
    station_guess = _infer_station(plan, db_path)

    result = ImportResult(import_id=import_id, project=plan.project)

    with _conn(db_path) as conn:
        conn.execute(
            """INSERT INTO redline_imports
               (id, epoch, wireplan_path, project_name, station_guess,
                imported_by, job_count, relay_count, drawing_count, crow_count)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                import_id, now, wireplan_path, plan.project,
                station_guess, imported_by,
                len(plan.jobs), len(plan.relay_settings),
                len(plan.drawing_registry), len(plan.crows),
            ),
        )

        _import_relay_settings(conn, plan, topo, import_id, result, now)
        _import_drawing_registry(conn, plan, topo, import_id, result, now)
        _import_testing_jobs(conn, plan, topo, import_id, result, now)
        _import_block_unblock_jobs(conn, plan, topo, import_id, result, now)
        _import_wire_jobs(conn, plan, topo, import_id, result, now)
        _import_crows(conn, plan, topo, import_id, result, now)

        linked_devices = len({
            lnk["pg_id"]
            for lnk in result.links_created
            if topo.by_id.get(lnk["pg_id"])
        })
        conn.execute(
            """UPDATE redline_imports
               SET linked_device_count = ?
               WHERE id = ?""",
            (linked_devices, import_id),
        )

    log.info("Import complete: %s", result.summary)
    return result


def import_wireplan_from_dict(
    wireplan_data: dict,
    db_path: str,
    topology: dict | None = None,
    imported_by: str = "",
    source_label: str = "<inline>",
) -> ImportResult:
    """
    Same as import_wireplan() but accepts an already-parsed dict instead of a
    file path.  Useful when the API receives the .wirePlan as an uploaded JSON
    body rather than a file on disk.
    """
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Site DB not found: {db_path}")

    _sdb.init_db(db_path)
    _ensure_redline_schema(db_path)

    plan = WirePlan.from_dict(wireplan_data)
    log.info("Loaded wirePlan dict '%s'", plan.project)

    if topology is None:
        topology = _sdb.get_latest_topology(db_path)
    topo = TopoIndex.build(topology)

    now = int(time.time())
    import_id = str(uuid.uuid4())
    station_guess = _infer_station(plan, db_path)

    result = ImportResult(import_id=import_id, project=plan.project)

    with _conn(db_path) as conn:
        conn.execute(
            """INSERT INTO redline_imports
               (id, epoch, wireplan_path, project_name, station_guess,
                imported_by, job_count, relay_count, drawing_count, crow_count)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                import_id, now, source_label, plan.project,
                station_guess, imported_by,
                len(plan.jobs), len(plan.relay_settings),
                len(plan.drawing_registry), len(plan.crows),
            ),
        )
        _import_relay_settings(conn, plan, topo, import_id, result, now)
        _import_drawing_registry(conn, plan, topo, import_id, result, now)
        _import_testing_jobs(conn, plan, topo, import_id, result, now)
        _import_block_unblock_jobs(conn, plan, topo, import_id, result, now)
        _import_wire_jobs(conn, plan, topo, import_id, result, now)
        _import_crows(conn, plan, topo, import_id, result, now)

        linked_devices = len({
            lnk["pg_id"]
            for lnk in result.links_created
            if topo.by_id.get(lnk["pg_id"])
        })
        conn.execute(
            "UPDATE redline_imports SET linked_device_count = ? WHERE id = ?",
            (linked_devices, import_id),
        )

    log.info("Import complete: %s", result.summary)
    return result


# ─────────────────────────────────────────────────────────────────────────────────
# Query helpers
# ─────────────────────────────────────────────────────────────────────────────────

def list_imports(db_path: str) -> list[dict]:
    """Return all redline_imports rows for a site, newest first."""
    _ensure_redline_schema(db_path)
    with _conn(db_path) as c:
        rows = c.execute(
            """SELECT id, epoch, wireplan_path, project_name, station_guess,
                      imported_by, job_count, relay_count, drawing_count,
                      crow_count, linked_device_count
               FROM redline_imports
               ORDER BY epoch DESC"""
        ).fetchall()
    return [dict(r) for r in rows]


def get_import_links(db_path: str, import_id: str) -> list[dict]:
    """Return every correlation link created by one import."""
    _ensure_redline_schema(db_path)
    with _conn(db_path) as c:
        rows = c.execute(
            """SELECT id, epoch, rl_entity_type, rl_entity_key,
                      pg_entity_type, pg_entity_id,
                      clue_tier, confidence, clue_detail
               FROM redline_links
               WHERE import_id = ?
               ORDER BY confidence DESC, epoch ASC""",
            (import_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_device_wireplan_links(db_path: str, device_id: str) -> list[dict]:
    """
    Return all redline_links that point at a specific topology device,
    joined with the import project name for context.  Useful for surfacing
    wire-plan history on a device's detail panel in the UI.
    """
    _ensure_redline_schema(db_path)
    with _conn(db_path) as c:
        rows = c.execute(
            """SELECT l.id, l.epoch, l.rl_entity_type, l.rl_entity_key,
                      l.pg_entity_type, l.pg_entity_id,
                      l.clue_tier, l.confidence, l.clue_detail,
                      i.project_name, i.wireplan_path, i.imported_by
               FROM redline_links l
               JOIN redline_imports i ON i.id = l.import_id
               WHERE l.pg_entity_id = ?
               ORDER BY l.epoch DESC""",
            (device_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def rollback_import(db_path: str, import_id: str) -> int:
    """
    Delete the redline_imports row.  All redline_links rows cascade-delete
    automatically (ON DELETE CASCADE).  Content rows (device_drawings,
    maintenance_log, tests) created by the import are NOT automatically
    deleted because they may have been edited since import; call
    rollback_import_full() if you want those too.

    Returns the number of redline_links rows deleted.
    """
    _ensure_redline_schema(db_path)
    with _conn(db_path) as c:
        count = c.execute(
            "SELECT COUNT(*) FROM redline_links WHERE import_id = ?",
            (import_id,),
        ).fetchone()[0]
        c.execute("DELETE FROM redline_imports WHERE id = ?", (import_id,))
    return count


def rollback_import_full(db_path: str, import_id: str) -> dict[str, int]:
    """
    Full rollback: delete the import header AND all content rows created by
    the import (device_drawings, maintenance_log, tests) by cross-referencing
    the redline_links table before deleting it.

    Returns a dict of {table: rows_deleted}.
    """
    _ensure_redline_schema(db_path)
    deleted: dict[str, int] = {
        "device_drawings": 0,
        "maintenance_log": 0,
        "tests": 0,
        "redline_links": 0,
    }
    with _conn(db_path) as c:
        links = c.execute(
            "SELECT pg_entity_type, pg_entity_id FROM redline_links WHERE import_id = ?",
            (import_id,),
        ).fetchall()

        by_type: dict[str, list[str]] = defaultdict(list)
        for lnk in links:
            by_type[lnk["pg_entity_type"]].append(lnk["pg_entity_id"])

        for drawing_id in set(by_type.get("device_drawing", [])):
            cur = c.execute("DELETE FROM device_drawings WHERE id = ?", (drawing_id,))
            deleted["device_drawings"] += cur.rowcount

        for maint_id in set(by_type.get("maintenance_log", [])):
            cur = c.execute("DELETE FROM maintenance_log WHERE id = ?", (maint_id,))
            deleted["maintenance_log"] += cur.rowcount

        for test_id in set(by_type.get("test", [])):
            cur = c.execute("DELETE FROM tests WHERE id = ?", (test_id,))
            deleted["tests"] += cur.rowcount

        deleted["redline_links"] = len(links)
        c.execute("DELETE FROM redline_imports WHERE id = ?", (import_id,))

    return deleted


def explain_import(db_path: str, import_id: str) -> str:
    """Return a human-readable audit report for one import."""
    _ensure_redline_schema(db_path)
    with _conn(db_path) as c:
        imp = c.execute(
            "SELECT * FROM redline_imports WHERE id = ?", (import_id,)
        ).fetchone()
        if not imp:
            return f"No import found with id={import_id}"

        links = c.execute(
            """SELECT rl_entity_type, rl_entity_key, pg_entity_type, pg_entity_id,
                      clue_tier, confidence, clue_detail
               FROM redline_links WHERE import_id = ?
               ORDER BY confidence DESC""",
            (import_id,),
        ).fetchall()

    lines = [
        f"── Red-Line-Routing Import Report ─────────────────────────────────",
        f"  Import ID   : {import_id}",
        f"  Project     : {imp['project_name']}",
        f"  File        : {imp['wireplan_path']}",
        f"  Imported by : {imp['imported_by'] or '(unknown)'}",
        f"  Date        : {_epoch_str(imp['epoch'])}",
        f"  Station     : {imp['station_guess'] or '(not inferred)'}",
        f"",
        f"  Jobs in plan    : {imp['job_count']}",
        f"  Relay settings  : {imp['relay_count']}",
        f"  Drawings        : {imp['drawing_count']}",
        f"  CROWs           : {imp['crow_count']}",
        f"  Linked devices  : {imp['linked_device_count']}",
        f"",
        f"── Correlation Links ({len(links)}) ────────────────────────────────",
    ]

    tier_order = ["ID_EXACT", "WO_LINK", "PROT_EQUIP", "NORM_NAME",
                  "SEC_LOCATION", "PANEL_HIT", "DRAWING_REF",
                  "JOB_TYPE_TESTING", "CROW_OUTAGE", "TOKEN_MATCH"]
    by_tier: dict[str, list] = defaultdict(list)
    for lnk in links:
        by_tier[lnk["clue_tier"]].append(lnk)

    for tier in tier_order + [t for t in by_tier if t not in tier_order]:
        group = by_tier.get(tier, [])
        if not group:
            continue
        lines.append(f"\n  [{tier}]")
        for lnk in group:
            lines.append(
                f"    {lnk['rl_entity_type']:15s} '{lnk['rl_entity_key'][:30]}' "
                f" →  {lnk['pg_entity_type']:15s} '{lnk['pg_entity_id'][:36]}' "
                f" conf={lnk['confidence']:.2f}"
            )
            if lnk["clue_detail"]:
                lines.append(f"       ⤵ {lnk['clue_detail']}")

    return "\n".join(lines)


def _epoch_str(epoch: int) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
