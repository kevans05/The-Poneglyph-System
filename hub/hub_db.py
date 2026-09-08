"""
Poneglyph Hub — SQLite persistence for the shared server.

Phase 1 scope: accounts + bearer tokens + the published test pool.
The substation version graph (Phase 2+) will land in this same DB.

One file, one volume.  UUID / client-supplied primary keys mean a published
test is idempotent by its own id — re-publishing is a no-op.
"""

import hashlib
import json
import os
import secrets
import sqlite3
import time

DB_PATH = os.environ.get("HUB_DB", os.path.join("hub_data", "hub.db"))

# 90 days, refreshed on every authenticated call (see touch_token).
TOKEN_TTL_SECONDS = int(os.environ.get("HUB_TOKEN_TTL", str(90 * 24 * 3600)))
_PBKDF2_ROUNDS = 240_000


_SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    username      TEXT PRIMARY KEY,
    display_name  TEXT    NOT NULL DEFAULT '',
    pw_salt       TEXT    NOT NULL,
    pw_hash       TEXT    NOT NULL,
    identity_id   TEXT    NOT NULL DEFAULT '',   -- bound PoneglyphIdentity UUID
    created_epoch INTEGER NOT NULL,
    disabled      INTEGER NOT NULL DEFAULT 0,
    is_admin      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tokens (
    token           TEXT PRIMARY KEY,
    username        TEXT    NOT NULL REFERENCES accounts(username) ON DELETE CASCADE,
    issued_epoch    INTEGER NOT NULL,
    expires_epoch   INTEGER NOT NULL,
    last_seen_epoch INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tokens_user ON tokens(username);

CREATE TABLE IF NOT EXISTS published_tests (
    test_id            TEXT PRIMARY KEY,          -- client's test UUID (idempotency key)
    substation_id      TEXT    NOT NULL DEFAULT '',
    substation_version TEXT    NOT NULL DEFAULT '',
    name               TEXT    NOT NULL DEFAULT '',
    description        TEXT    NOT NULL DEFAULT '',
    status             TEXT    NOT NULL DEFAULT '',
    session_count      INTEGER NOT NULL DEFAULT 0,
    reading_count      INTEGER NOT NULL DEFAULT 0,
    published_by       TEXT    NOT NULL DEFAULT '',
    published_by_id    TEXT    NOT NULL DEFAULT '',
    published_epoch    INTEGER NOT NULL,
    bundle             TEXT    NOT NULL           -- full JSON bundle
);
CREATE INDEX IF NOT EXISTS idx_ptests_sub   ON published_tests(substation_id);
CREATE INDEX IF NOT EXISTS idx_ptests_epoch ON published_tests(published_epoch DESC);

CREATE TABLE IF NOT EXISTS substations (
    id            TEXT PRIMARY KEY,          -- station code / number_code
    name          TEXT    NOT NULL DEFAULT '',
    head_id       TEXT    NOT NULL DEFAULT '',
    created_epoch INTEGER NOT NULL,
    updated_epoch INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS substation_versions (
    id             TEXT PRIMARY KEY,          -- content hash
    substation_id  TEXT    NOT NULL REFERENCES substations(id) ON DELETE CASCADE,
    parent_id      TEXT    NOT NULL DEFAULT '',
    merge_parent   TEXT    NOT NULL DEFAULT '',
    branch         TEXT    NOT NULL DEFAULT 'main',
    epoch          INTEGER NOT NULL,
    author         TEXT    NOT NULL DEFAULT '',
    author_id      TEXT    NOT NULL DEFAULT '',
    message        TEXT    NOT NULL DEFAULT '',
    topology       TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sv_sub ON substation_versions(substation_id);
"""


def _conn():
    d = os.path.dirname(DB_PATH)
    if d:
        os.makedirs(d, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    return c


_MIGRATIONS = [
    ("accounts", "is_admin", "INTEGER NOT NULL DEFAULT 0"),
]


def init_db():
    with _conn() as c:
        c.executescript(_SCHEMA)
        existing = {r["name"] for r in c.execute("PRAGMA table_info(accounts)").fetchall()}
        for table, col, typedef in _MIGRATIONS:
            if table == "accounts" and col not in existing:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typedef}")


# ── Passwords ─────────────────────────────────────────────────────────────────

def _hash_pw(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), _PBKDF2_ROUNDS
    ).hex()


def count_accounts() -> int:
    with _conn() as c:
        return c.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]


def create_account(username: str, password: str, display_name: str = "",
                   is_admin: bool | None = None) -> None:
    """The very first account ever created is always an admin, regardless of
    `is_admin`, so the hub can never end up with no one able to manage it."""
    username = username.strip()
    if not username or not password:
        raise ValueError("username and password are required")
    salt = secrets.token_hex(16)
    with _conn() as c:
        exists = c.execute(
            "SELECT 1 FROM accounts WHERE username = ?", (username,)
        ).fetchone()
        if exists:
            raise ValueError(f"account '{username}' already exists")
        first = c.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 0
        admin_flag = 1 if (first or is_admin) else 0
        c.execute(
            """INSERT INTO accounts
               (username, display_name, pw_salt, pw_hash, created_epoch, is_admin)
               VALUES (?,?,?,?,?,?)""",
            (username, display_name or username, salt, _hash_pw(password, salt),
             int(time.time()), admin_flag),
        )


def set_password(username: str, password: str) -> bool:
    salt = secrets.token_hex(16)
    with _conn() as c:
        cur = c.execute(
            "UPDATE accounts SET pw_salt = ?, pw_hash = ? WHERE username = ?",
            (salt, _hash_pw(password, salt), username.strip()),
        )
        return cur.rowcount > 0


def set_admin(username: str, is_admin: bool) -> dict:
    """Flip the admin flag. Refuses to demote the last remaining admin."""
    with _conn() as c:
        if not is_admin:
            n_admins = c.execute(
                "SELECT COUNT(*) FROM accounts WHERE is_admin = 1"
            ).fetchone()[0]
            row = c.execute(
                "SELECT is_admin FROM accounts WHERE username = ?", (username,)
            ).fetchone()
            if row and row["is_admin"] and n_admins <= 1:
                return {"ok": False, "error": "cannot demote the last admin"}
        cur = c.execute(
            "UPDATE accounts SET is_admin = ? WHERE username = ?",
            (1 if is_admin else 0, username),
        )
        return {"ok": cur.rowcount > 0}


def set_disabled(username: str, disabled: bool) -> bool:
    with _conn() as c:
        cur = c.execute(
            "UPDATE accounts SET disabled = ? WHERE username = ?",
            (1 if disabled else 0, username),
        )
        return cur.rowcount > 0


def delete_account(username: str) -> dict:
    """Delete an account (cascades its tokens). Refuses to delete the last
    remaining admin — published tests / versions it authored are untouched,
    they just keep the historical name."""
    with _conn() as c:
        row = c.execute(
            "SELECT is_admin FROM accounts WHERE username = ?", (username,)
        ).fetchone()
        if not row:
            return {"ok": False, "error": "no such account"}
        if row["is_admin"]:
            n_admins = c.execute(
                "SELECT COUNT(*) FROM accounts WHERE is_admin = 1"
            ).fetchone()[0]
            if n_admins <= 1:
                return {"ok": False, "error": "cannot delete the last admin"}
        c.execute("DELETE FROM accounts WHERE username = ?", (username,))
        return {"ok": True}


def list_accounts() -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            """SELECT username, display_name, identity_id, created_epoch, disabled, is_admin
               FROM accounts ORDER BY username"""
        ).fetchall()
    return [dict(r) for r in rows]


def list_roster() -> list[dict]:
    """The public directory: just enough to pick a colleague's name when
    tagging who's actually taking a reading — no admin gate, no identity_id
    or account-management fields. Any signed-in account can read this."""
    with _conn() as c:
        rows = c.execute(
            "SELECT username, display_name FROM accounts WHERE disabled = 0 ORDER BY display_name"
        ).fetchall()
    return [dict(r) for r in rows]


def verify_password(username: str, password: str) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM accounts WHERE username = ? AND disabled = 0",
            (username.strip(),),
        ).fetchone()
    if not row:
        return None
    if not secrets.compare_digest(_hash_pw(password, row["pw_salt"]), row["pw_hash"]):
        return None
    return dict(row)


# ── Tokens ───────────────────────────────────────────────────────────────────

def issue_token(username: str, identity_id: str = "") -> dict:
    """Mint a bearer token. Binds the caller's PoneglyphIdentity id to the
    account on first sight so historical author_id / technician_id signatures
    resolve to this person."""
    now = int(time.time())
    tok = secrets.token_urlsafe(32)
    expires = now + TOKEN_TTL_SECONDS
    with _conn() as c:
        if identity_id:
            cur = c.execute(
                "SELECT identity_id FROM accounts WHERE username = ?", (username,)
            ).fetchone()
            if cur is not None and not cur["identity_id"]:
                c.execute(
                    "UPDATE accounts SET identity_id = ? WHERE username = ?",
                    (identity_id, username),
                )
        c.execute(
            """INSERT INTO tokens
               (token, username, issued_epoch, expires_epoch, last_seen_epoch)
               VALUES (?,?,?,?,?)""",
            (tok, username, now, expires, now),
        )
    return {"token": tok, "expires_epoch": expires}


def check_token(token: str) -> dict | None:
    """Validate a bearer token and slide its expiry forward (refresh-on-sync).
    Returns {username, display_name, expires_epoch} or None."""
    if not token:
        return None
    now = int(time.time())
    with _conn() as c:
        row = c.execute(
            """SELECT t.username, t.expires_epoch, a.display_name, a.disabled, a.is_admin
               FROM tokens t JOIN accounts a ON a.username = t.username
               WHERE t.token = ?""",
            (token,),
        ).fetchone()
        if not row or row["disabled"] or row["expires_epoch"] < now:
            return None
        new_expires = now + TOKEN_TTL_SECONDS
        c.execute(
            "UPDATE tokens SET last_seen_epoch = ?, expires_epoch = ? WHERE token = ?",
            (now, new_expires, token),
        )
    return {
        "username": row["username"],
        "display_name": row["display_name"],
        "is_admin": bool(row["is_admin"]),
        "expires_epoch": new_expires,
    }


def revoke_token(token: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM tokens WHERE token = ?", (token,))


# ── Published test pool ──────────────────────────────────────────────────────

def publish_test(bundle: dict, published_by: str, published_by_id: str) -> dict:
    """Store a test bundle. Idempotent by bundle['test']['id'] — an existing
    id is left untouched and reported as a dedup."""
    test = bundle.get("test") or {}
    test_id = str(test.get("id") or "").strip()
    if not test_id:
        raise ValueError("bundle.test.id is required")

    sub = bundle.get("substation") or {}
    sessions = bundle.get("sessions") or []
    measurements = bundle.get("measurements") or []
    now = int(time.time())

    with _conn() as c:
        existing = c.execute(
            "SELECT 1 FROM published_tests WHERE test_id = ?", (test_id,)
        ).fetchone()
        if existing:
            return {"stored": test_id, "dedup": True}
        c.execute(
            """INSERT INTO published_tests
               (test_id, substation_id, substation_version, name, description,
                status, session_count, reading_count, published_by,
                published_by_id, published_epoch, bundle)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                test_id,
                str(sub.get("id") or ""),
                str(sub.get("version") or ""),
                str(test.get("name") or ""),
                str(test.get("description") or ""),
                str(test.get("status") or ""),
                len(sessions),
                len(measurements),
                published_by or "",
                published_by_id or "",
                now,
                json.dumps(bundle),
            ),
        )
    return {"stored": test_id, "dedup": False}


def list_published_tests(substation_id: str = "", limit: int = 200) -> list[dict]:
    q = """SELECT test_id, substation_id, substation_version, name, description,
                  status, session_count, reading_count, published_by,
                  published_by_id, published_epoch
           FROM published_tests"""
    params: list = []
    if substation_id:
        q += " WHERE substation_id = ?"
        params.append(substation_id)
    q += " ORDER BY published_epoch DESC LIMIT ?"
    params.append(limit)
    with _conn() as c:
        rows = c.execute(q, params).fetchall()
    return [dict(r) for r in rows]


def get_published_bundle(test_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT bundle FROM published_tests WHERE test_id = ?", (test_id,)
        ).fetchone()
    return json.loads(row["bundle"]) if row else None


# ── Substation version graph ─────────────────────────────────────────────────

# Short, recognisable device-type labels for the one-line summary — same
# spirit as the desktop app's TYPE_ABBREV, kept independent since the hub has
# no import path to the client's static/utils.js.
_TYPE_ABBR = {
    "CircuitBreaker": "CB", "Disconnect": "DISC", "PowerTransformer": "XFMR",
    "VoltageRegulator": "REG", "CurrentTransformer": "CT",
    "VoltageTransformer": "VT", "DualWindingVT": "VT", "Relay": "RELAY",
    "CTTB": "CTTB", "FTBlock": "FTB", "IsoBlock": "ISO", "Bus": "BUS",
    "PowerLine": "LINE", "Line": "LINE", "Wire": "BUS",
    "Meter": "MTR", "Load": "LOAD",
    "ShuntCapacitor": "CAP", "ShuntReactor": "RCT", "SurgeArrester": "ARR",
    "VoltageSource": "SRC",
}


def _summarize_topology(topology: dict) -> str:
    """One-line, human-scannable gist of a substation's device makeup —
    voltage classes plus the most common equipment types."""
    devices = (topology or {}).get("devices") or []
    if not devices:
        return "no devices yet"

    counts: dict = {}
    kvs = set()
    for d in devices:
        t = d.get("type", "?")
        counts[t] = counts.get(t, 0) + 1
        for key in ("voltage_class_kv", "pri_kv", "sec_kv", "nominal_kv", "kv_rating"):
            v = d.get(key)
            if isinstance(v, (int, float)) and v > 0:
                kvs.add(v)

    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
    parts = [f"{n}×{_TYPE_ABBR.get(t, t)}" for t, n in top]
    kv_str = "/".join(
        (str(int(k)) if float(k).is_integer() else f"{k:.1f}")
        for k in sorted(kvs, reverse=True)[:3]
    )

    summary = f"{len(devices)} device{'s' if len(devices) != 1 else ''}"
    if kv_str:
        summary += f" · {kv_str} kV"
    if parts:
        summary += " · " + ", ".join(parts)
    return summary


def list_substations() -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            """SELECT s.id, s.name, s.head_id, s.updated_epoch, v.topology,
                      (SELECT COUNT(*) FROM substation_versions v2
                       WHERE v2.substation_id = s.id) AS version_count
               FROM substations s
               LEFT JOIN substation_versions v ON v.id = s.head_id
               ORDER BY s.updated_epoch DESC"""
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        topo = d.pop("topology", None)
        try:
            d["summary"] = _summarize_topology(json.loads(topo)) if topo else "no devices yet"
        except Exception:
            d["summary"] = ""
        out.append(d)
    return out


def get_substation(sub_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM substations WHERE id = ?", (sub_id,)).fetchone()
    return dict(row) if row else None


def get_version(sub_id: str, version_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM substation_versions WHERE substation_id = ? AND id = ?",
            (sub_id, version_id),
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["topology"] = json.loads(d["topology"])
    return d


def _ancestry(c, sub_id: str, version_id: str) -> list[str]:
    """version_id back to root, following parent_id (and merge_parent)."""
    seen, stack, order = set(), [version_id], []
    while stack:
        vid = stack.pop()
        if not vid or vid in seen:
            continue
        seen.add(vid)
        order.append(vid)
        row = c.execute(
            "SELECT parent_id, merge_parent FROM substation_versions WHERE substation_id = ? AND id = ?",
            (sub_id, vid),
        ).fetchone()
        if row:
            if row["parent_id"]:
                stack.append(row["parent_id"])
            if row["merge_parent"]:
                stack.append(row["merge_parent"])
    return order


def versions_since(sub_id: str, since_id: str = "", full: bool = False) -> list[dict]:
    """Versions on the path from head back to (and excluding) since_id, oldest
    first. `full` or no since_id → the whole graph, oldest first."""
    sub = get_substation(sub_id)
    if not sub or not sub["head_id"]:
        return []
    with _conn() as c:
        if full or not since_id:
            rows = c.execute(
                "SELECT * FROM substation_versions WHERE substation_id = ? ORDER BY epoch ASC, rowid ASC",
                (sub_id,),
            ).fetchall()
            wanted = [r["id"] for r in rows]
        else:
            anc = set(_ancestry(c, sub_id, sub["head_id"]))
            anc.discard(since_id)
            anc -= set(_ancestry(c, sub_id, since_id))
            rows = c.execute(
                "SELECT * FROM substation_versions WHERE substation_id = ? ORDER BY epoch ASC, rowid ASC",
                (sub_id,),
            ).fetchall()
            wanted = [r["id"] for r in rows if r["id"] in anc]
        by_id = {r["id"]: r for r in rows}
    out = []
    for vid in wanted:
        d = dict(by_id[vid])
        d["topology"] = json.loads(d["topology"])
        out.append(d)
    return out


def create_substation(sub_id: str, name: str, root_version: dict) -> dict:
    """Register a new substation with its first (root) version."""
    now = int(time.time())
    with _conn() as c:
        if c.execute("SELECT 1 FROM substations WHERE id = ?", (sub_id,)).fetchone():
            raise ValueError(f"substation '{sub_id}' already exists")
        vid = str(root_version["id"])
        c.execute(
            "INSERT INTO substations (id, name, head_id, created_epoch, updated_epoch) VALUES (?,?,?,?,?)",
            (sub_id, name or sub_id, vid, now, now),
        )
        _insert_version(c, sub_id, root_version)
    return {"substation_id": sub_id, "head_id": vid}


def push_versions(sub_id: str, base_id: str, versions: list[dict]) -> dict:
    """Fast-forward the substation head. Accepts iff the caller's base_id is the
    current head, or one of the pushed versions is a merge commit naming the
    current head as a parent. Otherwise 409-style rejection with the real head."""
    sub = get_substation(sub_id)
    if not sub:
        raise ValueError(f"substation '{sub_id}' not found")
    if not versions:
        return {"head_id": sub["head_id"], "applied": 0}

    head = sub["head_id"]
    ids = {str(v["id"]) for v in versions}
    names_head_as_parent = any(
        str(v.get("parent_id")) == head or str(v.get("merge_parent")) == head
        for v in versions
    )
    if base_id != head and not names_head_as_parent:
        return {"conflict": True, "head_id": head, "error": "non-fast-forward"}

    # Order so parents land before children.
    ordered = _topo_order(versions)
    now = int(time.time())
    with _conn() as c:
        for v in ordered:
            _insert_version(c, sub_id, v)
        new_head = ordered[-1]["id"]
        c.execute(
            "UPDATE substations SET head_id = ?, updated_epoch = ? WHERE id = ?",
            (new_head, now, sub_id),
        )
    return {"head_id": new_head, "applied": len(ordered)}


def _topo_order(versions: list[dict]) -> list[dict]:
    by_id = {str(v["id"]): v for v in versions}
    out, placed = [], set()
    def visit(vid):
        v = by_id.get(vid)
        if not v or vid in placed:
            return
        for p in (str(v.get("parent_id") or ""), str(v.get("merge_parent") or "")):
            if p in by_id and p not in placed:
                visit(p)
        placed.add(vid)
        out.append(v)
    for vid in list(by_id):
        visit(vid)
    return out


def _insert_version(c, sub_id: str, v: dict) -> None:
    topo = v["topology"]
    c.execute(
        """INSERT OR IGNORE INTO substation_versions
           (id, substation_id, parent_id, merge_parent, branch, epoch,
            author, author_id, message, topology)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (
            str(v["id"]), sub_id,
            str(v.get("parent_id") or ""), str(v.get("merge_parent") or ""),
            str(v.get("branch") or "main"), int(v.get("epoch") or time.time()),
            str(v.get("author") or ""), str(v.get("author_id") or ""),
            str(v.get("message") or ""),
            topo if isinstance(topo, str) else json.dumps(topo),
        ),
    )


def purge_expired_tokens() -> int:
    now = int(time.time())
    with _conn() as c:
        cur = c.execute("DELETE FROM tokens WHERE expires_epoch < ?", (now,))
        return cur.rowcount


# ── Admin: delete (destructive — used from the hub admin GUI) ────────────────

def delete_substation(sub_id: str) -> dict:
    with _conn() as c:
        if not c.execute("SELECT 1 FROM substations WHERE id = ?", (sub_id,)).fetchone():
            return {"ok": False, "error": "no such substation"}
        c.execute("DELETE FROM substation_versions WHERE substation_id = ?", (sub_id,))
        c.execute("DELETE FROM substations WHERE id = ?", (sub_id,))
        return {"ok": True}


def delete_published_test(test_id: str) -> dict:
    with _conn() as c:
        cur = c.execute("DELETE FROM published_tests WHERE test_id = ?", (test_id,))
        return {"ok": cur.rowcount > 0}


def admin_stats() -> dict:
    with _conn() as c:
        return {
            "accounts": c.execute("SELECT COUNT(*) FROM accounts").fetchone()[0],
            "substations": c.execute("SELECT COUNT(*) FROM substations").fetchone()[0],
            "tests": c.execute("SELECT COUNT(*) FROM published_tests").fetchone()[0],
            "versions": c.execute("SELECT COUNT(*) FROM substation_versions").fetchone()[0],
            "tokens": c.execute("SELECT COUNT(*) FROM tokens").fetchone()[0],
        }
