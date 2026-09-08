"""
Poneglyph Hub — shared server for The Poneglyph System.

Two stores:
  * Test pool — technicians publish load-test bundles and pull each other's.
    Append-only, idempotent by test id, no merge logic.
  * Substation version graph — a per-substation DAG of full-topology versions,
    each signed with the operator.  The hub only fast-forwards the head or
    accepts merge commits; the 3-way structural merge runs on the client
    (topo_merge.py in the desktop app).

A browser admin GUI (users / substations / tests) lives at "/", served from
static/ — no separate process, same server.

Run:
    python hub.py serve                       # HUB_PORT (default 8900), HUB_DB
    python hub.py adduser <username> [name]   # prompts for a password
    python hub.py passwd  <username>
    python hub.py listusers
    python hub.py purge-tokens                # drop expired tokens (cron-safe)

The first account ever created (CLI or the GUI's own bootstrap screen) is
always an admin, so the hub can never end up with no one able to manage it.

Concurrency model matches api.py: single-threaded stdlib http.server, one
request at a time, all state in SQLite.
"""

import getpass
import json
import mimetypes
import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs, unquote

import hub_db

HOST = os.environ.get("HUB_HOST", "0.0.0.0")
PORT = int(os.environ.get("HUB_PORT", "8900"))
MAX_BODY = 32 * 1024 * 1024  # 32 MB — a very large test bundle
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


def _send_json(handler, data, status=200):
    try:
        body = json.dumps(data).encode("utf-8")
        handler.send_response(status)
        handler.send_header("Content-type", "application/json")
        handler.send_header("Access-Control-Allow-Origin", "*")
        handler.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        handler.end_headers()
        handler.wfile.write(body)
    except (BrokenPipeError, ConnectionResetError):
        pass


def _bearer(handler) -> str:
    raw = handler.headers.get("Authorization", "") or ""
    if raw.lower().startswith("bearer "):
        return raw[7:].strip()
    return ""


class HubServer(BaseHTTPRequestHandler):
    server_version = "PoneglyphHub/1.0"

    def log_message(self, *args):
        pass

    # ── helpers ──────────────────────────────────────────────────────────────
    def _auth(self):
        """Return the token session dict, or None (and send 401)."""
        sess = hub_db.check_token(_bearer(self))
        if not sess:
            _send_json(self, {"error": "invalid or expired token"}, 401)
            return None
        return sess

    def _admin_auth(self):
        """Like _auth, but also requires the account to be an admin."""
        sess = self._auth()
        if sess is None:
            return None
        if not sess.get("is_admin"):
            _send_json(self, {"error": "admin access required"}, 403)
            return None
        return sess

    def _serve_static(self, path: str) -> bool:
        """Serve a file under static/. Returns True if it handled the request
        (including a 404 for a path that looks like a static asset)."""
        rel = path.lstrip("/") or "admin.html"
        if rel == "admin":
            rel = "admin.html"
        full = os.path.normpath(os.path.join(STATIC_DIR, rel))
        if not full.startswith(STATIC_DIR):
            self.send_response(403); self.end_headers()
            return True
        if not os.path.isfile(full):
            return False
        ctype, _ = mimetypes.guess_type(full)
        try:
            with open(full, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-type", ctype or "application/octet-stream")
            if full.endswith((".html", ".js", ".css")):
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass
        return True

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > MAX_BODY:
            raise ValueError("request body too large")
        return json.loads(self.rfile.read(length) or b"{}")

    def do_OPTIONS(self):
        _send_json(self, {}, 204)

    # ── GET ──────────────────────────────────────────────────────────────────
    def do_GET(self):
        try:
            parsed = urlparse(self.path)
            path = parsed.path

            if path == "/api/hub/ping":
                return _send_json(self, {"ok": True, "service": "poneglyph-hub", "phases": "test-pool + substation-graph"})

            if path == "/api/hub/tests":
                sess = self._auth()
                if not sess:
                    return
                q = parse_qs(parsed.query)
                sub = (q.get("substation", [""])[0] or "").strip()
                return _send_json(self, {
                    "tests": hub_db.list_published_tests(sub),
                    "token_expires_epoch": sess["expires_epoch"],
                })

            if path.startswith("/api/hub/tests/"):
                sess = self._auth()
                if not sess:
                    return
                test_id = path.rsplit("/", 1)[-1]
                bundle = hub_db.get_published_bundle(test_id)
                if bundle is None:
                    return _send_json(self, {"error": "not found"}, 404)
                return _send_json(self, {
                    "bundle": bundle,
                    "token_expires_epoch": sess["expires_epoch"],
                })

            if path == "/api/hub/whoami":
                sess = self._auth()
                if not sess:
                    return
                return _send_json(self, {
                    "username": sess["username"],
                    "display_name": sess["display_name"],
                    "is_admin": sess.get("is_admin", False),
                    "token_expires_epoch": sess["expires_epoch"],
                })

            # ── Admin GUI API ────────────────────────────────────────────────
            if path == "/api/hub/admin/bootstrap-needed":
                return _send_json(self, {"needed": hub_db.count_accounts() == 0})

            if path == "/api/hub/admin/users":
                sess = self._admin_auth()
                if not sess:
                    return
                return _send_json(self, {"users": hub_db.list_accounts()})

            if path == "/api/hub/admin/stats":
                sess = self._admin_auth()
                if not sess:
                    return
                return _send_json(self, hub_db.admin_stats())

            if path == "/api/hub/users":
                sess = self._auth()
                if not sess:
                    return
                return _send_json(self, {
                    "users": hub_db.list_roster(),
                    "token_expires_epoch": sess["expires_epoch"],
                })

            if path == "/api/hub/substations":
                sess = self._auth()
                if not sess:
                    return
                return _send_json(self, {
                    "substations": hub_db.list_substations(),
                    "token_expires_epoch": sess["expires_epoch"],
                })

            if path.startswith("/api/hub/substations/"):
                sess = self._auth()
                if not sess:
                    return
                sub_id = unquote(path.split("/", 5)[4])
                q = parse_qs(parsed.query)
                sub = hub_db.get_substation(sub_id)
                if not sub:
                    return _send_json(self, {"error": "not found"}, 404)
                since = (q.get("since", [""])[0] or "").strip()
                full = q.get("full", ["0"])[0] in ("1", "true", "yes")
                return _send_json(self, {
                    "substation": {"id": sub["id"], "name": sub["name"], "head_id": sub["head_id"]},
                    "versions": hub_db.versions_since(sub_id, since, full),
                    "token_expires_epoch": sess["expires_epoch"],
                })

            # ── Static admin GUI (falls through when nothing above matched) ─────
            if not path.startswith("/api/"):
                if self._serve_static(path):
                    return
                self.send_response(404); self.end_headers()
                return

            return _send_json(self, {"error": "not found"}, 404)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            traceback.print_exc()
            _send_json(self, {"error": str(e)}, 500)

    # ── POST ─────────────────────────────────────────────────────────────────
    def do_POST(self):
        try:
            path = urlparse(self.path).path
            req = self._read_body()

            if path == "/api/hub/login":
                acc = hub_db.verify_password(
                    str(req.get("username", "")), str(req.get("password", ""))
                )
                if not acc:
                    return _send_json(self, {"error": "bad credentials"}, 401)
                tok = hub_db.issue_token(
                    acc["username"], str(req.get("identity_id", "")).strip()
                )
                return _send_json(self, {
                    "token": tok["token"],
                    "expires_epoch": tok["expires_epoch"],
                    "username": acc["username"],
                    "display_name": acc["display_name"],
                    "is_admin": bool(acc.get("is_admin")),
                })

            if path == "/api/hub/token/refresh":
                sess = self._auth()
                if not sess:
                    return
                # check_token already slid the expiry forward
                return _send_json(self, {
                    "username": sess["username"],
                    "display_name": sess["display_name"],
                    "expires_epoch": sess["expires_epoch"],
                })

            if path == "/api/hub/logout":
                hub_db.revoke_token(_bearer(self))
                return _send_json(self, {"ok": True})

            if path == "/api/hub/tests":
                sess = self._auth()
                if not sess:
                    return
                bundle = req.get("bundle") if "bundle" in req else req
                if not isinstance(bundle, dict) or not (bundle.get("test") or {}).get("id"):
                    return _send_json(self, {"error": "bundle.test.id is required"}, 400)
                result = hub_db.publish_test(
                    bundle,
                    published_by=sess["display_name"] or sess["username"],
                    published_by_id=str(req.get("identity_id", "")).strip(),
                )
                result["token_expires_epoch"] = sess["expires_epoch"]
                return _send_json(self, result)

            if path == "/api/hub/substations":
                sess = self._auth()
                if not sess:
                    return
                sub_id = str(req.get("substation_id", "")).strip()
                root = req.get("root_version") or {}
                if not sub_id or not root.get("id") or not root.get("topology"):
                    return _send_json(self, {"error": "substation_id and root_version{id,topology} required"}, 400)
                try:
                    res = hub_db.create_substation(sub_id, str(req.get("name", "")), root)
                except ValueError as e:
                    return _send_json(self, {"error": str(e)}, 409)
                res["token_expires_epoch"] = sess["expires_epoch"]
                return _send_json(self, res)

            if path.startswith("/api/hub/substations/") and path.endswith("/push"):
                sess = self._auth()
                if not sess:
                    return
                sub_id = unquote(path.split("/")[4])
                res = hub_db.push_versions(
                    sub_id,
                    str(req.get("base_id", "")),
                    req.get("versions") or [],
                )
                res["token_expires_epoch"] = sess["expires_epoch"]
                return _send_json(self, res, 409 if res.get("conflict") else 200)

            # ── Admin GUI API ────────────────────────────────────────────────
            if path == "/api/hub/admin/bootstrap":
                if hub_db.count_accounts() > 0:
                    return _send_json(self, {"error": "already initialised — sign in instead"}, 409)
                username = str(req.get("username", "")).strip()
                password = str(req.get("password", ""))
                if not username or not password:
                    return _send_json(self, {"error": "username and password required"}, 400)
                try:
                    hub_db.create_account(username, password, str(req.get("display_name", "")))
                except ValueError as e:
                    return _send_json(self, {"error": str(e)}, 400)
                tok = hub_db.issue_token(username, str(req.get("identity_id", "")).strip())
                return _send_json(self, {
                    "token": tok["token"], "expires_epoch": tok["expires_epoch"],
                    "username": username, "is_admin": True,
                })

            if path == "/api/hub/admin/users":
                sess = self._admin_auth()
                if not sess:
                    return
                username = str(req.get("username", "")).strip()
                password = str(req.get("password", ""))
                if not username or not password:
                    return _send_json(self, {"error": "username and password required"}, 400)
                try:
                    hub_db.create_account(
                        username, password, str(req.get("display_name", "")),
                        is_admin=bool(req.get("is_admin")),
                    )
                except ValueError as e:
                    return _send_json(self, {"error": str(e)}, 400)
                return _send_json(self, {"ok": True})

            if path == "/api/hub/admin/users/delete":
                sess = self._admin_auth()
                if not sess:
                    return
                res = hub_db.delete_account(str(req.get("username", "")).strip())
                return _send_json(self, res, 200 if res.get("ok") else 400)

            if path == "/api/hub/admin/users/set-admin":
                sess = self._admin_auth()
                if not sess:
                    return
                res = hub_db.set_admin(str(req.get("username", "")).strip(), bool(req.get("is_admin")))
                return _send_json(self, res, 200 if res.get("ok") else 400)

            if path == "/api/hub/admin/users/set-disabled":
                sess = self._admin_auth()
                if not sess:
                    return
                ok = hub_db.set_disabled(str(req.get("username", "")).strip(), bool(req.get("disabled")))
                return _send_json(self, {"ok": ok}, 200 if ok else 404)

            if path == "/api/hub/admin/users/reset-password":
                sess = self._admin_auth()
                if not sess:
                    return
                password = str(req.get("password", ""))
                if not password:
                    return _send_json(self, {"error": "password required"}, 400)
                ok = hub_db.set_password(str(req.get("username", "")).strip(), password)
                return _send_json(self, {"ok": ok}, 200 if ok else 404)

            if path == "/api/hub/admin/substations/delete":
                sess = self._admin_auth()
                if not sess:
                    return
                res = hub_db.delete_substation(str(req.get("substation_id", "")).strip())
                return _send_json(self, res, 200 if res.get("ok") else 404)

            if path == "/api/hub/admin/tests/delete":
                sess = self._admin_auth()
                if not sess:
                    return
                res = hub_db.delete_published_test(str(req.get("test_id", "")).strip())
                return _send_json(self, res, 200 if res.get("ok") else 404)

            return _send_json(self, {"error": "not found"}, 404)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            traceback.print_exc()
            _send_json(self, {"error": str(e)}, 500)


# ── CLI ──────────────────────────────────────────────────────────────────────

def _cli_adduser(args):
    if not args:
        print("usage: python hub.py adduser <username> [display name]")
        return 2
    username = args[0]
    display = " ".join(args[1:]) if len(args) > 1 else username
    pw = getpass.getpass(f"password for {username}: ")
    pw2 = getpass.getpass("repeat password: ")
    if pw != pw2:
        print("passwords do not match")
        return 1
    hub_db.init_db()
    try:
        hub_db.create_account(username, pw, display)
    except ValueError as e:
        print(f"error: {e}")
        return 1
    print(f"created account '{username}'")
    return 0


def _cli_passwd(args):
    if not args:
        print("usage: python hub.py passwd <username>")
        return 2
    username = args[0]
    pw = getpass.getpass(f"new password for {username}: ")
    pw2 = getpass.getpass("repeat password: ")
    if pw != pw2:
        print("passwords do not match")
        return 1
    hub_db.init_db()
    if hub_db.set_password(username, pw):
        print(f"password updated for '{username}'")
        return 0
    print(f"no such account '{username}'")
    return 1


def _cli_purge_tokens(_args):
    hub_db.init_db()
    n = hub_db.purge_expired_tokens()
    print(f"purged {n} expired token(s)")
    return 0


def _cli_listusers(_args):
    hub_db.init_db()
    rows = hub_db.list_accounts()
    if not rows:
        print("(no accounts)")
        return 0
    for r in rows:
        bound = r["identity_id"][:8] if r["identity_id"] else "—"
        flags = ("admin" if r["is_admin"] else "") + (" [disabled]" if r["disabled"] else "")
        print(f"{r['username']:<20} {r['display_name']:<24} sig:{bound}  {flags}")
    return 0


def _cli_serve(_args):
    hub_db.init_db()
    httpd = HTTPServer((HOST, PORT), HubServer)
    print(f"Poneglyph Hub on {HOST}:{PORT}  (db: {hub_db.DB_PATH})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.server_close()
    return 0


_COMMANDS = {
    "serve": _cli_serve,
    "adduser": _cli_adduser,
    "passwd": _cli_passwd,
    "listusers": _cli_listusers,
    "purge-tokens": _cli_purge_tokens,
}

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "serve"
    handler = _COMMANDS.get(cmd)
    if not handler:
        print(f"unknown command '{cmd}'. commands: {', '.join(_COMMANDS)}")
        sys.exit(2)
    sys.exit(handler(sys.argv[2:]))
