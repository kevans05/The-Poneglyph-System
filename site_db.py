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
    id       TEXT PRIMARY KEY,        -- UUID
    epoch    INTEGER NOT NULL,
    label    TEXT    NOT NULL,
    topology TEXT    NOT NULL         -- full substation.json blob
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
    test_id     TEXT    REFERENCES tests(id),
    snapshot_id TEXT    REFERENCES snapshots(id)
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
"""

# Columns added after initial release — applied to existing DBs on open.
_MIGRATIONS = [
    ("site_info",  "site_name",   "TEXT    DEFAULT ''"),
    ("site_info",  "number_code", "TEXT    DEFAULT ''"),
    ("site_info",  "gps_lat",     "REAL"),
    ("site_info",  "gps_lon",     "REAL"),
    ("sessions",   "technician",  "TEXT    DEFAULT ''"),
    ("sessions",   "test_id",     "TEXT"),
]


def _init(db_path: str):
    with _conn(db_path) as c:
        c.executescript(_SCHEMA)
        # Apply any new columns to pre-existing tables
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
    _init(path)
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
    """Return metadata for every site DB found in SITES_DIR."""
    if not os.path.exists(SITES_DIR):
        return []
    sites = []
    for fname in sorted(os.listdir(SITES_DIR)):
        if not fname.endswith(".db"):
            continue
        path = os.path.join(SITES_DIR, fname)
        try:
            with _conn(path) as c:
                info = c.execute("SELECT * FROM site_info LIMIT 1").fetchone()
                if info is None:
                    continue
                sess_count = c.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
                snap_count = c.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
                last_sess = c.execute(
                    "SELECT epoch FROM sessions ORDER BY epoch DESC LIMIT 1"
                ).fetchone()
            sites.append({
                "station": info["station"],
                "description": info["description"],
                "created_epoch": info["created_epoch"],
                "last_epoch": last_sess["epoch"] if last_sess else info["created_epoch"],
                "session_count": sess_count,
                "snapshot_count": snap_count,
                "db_path": path,
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


def _touch(db_path: str):
    """Update last_epoch to now."""
    try:
        with _conn(db_path) as c:
            c.execute("UPDATE site_info SET last_epoch = ? WHERE id = 1", (int(time.time()),))
    except Exception:
        pass


# ── Snapshots ─────────────────────────────────────────────────────────────────

def save_snapshot(db_path: str, label: str, topology: dict | str) -> str:
    """Persist a topology snapshot. Returns the UUID row id."""
    blob = topology if isinstance(topology, str) else json.dumps(topology, indent=2)
    row_id = str(uuid.uuid4())
    with _conn(db_path) as c:
        c.execute(
            "INSERT INTO snapshots (id, epoch, label, topology) VALUES (?,?,?,?)",
            (row_id, int(time.time()), label, blob),
        )
    _touch(db_path)
    return row_id


def list_snapshots(db_path: str, limit: int = 100) -> list[dict]:
    with _conn(db_path) as c:
        rows = c.execute(
            "SELECT id, epoch, label FROM snapshots ORDER BY epoch DESC LIMIT ?",
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
        c.execute("DELETE FROM snapshots WHERE id = ?", (snapshot_id,))


# ── Tests ─────────────────────────────────────────────────────────────────────

def create_test(
    db_path: str,
    name: str,
    description: str = "",
    created_by: str = "",
) -> str:
    """Create a named test. Returns the UUID."""
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


def delete_test(db_path: str, test_id: str):
    with _conn(db_path) as c:
        c.execute("DELETE FROM tests WHERE id = ?", (test_id,))


# ── Test Drawings ──────────────────────────────────────────────────────────────

def add_drawing(
    db_path: str,
    test_id: str,
    title: str,
    url: str = "",
    revision: str = "",
    notes: str = "",
) -> str:
    """Add a drawing reference to a test. Returns the UUID."""
    row_id = str(uuid.uuid4())
    with _conn(db_path) as c:
        c.execute(
            "INSERT INTO test_drawings (id, test_id, title, url, revision, notes) VALUES (?,?,?,?,?,?)",
            (row_id, test_id, title, url or "", revision or "", notes or ""),
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

def start_session(
    db_path: str,
    label: str = "",
    device: str = "",
    instrument: str = "manual",
    technician: str = "",
    test_id: str | None = None,
    snapshot_id: str | None = None,
) -> str:
    """Open a new measurement session. Returns the session UUID."""
    row_id = str(uuid.uuid4())
    with _conn(db_path) as c:
        c.execute(
            """INSERT INTO sessions (id, epoch, label, device, instrument, technician, test_id, snapshot_id)
               VALUES (?,?,?,?,?,?,?,?)""",
            (row_id, int(time.time()), label, device or "", instrument, technician or "", test_id, snapshot_id),
        )
    _touch(db_path)
    return row_id


def list_sessions(db_path: str, limit: int = 100, test_id: str | None = None) -> list[dict]:
    where = "WHERE s.test_id = ?" if test_id else ""
    params = [test_id, limit] if test_id else [limit]
    with _conn(db_path) as c:
        rows = c.execute(
            f"""SELECT s.id, s.epoch, s.label, s.device, s.instrument,
                       s.technician, s.test_id, s.snapshot_id,
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

def record_measurements(
    db_path: str,
    session_id: str | None,
    device_id: str,
    measurements: dict[str, float],
    epoch: int | None = None,
):
    now = epoch or int(time.time())
    rows = [
        (str(uuid.uuid4()), session_id, now, device_id, k, float(v))
        for k, v in measurements.items()
        if isinstance(v, (int, float))
    ]
    if not rows:
        return
    with _conn(db_path) as c:
        c.executemany(
            "INSERT INTO measurements (id, session_id, epoch, device_id, key, value) VALUES (?,?,?,?,?,?)",
            rows,
        )
    _touch(db_path)


def get_session_measurements(db_path: str, session_id: str) -> dict:
    """Return all measurements for a session, grouped by device_id → key → list of readings."""
    with _conn(db_path) as c:
        rows = c.execute(
            """SELECT epoch, device_id, key, value
               FROM measurements WHERE session_id = ?
               ORDER BY epoch ASC""",
            (session_id,),
        ).fetchall()
    by_device: dict[str, dict[str, list]] = {}
    for r in rows:
        by_device.setdefault(r["device_id"], {}).setdefault(r["key"], []).append(
            {"epoch": r["epoch"], "value": r["value"]}
        )
    return by_device


def get_device_history(db_path: str, device_id: str, key: str, limit: int = 200) -> list[dict]:
    """Time-series of readings for one device+key across all sessions."""
    with _conn(db_path) as c:
        rows = c.execute(
            """SELECT m.epoch, m.value, m.session_id, s.label, s.instrument
               FROM measurements m
               LEFT JOIN sessions s ON s.id = m.session_id
               WHERE m.device_id = ? AND m.key = ?
               ORDER BY m.epoch DESC
               LIMIT ?""",
            (device_id, key, limit),
        ).fetchall()
    return [dict(r) for r in rows]
