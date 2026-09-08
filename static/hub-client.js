"use strict";

/**
 * hub-client.js — client for the Poneglyph Hub (Phase 1: the test pool).
 *
 * Config lives in PoneglyphSettings (per-device):
 *   hubUrl           base URL of the hub, e.g. https://hub.example.internal
 *   hubToken         bearer token from a successful login
 *   hubUser          display name the hub knows this operator by
 *   hubTokenExpires  epoch seconds; refreshed on every authenticated call
 *
 * Everything degrades gracefully offline — callers get a rejected promise with
 * a readable .message and the UI stays usable.
 */

function _hubBase() {
  const raw = (PoneglyphSettings.get("hubUrl") || "").trim();
  return raw.replace(/\/+$/, "");
}

function hubConfigured() {
  return !!_hubBase();
}

function hubConnected() {
  return !!PoneglyphSettings.get("hubToken");
}

function hubStatus() {
  return {
    configured: hubConfigured(),
    connected: hubConnected(),
    url: _hubBase(),
    user: PoneglyphSettings.get("hubUser") || "",
    expires: Number(PoneglyphSettings.get("hubTokenExpires")) || 0,
  };
}

function _hubClearToken() {
  PoneglyphSettings.setMany({ hubToken: "", hubUser: "", hubTokenExpires: 0 });
}

/** fetch() against the hub with the bearer token attached and JSON parsed.
 *  Throws Error on network failure, non-2xx, or an expired token. */
function _hubFetch(path, { method = "GET", body = null, auth = true } = {}) {
  const base = _hubBase();
  if (!base) return Promise.reject(new Error("No hub URL configured."));

  const headers = { "Content-Type": "application/json" };
  if (auth) {
    const tok = PoneglyphSettings.get("hubToken");
    if (!tok) return Promise.reject(new Error("Not signed in to the hub."));
    headers["Authorization"] = "Bearer " + tok;
  }

  return fetch(base + path, {
    method,
    headers,
    body: body == null ? undefined : JSON.stringify(body),
  })
    .then((r) =>
      r
        .json()
        .catch(() => ({}))
        .then((data) => ({ ok: r.ok, status: r.status, data })),
    )
    .catch(() => {
      throw new Error("Hub unreachable — check the connection and hub URL.");
    })
    .then(({ ok, status, data }) => {
      if (status === 401) {
        _hubClearToken();
        throw new Error("Hub session expired — sign in again.");
      }
      if (typeof data.token_expires_epoch === "number") {
        PoneglyphSettings.set("hubTokenExpires", data.token_expires_epoch);
      }
      if (!ok) throw new Error(data.error || `Hub error (${status}).`);
      return data;
    });
}

function hubPing() {
  return _hubFetch("/api/hub/ping", { auth: false });
}

function hubLogin(username, password) {
  const identity_id =
    (window.PoneglyphIdentity && PoneglyphIdentity.getId()) || "";
  return _hubFetch("/api/hub/login", {
    method: "POST",
    auth: false,
    body: { username: username, password: password, identity_id: identity_id },
  }).then((d) => {
    PoneglyphSettings.setMany({
      hubToken: d.token || "",
      hubUser: d.display_name || d.username || username,
      hubTokenExpires: d.expires_epoch || 0,
    });
    return d;
  });
}

function hubLogout() {
  const done = () => {
    _hubClearToken();
    return { ok: true };
  };
  if (!hubConnected()) return Promise.resolve(done());
  return _hubFetch("/api/hub/logout", { method: "POST" })
    .then(done)
    .catch(done);
}

/** Publish one local test to the hub. Idempotent — re-publishing is a no-op. */
function hubPublishTest(testId) {
  const identity_id =
    (window.PoneglyphIdentity && PoneglyphIdentity.getId()) || "";
  return fetch("/api/tests/" + encodeURIComponent(testId) + "/bundle")
    .then((r) => {
      if (!r.ok) throw new Error("Could not build the test bundle locally.");
      return r.json();
    })
    .then((bundle) =>
      _hubFetch("/api/hub/tests", {
        method: "POST",
        body: { bundle: bundle, identity_id: identity_id },
      }),
    );
}

/** List published tests, optionally filtered to one substation id. */
function hubBrowseTests(substationId) {
  const q = substationId
    ? "?substation=" + encodeURIComponent(substationId)
    : "";
  return _hubFetch("/api/hub/tests" + q).then((d) => d.tests || []);
}

/** List the substations available on the hub (id, name, head_id, version_count). */
function hubBrowseSubstations() {
  return _hubFetch("/api/hub/substations").then((d) => d.substations || []);
}

/** The hub's user directory ({username, display_name} pairs) — any signed-in
 *  account can read this, unlike the admin-only user management endpoints.
 *  Used to let a technician pick a colleague's name even on a device that
 *  colleague has never signed into. Resolves to [] when not connected. */
function hubListUsers() {
  if (!hubConnected()) return Promise.resolve([]);
  return _hubFetch("/api/hub/users")
    .then((d) => d.users || [])
    .catch(() => []);
}

/** The bearer token + hub URL, for handing to the app's own /api/hub-sync/* routes. */
function hubCreds() {
  return {
    hub_url: _hubBase(),
    token: PoneglyphSettings.get("hubToken") || "",
  };
}

/** Pull one published test into the active local site DB (read-only record). */
function hubPullTest(testId) {
  const origin = "hub:" + (PoneglyphSettings.get("hubUser") || "shared");
  return _hubFetch("/api/hub/tests/" + encodeURIComponent(testId)).then((d) => {
    if (!d.bundle) throw new Error("Hub returned no bundle for that test.");
    return fetch("/api/tests/import-bundle", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bundle: d.bundle, origin: origin }),
    })
      .then((r) => r.json())
      .then((res) => {
        if (res.error) throw new Error(res.error);
        return res;
      });
  });
}

window.PoneglyphHub = {
  status: hubStatus,
  configured: hubConfigured,
  connected: hubConnected,
  creds: hubCreds,
  ping: hubPing,
  login: hubLogin,
  logout: hubLogout,
  publishTest: hubPublishTest,
  browseTests: hubBrowseTests,
  pullTest: hubPullTest,
  browseSubstations: hubBrowseSubstations,
  listUsers: hubListUsers,
};
