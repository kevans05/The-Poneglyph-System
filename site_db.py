"""
SCADA Pro — Site-specific SQLite persistence layer.

Each substation site gets its own .db file under sites/.
UUID primary keys let two offline copies of the same site DB be merged by
simple row insertion — no ID conflicts possible.

Hierarchy:  Site DB → Tests → Sessions → Measurements
            Site DB → Tests → test_drawings

sites/
    ALZ.db
    XYZ.db
    ...
"""

import json
import os
import sqlite3
import time
import uuid

import topo_merge

SITES_DIR = "sites"


# ── Connection ────────────────────────────────────────────────────────────────

def _conn(db_path: str) -> sqlite3.Connection:
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    return c


# ── Schema ────────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS site_info (
    id            INTEGER PRIMARY KEY CHECK (id = 1),
    station       TEXT    NOT NULL,
    site_name     TEXT    DEFAULT '',
    description   TEXT    DEFAULT '',
    number_code   TEXT    DEFAULT '',
    gps_lat       REAL,
    gps_lon       REAL,
    created_epoch INTEGER NOT NULL,
    last_epoch    INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS snapshots (
    id        TEXT PRIMARY KEY,       -- UUID
    epoch     INTEGER NOT NULL,
    label     TEXT    NOT NULL,
    topology  TEXT    NOT NULL,       -- full substation.json blob
    author    TEXT    DEFAULT '',     -- operator display name
    author_id TEXT    DEFAULT ''      -- operator signature (PoneglyphIdentity id)
);
CREATE INDEX IF NOT EXISTS idx_snap_epoch ON snapshots(epoch DESC);

CREATE TABLE IF NOT EXISTS tests (
    id          TEXT    PRIMARY KEY,  -- UUID
    epoch       INTEGER NOT NULL,
    name        TEXT    NOT NULL,
    description TEXT    DEFAULT '',
    created_by  TEXT    DEFAULT '',
    status      TEXT    DEFAULT 'IN PROGRESS'
);
CREATE INDEX IF NOT EXISTS idx_test_epoch ON tests(epoch DESC);

CREATE TABLE IF NOT EXISTS test_drawings (
    id       TEXT PRIMARY KEY,        -- UUID
    test_id  TEXT NOT NULL REFERENCES tests(id) ON DELETE CASCADE,
    title    TEXT NOT NULL,
    url      TEXT DEFAULT '',
    revision TEXT DEFAULT '',
    notes    TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_draw_test ON test_drawings(test_id);

CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,     -- UUID
    epoch       INTEGER NOT NULL,
    label       TEXT    DEFAULT '',
    device      TEXT    DEFAULT '',
    instrument  TEXT    DEFAULT 'manual',
    technician  TEXT    DEFAULT '',
    technician_id TEXT  DEFAULT '',
    test_id     TEXT    REFERENCES tests(id) ON DELETE CASCADE,
    snapshot_id TEXT    REFERENCES snapshots(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_sess_epoch ON sessions(epoch DESC);

CREATE TABLE IF NOT EXISTS measurements (
    id         TEXT    PRIMARY KEY,   -- UUID
    session_id TEXT    REFERENCES sessions(id) ON DELETE CASCADE,
    epoch      INTEGER NOT NULL,
    device_id  TEXT    NOT NULL,
    key        TEXT    NOT NULL,
    value      REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_meas_epoch      ON measurements(epoch DESC);
CREATE INDEX IF NOT EXISTS idx_meas_device_key ON measurements(device_id, key);
CREATE INDEX IF NOT EXISTS idx_meas_session    ON measurements(session_id);

CREATE TABLE IF NOT EXISTS device_history (
    id          TEXT    PRIMARY KEY,   -- UUID
    device_id   TEXT    NOT NULL,
    epoch       INTEGER NOT NULL,
    type        TEXT,
    status      TEXT,
    config      TEXT,                  -- JSON blob of params
    snapshot_id TEXT    REFERENCES snapshots(id) ON DELETE CASCADE,
    author      TEXT    DEFAULT '',    -- operator display name
    author_id   TEXT    DEFAULT ''     -- operator signature
);
CREATE INDEX IF NOT EXISTS idx_dev_hist_id    ON device_history(device_id);
CREATE INDEX IF NOT EXISTS idx_dev_hist_epoch ON device_history(epoch DESC);

-- Poneglyph Hub: local mirror of the substation version graph + the link row.
CREATE TABLE IF NOT EXISTS substation_versions (
    id            TEXT PRIMARY KEY,           -- content hash (topo_merge.content_hash)
    parent_id     TEXT    NOT NULL DEFAULT '',
    merge_parent  TEXT    NOT NULL DEFAULT '',
    branch        TEXT    NOT NULL DEFAULT 'main',
    epoch         INTEGER NOT NULL,
    author        TEXT    NOT NULL DEFAULT '',
    author_id     TEXT    NOT NULL DEFAULT '',
    message       TEXT    NOT NULL DEFAULT '',
    topology      TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS hub_sync (
    id            INTEGER PRIMARY KEY CHECK (id = 1),
    hub_url       TEXT    NOT NULL DEFAULT '',
    substation_id TEXT    NOT NULL DEFAULT '',
    base_id       TEXT    NOT NULL DEFAULT '',   -- last version pulled clean
    head_id       TEXT    NOT NULL DEFAULT '',   -- local tip
    branch        TEXT    NOT NULL DEFAULT 'main',
    linked_epoch  INTEGER NOT NULL DEFAULT 0
);

-- Device serial number changelog.
-- Each row records a serial number assignment or change for a physical device.
-- This lets you track relay swaps, CT replacements, etc. over time.
-- Inventory fields (manufacturer, model_number, etc.) describe the physical unit
-- assigned at that point in time.
CREATE TABLE IF NOT EXISTS device_serials (
    id                TEXT    PRIMARY KEY,   -- UUID
    device_id         TEXT    NOT NULL,      -- logical device ID in the topology
    epoch             INTEGER NOT NULL,      -- when the serial was recorded
    serial            TEXT    NOT NULL,      -- serial number string (free-form)
    notes             TEXT    DEFAULT '',    -- reason for change (e.g. "replaced after failure")
    technician        TEXT    DEFAULT '',    -- who made the change
    manufacturer      TEXT    DEFAULT '',
    model_number      TEXT    DEFAULT '',
    asset_tag         TEXT    DEFAULT '',
    manufacture_date  TEXT    DEFAULT '',    -- ISO date string (YYYY-MM-DD)
    installation_date TEXT    DEFAULT '',
    in_service_date   TEXT    DEFAULT '',
    firmware_version  TEXT    DEFAULT '',
    status            TEXT    DEFAULT 'active'  -- active | spare | out_of_service | retired
);
CREATE INDEX IF NOT EXISTS idx_serials_device ON device_serials(device_id);
CREATE INDEX IF NOT EXISTS idx_serials_epoch  ON device_serials(epoch DESC);

CREATE TABLE IF NOT EXISTS device_drawings (
    id        TEXT PRIMARY KEY,   -- UUID
    device_id TEXT NOT NULL,      -- logical device ID in the topology
    title     TEXT NOT NULL,
    url       TEXT DEFAULT '',
    revision  TEXT DEFAULT '',
    notes     TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_dev_draw_device ON device_drawings(device_id);

-- Append-only log of revision changes on device_drawings rows.
-- The device_drawings row is updated in-place; this table preserves what
-- revision was current before the change, so history is never lost.
-- test_drawings rows are frozen by design (one row per test) and are never
-- logged here — their revision is immutable once the drawing is added.
CREATE TABLE IF NOT EXISTS drawing_revision_log (
    id           TEXT    PRIMARY KEY,
    drawing_id   TEXT    NOT NULL,    -- device_drawings.id
    old_revision TEXT    DEFAULT '',
    new_revision TEXT    NOT NULL,
    old_url      TEXT    DEFAULT '',
    new_url      TEXT    DEFAULT '',
    epoch        INTEGER NOT NULL,
    updated_by   TEXT    DEFAULT '',
    notes        TEXT    DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_draw_rev_log ON drawing_revision_log(drawing_id);

-- Cached list of every revision the corporate drawing system holds for one
-- drawing number.  Bound to attached drawings so a technician holding rev C
-- can see that A / B / D exist and swap to one.  Refreshed on demand.
CREATE TABLE IF NOT EXISTS drawing_revision_sets (
    drawing_number TEXT    PRIMARY KEY,
    revisions      TEXT    NOT NULL DEFAULT '[]',  -- JSON: [{revision,state,title,document_url,...}]
    fetched_epoch  INTEGER NOT NULL DEFAULT 0,
    source         TEXT    NOT NULL DEFAULT 'corporate-search'
);

CREATE TABLE IF NOT EXISTS maintenance_log (
    id             TEXT    PRIMARY KEY,   -- UUID
    device_id      TEXT    NOT NULL,      -- logical device ID in the topology
    serial         TEXT    DEFAULT '',    -- which physical unit (links to device_serials.serial)
    epoch          INTEGER NOT NULL,
    technician     TEXT    DEFAULT '',
    work_performed TEXT    DEFAULT '',
    notes          TEXT    DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_maint_device ON maintenance_log(device_id);
CREATE INDEX IF NOT EXISTS idx_maint_epoch  ON maintenance_log(epoch DESC);
"""

# Columns added after initial release — applied to existing DBs on open.
# The device_serials table is created by _SCHEMA (via CREATE TABLE IF NOT EXISTS),
# so it does not need a column migration entry.
_MIGRATIONS = [
    ("site_info",  "site_name",   "TEXT    DEFAULT ''"),
    ("site_info",  "number_code", "TEXT    DEFAULT ''"),
    ("site_info",  "gps_lat",     "REAL"),
    ("site_info",  "gps_lon",     "REAL"),
    ("sessions",   "technician",    "TEXT    DEFAULT ''"),
    ("sessions",   "technician_id", "TEXT    DEFAULT ''"),
    ("sessions",   "test_id",       "TEXT"),
    ("snapshots",       "author",    "TEXT    DEFAULT ''"),
    ("snapshots",       "author_id", "TEXT    DEFAULT ''"),
    ("device_history",  "author",    "TEXT    DEFAULT ''"),
    ("device_history",  "author_id", "TEXT    DEFAULT ''"),
    ("tests",          "vref_label",        "TEXT    DEFAULT ''"),
    ("tests",          "vref_magnitude",    "REAL"),
    ("tests",          "capture_points",    "TEXT    DEFAULT \"[]\""),
    ("tests",          "origin",            "TEXT    DEFAULT 'local'"),
    ("device_serials", "manufacturer",      "TEXT    DEFAULT ''"),
    ("device_serials", "model_number",      "TEXT    DEFAULT ''"),
    ("device_serials", "asset_tag",         "TEXT    DEFAULT ''"),
    ("device_serials", "manufacture_date",  "TEXT    DEFAULT ''"),
    ("device_serials", "installation_date", "TEXT    DEFAULT ''"),
    ("device_serials", "in_service_date",   "TEXT    DEFAULT ''"),
    ("device_serials", "firmware_version",  "TEXT    DEFAULT ''"),
    ("device_serials", "status",            "TEXT    DEFAULT 'active'"),
    ("device_drawings", "drawing_number",   "TEXT    DEFAULT ''"),
    ("test_drawings",   "drawing_number",   "TEXT    DEFAULT ''"),
]


def init_db(db_path: str):
    """Create tables / apply column migrations on an existing or new DB file."""
    with _conn(db_path) as c:
        c.executescript(_SCHEMA)
        existing_cols: dict[str, set] = {}
        for table, col, typedef in _MIGRATIONS:
            if table not in existing_cols:
                rows = c.execute(f"PRAGMA table_info({table})").fetchall()
                existing_cols[table] = {r["name"] for r in rows}
            if col not in existing_cols[table]:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typedef}")
                existing_cols[table].add(col)


# ── Site management ───────────────────────────────────────────────────────────

def db_path_for(station: str) -> str:
    return os.path.join(SITES_DIR, f"{station}.db")

def create_site(
    station: str,
    site_name: str = "",
    description: str = "",
    number_code: str = "",
    gps_lat: float | None = None,
    gps_lon: float | None = None,
    topology: dict | None = None,
) -> str:
    """Create a new site DB. Returns its path. Raises if it already exists."""
    os.makedirs(SITES_DIR, exist_ok=True)
    path = db_path_for(station)
    if os.path.exists(path):
        raise FileExistsError(f"Site '{station}' already exists")
    init_db(path)
    now = int(time.time())
    with _conn(path) as c:
        c.execute(
            """INSERT INTO site_info
               (id, station, site_name, description, number_code,
                gps_lat, gps_lon, created_epoch, last_epoch)
               VALUES (1,?,?,?,?,?,?,?,?)""",
            (station, site_name or "", description or "",
             number_code or "",
             gps_lat, gps_lon, now, now),
        )
    if topology:
        save_snapshot(path, label="Initial topology", topology=topology)
    return path

def list_sites() -> list[dict]:
    """Return metadata for every site DB found in SITES_DIR, including its Hub
    link state — lazily migrates each DB first so older site files pick up
    newer tables/columns (hub_sync included) just by being listed."""
    if not os.path.exists(SITES_DIR):
        return []
    sites = []
    for fname in sorted(os.listdir(SITES_DIR)):
        if not fname.endswith(".db"):
            continue
        path = os.path.join(SITES_DIR, fname)
        try:
            init_db(path)
            with _conn(path) as c:
                info = c.execute("SELECT * FROM site_info LIMIT 1").fetchone()
                if info is None:
                    continue
                sess_count = c.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
                snap_count = c.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
                last_sess = c.execute(
                    "SELECT epoch FROM sessions ORDER BY epoch DESC LIMIT 1"
                ).fetchone()
                sync_row = c.execute(
                    "SELECT hub_url, substation_id, base_id, head_id FROM hub_sync WHERE id = 1"
                ).fetchone()
            ahead = 0
            if sync_row and sync_row["substation_id"] and sync_row["base_id"] and sync_row["head_id"]:
                ahead = len(local_versions_between(path, sync_row["base_id"], sync_row["head_id"]))
            sites.append({
                "station": info["station"],
                "description": info["description"],
                "number_code": info["number_code"] if "number_code" in info.keys() else "",
                "created_epoch": info["created_epoch"],
                "last_epoch": last_sess["epoch"] if last_sess else info["created_epoch"],
                "session_count": sess_count,
                "snapshot_count": snap_count,
                "db_path": path,
                "hub_linked": bool(sync_row and sync_row["substation_id"]),
                "hub_url": (sync_row["hub_url"] if sync_row else "") or "",
                "hub_substation_id": (sync_row["substation_id"] if sync_row else "") or "",
                "hub_ahead": ahead,
            })
        except Exception:
            pass
    return sorted(sites, key=lambda s: s["station"])

def get_site_info(db_path: str) -> dict | None:
    try:
        with _conn(db_path) as c:
            row = c.execute("SELECT * FROM site_info LIMIT 1").fetchone()
        return dict(row) if row else None
    except Exception:
        return None


_EDITABLE_SITE_FIELDS = {
    "site_name", "description", "number_code", "gps_lat", "gps_lon",
}


def update_site_info(db_path: str, fields: dict) -> dict | None:
    """Patch editable site_info columns. Returns the new row or None on failure.

    `station` is the immutable primary identifier (it's also the filename) and
    is never updated here.
    """
    keep = {k: v for k, v in fields.items() if k in _EDITABLE_SITE_FIELDS}
    if not keep:
        return get_site_info(db_path)
    cols = ", ".join(f"{k} = ?" for k in keep)
    params = list(keep.values()) + [int(time.time())]
    with _conn(db_path) as c:
        c.execute(
            f"UPDATE site_info SET {cols}, last_epoch = ? WHERE id = 1",
            params,
        )
    return get_site_info(db_path)


def _touch(db_path: str):
    """Update last_epoch to now."""
    try:
        with _conn(db_path) as c:
            c.execute("UPDATE site_info SET last_epoch = ? WHERE id = 1", (int(time.time()),))
    except Exception:
        pass


# ── Snapshots ─────────────────────────────────────────────────────────────────

def save_snapshot(
    db_path: str,
    label: str,
    topology: dict | str,
    record_device_history: bool = True,
    author: str = "",
    author_id: str = "",
) -> str:
    """Persist a topology snapshot. Returns the UUID row id.

    `author` / `author_id` record which operator made the change (display name
    and PoneglyphIdentity signature).

    When `record_device_history` is True, also writes one row per device to
    `device_history` for long-term per-device config audit trail. Disable for
    high-frequency auto-saves to keep the table from ballooning.
    """
    topo_dict = json.loads(topology) if isinstance(topology, str) else topology
    blob = json.dumps(topo_dict, indent=2)
    row_id = str(uuid.uuid4())
    now = int(time.time())
    author = author or ""
    author_id = author_id or ""
    with _conn(db_path) as c:
        c.execute(
            "INSERT INTO snapshots (id, epoch, label, topology, author, author_id) VALUES (?,?,?,?,?,?)",
            (row_id, now, label, blob, author, author_id),
        )
        if record_device_history:
            history_rows = []
            for d in topo_dict.get("devices", []):
                did = d.get("id")
                if not did:
                    continue
                config = {k: v for k, v in d.items() if k not in ("id", "type", "status")}
                history_rows.append((
                    str(uuid.uuid4()),
                    did,
                    now,
                    d.get("type"),
                    d.get("status"),
                    json.dumps(config),
                    row_id,
                    author,
                    author_id,
                ))
            if history_rows:
                c.executemany(
                    """INSERT INTO device_history
                       (id, device_id, epoch, type, status, config, snapshot_id, author, author_id)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    history_rows,
                )
    _touch(db_path)
    return row_id

def list_snapshots(db_path: str, limit: int = 100) -> list[dict]:
    with _conn(db_path) as c:
        rows = c.execute(
            "SELECT id, epoch, label, author, author_id FROM snapshots ORDER BY epoch DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]

def get_snapshot_topology(db_path: str, snapshot_id: str) -> dict | None:
    with _conn(db_path) as c:
        row = c.execute(
            "SELECT topology FROM snapshots WHERE id = ?", (snapshot_id,)
        ).fetchone()
    return json.loads(row["topology"]) if row else None

def get_latest_topology(db_path: str) -> dict | None:
    """Return the most recent snapshot topology, or None if none exist."""
    with _conn(db_path) as c:
        row = c.execute(
            "SELECT topology FROM snapshots ORDER BY epoch DESC LIMIT 1"
        ).fetchone()
    return json.loads(row["topology"]) if row else None

def delete_snapshot(db_path: str, snapshot_id: str):
    with _conn(db_path) as c:
        c.execute("DELETE FROM sessions WHERE snapshot_id = ?", (snapshot_id,))
        c.execute("DELETE FROM snapshots WHERE id = ?", (snapshot_id,))


# ── Tests ─────────────────────────────────────────────────────────────────────

def create_test(db_path: str, name: str, description: str = "", created_by: str = "") -> str:
    row_id = str(uuid.uuid4())
    with _conn(db_path) as c:
        c.execute(
            "INSERT INTO tests (id, epoch, name, description, created_by) VALUES (?,?,?,?,?)",
            (row_id, int(time.time()), name, description or "", created_by or ""),
        )
    _touch(db_path)
    return row_id

def list_tests(db_path: str) -> list[dict]:
    with _conn(db_path) as c:
        rows = c.execute(
            """SELECT t.id, t.epoch, t.name, t.description, t.created_by, t.status,
                      t.origin,
                      COUNT(DISTINCT d.id) AS drawing_count,
                      COUNT(DISTINCT s.id) AS session_count
               FROM tests t
               LEFT JOIN test_drawings d ON d.test_id = t.id
               LEFT JOIN sessions s ON s.test_id = t.id
               GROUP BY t.id
               ORDER BY t.epoch DESC"""
        ).fetchall()
    return [dict(r) for r in rows]

def get_test(db_path: str, test_id: str) -> dict | None:
    with _conn(db_path) as c:
        row = c.execute("SELECT * FROM tests WHERE id = ?", (test_id,)).fetchone()
    return dict(row) if row else None

def update_test_status(db_path: str, test_id: str, status: str):
    with _conn(db_path) as c:
        c.execute("UPDATE tests SET status = ? WHERE id = ?", (status, test_id))

def set_test_vref(db_path: str, test_id: str, label: str, magnitude: float | None):
    """Store the system reference VT for a test. Angle is always 0 by definition."""
    with _conn(db_path) as c:
        c.execute(
            "UPDATE tests SET vref_label = ?, vref_magnitude = ? WHERE id = ?",
            (label or "", magnitude, test_id),
        )

def delete_test(db_path: str, test_id: str):
    with _conn(db_path) as c:
        c.execute("DELETE FROM sessions WHERE test_id = ?", (test_id,))
        c.execute("DELETE FROM tests WHERE id = ?", (test_id,))


# ── Test Drawings ─────────────────────────────────────────────────────────────

def add_drawing(db_path: str, test_id: str, title: str, url: str = "", revision: str = "",
                notes: str = "", drawing_number: str = "") -> str:
    row_id = str(uuid.uuid4())
    with _conn(db_path) as c:
        c.execute(
            "INSERT INTO test_drawings (id, test_id, title, url, revision, notes, drawing_number) VALUES (?,?,?,?,?,?,?)",
            (row_id, test_id, title, url or "", revision or "", notes or "", drawing_number or ""),
        )
    return row_id

def list_drawings(db_path: str, test_id: str) -> list[dict]:
    with _conn(db_path) as c:
        rows = c.execute(
            "SELECT * FROM test_drawings WHERE test_id = ? ORDER BY rowid ASC",
            (test_id,),
        ).fetchall()
    return [dict(r) for r in rows]

def delete_drawing(db_path: str, drawing_id: str):
    with _conn(db_path) as c:
        c.execute("DELETE FROM test_drawings WHERE id = ?", (drawing_id,))


# ── Sessions ──────────────────────────────────────────────────────────────────

def start_session(db_path: str, label: str = "", device: str = "", instrument: str = "manual", technician: str = "", test_id: str | None = None, snapshot_id: str | None = None, technician_id: str = "") -> str:
    row_id = str(uuid.uuid4())
    with _conn(db_path) as c:
        c.execute(
            """INSERT INTO sessions (id, epoch, label, device, instrument, technician, technician_id, test_id, snapshot_id)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (row_id, int(time.time()), label, device or "", instrument, technician or "", technician_id or "", test_id, snapshot_id),
        )
    _touch(db_path)
    return row_id

def list_sessions(db_path: str, limit: int = 100, test_id: str | None = None) -> list[dict]:
    where = "WHERE s.test_id = ?" if test_id else ""
    params = [test_id, limit] if test_id else [limit]
    with _conn(db_path) as c:
        rows = c.execute(
            f"""SELECT s.id, s.epoch, s.label, s.device, s.instrument,
                       s.technician, s.technician_id, s.test_id, s.snapshot_id,
                       t.name AS test_name,
                       COUNT(m.id) AS reading_count
               FROM sessions s
               LEFT JOIN tests t ON t.id = s.test_id
               LEFT JOIN measurements m ON m.session_id = s.id
               {where}
               GROUP BY s.id
               ORDER BY s.epoch DESC
               LIMIT ?""",
            params,
        ).fetchall()
    return [dict(r) for r in rows]

def get_session(db_path: str, session_id: str) -> dict | None:
    with _conn(db_path) as c:
        row = c.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    return dict(row) if row else None

def delete_session(db_path: str, session_id: str):
    with _conn(db_path) as c:
        c.execute("DELETE FROM sessions WHERE id = ?", (session_id,))


# ── Measurements ──────────────────────────────────────────────────────────────

def record_measurements(db_path: str, session_id: str | None, device_id: str, measurements: dict, epoch: int | None = None):
    now = epoch or int(time.time())
    rows = [(str(uuid.uuid4()), session_id, now, device_id, k, float(v)) for k, v in measurements.items() if isinstance(v, (int, float))]
    if not rows: return
    with _conn(db_path) as c:
        c.executemany("INSERT INTO measurements (id, session_id, epoch, device_id, key, value) VALUES (?,?,?,?,?,?)", rows)
    _touch(db_path)

def get_session_measurements(db_path: str, session_id: str) -> dict:
    with _conn(db_path) as c:
        rows = c.execute("SELECT epoch, device_id, key, value FROM measurements WHERE session_id = ? ORDER BY epoch ASC", (session_id,)).fetchall()
    by_device = {}
    for r in rows:
        by_device.setdefault(r["device_id"], {}).setdefault(r["key"], []).append({"epoch": r["epoch"], "value": r["value"]})
    return by_device

def get_device_history(db_path: str, device_id: str, key: str, limit: int = 200) -> list[dict]:
    with _conn(db_path) as c:
        rows = c.execute("""SELECT m.epoch, m.value, m.session_id, s.label, s.instrument FROM measurements m LEFT JOIN sessions s ON s.id = m.session_id WHERE m.device_id = ? AND m.key = ? ORDER BY m.epoch DESC LIMIT ?""", (device_id, key, limit)).fetchall()
    return [dict(r) for r in rows]

def get_test_device_ids(db_path: str, test_id: str) -> list[str]:
    with _conn(db_path) as c:
        rows = c.execute("""
            SELECT DISTINCT m.device_id FROM measurements m
            JOIN sessions s ON s.id = m.session_id
            WHERE s.test_id = ?
        """, (test_id,)).fetchall()
    return [r["device_id"] for r in rows]

def get_test_report_data(db_path: str, test_id: str) -> dict | None:
    with _conn(db_path) as c:
        test = c.execute("SELECT * FROM tests WHERE id = ?", (test_id,)).fetchone()
        if not test:
            return None
        site_row  = c.execute("SELECT * FROM site_info LIMIT 1").fetchone()
        drawings  = c.execute(
            "SELECT * FROM test_drawings WHERE test_id = ? ORDER BY rowid", (test_id,)
        ).fetchall()
        sessions  = c.execute(
            "SELECT * FROM sessions WHERE test_id = ? ORDER BY epoch ASC, rowid ASC", (test_id,)
        ).fetchall()

        all_meas = c.execute("""
            SELECT m.session_id, m.device_id, m.key, m.value, m.epoch
            FROM measurements m
            JOIN sessions s ON s.id = m.session_id
            WHERE s.test_id = ?
            ORDER BY m.device_id, m.epoch DESC
        """, (test_id,)).fetchall()

        meas_by_session: dict = {}
        seen: set = set()
        for row in all_meas:
            dk = (row["session_id"], row["device_id"], row["key"])
            if dk not in seen:
                seen.add(dk)
                meas_by_session.setdefault(row["session_id"], {}) \
                    .setdefault(row["device_id"], {})[row["key"]] = {
                        "value": row["value"],
                        "epoch": row["epoch"],
                    }

        session_data = [
            {**dict(sess), "by_device": meas_by_session.get(sess["id"], {})}
            for sess in sessions
        ]

        return {
            "site":     dict(site_row) if site_row else {},
            "test":     dict(test),
            "drawings": [dict(d) for d in drawings],
            "sessions": session_data,
        }

def get_device_config_history(db_path: str, device_id: str, limit: int = 100) -> list[dict]:
    with _conn(db_path) as c:
        rows = c.execute("""SELECT h.epoch, h.type, h.status, h.config, h.snapshot_id, h.author, h.author_id, s.label as snapshot_label FROM device_history h LEFT JOIN snapshots s ON s.id = h.snapshot_id WHERE h.device_id = ? ORDER BY h.epoch DESC LIMIT ?""", (device_id, limit)).fetchall()
    return [dict(r) for r in rows]

def update_test_capture_points(db_path: str, test_id: str, devices: list[str]):
    with _conn(db_path) as c:
        c.execute("UPDATE tests SET capture_points = ? WHERE id = ?", (json.dumps(devices), test_id))


# ── Hub test bundles ─────────────────────────────────────────────────────────

def export_test_bundle(db_path: str, test_id: str,
                       substation_id: str = "", substation_version: str = "") -> dict | None:
    """Assemble a self-contained bundle for one test: the test row, its
    sessions, every measurement, and its drawings. Shape matches the hub's
    POST /api/hub/tests contract."""
    with _conn(db_path) as c:
        test = c.execute("SELECT * FROM tests WHERE id = ?", (test_id,)).fetchone()
        if not test:
            return None
        sessions = c.execute(
            "SELECT * FROM sessions WHERE test_id = ? ORDER BY epoch ASC, rowid ASC",
            (test_id,),
        ).fetchall()
        sess_ids = [s["id"] for s in sessions]
        measurements = []
        if sess_ids:
            ph = ",".join("?" * len(sess_ids))
            measurements = c.execute(
                f"""SELECT id, session_id, epoch, device_id, key, value
                    FROM measurements WHERE session_id IN ({ph})
                    ORDER BY epoch ASC, rowid ASC""",
                sess_ids,
            ).fetchall()
        drawings = c.execute(
            "SELECT id, title, url, revision, notes, drawing_number FROM test_drawings WHERE test_id = ? ORDER BY rowid ASC",
            (test_id,),
        ).fetchall()

    if not substation_version:
        substation_version = (sessions[0]["snapshot_id"] if sessions else "") or ""

    t = dict(test)
    return {
        "test": {
            "id": t["id"],
            "name": t.get("name", ""),
            "description": t.get("description", ""),
            "status": t.get("status", ""),
            "epoch": t.get("epoch"),
            "created_by": t.get("created_by", ""),
            "capture_points": json.loads(t.get("capture_points") or "[]"),
            "vref_label": t.get("vref_label", ""),
            "vref_magnitude": t.get("vref_magnitude"),
        },
        "sessions": [dict(s) for s in sessions],
        "measurements": [dict(m) for m in measurements],
        "drawings": [dict(d) for d in drawings],
        "substation": {"id": substation_id, "version": substation_version},
    }


def import_test_bundle(db_path: str, bundle: dict, origin: str = "hub") -> dict:
    """Insert a pulled bundle into this site DB. Idempotent by row id — an
    already-present test / session / measurement / drawing is left untouched.
    Returns {test_id, imported}."""
    t = bundle.get("test") or {}
    test_id = str(t.get("id") or "").strip()
    if not test_id:
        raise ValueError("bundle.test.id is required")

    now = int(time.time())
    with _conn(db_path) as c:
        existed = c.execute("SELECT 1 FROM tests WHERE id = ?", (test_id,)).fetchone()
        c.execute(
            """INSERT OR IGNORE INTO tests
               (id, epoch, name, description, created_by, status,
                vref_label, vref_magnitude, capture_points, origin)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                test_id,
                t.get("epoch") or now,
                t.get("name", ""),
                t.get("description", ""),
                t.get("created_by", ""),
                t.get("status", "COMPLETE"),
                t.get("vref_label", "") or "",
                t.get("vref_magnitude"),
                json.dumps(t.get("capture_points") or []),
                origin,
            ),
        )
        for s in bundle.get("sessions") or []:
            c.execute(
                """INSERT OR IGNORE INTO sessions
                   (id, epoch, label, device, instrument, technician,
                    technician_id, test_id, snapshot_id)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    s.get("id"),
                    s.get("epoch") or now,
                    s.get("label", "") or "",
                    s.get("device", "") or "",
                    s.get("instrument", "manual") or "manual",
                    s.get("technician", "") or "",
                    s.get("technician_id", "") or "",
                    test_id,
                    s.get("snapshot_id"),
                ),
            )
        meas = bundle.get("measurements") or []
        if meas:
            c.executemany(
                """INSERT OR IGNORE INTO measurements
                   (id, session_id, epoch, device_id, key, value)
                   VALUES (?,?,?,?,?,?)""",
                [
                    (m.get("id"), m.get("session_id"), m.get("epoch") or now,
                     m.get("device_id"), m.get("key"), m.get("value"))
                    for m in meas
                ],
            )
        for d in bundle.get("drawings") or []:
            c.execute(
                """INSERT OR IGNORE INTO test_drawings
                   (id, test_id, title, url, revision, notes, drawing_number)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    d.get("id"), test_id, d.get("title", "") or "",
                    d.get("url", "") or "", d.get("revision", "") or "",
                    d.get("notes", "") or "", d.get("drawing_number", "") or "",
                ),
            )
    _touch(db_path)
    return {"test_id": test_id, "imported": not existed}


# ── Device Serial Numbers ─────────────────────────────────────────────────────

def record_device_serial(
    db_path: str,
    device_id: str,
    serial: str,
    notes: str = "",
    technician: str = "",
    manufacturer: str = "",
    model_number: str = "",
    asset_tag: str = "",
    manufacture_date: str = "",
    installation_date: str = "",
    in_service_date: str = "",
    firmware_version: str = "",
    status: str = "active",
) -> str:
    """Record a serial number assignment or swap for a device.

    Returns the UUID of the new row.  Each call creates a new row so the full
    swap history is preserved — you can always trace what serial was installed
    at any point in time.
    """
    row_id = str(uuid.uuid4())
    with _conn(db_path) as c:
        c.execute(
            """INSERT INTO device_serials
               (id, device_id, epoch, serial, notes, technician,
                manufacturer, model_number, asset_tag,
                manufacture_date, installation_date, in_service_date,
                firmware_version, status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                row_id, device_id, int(time.time()), serial.strip(),
                notes.strip(), technician.strip(),
                manufacturer.strip(), model_number.strip(), asset_tag.strip(),
                manufacture_date.strip(), installation_date.strip(),
                in_service_date.strip(), firmware_version.strip(),
                status.strip() or "active",
            ),
        )
    _touch(db_path)
    return row_id


def update_device_serial(db_path: str, row_id: str, fields: dict) -> bool:
    """Update inventory fields on an existing device_serials row.

    Only the fields present in `fields` are updated.  Returns True if a row
    was matched.
    """
    allowed = {
        "manufacturer", "model_number", "asset_tag",
        "manufacture_date", "installation_date", "in_service_date",
        "firmware_version", "status", "notes", "technician",
    }
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return False
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    with _conn(db_path) as c:
        cur = c.execute(
            f"UPDATE device_serials SET {set_clause} WHERE id = ?",
            (*updates.values(), row_id),
        )
    _touch(db_path)
    return cur.rowcount > 0


def get_device_serials(db_path: str, device_id: str, limit: int = 50) -> list[dict]:
    """Return serial number history for a device, newest first."""
    with _conn(db_path) as c:
        rows = c.execute(
            """SELECT id, epoch, serial, notes, technician,
                      manufacturer, model_number, asset_tag,
                      manufacture_date, installation_date, in_service_date,
                      firmware_version, status
               FROM device_serials
               WHERE device_id = ?
               ORDER BY epoch DESC LIMIT ?""",
            (device_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def get_latest_serial(db_path: str, device_id: str) -> str | None:
    """Return the most recent serial number for a device, or None."""
    with _conn(db_path) as c:
        row = c.execute(
            "SELECT serial FROM device_serials WHERE device_id = ? ORDER BY epoch DESC LIMIT 1",
            (device_id,),
        ).fetchone()
    return row["serial"] if row else None


# ── Maintenance log ───────────────────────────────────────────────────────────

def add_maintenance_log(
    db_path: str,
    device_id: str,
    work_performed: str,
    serial: str = "",
    technician: str = "",
    notes: str = "",
) -> str:
    """Append a maintenance entry for a device. Returns the UUID of the new row."""
    row_id = str(uuid.uuid4())
    with _conn(db_path) as c:
        c.execute(
            """INSERT INTO maintenance_log
               (id, device_id, serial, epoch, technician, work_performed, notes)
               VALUES (?,?,?,?,?,?,?)""",
            (
                row_id, device_id, serial.strip(),
                int(time.time()), technician.strip(),
                work_performed.strip(), notes.strip(),
            ),
        )
    _touch(db_path)
    return row_id


def get_maintenance_log(db_path: str, device_id: str, limit: int = 100) -> list[dict]:
    """Return maintenance history for a device, newest first."""
    with _conn(db_path) as c:
        rows = c.execute(
            """SELECT id, epoch, serial, technician, work_performed, notes
               FROM maintenance_log
               WHERE device_id = ?
               ORDER BY epoch DESC LIMIT ?""",
            (device_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


# ── Device Drawings ───────────────────────────────────────────────────────────

def add_device_drawing(
    db_path: str,
    device_id: str,
    title: str,
    url: str = "",
    revision: str = "",
    notes: str = "",
    drawing_number: str = "",
) -> str:
    """Attach a drawing reference to a topology device. Returns the UUID."""
    row_id = str(uuid.uuid4())
    with _conn(db_path) as c:
        c.execute(
            """INSERT INTO device_drawings (id, device_id, title, url, revision, notes, drawing_number)
               VALUES (?,?,?,?,?,?,?)""",
            (row_id, device_id, title.strip(), url.strip(), revision.strip(),
             notes.strip(), (drawing_number or "").strip()),
        )
    _touch(db_path)
    return row_id


def list_device_drawings(db_path: str, device_id: str) -> list[dict]:
    """Return all drawings attached to a device, in insertion order."""
    with _conn(db_path) as c:
        rows = c.execute(
            "SELECT id, title, url, revision, notes, drawing_number FROM device_drawings WHERE device_id = ? ORDER BY rowid ASC",
            (device_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def delete_device_drawing(db_path: str, drawing_id: str):
    with _conn(db_path) as c:
        c.execute("DELETE FROM device_drawings WHERE id = ?", (drawing_id,))
    _touch(db_path)


def update_device_drawing(
    db_path: str,
    drawing_id: str,
    new_revision: str,
    new_url: str | None = None,
    updated_by: str = "",
    notes: str = "",
) -> str:
    """Update a device drawing's revision, logging the old values first.

    The old revision/url are written to drawing_revision_log so history is
    preserved.  If new_url is None the url is left unchanged.
    Returns the UUID of the log entry.
    """
    log_id = str(uuid.uuid4())
    with _conn(db_path) as c:
        row = c.execute(
            "SELECT revision, url FROM device_drawings WHERE id = ?", (drawing_id,)
        ).fetchone()
        if not row:
            raise ValueError(f"drawing_id {drawing_id!r} not found")
        old_revision = row["revision"] or ""
        old_url = row["url"] or ""
        resolved_url = new_url.strip() if new_url is not None else old_url
        c.execute(
            """INSERT INTO drawing_revision_log
               (id, drawing_id, old_revision, new_revision, old_url, new_url, epoch, updated_by, notes)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                log_id, drawing_id,
                old_revision, new_revision.strip(),
                old_url, resolved_url,
                int(time.time()), updated_by.strip(), notes.strip(),
            ),
        )
        c.execute(
            "UPDATE device_drawings SET revision = ?, url = ? WHERE id = ?",
            (new_revision.strip(), resolved_url, drawing_id),
        )
    _touch(db_path)
    return log_id


def get_drawing_revision_history(db_path: str, drawing_id: str) -> list[dict]:
    """Return the revision history for a device drawing, newest first."""
    with _conn(db_path) as c:
        rows = c.execute(
            """SELECT id, epoch, old_revision, new_revision, old_url, new_url, updated_by, notes
               FROM drawing_revision_log
               WHERE drawing_id = ?
               ORDER BY epoch DESC""",
            (drawing_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# ── Hub substation version graph (local mirror) ──────────────────────────────

def get_hub_sync(db_path: str) -> dict | None:
    with _conn(db_path) as c:
        row = c.execute("SELECT * FROM hub_sync WHERE id = 1").fetchone()
    return dict(row) if row else None


def set_hub_sync(db_path: str, **fields):
    cur = get_hub_sync(db_path) or {
        "hub_url": "", "substation_id": "", "base_id": "",
        "head_id": "", "branch": "main", "linked_epoch": int(time.time()),
    }
    cur.update({k: v for k, v in fields.items() if v is not None})
    with _conn(db_path) as c:
        c.execute(
            """INSERT INTO hub_sync (id, hub_url, substation_id, base_id, head_id, branch, linked_epoch)
               VALUES (1,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                 hub_url=excluded.hub_url, substation_id=excluded.substation_id,
                 base_id=excluded.base_id, head_id=excluded.head_id,
                 branch=excluded.branch, linked_epoch=excluded.linked_epoch""",
            (cur["hub_url"], cur["substation_id"], cur["base_id"],
             cur["head_id"], cur.get("branch", "main"), cur["linked_epoch"]),
        )
    return get_hub_sync(db_path)


def clear_hub_sync(db_path: str):
    with _conn(db_path) as c:
        c.execute("DELETE FROM hub_sync WHERE id = 1")


def add_local_version(db_path: str, v: dict):
    topo = v["topology"]
    with _conn(db_path) as c:
        c.execute(
            """INSERT OR IGNORE INTO substation_versions
               (id, parent_id, merge_parent, branch, epoch, author, author_id, message, topology)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                str(v["id"]), str(v.get("parent_id") or ""), str(v.get("merge_parent") or ""),
                str(v.get("branch") or "main"), int(v.get("epoch") or time.time()),
                str(v.get("author") or ""), str(v.get("author_id") or ""),
                str(v.get("message") or ""),
                topo if isinstance(topo, str) else json.dumps(topo),
            ),
        )


def get_local_version(db_path: str, version_id: str) -> dict | None:
    with _conn(db_path) as c:
        row = c.execute(
            "SELECT * FROM substation_versions WHERE id = ?", (version_id,)
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["topology"] = json.loads(d["topology"])
    return d


def _local_ancestry(c, version_id: str) -> set:
    seen, stack = set(), [version_id]
    while stack:
        vid = stack.pop()
        if not vid or vid in seen:
            continue
        seen.add(vid)
        row = c.execute(
            "SELECT parent_id, merge_parent FROM substation_versions WHERE id = ?", (vid,)
        ).fetchone()
        if row:
            if row["parent_id"]:
                stack.append(row["parent_id"])
            if row["merge_parent"]:
                stack.append(row["merge_parent"])
    return seen


def local_versions_between(db_path: str, base_id: str, head_id: str) -> list[dict]:
    """Versions in head_id's ancestry but not base_id's, oldest first."""
    with _conn(db_path) as c:
        want = _local_ancestry(c, head_id) - _local_ancestry(c, base_id)
        rows = c.execute(
            "SELECT * FROM substation_versions ORDER BY epoch ASC, rowid ASC"
        ).fetchall()
    out = []
    for r in rows:
        if r["id"] in want:
            d = dict(r)
            d["topology"] = json.loads(d["topology"])
            out.append(d)
    return out


def record_version(db_path: str, topology: dict, *, author: str = "", author_id: str = "",
                   message: str = "", branch: str = "main", parent_id: str = "",
                   merge_parent: str = "") -> str:
    """Hash `topology`, append it as a version if its content differs from the
    given parent, and return the version id (parent_id if unchanged)."""
    if parent_id:
        parent = get_local_version(db_path, parent_id)
        if parent and topo_merge.topo_equal(parent["topology"], topology) and not merge_parent:
            return parent_id
    vid = topo_merge.content_hash(topology, parent_id, branch)
    add_local_version(db_path, {
        "id": vid, "parent_id": parent_id, "merge_parent": merge_parent,
        "branch": branch, "epoch": int(time.time()),
        "author": author, "author_id": author_id, "message": message,
        "topology": topology,
    })
    return vid


# ── Drawing revision sets (sibling revisions from the corporate system) ───────

def get_drawing_revision_set(db_path: str, drawing_number: str) -> dict | None:
    with _conn(db_path) as c:
        row = c.execute(
            "SELECT drawing_number, revisions, fetched_epoch, source FROM drawing_revision_sets WHERE drawing_number = ?",
            ((drawing_number or "").strip(),),
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    try:
        d["revisions"] = json.loads(d["revisions"] or "[]")
    except Exception:
        d["revisions"] = []
    return d


def save_drawing_revision_set(db_path: str, drawing_number: str, revisions: list,
                              source: str = "corporate-search") -> None:
    with _conn(db_path) as c:
        c.execute(
            """INSERT INTO drawing_revision_sets (drawing_number, revisions, fetched_epoch, source)
               VALUES (?,?,?,?)
               ON CONFLICT(drawing_number) DO UPDATE SET
                 revisions=excluded.revisions, fetched_epoch=excluded.fetched_epoch,
                 source=excluded.source""",
            ((drawing_number or "").strip(), json.dumps(revisions or []),
             int(time.time()), source),
        )
    _touch(db_path)
