# Poneglyph Hub

Shared server for The Poneglyph System. See the full design in
[`../docs/poneglyph-hub.md`](../docs/poneglyph-hub.md).

**Implemented:**

- **Test pool** — technicians publish load-test bundles and pull each other's.
  Append-only, idempotent by test id, no merge logic.
- **Substation version graph** — a per-substation DAG of full-topology versions,
  each signed with the operator. Clients pull the head, commit offline, and push;
  the hub only fast-forwards or accepts merge commits. The 3-way structural merge
  runs on the *client* (`topo_merge.py` in the desktop app) — the hub just stores
  and orders versions.
- **Admin GUI** — a browser dashboard at `/` for managing the hub itself: users,
  uploaded substations (with version history), and published tests. No separate
  process — served by the same `hub.py`.

## Run it

```sh
# from hub/
docker compose up -d --build
```

Then open `http://<hub-host>:8900/` — the first visit finds no accounts and
shows a **CREATE ADMIN ACCOUNT** screen instead of a login form. That account is
always an admin. From the dashboard's **USERS** tab, add one account per
technician (admin or not); everyone signs into the desktop app's
**⚙ SETTINGS → PONEGLYPH HUB** with those same credentials.

The CLI still works if you'd rather script it (also useful for a first account
over SSH, with no port exposed yet):

```sh
docker compose run --rm hub python hub.py adduser cutty "Cutty Flamm"
docker compose run --rm hub python hub.py listusers
```

Without Docker (stdlib only, no venv needed):

```sh
HUB_DB=hub_data/hub.db python hub.py serve       # :8900 — visit / to bootstrap
```

The `poneglyph_hub_data` volume (or `hub_data/hub.db`) is the only durable
state. Terminate TLS with a reverse proxy for anything past a trusted LAN —
including the admin GUI, which sends credentials the same way the API does.

## Endpoints

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| `GET`  | `/api/hub/ping` | — | liveness |
| `POST` | `/api/hub/login` | — | `{username, password, identity_id?}` → `{token, expires_epoch, …}` |
| `POST` | `/api/hub/token/refresh` | bearer | slide the token expiry forward |
| `POST` | `/api/hub/logout` | bearer | revoke the current token |
| `GET`  | `/api/hub/whoami` | bearer | current account + token expiry |
| `GET`  | `/api/hub/users` | bearer | public directory — `{username, display_name}` for every enabled account, no admin gate |
| `GET`  | `/api/hub/tests?substation=<id>` | bearer | browse published tests (omit `substation` for all) |
| `POST` | `/api/hub/tests` | bearer | publish a bundle; idempotent by `bundle.test.id` |
| `GET`  | `/api/hub/tests/<test_id>` | bearer | pull one full bundle |
| `GET`  | `/api/hub/substations` | bearer | list substations + head version |
| `POST` | `/api/hub/substations` | bearer | register a new substation with its root version |
| `GET`  | `/api/hub/substations/<id>?since=<v>&full=<0\|1>` | bearer | pull versions after `v` (or all) |
| `POST` | `/api/hub/substations/<id>/push` | bearer | fast-forward the head; `409` + `{head_id}` if non-fast-forward |

Every authenticated response carries `token_expires_epoch` — sync at least
once per TTL and you never log in again.

### Admin (require the account's `is_admin` flag; 403 otherwise)

| Method | Path | Purpose |
| --- | --- | --- |
| `GET`  | `/api/hub/admin/bootstrap-needed` | `{needed}` — true iff the hub has zero accounts. No auth. |
| `POST` | `/api/hub/admin/bootstrap` | `{username, password, display_name?}` → creates the first account (always admin) + logs it in. Refused once any account exists. No auth. |
| `GET`  | `/api/hub/admin/stats` | Counts: accounts, substations, versions, tests, active tokens. |
| `GET`  | `/api/hub/admin/users` | List every account. |
| `POST` | `/api/hub/admin/users` | `{username, password, display_name?, is_admin?}` — create an account. |
| `POST` | `/api/hub/admin/users/delete` | `{username}` — refused for the last remaining admin. |
| `POST` | `/api/hub/admin/users/set-admin` | `{username, is_admin}` — refused if it would leave zero admins. |
| `POST` | `/api/hub/admin/users/set-disabled` | `{username, disabled}` — soft block; keeps the account and its history. |
| `POST` | `/api/hub/admin/users/reset-password` | `{username, password}`. |
| `POST` | `/api/hub/admin/substations/delete` | `{substation_id}` — deletes the substation **and its full version history**. |
| `POST` | `/api/hub/admin/tests/delete` | `{test_id}` — removes one published test from the pool. |

Deleting or disabling an account never touches what they authored — snapshots,
versions and published tests keep their recorded `author` / `published_by`.

## CLI

```
python hub.py serve
python hub.py adduser <username> [display name]
python hub.py passwd  <username>
python hub.py listusers
python hub.py purge-tokens        # drop expired tokens (safe to cron)
```

## Config

| Env | Default | Meaning |
| --- | --- | --- |
| `HUB_DB` | `hub_data/hub.db` | SQLite path (mount a volume here) |
| `HUB_HOST` | `0.0.0.0` | bind address |
| `HUB_PORT` | `8900` | bind port |
| `HUB_TOKEN_TTL` | `7776000` (90d) | token lifetime, refreshed on every call |

## Bundle shape

```json
{
  "test":         { "id", "name", "description", "status", "epoch",
                    "capture_points", "vref_label", "vref_magnitude" },
  "sessions":     [ { "id", "epoch", "technician", "technician_id", "instrument" } ],
  "measurements": [ { "id", "session_id", "device_id", "key", "value", "epoch" } ],
  "drawings":     [ { "id", "title", "url", "revision", "notes" } ],
  "substation":   { "id", "version" }
}
```

The desktop app builds this from `GET /api/tests/<id>/bundle` and re-imports a
pulled bundle through `POST /api/tests/import-bundle`.
