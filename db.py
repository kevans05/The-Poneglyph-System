"""
SCADA Pro — SQLite persistence layer.

Tables
------
snapshots     Full topology captures (replaces the snapshots/ file directory).
sessions      PLUG / PMM measurement sessions — one per instrument connection.
measurements  Individual meter readings linked to a session, indexed by epoch.

All timestamps are Unix epoch (integer seconds, UTC).
"""

import json
import sqlite3
import time

DB_PATH = "scada.db"


# ── Connection ────────────────────────────────────────────────────────────────

def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")   # safe for concurrent reads
    c.execute("PRAGMA foreign_keys=ON")
    return c


# ── Schema ────────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    epoch    INTEGER NOT NULL,
    label    TEXT    NOT NULL,
    station  TEXT    DEFAULT '',
    device   TEXT    DEFAULT '',
    topology TEXT    NOT NULL        -- full substation.json blob
);
CREATE INDEX IF NOT EXISTS idx_snap_epoch ON snapshots(epoch DESC);

CREATE TABLE IF NOT EXISTS sessions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    epoch      INTEGER NOT NULL,
    label      TEXT    DEFAULT '',
    station    TEXT    DEFAULT '',
    device     TEXT    DEFAULT '',
    instrument TEXT    DEFAULT 'manual',  -- 'manual' | 'pmm1' | 'pmm2'
    snapshot_id INTEGER REFERENCES snapshots(id)
);
CREATE INDEX IF NOT EXISTS idx_sess_epoch ON sessions(epoch DESC);

CREATE TABLE IF NOT EXISTS measurements (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER REFERENCES sessions(id) ON DELETE CASCADE,
    epoch      INTEGER NOT NULL,
    device_id  TEXT    NOT NULL,
    key        TEXT    NOT NULL,   -- e.g. 'Phase A Current'
    value      REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_meas_epoch      ON measurements(epoch DESC);
CREATE INDEX IF NOT EXISTS idx_meas_device_key ON measurements(device_id, key);
CREATE INDEX IF NOT EXISTS idx_meas_session    ON measurements(session_id);
"""


def init_db():
    """Create tables and indexes if they don't already exist."""
    with _conn() as c:
        c.executescript(_SCHEMA)


# ── Snapshots ─────────────────────────────────────────────────────────────────

def save_snapshot(label: str, station: str, device: str, topology: dict | str) -> int:
    """Persist a topology snapshot.  Returns the new row id."""
    blob = topology if isinstance(topology, str) else json.dumps(topology, indent=2)
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO snapshots (epoch, label, station, device, topology) VALUES (?,?,?,?,?)",
            (int(time.time()), label, station or "", device or "", blob),
        )
        return cur.lastrowid


def list_snapshots(limit: int = 100) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT id, epoch, label, station, device FROM snapshots ORDER BY epoch DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_snapshot_topology(snapshot_id: int) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT topology FROM snapshots WHERE id = ?", (snapshot_id,)
        ).fetchone()
    if row is None:
        return None
    return json.loads(row["topology"])


def delete_snapshot(snapshot_id: int):
    with _conn() as c:
        c.execute("DELETE FROM snapshots WHERE id = ?", (snapshot_id,))


# ── Sessions ──────────────────────────────────────────────────────────────────

def start_session(
    label: str = "",
    station: str = "",
    device: str = "",
    instrument: str = "manual",
    snapshot_id: int | None = None,
) -> int:
    """Open a new measurement session.  Returns the session id."""
    with _conn() as c:
        cur = c.execute(
            """INSERT INTO sessions (epoch, label, station, device, instrument, snapshot_id)
               VALUES (?,?,?,?,?,?)""",
            (int(time.time()), label, station or "", device or "", instrument, snapshot_id),
        )
        return cur.lastrowid


def list_sessions(limit: int = 100) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            """SELECT s.id, s.epoch, s.label, s.station, s.device, s.instrument,
                      s.snapshot_id, COUNT(m.id) AS reading_count
               FROM sessions s
               LEFT JOIN measurements m ON m.session_id = s.id
               GROUP BY s.id
               ORDER BY s.epoch DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_session(session_id: int) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
    return dict(row) if row else None


def delete_session(session_id: int):
    with _conn() as c:
        c.execute("DELETE FROM sessions WHERE id = ?", (session_id,))


# ── Measurements ──────────────────────────────────────────────────────────────

def record_measurements(
    session_id: int | None,
    device_id: str,
    measurements: dict[str, float],
    epoch: int | None = None,
):
    """Write one or more key/value readings for a device.

    measurements: {"Phase A Current": 0.56, "Phase A I-Angle": 134.1, …}
    """
    now = epoch or int(time.time())
    rows = [
        (session_id, now, device_id, k, float(v))
        for k, v in measurements.items()
        if isinstance(v, (int, float))
    ]
    if not rows:
        return
    with _conn() as c:
        c.executemany(
            "INSERT INTO measurements (session_id, epoch, device_id, key, value) VALUES (?,?,?,?,?)",
            rows,
        )


def get_session_measurements(session_id: int) -> dict:
    """Return all measurements for a session, grouped by device_id → key → list of readings."""
    with _conn() as c:
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


def get_device_history(
    device_id: str,
    key: str,
    limit: int = 200,
) -> list[dict]:
    """Time-series of readings for one device+key across all sessions."""
    with _conn() as c:
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
