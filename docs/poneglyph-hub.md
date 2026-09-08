# Poneglyph Hub — design spec

**Status:** v0.3 · 2026-09-04 — P0–P5 built
**Locked:** branch & merge · offline-first · publish-only tests · hub-issued tokens · Docker host
**Merge engine:** custom version graph in the hub DB (no `git` dependency). Structural 3-way merge runs client-side in `topo_merge.py`.
**Still open:** token TTL tuning · SQLite-WAL vs. Postgres under real contention · permissions

A shared server where technicians co-build substation models and publish load
tests — offline-first, with branch-and-merge for the models and conflict-free
publishing for the tests.

Shareable version of this doc: <https://claude.ai/code/artifact/bb4c77d4-344d-4d2d-8d61-a65fef090be1>

---

## 1. Summary

Today the app stores everything for one substation in a single SQLite file: the
as-built model and every load test ever run against it, side by side. Two
artifacts with different lifecycles are glued together by that file.

This spec splits them and puts both on a shared hub.

- The **substation library** is the as-built — topology, device configuration,
  connections, drawings, serials, maintenance history. It is long-lived, changes
  slowly, and is built by several technicians together. It needs versioning and
  merge.
- The **test pool** is a flat collection of load-test records. Each is a dated
  field event owned by the technician who ran it; dozens accumulate against a
  substation over its service life. Records are immutable once filed, so this
  half needs no merge at all.

Field technicians are frequently off-network. The client keeps working entirely
against its local database and reconciles with the hub whenever a connection is
available — never blocking on one.

## 2. The two stores

| | Substation library | Test pool |
| --- | --- | --- |
| **Holds** | `site_info`, topology & device config, connections, `device_drawings`, `device_serials`, `maintenance_log` | `tests`, `sessions`, `measurements`, `test_drawings`, capture points, `vref` |
| **Lifecycle** | Years. Edited in bursts when a bay or scheme changes. | One field visit. Frozen once filed. |
| **Writers** | Several technicians, often on divergent local copies. | One technician per record, signed with their identity. |
| **Sharing** | Pull a version, commit locally, merge on push. | Publish the bundle upward; others pull it read-only. |
| **Conflicts** | Possible — resolved by structural 3-way merge. | None — idempotent by test UUID. |
| **Storage** | Version graph on the hub. | Flat `published_tests` table. |

The only link between the two: `sessions.snapshot_id`. A test was measured
against the substation *as it looked that day*, so every published bundle pins
`{ substation_id, substation_version }`.

## 3. Architecture

### Client — the existing app

Local-file mode is unchanged; pure offline work still needs nothing but the
`sites/*.db` files. A new "connect to hub" mode adds pull / merge / push for
substations and publish / browse for tests. Every hub call tolerates being
offline: it is queued and retried, and the UI never waits on the network.

### Hub — new, Dockerised

One container: the sync API, a SQLite data volume, and a token-auth layer in
front. Same stdlib `http.server` lineage as the app — no framework. It holds one
version graph per substation plus the flat test pool. `docker-compose` mounts a
named volume for the data so the container itself stays disposable.

### Transport

Plain HTTPS + JSON, `Authorization: Bearer <token>`. No git wire protocol, no
websockets, no long-poll. All sync state lives in rows on both ends.

## 4. Substation version graph

A version is exactly today's snapshot — the full substation JSON blob — plus a
parent pointer, a branch name, and the operator signature already recorded on
`snapshots.author_id`. The hub stores the graph; the client stores whichever
versions it has pulled or authored.

```
-- hub + client, same shape
substation_versions
  id             TEXT PRIMARY KEY     -- content hash
  substation_id  TEXT                 -- which station
  parent_id      TEXT                 -- prior version (NULL at root)
  merge_parent   TEXT                 -- second parent, set only on merge commits
  branch         TEXT                 -- 'main' or '<tech>/<slug>'
  epoch          INTEGER              -- advisory only; ancestry is by parent_id
  author         TEXT
  author_id      TEXT                 -- PoneglyphIdentity signature
  message        TEXT
  topology       TEXT                 -- full substation JSON, as snapshots today

-- client only: what local work descends from
sync_state
  substation_id  TEXT PRIMARY KEY
  base_id        TEXT                 -- last version pulled clean from the hub
  head_id        TEXT                 -- local tip (== base_id until you commit)
  server_url     TEXT
```

> **Why "poneglyph."** The real poneglyphs are indestructible stone records —
> history you can read and add to but never rewrite. The substation library is
> the same: every version is a signed block on an append-only chain. A merge
> adds a block; it never edits one.

## 5. Structural merge

The model is a keyed list of devices and connections, not free text, so the
merge is structural — a line-diff would invent conflicts across re-ordered JSON.
Three-way against the common ancestor (`base_id`), keyed by device `id`:

```
merge(base, ours, theirs) -> (result, conflicts)

  for id in keys(base) ∪ keys(ours) ∪ keys(theirs):
      b, o, t = base[id], ours[id], theirs[id]

      if o == t:            result[id] = o        # same edit, or both untouched
      elif o == b:          result[id] = t        # only theirs moved
      elif t == b:          result[id] = o        # only ours moved
      elif o is None or t is None:
          conflicts += DeleteEdit(id)             # removed on one side, changed on the other
      else:
          merged, fc = merge_fields(b, o, t)      # per-key 3-way
          result[id] = merged
          conflicts += fc

  # connections merge identically, keyed by
  # (source, target, from_terminal, to_terminal)
```

`merge_fields` takes the side that changed each key; only a key both sides
changed to *different* values becomes a conflict. Device position is treated as
a non-conflicting field — last write wins, never blocks a merge.

```
Conflict = {
  kind:      "field" | "delete-edit" | "connection",
  device_id: "T1-CT-A",
  field:     "selected_tap",     # "field" kind only
  base:      "2000:5",
  ours:      "1200:5",
  theirs:    "1600:5",
}
```

Unconflicted changes from both sides are already in `result`. The resolver panel
lists conflicts as device / field / connection rows; the technician picks *ours*,
*theirs*, or a typed value, and the resolution is written as a merge commit with
two parents.

## 6. Offline lifecycle

1. **Pull** — client fetches substation X at version `vN`. Recorded as
   `base_id = head_id = vN`. Read-only is fine here — a field tech measuring, not
   editing, never needs to commit.
2. **Work offline** — structural edits stack as signed local commits on branch
   `<tech>/<slug>`. `head_id` advances; `base_id` stays at `vN`. No connection
   required.
3. **Reconnect & compare** — on the next sync the client asks the hub for X's
   current head and the versions since `vN`.
4a. **Hub still at `vN` (fast-forward)** — local commits push straight up. Hub
    head becomes the local head.
4b. **Hub moved to `vN+k` (merge)** — pull `vN…vN+k`, run
    `merge(base=vN, ours=head, theirs=vN+k)`, resolve any conflicts, write a
    merge commit, push.
5. **Settle** — `base_id = head_id =` the new hub head. The local branch is
   folded into `main`; the outbox is empty.

The hub only ever accepts a push whose first parent is its current head
(fast-forward) or a merge commit that names the current head as a parent.
Anything else is rejected with the current head so the client can merge and
retry — the hub never merges.

## 7. Test pool

Publishing is a single idempotent upload. The bundle is self-contained and pins
the substation version it was measured against, so it stays meaningful even
after the model is rebuilt.

```
POST /api/hub/tests            (bearer)
{
  test:         { id, name, description, status, epoch,
                  capture_points, vref_label, vref_magnitude },
  sessions:     [ { id, epoch, technician, technician_id, instrument } ],
  measurements: [ { id, session_id, device_id, key, value, epoch } ],
  drawings:     [ { id, title, url, revision, notes } ],
  substation:   { id, version }        -- what it was measured against
}
-> 200 { stored: "<test_id>", dedup: true | false }
```

Re-publishing the same `test.id` is a no-op that returns `dedup: true`. Browsing
is `GET /api/hub/tests?substation=X`; pulling one drops it into the local `sites`
DB as a read-only record (`tests.origin = 'hub:<user>'`). Drawings travel as
URLs, never blobs — same as today.

## 8. Sync API

| Method | Path | Purpose | Auth |
| --- | --- | --- | --- |
| `POST` | `/api/hub/login` | Username + password → bearer token. The one call that needs connectivity. | — |
| `POST` | `/api/hub/token/refresh` | Extend the token; also piggy-backed on every successful sync response. | bearer |
| `GET`  | `/api/hub/substations` | List stations with their current head version. | bearer |
| `GET`  | `/api/hub/substations/{id}?since={v}` | Pull versions after `v` (omit `since` for a full pull). | bearer |
| `POST` | `/api/hub/substations/{id}/push` | Push local commits. Fast-forward, or reject with the current head. | bearer |
| `GET`  | `/api/hub/tests?substation={id}` | Browse published test records. | bearer |
| `POST` | `/api/hub/tests` | Publish a test bundle. Idempotent by `test.id`. | bearer |
| `GET`  | `/api/hub/tests/{id}` | Pull one full test bundle. | bearer |

## 9. Token auth

Field techs are usually off the corporate network, so anything that revalidates
per request — AD, Kerberos — is out. Instead:

- `POST /api/hub/login` with username + password returns `{ token, expires }`.
  This is the only step that requires connectivity.
- The token is stored locally (config file / `localStorage`) and sent as
  `Authorization: Bearer` on every hub call. All sync then works whenever a
  connection happens to be present.
- Every successful sync response carries a refreshed token
  (`token_expires_epoch`). A tech who syncs at least once per TTL never logs in
  again; one who is dark for longer re-logs on their next connected day.
- First login binds `PoneglyphIdentity.id` — the per-device signature UUID
  already stamped on `author_id` / `technician_id` — to the hub account, so
  historical signatures resolve to a real person.

**Out of scope for v1:** SSO, password-reset flow, and per-substation
permissions. Everyone who can log in can pull, push, and publish; station
ownership comes later if the team needs it.

## 10. Build order

- **P0 — Change signing.** *Done.* `author` / `author_id` on `snapshots` and
  `device_history`; `POST /api/operator`; history modal shows `◆ name`.
- **P1 — Test pool.** *Done.* Hub container (`hub/`) with `/api/hub/login` and
  `/api/hub/tests`. Client: **⇪ PUBLISH TO HUB** on a test, **☁ SHARED TESTS** in
  the Tests modal, backed by `GET /api/tests/<id>/bundle` and
  `POST /api/tests/import-bundle`. Zero merge code.
- **P2 — Substation pull + version graph.** *Done.* `substations` /
  `substation_versions` on the hub; local mirror + `hub_sync` row on the client.
  Lives in **Site Selection**, not a separate screen: each local site's row
  shows synced / n-unpushed / not-synced inline, a **☁ ON THE HUB — NOT ON THIS
  MACHINE** section lists substations with no local copy for bulk pull, and
  **☁ SYNC ALL LINKED SITES** walks every linked site in turn. A row's MANAGE
  button opens the full link / pull / push / conflict panel for that one site.
  Every `_autosave` on a linked site appends a signed local version; the hub
  only fast-forwards.
- **P3 — Structural merge + conflict UI.** *Done.* `topo_merge.merge(base, ours,
  theirs)` — device-keyed, field-level, connection-set-aware; provisional
  resolution to *ours*. On a divergent pull the per-site panel lists conflicts
  as ours/theirs rows; `POST /api/hub-sync/resolve` writes a two-parent merge
  commit. `topo_merge.resolve` + `content_hash` round out the module.
- **P4 — Auth hardening + ops.** *Done.* `GET /api/hub/whoami`,
  `hub.py purge-tokens`, `docker-compose` healthcheck on `/api/hub/ping`,
  identity-UUID bound at first login. TTL tuning and the SQLite/Postgres call
  stay open (see header).
- **P5 — Admin GUI.** *Done.* A browser dashboard at the hub's `/` — no
  separate process, served by `hub.py` alongside the API. First visit with zero
  accounts shows a bootstrap screen instead of login (that account is always
  admin). Tabs: overview stats, **users** (add / disable / promote / reset
  password / delete, with guards against leaving zero admins), **substations**
  (list + expandable version history + delete), **tests** (list + delete).
  Deleting or disabling an account never touches what they authored.

## 11. Open items

- **Merge engine** — custom version graph in the hub DB (reuses `snapshots`, the
  HTTP API, and P0 signing) vs. real `git` with a structural merge driver.
  Leaning custom: no `git` binary on field laptops, and git's offline history is
  already covered by the local commit stack.
- **Token lifetime** — start at 90 days with refresh-on-sync; shorten if that
  feels loose.
- **Hub storage** — SQLite in WAL mode on the mounted volume is fine for a small
  team; move to Postgres only if concurrent pushes actually contend.
- **Permissions** — flat in v1. Per-substation ownership and a review gate on
  `main` are deferred.
- **Clock skew** — `epoch` is advisory only; all ancestry is by `parent_id`.

## 12. Beyond v1

### Drawing revision sets — *done*

When a drawing is attached — to a device or a test — the full set of that
drawing's known revisions is bound to it, not just this app's own edit history.

- `device_drawings` / `test_drawings` gained a `drawing_number` column, captured
  from the corporate-search result at attach time.
- `drawing_search_config.list_revisions(number)` enumerates every revision the
  corporate system holds. `GET /api/drawings/revisions?number=<n>&refresh=<0|1>`
  serves it from the per-site `drawing_revision_sets` cache, re-querying when
  stale (`cache_refresh_hours`) or forced.
- Device drawings: **REVISIONS** on each row lists them; clicking a sibling swaps
  the attachment via `/api/db/device-drawings/update`, which logs the old
  revision to `drawing_revision_log`.
- Test drawings: the same list renders read-only — the pinned revision stays as
  the field record.
- Frontend: `static/drawing-revisions.js` (`renderDrawingRevisions`), wired into
  the device drawings manager and the test detail view.
