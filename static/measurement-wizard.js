"use strict";

// Types that carry electrical signals worth measuring
const WIZARD_MEASURABLE = new Set([
  "VoltageSource",
  "Bus",
  "CircuitBreaker",
  "Disconnect",
  "PowerTransformer",
  "VoltageRegulator",
  "PowerLine",
  "Load",
  "CurrentTransformer",
  "VoltageTransformer",
  "DualWindingVT",
  "CTTB",
  "FTBlock",
  "IsoBlock",
  "Relay",
  "ShuntCapacitor",
  "ShuntReactor",
  "SurgeArrester",
  "SeriesCapacitor",
  "SeriesReactor",
  "NeutralGroundingResistor",
  "SVC",
  "LineTrap",
]);

// Which quantities each device type carries (controls wizard row visibility)
function _deviceShowsVoltage(type) {
  return !["CurrentTransformer", "CTTB"].includes(type);
}
function _deviceShowsCurrent(type) {
  return ![
    "VoltageTransformer",
    "DualWindingVT",
    "FTBlock",
    "IsoBlock",
  ].includes(type);
}

// Device-type-aware predicted key names for the report
function _predKey(node, phase, qty) {
  const type = typeof node === "string" ? node : node.type;
  const isDelta =
    node &&
    node.summary &&
    (node.summary && (node.summary && node.summary.Connection)) &&
    (node.summary && (node.summary && node.summary.Connection)).includes("Delta");

  if (qty === "voltage") {
    if (["VoltageTransformer", "DualWindingVT"].includes(type)) {
      if (isDelta) {
        const pMap = { A: "AB", B: "BC", C: "CA" };
        return `Sec Voltage Phase ${pMap[phase] || phase}`;
      }
      return `Sec Voltage Phase ${phase}`;
    }
    if (isDelta) {
      const pMap = { A: "A-B", B: "B-C", C: "C-A" };
      return `Phase ${pMap[phase] || phase} Voltage`;
    }
    return `Phase ${phase} Voltage (LN)`;
  }
  if (qty === "current") {
    if (type === "CurrentTransformer") return `Sec Current Phase ${phase}`;
    return `Phase ${phase} Current`;
  }
  if (qty === "v-angle") {
    if (isDelta) {
      const pMap = ["VoltageTransformer", "DualWindingVT"].includes(type)
        ? { A: "AB", B: "BC", C: "CA" }
        : { A: "A-B", B: "B-C", C: "C-A" };
      return `Phase ${pMap[phase] || phase} V-Angle`;
    }
    return `Phase ${phase} V-Angle`;
  }
  if (qty === "i-angle") return `Phase ${phase} I-Angle`;
  return null;
}

/**
 * Detach Brain Point to a separate popup window.
 * Uses a MutationObserver to sync DOM changes from D3 operations to the popup.
 */
let _bpPopup = null;
let _bpObserver = null;

function detachBrainPoint() {
  const module = document.getElementById("brain-point-module");
  if (!module) return;

  // If already open, focus it
  if (_bpPopup && !_bpPopup.closed) { _bpPopup.focus(); return; }

  const rect = module.getBoundingClientRect();
  const w = Math.round(rect.width)  || 700;
  const h = Math.round(rect.height) || 600;
  const left = Math.round(window.screenX + window.outerWidth / 2 - w / 2);

  const styleLinks = Array.from(document.querySelectorAll("link[rel=stylesheet]"))
    .map(l => '<link rel="stylesheet" href="' + l.href + '">').join("\n");

  _bpPopup = window.open("", "brain_point",
    "width=" + (w + 40) + ",height=" + (h + 40) + ",resizable=yes,scrollbars=yes,left=" + left + ",top=60");
  if (!_bpPopup) { alert("Popup blocked — please allow popups for this site."); return; }

  _bpPopup.document.write(`<!doctype html><html><head>
    <meta charset="UTF-8">
    <title>MEASUREMENT — Telemetry Interface</title>
    ${styleLinks}
    <style>
      body { overflow: auto; margin: 0; background: #080808; }
      .measure-wizard {
        position: relative !important;
        top: auto !important; left: auto !important;
        transform: none !important;
        width: 100% !important; height: auto !important;
        box-shadow: none; border-radius: 0;
      }
    </style>
  </head><body>
    <div id="brain-point-module" class="measure-wizard">
      <div id="brain-point-body" style="flex:1;overflow-y:auto;padding:16px;"></div>
      <div id="brain-point-footer" class="wizard-footer" style="display:flex;gap:8px;padding:10px 14px;border-top:1px solid #222;background:#0e0e0e;"></div>
    </div>
  </body></html>`);
  _bpPopup.document.close();

  // Hide main window modal
  module.style.display = "none";

  // Sync content immediately
  _syncBrainPointToPopup();

  // Watch for any DOM changes to the Brain Point module and re-sync
  if (_bpObserver) _bpObserver.disconnect();
  _bpObserver = new MutationObserver(() => _syncBrainPointToPopup());
  _bpObserver.observe(module, { childList: true, subtree: true, characterData: true, attributes: true });

  // Clean up when popup closes
  _bpPopup.addEventListener("beforeunload", () => {
    if (_bpObserver) { _bpObserver.disconnect(); _bpObserver = null; }
    _bpPopup = null;
    // Restore main window modal
    const m = document.getElementById("brain-point-module");
    if (m) m.style.display = "flex";
  });
}

function _syncBrainPointToPopup() {
  if (!_bpPopup || _bpPopup.closed) {
    if (_bpObserver) { _bpObserver.disconnect(); _bpObserver = null; }
    return;
  }
  try {
    const src = document.getElementById("brain-point-body");
    const foot = document.getElementById("brain-point-footer");
    const dst = _bpPopup.document.getElementById("brain-point-body");
    const dstFoot = _bpPopup.document.getElementById("brain-point-footer");
    if (src && dst)     dst.innerHTML     = src.innerHTML;
    if (foot && dstFoot) dstFoot.innerHTML = foot.innerHTML;
  } catch(e) { /* popup closed */ }
}

// 360 lag angle convention (default on — relays show 0–360°, no negative angles)
var _use360Lag = true;
function _lagAngle(deg) {
  return _use360Lag ? ((deg % 360) + 360) % 360 : deg;
}
function _fmtAngle(deg) {
  return _lagAngle(deg).toFixed(1) + "°";
}
function _toggleAngleConv() {
  _use360Lag = !_use360Lag;
  const label = _use360Lag ? "360°" : "±180°";
  const col   = _use360Lag ? "#3af" : "#888";
  document.querySelectorAll(".ang-conv-btn").forEach(btn => {
    btn.textContent = label;
    btn.style.color = col;
    btn.style.borderColor = _use360Lag ? "#3af" : "#555";
  });
  Object.keys(openWindows).forEach(id => {
    const node = (currentData && currentData.nodes) && currentData.nodes.find(n => n.id === id);
    if (node) updateWindow(id, node);
  });
}

// Device selection filter groups
const FILTER_GROUPS = {
  PROTECTION: new Set(["Relay", "CTTB", "FTBlock", "IsoBlock", "AuxiliaryTransformer", "Meter"]),
  SENSORS: new Set([
    "CurrentTransformer",
    "VoltageTransformer",
    "DualWindingVT",
  ]),
  PRIMARY: new Set([
    "VoltageSource",
    "CircuitBreaker",
    "Disconnect",
    "PowerTransformer",
    "VoltageRegulator",
    "Bus",
    "PowerLine",
    "Load",
    "Wire",
  ]),
  ALL: null,
};
let _bpFilter = "PROTECTION";

var _technicianName = "";
let _activeTestId   = null;
let _activeTestName = null;

// ── PMM Connection Wizard (Granular Phase-by-Phase Capture) ────────────────

let _bpSelectedMode = "m1"; // always m1 (single phase)
let _bpChan1 = 0;
let _bpChan2 = 6;
let _bpRefVTId = null;
let _bpSelectedDevices = [];
let _bpTargetDeviceId = null;
let _bpTargetPhase = "A";
let _bpLastMeasType = null; // 'voltage' | 'current' — physical input last used
let _bpSessionMeasurements = {}; // tracks entered values per device for balance checks
let _bpVoltChan1 = 0;   // saved voltage reference channel
let _bpVoltChan2 = 0;   // saved voltage measurement channel
let _bpCurrChan1 = 0;   // saved current reference channel
let _bpCurrChan2 = 6;   // saved current measurement channel (default Ia)
let _bpDeviceMeasStep = null; // "voltage"|"current" for multi-analog V→I split
// True once the system reference VT has been captured for this session — a
// manual session should only ever be asked for it once, not on every
// voltage/current device transition.
let _bpVrefCapturedThisSession = false;
let _bpVoltDevices   = []; // ordered selected voltage-only device IDs
let _bpCurrDevices   = []; // ordered selected current-only device IDs
let _bpRelayDevices  = []; // ordered selected relay device IDs
let _bpMultiDevices  = []; // ordered selected multi-analog (primary) device IDs

// Instrument type for this session
let _bpInstrumentType = "manual"; // "pmm1" | "pmm2" | "manual"
let _pmmPort = null; // Web Serial port handle / label for the connected PMM-1
let _pmmIP = "192.168.1.10"; // target PMM2 IP address
let _pmmConnected = false; // true once /api/pmm/connect returns ok

let _pmmLastReading = null; // most recent query result

function _bpDeviceExpectedType(deviceType) {
  if (["CurrentTransformer", "CTTB"].includes(deviceType)) return "current";
  if (
    ["VoltageTransformer", "DualWindingVT", "FTBlock", "IsoBlock"].includes(
      deviceType,
    )
  )
    return "voltage";
  return _bpChan2 >= 6 ? "current" : "voltage";
}

const PMM_SOURCES = [
  { v: 0, l: "Van" },
  { v: 1, l: "Vbn" },
  { v: 2, l: "Vcn" },
  { v: 3, l: "Vab" },
  { v: 4, l: "Vbc" },
  { v: 5, l: "Vca" },
  { v: 6, l: "Ia" },
  { v: 7, l: "Ib" },
  { v: 8, l: "Ic" },
];

// ── Technician History ─────────────────────────────────────────────────────────

const _BP_TECH_HIST_KEY = "bp_tech_history";

function _bpGetTechHistory() {
  try { return JSON.parse(localStorage.getItem(_BP_TECH_HIST_KEY)) || []; }
  catch { return []; }
}

function _bpSaveTechHistory(name) {
  const h = _bpGetTechHistory().filter((n) => n !== name);
  h.unshift(name);
  localStorage.setItem(_BP_TECH_HIST_KEY, JSON.stringify(h.slice(0, 8)));
}

function _bpPickTechnician(onPicked) {
  const hist = _bpGetTechHistory();
  const localNames = _technicianName
    ? [_technicianName, ...hist.filter((n) => n !== _technicianName)]
    : hist;

  // Know about everyone on the hub too, not just names used on this device —
  // a shared field instrument gets passed between technicians who may never
  // have touched this particular laptop before.
  const rosterP =
    window.PoneglyphHub && typeof PoneglyphHub.listUsers === "function"
      ? PoneglyphHub.listUsers().catch(() => [])
      : Promise.resolve([]);

  rosterP.then((roster) => {
    const seen = new Set(localNames);
    const hubNames = [];
    (roster || []).forEach((u) => {
      const n = (u.display_name || u.username || "").trim();
      if (n && !seen.has(n)) {
        seen.add(n);
        hubNames.push(n);
      }
    });
    _bpShowTechnicianPicker(localNames, hubNames, onPicked);
  });
}

function _bpShowTechnicianPicker(localNames, hubNames, onPicked) {
  const names = [...localNames, ...hubNames];
  const isHub = new Set(hubNames);

  if (names.length === 0) {
    showInputDialog("TECHNICIAN NAME", "Cutty Flamm", (name) => {
      if (!name) return;
      _bpSaveTechHistory(name);
      onPicked(name);
    });
    return;
  }

  const overlay = document.createElement("div");
  overlay.style.cssText =
    "position:fixed;inset:0;background:rgba(0,0,0,0.85);z-index:10500;display:flex;align-items:center;justify-content:center;";
  const box = document.createElement("div");
  box.style.cssText =
    "background:#0c0c0c;border:1px solid #0f0;padding:20px;min-width:380px;max-width:480px;" +
    "font-family:'Consolas','Courier New',monospace;display:flex;flex-direction:column;gap:8px;";

  const title = document.createElement("div");
  title.textContent = "TECHNICIAN NAME";
  title.style.cssText =
    "font-size:10px;color:#888;letter-spacing:1px;border-bottom:1px solid #1a1a1a;padding-bottom:8px;margin-bottom:4px;";
  box.appendChild(title);

  names.forEach((name) => {
    const row = document.createElement("div");
    row.style.cssText =
      "padding:9px 12px;border:1px solid #1a1a1a;color:#0f0;cursor:pointer;font-size:11px;border-radius:2px;" +
      "display:flex;justify-content:space-between;align-items:center;gap:8px;";
    const nameSpan = document.createElement("span");
    nameSpan.textContent = name;
    row.appendChild(nameSpan);
    if (isHub.has(name)) {
      const tag = document.createElement("span");
      tag.textContent = "☁";
      tag.title = "signed in on the hub";
      tag.style.cssText = "color:#3fdc8f;font-size:10px;";
      row.appendChild(tag);
    }
    row.addEventListener("mouseenter", () => (row.style.background = "#0d1a0d"));
    row.addEventListener("mouseleave", () => (row.style.background = "transparent"));
    row.addEventListener("click", () => {
      document.body.removeChild(overlay);
      _bpSaveTechHistory(name);
      onPicked(name);
    });
    box.appendChild(row);
  });

  const sep = document.createElement("div");
  sep.style.cssText = "border-top:1px solid #1a1a1a;margin:4px 0;";
  box.appendChild(sep);

  const newBtn = document.createElement("div");
  newBtn.textContent = "+ NEW TECHNICIAN";
  newBtn.style.cssText =
    "padding:8px 12px;border:1px solid #1a1a1a;color:#555;cursor:pointer;font-size:10px;letter-spacing:1px;border-radius:2px;";
  newBtn.addEventListener("mouseenter", () => (newBtn.style.color = "#aaa"));
  newBtn.addEventListener("mouseleave", () => (newBtn.style.color = "#555"));
  newBtn.addEventListener("click", () => {
    document.body.removeChild(overlay);
    showInputDialog("TECHNICIAN NAME", "", (name) => {
      if (!name) return;
      _bpSaveTechHistory(name);
      onPicked(name);
    });
  });
  box.appendChild(newBtn);

  overlay.appendChild(box);
  document.body.appendChild(overlay);
}

function initBrainPointSequence() {
  _bpSessionMeasurements = {};
  _pmmLastReading = null;
  _bpVrefCapturedThisSession = false;

  const doStart = (techName) => {
    _technicianName = techName || _technicianName;
    pickTest(_technicianName).then(testResult => {
      _activeTestId   = testResult ? testResult.test_id   : null;
      _activeTestName = testResult ? testResult.test_name : null;
      startSession(
        new Date().toISOString().slice(0, 16),
        "manual",
        _technicianName,
        _activeTestId,
      ).catch(() => {});
      d3.select("#brain-point-module")
        .style("display", "flex")
        .style("transform", "translate(-50%, -50%)")
        .style("top", "50%")
        .style("left", "50%");
      _bpRenderStep4();
    });
  };

  _bpPickTechnician(doStart);
}

// Sort a flat list of device IDs into the four capture-point buckets the
// wizard tracks, using the same rules as _bpRenderStep4's category filters.
function _bpDistributeCapturePoints(ids) {
  const byId = new Map((currentData?.nodes || []).map((n) => [n.id, n]));
  _bpVoltDevices = [];
  _bpCurrDevices = [];
  _bpRelayDevices = [];
  _bpMultiDevices = [];
  (ids || []).forEach((id) => {
    const n = byId.get(id);
    if (!n || !WIZARD_MEASURABLE.has(n.type)) return;
    if (n.type === "Relay") _bpRelayDevices.push(id);
    else if (!_deviceShowsCurrent(n.type)) _bpVoltDevices.push(id);
    else if (!_deviceShowsVoltage(n.type)) _bpCurrDevices.push(id);
    else _bpMultiDevices.push(id);
  });
  _bpSelectedDevices = [
    ..._bpVoltDevices,
    ..._bpCurrDevices,
    ..._bpRelayDevices,
    ..._bpMultiDevices,
  ];
  return _bpSelectedDevices.length;
}

// Launch the measurement interface for an already-known test (from the Tests
// detail view). Skips the test picker — only asks who is taking the readings —
// and, when the test already defines capture points, skips straight past the
// capture-point picker to instrument selection.
function startTestMeasurement(testId, testName) {
  _bpSessionMeasurements = {};
  _pmmLastReading = null;
  _bpVrefCapturedThisSession = false;

  _bpPickTechnician((techName) => {
    _technicianName = techName || _technicianName;
    _activeTestId = testId || null;
    _activeTestName = testName || null;
    startSession(
      new Date().toISOString().slice(0, 16),
      "manual",
      _technicianName,
      _activeTestId,
    ).catch(() => {});
    d3.select("#brain-point-module")
      .style("display", "flex")
      .style("transform", "translate(-50%, -50%)")
      .style("top", "50%")
      .style("left", "50%");

    fetchTestDetail(testId)
      .then(({ test }) => {
        let pts = [];
        try {
          pts = JSON.parse((test && test.capture_points) || "[]");
        } catch (e) {
          pts = [];
        }
        if (_bpDistributeCapturePoints(pts) > 0) _bpRenderStep0();
        else _bpRenderStep4();
      })
      .catch(() => _bpRenderStep4());
  });
}

// Step 0 — Instrument type selection (replaces old Steps 1 & 2)
function _bpRenderStep0() {
  d3.select("#brain-point-module").style("width", "700px").style("height", "auto");
  const body = d3.select("#brain-point-body").html("");
  body
    .style("background", "#111")
    .style("color", "#eee")
    .style("height", "auto")
    .style("padding", "20px");

  body
    .append("div")
    .text("MEASUREMENT — THE PONEGLYPH SYSTEM")
    .style("font-size", "11px")
    .style("color", "#0f0")
    .style("letter-spacing", "1px")
    .style("margin-bottom", "20px")
    .style("border-bottom", "1px solid #1a1a1a")
    .style("padding-bottom", "10px");

  body
    .append("div")
    .text("SELECT INSTRUMENT")
    .style("font-size", "10px")
    .style("color", "#888")
    .style("margin-bottom", "14px");

  const cards = [
    {
      id: "pmm1",
      title: "MEGGER PMM-1",
      sub: "Live serial connection · RS-232 19200 8N1",
      badge: "HARDWARE",
      badgeColor: "#0f0",
      available: true,
    },
    {
      id: "pmm2",
      title: "MEGGER PMM-2",
      sub: "Live network connection · TCP/IP Port 5025",
      badge: "HARDWARE",
      badgeColor: "#0f0",
      available: true,
    },
    {
      id: "manual",
      title: "MANUAL ENTRY",
      sub: "Enter readings from any instrument by hand",
      badge: "MANUAL",
      badgeColor: "#3af",
      available: true,
    },
  ];

  cards.forEach((card) => {
    const c = body
      .append("div")
      .style(
        "background",
        _bpInstrumentType === card.id ? "#0d1a0d" : "#1a1a1a",
      )
      .style(
        "border",
        `1px solid ${_bpInstrumentType === card.id ? "#0a0" : "#2a2a2a"}`,
      )
      .style("border-radius", "4px")
      .style("padding", "14px 18px")
      .style("margin-bottom", "10px")
      .style("cursor", card.available ? "pointer" : "default")
      .style("display", "flex")
      .style("align-items", "center")
      .style("gap", "14px");
    if (card.available) {
      c.on("click", () => {
        _bpInstrumentType = card.id;
        _bpRenderStep0();
      });
    }
    c.append("div")
      .style("width", "14px")
      .style("height", "14px")
      .style("border-radius", "50%")
      .style("border", `2px solid ${card.badgeColor}`)
      .style(
        "background",
        _bpInstrumentType === card.id ? card.badgeColor : "transparent",
      )
      .style("flex-shrink", "0");
    const txt = c.append("div").style("flex", "1");
    txt
      .append("div")
      .text(card.title)
      .style("font-size", "12px")
      .style("font-weight", "bold")
      .style("color", card.available ? "#eee" : "#555");
    txt
      .append("div")
      .text(card.sub)
      .style("font-size", "9px")
      .style("color", card.available ? "#666" : "#333")
      .style("margin-top", "2px");
    c.append("div")
      .text(card.badge)
      .style("font-size", "9px")
      .style("color", card.badgeColor)
      .style("border", `1px solid ${card.badgeColor}`)
      .style("padding", "2px 6px")
      .style("border-radius", "3px")
      .style("flex-shrink", "0")
      .style("letter-spacing", "1px");
  });

  const footer = d3.select("#brain-point-footer").html("");
  footer
    .append("button")
    .attr("class", "wiz-secondary")
    .text("← CAPTURE POINTS (" + _bpSelectedDevices.length + ")")
    .on("click", _bpRenderStep4);
  footer.append("div").style("flex", 1);
  // Already connected? Skip straight past the connect screen — re-running it
  // was a dead end (its own "NEXT" led right back to capture points, with no
  // path forward into the reading screen at all).
  const alreadyLive = _bpLiveInstrumentActive();
  footer
    .append("button")
    .attr("class", "wiz-save")
    .text(
      alreadyLive
        ? "NEXT: START READINGS →"
        : _bpInstrumentType === "pmm1"
          ? "NEXT: CONNECT PMM-1 →"
          : _bpInstrumentType === "pmm2"
            ? "NEXT: CONNECT PMM-2 →"
            : "NEXT: CONFIGURE →",
    )
    .on("click", () => {
      if (alreadyLive) _bpBeginReadings();
      else if (_bpInstrumentType === "pmm1") _bpConnectPMM1();
      else if (_bpInstrumentType === "pmm2") _bpConnectPMM2();
      else _bpBeginReadings();
    });
}

// Pending (chosen but not yet connected) Web Serial port for the PMM-1.
let _pmmPendingPort = null;

// Route channel-config / query through the browser's Web Serial PMM-1 when that
// is the active instrument; otherwise fall back to the server (PMM-2 over TCP).
function _pmmConfigure(chan1, chan2) {
  if (_bpInstrumentType === "pmm1" && window.PMM1 && window.PMM1.active) {
    return window.PMM1.active.configureChannels(chan1, chan2);
  }
  return fetch("/api/pmm/configure", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chan1, chan2 }),
  }).then((r) => r.json());
}

function _pmmQuery() {
  if (_bpInstrumentType === "pmm1" && window.PMM1 && window.PMM1.active) {
    return window.PMM1.active.query();
  }
  return fetch("/api/pmm/query").then((r) => r.json());
}

function _pmmDisconnect() {
  if (window.PMM1 && window.PMM1.active) {
    const p = window.PMM1.active;
    window.PMM1.active = null;
    return p.disconnect().catch(() => {});
  }
  return fetch("/api/pmm/disconnect", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  }).catch(() => {});
}

// PMM-1 port selection + connection, over the Web Serial API (browser-side).
function _bpConnectPMM1() {
  d3.select("#brain-point-module").style("width", "700px").style("height", "auto");
  const body = d3
    .select("#brain-point-body")
    .html("")
    .style("background", "#000")
    .style("color", "#0f0")
    .style("height", "auto")
    .style("padding", "20px");

  body
    .append("div")
    .text("PMM-1 CONNECTION  ·  WEB SERIAL  ·  19200 BAUD  ·  8N1")
    .style("font-size", "10px")
    .style("color", "#0a0")
    .style("letter-spacing", "1px")
    .style("margin-bottom", "18px");

  const supported = window.PMM1 && window.PMM1.Port.isSupported();

  // Connection status terminal
  const term = body
    .append("div")
    .attr("id", "pmm-term")
    .style("background", "#000")
    .style("border", "1px solid #030")
    .style("padding", "10px")
    .style("font-size", "10px")
    .style("min-height", "80px")
    .style("color", "#0f0")
    .style("margin-bottom", "14px");

  if (!supported) {
    term
      .append("div")
      .text("✗ WEB SERIAL NOT AVAILABLE IN THIS BROWSER")
      .style("color", "#f44")
      .style("font-weight", "bold");
    term
      .append("div")
      .text("Use Chrome or Edge, served over HTTPS or http://localhost.")
      .style("color", "#555");
  } else if (_pmmConnected) {
    term
      .append("div")
      .text("✓ CONNECTED TO PMM-1 @ " + (_pmmPort || "serial port"))
      .style("color", "#0f0")
      .style("font-weight", "bold");
    term
      .append("div")
      .text("Single-phase mode (m1) active.")
      .style("color", "#555");
  } else {
    term.append("div").text("STATUS: DISCONNECTED").style("color", "#555");
    term
      .append("div")
      .text(
        _pmmPendingPort
          ? "Port selected — press CONNECT."
          : "Press SELECT PORT to choose the PMM-1 serial adapter.",
      )
      .style("color", "#333");
  }

  const footer = d3.select("#brain-point-footer").html("");
  footer
    .append("button")
    .attr("class", "wiz-secondary")
    .text("← BACK")
    .on("click", _bpRenderStep0);
  footer.append("div").style("flex", 1);

  if (_pmmConnected) {
    footer
      .append("button")
      .attr("class", "wiz-secondary")
      .style("border-color", "#f44")
      .style("color", "#f44")
      .text("DISCONNECT")
      .on("click", () => {
        _pmmDisconnect().then(() => {
          _pmmConnected = false;
          _pmmPendingPort = null;
          _pmmPort = null;
          _bpConnectPMM1();
        });
      });
    footer
      .append("button")
      .attr("class", "wiz-save")
      .text("NEXT: START READINGS →")
      .on("click", _bpBeginReadings);
  } else if (supported) {
    footer
      .append("button")
      .attr("class", "wiz-secondary")
      .text(_pmmPendingPort ? "↺ CHANGE PORT" : "SELECT PORT")
      .on("click", () => {
        window.PMM1.Port.request()
          .then((port) => {
            _pmmPendingPort = port;
            _bpConnectPMM1();
          })
          .catch((e) => {
            // User dismissed the picker, or no port granted.
            term
              .append("div")
              .text("✗ " + ((e && e.message) || e))
              .style("color", "#f44");
          });
      });
    footer
      .append("button")
      .attr("class", "wiz-save")
      .text("CONNECT →")
      .on("click", () => {
        if (!_pmmPendingPort) {
          term.append("div").text("⚠ SELECT A PORT FIRST").style("color", "#f80");
          return;
        }
        term.node().innerHTML = "";
        term
          .append("div")
          .text("> Opening serial port @ 19200 8N1...")
          .style("color", "#888");
        _pmmPendingPort
          .connect()
          .then((res) => {
            if (res.ok) {
              window.PMM1.active = _pmmPendingPort;
              _pmmConnected = true;
              _pmmPort = _pmmPendingPort.label();
              _pmmPendingPort = null;
              term
                .append("div")
                .text("AOK! — PMM-1 connected, m1 mode active")
                .style("color", "#0f0")
                .style("font-weight", "bold");
              setTimeout(_bpConnectPMM1, 600);
            } else {
              term
                .append("div")
                .text("✗ " + (res.error || "Connection failed"))
                .style("color", "#f44");
            }
          })
          .catch((e) =>
            term
              .append("div")
              .text("✗ " + ((e && e.message) || e))
              .style("color", "#f44"),
          );
      });
  }
}

// PMM-2 IP connection
function _bpConnectPMM2() {
  d3.select("#brain-point-module").style("width", "700px").style("height", "auto");
  const body = d3
    .select("#brain-point-body")
    .html("")
    .style("background", "#000")
    .style("color", "#0f0")
    .style("height", "auto")
    .style("padding", "20px");

  body
    .append("div")
    .text("PMM-2 CONNECTION  ·  TCP/IP PORT 5025")
    .style("font-size", "10px")
    .style("color", "#0a0")
    .style("letter-spacing", "1px")
    .style("margin-bottom", "18px");

  // IP Address input
  const ipRow = body
    .append("div")
    .style("display", "flex")
    .style("gap", "8px")
    .style("align-items", "center")
    .style("margin-bottom", "14px");
  ipRow
    .append("label")
    .text("IP ADDRESS")
    .style("font-size", "9px")
    .style("color", "#888")
    .style("white-space", "nowrap");
  const ipInput = ipRow
    .append("input")
    .attr("type", "text")
    .style("flex", "1")
    .style("background", "#111")
    .style("color", "#0f0")
    .style("border", "1px solid #040")
    .style("padding", "4px 8px")
    .property("value", _pmmIP);
  ipInput.on("input", function () {
    _pmmIP = this.value;
  });

  // Connection status terminal
  const term = body
    .append("div")
    .attr("id", "pmm-term")
    .style("background", "#000")
    .style("border", "1px solid #030")
    .style("padding", "10px")
    .style("font-size", "10px")
    .style("min-height", "80px")
    .style("color", "#0f0")
    .style("margin-bottom", "14px");

  if (_pmmConnected) {
    term
      .append("div")
      .text("✓ CONNECTED TO PMM-2 @ " + _pmmIP)
      .style("color", "#0f0")
      .style("font-weight", "bold");
    term.append("div").text("Ready for RTS commands.").style("color", "#555");
  } else {
    term.append("div").text("STATUS: DISCONNECTED").style("color", "#555");
    term
      .append("div")
      .text("Enter IP address and press CONNECT.")
      .style("color", "#333");
  }

  const footer = d3.select("#brain-point-footer").html("");
  footer
    .append("button")
    .attr("class", "wiz-secondary")
    .text("← BACK")
    .on("click", _bpRenderStep0);
  footer.append("div").style("flex", 1);

  if (_pmmConnected) {
    footer
      .append("button")
      .attr("class", "wiz-secondary")
      .style("border-color", "#f44")
      .style("color", "#f44")
      .text("DISCONNECT")
      .on("click", () => {
        fetch("/api/pmm/disconnect", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: "{}",
        }).then(() => {
          _pmmConnected = false;
          _bpConnectPMM2();
        });
      });
    footer
      .append("button")
      .attr("class", "wiz-save")
      .text("NEXT: START READINGS →")
      .on("click", _bpBeginReadings);
  } else {
    footer
      .append("button")
      .attr("class", "wiz-save")
      .text("CONNECT →")
      .on("click", () => {
        const ip = ipInput.node().value;
        if (!ip) {
          term.node().innerHTML = "";
          term
            .append("div")
            .text("⚠ ENTER IP ADDRESS FIRST")
            .style("color", "#f80");
          return;
        }
        _pmmIP = ip;
        term.node().innerHTML = "";
        term
          .append("div")
          .text("> Connecting to " + ip + " : 5025...")
          .style("color", "#888");
        fetch("/api/pmm/connect", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ port: ip, model: "pmm2" }),
        })
          .then((r) => r.json())
          .then((res) => {
            if (res.ok) {
              _pmmConnected = true;
              term
                .append("div")
                .text("AOK! — PMM-2 connected")
                .style("color", "#0f0")
                .style("font-weight", "bold");
              setTimeout(_bpConnectPMM2, 600);
            } else {
              term
                .append("div")
                .text("✗ " + (res.error || "Connection failed"))
                .style("color", "#f44");
            }
          })
          .catch((e) =>
            term
              .append("div")
              .text("✗ " + e)
              .style("color", "#f44"),
          );
      });
  }
}

// ── Device-group & Channel-config Helpers ─────────────────────────────────────

function _bpDeviceGroup(type) {
  if (!_deviceShowsCurrent(type)) return "voltage";
  if (!_deviceShowsVoltage(type)) return "current";
  return "multi";
}

function _bpApplyChanConfig(measType) {
  if (measType === "current") {
    _bpChan1 = _bpCurrChan1;
    _bpChan2 = _bpCurrChan2;
  } else {
    _bpChan1 = _bpVoltChan1;
    _bpChan2 = _bpVoltChan2;
  }
}

function _bpShowChannelConfig(measType, prevType, onDone) {
  // The disconnect-warning and physical-channel screens are about a meter's
  // leads and inputs — meaningless without one, and hit on every single
  // voltage/current transition, which is exactly what makes a manual session
  // feel like it's circling: pure typing-in-numbers has no leads to move and
  // no channel to reassign, so skip straight through. The one thing worth
  // keeping is the system reference VT, captured once per session rather
  // than re-asked at every transition.
  if (!_bpLiveInstrumentActive()) {
    _bpApplyChanConfig(measType);
    if (measType === "voltage" && _activeTestId && !_bpVrefCapturedThisSession) {
      // Offered once per session — whether it's filled in or skipped, later
      // voltage transitions won't ask again.
      _bpVrefCapturedThisSession = true;
      _bpCaptureVRef(_bpChan1, _bpRefVTId, false, onDone);
    } else {
      onDone();
    }
    return;
  }
  if (prevType !== null && prevType !== measType) {
    _bpShowDisconnectWarning(prevType, measType, () => _bpRenderChannelConfigOverlay(measType, onDone));
  } else {
    _bpRenderChannelConfigOverlay(measType, onDone);
  }
}

function _bpShowDisconnectWarning(fromType, toType, onConfirmed) {
  d3.select("#brain-point-module").style("width", "700px").style("height", "auto");
  const body = d3.select("#brain-point-body").html("");
  const footer = d3.select("#brain-point-footer").html("");

  body
    .style("background", "#0a0000")
    .style("color", "#f66")
    .style("display", "flex")
    .style("flex-direction", "column")
    .style("align-items", "center")
    .style("justify-content", "center")
    .style("padding", "40px 30px")
    .style("gap", "16px")
    .style("height", "auto");

  body.append("div")
    .text("⚠  CHANGING MEASUREMENT TYPE")
    .style("font-size", "18px")
    .style("font-weight", "bold")
    .style("letter-spacing", "2px")
    .style("color", "#f66");

  body.append("div")
    .text(`Switching from ${fromType.toUpperCase()} to ${toType.toUpperCase()} measurement`)
    .style("font-size", "11px")
    .style("color", "#888")
    .style("text-align", "center");

  const warn = body.append("div")
    .style("border", "2px solid #a60")
    .style("padding", "20px 28px")
    .style("border-radius", "4px")
    .style("background", "#0d0800")
    .style("text-align", "center")
    .style("max-width", "520px");

  warn.append("div")
    .text("DISCONNECT LEADS FROM ALL PROTECTION CIRCUITS")
    .style("font-size", "14px")
    .style("font-weight", "bold")
    .style("color", "#fa0")
    .style("letter-spacing", "1px")
    .style("margin-bottom", "10px");

  warn.append("div")
    .text(
      "Internal PMM circuitry may share input paths. Leaving probes connected during a " +
      "channel-type change can energize protection trip circuits or damage the instrument.",
    )
    .style("font-size", "10px")
    .style("color", "#888")
    .style("line-height", "1.6");

  footer.append("div").style("flex", 1);
  footer.append("button")
    .attr("class", "wiz-save")
    .text("LEADS DISCONNECTED — CONTINUE →")
    .style("background", "#0a0500")
    .style("border-color", "#fa0")
    .style("color", "#fa0")
    .on("click", onConfirmed);
}

function _bpRenderChannelConfigOverlay(measType, onDone) {
  d3.select("#brain-point-module").style("width", "750px").style("height", "auto");
  const body = d3.select("#brain-point-body").html("");
  const footer = d3.select("#brain-point-footer").html("");

  body
    .style("background", "#111")
    .style("color", "#eee")
    .style("height", "auto")
    .style("padding", "20px");

  const isVolt = measType === "voltage";
  const savedC1 = isVolt ? _bpVoltChan1 : _bpCurrChan1;
  const savedC2 = isVolt ? _bpVoltChan2 : _bpCurrChan2;
  const recommendedC1 = isVolt ? savedC1 : _bpVoltChan1;

  body.append("div")
    .text(`CHANNEL SETUP — ${isVolt ? "VOLTAGE" : "CURRENT"} MEASUREMENT`)
    .style("font-size", "11px")
    .style("color", isVolt ? "#66f" : "#0f0")
    .style("letter-spacing", "1px")
    .style("margin-bottom", "20px")
    .style("border-bottom", "1px solid #1a1a1a")
    .style("padding-bottom", "10px");

  const vtNodes = (currentData?.nodes || []).filter((n) =>
    ["VoltageTransformer", "DualWindingVT"].includes(n.type),
  );
  if (vtNodes.length > 0) {
    body.append("label").text("SYSTEM REFERENCE VT")
      .style("font-size", "10px").style("color", "#888")
      .style("display", "block").style("margin-bottom", "4px");
    const vtSel = body.append("select")
      .style("width", "100%").style("margin-bottom", "15px")
      .style("background", "#222").style("color", "#eee").style("padding", "4px")
      .on("change", function () { _bpRefVTId = this.value; });
    vtSel.append("option").attr("value", "").text("-- SELECT REFERENCE VT FROM SYSTEM --");
    vtNodes.forEach((n) =>
      vtSel.append("option").attr("value", n.id).text(n.id).property("selected", _bpRefVTId === n.id),
    );
  }

  let c1Val = recommendedC1;
  body.append("label").text("CHANNEL 1 (Reference Voltage)")
    .style("font-size", "10px").style("color", "#888")
    .style("display", "block").style("margin-bottom", "4px");
  if (!isVolt) {
    body.append("div")
      .text(`Recommended: ${PMM_SOURCES[recommendedC1]?.l || recommendedC1} (last voltage reference)`)
      .style("font-size", "9px").style("color", "#555").style("margin-bottom", "6px");
  }
  const sel1 = body.append("select")
    .style("width", "100%").style("margin-bottom", "15px")
    .style("background", "#222").style("color", "#eee").style("padding", "4px")
    .on("change", function () { c1Val = parseInt(this.value); });
  PMM_SOURCES.slice(0, 6).forEach((s) =>
    sel1.append("option").attr("value", s.v).text(s.l).property("selected", recommendedC1 === s.v),
  );

  let c2Val = savedC2;
  const chanLabel = isVolt ? "CHANNEL 2 (Voltage Measurement)" : "CHANNEL 2 (Current Measurement)";
  body.append("label").text(chanLabel)
    .style("font-size", "10px").style("color", "#888")
    .style("display", "block").style("margin-bottom", "4px");
  const sel2 = body.append("select")
    .style("width", "100%").style("background", "#222").style("color", "#eee").style("padding", "4px")
    .on("change", function () { c2Val = parseInt(this.value); });
  const chan2Sources = isVolt ? PMM_SOURCES.slice(0, 6) : PMM_SOURCES.slice(6);
  chan2Sources.forEach((s) =>
    sel2.append("option").attr("value", s.v).text(s.l).property("selected", savedC2 === s.v),
  );

  footer.append("div").style("flex", 1);
  footer.append("button")
    .attr("class", "wiz-save")
    .text(isVolt ? "CAPTURE REFERENCE →" : "BEGIN MEASUREMENT →")
    .on("click", () => {
      if (isVolt) { _bpVoltChan1 = c1Val; _bpVoltChan2 = c2Val; }
      else { _bpCurrChan1 = c1Val; _bpCurrChan2 = c2Val; }
      _bpChan1 = c1Val;
      _bpChan2 = c2Val;
      const isMeter = (
        (_bpInstrumentType === "pmm1" || _bpInstrumentType === "pmm2") &&
        _pmmConnected
      );
      if (isMeter) {
        Promise.resolve(_pmmConfigure(c1Val, c2Val)).catch(() => {});
      }
      if (isVolt && _activeTestId && !_bpVrefCapturedThisSession) {
        // Offered once per session, same as the manual path — otherwise a
        // meter session gets asked to re-capture it on every voltage pass.
        _bpVrefCapturedThisSession = true;
        _bpCaptureVRef(c1Val, _bpRefVTId, isMeter, onDone);
      } else {
        onDone();
      }
    });
}

// Capture the system reference VT magnitude after the voltage channel has been
// configured. Meter sessions read chan1 from the live meter feed; manual
// sessions prompt the user. Result is POSTed to /api/tests/vref.
function _bpCaptureVRef(chan1Val, refVTId, isMeter, onDone) {
  d3.select("#brain-point-module").style("width", "750px").style("height", "auto");
  const body = d3.select("#brain-point-body").html("");
  const footer = d3.select("#brain-point-footer").html("");

  body
    .style("background", "#111")
    .style("color", "#eee")
    .style("height", "auto")
    .style("padding", "20px");

  body.append("div")
    .text("SYSTEM REFERENCE VT — MAGNITUDE CAPTURE")
    .style("font-size", "11px")
    .style("color", "#66f")
    .style("letter-spacing", "1px")
    .style("margin-bottom", "20px")
    .style("border-bottom", "1px solid #1a1a1a")
    .style("padding-bottom", "10px");

  const chanLabel = (PMM_SOURCES[chan1Val] && PMM_SOURCES[chan1Val].l) || String(chan1Val);
  const label = (refVTId ? refVTId + " " : "") + chanLabel;

  body.append("div")
    .text("Reference label that will be stored on this test:")
    .style("font-size", "10px").style("color", "#888").style("margin-bottom", "4px");
  body.append("div")
    .text(label)
    .style("font-size", "13px").style("color", "#fff")
    .style("background", "#1a1a1a").style("padding", "6px 10px")
    .style("margin-bottom", "16px").style("border", "1px solid #2a2a2a");

  body.append("label").text("MAGNITUDE (V) — angle = 0 by definition")
    .style("font-size", "10px").style("color", "#888")
    .style("display", "block").style("margin-bottom", "4px");
  const magInput = body.append("input")
    .attr("type", "number").attr("step", "0.001")
    .attr("placeholder", isMeter ? "click READ FROM METER below" : "type the measured magnitude")
    .style("width", "100%").style("background", "#222").style("color", "#eee")
    .style("padding", "6px 8px").style("border", "1px solid #333")
    .style("font-family", "inherit").style("font-size", "12px")
    .style("box-sizing", "border-box");

  const status = body.append("div")
    .style("font-size", "10px").style("color", "#888").style("margin-top", "8px").style("min-height", "14px");

  if (isMeter) {
    body.append("button")
      .text("READ FROM METER")
      .style("margin-top", "12px")
      .style("background", "#001a1a").style("border", "1px solid #0aa").style("color", "#0cc")
      .style("font-family", "inherit").style("font-size", "10px")
      .style("padding", "6px 14px").style("cursor", "pointer").style("letter-spacing", "1px")
      .on("click", function () {
        status.text("querying meter…").style("color", "#888");
        Promise.resolve(_pmmQuery())
          .then(res => {
            if (res && res.ok && typeof res.chan1 === "number") {
              magInput.property("value", res.chan1.toFixed(4));
              status.text("captured chan1 = " + res.chan1.toFixed(4) + " V").style("color", "#0a0");
            } else {
              status.text("meter read failed: " + (res && res.error || "no chan1")).style("color", "#f44");
            }
          })
          .catch(e => status.text("meter read error: " + e).style("color", "#f44"));
      });
  } else {
    magInput.node().focus();
  }

  // A meter session came from the channel-config screen and can go back to
  // it; a manual session skipped straight here, so "back" is really "skip
  // capturing a reference for now" — same destination, onDone(), either way.
  const isMeterFlow = _bpLiveInstrumentActive();
  footer.append("button")
    .text(isMeterFlow ? "← BACK" : "SKIP FOR NOW →")
    .style("background", "#0a0a0a").style("border", "1px solid #333").style("color", "#666")
    .style("font-family", "inherit").style("font-size", "10px")
    .style("padding", "6px 12px").style("cursor", "pointer")
    .on("click", () => {
      if (isMeterFlow) _bpRenderChannelConfigOverlay("voltage", onDone);
      else onDone();
    });
  footer.append("div").style("flex", 1);
  footer.append("button")
    .attr("class", "wiz-save")
    .text("SAVE & BEGIN MEASUREMENT →")
    .on("click", () => {
      const raw = magInput.property("value");
      const mag = raw === "" ? null : parseFloat(raw);
      if (raw !== "" && (Number.isNaN(mag) || mag < 0)) {
        status.text("magnitude must be a non-negative number").style("color", "#f44");
        return;
      }
      fetch("/api/tests/vref", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          test_id: _activeTestId,
          label: label,
          magnitude: mag,
        }),
      })
        .then(r => r.json())
        .then(res => {
          if (res && res.ok) onDone();
          else status.text("save failed: " + (res && res.error || "unknown")).style("color", "#f44");
        })
        .catch(e => status.text("save error: " + e).style("color", "#f44"));
    });
}

// Render a compact drawings reference strip into `parentSel` for the given device.
// Appends a hidden div that fills in async; stays hidden if the device has no drawings.
function _bpRenderDrawingsStrip(parentSel, deviceId) {
  const strip = parentSel.append("div")
    .style("display", "none")
    .style("margin-bottom", "8px")
    .style("background", "#0a0a14")
    .style("border", "1px solid #1a1a2a")
    .style("padding", "5px 10px")
    .style("border-radius", "4px")
    .style("align-items", "center")
    .style("gap", "8px")
    .style("flex-wrap", "wrap");

  fetchDeviceDrawings(deviceId).then(resp => {
    const drawings = resp.drawings || [];
    if (drawings.length === 0) return;
    strip.style("display", "flex");
    strip.append("span").text("DRAWINGS:")
      .style("font-size", "9px").style("color", "#555").style("letter-spacing", "1px");
    drawings.forEach(d => {
      const chip = strip.append("span")
        .style("font-size", "9px").style("border", "1px solid #1a1a3a")
        .style("padding", "2px 8px").style("border-radius", "3px");
      const label = d.title + (d.revision ? ` (${d.revision})` : "");
      if (d.url) {
        chip.style("color", "#3af").style("cursor", "pointer")
          .text(label).on("click", () => window.open(d.url, "_blank"));
      } else {
        chip.style("color", "#556").text(label);
      }
    });
  }).catch(() => {});
}

// Device drawings manager — shown inline inside the brain-point panel.
// onBack: function to call when the user returns (typically _bpRenderStep4).
function _bpShowDeviceDrawings(deviceId, onBack) {
  d3.select("#brain-point-module").style("width", "700px").style("height", "auto");
  const body = d3.select("#brain-point-body").html("").style("padding", "16px").style("height", "auto");

  body.append("div")
    .text(`DRAWINGS — ${deviceId}`)
    .style("font-size", "10px").style("color", "#3af").style("letter-spacing", "1px")
    .style("border-bottom", "1px solid #1a1a2a").style("padding-bottom", "8px")
    .style("margin-bottom", "12px");

  const listDiv = body.append("div").attr("id", "ddraw-list");

  const addFormDiv = body.append("div")
    .style("margin-top", "14px").style("border-top", "1px solid #1a1a1a").style("padding-top", "12px");
  addFormDiv.append("div").text("ADD DRAWING")
    .style("font-size", "9px").style("color", "#888").style("letter-spacing", "1px").style("margin-bottom", "8px");

  const fieldStyle = "background:#111; border:1px solid #333; color:#eee; padding:6px 8px; font-family:inherit; font-size:11px; width:100%; box-sizing:border-box;";
  addFormDiv.append("input").attr("id", "ddraw-title").attr("type", "text")
    .attr("placeholder", "Drawing title *")
    .attr("style", fieldStyle + "margin-bottom:6px;");
  const row2 = addFormDiv.append("div").style("display", "flex").style("gap", "6px").style("margin-bottom", "6px");
  row2.append("input").attr("id", "ddraw-rev").attr("type", "text")
    .attr("placeholder", "Revision").attr("style", "background:#111;border:1px solid #333;color:#eee;padding:6px 8px;font-family:inherit;font-size:11px;width:80px;box-sizing:border-box;");
  row2.append("input").attr("id", "ddraw-url").attr("type", "text")
    .attr("placeholder", "URL / reference").attr("style", "background:#111;border:1px solid #333;color:#eee;padding:6px 8px;font-family:inherit;font-size:11px;flex:1;box-sizing:border-box;");
  addFormDiv.append("input").attr("id", "ddraw-notes").attr("type", "text")
    .attr("placeholder", "Notes (sheet numbers, etc.)")
    .attr("style", fieldStyle + "margin-bottom:8px;");

  const addBtn = addFormDiv.append("button")
    .text("+ ADD")
    .style("background", "#001a00").style("border", "1px solid #0f0").style("color", "#0f0")
    .style("font-family", "inherit").style("font-size", "10px").style("padding", "6px 16px")
    .style("cursor", "pointer").style("letter-spacing", "1px");

  const renderList = () => {
    fetchDeviceDrawings(deviceId).then(resp => {
      const drawings = resp.drawings || [];
      const list = d3.select("#ddraw-list").html("");
      if (drawings.length === 0) {
        list.append("div").text("No drawings attached yet.")
          .style("font-size", "9px").style("color", "#333").style("padding", "4px 0");
        return;
      }
      drawings.forEach(d => {
        const block = list.append("div")
          .style("border-bottom", "1px solid #111").style("padding", "6px 0");

        // ── Main row: title + revision + action buttons ──────────────────────
        const item = block.append("div")
          .style("display", "flex").style("align-items", "center").style("gap", "8px");

        const label = item.append("div").style("flex", "1").style("font-size", "10px");
        if (d.url) {
          label.append("a").attr("href", d.url).attr("target", "_blank")
            .text(d.title).style("color", "#3af").style("text-decoration", "none");
        } else {
          label.append("span").text(d.title).style("color", "#ccc");
        }
        if (d.revision) label.append("span").text(` (${d.revision})`).style("color", "#888").style("font-size", "9px");
        if (d.notes) label.append("div").text(d.notes).style("color", "#444").style("font-size", "9px");

        const btnStyle = "background:none; border:1px solid #2a2a2a; color:#666; cursor:pointer; font-size:9px; padding:1px 6px; font-family:inherit; letter-spacing:1px;";
        // "UPDATE REV" button toggles inline update form
        const updateBtn = item.append("button").attr("style", btnStyle).text("UPDATE REV");
        // "HISTORY" button toggles revision log
        const histBtn = item.append("button").attr("style", btnStyle).text("HISTORY");
        // Delete
        item.append("button").text("×")
          .style("background", "none").style("border", "none").style("color", "#555")
          .style("cursor", "pointer").style("font-size", "14px").style("padding", "0 4px")
          .on("click", () => deleteDeviceDrawing(d.id).then(renderList).catch(() => {}));

        // ── Inline UPDATE REV form (hidden by default) ───────────────────────
        const updateForm = block.append("div")
          .style("display", "none")
          .style("margin-top", "6px").style("padding", "8px 10px")
          .style("background", "#0d0d0d").style("border", "1px solid #222")
          .style("border-radius", "3px");

        updateForm.append("div").text("NEW REVISION")
          .style("font-size", "9px").style("color", "#666").style("letter-spacing", "1px")
          .style("margin-bottom", "6px");

        const inpRow = updateForm.append("div").style("display", "flex").style("gap", "6px").style("margin-bottom", "6px");
        const revInp = inpRow.append("input").attr("type", "text")
          .attr("placeholder", "e.g. R4")
          .attr("style", "background:#111;border:1px solid #333;color:#eee;padding:5px 8px;font-family:inherit;font-size:11px;width:80px;box-sizing:border-box;");
        const urlInp = inpRow.append("input").attr("type", "text")
          .attr("placeholder", "URL (leave blank to keep current)")
          .attr("style", "background:#111;border:1px solid #333;color:#eee;padding:5px 8px;font-family:inherit;font-size:11px;flex:1;box-sizing:border-box;");
        const byInp = inpRow.append("input").attr("type", "text")
          .attr("placeholder", "Updated by")
          .attr("style", "background:#111;border:1px solid #333;color:#eee;padding:5px 8px;font-family:inherit;font-size:11px;width:100px;box-sizing:border-box;");

        const saveRevBtn = updateForm.append("button")
          .text("SAVE REVISION")
          .style("background", "#001a1a").style("border", "1px solid #3af").style("color", "#3af")
          .style("font-family", "inherit").style("font-size", "9px").style("padding", "4px 12px")
          .style("cursor", "pointer").style("letter-spacing", "1px");

        saveRevBtn.on("click", () => {
          const rev = (revInp.property("value") || "").trim();
          if (!rev) { revInp.style("border-color", "#f00"); return; }
          revInp.style("border-color", "#333");
          const newUrl = (urlInp.property("value") || "").trim() || null;
          const by = (byInp.property("value") || "").trim();
          saveRevBtn.text("SAVING...").property("disabled", true);
          updateDeviceDrawing(d.id, rev, newUrl, by, "").then(() => renderList()).catch(() => {
            saveRevBtn.text("SAVE REVISION").property("disabled", false);
          });
        });

        updateBtn.on("click", () => {
          const showing = updateForm.style("display") !== "none";
          updateForm.style("display", showing ? "none" : "block");
          histArea.style("display", "none");
        });

        // ── Revision history area (hidden by default) ────────────────────────
        const histArea = block.append("div").style("display", "none");

        histBtn.on("click", () => {
          const showing = histArea.style("display") !== "none";
          if (showing) { histArea.style("display", "none"); return; }
          updateForm.style("display", "none");
          histArea.style("display", "block").html("<div style='font-size:9px;color:#444;padding:4px 0'>Loading...</div>");
          fetchDrawingHistory(d.id).then(hresp => {
            const entries = hresp.history || [];
            histArea.html("");
            if (entries.length === 0) {
              histArea.append("div").text("No revision history yet.")
                .style("font-size", "9px").style("color", "#333").style("padding", "4px 0");
              return;
            }
            const tbl = histArea.append("div")
              .style("margin-top", "4px").style("border-left", "2px solid #1a1a2a")
              .style("padding-left", "8px");
            entries.forEach(h => {
              const hrow = tbl.append("div").style("font-size", "9px").style("padding", "3px 0")
                .style("border-bottom", "1px solid #0d0d0d").style("display", "flex")
                .style("gap", "8px").style("align-items", "baseline");
              hrow.append("span")
                .text(new Date(h.epoch * 1000).toLocaleDateString())
                .style("color", "#444").style("min-width", "70px");
              hrow.append("span")
                .text(`${h.old_revision || "—"} → ${h.new_revision}`)
                .style("color", "#3af");
              if (h.updated_by) hrow.append("span").text(h.updated_by).style("color", "#556");
            });
          }).catch(() => { histArea.html("<div style='font-size:9px;color:#555'>Error loading history.</div>"); });
        });
      });
    }).catch(() => {});
  };

  renderList();

  addBtn.on("click", () => {
    const title = (document.getElementById("ddraw-title").value || "").trim();
    if (!title) { document.getElementById("ddraw-title").style.borderColor = "#f00"; return; }
    document.getElementById("ddraw-title").style.borderColor = "#333";
    addBtn.text("SAVING...").property("disabled", true);
    addDeviceDrawing(
      deviceId, title,
      (document.getElementById("ddraw-url").value || "").trim(),
      (document.getElementById("ddraw-rev").value || "").trim(),
      (document.getElementById("ddraw-notes").value || "").trim(),
    ).then(() => {
      document.getElementById("ddraw-title").value = "";
      document.getElementById("ddraw-url").value = "";
      document.getElementById("ddraw-rev").value = "";
      document.getElementById("ddraw-notes").value = "";
      addBtn.text("+ ADD").property("disabled", false);
      renderList();
    }).catch(() => { addBtn.text("+ ADD").property("disabled", false); });
  });

  const footer = d3.select("#brain-point-footer").html("");
  footer.append("button").attr("class", "wiz-secondary").text("← BACK TO CAPTURE POINTS")
    .on("click", onBack);
}

// ── Standalone Device Drawings Manager ───────────────────────────────────────
// A full-screen overlay modal for viewing and managing drawings attached to a
// device.  Called from device info windows and drawing chips.

function _openDrawingsManager(deviceId) {
  const existing = document.getElementById("_ddm-overlay");
  if (existing) existing.remove();

  const overlay = document.createElement("div");
  overlay.id = "_ddm-overlay";
  overlay.style.cssText =
    "position:fixed;inset:0;background:rgba(0,0,0,0.82);z-index:11000;" +
    "display:flex;align-items:center;justify-content:center;";

  const box = document.createElement("div");
  box.style.cssText =
    "background:#0c0c0c;border:1px solid #2a2a4a;min-width:560px;max-width:780px;" +
    "width:90vw;max-height:85vh;display:flex;flex-direction:column;" +
    "font-family:'Consolas','Courier New',monospace;box-shadow:0 20px 60px rgba(0,0,0,0.95);";

  // Header
  const hdr = document.createElement("div");
  hdr.style.cssText =
    "display:flex;justify-content:space-between;align-items:center;" +
    "padding:12px 16px;background:#111;border-bottom:1px solid #1e1e3a;flex-shrink:0;";
  hdr.innerHTML =
    `<span style="color:#aaf;font-size:11px;letter-spacing:1px;">📎 DRAWINGS — <span style="color:#fff;">${deviceId}</span></span>` +
    `<span id="_ddm-close" style="cursor:pointer;color:#555;font-size:16px;padding:0 4px;" title="Close">✕</span>`;

  // Scrollable list area
  const listWrap = document.createElement("div");
  listWrap.style.cssText = "flex:1;overflow-y:auto;padding:12px 16px;";
  listWrap.id = "_ddm-list";

  // Add form section
  const addSec = document.createElement("div");
  addSec.style.cssText =
    "flex-shrink:0;padding:12px 16px;border-top:1px solid #1a1a2a;background:#080810;";
  addSec.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
      <span style="font-size:9px;color:#666;letter-spacing:1px;">ADD / ATTACH A DRAWING</span>
      <button id="_ddm-search-btn"
        style="background:#04121c;border:1px solid #3af;color:#7fd0ff;font-family:inherit;
               font-size:9px;letter-spacing:1px;padding:4px 10px;cursor:pointer;">
        🔍 SEARCH CORPORATE DRAWINGS
      </button>
    </div>
    <input id="_ddm-title" type="text" placeholder="Drawing title *"
      style="width:100%;box-sizing:border-box;background:#111;border:1px solid #333;color:#eee;
             padding:6px 8px;font-family:inherit;font-size:11px;margin-bottom:6px;" />
    <div style="display:flex;gap:6px;margin-bottom:6px;">
      <input id="_ddm-rev" type="text" placeholder="Revision (e.g. R3)"
        style="width:90px;background:#111;border:1px solid #333;color:#eee;
               padding:6px 8px;font-family:inherit;font-size:11px;box-sizing:border-box;" />
      <input id="_ddm-url" type="text" placeholder="URL or document reference (optional)"
        style="flex:1;background:#111;border:1px solid #333;color:#eee;
               padding:6px 8px;font-family:inherit;font-size:11px;box-sizing:border-box;" />
    </div>
    <input id="_ddm-notes" type="text" placeholder="Notes — sheet numbers, scope, etc."
      style="width:100%;box-sizing:border-box;background:#111;border:1px solid #333;color:#888;
             padding:6px 8px;font-family:inherit;font-size:10px;margin-bottom:8px;" />
    <input id="_ddm-dwgnum" type="hidden" />
    <button id="_ddm-add-btn"
      style="background:#001a20;border:1px solid #aaf;color:#aaf;font-family:inherit;
             font-size:10px;padding:6px 20px;cursor:pointer;letter-spacing:1px;">
      + ATTACH DRAWING
    </button>`;

  box.appendChild(hdr);
  box.appendChild(listWrap);
  box.appendChild(addSec);
  overlay.appendChild(box);
  document.body.appendChild(overlay);

  // Close handlers
  document.getElementById("_ddm-close").onclick = () => overlay.remove();
  overlay.addEventListener("click", e => { if (e.target === overlay) overlay.remove(); });

  // Corporate drawing search → prefill the add form from a chosen result.
  const searchBtn = document.getElementById("_ddm-search-btn");
  if (searchBtn && typeof _openDrawingSearch === "function") {
    const node = currentData && currentData.nodes && currentData.nodes.find(n => n.id === deviceId);
    searchBtn.onclick = () => {
      _openDrawingSearch({ deviceId, deviceType: node && node.type }, (d) => {
        const set = (id, v) => { const el = document.getElementById(id); if (el) el.value = v || ""; };
        set("_ddm-title", d.title || d.drawing_number);
        set("_ddm-rev", d.revision);
        set("_ddm-url", d.document_url);
        set("_ddm-dwgnum", d.drawing_number);
        const bits = ["DWG " + d.drawing_number];
        if (d.drawing_subject) bits.push("subj " + d.drawing_subject);
        if (d.legacy_doc_number) bits.push("legacy " + d.legacy_doc_number);
        set("_ddm-notes", bits.join(" · "));
        const t = document.getElementById("_ddm-title");
        if (t) { t.style.borderColor = "#3af"; setTimeout(() => (t.style.borderColor = "#333"), 900); t.focus(); }
      });
    };
  } else if (searchBtn) {
    searchBtn.style.display = "none";
  }

  const renderList = () => {
    const listEl = document.getElementById("_ddm-list");
    if (!listEl) return;
    listEl.innerHTML = '<div style="font-size:9px;color:#333;padding:4px 0;">Loading…</div>';
    fetchDeviceDrawings(deviceId).then(resp => {
      const drawings = resp.drawings || [];
      if (drawings.length === 0) {
        listEl.innerHTML = '<div style="font-size:10px;color:#333;padding:8px 0;">No drawings attached to this device yet.</div>';
        return;
      }
      listEl.innerHTML = "";
      drawings.forEach(d => {
        const row = document.createElement("div");
        row.style.cssText = "border-bottom:1px solid #111;padding:8px 0;";

        // Main info row
        const main = document.createElement("div");
        main.style.cssText = "display:flex;align-items:center;gap:10px;";

        // Title + revision + notes
        const info = document.createElement("div");
        info.style.cssText = "flex:1;min-width:0;";
        if (d.url) {
          info.innerHTML = `<a href="${d.url}" target="_blank"
            style="color:#aaf;text-decoration:none;font-size:11px;font-weight:bold;">${d.title}</a>`;
        } else {
          info.innerHTML = `<span style="color:#ccc;font-size:11px;font-weight:bold;">${d.title}</span>`;
        }
        if (d.revision) {
          info.innerHTML += ` <span style="color:#556;font-size:9px;background:#0a0a14;
            border:1px solid #1a1a2a;padding:1px 6px;border-radius:3px;">${d.revision}</span>`;
        }
        if (d.url) {
          info.innerHTML += ` <button onclick="window.open('${d.url.replace(/'/g,"\\'")}','_blank')"
            style="background:#0a0a1a;border:1px solid #2a2a4a;color:#88a;font-size:9px;
                   padding:1px 7px;cursor:pointer;font-family:inherit;margin-left:4px;">
            OPEN ↗</button>`;
        }
        if (d.notes) {
          info.innerHTML += `<div style="color:#444;font-size:9px;margin-top:2px;">${d.notes}</div>`;
        }

        // Action buttons
        const actions = document.createElement("div");
        actions.style.cssText = "display:flex;gap:4px;flex-shrink:0;";
        const btnCss = "background:none;border:1px solid #222;color:#555;cursor:pointer;" +
                       "font-size:9px;padding:2px 7px;font-family:inherit;letter-spacing:1px;";

        const updBtn = document.createElement("button");
        updBtn.style.cssText = btnCss;
        updBtn.textContent = "UPDATE REV";
        const histBtn = document.createElement("button");
        histBtn.style.cssText = btnCss;
        histBtn.textContent = "HISTORY";
        const revBtn = document.createElement("button");
        revBtn.style.cssText = btnCss;
        revBtn.textContent = "REVISIONS";
        if (!d.drawing_number) { revBtn.disabled = true; revBtn.title = "no drawing number on this attachment"; }
        const delBtn = document.createElement("button");
        delBtn.style.cssText = btnCss + "color:#622;border-color:#2a1010;";
        delBtn.textContent = "✕";
        delBtn.title = "Remove drawing";
        delBtn.onclick = () => {
          if (!confirm(`Remove "${d.title}" from ${deviceId}?`)) return;
          deleteDeviceDrawing(d.id).then(renderList);
        };

        actions.appendChild(updBtn);
        actions.appendChild(histBtn);
        actions.appendChild(revBtn);
        actions.appendChild(delBtn);
        main.appendChild(info);
        main.appendChild(actions);
        row.appendChild(main);

        // Inline UPDATE REV form (hidden)
        const updForm = document.createElement("div");
        updForm.style.cssText =
          "display:none;margin-top:8px;padding:10px;background:#0a0a14;" +
          "border:1px solid #1a1a2a;border-radius:3px;";
        updForm.innerHTML = `
          <div style="font-size:9px;color:#555;letter-spacing:1px;margin-bottom:6px;">NEW REVISION</div>
          <div style="display:flex;gap:6px;margin-bottom:6px;">
            <input class="_upd-rev" type="text" placeholder="e.g. R4"
              style="width:80px;background:#111;border:1px solid #333;color:#eee;
                     padding:5px 8px;font-family:inherit;font-size:11px;box-sizing:border-box;" />
            <input class="_upd-url" type="text" placeholder="New URL (blank = keep current)"
              style="flex:1;background:#111;border:1px solid #333;color:#eee;
                     padding:5px 8px;font-family:inherit;font-size:11px;box-sizing:border-box;" />
            <input class="_upd-by" type="text" placeholder="Updated by"
              style="width:110px;background:#111;border:1px solid #333;color:#eee;
                     padding:5px 8px;font-family:inherit;font-size:11px;box-sizing:border-box;" />
          </div>
          <button class="_upd-save" style="background:#001a1a;border:1px solid #3af;color:#3af;
            font-family:inherit;font-size:9px;padding:4px 14px;cursor:pointer;letter-spacing:1px;">
            SAVE REVISION</button>`;
        const revInp = updForm.querySelector("._upd-rev");
        const urlInp = updForm.querySelector("._upd-url");
        const byInp  = updForm.querySelector("._upd-by");
        const saveBtn = updForm.querySelector("._upd-save");
        saveBtn.onclick = () => {
          const rev = revInp.value.trim();
          if (!rev) { revInp.style.borderColor = "#f00"; return; }
          revInp.style.borderColor = "#333";
          saveBtn.textContent = "SAVING…"; saveBtn.disabled = true;
          updateDeviceDrawing(d.id, rev, urlInp.value.trim() || null, byInp.value.trim(), "")
            .then(renderList);
        };
        updBtn.onclick = () => {
          const showing = updForm.style.display !== "none";
          updForm.style.display = showing ? "none" : "block";
          histArea.style.display = "none";
        };

        // Revision history area (hidden)
        const histArea = document.createElement("div");
        histArea.style.display = "none";
        histArea.style.marginTop = "8px";
        histBtn.onclick = () => {
          if (histArea.style.display !== "none") { histArea.style.display = "none"; return; }
          updForm.style.display = "none";
          histArea.style.display = "block";
          histArea.innerHTML = "<div style='font-size:9px;color:#333;padding:4px 0;'>Loading…</div>";
          fetchDrawingHistory(d.id).then(hresp => {
            const entries = hresp.history || [];
            if (!entries.length) {
              histArea.innerHTML = "<div style='font-size:9px;color:#333;padding:4px 0;'>No revision history yet.</div>";
              return;
            }
            histArea.innerHTML = entries.map(h =>
              `<div style="font-size:9px;padding:3px 0 3px 8px;border-left:2px solid #1a1a2a;
                           margin-bottom:3px;display:flex;gap:10px;">
                <span style="color:#444;min-width:70px;">${new Date(h.epoch*1000).toLocaleDateString()}</span>
                <span style="color:#3af;">${h.old_revision || "—"} → ${h.new_revision}</span>
                ${h.updated_by ? `<span style="color:#556;">${h.updated_by}</span>` : ""}
               </div>`
            ).join("");
          });
        };

        // Sibling-revision set (from the corporate system, cached per site)
        const revArea = document.createElement("div");
        revArea.style.display = "none";
        revArea.style.marginTop = "8px";
        revBtn.onclick = () => {
          if (revArea.style.display !== "none") { revArea.style.display = "none"; return; }
          updForm.style.display = "none";
          histArea.style.display = "none";
          revArea.style.display = "block";
          if (typeof renderDrawingRevisions === "function") {
            renderDrawingRevisions(revArea, {
              drawingNumber: d.drawing_number,
              currentRevision: d.revision,
              drawingId: d.id,
              onSwapped: renderList,
            });
          }
        };

        row.appendChild(updForm);
        row.appendChild(histArea);
        row.appendChild(revArea);
        listEl.appendChild(row);
      });
    }).catch(() => {
      const listEl = document.getElementById("_ddm-list");
      if (listEl) listEl.innerHTML = '<div style="color:#555;font-size:9px;">Error loading drawings.</div>';
    });
  };

  renderList();

  document.getElementById("_ddm-add-btn").onclick = () => {
    const title = (document.getElementById("_ddm-title").value || "").trim();
    if (!title) { document.getElementById("_ddm-title").style.borderColor = "#f00"; return; }
    document.getElementById("_ddm-title").style.borderColor = "#333";
    const btn = document.getElementById("_ddm-add-btn");
    btn.textContent = "ATTACHING…"; btn.disabled = true;
    addDeviceDrawing(
      deviceId, title,
      (document.getElementById("_ddm-url").value || "").trim(),
      (document.getElementById("_ddm-rev").value || "").trim(),
      (document.getElementById("_ddm-notes").value || "").trim(),
      (document.getElementById("_ddm-dwgnum").value || "").trim()
    ).then(() => {
      ["_ddm-title","_ddm-rev","_ddm-url","_ddm-notes","_ddm-dwgnum"].forEach(id => {
        const el = document.getElementById(id); if (el) el.value = "";
      });
      btn.textContent = "+ ATTACH DRAWING"; btn.disabled = false;
      renderList();
      // Refresh drawing strip in any open device window
      const node = currentData && currentData.nodes && currentData.nodes.find(n => n.id === deviceId);
      if (node) {
        const safeId = deviceId.replace(/\s+/g, "-");
        _renderWindowDrawingStrip(safeId, deviceId);
      }
    }).catch(() => { btn.textContent = "+ ATTACH DRAWING"; btn.disabled = false; });
  };
}

// ── Load Test Drawing Suggestion ──────────────────────────────────────────────
// After devices are selected for a test, check if any have drawings not yet
// in the test and offer to add them.

function _suggestTestDrawings(testId, deviceIds, onDone) {
  // Fetch all device drawings and existing test drawings in parallel
  Promise.all([
    fetchTestDetail(testId).catch(() => ({ drawings: [] })),
    ...deviceIds.map(id => fetchDeviceDrawings(id).then(r => ({ id, drawings: r.drawings || [] })).catch(() => ({ id, drawings: [] }))),
  ]).then(([testDetail, ...deviceResults]) => {
    const testDrawingTitles = new Set(
      (testDetail.drawings || []).map(d => d.title.toLowerCase().trim())
    );

    // Collect unique drawings not already in the test
    const suggestions = [];
    const seen = new Set();
    deviceResults.forEach(({ id: devId, drawings }) => {
      drawings.forEach(d => {
        const key = d.title.toLowerCase().trim();
        if (!testDrawingTitles.has(key) && !seen.has(key)) {
          seen.add(key);
          suggestions.push({ ...d, sourceDevice: devId });
        }
      });
    });

    if (suggestions.length === 0) { onDone(); return; }

    // Show suggestion modal
    const overlay = document.createElement("div");
    overlay.style.cssText =
      "position:fixed;inset:0;background:rgba(0,0,0,0.88);z-index:12000;" +
      "display:flex;align-items:center;justify-content:center;";

    const box = document.createElement("div");
    box.style.cssText =
      "background:#0c0c0c;border:1px solid #2a4a2a;min-width:480px;max-width:680px;" +
      "width:88vw;font-family:'Consolas','Courier New',monospace;box-shadow:0 20px 60px rgba(0,0,0,0.95);";

    const checkedIds = new Set(suggestions.map((_, i) => i));

    const render = () => {
      box.innerHTML = `
        <div style="padding:12px 16px;background:#0d160d;border-bottom:1px solid #1a2a1a;
                    display:flex;justify-content:space-between;align-items:center;">
          <span style="color:#8f8;font-size:11px;letter-spacing:1px;">
            📋 ADD DEVICE DRAWINGS TO TEST?
          </span>
          <span style="color:#555;font-size:9px;">${suggestions.length} drawing${suggestions.length !== 1 ? "s" : ""} found on selected devices</span>
        </div>
        <div style="padding:12px 16px;max-height:360px;overflow-y:auto;">
          ${suggestions.map((d, i) => `
            <label style="display:flex;align-items:flex-start;gap:10px;padding:7px 0;
                          border-bottom:1px solid #111;cursor:pointer;">
              <input type="checkbox" data-idx="${i}" ${checkedIds.has(i) ? "checked" : ""}
                style="margin-top:2px;flex-shrink:0;accent-color:#8f8;" />
              <div>
                <div style="font-size:11px;color:${d.url ? "#aaf" : "#ccc"};">
                  ${d.url ? `<a href="${d.url}" target="_blank"
                    style="color:#aaf;text-decoration:none;">${d.title}</a>` : d.title}
                  ${d.revision ? `<span style="color:#556;font-size:9px;background:#0a0a14;
                    border:1px solid #1a1a2a;padding:1px 5px;border-radius:3px;margin-left:5px;">${d.revision}</span>` : ""}
                </div>
                <div style="font-size:9px;color:#444;margin-top:2px;">
                  from device: <span style="color:#556;">${d.sourceDevice}</span>
                  ${d.notes ? ` · ${d.notes}` : ""}
                </div>
              </div>
            </label>`).join("")}
        </div>
        <div style="padding:10px 16px;display:flex;gap:8px;justify-content:flex-end;
                    border-top:1px solid #111;background:#080808;">
          <button id="_sug-skip"
            style="background:none;border:1px solid #333;color:#555;font-family:inherit;
                   font-size:10px;padding:6px 16px;cursor:pointer;letter-spacing:1px;">
            SKIP</button>
          <button id="_sug-add"
            style="background:#001a00;border:1px solid #8f8;color:#8f8;font-family:inherit;
                   font-size:10px;padding:6px 20px;cursor:pointer;letter-spacing:1px;">
            ADD SELECTED TO TEST</button>
        </div>`;

      // Wire checkboxes
      box.querySelectorAll("input[type=checkbox]").forEach(cb => {
        cb.onchange = () => {
          const idx = parseInt(cb.dataset.idx);
          if (cb.checked) checkedIds.add(idx); else checkedIds.delete(idx);
          box.querySelector("#_sug-add").textContent =
            `ADD ${checkedIds.size} TO TEST`;
        };
      });
      box.querySelector("#_sug-add").textContent =
        `ADD ${checkedIds.size} TO TEST`;

      box.querySelector("#_sug-skip").onclick = () => { overlay.remove(); onDone(); };
      box.querySelector("#_sug-add").onclick = () => {
        const toAdd = suggestions.filter((_, i) => checkedIds.has(i));
        if (!toAdd.length) { overlay.remove(); onDone(); return; }
        box.querySelector("#_sug-add").textContent = "ADDING…";
        box.querySelector("#_sug-add").disabled = true;
        Promise.all(toAdd.map(d =>
          addDrawing(testId, d.title, d.url || "", d.revision || "", d.notes || "")
        )).then(() => { overlay.remove(); onDone(); });
      };
    };

    render();
    overlay.appendChild(box);
    document.body.appendChild(overlay);
  });
}

function _bpRenderStep4() {
  d3.select("#brain-point-module")
    .style("width", "900px")
    .style("height", "680px")
    .style("top", "50%")
    .style("left", "50%")
    .style("transform", "translate(-50%, -50%)");

  const body = d3.select("#brain-point-body").html("");
  body.style("height", "auto").style("overflow-y", "auto").style("padding", "16px");
  body.append("h4").text("STEP 2: SELECT CAPTURE POINTS").style("margin-top", "0");

  const allNodes = (currentData?.nodes || []).filter((n) => WIZARD_MEASURABLE.has(n.type));
  const voltNodes  = allNodes.filter((n) => !_deviceShowsCurrent(n.type));
  const currNodes  = allNodes.filter((n) => !_deviceShowsVoltage(n.type));
  const relayNodes = allNodes.filter((n) => n.type === "Relay");
  const multiNodes = allNodes.filter(
    (n) => n.type !== "Relay" && _deviceShowsVoltage(n.type) && _deviceShowsCurrent(n.type),
  );

  _bpVoltDevices  = _bpVoltDevices.filter((id) => voltNodes.some((n) => n.id === id));
  _bpCurrDevices  = _bpCurrDevices.filter((id) => currNodes.some((n) => n.id === id));
  _bpRelayDevices = _bpRelayDevices.filter((id) => relayNodes.some((n) => n.id === id));
  _bpMultiDevices = _bpMultiDevices.filter((id) => multiNodes.some((n) => n.id === id));

  function renderGroup(label, nodes, getOrdered, setOrdered) {
    const section = body.append("div").style("margin-bottom", "18px");
    section
      .append("div")
      .text("─ " + label)
      .style("font-size", "9px")
      .style("color", "#555")
      .style("letter-spacing", "2px")
      .style("margin-bottom", "6px")
      .style("border-bottom", "1px solid #1a1a1a")
      .style("padding-bottom", "4px");

    const ordered = getOrdered();
    if (nodes.length === 0) {
      section
        .append("div")
        .text("No devices in this category")
        .style("font-size", "9px")
        .style("color", "#2a2a2a")
        .style("padding", "4px 0");
      return;
    }

    const selectedIds = ordered.filter((id) => nodes.some((n) => n.id === id));
    const unselectedIds = nodes.filter((n) => !ordered.includes(n.id)).map((n) => n.id);
    const displayIds = [...selectedIds, ...unselectedIds];

    const table = section.append("table").attr("class", "wizard-select-table");
    const tbody = table.append("tbody");

    displayIds.forEach((id) => {
      const node = nodes.find((n) => n.id === id);
      if (!node) return;
      const isChecked = ordered.includes(id);
      const rank = ordered.indexOf(id);

      const row = tbody.append("tr");
      row.append("td").text(id);
      row.append("td").text(node.type).style("color", "#555").style("font-size", "10px");

      const drawTd = row.append("td").style("width", "70px");
      drawTd.append("button")
        .attr("id", "draw-badge-" + id.replace(/[^\w]/g, "_"))
        .text("DRAW")
        .style("font-size", "8px").style("padding", "1px 5px")
        .style("background", "#111").style("color", "#444")
        .style("border", "1px solid #222").style("cursor", "pointer")
        .style("letter-spacing", "1px").style("font-family", "inherit")
        .on("click", () => _bpShowDeviceDrawings(id, _bpRenderStep4));

      const ctrlTd = row
        .append("td")
        .style("text-align", "right")
        .style("white-space", "nowrap")
        .style("width", "90px");

      if (isChecked && rank > 0) {
        ctrlTd
          .append("button")
          .text("↑")
          .style("padding", "1px 6px").style("font-size", "11px").style("cursor", "pointer")
          .style("margin-right", "2px").style("background", "#111")
          .style("color", "#888").style("border", "1px solid #333")
          .on("click", () => {
            const arr = [...ordered];
            const i = arr.indexOf(id);
            [arr[i - 1], arr[i]] = [arr[i], arr[i - 1]];
            setOrdered(arr);
            _bpRenderStep4();
          });
      } else {
        ctrlTd.append("span").style("display", "inline-block").style("width", "28px");
      }

      if (isChecked && rank < ordered.length - 1) {
        ctrlTd
          .append("button")
          .text("↓")
          .style("padding", "1px 6px").style("font-size", "11px").style("cursor", "pointer")
          .style("margin-right", "6px").style("background", "#111")
          .style("color", "#888").style("border", "1px solid #333")
          .on("click", () => {
            const arr = [...ordered];
            const i = arr.indexOf(id);
            [arr[i], arr[i + 1]] = [arr[i + 1], arr[i]];
            setOrdered(arr);
            _bpRenderStep4();
          });
      } else {
        ctrlTd.append("span").style("display", "inline-block").style("width", "30px");
      }

      ctrlTd
        .append("input")
        .attr("type", "checkbox")
        .property("checked", isChecked)
        .on("change", function () {
          if (this.checked) {
            if (!ordered.includes(id)) setOrdered([...ordered, id]);
          } else {
            setOrdered(ordered.filter((x) => x !== id));
          }
          _bpRenderStep4();
        });
    });
  }

  [
    ["VOLTAGE ONLY — VT · DVT · FTBlock · IsoBlock", voltNodes,  () => _bpVoltDevices,  arr => { _bpVoltDevices  = arr; }],
    ["CURRENT ONLY — CT · CTTB",                     currNodes,  () => _bpCurrDevices,  arr => { _bpCurrDevices  = arr; }],
    ["RELAY — Protection Devices",                   relayNodes, () => _bpRelayDevices, arr => { _bpRelayDevices = arr; }],
    ["MULTI-ANALOG — Primary Equipment",             multiNodes, () => _bpMultiDevices, arr => { _bpMultiDevices = arr; }],
  ].forEach(([label, nodes, get, set]) => renderGroup(label, nodes, get, set));

  // Async: update drawing badges with counts after table renders
  allNodes.forEach(({ id }) => {
    fetchDeviceDrawings(id).then(resp => {
      const count = (resp.drawings || []).length;
      const el = document.getElementById("draw-badge-" + id.replace(/[^\w]/g, "_"));
      if (!el) return;
      if (count > 0) {
        el.textContent = `DRAW (${count})`;
        el.style.color = "#3af";
        el.style.borderColor = "#3af";
      }
    }).catch(() => {});
  });

  const footer = d3.select("#brain-point-footer").html("");
  footer
    .append("button")
    .attr("class", "wiz-secondary")
    .text("← BACK")
    .on("click", () => {
      if (_bpInstrumentType === "pmm1") _bpConnectPMM1();
      else if (_bpInstrumentType === "pmm2") _bpConnectPMM2();
      else _bpRenderStep4();
    });
  footer.append("div").style("flex", 1);

  const totalSelected = _bpVoltDevices.length + _bpCurrDevices.length + _bpRelayDevices.length + _bpMultiDevices.length;
  footer
    .append("button")
    .attr("class", "wiz-save")
    .text("NEXT: SELECT INSTRUMENT →" + (totalSelected > 0 ? ` (${totalSelected})` : ""))
    .on("click", () => {
      _bpSelectedDevices = [..._bpVoltDevices, ..._bpCurrDevices, ..._bpRelayDevices, ..._bpMultiDevices];
      if (_bpSelectedDevices.length === 0) return;

      if (_activeTestId) {
        updateTestCapturePoints(_activeTestId, _bpSelectedDevices);
        // Offer to add device drawings to the test before proceeding
        _suggestTestDrawings(_activeTestId, _bpSelectedDevices, _bpRenderStep0);
      } else {
        _bpRenderStep0();
      }
    });
}

// ── PMM-1 Live Measurement Step ───────────────────────────────────────────────

function _pmmChan2ForPhase(baseChan2, phase) {
  // Auto-adjust channel 2 when stepping through phases.
  // Current inputs 6=Ia, 7=Ib, 8=Ic  →  map to phase
  if (baseChan2 >= 6 && baseChan2 <= 8)
    return 6 + ["A", "B", "C"].indexOf(phase);
  // LN voltage inputs 0=Van, 1=Vbn, 2=Vcn
  if (baseChan2 >= 0 && baseChan2 <= 2) return ["A", "B", "C"].indexOf(phase);
  return baseChan2; // LL or special — no auto-adjust
}

// ── Live instrument helpers ────────────────────────────────────────────────────

// True when the session's chosen instrument has an actual live connection right
// now (Web Serial port open for PMM-1, server-side socket up for PMM-2).
// "manual" is never live.
function _bpLiveInstrumentActive() {
  if (_bpInstrumentType === "pmm1") return !!(window.PMM1 && window.PMM1.active);
  if (_bpInstrumentType === "pmm2") return !!_pmmConnected;
  return false;
}

/** Common entry into the reading screen from any of the three places that
 *  lead there: manual chosen directly, or a meter just finished connecting. */
function _bpBeginReadings() {
  _bpTargetDeviceId = _bpSelectedDevices[0];
  _bpTargetPhase = "A";
  _bpManualOverride = false;
  _bpRenderReadingScreen();
}

function _bpInstrumentLabel() {
  if (_bpInstrumentType === "pmm1") return "PMM-1 · serial";
  if (_bpInstrumentType === "pmm2") return "PMM-2 · " + (_pmmIP || "network");
  return "manual entry";
}

// Per-reading override: even in a live-meter session, a digital relay's value
// comes off its own front-panel display, not a probe — this logs one point by
// hand without leaving the flow or disconnecting the meter. Resets when the
// target device changes; stays set across that device's phases, since a
// digital relay stays a digital relay for all of them.
let _bpManualOverride = false;

// Which of the MAG / ANG boxes the on-screen keypad is currently typing into.
let _bpKeypadTarget = "bp-mag-in";

function _bpKeypadPress(key) {
  const el = document.getElementById(_bpKeypadTarget);
  if (!el) return;
  if (key === "back") el.value = el.value.slice(0, -1);
  else if (key === "clear") el.value = "";
  else if (key === "sign")
    el.value = el.value.startsWith("-") ? el.value.slice(1) : "-" + el.value;
  else if (key === ".") {
    if (!el.value.includes(".")) el.value += ".";
  } else el.value += key;
}

function _bpFocusKeypad(inputId) {
  _bpKeypadTarget = inputId;
  ["bp-mag-in", "bp-ang-in"].forEach((id) => {
    const box = document.getElementById(id + "-wrap");
    if (box) box.style.borderColor = id === inputId ? "#0f0" : "#1a3a1a";
  });
}

/** A large, mouse/click-friendly numeric keypad — built for gloved hands where
 *  precise physical-keyboard presses are the actual bottleneck, not a
 *  touchscreen. Always targets whichever of MAG / ANG was last focused. */
function _bpRenderKeypad(container) {
  container.selectAll("*").remove();
  const rows = [
    ["7", "8", "9"],
    ["4", "5", "6"],
    ["1", "2", "3"],
    ["sign", "0", "."],
  ];
  const grid = container
    .append("div")
    .style("display", "grid")
    .style("grid-template-columns", "repeat(3, 1fr)")
    .style("gap", "6px");
  rows.forEach((row) => {
    row.forEach((k) => {
      grid
        .append("button")
        .text(k === "sign" ? "±" : k)
        .style("padding", "16px 0")
        .style("font-size", "20px")
        .style("font-weight", "bold")
        .style("background", "#111")
        .style("color", "#0f0")
        .style("border", "1px solid #333")
        .style("border-radius", "4px")
        .style("cursor", "pointer")
        .on("click", () => _bpKeypadPress(k));
    });
  });
  container
    .append("button")
    .text("⌫ BACKSPACE")
    .style("width", "100%")
    .style("margin-top", "6px")
    .style("padding", "14px 0")
    .style("font-size", "13px")
    .style("letter-spacing", "1px")
    .style("background", "#1a0a0a")
    .style("color", "#c66")
    .style("border", "1px solid #422")
    .style("border-radius", "4px")
    .style("cursor", "pointer")
    .on("click", () => _bpKeypadPress("back"));
}

/**
 * The one reading screen — replaces the old split between _bpRenderStep5
 * (manual) and _bpRenderPMMStep5 (PMM-1 only). PMM-1, PMM-2, "manual", and
 * whatever meter comes next are all the same operation: probe the point,
 * confirm the value, log it, move on. This renders that operation once,
 * branching only on whether *this* reading is coming off a live meter or a
 * hand-read display (a digital relay's front panel, or the session's own
 * "manual" choice) — never on which brand of meter it is.
 */
function _bpRenderReadingScreen() {
  const live = _bpLiveInstrumentActive() && !_bpManualOverride;

  d3.select("#status-bar")
    .style("background", "#040")
    .style("color", "#0f0")
    .text(
      live
        ? `MEASUREMENT — ${_bpInstrumentLabel()} LIVE`
        : "MEASUREMENT — manual entry",
    );
  d3.select("#brain-point-module")
    .style("width", "98vw")
    .style("height", "96vh")
    .style("top", "2vh")
    .style("left", "1vw")
    .style("transform", "none");

  const body = d3
    .select("#brain-point-body")
    .html("")
    .style("height", "calc(100% - 120px)");

  // Keyboard: Enter → log, arrows → navigate. Kept for anyone who prefers it;
  // the on-screen controls never require it.
  d3.select("body").on("keydown.bp", (e) => {
    if (d3.select("#brain-point-module").style("display") === "none") return;
    const magIn = document.getElementById("bp-mag-in");
    if (e.key === "Enter") {
      if (magIn && document.activeElement === magIn) {
        const angIn = document.getElementById("bp-ang-in");
        if (angIn) angIn.focus();
      } else {
        _bpLogCurrentPoint();
      }
      e.preventDefault();
    } else if (e.key === "ArrowRight") {
      _bpMoveToNextPhase();
      e.preventDefault();
    } else if (e.key === "ArrowLeft") {
      _bpMoveToPrevPhase();
      e.preventDefault();
    } else if (e.key === "ArrowDown") {
      _bpMoveToNextDevice();
      e.preventDefault();
    } else if (e.key === "ArrowUp") {
      _bpMoveToPrevDevice();
      e.preventDefault();
    }
  });

  if (_bpSelectedDevices.length === 0) {
    body
      .append("div")
      .text("NO DEVICES SELECTED.")
      .style("padding", "20px")
      .style("text-align", "center");
    return;
  }

  const node =
    ((currentData && currentData.nodes) &&
      currentData.nodes.find((n) => n.id === _bpTargetDeviceId)) ||
    ((currentData && currentData.nodes) &&
      currentData.nodes.find((n) => n.id === _bpSelectedDevices[0]));
  _bpTargetDeviceId = node.id;
  const refVT =
    (currentData && currentData.nodes) &&
    currentData.nodes.find((n) => n.id === _bpRefVTId);

  const expectedType = _bpDeviceExpectedType(node.type);
  const showsI = _deviceShowsCurrent(node.type);
  const isNeutralPhase = _bpTargetPhase === "N";
  const needsNeutral =
    showsI && (_bpSelectedMode === "m3y" || _bpSelectedMode === "m1");
  const phaseList = needsNeutral ? ["A", "B", "C", "N"] : ["A", "B", "C"];

  // ── Top controls: device, phase, instrument status ─────────────────────────
  const controls = body
    .append("div")
    .style("display", "flex")
    .style("flex-wrap", "wrap")
    .style("gap", "16px")
    .style("align-items", "flex-end")
    .style("margin-bottom", "12px")
    .style("background", "#161616")
    .style("padding", "12px")
    .style("border-radius", "4px");

  const devGrp = controls.append("div").style("flex", "1 1 220px");
  devGrp
    .append("label")
    .text("TARGET DEVICE")
    .style("font-size", "9px")
    .style("color", "#888")
    .style("display", "block");
  const devSel = devGrp
    .append("select")
    .style("width", "100%")
    .style("padding", "8px")
    .style("font-size", "13px")
    .style("background", "#111")
    .style("color", "#eee")
    .style("border", "1px solid #444")
    .on("change", function () {
      _bpTargetDeviceId = this.value;
      _bpManualOverride = false;
      _bpRenderReadingScreen();
    });
  _bpSelectedDevices.forEach((id) => {
    devSel
      .append("option")
      .attr("value", id)
      .text(id)
      .property("selected", _bpTargetDeviceId === id);
  });

  const phGrp = controls.append("div").style("flex", "1 1 260px");
  phGrp
    .append("label")
    .text("ACTIVE PHASE — tap or ← →")
    .style("font-size", "9px")
    .style("color", "#888")
    .style("display", "block")
    .style("margin-bottom", "3px");
  const phRow = phGrp.append("div").style("display", "flex").style("gap", "6px");
  phaseList.forEach((p) => {
    const isN = p === "N";
    phRow
      .append("button")
      .text(p)
      .style("flex", 1)
      .style("padding", "12px 0")
      .style("font-size", "16px")
      .style("font-weight", "bold")
      .style(
        "background",
        _bpTargetPhase === p ? (isN ? "#a0a000" : "#0f0") : "#333",
      )
      .style("color", _bpTargetPhase === p ? "#000" : isN ? "#aa0" : "#eee")
      .style("border", isN ? "1px solid #660" : "none")
      .style("border-radius", "4px")
      .style("cursor", "pointer")
      .on("click", () => {
        _bpTargetPhase = p;
        _bpRenderReadingScreen();
      });
  });

  const instGrp = controls
    .append("div")
    .style("flex", "1 1 240px")
    .style("display", "flex")
    .style("flex-direction", "column")
    .style("gap", "4px")
    .style("align-items", "flex-start");
  instGrp
    .append("div")
    .html(
      `<span style="color:#555;">◆ USING</span> <span style="color:${live ? "#0f0" : "#3af"};font-weight:bold;">${_bpInstrumentLabel()}</span>` +
        (_bpManualOverride ? ' <span style="color:#aa0;">(override)</span>' : ""),
    )
    .style("font-size", "11px");
  if (_bpLiveInstrumentActive()) {
    instGrp
      .append("button")
      .text(
        _bpManualOverride
          ? "◀ USE " + (_bpInstrumentType === "pmm1" ? "PMM-1" : "PMM-2") + " AGAIN"
          : "✎ ENTER THIS ONE BY HAND",
      )
      .style("padding", "8px 12px")
      .style("font-size", "10px")
      .style("letter-spacing", "0.5px")
      .style("background", _bpManualOverride ? "#001a0a" : "#1a1500")
      .style("color", _bpManualOverride ? "#0f6" : "#fa0")
      .style("border", "1px solid " + (_bpManualOverride ? "#0f6" : "#663"))
      .style("border-radius", "4px")
      .style("cursor", "pointer")
      .on("click", () => {
        _bpManualOverride = !_bpManualOverride;
        _pmmLastReading = null;
        _bpRenderReadingScreen();
      });
    instGrp
      .append("div")
      .text("for digital relays and anything else read off a display")
      .style("font-size", "8px")
      .style("color", "#444");
  }

  // Device drawings reference strip (populated async)
  _bpRenderDrawingsStrip(body, _bpTargetDeviceId);

  // ── Main panel ───────────────────────────────────────────────────────────
  const main = body
    .append("div")
    .style("display", "grid")
    .style("grid-template-columns", "260px 1fr")
    .style("gap", "14px");

  // Left — reference + predicted (context only, same for every instrument)
  const refCol = main
    .append("div")
    .style("background", "#111")
    .style("padding", "14px")
    .style("border", "1px solid #333")
    .style("border-radius", "4px")
    .style("font-size", "10px");

  if (refVT) {
    refCol
      .append("div")
      .text("REF VT — ANGLE REFERENCE")
      .style("font-size", "9px")
      .style("color", "#888")
      .style("margin-bottom", "8px");
    const vRefKey = _predKey(refVT, _bpTargetPhase, "voltage");
    const aRefKey = _predKey(refVT, _bpTargetPhase, "v-angle");
    const vRef = refVT.summary?.[vRefKey] ?? 0;
    const aRef = refVT.summary?.[aRefKey] ?? 0;
    refCol.append("div").text(refVT.id).style("color", "#3af").style("font-weight", "bold").style("font-size", "11px");
    refCol.append("div").text(`PHASE ${_bpTargetPhase}`).style("font-size", "9px").style("color", "#555");
    refCol
      .append("div")
      .style("margin-top", "8px")
      .html(
        `<div style="font-size:20px;color:#3af;">${vRef.toFixed(1)} <span style="font-size:9px;color:#555;">V</span></div>` +
          `<div style="font-size:14px;color:#3af;">∠ ${_fmtAngle(aRef)}</div>`,
      );
  } else {
    refCol.append("div").text("NO REF VT SELECTED").style("color", "#555").style("font-size", "10px");
  }

  const predMagKey = _predKey(node, _bpTargetPhase, expectedType);
  const predAngKey = _predKey(node, _bpTargetPhase, expectedType === "current" ? "i-angle" : "v-angle");
  const predMag = node.summary?.[predMagKey];
  const predAng = node.summary?.[predAngKey];
  refCol.append("div").style("margin-top", "14px").style("padding-top", "10px").style("border-top", "1px solid #222");
  refCol.append("div").text("TARGET DEVICE PREDICTED").style("font-size", "9px").style("color", "#888").style("margin-bottom", "6px");
  refCol.append("div").text(node.id).style("color", "#fa0").style("font-size", "10px").style("font-weight", "bold");
  if (predMag !== undefined && predMag !== null) {
    refCol
      .append("div")
      .style("margin-top", "6px")
      .html(
        `<div style="font-size:18px;color:#fa0;">${predMag.toFixed(2)} <span style="font-size:9px;color:#555;">${expectedType === "current" ? "A" : "V"}</span></div>` +
          `<div style="font-size:13px;color:#fa0;">∠ ${_fmtAngle(predAng ?? 0)}</div>`,
      );
  } else {
    refCol.append("div").text("No prediction available").style("color", "#333").style("font-size", "9px").style("margin-top", "6px");
  }

  // Right — the actual reading interface
  const right = main
    .append("div")
    .style("background", "#000")
    .style("border", "2px solid #111")
    .style("border-radius", "6px")
    .style("padding", "18px");

  const qty = expectedType === "current" ? "Current" : "Voltage";
  const unit = expectedType === "current" ? "A" : "V";
  const storeKey = isNeutralPhase ? "Neutral Current" : `Phase ${_bpTargetPhase} ${qty}`;
  const angKey = isNeutralPhase ? "Neutral I-Angle" : `Phase ${_bpTargetPhase} ${qty === "Voltage" ? "V-Angle" : "I-Angle"}`;
  const phaseLabel = isNeutralPhase ? "NEUTRAL" : `PHASE ${_bpTargetPhase}`;

  right
    .append("div")
    .text(`${node.id} — ${phaseLabel}`)
    .style("font-size", "13px")
    .style("color", isNeutralPhase ? "#aa0" : "#0a0")
    .style("font-weight", "bold")
    .style("margin-bottom", "4px");
  if (isNeutralPhase) {
    right
      .append("div")
      .text("RECONNECT PROBE TO NEUTRAL TERMINAL (N)")
      .style("font-size", "9px")
      .style("color", "#660")
      .style("letter-spacing", "1px")
      .style("margin-bottom", "10px");
  }

  let mag = null,
    ang = null;

  if (live) {
    const effectiveChan2 = isNeutralPhase ? _bpChan2 : _pmmChan2ForPhase(_bpChan2, _bpTargetPhase);
    const reading = _pmmLastReading;
    if (reading && reading.ok) {
      mag = reading.chan2;
      ang = reading.phase;
    }

    right
      .append("div")
      .html(
        `<span style="color:#555;">CHAN 1 REF:</span> <span style="color:#3af;">${PMM_SOURCES[_bpChan1]?.l || _bpChan1}</span>` +
          ` &nbsp;·&nbsp; <span style="color:#555;">CHAN 2:</span> <span style="color:#0f0;">${PMM_SOURCES[effectiveChan2]?.l || effectiveChan2}</span>`,
      )
      .style("font-size", "9px")
      .style("margin-bottom", "12px");

    const queryBtn = right
      .append("button")
      .text("▶ QUERY METER")
      .style("width", "100%")
      .style("padding", "20px")
      .style("background", "#020a02")
      .style("color", "#0f0")
      .style("border", "2px solid #0a0")
      .style("border-radius", "6px")
      .style("cursor", "pointer")
      .style("font-size", "16px")
      .style("font-weight", "bold")
      .style("letter-spacing", "2px")
      .style("margin-bottom", "14px")
      .on("click", () => {
        queryBtn.text("QUERYING…").property("disabled", true);
        Promise.resolve(_pmmConfigure(_bpChan1, effectiveChan2))
          .then(() => _pmmQuery())
          .then((res) => {
            _pmmLastReading = res;
            _bpRenderReadingScreen();
          })
          .catch((e) => {
            _pmmLastReading = { ok: false, error: String(e) };
            _bpRenderReadingScreen();
          });
      });

    if (reading && !reading.ok) {
      right
        .append("div")
        .style("color", "#f44")
        .style("font-size", "10px")
        .style("margin-bottom", "10px")
        .text("⚠ " + (reading.error || "Query failed — check the connection."));
    } else if (reading && reading.ok) {
      right
        .append("div")
        .style("color", "#444")
        .style("font-size", "9px")
        .style("margin-bottom", "10px")
        .text(
          `watts ${reading.watts.toFixed(3)}  ·  vars ${reading.vars.toFixed(3)}  ·  freq ${reading.freq.toFixed(2)} Hz`,
        );
    }
  }

  // MAG / ANG — always the source of truth _bpLogCurrentPoint reads from.
  // Pre-filled by a query when live; blank and keypad-driven when manual.
  const measBox = right
    .append("div")
    .style("border", isNeutralPhase ? "2px solid #660" : "2px solid #1a1a1a")
    .style("border-radius", "6px")
    .style("padding", "16px")
    .style("background", isNeutralPhase ? "#0a0a00" : "#050505");

  const valueRow = (label, id, val, decimals, fontSize, unitLabel) => {
    const row = measBox
      .append("div")
      .attr("id", id + "-wrap")
      .style("display", "flex")
      .style("align-items", "center")
      .style("gap", "18px")
      .style("padding", "10px")
      .style("margin-bottom", "10px")
      .style("border", "2px solid #1a3a1a")
      .style("border-radius", "6px")
      .style("cursor", "text")
      .on("click", () => {
        document.getElementById(id).focus();
      });
    row.append("span").text(label).style("font-size", "13px").style("color", "#0a0").style("font-weight", "bold").style("width", "44px").style("flex-shrink", "0");
    row
      .append("input")
      .attr("type", "text")
      .attr("inputmode", "decimal")
      .attr("id", id)
      .property("value", val !== null ? val.toFixed(decimals) : "")
      .style("background", "transparent")
      .style("border", "none")
      .style("outline", "none")
      .style("color", "#0f0")
      .style("font-size", fontSize)
      .style("width", "100%")
      .style("text-align", "center")
      .style("font-family", "'Courier New',monospace")
      .on("focus", () => _bpFocusKeypad(id));
    row.append("span").text(unitLabel).style("color", "#0a0").style("font-size", "16px").style("flex-shrink", "0");
    return row;
  };

  valueRow("MAG", "bp-mag-in", mag, 4, "34px", unit);
  valueRow("ANG", "bp-ang-in", ang !== null ? _lagAngle(ang) : null, 2, "26px", "°");

  const keypadWrap = measBox.append("div").style("margin-top", "6px");
  _bpRenderKeypad(keypadWrap);
  _bpFocusKeypad("bp-mag-in");

  right
    .append("div")
    .attr("id", "bp-save-err")
    .style("color", "#f44")
    .style("font-size", "10px")
    .style("margin-top", "10px")
    .style("min-height", "14px");

  right
    .append("button")
    .text("✓ ACCEPT & LOG POINT  (ENTER)")
    .style("width", "100%")
    .style("margin-top", "10px")
    .style("padding", "18px")
    .style("background", "#060")
    .style("color", "#0f0")
    .style("border", "2px solid #0a0")
    .style("border-radius", "6px")
    .style("cursor", "pointer")
    .style("font-weight", "bold")
    .style("font-size", "15px")
    .style("text-transform", "uppercase")
    .style("letter-spacing", "2px")
    .on("click", _bpLogCurrentPoint);

  right
    .append("div")
    .style("margin-top", "10px")
    .style("color", "#444")
    .style("font-size", "9px")
    .style("text-align", "center")
    .text("logging auto-advances to the next phase, then the next device");

  // ── Footer ──────────────────────────────────────────────────────────────
  const footer = d3.select("#brain-point-footer").html("");
  footer.append("button").attr("class", "wiz-secondary").text("BACK TO SELECTION").on("click", _bpRenderStep4);
  footer.append("div").style("flex", 1);
  footer
    .append("button")
    .attr("class", "wiz-secondary")
    .style("border-color", _use360Lag ? "#3af" : "#444")
    .style("color", _use360Lag ? "#3af" : "#555")
    .style("font-size", "9px")
    .text(_use360Lag ? "360° LAG ✓" : "±180°")
    .on("click", () => {
      _use360Lag = !_use360Lag;
      _bpRenderReadingScreen();
    });
  if (!_bpInSIMode) {
    footer
      .append("button")
      .attr("class", "wiz-secondary")
      .style("border-color", "#f00")
      .style("color", "#f00")
      .text("SHORT & ISOLATE (S&I)")
      .on("click", _bpStartSIWorkflow);
  }
  footer
    .append("button")
    .attr("class", "wiz-save")
    .text("EXIT MEASUREMENT")
    .on("click", () => {
      _bpInSIMode = false;
      d3.select("#brain-point-module").style("display", "none");
      d3.select("body").on("keydown.bp", null);
      d3.select("#status-bar").style("background", "#111").style("color", "#0f0").text("Navigation System Standby.");
      refreshData();
    });

  setTimeout(() => {
    const el = document.getElementById(live && mag !== null ? "bp-ang-in" : "bp-mag-in");
    if (el) el.focus();
  }, 100);
}
function _bpLogCurrentPoint() {
  const node = (currentData && currentData.nodes) && currentData.nodes.find((n) => n.id === _bpTargetDeviceId);
  if (!node) return;
  const errEl = document.getElementById("bp-save-err");
  const showErr = (msg) => { if (errEl) errEl.textContent = "⚠ " + msg; };
  if (errEl) errEl.textContent = "";

  const expectedType = _bpDeviceExpectedType(node.type);
  const qty = expectedType === "current" ? "Current" : "Voltage";
  const isNeutralPhase = _bpTargetPhase === "N";
  const storeKey = isNeutralPhase
    ? "Neutral Current"
    : `Phase ${_bpTargetPhase} ${qty}`;
  const angKey = isNeutralPhase
    ? "Neutral I-Angle"
    : `Phase ${_bpTargetPhase} ${qty === "Voltage" ? "V-Angle" : "I-Angle"}`;

  const magInput = document.getElementById("bp-mag-in");
  const angInput = document.getElementById("bp-ang-in");
  const mag = parseFloat(magInput ? magInput.value : "");
  const ang = parseFloat(angInput ? angInput.value : "");
  if (isNaN(mag) && isNaN(ang)) {
    showErr("Nothing to log — query the meter or enter a value first.");
    return;
  }
  const measurements = {};
  if (!isNaN(mag)) measurements[storeKey] = mag;
  if (!isNaN(ang)) measurements[angKey] = ang;

  // Track locally for balance check
  if (!_bpSessionMeasurements[node.id])
    _bpSessionMeasurements[node.id] = {};
  Object.assign(_bpSessionMeasurements[node.id], measurements);

  reconfigureAPI(node.id, "record_measurement", { measurements })
    .then((resp) => {
      if (resp && resp.error) {
        showErr(resp.error + " — try again before moving on.");
        return;
      }
      _bpLastMeasType = expectedType;

      // Success feedback (BIG FLASH)
      d3.select("#brain-point-module")
        .transition()
        .duration(100)
        .style("background", isNeutralPhase ? "#0a0a00" : "#040")
        .transition()
        .duration(300)
        .style("background", "#0a0a0a");

      if (isNeutralPhase) {
        _bpCheckNeutralBalance(node);
      } else {
        _bpMoveToNextPhase();
      }
    })
    .catch(() => {
      showErr("Network error — reading was NOT saved. Try again.");
    });
}

function _bpMoveToNextPhase() {
  _pmmLastReading = null;
  if (_bpTargetPhase === "N") {
    _bpTargetPhase = "A";
    _bpDeviceMeasStep = null;
    _bpMoveToNextDevice();
    return;
  }

  const phases = ["A", "B", "C"];
  const idx = phases.indexOf(_bpTargetPhase);
  const node = (currentData && currentData.nodes) && currentData.nodes.find((n) => n.id === _bpTargetDeviceId);
  const showsI = node && _deviceShowsCurrent(node.type);
  const showsV = node && _deviceShowsVoltage(node.type);
  const isMultiAnalog = showsV && showsI;
  const wantsNeutral = showsI && (_bpSelectedMode === "m3y" || _bpSelectedMode === "m1");

  if (idx < 2) {
    _bpTargetPhase = phases[idx + 1];
    _bpRenderReadingScreen();
  } else if (isMultiAnalog && _bpDeviceMeasStep === "voltage") {
    // Done with voltage pass of multi-analog — switch to current
    _bpDeviceMeasStep = "current";
    _bpTargetPhase = "A";
    _bpShowChannelConfig("current", "voltage", () => {
      _bpRenderReadingScreen();
    });
  } else {
    // At phase C — go to N for wye current devices, otherwise next device
    const inCurrentPass = _bpDeviceMeasStep === "current" || (!isMultiAnalog && showsI);
    if (wantsNeutral && inCurrentPass) {
      _bpTargetPhase = "N";
      _bpRenderReadingScreen();
    } else {
      _bpTargetPhase = "A";
      _bpDeviceMeasStep = null;
      _bpMoveToNextDevice();
    }
  }
}

function _bpMoveToPrevPhase() {
  _pmmLastReading = null;
  const phases =
    _bpTargetPhase === "N" ? ["A", "B", "C", "N"] : ["A", "B", "C"];
  const idx = phases.indexOf(_bpTargetPhase);
  if (idx > 0) {
    _bpTargetPhase = phases[idx - 1];
    _bpRenderReadingScreen();
  }
}

function _bpMoveToNextDevice() {
  const idx = _bpSelectedDevices.indexOf(_bpTargetDeviceId);
  _pmmLastReading = null;
  _bpDeviceMeasStep = null;
  _bpManualOverride = false; // a fresh device may not be a digital-display case

  if (idx < _bpSelectedDevices.length - 1) {
    const nextId = _bpSelectedDevices[idx + 1];
    _bpTargetDeviceId = nextId;
    _bpTargetPhase = "A";

    const nextNode = (currentData?.nodes || []).find((n) => n.id === nextId);
    const nextGroup = nextNode ? _bpDeviceGroup(nextNode.type) : "voltage";
    const nextMeasType = nextGroup === "current" ? "current" : "voltage";
    const prevMeasType = _bpLastMeasType;

    if (nextGroup === "multi") _bpDeviceMeasStep = "voltage";

    if (prevMeasType !== null && prevMeasType !== nextMeasType) {
      _bpShowChannelConfig(nextMeasType, prevMeasType, () => {
        _bpRenderReadingScreen();
      });
    } else {
      _bpApplyChanConfig(nextMeasType);
      _bpRenderReadingScreen();
    }
  } else {
    _bpRenderReadingScreen();
  }
}

function _bpMoveToPrevDevice() {
  const idx = _bpSelectedDevices.indexOf(_bpTargetDeviceId);
  _pmmLastReading = null;
  _bpManualOverride = false;
  if (idx > 0) {
    _bpTargetDeviceId = _bpSelectedDevices[idx - 1];
    _bpTargetPhase = "A";
  }
  _bpRenderReadingScreen();
}

// ── Neutral Balance Check & S&I Auto-Suggestion ───────────────────────────────

function _bpCheckNeutralBalance(node) {
  const m = _bpSessionMeasurements[node.id] || {};
  const ia = m["Phase A Current"];
  const ib = m["Phase B Current"];
  const ic = m["Phase C Current"];
  const ineutral = m["Neutral Current"];
  const angA = m["Phase A I-Angle"];
  const angB = m["Phase B I-Angle"];
  const angC = m["Phase C I-Angle"];

  if ([ia, ib, ic, ineutral, angA, angB, angC].some((v) => v === undefined)) {
    _bpTargetPhase = "A";
    _bpMoveToNextDevice();
    return;
  }

  const avg = (ia + ib + ic) / 3;
  if (avg < 0.001) {
    _bpTargetPhase = "A";
    _bpMoveToNextDevice();
    return;
  }

  // Phasor sum of the three phase currents — if vectors cancel, neutral is near zero
  const toRad = (d) => (d * Math.PI) / 180;
  const re = ia * Math.cos(toRad(angA)) + ib * Math.cos(toRad(angB)) + ic * Math.cos(toRad(angC));
  const im = ia * Math.sin(toRad(angA)) + ib * Math.sin(toRad(angB)) + ic * Math.sin(toRad(angC));
  const computedNeutral = Math.sqrt(re * re + im * im);

  // Trigger S&I when the phasor sum is small relative to average phase —
  // the neutral measurement will have high relative error and needs validation
  if (computedNeutral / avg < 0.05) {
    _bpShowSISuggestion(node, ia, ib, ic, ineutral, computedNeutral, avg);
  } else {
    _bpTargetPhase = "A";
    _bpMoveToNextDevice();
  }
}

function _bpShowSISuggestion(node, ia, ib, ic, ineutral, computedNeutral, avg) {
  const computedPct = ((computedNeutral / avg) * 100).toFixed(1);
  const measuredPct = ((ineutral / avg) * 100).toFixed(1);

  const body = d3.select("#brain-point-body");
  const overlay = body
    .append("div")
    .style("position", "absolute")
    .style("top", "50%")
    .style("left", "50%")
    .style("transform", "translate(-50%, -50%)")
    .style("background", "#030d03")
    .style("border", "2px solid #0f0")
    .style("padding", "28px 36px")
    .style("text-align", "center")
    .style("z-index", 9999)
    .style("border-radius", "4px")
    .style("min-width", "340px");

  overlay
    .append("div")
    .text("PHASOR SUM NEAR ZERO — S&I RECOMMENDED")
    .style("color", "#0f0")
    .style("font-size", "13px")
    .style("font-weight", "bold")
    .style("letter-spacing", "1px")
    .style("margin-bottom", "14px");

  overlay
    .append("div")
    .html(
      `Computed neutral (Ia+Ib+Ic): <span style="color:#0f0;">${computedPct}% of avg phase</span>` +
      ` &nbsp;·&nbsp; Measured neutral: <span style="color:#0f0;">${measuredPct}% of avg phase</span>`,
    )
    .style("font-size", "10px")
    .style("color", "#666")
    .style("margin-bottom", "14px");

  overlay
    .append("div")
    .text(
      "Phasor sum of A+B+C is near zero — the neutral measurement has high relative uncertainty. S&I will force current through the neutral for a reliable reading.",
    )
    .style("font-size", "10px")
    .style("color", "#888")
    .style("line-height", "1.5")
    .style("margin-bottom", "20px");

  const btns = overlay
    .append("div")
    .style("display", "flex")
    .style("gap", "10px")
    .style("justify-content", "center");

  btns
    .append("button")
    .attr("class", "wiz-secondary")
    .style("border-color", "#f00")
    .style("color", "#f00")
    .style("padding", "8px 16px")
    .text("INITIATE S&I SEQUENCE →")
    .on("click", () => {
      overlay.remove();
      _bpStartSIWorkflow();
    });

  btns
    .append("button")
    .attr("class", "wiz-secondary")
    .style("padding", "8px 16px")
    .text("BYPASS S&I")
    .on("click", () => {
      overlay.html("");

      overlay
        .append("div")
        .text("S&I BYPASS — LEAVE A NOTE")
        .style("color", "#ff0")
        .style("font-size", "13px")
        .style("font-weight", "bold")
        .style("letter-spacing", "1px")
        .style("margin-bottom", "10px");

      overlay
        .append("div")
        .text(
          "Let the next tech know why S&I was skipped. Not required, but strongly recommended.",
        )
        .style("color", "#888")
        .style("font-size", "10px")
        .style("line-height", "1.5")
        .style("margin-bottom", "12px");

      const chips = overlay
        .append("div")
        .style("display", "flex")
        .style("gap", "6px")
        .style("flex-wrap", "wrap")
        .style("margin-bottom", "10px");

      [
        "Can't block all protection",
        "87 relay active",
        "Time constraint",
        "S&I not safe in current config",
      ].forEach((s) => {
        chips
          .append("span")
          .text(s)
          .style("background", "#111")
          .style("border", "1px solid #333")
          .style("color", "#888")
          .style("font-size", "9px")
          .style("padding", "3px 8px")
          .style("border-radius", "3px")
          .style("cursor", "pointer")
          .on("click", function () {
            document.getElementById("bp-si-bypass-note").value = s;
          });
      });

      overlay
        .append("textarea")
        .attr("id", "bp-si-bypass-note")
        .attr(
          "placeholder",
          'e.g. "Can\'t block all protection — relay 87 active"',
        )
        .style("width", "100%")
        .style("background", "#0a0a0a")
        .style("color", "#0f0")
        .style("border", "1px solid #333")
        .style("font-family", "Courier, monospace")
        .style("font-size", "11px")
        .style("padding", "8px")
        .style("resize", "vertical")
        .style("min-height", "60px")
        .style("box-sizing", "border-box")
        .style("margin-bottom", "14px");

      const btns2 = overlay
        .append("div")
        .style("display", "flex")
        .style("gap", "10px")
        .style("justify-content", "center");

      const proceed = () => {
        overlay.remove();
        _bpTargetPhase = "A";
        _bpMoveToNextDevice();
      };

      btns2
        .append("button")
        .attr("class", "wiz-save")
        .style("padding", "8px 16px")
        .text("SAVE NOTE & CONTINUE →")
        .on("click", () => {
          const note = document
            .getElementById("bp-si-bypass-note")
            .value.trim();
          if (note) {
            reconfigureAPI(node.id, "record_measurement", {
              measurements: { "S&I Bypass Note": note },
            }).then(proceed);
          } else {
            proceed();
          }
        });

      btns2
        .append("button")
        .attr("class", "wiz-secondary")
        .style("padding", "8px 16px")
        .text("SKIP NOTE")
        .on("click", proceed);
    });
}

function _bpStartSIWorkflow() {
  d3.select("#brain-point-body").html("");
  const body = d3.select("#brain-point-body");

  const warnBox = body
    .append("div")
    .style("background", "#300")
    .style("border", "4px solid #f00")
    .style("padding", "20px")
    .style("margin", "20px")
    .style("text-align", "center");

  warnBox
    .append("h1")
    .style("color", "#f00")
    .style("font-size", "36px")
    .style("margin", "0 0 15px 0")
    .text("!!! CRITICAL WARNING !!!");

  warnBox
    .append("div")
    .style("color", "#fff")
    .style("font-size", "18px")
    .style("font-weight", "bold")
    .style("line-height", "1.5")
    .html(
      "S&I BLOCK PROTECTION DETECTED.<br><br>PROCEEDING WILL LIKELY CAUSE PROTECTION TO OPERATE (87, 50/51, etc).<br><br>ENSURE ALL TRIPPING CONTACTS ARE ISOLATED BEFORE CONTINUING.",
    );

  const footer = d3.select("#brain-point-footer").html("");
  footer
    .append("button")
    .attr("class", "wiz-secondary")
    .text("CANCEL / ABORT")
    .on("click", _bpRenderReadingScreen);

  footer.append("div").style("flex", "1");

  footer
    .append("button")
    .attr("class", "wiz-save")
    .style("background", "#f00")
    .style("color", "#fff")
    .text("I UNDERSTAND - PROCEED →")
    .on("click", _bpSIModeStep2);
}

function _bpSIModeStep2() {
  d3.select("#brain-point-body").html("");
  const body = d3.select("#brain-point-body");

  body.append("h3").text("STEP 2: DEFINE PHASE ROLES").style("color", "#ff0");
  body
    .append("p")
    .text(
      "Select the phase you will use for measurement. The other two must be isolated and shorted to neutral at the block.",
    )
    .style("color", "#888");

  const container = body
    .append("div")
    .style("display", "flex")
    .style("gap", "20px")
    .style("margin-top", "30px")
    .style("justify-content", "center");

  ["A", "B", "C"].forEach((ph) => {
    const isActive = _bpSISelectedPhase === ph;
    const card = container
      .append("div")
      .style("flex", "1")
      .style("max-width", "180px")
      .style("background", isActive ? "#121" : "#111")
      .style("border", "2px solid " + (isActive ? "#0f0" : "#333"))
      .style("border-radius", "8px")
      .style("padding", "25px 15px")
      .style("cursor", "pointer")
      .style("text-align", "center")
      .style("transition", "all 0.2s")
      .on("click", () => {
        _bpSISelectedPhase = ph;
        _bpSIModeStep2();
      });

    card
      .append("div")
      .text("PHASE")
      .style("font-size", "11px")
      .style("color", "#666")
      .style("letter-spacing", "1px");
    card
      .append("div")
      .text(ph)
      .style("font-size", "56px")
      .style("font-weight", "bold")
      .style("color", isActive ? "#0f0" : "#444")
      .style("margin", "5px 0");

    card
      .append("div")
      .style("margin-top", "15px")
      .style("padding", "6px")
      .style("border-radius", "4px")
      .style("background", isActive ? "#040" : "#211")
      .style("color", isActive ? "#0f0" : "#f44")
      .style("font-size", "11px")
      .style("font-weight", "bold")
      .text(isActive ? "● IN USE" : "○ ISOLATED");
  });

  const footer = d3.select("#brain-point-footer").html("");
  footer
    .append("button")
    .attr("class", "wiz-secondary")
    .text("BACK")
    .on("click", _bpStartSIWorkflow);
  footer.append("div").style("flex", "1");
  footer
    .append("button")
    .attr("class", "wiz-save")
    .text("CONFIRM CONFIGURATION →")
    .on("click", _bpSIModeStep3);
}

function _bpSIModeStep3() {
  const node = (currentData && currentData.nodes) && currentData.nodes.find((n) => n.id === _bpTargetDeviceId);
  const hasVoltage = !["CurrentTransformer", "CTTB"].includes(node.type);

  const others = ["A", "B", "C"].filter((p) => p !== _bpSISelectedPhase);

  d3.select("#brain-point-body").html("");
  const body = d3.select("#brain-point-body");

  body
    .append("h3")
    .text("STEP 3: PHYSICAL RECONFIGURATION")
    .style("color", "#ff0");

  const list = body
    .append("ul")
    .style("color", "#0f0")
    .style("font-size", "14px")
    .style("line-height", "2");
  list
    .append("li")
    .text(
      `Short and isolate Phase ${others[0]} and Phase ${others[1]} at the CTTB.`,
    );
  list
    .append("li")
    .text(
      `Set measurement probe to Neutral and Phase ${_bpSISelectedPhase}.`,
    );

  if (hasVoltage) {
    const vWarn = body
      .append("div")
      .style("background", "#440")
      .style("border", "1px solid #ff0")
      .style("padding", "15px")
      .style("margin-top", "20px");
    vWarn
      .append("div")
      .style("color", "#ff0")
      .style("font-weight", "bold")
      .text("VOLTAGE DETECTED:");
    vWarn
      .append("div")
      .style("color", "#fff")
      .style("margin-top", "5px")
      .text(
        "This device ingests voltage. DISCONNECT ALL VOLTAGE LEADS NOW. The meter will reconfigure Channel 2 to ensure safety.",
      );
  }

  const footer = d3.select("#brain-point-footer").html("");
  footer
    .append("button")
    .attr("class", "wiz-secondary")
    .text("BACK")
    .on("click", _bpSIModeStep2);
  footer.append("div").style("flex", "1");
  footer
    .append("button")
    .attr("class", "wiz-save")
    .text("RECONFIGURE METER & START →")
    .on("click", () => {
      _bpInSIMode = true;
      // Reconfigure meter physical input for Channel 2
      // Ia=6, Ib=7, Ic=8
      const chanMap = { A: 6, B: 7, C: 8 };
      _bpChan2 = chanMap[_bpSISelectedPhase];

      // Also update the target phase in the BRAIN POINT logger
      _bpTargetPhase = _bpSISelectedPhase;

      _bpRenderReadingScreen();
    });
}

