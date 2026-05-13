/**
 * SCADA Pro Console - API Client
 * Manages communication with the Python backend.
 */

/**
 * Global state variables
 */
let currentData = null; // Stores the latest topology JSON
let openWindows = {}; // Tracks which device windows are currently open
let compareSource = null; // Stores the ID of the first device selected for comparison

/**
 * Fetches the latest system state from the backend and triggers a redraw.
 */
function refreshData() {
  if (typeof simActive !== 'undefined' && simActive) return; 
  fetch("/api/topology")
    .then((r) => r.json())
    .then((data) => {
      currentData = data;
      render3LD(data);
      updateMinimap();
      if (typeof onTopologyRefreshed === "function") onTopologyRefreshed();
      updateStatusBar(data.reference, data.sync_errors || []);
      Object.keys(openWindows).forEach((id) => {
        const node = data.nodes.find((n) => n.id === id);
        if (node) updateWindow(id, node);
      });
    })
    .catch((err) => console.error("Failed to fetch topology:", err));
}

/**
 * Toggles a Breaker or Disconnect (Open/Close).
 * @param {string} name - The ID of the device to toggle.
 */
function toggleDevice(name) {
  fetch(`/api/toggle/${encodeURIComponent(name)}`).then(() => refreshData());
}

/**
 * Sends a reconfiguration request to the server.
 * @param {string} id - Device ID (null for adding new devices)
 * @param {string} action - 'update_device', 'add_device', or 'record_measurement'
 * @param {object} payload - Data for the action
 */
function reconfigureAPI(id, action, payload) {
  return fetch("/api/reconfigure", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id, action, ...payload }),
  }).then((r) => r.json());
}

/**
 * Historical Snapshot API
 */
function fetchSnapshots() {
    return fetch("/api/db/snapshots").then(r => r.json());
}

function createSnapshot(label) {
    return reconfigureAPI(null, "create_snapshot", { label });
}

function deleteSnapshot(id) {
    return fetch("/api/db/snapshots/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id }),
    }).then(r => r.json());
}

/** Load a snapshot by numeric DB id and return computed topology JSON. */
function loadSnapshotData(id) {
    return fetch("/api/db/snapshots/" + id).then(r => r.json());
}

/**
 * Session API
 */
function startSession(label, instrument, technician, testId) {
    return fetch("/api/db/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ label, instrument, technician, test_id: testId }),
    }).then(r => r.json());
}

/**
 * Test Management API
 */
function fetchTests() {
    return fetch("/api/tests").then(r => r.json());
}

function fetchTestDetail(id) {
    return fetch("/api/tests/" + id).then(r => r.json());
}

function createTest(name, description, createdBy) {
    return fetch("/api/tests/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, description, created_by: createdBy }),
    }).then(r => r.json());
}

function deleteTest(id) {
    return fetch("/api/tests/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id }),
    }).then(r => r.json());
}

function setTestStatus(id, status) {
    return fetch("/api/tests/status", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id, status }),
    }).then(r => r.json());
}

function updateTestCapturePoints(id, devices) {
    return fetch("/api/tests/capture-points", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id, devices }),
    }).then(r => r.json());
}

function addDrawing(testId, title, url, revision, notes) {
    return fetch("/api/tests/drawings/add", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ test_id: testId, title, url, revision, notes }),
    }).then(r => r.json());
}

function deleteDrawing(id) {
    return fetch("/api/tests/drawings/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id }),
    }).then(r => r.json());
}

function fetchSessions() {
    return fetch("/api/db/sessions").then(r => r.json());
}

function deleteSession(id) {
    return fetch("/api/db/sessions/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id }),
    }).then(r => r.json());
}

function fetchSessionMeasurements(sessionId) {
    return fetch(`/api/db/sessions/${sessionId}/measurements`).then(r => r.json());
}

function fetchDeviceHistory(deviceId, key) {
    return fetch(`/api/db/history/${encodeURIComponent(deviceId)}/${encodeURIComponent(key)}`).then(r => r.json());
}

function renameDevice(oldId, newId) {
    return reconfigureAPI(oldId, "rename_device", { new_id: newId });
}

/**
 * Site Management API
 */
function fetchSites() {
    return fetch("/api/sites").then(r => r.json());
}

function fetchActiveSite() {
    return fetch("/api/sites/active").then(r => r.json());
}

function createSite(station, description, seedCurrent = false) {
    return fetch("/api/sites/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ station, description, seed_current: seedCurrent }),
    }).then(r => r.json());
}

function loadSite(station) {
    return fetch("/api/sites/load", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ station }),
    }).then(r => r.json());
}

function updateSiteInfo(fields) {
    return fetch("/api/sites/update", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(fields || {}),
    }).then(r => r.json());
}

/**
 * Topology Import / Export
 * The site DB is the source of truth; JSON is only an interchange format.
 */
function exportTopology() {
    window.location.href = "/api/topology/export";
}

function importTopology(topology) {
    return fetch("/api/topology/import", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ topology }),
    }).then(r => r.json());
}

function fetchDeviceConfigHistory(deviceId) {
    return fetch("/api/db/device-config-history/" + encodeURIComponent(deviceId))
        .then(r => r.json());
}

/**
 * Serial Number / Inventory Tracking API
 */
function fetchDeviceSerials(deviceId) {
    return fetch("/api/db/serials/" + encodeURIComponent(deviceId)).then(r => r.json());
}

function recordDeviceSerial(deviceId, serial, notes, technician, inventoryFields) {
    return fetch("/api/db/serials/record", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            device_id: deviceId, serial,
            notes: notes || "", technician: technician || "",
            ...(inventoryFields || {}),
        }),
    }).then(r => r.json());
}

function updateDeviceSerial(rowId, fields) {
    return fetch("/api/db/serials/update", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: rowId, ...fields }),
    }).then(r => r.json());
}

/**
 * Maintenance Log API
 */
function recordMaintenanceLog(deviceId, workPerformed, serial, technician, notes) {
    return fetch("/api/db/maintenance/record", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            device_id: deviceId,
            work_performed: workPerformed,
            serial: serial || "",
            technician: technician || "",
            notes: notes || "",
        }),
    }).then(r => r.json());
}

function fetchMaintenanceLog(deviceId) {
    return fetch("/api/db/maintenance/" + encodeURIComponent(deviceId)).then(r => r.json());
}

/**
 * Device Drawings API
 */
function fetchDeviceDrawings(deviceId) {
    return fetch("/api/db/device-drawings/" + encodeURIComponent(deviceId)).then(r => r.json());
}

function addDeviceDrawing(deviceId, title, url, revision, notes) {
    return fetch("/api/db/device-drawings/add", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            device_id: deviceId,
            title: title || "",
            url: url || "",
            revision: revision || "",
            notes: notes || "",
        }),
    }).then(r => r.json());
}

function deleteDeviceDrawing(id) {
    return fetch("/api/db/device-drawings/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id }),
    }).then(r => r.json());
}

// Update a drawing's revision. Logs the old revision automatically.
// newUrl is optional — omit or pass null to leave the URL unchanged.
function updateDeviceDrawing(id, revision, newUrl, updatedBy, notes) {
    const body = { id, revision, updated_by: updatedBy || "", notes: notes || "" };
    if (newUrl !== null && newUrl !== undefined) body.url = newUrl;
    return fetch("/api/db/device-drawings/update", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    }).then(r => r.json());
}

function fetchDrawingHistory(drawingId) {
    return fetch("/api/db/drawing-history/" + encodeURIComponent(drawingId)).then(r => r.json());
}

/**
 * Device Analog History (time-series measurements for one key)
 */
function fetchAnalogHistory(deviceId, key) {
    return fetch(`/api/db/history/${encodeURIComponent(deviceId)}/${encodeURIComponent(key)}`)
        .then(r => r.json());
}
