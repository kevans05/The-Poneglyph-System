let _bpSISelectedPhase = "A";
let _bpInSIMode = false;
let compareData = null;

// ── Protection View Filter ─────────────────────────────────────────────────────
// When active, hides "infrastructure" node types (wires, raw CT/VT sensors) so
// only the protection chain and primary switching equipment remains visible.
// This makes it easier to trace CTTB → Relay → Breaker paths without clutter.

let _protViewActive = false;

// Types that are HIDDEN in protection view — physical wiring / low-level sensors
const PROT_VIEW_HIDDEN_TYPES = new Set([
  "Wire",
  "CurrentTransformer",
  "VoltageTransformer",
  "DualWindingVT",
  "PowerLine",
  "Line",
]);

function toggleProtectionView() {
  _protViewActive = !_protViewActive;
  const btn = document.getElementById("prot-view-btn");
  if (btn) {
    btn.style.color       = _protViewActive ? "#0f0" : "";
    btn.style.borderColor = _protViewActive ? "#0f0" : "";
    btn.style.background  = _protViewActive ? "#001a00" : "";
  }
  applyProtectionViewFilter();
}

/**
 * Show/hide SVG node groups and wire paths based on the protection view filter.
 * Edges are individual <path> elements with data-src / data-tgt attributes so
 * we select by attribute rather than by bound datum.
 */
function applyProtectionViewFilter() {
  if (!_protViewActive) {
    d3.select("#zoom-group").selectAll(".node").style("display", null);
    d3.select("#zoom-group").selectAll("[data-src]").style("display", null);
    return;
  }

  // Hide nodes whose type is in the hidden set
  d3.select("#zoom-group").selectAll(".node").each(function(d) {
    d3.select(this).style("display", (d && PROT_VIEW_HIDDEN_TYPES.has(d.type)) ? "none" : null);
  });

  // Build set of hidden IDs for edge path filtering
  const hiddenIds = new Set();
  if (currentData && currentData.nodes) {
    currentData.nodes.forEach(n => { if (PROT_VIEW_HIDDEN_TYPES.has(n.type)) hiddenIds.add(n.id); });
  }

  // Hide wire paths that connect to or from a hidden device
  d3.select("#zoom-group").selectAll("[data-src]").each(function() {
    const el = d3.select(this);
    const hidden = hiddenIds.has(el.attr("data-src")) || hiddenIds.has(el.attr("data-tgt"));
    el.style("display", hidden ? "none" : null);
  });
}
/**
 * SCADA Pro Console - UI & Window Management
 * Handles draggable windows, context menus, and modals.
 */

let zIndexCounter = 5000;
let connectionSource = null;
let _winCascade = 0;
let _configModalDragged = false;

/**
 * Handles a click on a node. If multiple nodes overlap, shows a selection menu.
 */
function handleNodeInteraction(event, d) {
  if (connectionSource) {
    completeConnection(d.id);
    return;
  }

  const elements = document.elementsFromPoint(event.clientX, event.clientY);
  const nodesAtPoint = [];
  const seenIds = new Set();

  elements.forEach((el) => {
    const nodeEl = el.closest(".node");
    if (nodeEl) {
      const data = d3.select(nodeEl).datum();
      if (data && !seenIds.has(data.id)) {
        nodesAtPoint.push(data);
        seenIds.add(data.id);
      }
    }
  });

  if (nodesAtPoint.length > 1) {
    showSelectionDialog(event, nodesAtPoint);
  } else if (d) {
    openWindow(d);
  }
}

/**
 * Displays a list of overlapping devices for the user to choose from.
 */
function showSelectionDialog(event, nodes) {
  const menu = d3
    .select("#context-menu")
    .style("display", "block")
    .style("left", event.pageX + "px")
    .style("top", event.pageY + "px");
  let html =
    '<div style="padding: 8px; font-size: 10px; color: #ffff00; border-bottom: 1px solid #444; background: #111;">MULTIPLE DEVICES DETECTED</div>';
  nodes.forEach((n) => {
    html +=
      '<div class="menu-item" onclick="openWindowById(\'' +
      n.id +
      "')\">" +
      n.id +
      ' <span style="color:#666; font-size:9px;">[' +
      n.type +
      "]</span></div>";
  });
  html +=
    "<div class=\"menu-item\" onclick=\"d3.select('#context-menu').style('display','none')\" style=\"color:#888; border-top: 1px solid #333;\">CANCEL</div>";
  menu.html(html);
  setTimeout(() => {
    d3.select("body").on("click.selection", () => {
      d3.select("#context-menu").style("display", "none");
      d3.select("body").on("click.selection", null);
    });
  }, 10);
}

function openWindowById(id) {
  const node = (currentData && currentData.nodes) && currentData.nodes.find((n) => n.id === id);
  if (node) openWindow(node);
  d3.select("#context-menu").style("display", "none");
}

/**
 * Engineering Actions
 */

// Entry point for the framework
function mountAnalFramework() {
  console.log("The Poneglyph System Online.");
  d3.select("#status-bar")
    .style("display", "block")
    .style("background", "#111")
    .style("color", "#0f0")
    .style("border-top", "1px solid #333")
    .text("Navigation System Standby.");
  refreshData();
}

function updateStatusBar(reference, syncErrors) {
  const bar = d3.select("#status-bar");
  let html = "";

  if (syncErrors && syncErrors.length > 0) {
    syncErrors.forEach(err => {
      const issues = err.issues.join(" · ");
      html += "<span style=\"background:#1a0000; color:#f44; padding:2px 10px; margin-right:8px; border:1px solid #f44; font-size:10px; letter-spacing:1px;\">";
      html += `⚠ SYNC FAULT: ${err.sources.join(" ↔ ")} — ${issues}</span>`;
    });
    bar.style("background", "#0d0000").style("color", "#f44");
  } else if (compareData) {
    html += `<span style="background:#420; color:#fa0; padding:2px 8px; margin-right:15px; border:1px solid #fa0;">COMPARISON MODE ACTIVE: ${compareData.filename}</span>`;
    html += `<span onclick="exitCompareMode()" style=\"text-decoration:underline; cursor:pointer; margin-right:20px; color:#f88;">[ EXIT COMPARE ]</span>`;
    bar.style("background", "#111").style("color", "#0f0");
  } else if (reference && reference.device_id) {
    html += `PHASE REFERENCE ACTIVE: <span style="color:#fff; font-weight:bold;">${reference.device_id} (Phase ${reference.phase})</span>`;
    html += ' <span onclick="setAsReference(null, null)" style=\"text-decoration:underline; cursor:pointer; margin-left:20px; color:#f88;">[ CLEAR REFERENCE ]</span>';
    bar.style("background", "#002200").style("color", "#0f0");
  } else {
    html += "Navigation System Standby (Internal 0° Reference).";
    bar.style("background", "#111").style("color", "#0f0");
  }

  bar.html(html).style("display", "block");
}

function setAsReference(deviceId, phase) {
  reconfigureAPI(null, "set_reference", {
    device_id: deviceId,
    phase: phase,
  }).then(() => refreshData());
}

function startConnectionMode(sourceId, bushing) {
  connectionSource = { id: sourceId, bushing: bushing };
  const bText = bushing ? " (Bushing " + bushing + ")" : "";
  d3.select("#status-bar")
    .style("display", "block")
    .style("background", "#ffff00")
    .style("color", "#000")
    .html(
      "CONNECTION MODE: Select target device to connect " +
        sourceId +
        bText +
        ' ... <span onclick=\"cancelConnectionMode()\" style=\"text-decoration:underline; cursor:pointer; margin-left:20px;\">CANCEL</span>',
    );
}

function startTripConnectionMode(sourceId) {
  connectionSource = { id: sourceId, isTrip: true };
  d3.select("#status-bar")
    .style("display", "block")
    .style("background", "#f44")
    .style("color", "#fff")
    .html(
      "TRIP CIRCUIT MODE: Select target Breaker/Switch to connect " +
        sourceId +
        " ... <span onclick=\"cancelConnectionMode()\" style=\"text-decoration:underline; cursor:pointer; margin-left:20px;\">CANCEL</span>",
    );
}

function startCloseConnectionMode(sourceId) {
  connectionSource = { id: sourceId, isClose: true };
  d3.select("#status-bar")
    .style("display", "block")
    .style("background", "#0a0")
    .style("color", "#fff")
    .html(
      "CLOSE CIRCUIT MODE: Select target Breaker/Switch to connect " +
        sourceId +
        " ... <span onclick=\"cancelConnectionMode()\" style=\"text-decoration:underline; cursor:pointer; margin-left:20px;\">CANCEL</span>",
    );
}

function startDCConnectionMode(sourceId, fromLabel, isReverse) {
  if (fromLabel === undefined) fromLabel = null;
  if (isReverse === undefined) isReverse = false;
  const node = (currentData && currentData.nodes) && currentData.nodes.find(n => n.id === sourceId);
  if (!fromLabel && node) {
    let outputs;
    if (isReverse) {
        outputs = (node.params && node.params.digital_inputs) || (node.type === 'Relay' ? ["IN101", "IN102"] : ["TRIP_COIL", "CLOSE_COIL", "TRIP_A", "TRIP_B", "TRIP_C", "CLOSE_A", "CLOSE_B", "CLOSE_C"]);
    } else {
        outputs = (node.params && node.params.digital_outputs);
        if (!outputs) {
            if (node.type === 'Relay') {
                outputs = ["TRIP", "OUT101", "OUT102"];
            } else if (node.type === 'CircuitBreaker') {
                outputs = ["52A", "52B", "52A_A", "52B_A", "52A_B", "52B_B", "52A_C", "52B_C"];
            } else if (node.type === 'Disconnect') {
                outputs = ["89A", "89B", "89A_A", "89B_A", "89A_B", "89B_B", "89A_C", "89B_C"];
            } else {
                outputs = ["DC_OUT"];
            }
        }
    }
    if (outputs.length > 1) {
        showTerminalPicker(isReverse ? "SELECT TARGET TERMINAL" : "SELECT SOURCE TERMINAL", outputs, (label) => startDCConnectionMode(sourceId, label, isReverse));
        return;
    }
    fromLabel = outputs[0];
  }

  connectionSource = { id: sourceId, isDC: true, from: fromLabel, isReverse: isReverse };
  const prompt = isReverse ? "WIRE FROM INPUT: Select source device to drive " : "DC CONNECTION: Select target device to connect ";
  d3.select("#status-bar")
    .style("display", "block")
    .style("background", "#ff8800")
    .style("color", "#000")
    .html(
      prompt +
        sourceId + " (" + fromLabel + ")" +
        " ... <span onclick=\"cancelConnectionMode()\" style=\"text-decoration:underline; cursor:pointer; margin-left:20px;\">CANCEL</span>",
    );
}

function startSecondaryConnectionMode(sourceId) {
  connectionSource = { id: sourceId, isSecondary: true };
  d3.select("#status-bar")
    .style("display", "block")
    .style("background", "#ffff00")
    .style("color", "#000")
    .html(
      "SECONDARY CONNECTION MODE: Select target CTTB/FT/Relay to connect " +
        sourceId +
        ' ... <span onclick=\"cancelConnectionMode()\" style=\"text-decoration:underline; cursor:pointer; margin-left:20px;\">CANCEL</span>',
    );
}

function cancelConnectionMode() {
  connectionSource = null;
  d3.select("#status-bar")
    .style("background", "#111")
    .style("color", "#0f0")
    .text("Navigation System Standby.");
}

function completeConnection(targetId, toLabel = null) {
  if (!connectionSource) return;
  const { id, bushing, isSecondary, isDC, isTrip, isClose, from } = connectionSource;
  
  if (isDC && !toLabel) {
    const targetNode = (currentData && currentData.nodes) ? (currentData && currentData.nodes) && currentData.nodes.find(n => n.id === targetId) : null;
    if (targetNode) {
        let inputs = (targetNode.params && targetNode.params.digital_inputs);
        if (!inputs) {
            if (targetNode.type === 'Relay') inputs = ["IN101", "IN102"];
            else if (['CircuitBreaker', 'Disconnect'].includes(targetNode.type)) inputs = ["TRIP_COIL", "CLOSE_COIL", "TRIP_A", "TRIP_B", "TRIP_C", "CLOSE_A", "CLOSE_B", "CLOSE_C"];
            else inputs = ["DC_IN"];
        }
        if (inputs.length > 1) {
            showTerminalPicker("SELECT TARGET TERMINAL", inputs, (label) => completeConnection(targetId, label));
            return;
        }
        toLabel = inputs[0];
    }
  }

  if (id === targetId) {
    alert("Cannot connect a device to itself.");
    return;
  }
  const action = isTrip ? "add_trip_connection" : isClose ? "add_close_connection" : isDC ? "add_dc_connection" : isSecondary ? "add_secondary_connection" : "add_connection";
  reconfigureAPI(id, action, { target_id: targetId, bushing: bushing, from: from, to: toLabel }).then(
    () => {
      cancelConnectionMode();
      refreshData();
    },
  );
}

function addCTTB(sensorId) {
  const newCTTB = {
    id: "CTTB-" + sensorId + "-" + Math.floor(Math.random() * 100),
    type: "CTTB",
  };
  reconfigureAPI(null, "add_device", { device: newCTTB }).then(() => {
    reconfigureAPI(sensorId, "add_secondary_connection", {
      target_id: newCTTB.id,
    }).then(() => refreshData());
  });
}

function addFTBlock(sensorId) {
  const newFT = {
    id: "FT-" + sensorId + "-" + Math.floor(Math.random() * 100),
    type: "FTBlock",
  };
  reconfigureAPI(null, "add_device", { device: newFT }).then(() => {
    reconfigureAPI(sensorId, "add_secondary_connection", {
      target_id: newFT.id,
    }).then(() => refreshData());
  });
}

function addRelay(sensorId) {
  const newRelay = {
    id: "RLY-" + sensorId + "-" + Math.floor(Math.random() * 100),
    type: "Relay",
    function: "Differential",
  };
  reconfigureAPI(null, "add_device", { device: newRelay }).then(() => {
    reconfigureAPI(sensorId, "add_secondary_connection", {
      target_id: newRelay.id,
    }).then(() => refreshData());
  });
}

const _DEVICE_DEFAULTS = {
  VoltageSource:       { nominal_voltage_kv: 230, nominal_power_mva: 100, pf: 0.85, winding_type: "Y", phase_shift_deg: 0 },
  CircuitBreaker:      { continuous_amps: 2000, interrupt_ka: 40, status: "OPEN" },
  Disconnect:          { status: "OPEN" },
  PowerTransformer:    { pri_kv: 230, sec_kv: 115, h_winding: "Y", x_winding: "D", polarity_reversed: false },
  VoltageRegulator:    { nominal_kv: 13.8, tap_pos: 0, step_percent: 0.625, max_steps: 16 },
  Load:                { load_mva: 50, pf: 0.85, is_balanced: true },
  VoltageTransformer:  { ratio: "2000:1", bushing: "X", polarity_normal: true, secondary_wiring: "Y" },
  DualWindingVT:       { ratio: "2000:1", sec2_ratio: "2000:1", bushing: "X", polarity_normal: true, secondary_wiring: "Y", secondary2_wiring: "Y" },
  CurrentTransformer:  { ratio: "2000:5", bushing: "X", position: "inner", polarity_facing: "AWAY", secondary_wiring: "Y" },
  FTBlock:             {},
  IsoBlock:            {},
  CTTB:                { mode: "SUM" },
  Relay:               { function: "Differential", category: "Numerical" },
  AuxiliaryTransformer: { phase_shift_deg: 0, ratio: 1.0 },
  Meter:                {},
  Indicator:            {},
  Wire:                {},
  Line:                { length_km: 1.0, r_per_km: 0.1, x_per_km: 0.3 },
  PowerLine:           { length_km: 1.0, r_per_km: 0.1, x_per_km: 0.3 },
  ShuntCapacitor:             { mvar_rating: 10, kv_rating: 115 },
  ShuntReactor:               { mvar_rating: 10, kv_rating: 115 },
  SurgeArrester:              { kv_rating: 115, bushing: "H" },
  SeriesCapacitor:            { mvar_rating: 50, impedance_ohm: 10 },
  SeriesReactor:              { mvar_rating: 10, impedance_ohm: 5 },
  NeutralGroundingResistor:   { resistance_ohm: 400, kv_rating: 13.8 },
  SVC:                        { mvar_min: -50, mvar_max: 50, mvar_setting: 0, kv_rating: 115 },
  LineTrap:                   { carrier_frequency_hz: 250 },
};

function _defaultId(type) {
  return (TYPE_ABBREV[type] || type) + "-" + Math.floor(Math.random() * 1000);
}

function plantDevice(type, pageX, pageY, gx, gy, hostId = null, bushing = null) {
  d3.select("#context-menu").style("display", "none");
  const suggestedId = _defaultId(type);
  showInputDialog("DEVICE ID / NAME", suggestedId, (devId) => {
    if (!devId) devId = suggestedId;
    const newDev = { id: devId, type, ...(_DEVICE_DEFAULTS[type] || {}) };
    if (hostId) newDev.location = hostId;
    if (bushing && (type === "CurrentTransformer" || type === "VoltageTransformer" || type === "DualWindingVT")) {
      newDev.bushing = bushing;
    }
    const payload = { device: newDev, gx: snapToGrid(gx), gy: snapToGrid(gy) };
    if (hostId) payload.connect_to = { id: hostId, bushing };
    reconfigureAPI(null, "add_device", payload).then(() => refreshData());
  });
}

function showPlantMenu(pageX, pageY, gx, gy, hostId = null, bushing = null) {
  const menu = d3
    .select("#context-menu")
    .style("display", "block")
    .style("left", pageX + "px")
    .style("top", pageY + "px");

  const title = hostId ? `PLANT AT ${hostId} (${bushing})` : "ADD NEW DEVICE";
  const groups = [
    { label: "SOURCES & LOADS",  types: ["VoltageSource", "Load", "Bus", "Line", "Wire"] },
    { label: "SWITCHING",        types: ["CircuitBreaker", "Disconnect"] },
    { label: "TRANSFORMERS",     types: ["PowerTransformer", "VoltageRegulator", "VoltageTransformer", "DualWindingVT", "CurrentTransformer"] },
    { label: "SHUNT DEVICES",    types: ["ShuntCapacitor", "ShuntReactor", "SurgeArrester", "SVC", "NeutralGroundingResistor"] },
    { label: "SERIES DEVICES",   types: ["SeriesCapacitor", "SeriesReactor", "LineTrap"] },
    { label: "PROTECTION",       types: ["CTTB", "FTBlock", "IsoBlock", "AuxiliaryTransformer", "Relay"] },
    { label: "METERING",         types: ["Meter"] },
    { label: "CONTROL",          types: ["Indicator"] },
  ];

  let html = "<div style=\"padding:6px 10px; font-size:10px; color:#ff0; border-bottom:1px solid #333; background:#111;\">" + title + "</div>";
  const args = `${pageX},${pageY},${gx},${gy},${hostId ? "'" + hostId + "'" : "null"},${bushing ? "'" + bushing + "'" : "null"}`;
  groups.forEach(g => {
    html += `<div style="padding:3px 10px; font-size:9px; color:#555; background:#0a0a0a; border-top:1px solid #1a1a1a;">${g.label}</div>`;
    g.types.forEach(t => {
      html += `<div class="menu-item" onclick="plantDevice('${t}',${args})">${t}</div>`;
    });
  });
  html += `<div class="menu-item" style="color:#555; border-top:1px solid #222;" onclick="d3.select('#context-menu').style('display','none')">CANCEL</div>`;
  menu.html(html);

  // Clamp to viewport so it never bleeds off-screen
  const menuEl = document.getElementById("context-menu");
  const r = menuEl.getBoundingClientRect();
  if (r.right > window.innerWidth - 8)
    menuEl.style.left = Math.max(0, pageX - r.width) + "px";
  if (r.bottom > window.innerHeight - 8)
    menuEl.style.top = Math.max(0, pageY - r.height) + "px";

  d3.select("body").on("click.menu", () => d3.select("#context-menu").style("display", "none"));
}

function rotateDevice(id, currentRotation) {
  const newRotation = (currentRotation + 90) % 360;
  reconfigureAPI(id, "update_rotation", { rotation: newRotation }).then(() =>
    refreshData(),
  );
}

function deleteDevice(id) {
  if (
    confirm(
      "Are you sure you want to PERMANENTLY DELETE device [" +
        id +
        "] and all its connections?",
    )
  ) {
    reconfigureAPI(id, "delete_device", {}).then(() => {
      closeWindow(id);
      refreshData();
    });
  }
}

function openWindow(node) {
  if (openWindows[node.id]) {
    openWindows[node.id].style.zIndex = ++zIndexCounter;
    return;
  }
  const win = document.createElement("div");
  win.className = "window";
  const cascade = (_winCascade++ % 10) * 26;
  win.style.left = (40 + cascade) + "px";
  win.style.top = (60 + cascade) + "px";
  win.style.zIndex = ++zIndexCounter;
  const safeId = node.id.replace(/\s+/g, "-");
  win.innerHTML =
    '<div class="window-header"><span class="window-title">' +
    node.id +
    '</span><span style="display:flex;gap:8px;align-items:center;">' +
    '<button class="ang-conv-btn" onclick="_toggleAngleConv()" title="Toggle angle convention">' +
    (_use360Lag ? "360°" : "±180°") +
    '</button>' +
    '<span style="cursor:pointer" onclick="closeWindow(\'' +
    node.id +
    '\')">[X]</span></span></div><div class="window-content" id="win-' +
    safeId +
    '"></div>';
  document.body.appendChild(win);
  openWindows[node.id] = win;
  makeDraggable(win);
  updateWindow(node.id, node);
}

function closeWindow(id) {
  if (openWindows[id]) {
    openWindows[id].remove();
    delete openWindows[id];
  }
}

// ── Summary row rendering helpers ─────────────────────────────────────────────

function _renderSummaryRows(entries, compNode) {
  let html = "";
  entries.forEach(function(entry) { var key = entry[0], value = entry[1];
    if (value === "HEADER") {
      html += `<div style="background:#1a1a1a; padding:2px 8px; font-size:10px; color:#aaa; margin-top:8px; text-align:center; border:1px solid #333; text-transform:uppercase;">${key.replace(/-/g, "").trim()}</div>`;
    } else {
      let valDisplay = "", compDisplay = "";
      if (typeof value === "number") {
        const isAngle = unitsMap[key] === "deg";
        valDisplay = isAngle ? _fmtAngle(value) : formatSI(value, unitsMap[key] || "");
        if (compNode?.summary?.[key] !== undefined) {
          const histVal = compNode.summary[key];
          const delta = value - histVal;
          const deltaColor = delta > 0 ? "#0f0" : delta < 0 ? "#f00" : "#888";
          const deltaSign = delta > 0 ? "+" : "";
          const hd = isAngle ? _fmtAngle(histVal) : formatSI(histVal, unitsMap[key] || "");
          const dd = isAngle ? (deltaSign + delta.toFixed(1) + "°") : formatSI(delta, unitsMap[key] || "");
          compDisplay = `<div style="font-size:9px; color:#666; margin-top:-2px;">Historic: ${hd} <span style="color:${deltaColor}">(${dd})</span></div>`;
        }
      } else {
        valDisplay = value;
      }
      const isPhaseDetail = key.startsWith("Phase") || key.startsWith("Pri Phase") || key.startsWith("Sec Current Phase") || key.startsWith("Sec Voltage Phase") || key.startsWith("Sec2 Voltage Phase");
      const indent = isPhaseDetail ? "padding-left:20px;" : "";
      html += `<div class="stat-row" style="${indent} flex-direction:column; align-items:stretch; border-bottom:1px solid #222; padding:4px 0;"><div style="display:flex; justify-content:space-between;"><span class="stat-label">${key}:</span><span class="stat-value">${valDisplay}</span></div>${compDisplay}</div>`;
    }
  });
  return html;
}

// Split entries at a key whose text includes markerSubstr. Returns [before, after] (marker entry excluded).
function _splitSummaryAt(entries, markerSubstr) {
  const idx = entries.findIndex(([k]) => k.includes(markerSubstr));
  if (idx === -1) return [entries, []];
  return [entries.slice(0, idx), entries.slice(idx + 1)];
}

// ── updateWindow ───────────────────────────────────────────────────────────────

function updateWindow(id, node) {
  if (!node) return;
  if (!node) return;
  const safeId = id.replace(/\s+/g, "-");
  const content = document.getElementById("win-" + safeId);
  if (!content) return;

  let compNode = null;
  if (compareData) compNode = compareData.nodes.find((n) => n.id === node.id);

  let html = "";

  // 1. PHASOR DIAGRAMS + TELEMETRY — per-winding layout for multi-winding devices
  if (node.type === "DualWindingVT") {
    const allEntries = Object.entries(node.summary || {});
    const [w1Entries, w2Entries] = _splitSummaryAt(allEntries, "WINDING 2");
    html += `<div class="section-title">WINDING 1 — ANALYSIS</div><div class="phasor-box" id="phasor-sec-${safeId}"></div>`;
    html += _renderSummaryRows(w1Entries, compNode);
    html += `<div class="section-title">WINDING 2 — ANALYSIS</div><div class="phasor-box" id="phasor-sec2-${safeId}"></div>`;
    html += _renderSummaryRows(w2Entries, compNode);

  } else if (node.type === "PowerTransformer") {
    const allEntries = Object.entries(node.summary || {});
    const [sharedEntries, afterPri] = _splitSummaryAt(allEntries, "PRIMARY SIDE");
    const [priEntries, secEntries] = _splitSummaryAt(afterPri, "SECONDARY SIDE");
    html += _renderSummaryRows(sharedEntries, compNode);
    html += `<div class="section-title">PRIMARY WINDING (H)</div><div class="phasor-box" id="phasor-pri-${safeId}"></div>`;
    html += _renderSummaryRows(priEntries, compNode);
    html += `<div class="section-title">SECONDARY WINDING (X)</div><div class="phasor-box" id="phasor-sec-${safeId}"></div>`;
    html += _renderSummaryRows(secEntries, compNode);

  } else {
    // Standard single-winding device
    html += `<div class="section-title">PHASOR ANALYSIS</div><div class="phasor-box" id="phasor-${safeId}"></div>`;

    // Protection devices: show per-input breakdown first
    const isProtection = ["Relay", "CTTB", "FTBlock"].includes(node.type);
    const inputNodes = isProtection && node.inputs?.length > 0
      ? node.inputs.map((id) => (currentData && currentData.nodes) && currentData.nodes.find((n) => n.id === id)).filter(Boolean)
      : [];

    if (inputNodes.length > 0) {
      html += '<div class="section-title">INPUT SOURCES</div>';
      const isRelay = ["Relay", "CTTB"].includes(node.type);
      const polarities = (isRelay && node.params?.input_polarities) ? node.params.input_polarities : {};
      inputNodes.forEach((inp) => {
        const s = inp.summary || {};
        const pol = polarities[inp.id] === -1 ? -1 : 1;
        const polLabel = pol === 1 ? "+" : "−";
        const polColor = pol === 1 ? "#0a0" : "#f44";
        const borderColor = pol === 1 ? "#1a4" : "#611";
        html += `<div style="background:#0d0d0d; margin:3px 0; padding:6px 10px; border-left:3px solid ${borderColor};">`;
        html += `<div style="font-size:9px; color:#888; margin-bottom:5px; display:flex; justify-content:space-between; align-items:center;">`;
        html += `<span style="color:#aaa;">${inp.id}</span>`;
        html += `<span style="color:#555;">[${inp.type}]</span>`;
        if (isRelay) {
          html += `<button onclick="toggleInputPolarity('${node.id}', '${inp.id}', ${pol})" style="margin-left:8px; background:#111; border:1px solid ${polColor}; color:${polColor}; font-size:11px; font-weight:bold; width:22px; height:18px; cursor:pointer; line-height:1;">${polLabel}</button>`;
        }
        html += `</div>`;
        ["A", "B", "C"].forEach((p) => {
          const iMag = s[`Sec Current Phase ${p}`], iAng = s[`Phase ${p} I-Angle`];
          const vMag = s[`Sec Voltage Phase ${p}`], vAng = s[`Phase ${p} V-Angle`];
          if (iMag !== undefined) html += `<div style="display:flex; justify-content:space-between; font-size:10px; padding:1px 0; color:#aaa;"><span style="color:#0a0; width:50px;">Ph${p} I</span><span>${pol === -1 ? '<span style="color:#f66">−</span>' : ''}${formatSI(iMag, "A")} &nbsp;∠&nbsp;${_fmtAngle(iAng || 0)}</span></div>`;
          if (vMag !== undefined) html += `<div style="display:flex; justify-content:space-between; font-size:10px; padding:1px 0; color:#aaa;"><span style="color:#66f; width:50px;">Ph${p} V</span><span>${formatSI(vMag, "V")} &nbsp;∠&nbsp;${_fmtAngle(vAng || 0)}</span></div>`;
        });
        html += `</div>`;
      });
      let mathOp;
      if (node.type === "CTTB") {
        mathOp = node.params?.mode === "DIFFERENTIAL" ? "DIFFERENTIAL (I₁ − I₂)" : "VECTOR SUM (Σ I)";
      } else if (isRelay) {
        const signs = inputNodes.map((inp) => (polarities[inp.id] === -1 ? "−" : "+"));
        const allPos = signs.every((s) => s === "+");
        if (allPos) {
          mathOp = "VECTOR SUM (Σ I)";
        } else {
          mathOp = signs.map((s, i) => `${i === 0 && s === "+" ? "" : s + " "}I${i + 1}`).join(" ").trim();
        }
      } else {
        mathOp = "SUM";
      }
      html += `<div style="font-size:9px; color:#555; text-align:center; padding:4px; margin-bottom:2px; border:1px dashed #222;">MATH: ${mathOp}</div>`;
      html += '<div class="section-title">COMBINED RESULT</div>';
    } else {
      html += '<div class="section-title">TELEMETRY DATA</div>';
    }

    html += _renderSummaryRows(Object.entries(node.summary || {}), compNode);
  }

  // Sync error banner (VoltageSource with conflicts)
  if (node.type === "VoltageSource" && node.sync_errors?.length > 0) {
    html += '<div style="background:#1a0000; border:1px solid #f00; padding:8px 10px; margin:6px 0;">';
    html += '<div style="font-size:10px; color:#f44; letter-spacing:1px; margin-bottom:4px;">⚠ SYNC CONFLICT DETECTED</div>';
    node.sync_errors.forEach(err => {
      const other = err.sources.find(s => s !== node.id);
      html += `<div style="font-size:9px; color:#f88; margin-bottom:3px;">With <b style="color:#fa0;">${other}</b>:</div>`;
      err.issues.forEach(issue => { html += `<div style="font-size:9px; color:#f66; padding-left:10px;">• ${issue}</div>`; });
    });
    html += '</div>';
  }

  // 3. EXECUTION CONTROLS
  if (["CircuitBreaker", "Disconnect"].includes(node.type)) {
    const action = node.status === "CLOSED" ? "TRIP / OPEN" : "CLOSE / SYNC";
    const btnClass =
      node.status === "CLOSED" ? "cmd-btn open-state" : "cmd-btn";
    html +=
      '<button class="' +
      btnClass +
      '" onclick="toggleDevice(\'' +
      node.id +
      "')\">EXECUTE: " +
      action +
      "</button>";
  }

  
  // Relay Control (Multi-Output)
  if (node.type === "Relay") {
    const outputs = (node.params && (node.params && node.params.digital_outputs)) || ["TRIP", "OUT101", "OUT102"];
    const overrides = (node.params && (node.params && node.params.output_manual_overrides)) || {};
    
    html += "<div class=\"section-title\">OUTPUT CONTROL (MANUAL)</div>";
    html += "<div style=\"display:grid; grid-template-columns: 1fr 1fr; gap:4px;\">";
    outputs.forEach(out => {
      const isForced = overrides[out] === true;
      const btnCol = isForced ? "#522" : "#111";
      const txtCol = isForced ? "#f44" : "#888";
      const label = isForced ? "FORCE " + out : "OVERRIDE " + out;
      html += "<button class=\"eng-btn\" style=\"background:" + btnCol + "; color:" + txtCol + "; border-color:" + txtCol + "; font-size:9px;\" " +
              "onclick=\"toggleTerminalOverride(\'" + node.id + "\', \'" + out + "\', " + (!isForced) + ")\">" + label + "</button>";
    });
    html += "</div>";

    const isMech = node.summary["Category"] === "Electromechanical";
    if (isMech) {
      const isDropped = node.summary["Target / Flag"] === "DROPPED";
      const tLabel = isDropped ? "RESET TARGET / FLAG" : "DROP TARGET";
      const tCol = isDropped ? "#f80" : "#444";
      html += "<button class=\"cmd-btn\" style=\"background:#111; color:" + tCol + "; border-color:" + tCol + "; margin-top:4px;\" " +
              "onclick=\"toggleRelayTarget(\'" + node.id + "\', " + (!isDropped) + ")\">" + tLabel + "</button>";
    }
    html += "<button class=\"cmd-btn\" style=\"background:#001530; color:#3af; border-color:#3af; margin-top:4px;\" " +
            "onclick=\"showLogicDesigner(\'" + node.id + "\')\">LOGIC DESIGNER <span>CONFIG</span></button>";

    if (typeof simActive !== "undefined" && simActive) {
      html += "<button class=\"cmd-btn\" style=\"background:#001a00; color:#4f4; border-color:#4f4; margin-top:4px;\" " +
              "onclick=\"showRelaySettingsEditor(\'" + node.id + "\')\">RELAY SETTINGS <span>SIM</span></button>";
    }
  }
  // 4. ENGINEERING CONTROLS (Grouped)
  html += '<div class="section-title">ENGINEERING CONTROLS</div>';

  if (node.type === "Wire" || node.type === "Bus") {
    html +=
      '<button class="eng-btn" onclick="startConnectionMode(\'' +
      node.id +
      "', 'X')\">CONNECT TO... <span>&rarr;</span></button>";
  } else if (["VoltageSource", "Load", "ShuntCapacitor", "ShuntReactor", "SurgeArrester", "SVC", "NeutralGroundingResistor"].includes(node.type)) {
    // Single-terminal shunt/source devices — one connection bushing only
    html += '<div style="font-size:9px; color:#666; margin-top:8px; border-bottom:1px solid #222;">TERMINAL CONNECTION</div>';
    html += '<div style="display:flex; gap:4px; margin-top:2px;">';
    html += `<button class="eng-btn" style="flex:1" onclick="startConnectionMode('${node.id}', 'X')">CONNECT <span>&rarr;</span></button>`;
    html += `<button class="eng-btn" style="flex:1" onclick="showPlantMenu(event.pageX, event.pageY, snapToGrid(${node.gx}+60), snapToGrid(${node.gy}), '${node.id}', 'X')">PLANT <span>+</span></button>`;
    html += '</div>';
  } else if (
    ![
      "CurrentTransformer",
      "CTTB",
      "Relay",
      "VoltageTransformer",
      "DualWindingVT",
      "FTBlock",
      "Indicator",
      "Meter",
      "AuxiliaryTransformer",
    ].includes(node.type)
  ) {
    const gx = node.gx,
      gy = node.gy;
    ["H", "X"].forEach((b) => {
      const bName =
        b === "H" ? "BUSHING H (HIGH SIDE)" : "BUSHING X (LOW SIDE)";
      html +=
        '<div style="font-size:9px; color:#666; margin-top:8px; border-bottom:1px solid #222;">' +
        bName +
        "</div>";
      html +=
        '<div style="display:flex; gap:4px; margin-top:2px;">' +
        '<button class="eng-btn" style="flex:1" onclick="startConnectionMode(\'' +
        node.id +
        "', '" +
        b +
        "')\">CONNECT <span>&rarr;</span></button>" +
        '<button class="eng-btn" style="flex:1" onclick="showPlantMenu(event.pageX, event.pageY, snapToGrid(' +
        gx +
        "+60), snapToGrid(" +
        gy +
        "), '" +
        node.id +
        "', '" +
        b +
        "')\">PLANT <span>+</span></button>" +
        "</div>";
      html +=
        '<div style="display:flex; gap:4px; margin-top:2px;">' +
        '<button class="eng-btn" style="flex:1" onclick="quickAddSensor(\'' +
        node.id +
        "', 'CT', '" +
        b +
        "')\">+CT</button>" +
        '<button class="eng-btn" style="flex:1" onclick="quickAddSensor(\'' +
        node.id +
        "', 'VT', '" +
        b +
        "')\">+VT</button>" +
        '<button class="eng-btn" style="flex:1" onclick="quickAddSensor(\'' +
        node.id +
        "', 'DualVT', '" +
        b +
        "')\">+DualVT</button>" +
        "</div>";
    });
  }

  // Secondary/Protection Chaining
  if (
    [
      "CurrentTransformer",
      "CTTB",
      "Relay",
      "VoltageTransformer",
      "DualWindingVT",
      "FTBlock",
      "Indicator",
      "Meter",
      "AuxiliaryTransformer",
    ].includes(node.type)
  ) {
    const isCurrent = ["CurrentTransformer", "CTTB"].includes(node.type);
    const header = isCurrent ? "CURRENT ANALOG PATH" : "VOLTAGE ANALOG PATH";
    const addType = isCurrent ? "CTTB" : "FT";
    html +=
      '<div style="font-size:9px; color:#666; margin-top:8px; border-bottom:1px solid #222;">' +
      header +
      "</div>";
    html +=
      '<div style="display:flex; gap:4px; margin-top:2px;">' +
      '<button class="eng-btn" style="flex:1" onclick="' +
      (isCurrent ? "addCTTB" : "addFTBlock") +
      "('" +
      node.id +
      "')\">+SUM (" +
      addType +
      ")</button>" +
      '<button class="eng-btn" style="flex:1" onclick="addRelay(\'' +
      node.id +
      "')\">+RELAY</button>" +
      '<button class="eng-btn" style="flex:1" onclick="startSecondaryConnectionMode(\'' +
      node.id +
      "')\">CONN <span>&rarr;</span></button>" +
      '<button class="eng-btn" style="flex:1; background:#320; color:#fa0;" onclick="startDCConnectionMode(\'' +
      node.id +
      "\')\">DC <span>&rarr;</span></button>" +
      "</div>";
  }


  // 5. CONTROL & DC WIRING
  const controlTypes = ["Relay", "Indicator", "Meter", "CircuitBreaker", "Disconnect", "CTTB", "FTBlock"];
  if (controlTypes.includes(node.type)) {
    html += '<div class="section-title">CONTROL & DC WIRING</div>';
    html += '<div style="display:flex; gap:4px; margin-top:2px;">';
    html += '<button class="eng-btn" style="flex:1; background:#320; color:#fa0;" onclick="startDCConnectionMode(\'' + node.id + '\')">DC <span>&rarr;</span></button>';
    html += '<button class="eng-btn" style="flex:1; background:#311; color:#f66;" onclick="startTripConnectionMode(\'' + node.id + '\')">TRIP <span>&rarr;</span></button>';
    html += '<button class="eng-btn" style="flex:1; background:#121; color:#6f6;" onclick="startCloseConnectionMode(\'' + node.id + '\')">CLOSE <span>&rarr;</span></button>';
    html += '</div>';
    
    // Wire From Input (reverse mode)
    html += '<div style="display:flex; gap:4px; margin-top:4px;">';
    html += '<button class="eng-btn" style="flex:1; font-size:8px; opacity:0.7;" onclick="startDCConnectionMode(\'' + node.id + '\')">WIRE FROM INPUT Terminal</button>';
    html += '</div>';
  }

  // Phase Reference Selection
  if (
    ["VoltageTransformer", "DualWindingVT", "CurrentTransformer"].includes(
      node.type,
    )
  ) {
    html +=
      '<div style="font-size:9px; color:#666; margin-top:8px; border-bottom:1px solid #222;">SET AS PHASE REFERENCE</div>';
    html += '<div style="display:flex; gap:4px; margin-top:2px;">';
    const isDelta =
      (node.summary && (node.summary && node.summary.Connection)) && (node.summary && (node.summary && node.summary.Connection)).includes("Delta");
    const phases = isDelta ? ["AB", "BC", "CA"] : ["A", "B", "C"];
    phases.forEach((ph) => {
      html += `<button class="eng-btn" style="flex:1" onclick="setAsReference('${node.id}', '${ph}')">${ph}</button>`;
    });
    html += "</div>";
  }

  // 5. DEVICE MANAGEMENT
  html += '<div class="section-title">DEVICE CONFIGURATION</div>';
  html +=
    '<div style="display:flex; gap:4px;">' +
    '<button class="eng-btn" style="flex:1" onclick="' +
    (node.type === "Load" ? "showLoadConfigModal" : "showConfigModal") +
    "('" +
    node.id +
    "')\">PARAMS <span>⚙</span></button>" +
    '<button class="eng-btn" style="flex:1" onclick="rotateDevice(\'' +
    node.id +
    "', " +
    (node.rotation || 0) +
    ')">ROTATE <span>⟳</span></button>' +
    '<button class="eng-btn" style="flex:1" onclick="showRenameDialog(\'' +
    node.id +
    "')\">RENAME</button>" +
    '<button class="eng-btn" style="flex:1; color:#f44; border-color:#522;" onclick="deleteDevice(\'' +
    node.id +
    "')\">DELETE <span>🗑</span></button>" +
    "</div>";

  // Serial number tracking — shows current serial and lets user record swaps
  const curSerial = (node.params && node.params.serial_number) || null;
  html += '<div style="font-size:9px; color:#666; margin-top:8px; border-bottom:1px solid #222;">ASSET SERIAL NUMBER</div>';
  html += '<div style="display:flex; gap:4px; margin-top:2px; align-items:center;">';
  html += `<span style="flex:1; font-size:10px; color:${curSerial ? '#0f0' : '#555'}; overflow:hidden; text-overflow:ellipsis;">${curSerial ? curSerial : '— not recorded —'}</span>`;
  html += `<button class="eng-btn" style="font-size:9px;" onclick="showSerialDialog('${node.id}')">RECORD S/N</button>`;
  html += `<button class="eng-btn" style="font-size:9px;" onclick="showSerialHistory('${node.id}')">S/N LOG</button>`;
  html += '</div>';

  // Analog history — lets technician review all recorded measurements for this device
  html += '<div style="font-size:9px; color:#666; margin-top:8px; border-bottom:1px solid #222;">ANALOG HISTORY</div>';
  html += `<button class="eng-btn" style="width:100%; margin-top:2px;" onclick="showAnalogHistoryModal('${node.id}', ${JSON.stringify(Object.keys(node.summary || {}))})">VIEW RECORDED MEASUREMENTS</button>`;

  content.innerHTML = html;
  drawPhasors(id, node.summary, node.type);
}

// ── Serial Number Dialog ──────────────────────────────────────────────────────

/**
 * Prompts the user to record a serial number (or replacement) for a device.
 * Creates a small overlay with S/N, notes, and technician fields.
 */
function showSerialDialog(deviceId) {
  const overlay = document.createElement("div");
  overlay.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,0.85);z-index:10600;display:flex;align-items:center;justify-content:center;";
  const box = document.createElement("div");
  box.style.cssText = "background:#0c0c0c;border:1px solid #0f0;padding:20px;min-width:360px;font-family:'Consolas','Courier New',monospace;display:flex;flex-direction:column;gap:10px;";
  box.innerHTML = `
    <div style="font-size:11px;color:#0f0;letter-spacing:1px;border-bottom:1px solid #1a1a1a;padding-bottom:8px;">RECORD SERIAL NUMBER — ${deviceId}</div>
    <div style="font-size:9px;color:#888;">SERIAL NUMBER *</div>
    <input id="_sn-serial" type="text" style="background:#111;border:1px solid #333;color:#eee;padding:6px 8px;font-family:inherit;font-size:11px;width:100%;box-sizing:border-box;" placeholder="e.g. SEL-421-SN12345" />
    <div style="font-size:9px;color:#888;">NOTES (reason for change, installation date, etc.)</div>
    <input id="_sn-notes" type="text" style="background:#111;border:1px solid #333;color:#888;padding:6px 8px;font-family:inherit;font-size:10px;width:100%;box-sizing:border-box;" placeholder="e.g. Replaced after thermal trip — 2025-05-12" />
    <div style="font-size:9px;color:#888;">TECHNICIAN</div>
    <input id="_sn-tech" type="text" style="background:#111;border:1px solid #333;color:#888;padding:6px 8px;font-family:inherit;font-size:10px;width:100%;box-sizing:border-box;" value="${_technicianName || ''}" placeholder="Name" />
    <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:4px;">
      <button id="_sn-cancel" style="background:#0a0a0a;border:1px solid #333;color:#555;font-family:inherit;font-size:10px;padding:6px 14px;cursor:pointer;">CANCEL</button>
      <button id="_sn-save" style="background:#001a00;border:1px solid #0f0;color:#0f0;font-family:inherit;font-size:10px;padding:6px 14px;cursor:pointer;">SAVE S/N</button>
    </div>`;
  overlay.appendChild(box);
  document.body.appendChild(overlay);
  document.getElementById("_sn-serial").focus();

  document.getElementById("_sn-cancel").onclick = () => document.body.removeChild(overlay);
  document.getElementById("_sn-save").onclick = () => {
    const serial = document.getElementById("_sn-serial").value.trim();
    if (!serial) { alert("Serial number is required."); return; }
    recordDeviceSerial(deviceId, serial, document.getElementById("_sn-notes").value, document.getElementById("_sn-tech").value)
      .then(() => {
        document.body.removeChild(overlay);
        // Update the in-memory node params so the window refreshes immediately
        const node = currentData && currentData.nodes && currentData.nodes.find(n => n.id === deviceId);
        if (node) { if (!node.params) node.params = {}; node.params.serial_number = serial; }
        refreshData();
      });
  };
}

/**
 * Shows the full serial-number swap history for a device in a modal overlay.
 */
function showSerialHistory(deviceId) {
  const overlay = document.createElement("div");
  overlay.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,0.85);z-index:10600;display:flex;align-items:center;justify-content:center;";
  const box = document.createElement("div");
  box.style.cssText = "background:#0c0c0c;border:1px solid #0af;padding:20px;min-width:420px;max-width:560px;max-height:70vh;overflow-y:auto;font-family:'Consolas','Courier New',monospace;display:flex;flex-direction:column;gap:8px;";
  box.innerHTML = `<div style="font-size:11px;color:#0af;letter-spacing:1px;border-bottom:1px solid #1a1a1a;padding-bottom:8px;">SERIAL NUMBER LOG — ${deviceId}</div><div id="_sh-body" style="font-size:10px;color:#888;">Loading...</div><div style="display:flex;justify-content:flex-end;margin-top:4px;"><button id="_sh-close" style="background:#0a0a0a;border:1px solid #333;color:#555;font-family:inherit;font-size:10px;padding:6px 14px;cursor:pointer;">CLOSE</button></div>`;
  overlay.appendChild(box);
  document.body.appendChild(overlay);
  document.getElementById("_sh-close").onclick = () => document.body.removeChild(overlay);

  fetchDeviceSerials(deviceId).then(data => {
    const rows = data.serials || [];
    if (!rows.length) { document.getElementById("_sh-body").textContent = "No serial numbers recorded yet."; return; }
    let html = '<table style="width:100%;border-collapse:collapse;">';
    html += '<tr style="color:#555;font-size:9px;border-bottom:1px solid #222;"><th style="text-align:left;padding:3px 6px;">DATE</th><th style="text-align:left;padding:3px 6px;">SERIAL</th><th style="text-align:left;padding:3px 6px;">TECH</th><th style="text-align:left;padding:3px 6px;">NOTES</th></tr>';
    rows.forEach((r, i) => {
      const d = new Date(r.epoch * 1000);
      const dateStr = d.toISOString().slice(0, 10);
      const bg = i === 0 ? "#001a00" : "transparent";
      const col = i === 0 ? "#0f0" : "#888";
      html += `<tr style="background:${bg};border-bottom:1px solid #1a1a1a;">`;
      html += `<td style="padding:4px 6px;color:${col};font-size:9px;">${dateStr}</td>`;
      html += `<td style="padding:4px 6px;color:${col};font-size:10px;font-weight:bold;">${r.serial}</td>`;
      html += `<td style="padding:4px 6px;color:#666;font-size:9px;">${r.technician || '—'}</td>`;
      html += `<td style="padding:4px 6px;color:#555;font-size:9px;">${r.notes || '—'}</td>`;
      html += '</tr>';
    });
    html += '</table>';
    document.getElementById("_sh-body").innerHTML = html;
  });
}

// ── Analog History Modal ──────────────────────────────────────────────────────

/**
 * Opens a modal letting the user pick an analog key and view all historical
 * recorded values for that device (across all sessions).
 */
function showAnalogHistoryModal(deviceId, summaryKeys) {
  // Filter to keys that are likely numeric measurements (skip HEADERs, status strings)
  const node = currentData && currentData.nodes && currentData.nodes.find(n => n.id === deviceId);
  const summary = (node && node.summary) || {};
  const measKeys = summaryKeys.filter(k => typeof summary[k] === "number" && summary[k] !== "HEADER");

  const overlay = document.createElement("div");
  overlay.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,0.85);z-index:10600;display:flex;align-items:center;justify-content:center;";
  const box = document.createElement("div");
  box.style.cssText = "background:#0c0c0c;border:1px solid #fa0;padding:20px;min-width:480px;max-width:620px;max-height:80vh;overflow-y:auto;font-family:'Consolas','Courier New',monospace;display:flex;flex-direction:column;gap:8px;";

  const keyOpts = measKeys.map(k => `<option value="${k}">${k}</option>`).join("");
  box.innerHTML = `
    <div style="font-size:11px;color:#fa0;letter-spacing:1px;border-bottom:1px solid #1a1a1a;padding-bottom:8px;">ANALOG HISTORY — ${deviceId}</div>
    <div style="display:flex;gap:8px;align-items:center;">
      <select id="_ah-key" style="flex:1;background:#111;border:1px solid #333;color:#eee;padding:5px 8px;font-family:inherit;font-size:10px;">
        ${keyOpts.length ? keyOpts : '<option value="">— no numeric keys —</option>'}
      </select>
      <button id="_ah-load" style="background:#001a00;border:1px solid #fa0;color:#fa0;font-family:inherit;font-size:10px;padding:5px 14px;cursor:pointer;">LOAD</button>
    </div>
    <div id="_ah-body" style="font-size:10px;color:#888;min-height:60px;">Select a measurement key above, then click LOAD.</div>
    <div style="display:flex;justify-content:flex-end;margin-top:4px;">
      <button id="_ah-close" style="background:#0a0a0a;border:1px solid #333;color:#555;font-family:inherit;font-size:10px;padding:6px 14px;cursor:pointer;">CLOSE</button>
    </div>`;
  overlay.appendChild(box);
  document.body.appendChild(overlay);
  document.getElementById("_ah-close").onclick = () => document.body.removeChild(overlay);

  document.getElementById("_ah-load").onclick = () => {
    const key = document.getElementById("_ah-key").value;
    if (!key) return;
    document.getElementById("_ah-body").textContent = "Loading...";
    fetchAnalogHistory(deviceId, key).then(data => {
      const rows = data.history || [];
      if (!rows.length) { document.getElementById("_ah-body").textContent = "No recorded measurements for this key."; return; }
      const unit = (typeof unitsMap !== "undefined" && unitsMap[key]) || "";
      let html = `<div style="font-size:9px;color:#555;margin-bottom:4px;">${rows.length} reading(s) found — newest first</div>`;
      html += '<table style="width:100%;border-collapse:collapse;">';
      html += '<tr style="color:#555;font-size:9px;border-bottom:1px solid #222;"><th style="text-align:left;padding:3px 6px;">DATE / TIME</th><th style="text-align:right;padding:3px 6px;">VALUE</th><th style="text-align:left;padding:3px 6px;">SESSION</th><th style="text-align:left;padding:3px 6px;">INSTRUMENT</th></tr>';
      rows.forEach(r => {
        const d = new Date(r.epoch * 1000);
        const dateStr = d.toLocaleString();
        const valStr = (typeof formatSI !== "undefined") ? formatSI(r.value, unit) : r.value.toFixed(3) + " " + unit;
        html += `<tr style="border-bottom:1px solid #1a1a1a;">`;
        html += `<td style="padding:4px 6px;color:#aaa;font-size:9px;">${dateStr}</td>`;
        html += `<td style="padding:4px 6px;color:#0f0;font-size:10px;font-weight:bold;text-align:right;">${valStr}</td>`;
        html += `<td style="padding:4px 6px;color:#666;font-size:9px;">${r.label || '—'}</td>`;
        html += `<td style="padding:4px 6px;color:#555;font-size:9px;">${r.instrument || '—'}</td>`;
        html += '</tr>';
      });
      html += '</table>';
      document.getElementById("_ah-body").innerHTML = html;
    });
  };
  // Auto-load the first key if available
  if (measKeys.length) document.getElementById("_ah-load").click();
}

function quickAddSensor(hostId, type, bushing) {
  if (type === "CT") addCTToBushingManual(hostId, bushing);
  else if (type === "VT") addVTToBushingManual(hostId, false, bushing);
  else if (type === "DualVT") addVTToBushingManual(hostId, true, bushing);
}

function addCTToBushingManual(hostId, bushing) {
  const suggested = "CT-" + hostId + "-" + Math.floor(Math.random() * 1000);
  showInputDialog("CT DEVICE ID / NAME", suggested, (devId) => {
    if (!devId) devId = suggested;
    const newCT = {
      id: devId,
      type: "CurrentTransformer",
      location: hostId,
      bushing,
      position: "inner",
      polarity_facing: "AWAY",
      tap_ratios: { "2000:5": 400 },
      selected_tap: "2000:5",
    };
    reconfigureAPI(null, "add_device", { device: newCT }).then(() => refreshData());
  });
}

function addVTToBushingManual(hostId, isDual, bushing) {
  const type = isDual ? "DualWindingVT" : "VoltageTransformer";
  const suggested = (isDual ? "DVT" : "VT") + "-" + hostId + "-" + Math.floor(Math.random() * 1000);
  showInputDialog((isDual ? "DUAL-VT" : "VT") + " DEVICE ID / NAME", suggested, (devId) => {
    if (!devId) devId = suggested;
    const newVT = {
      id: devId,
      type,
      location: hostId,
      bushing,
      tap_ratios: { "2000:1": 2000 },
      selected_tap: "2000:1",
    };
    if (isDual) newVT.sec2_ratio = "2000:1";
    reconfigureAPI(null, "add_device", { device: newVT }).then(() => refreshData());
  });
}

function showContextMenu(e, d) {
  if (typeof simActive !== 'undefined' && simActive) console.log('Sim mode menu showing for', d.id);
  e.preventDefault();
  const menu = d3
    .select("#context-menu")
    .style("display", "block")
    .style("left", e.pageX + "px")
    .style("top", e.pageY + "px");
  menu.html(
    '<div class="menu-item" onclick="' +
      (d.type === "Load" ? "showLoadConfigModal" : "showConfigModal") +
      "('" +
      d.id +
      "')\">CONFIGURE DEVICE</div>" +

      (typeof simActive !== 'undefined' && simActive ?
        '<div style="padding:4px 10px; font-size:9px; color:#555; background:#0a0a0a; border-top:1px solid #222;">SIMULATION</div>' +
        '<div class="menu-item" style="color:#f55;" onclick="showFaultConfig(\'' + d.id + '\')">CONFIGURE & INJECT FAULT...</div>' +
        '<div class="menu-item" style="color:#0f0;" onclick="clearFault(\'' + d.id + '\')">CLEAR FAULT</div>' +
        (d.type === 'Relay' ? '<div class="menu-item" style="color:#4af;" onclick="showRelaySettingsEditor(\'' + d.id + '\')">EDIT RELAY SETTINGS...</div>' : '')
      : '') +

      (function() {
        let breakHtml = "";
        const allConns = [];
        // Find all edges where THIS device is the source
        currentData.edges.forEach(e => {
          const sid = (typeof e.source === "string") ? e.source : e.source.id;
          const tid = (typeof e.target === "string") ? e.target : e.target.id;
          if (sid === d.id) {
            allConns.push({ src: sid, tgt: tid, label: "WIRE TO " + tid });
          } else if (tid === d.id) {
            allConns.push({ src: sid, tgt: tid, label: "WIRE FROM " + sid });
          }
        });
        
        if (allConns.length > 0) {
           breakHtml += '<div style="padding:4px 10px; font-size:9px; color:#555; background:#0a0a0a; border-top:1px solid #222;">BREAK CONNECTION</div>';
           allConns.forEach(c => {
             breakHtml += '<div class="menu-item" style="color:#f88;" onclick="breakConnection(\'' + c.src + '\', \'' + c.tgt + '\')">' + c.label + '</div>';
           });
        }
        return breakHtml;
      })() +
      '<div class="menu-item" onclick="showRenameDialog(\'' +
      d.id +
      "')\">RENAME DEVICE</div>" +
      "<div class=\"menu-item\" onclick=\"d3.select('#context-menu').style('display','none')\">CLOSE MENU</div>",
  );
  d3.select("body").on("click.menu", () =>
    d3.select("#context-menu").style("display", "none"),
  );
}

function makeDraggable(el) {
  const header = el.querySelector(".window-header");
  let p1 = 0,
    p2 = 0,
    p3 = 0,
    p4 = 0;
  header.onmousedown = (e) => {
    e.preventDefault();
    el.style.zIndex = ++zIndexCounter;
    p3 = e.clientX;
    p4 = e.clientY;
    document.onmouseup = () => {
      document.onmouseup = null;
      document.onmousemove = null;
    };
    document.onmousemove = (e) => {
      e.preventDefault();
      p1 = p3 - e.clientX;
      p2 = p4 - e.clientY;
      p3 = e.clientX;
      p4 = e.clientY;
      const newTop = Math.max(0, Math.min(el.offsetTop - p2, window.innerHeight - 36));
      const newLeft = Math.max(-(el.offsetWidth - 70), Math.min(el.offsetLeft - p1, window.innerWidth - 70));
      el.style.top = newTop + "px";
      el.style.left = newLeft + "px";
    };
  };
}

// ── Generic input dialog (replaces all browser prompt() calls) ─────────────────

function showInputDialog(label, defaultVal, callback) {
  const dialog = document.getElementById("input-dialog");
  const field = document.getElementById("input-dialog-field");
  const labelEl = document.getElementById("input-dialog-label");
  labelEl.textContent = label;
  field.value = defaultVal || "";
  dialog.style.display = "flex";
  field.focus();
  field.select();

  const finish = (ok) => {
    dialog.style.display = "none";
    document.getElementById("input-dialog-ok").onclick = null;
    document.getElementById("input-dialog-cancel").onclick = null;
    field.onkeydown = null;
    if (ok) callback(field.value.trim());
  };

  document.getElementById("input-dialog-ok").onclick = () => finish(true);
  document.getElementById("input-dialog-cancel").onclick = () => finish(false);
  field.onkeydown = (e) => {
    if (e.key === "Enter") finish(true);
    if (e.key === "Escape") finish(false);
  };
}

function showRenameDialog(id) {
  showInputDialog("NEW DEVICE NAME / ID", id, (newId) => {
    if (!newId || newId === id) return;
    renameDevice(id, newId).then(() => {
      if (openWindows[id]) {
        closeWindow(id);
      }
      refreshData();
    });
  });
}

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

function showConfigModal(id) {
  const node = (currentData && currentData.nodes) && currentData.nodes.find((n) => n.id === id);
  if (!node) return;
  const fieldDefs = {
    VoltageSource: [
      { label: "Nominal Voltage (kV)", key: "nominal_voltage_kv" },
      { label: "Nominal Power (MVA)", key: "nominal_power_mva" },
      { label: "Power Factor (0-1)", key: "pf" },
      { label: "Phase Shift (°)", key: "phase_shift_deg" },
      {
        label: "Winding / Connection",
        key: "winding_type",
        type: "select",
        options: [
          { value: "Y",  label: "Y — Wye" },
          { value: "YG", label: "YG — Wye Grounded" },
          { value: "D",  label: "D — Delta" },
        ],
      },
    ],
    CircuitBreaker: [
      { label: "Single Pole Mode", key: "is_single_pole", type: "checkbox" },
      { label: "Continuous Amps (A)", key: "continuous_amps" },
      { label: "Interrupt (kA)", key: "interrupt_ka" },
    ],
    VoltageRegulator: [
      { label: "Nominal Voltage (kV)", key: "nominal_kv" },
      { label: "Tap Position (-16 to +16)", key: "tap_pos" },
      { label: "Step % (default 0.625)", key: "step_percent" },
      { label: "Max Steps (default 16)", key: "max_steps" },
    ],
    PowerTransformer: [
      { label: "Pri (kV)", key: "pri_kv" },
      { label: "Sec (kV)", key: "sec_kv" },
    ],
    CTTB: [
      {
        label: "CTTB Mode",
        key: "mode",
        type: "select",
        options: [
          { value: "SUM", label: "SUM (Totalization)" },
          { value: "DIFFERENTIAL", label: "DIFFERENTIAL (I1 - I2 - ...)" },
        ],
      },
    ],
    Meter: [],
    AuxiliaryTransformer: [
      { label: "Phase Shift (°)", key: "phase_shift_deg" },
      { label: "Ratio Correction", key: "ratio" },
    ],
    Relay: [
      {
        label: "Relay Category",
        key: "category",
        type: "select",
        options: [
          { value: "Numerical", label: "Microprocessor / Numerical" },
          { value: "Electromechanical", label: "Electromechanical (Latching)" },
        ],
      },
      {
        label: "Relay Function",
        key: "function",
        type: "select",
        options: [
          { value: "Differential", label: "87 — Differential" },
          { value: "Overcurrent", label: "50/51 — Overcurrent" },
          { value: "Distance", label: "21 — Distance" },
          { value: "Lockout", label: "86 — Lockout" },
        ],
      },
    ],
    CurrentTransformer: [
      { label: "Bushing", key: "bushing", type: "text" },
      { label: "Position", key: "position", type: "text" },
      { label: "Polarity Normal", key: "polarity_normal", type: "checkbox" },
      { label: "Phase Shift (°)", key: "phase_shift_deg" },
      {
        label: "Secondary Wiring",
        key: "secondary_wiring",
        type: "select",
        options: [
          { value: "Y", label: "Y — Wye (Standard)" },
          { value: "DAB", label: "Δ — Delta (DAB)" },
          { value: "DAC", label: "Δ — Delta (DAC)" },
          { value: "RESIDUAL", label: "3I₀ — Residual" },
          { value: "A", label: "Phase A Only" },
          { value: "B", label: "Phase B Only" },
          { value: "C", label: "Phase C Only" },
          { value: "N", label: "Neutral / Ground" },
        ],
      },
      { label: "Phase A Ratio Override", key: "ratio_a" },
      { label: "Phase B Ratio Override", key: "ratio_b" },
      { label: "Phase C Ratio Override", key: "ratio_c" },
    ],
    VoltageTransformer: [
      { label: "Bushing", key: "bushing", type: "text" },
      { label: "Polarity Normal", key: "polarity_normal", type: "checkbox" },
      { label: "Phase Shift (°)", key: "phase_shift_deg" },
      {
        label: "Secondary Wiring",
        key: "secondary_wiring",
        type: "select",
        options: [
          { value: "Y", label: "Y — Wye (LN)" },
          { value: "D", label: "Δ — Delta (LL)" },
          { value: "DAB", label: "Δ — Delta (DAB)" },
          { value: "DAC", label: "Δ — Delta (DAC)" },
        ],
      },
    ],
    DualWindingVT: [
      { label: "Bushing", key: "bushing", type: "text" },
      { label: "Polarity Normal", key: "polarity_normal", type: "checkbox" },
      { label: "Phase Shift (°)", key: "phase_shift_deg" },
      { label: "W2 Ratio (e.g. 2000:1)", key: "sec2_ratio", type: "text" },
      {
        label: "W1 Secondary Wiring",
        key: "secondary_wiring",
        type: "select",
        options: [
          { value: "Y", label: "Y — Wye (LN)" },
          { value: "D", label: "Δ — Delta (LL)" },
          { value: "DAB", label: "Δ — Delta (DAB)" },
          { value: "DAC", label: "Δ — Delta (DAC)" },
        ],
      },
      {
        label: "W2 Secondary Wiring",
        key: "secondary2_wiring",
        type: "select",
        options: [
          { value: "Y", label: "Y — Wye (LN)" },
          { value: "D", label: "Δ — Delta (LL)" },
          { value: "DAB", label: "Δ — Delta (DAB)" },
          { value: "DAC", label: "Δ — Delta (DAC)" },
        ],
      },
    ],
    ShuntCapacitor: [
      { label: "Rating (MVAr)", key: "mvar_rating" },
      { label: "Rated Voltage (kV)", key: "kv_rating" },
    ],
    ShuntReactor: [
      { label: "Rating (MVAr)", key: "mvar_rating" },
      { label: "Rated Voltage (kV)", key: "kv_rating" },
    ],
    SurgeArrester: [
      { label: "Rated kV (MCOV)", key: "kv_rating" },
      { label: "Bushing", key: "bushing", type: "text" },
      { label: "Polarity Normal", key: "polarity_normal", type: "checkbox" },
      { label: "Phase Shift (°)", key: "phase_shift_deg" },
    ],
    SeriesCapacitor: [
      { label: "Rating (MVAr)", key: "mvar_rating" },
      { label: "Reactance Xc (Ω)", key: "impedance_ohm" },
    ],
    SeriesReactor: [
      { label: "Rating (MVAr)", key: "mvar_rating" },
      { label: "Reactance XL (Ω)", key: "impedance_ohm" },
    ],
    NeutralGroundingResistor: [
      { label: "Resistance (Ω)", key: "resistance_ohm" },
      { label: "Rated kV", key: "kv_rating" },
    ],
    SVC: [
      { label: "MVAr Min", key: "mvar_min" },
      { label: "MVAr Max", key: "mvar_max" },
      { label: "MVAr Setting (+cap / −ind)", key: "mvar_setting" },
      { label: "Rated kV", key: "kv_rating" },
    ],
    PowerLine: [
      { label: 'Length (km)', key: 'length_km' },
      { label: 'R (Ω/km)', key: 'r_per_km' },
      { label: 'X (Ω/km)', key: 'x_per_km' },
    ],
    Line: [
      { label: 'Length (km)', key: 'length_km' },
      { label: 'R (Ω/km)', key: 'r_per_km' },
      { label: 'X (Ω/km)', key: 'x_per_km' },
    ],

    LineTrap: [
      { label: "Carrier Frequency (Hz)", key: "carrier_frequency_hz" },
    ],
  };
  // Always append serial_number as a universal editable field
  const typeFields = fieldDefs[node.type] || [];
  const serialField = { label: "Serial Number", key: "serial_number", type: "text" };
  const fields = [...typeFields, serialField];
  const params = {...(node.params || {})};
  if (node.type === "CurrentTransformer" && params.phase_ratios) {
    params.ratio_a = params.phase_ratios.a;
    params.ratio_b = params.phase_ratios.b;
    params.ratio_c = params.phase_ratios.c;
  }
  _resetConfigModalPos();
  d3.select("#config-modal").style("display", "flex");
  d3.select("#modal-title").text("CONFIGURE [" + id + "]");
  const body = d3.select("#modal-body").html("");
  fields.forEach((f) => {
    body
      .append("label")
      .text(f.label)
      .style("font-size", "9px")
      .style("color", "#888")
      .style("margin-top", "6px");

    if (f.type === "select") {
      const sel = body
        .append("select")
        .attr("id", "conf-" + f.key)
        .style("width", "100%")
        .style("background", "#222")
        .style("color", "#eee")
        .style("border", "1px solid #444")
        .style("padding", "4px")
        .style("margin-bottom", "4px");
      (f.options || []).forEach((opt) => {
        sel
          .append("option")
          .attr("value", opt.value)
          .text(opt.label)
          .property("selected", (params[f.key] ?? "") === opt.value);
      });
    } else if (f.type === "checkbox") {
      body
        .append("input")
        .attr("id", "conf-" + f.key)
        .attr("type", "checkbox")
        .property("checked", params[f.key] !== false); // default to true if undefined
      body.append("span").text(" (Active)").style("font-size", "9px").style("color", "#555");
    } else {
      body
        .append("input")
        .attr("id", "conf-" + f.key)
        .attr("type", f.type || "number")
        .property("value", params[f.key] ?? "");
    }
  });

  // CT/VT/DualWindingVT: tap ratio selector + add/remove tap management
  if (["CurrentTransformer", "VoltageTransformer", "DualWindingVT", "VoltageRegulator"].includes(node.type)) {
    _appendTapSelector(body, params, node.type);
  }

  // PowerTransformer: tap selector + winding type selectors
  if (node.type === "PowerTransformer") {
    _appendPTTapSelector(body, params);
    _appendWindingSelects(body, params);
  }

  d3.select("#modal-save").on("click", () => {
    const props = {};
    fields.forEach((f) => {
      const el = d3.select("#conf-" + f.key);
      if (f.type === "checkbox") {
        props[f.key] = el.property("checked");
      } else {
        const v = el.property("value");
        if (v !== "") {
          if (f.type === "text" || f.type === "select") {
            props[f.key] = v;
          } else {
            props[f.key] = parseFloat(v);
          }
        }
      }
    });
    if (["CurrentTransformer", "VoltageTransformer", "DualWindingVT", "VoltageRegulator"].includes(node.type)) {
      const selTap = document.getElementById("conf-selected_tap");
      if (selTap) props.selected_tap = selTap.value;
      // collect tap_ratios from the editable list; parse "N:M" strings into floats
      const tapRows = document.querySelectorAll(".tap-ratio-row");
      if (tapRows.length > 0) {
        const tapRatios = {};
        tapRows.forEach(row => {
          const lbl = row.querySelector(".tap-lbl")?.value?.trim();
          if (!lbl) return;
          const parts = lbl.split(":");
          if (parts.length === 2) {
            const ratio = parseFloat(parts[0]) / parseFloat(parts[1]);
            if (!isNaN(ratio) && ratio > 0) tapRatios[lbl] = ratio;
          }
        });
        if (Object.keys(tapRatios).length > 0) props.tap_ratios = tapRatios;
      }
    }
    if (node.type === "CurrentTransformer") {
      const pr = {};
      if (props.ratio_a) pr.a = props.ratio_a;
      if (props.ratio_b) pr.b = props.ratio_b;
      if (props.ratio_c) pr.c = props.ratio_c;
      if (Object.keys(pr).length > 0) props.phase_ratios = pr;
    }
    if (node.type === "PowerTransformer") {
      props.h_winding = document.getElementById("conf-h_winding").value;
      props.x_winding = document.getElementById("conf-x_winding").value;
      props.polarity_reversed = document.getElementById(
        "conf-polarity_reversed",
      ).checked;
      const selIdx = document.getElementById("conf-selected_tap_index");
      if (selIdx) props.selected_tap_index = parseInt(selIdx.value, 10);
    }
    reconfigureAPI(id, "update_device", { properties: props }).then(() => {
      d3.select("#config-modal").style("display", "none");
      refreshData();
    });
  });
}

function _appendTapSelector(body, params, deviceType) {
  const tapRatios = params.tap_ratios || {};
  const tapKeys = Object.keys(tapRatios);
  const selectedTap = params.selected_tap || tapKeys[0] || "";

  body.append("div")
    .style("font-size", "9px").style("color", "#0af")
    .style("margin-top", "12px").style("border-top", "1px solid #1a1a1a")
    .style("padding-top", "8px").style("letter-spacing", "1px")
    .text("TAP RATIOS");

  // Active tap selector
  body.append("label").text("ACTIVE TAP")
    .style("font-size", "9px").style("color", "#888").style("margin-top", "6px");
  const sel = body.append("select").attr("id", "conf-selected_tap")
    .style("width", "100%").style("background", "#222").style("color", "#eee")
    .style("border", "1px solid #444").style("padding", "4px").style("margin-bottom", "6px");
  tapKeys.forEach(k => {
    sel.append("option").attr("value", k).text(k)
      .property("selected", k === selectedTap);
  });
  if (tapKeys.length === 0) {
    sel.append("option").attr("value", selectedTap).text(selectedTap || "(none)")
      .property("selected", true);
  }

  // Editable tap list
  body.append("label").text("ALL TAPS (one per line, label:ratio format)")
    .style("font-size", "9px").style("color", "#888").style("margin-top", "4px");

  const listDiv = body.append("div").attr("id", "tap-list-container")
    .style("display", "flex").style("flex-direction", "column").style("gap", "3px")
    .style("margin-bottom", "4px");

  const renderTapList = (taps) => {
    listDiv.html("");
    taps.forEach((k, i) => {
      const row = listDiv.append("div").attr("class", "tap-ratio-row")
        .style("display", "flex").style("gap", "4px").style("align-items", "center");
      row.append("input").attr("class", "tap-lbl").attr("type", "text")
        .property("value", k)
        .style("flex", "1").style("background", "#111").style("border", "1px solid #333")
        .style("color", "#eee").style("padding", "3px 6px").style("font-size", "10px")
        .on("input", function() {
          // update the active-tap selector live
          const selEl = document.getElementById("conf-selected_tap");
          if (selEl && selEl.options[i]) selEl.options[i].value = this.value;
          if (selEl && selEl.options[i]) selEl.options[i].textContent = this.value;
        });
      row.append("button").text("✕")
        .style("background", "none").style("border", "1px solid #522")
        .style("color", "#f44").style("cursor", "pointer").style("font-size", "10px")
        .style("padding", "2px 6px")
        .on("click", () => {
          const remaining = Array.from(document.querySelectorAll(".tap-ratio-row .tap-lbl"))
            .map(el => el.value).filter((_, j) => j !== i);
          renderTapList(remaining);
        });
    });
  };
  renderTapList(tapKeys.length > 0 ? tapKeys : (selectedTap ? [selectedTap] : []));

  body.append("button").text("+ ADD TAP")
    .style("background", "#0a0a0a").style("border", "1px solid #333").style("color", "#888")
    .style("font-size", "9px").style("padding", "4px 10px").style("cursor", "pointer")
    .style("margin-bottom", "6px")
    .on("click", () => {
      const existing = Array.from(document.querySelectorAll(".tap-ratio-row .tap-lbl"))
        .map(el => el.value);
      renderTapList([...existing, deviceType === "CurrentTransformer" ? "2000:5" : "2000:1"]);
    });
}

function _appendPTTapSelector(body, params) {
  const tapConfigs = params.tap_configs || [{ label: "Nominal", pri_kv: params.pri_kv || 230, sec_kv: params.sec_kv || 115 }];
  const selectedIdx = params.selected_tap_index ?? 0;

  body.append("div")
    .style("font-size", "9px").style("color", "#0af")
    .style("margin-top", "12px").style("border-top", "1px solid #1a1a1a")
    .style("padding-top", "8px").style("letter-spacing", "1px")
    .text("TAP POSITIONS");

  body.append("label").text("ACTIVE TAP POSITION")
    .style("font-size", "9px").style("color", "#888").style("margin-top", "6px");
  const sel = body.append("select").attr("id", "conf-selected_tap_index")
    .style("width", "100%").style("background", "#222").style("color", "#eee")
    .style("border", "1px solid #444").style("padding", "4px").style("margin-bottom", "6px");
  tapConfigs.forEach((tap, i) => {
    const label = tap.label || `Tap ${i + 1}`;
    const detail = ` (${tap.pri_kv}kV / ${tap.sec_kv}kV)`;
    sel.append("option").attr("value", i).text(label + detail)
      .property("selected", i === selectedIdx);
  });
}

const _WINDING_OPTIONS = [
  { value: "Y", label: "Y — Wye" },
  { value: "YG", label: "YG — Wye Grounded" },
  { value: "D", label: "D — Delta" },
  { value: "Z", label: "Z — Zigzag" },
  { value: "ZG", label: "ZG — Zigzag Grounded" },
];

function _appendWindingSelects(body, params) {
  [
    { label: "HV Winding (H)", key: "h_winding" },
    { label: "LV Winding (X)", key: "x_winding" },
  ].forEach(({ label, key }) => {
    body
      .append("label")
      .text(label)
      .style("font-size", "9px")
      .style("color", "#888")
      .style("margin-top", "8px");
    const sel = body.append("select").attr("id", "conf-" + key);
    _WINDING_OPTIONS.forEach((o) => {
      sel
        .append("option")
        .attr("value", o.value)
        .property(
          "selected",
          (params[key] || (key === "h_winding" ? "Y" : "D")) === o.value,
        )
        .text(o.label);
    });
    sel.on("change", () => _updateAutoShiftHint());
  });

  // Polarity row (only meaningful for cross-family combos, but always shown)
  const polarityRow = body
    .append("div")
    .style("display", "flex")
    .style("align-items", "center")
    .style("gap", "8px")
    .style("margin-top", "10px");
  polarityRow
    .append("input")
    .attr("id", "conf-polarity_reversed")
    .attr("type", "checkbox")
    .property("checked", params.polarity_reversed === true)
    .on("change", () => _updateAutoShiftHint());
  polarityRow
    .append("label")
    .attr("for", "conf-polarity_reversed")
    .text("Reversed polarity (+30° instead of −30°)")
    .style("font-size", "9px")
    .style("color", "#ccc")
    .style("cursor", "pointer");

  body
    .append("div")
    .attr("id", "winding-shift-hint")
    .style("font-size", "9px")
    .style("color", "#3af")
    .style("margin-top", "4px")
    .text(
      _shiftHintText(
        params.h_winding || "Y",
        params.x_winding || "D",
        params.polarity_reversed === true,
      ),
    );
}

function _isCrossFamily(h, x) {
  const yFamily = new Set(["Y", "YG"]);
  return yFamily.has(h.toUpperCase()) !== yFamily.has(x.toUpperCase());
}

function _shiftHintText(h, x, reversed) {
  const names = {
    Y: "Wye",
    YG: "Wye-Grounded",
    D: "Delta",
    Z: "Zigzag",
    ZG: "Zigzag-Grounded",
  };
  const cross = _isCrossFamily(h, x);
  const shift = cross ? (reversed ? +30 : -30) : 0;
  const polNote = cross
    ? reversed
      ? " · Reversed polarity"
      : " · Normal polarity (ANSI)"
    : " · Same family — polarity has no effect";
  return `${names[h] || h} / ${names[x] || x} → ${shift > 0 ? "+" : ""}${shift}°${polNote}`;
}

function _updateAutoShiftHint() {
  const h = document.getElementById("conf-h_winding")?.value || "Y";
  const x = document.getElementById("conf-x_winding")?.value || "D";
  const reversed =
    document.getElementById("conf-polarity_reversed")?.checked || false;
  const hint = document.getElementById("winding-shift-hint");
  if (hint) hint.textContent = _shiftHintText(h, x, reversed);
}

function showLoadConfigModal(id) {
  const node = (currentData && currentData.nodes) && currentData.nodes.find((n) => n.id === id);
  if (!node) return;
  _resetConfigModalPos();
  d3.select("#config-modal").style("display", "flex");
  d3.select("#modal-title").text("LOAD CONFIGURATION [" + id + "]");
  const body = d3.select("#modal-body").html("");
  const params = node.params,
    totalMva = params.load_mva || 0,
    totalPf = params.pf || 1.0;
  const phaseVa = params.phase_va || {
    a: (totalMva * 1e6) / 3,
    b: (totalMva * 1e6) / 3,
    c: (totalMva * 1e6) / 3,
  };
  const phasePf = params.phase_pf || { a: totalPf, b: totalPf, c: totalPf };
  const nonZero = ["a", "b", "c"].filter((p) => (phaseVa[p] || 0) > 1);
  const isSingle = params.is_balanced === false && nonZero.length <= 1;
  const mode = isSingle ? "single" : "3phase";
  const activePh = isSingle ? nonZero[0] || "a" : "a";

  let html =
    '<div style="margin-bottom:8px;"><label style="font-size:10px;color:#fff;">MODE:</label>' +
    '<select id="load-mode-select" style="width:100%;margin-top:4px;">' +
    '<option value="3phase"' +
    (mode === "3phase" ? " selected" : "") +
    ">3-Phase</option>" +
    '<option value="single"' +
    (mode === "single" ? " selected" : "") +
    ">Single Phase</option>" +
    "</select></div>";

  // 3-phase: total at top, per-phase breakdown constrained to sum to total
  const initPhVa = (p) =>
    params.is_balanced === false ? (phaseVa[p] || 0) / 1e6 : totalMva / 3;
  const initPhPf = (p) =>
    params.is_balanced === false ? phasePf[p] || 1.0 : totalPf;
  html +=
    '<div id="load-3phase-section" style="display:' +
    (mode === "3phase" ? "block" : "none") +
    ';">';
  html += '<div class="section-title">3-PHASE TOTAL</div>';
  html +=
    createLoadRow("Total MVA", "total-mva", totalMva) +
    createLoadRow("Power Factor", "total-pf", totalPf);
  html += '<div class="section-title">PHASE BREAKDOWN</div>';
  ["a", "b", "c"].forEach((p) => {
    html += createLoadRow(
      "Phase " + p.toUpperCase() + " MVA",
      "ph-" + p + "-mva",
      initPhVa(p),
    );
    html += createLoadRow(
      "Phase " + p.toUpperCase() + " PF",
      "ph-" + p + "-pf",
      initPhPf(p),
    );
  });
  html += "</div>";

  // Single phase: choose which phase carries all the load
  html +=
    '<div id="load-single-section" style="display:' +
    (mode === "single" ? "block" : "none") +
    ';">';
  html += '<div class="section-title">SINGLE PHASE</div>';
  html +=
    '<div style="margin-bottom:6px;"><label style="font-size:9px;color:#888;display:block;">Active Phase</label>' +
    '<select id="single-ph-select" style="width:100%;">' +
    ["a", "b", "c"]
      .map(
        (p) =>
          '<option value="' +
          p +
          '"' +
          (p === activePh ? " selected" : "") +
          ">Phase " +
          p.toUpperCase() +
          "</option>",
      )
      .join("") +
    "</select></div>";
  html += createLoadRow(
    "Phase MVA",
    "single-mva",
    (phaseVa[activePh] || 0) / 1e6,
  );
  html += createLoadRow("Power Factor", "single-pf", phasePf[activePh] || 1.0);
  html += "</div>";
  body.html(html);

  d3.select("#load-mode-select").on("change", function () {
    d3.select("#load-3phase-section").style(
      "display",
      this.value === "3phase" ? "block" : "none",
    );
    d3.select("#load-single-section").style(
      "display",
      this.value === "single" ? "block" : "none",
    );
  });

  // Total changed: redistribute phases preserving their ratios; also push PF to all phases
  function onTotalChange() {
    const t = parseFloat(d3.select("#total-mva").property("value")) || 0;
    const pf = parseFloat(d3.select("#total-pf").property("value")) || 1.0;
    const a = parseFloat(d3.select("#ph-a-mva").property("value")) || 0,
      b = parseFloat(d3.select("#ph-b-mva").property("value")) || 0,
      c = parseFloat(d3.select("#ph-c-mva").property("value")) || 0;
    const s = a + b + c;
    if (s > 0) {
      d3.select("#ph-a-mva").property("value", ((t * a) / s).toFixed(3));
      d3.select("#ph-b-mva").property("value", ((t * b) / s).toFixed(3));
      d3.select("#ph-c-mva").property("value", ((t * c) / s).toFixed(3));
    } else {
      ["a", "b", "c"].forEach((p) =>
        d3.select("#ph-" + p + "-mva").property("value", (t / 3).toFixed(3)),
      );
    }
    ["a", "b", "c"].forEach((p) =>
      d3.select("#ph-" + p + "-pf").property("value", pf.toFixed(3)),
    );
  }

  // Phase MVA changed: adjust the other two (preserving their ratio) to keep sum = total
  function onPhaseChange(ch) {
    const total = parseFloat(d3.select("#total-mva").property("value")) || 0;
    let v = parseFloat(d3.select("#ph-" + ch + "-mva").property("value")) || 0;
    if (v > total) {
      v = total;
      d3.select("#ph-" + ch + "-mva").property("value", total.toFixed(3));
    }
    const rem = total - v,
      oth = ["a", "b", "c"].filter((p) => p !== ch);
    const o0 =
      parseFloat(d3.select("#ph-" + oth[0] + "-mva").property("value")) || 0;
    const o1 =
      parseFloat(d3.select("#ph-" + oth[1] + "-mva").property("value")) || 0;
    const os = o0 + o1;
    d3.select("#ph-" + oth[0] + "-mva").property(
      "value",
      (os > 0 ? (rem * o0) / os : rem / 2).toFixed(3),
    );
    d3.select("#ph-" + oth[1] + "-mva").property(
      "value",
      (os > 0 ? (rem * o1) / os : rem / 2).toFixed(3),
    );
  }

  d3.select("#total-mva").on("input", onTotalChange);
  d3.select("#total-pf").on("input", onTotalChange);
  ["a", "b", "c"].forEach((p) =>
    d3.select("#ph-" + p + "-mva").on("input", () => onPhaseChange(p)),
  );

  d3.select("#modal-save").on("click", () => {
    const m = d3.select("#load-mode-select").property("value");
    let props;
    if (m === "3phase") {
      const pva = {},
        ppf = {};
      ["a", "b", "c"].forEach((p) => {
        pva[p] =
          (parseFloat(d3.select("#ph-" + p + "-mva").property("value")) || 0) *
          1e6;
        ppf[p] =
          parseFloat(d3.select("#ph-" + p + "-pf").property("value")) || 1.0;
      });
      props = {
        is_balanced: false,
        load_mva: parseFloat(d3.select("#total-mva").property("value")) || 0,
        pf: parseFloat(d3.select("#total-pf").property("value")) || 1.0,
        phase_va: pva,
        phase_pf: ppf,
      };
    } else {
      const ph = d3.select("#single-ph-select").property("value"),
        mva =
          (parseFloat(d3.select("#single-mva").property("value")) || 0) * 1e6,
        pf = parseFloat(d3.select("#single-pf").property("value")) || 1.0;
      const pva = { a: 0, b: 0, c: 0 },
        ppf = { a: 1.0, b: 1.0, c: 1.0 };
      pva[ph] = mva;
      ppf[ph] = pf;
      props = {
        is_balanced: false,
        load_mva: mva / 1e6,
        pf,
        phase_va: pva,
        phase_pf: ppf,
      };
    }
    reconfigureAPI(id, "update_device", { properties: props }).then(() => {
      d3.select("#config-modal").style("display", "none");
      refreshData();
    });
  });
}

function createLoadRow(label, id, value) {
  return (
    '<div style="margin-bottom:6px;"><label style="font-size:9px; color:#888; display:block;">' +
    label +
    '</label><input id="' +
    id +
    '" type="number" step="0.001" style="width:100%; box-sizing:border-box;" value="' +
    value.toFixed(3) +
    '"></div>'
  );
}

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
let _bpVoltDevices   = []; // ordered selected voltage-only device IDs
let _bpCurrDevices   = []; // ordered selected current-only device IDs
let _bpRelayDevices  = []; // ordered selected relay device IDs
let _bpMultiDevices  = []; // ordered selected multi-analog (primary) device IDs

// Instrument type for this session
let _bpInstrumentType = "manual"; // "pmm1" | "pmm2" | "manual"
let _pmmPort = null; // selected serial port path
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
  const names = _technicianName
    ? [_technicianName, ...hist.filter((n) => n !== _technicianName)]
    : hist;

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
    row.textContent = name;
    row.style.cssText =
      "padding:9px 12px;border:1px solid #1a1a1a;color:#0f0;cursor:pointer;font-size:11px;border-radius:2px;";
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
    .text("BRAIN POINT — THE PONEGLYPH SYSTEM")
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
    {
      id: "sim",
      title: "DEBUG / SIMULATION",
      sub: "Generate mock power measurements (no hardware needed)",
      badge: "DEBUG",
      badgeColor: "#f0f",
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
        _bpRenderStep4();
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
  footer.append("div").style("flex", 1);
  footer
    .append("button")
    .attr("class", "wiz-save")
    .text(
      _bpInstrumentType === "pmm1"
        ? "NEXT: CONNECT PMM-1 →"
        : _bpInstrumentType === "pmm2"
          ? "NEXT: CONNECT PMM-2 →"
          : _bpInstrumentType === "sim"
            ? "START SIMULATION →"
            : "NEXT: CONFIGURE →",
    )
    .on("click", () => {
      if (_bpInstrumentType === "pmm1") _bpConnectPMM1();
      else if (_bpInstrumentType === "pmm2") _bpConnectPMM2();
      else if (_bpInstrumentType === "sim") _bpStartSimulation();
      else {
          _bpTargetDeviceId = _bpSelectedDevices[0];
          _bpTargetPhase = "A";
          _bpRenderStep5();
      }
    });
}

// PMM-1 port selection + real serial connection
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
    .text("PMM-1 CONNECTION  ·  19200 BAUD  ·  8N1")
    .style("font-size", "10px")
    .style("color", "#0a0")
    .style("letter-spacing", "1px")
    .style("margin-bottom", "18px");

  // Port selector
  const portRow = body
    .append("div")
    .style("display", "flex")
    .style("gap", "8px")
    .style("align-items", "center")
    .style("margin-bottom", "14px");
  portRow
    .append("label")
    .text("SERIAL PORT")
    .style("font-size", "9px")
    .style("color", "#888")
    .style("white-space", "nowrap");
  const portSel = portRow
    .append("select")
    .style("flex", "1")
    .style("background", "#111")
    .style("color", "#0f0")
    .style("border", "1px solid #040")
    .style("padding", "4px 8px");
  portSel.append("option").attr("value", "").text("-- select port --");
  portSel.on("change", function () {
    _pmmPort = this.value;
  });

  // Refresh port list
  const refreshBtn = portRow
    .append("button")
    .attr("class", "wiz-secondary")
    .style("font-size", "9px")
    .text("↺ REFRESH")
    .on("click", () => _bpPopulatePorts(portSel));
  _bpPopulatePorts(portSel);

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
      .text("✓ CONNECTED TO PMM-1 @ " + _pmmPort)
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
      .text("Select a port and press CONNECT.")
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
          _bpConnectPMM1();
        });
      });
    footer
      .append("button")
      .attr("class", "wiz-save")
      .text("NEXT: DEVICES →")
      .on("click", _bpRenderStep4);
  } else {
    footer
      .append("button")
      .attr("class", "wiz-save")
      .text("CONNECT →")
      .on("click", () => {
        const port = portSel.node().value;
        if (!port) {
          term.node().innerHTML = "";
          term
            .append("div")
            .text("⚠ SELECT A PORT FIRST")
            .style("color", "#f80");
          return;
        }
        _pmmPort = port;
        term.node().innerHTML = "";
        term
          .append("div")
          .text("> Connecting to " + port + " @ 19200 8N1...")
          .style("color", "#888");
        fetch("/api/pmm/connect", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ port, model: "pmm1" }),
        })
          .then((r) => r.json())
          .then((res) => {
            if (res.ok) {
              _pmmConnected = true;
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
              .text("✗ " + e)
              .style("color", "#f44"),
          );
      });
  }
}

function _bpStartSimulation() {
  _pmmConnected = true;
  fetch("/api/pmm/connect", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ port: "SIMULATOR", model: "sim" }),
  }).then(() => {
    _bpRenderStep4();
  });
}

function _bpPopulatePorts(selectEl) {
  fetch("/api/pmm/ports")
    .then((r) => r.json())
    .then((data) => {
      selectEl.selectAll("option").remove();
      selectEl.append("option").attr("value", "").text("-- select port --");
      (data.ports || []).forEach((p) => {
        selectEl
          .append("option")
          .attr("value", p.device)
          .text(
            p.device +
              (p.description !== p.device ? "  ·  " + p.description : ""),
          )
          .property("selected", _pmmPort === p.device);
      });
      if (_pmmPort) selectEl.property("value", _pmmPort);
    })
    .catch(() => {
      selectEl.selectAll("option").remove();
      selectEl
        .append("option")
        .attr("value", "")
        .text("-- could not enumerate ports --");
    });
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
      .text("NEXT: DEVICES →")
      .on("click", _bpRenderStep4);
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
        (_bpInstrumentType === "pmm1" || _bpInstrumentType === "pmm2" || _bpInstrumentType === "sim") &&
        _pmmConnected
      );
      if (isMeter) {
        fetch("/api/pmm/configure", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ chan1: c1Val, chan2: c2Val }),
        }).catch(() => {});
      }
      if (isVolt && _activeTestId) {
        _bpCaptureVRef(c1Val, _bpRefVTId, isMeter, onDone);
      } else {
        onDone();
      }
    });
}

// Capture the system reference VT magnitude after the voltage channel has been
// configured. Meter / sim sessions read chan1 from /api/pmm/query; manual
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
        fetch("/api/pmm/query")
          .then(r => r.json())
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

  footer.append("button")
    .text("← BACK")
    .style("background", "#0a0a0a").style("border", "1px solid #333").style("color", "#666")
    .style("font-family", "inherit").style("font-size", "10px")
    .style("padding", "6px 12px").style("cursor", "pointer")
    .on("click", () => _bpRenderChannelConfigOverlay("voltage", onDone));
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
      }
      _bpRenderStep0();
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

function _bpRenderPMMStep5() {
  d3.select("#status-bar")
    .style("background", "#040")
    .style("color", "#0f0")
    .text(`BRAIN POINT — ${_bpInstrumentType === "sim" ? "SIMULATION" : "PMM-1 LIVE"} · Single-Phase Mode`);
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

  if (_bpSelectedDevices.length === 0) {
    body
      .append("div")
      .text("NO DEVICES SELECTED.")
      .style("padding", "20px")
      .style("text-align", "center");
    return;
  }

  const node =
    (currentData && currentData.nodes) && currentData.nodes.find((n) => n.id === _bpTargetDeviceId) ||
    (currentData && currentData.nodes) && currentData.nodes.find((n) => n.id === _bpSelectedDevices[0]);
  _bpTargetDeviceId = node.id;
  const isNeutralPhase = _bpTargetPhase === "N";
  const effectiveChan2 = isNeutralPhase
    ? _bpChan2 // neutral: don't auto-switch, user physically moves probe
    : _pmmChan2ForPhase(_bpChan2, _bpTargetPhase);

  // ── Top controls ──────────────────────────────────────────────────────────
  const controls = body
    .append("div")
    .style("display", "flex")
    .style("gap", "16px")
    .style("margin-bottom", "12px")
    .style("background", "#111")
    .style("padding", "10px")
    .style("border-radius", "4px");

  const devGrp = controls.append("div").style("flex", 1);
  devGrp
    .append("label")
    .text("TARGET DEVICE")
    .style("font-size", "9px")
    .style("color", "#888")
    .style("display", "block");
  const devSel = devGrp
    .append("select")
    .style("width", "100%")
    .style("background", "#111")
    .style("color", "#eee")
    .style("border", "1px solid #444")
    .on("change", function () {
      _bpTargetDeviceId = this.value;
      _bpRenderPMMStep5();
    });
  _bpSelectedDevices.forEach((id) => {
    devSel
      .append("option")
      .attr("value", id)
      .text(id)
      .property("selected", _bpTargetDeviceId === id);
  });

  const phGrp = controls.append("div").style("width", "260px");
  phGrp
    .append("label")
    .text("ACTIVE PHASE")
    .style("font-size", "9px")
    .style("color", "#888")
    .style("display", "block");
  const phRow = phGrp
    .append("div")
    .style("display", "flex")
    .style("gap", "5px")
    .style("margin-top", "2px");
  const showsI = _deviceShowsCurrent(node.type);
  const needsN = showsI; // neutral always available for current devices
  (needsN ? ["A", "B", "C", "N"] : ["A", "B", "C"]).forEach((p) => {
    const isN = p === "N";
    phRow
      .append("button")
      .text(p)
      .style("flex", 1)
      .style("padding", "4px")
      .style(
        "background",
        _bpTargetPhase === p ? (isN ? "#a0a000" : "#0f0") : "#333",
      )
      .style("color", _bpTargetPhase === p ? "#000" : isN ? "#aa0" : "#eee")
      .style("border", isN ? "1px solid #660" : "none")
      .style("border-radius", "2px")
      .on("click", () => {
        _bpTargetPhase = p;
        _bpRenderPMMStep5();
      });
  });

  // ── Main panel ────────────────────────────────────────────────────────────
  const main = body
    .append("div")
    .style("display", "grid")
    .style("grid-template-columns", "280px 1fr")
    .style("gap", "14px");

  // Left — channel info + last reading
  const left = main
    .append("div")
    .style("background", "#000")
    .style("border", "1px solid #030")
    .style("padding", "14px")
    .style("font-size", "10px");

  left
    .append("div")
    .text(_bpInstrumentType === "sim" ? "SIMULATION FEED" : "PMM-1 LIVE FEED")
    .style("color", "#0a0")
    .style("font-size", "9px")
    .style("letter-spacing", "1px")
    .style("margin-bottom", "10px");

  const chanLabel = PMM_SOURCES[_bpChan1]?.l || _bpChan1;
  const measLabel = PMM_SOURCES[effectiveChan2]?.l || effectiveChan2;
  left
    .append("div")
    .html(
      `<span style="color:#555;">CHAN 1 (REF):</span> <span style="color:#3af;">${chanLabel}</span>`,
    )
    .style("margin-bottom", "4px");
  left
    .append("div")
    .html(
      `<span style="color:#555;">CHAN 2 (MEAS):</span> <span style="color:#0f0;">${measLabel}</span>`,
    )
    .style("margin-bottom", "12px");

  if (isNeutralPhase) {
    left
      .append("div")
      .style("background", "#0a0a00")
      .style("border", "1px solid #440")
      .style("padding", "8px")
      .style("color", "#aa0")
      .style("font-size", "9px")
      .style("margin-bottom", "10px")
      .text(
        "RECONNECT CURRENT PROBE TO NEUTRAL TERMINAL (N), KEEP ON CURRENT CHANNEL",
      );
  }

  const reading = _pmmLastReading;
  if (reading && reading.ok) {
    left
      .append("div")
      .style("margin-top", "8px")
      .html(
        `<div style="font-size:28px;color:#0f0;">${reading.chan2.toFixed(4)}<span style="font-size:10px;color:#555;"> ${showsI ? "A" : "V"}</span></div>` +
          `<div style="font-size:18px;color:#0f0;">∠ ${_fmtAngle(reading.phase)}</div>`,
      );
    left
      .append("div")
      .style("margin-top", "10px")
      .style("border-top", "1px solid #111")
      .style("padding-top", "8px")
      .html(
        `<div style="color:#444;font-size:9px;">CHAN 1 REF: ${reading.chan1.toFixed(4)}</div>` +
          `<div style="color:#444;font-size:9px;">WATTS: ${reading.watts.toFixed(3)} W</div>` +
          `<div style="color:#444;font-size:9px;">VARS: ${reading.vars.toFixed(3)} var</div>` +
          `<div style="color:#444;font-size:9px;">FREQ: ${reading.freq.toFixed(2)} Hz</div>`,
      );
  } else if (reading && !reading.ok) {
    left
      .append("div")
      .style("color", "#f44")
      .style("font-size", "9px")
      .style("margin-top", "8px")
      .text("⚠ " + (reading.error || "Query failed"));
  } else {
    left
      .append("div")
      .style("color", "#333")
      .style("font-size", "9px")
      .style("margin-top", "8px")
      .text("Press QUERY PMM to read.");
  }

  // Right — query + log interface
  const right = main
    .append("div")
    .style("background", "#000")
    .style("border", "2px solid #111")
    .style("border-radius", "6px")
    .style("padding", "20px")
    .style("position", "relative");

  right
    .append("div")
    .style("position", "absolute")
    .style("top", "6px")
    .style("right", "10px")
    .style("font-size", "9px")
    .style("color", "#050")
    .text((_bpInstrumentType === "sim" ? "SIM" : "PMM-1") + " · m1 · SINGLE PHASE");

  right
    .append("div")
    .text(
      `INSTRUMENT: ${node.id} — ${isNeutralPhase ? "NEUTRAL" : "PHASE " + _bpTargetPhase}`,
    )
    .style("font-size", "12px")
    .style("color", "#0a0")
    .style("margin-bottom", "16px");

  // QUERY button
  const queryBtn = right
    .append("button")
    .text(_bpInstrumentType === "sim" ? "▶ QUERY SIMULATOR" : "▶ QUERY PMM-1")
    .style("width", "100%")
    .style("padding", "14px")
    .style("background", "#020a02")
    .style("color", "#0f0")
    .style("border", "2px solid #0a0")
    .style("cursor", "pointer")
    .style("font-size", "13px")
    .style("font-weight", "bold")
    .style("letter-spacing", "2px")
    .style("margin-bottom", "14px")
    .on("click", () => {
      queryBtn.text("QUERYING...").property("disabled", true);
      // Reconfigure channels if phase changed
      fetch("/api/pmm/configure", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ chan1: _bpChan1, chan2: effectiveChan2 }),
      })
        .then(() => fetch("/api/pmm/query"))
        .then((r) => r.json())
        .then((res) => {
          _pmmLastReading = res;
          _bpRenderPMMStep5();
        })
        .catch((e) => {
          _pmmLastReading = { ok: false, error: String(e) };
          _bpRenderPMMStep5();
        });
    });

  // Log section — shows pre-filled values from last reading
  const mag = reading?.ok ? reading.chan2 : null;
  const ang = reading?.ok ? reading.phase : null;

  const measBox = right
    .append("div")
    .style("border", "2px solid #1a1a1a")
    .style("padding", "16px")
    .style("background", "#050505");
  measBox
    .append("div")
    .text("VALUES TO LOG")
    .style("font-size", "9px")
    .style("color", "#555")
    .style("margin-bottom", "10px");

  const r1 = measBox
    .append("div")
    .style("display", "flex")
    .style("align-items", "center")
    .style("gap", "20px")
    .style("margin-bottom", "12px");
  r1.append("span")
    .text("MAG")
    .style("font-size", "13px")
    .style("color", "#0a0")
    .style("font-weight", "bold")
    .style("width", "44px");
  r1.append("input")
    .attr("type", "number")
    .attr("id", "bp-mag-in")
    .property("value", mag !== null ? mag.toFixed(5) : "")
    .style("background", "#111")
    .style("border", "2px solid #040")
    .style("color", "#0f0")
    .style("font-size", "36px")
    .style("width", "220px")
    .style("padding", "8px")
    .style("text-align", "center")
    .style("font-family", "'Courier New',monospace");
  r1.append("span")
    .text(showsI ? "A" : "V")
    .style("color", "#0a0")
    .style("font-size", "20px");

  const r2 = measBox
    .append("div")
    .style("display", "flex")
    .style("align-items", "center")
    .style("gap", "20px");
  r2.append("span")
    .text("ANG")
    .style("font-size", "13px")
    .style("color", "#0a0")
    .style("font-weight", "bold")
    .style("width", "44px");
  r2.append("input")
    .attr("type", "number")
    .attr("id", "bp-ang-in")
    .property("value", ang !== null ? _lagAngle(ang).toFixed(2) : "")
    .style("background", "#111")
    .style("border", "2px solid #040")
    .style("color", "#0f0")
    .style("font-size", "28px")
    .style("width", "180px")
    .style("padding", "8px")
    .style("text-align", "center")
    .style("font-family", "'Courier New',monospace");
  r2.append("span").text("°").style("color", "#0a0").style("font-size", "20px");

  right
    .append("button")
    .text("ACCEPT & LOG POINT  (ENTER)")
    .style("width", "100%")
    .style("margin-top", "16px")
    .style("padding", "14px")
    .style("background", "#060")
    .style("color", "#0f0")
    .style("border", "2px solid #0a0")
    .style("cursor", "pointer")
    .style("font-weight", "bold")
    .style("font-size", "13px")
    .style("text-transform", "uppercase")
    .style("letter-spacing", "2px")
    .on("click", _bpLogCurrentPoint);

  setTimeout(() => {
    const el = document.getElementById("bp-mag-in");
    if (el) el.focus();
  }, 100);

  // ── Footer ────────────────────────────────────────────────────────────────
  const footer = d3.select("#brain-point-footer").html("");
  footer
    .append("button")
    .attr("class", "wiz-secondary")
    .text("BACK TO SELECTION")
    .on("click", _bpRenderStep4);
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
      _bpRenderPMMStep5();
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
    .text("EXIT BRAIN POINT")
    .on("click", () => {
      _bpInSIMode = false;
      d3.select("#brain-point-module").style("display", "none");
      d3.select("#status-bar")
        .style("background", "#111")
        .style("color", "#0f0")
        .text("Navigation System Standby.");
      refreshData();
    });

  // Keyboard: Enter → log, arrows → navigate
  d3.select("body").on("keydown.bp", (e) => {
    if (d3.select("#brain-point-module").style("display") === "none") return;
    if (e.key === "Enter") {
      _bpLogCurrentPoint();
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
}

function _bpRenderStep5() {
  d3.select("#status-bar")
    .style("background", "#040")
    .style("color", "#0f0")
    .text("BRAIN POINT Module Active. Routing current through terminal blocks...");

  d3.select("#brain-point-module")
    .style("width", "98vw")
    .style("height", "96vh")
    .style("top", "2vh")
    .style("left", "1vw")
    .style("transform", "none");

  const body = d3
    .select("#brain-point-body")
    .html("")
    .style("height", "calc(100% - 120px)"); // Allow body to fill most of the space

  // Add keyboard listener for this step
  d3.select("body").on("keydown.bp", (e) => {
    if (d3.select("#brain-point-module").style("display") === "none") return;

    if (e.key === "Enter") {
      const magIn = document.getElementById("bp-mag-in");
      if (magIn && document.activeElement === magIn) {
        // If focusing magnitude, move to angle
        const angIn = document.getElementById("bp-ang-in");
        if (angIn) angIn.focus();
        e.preventDefault();
      } else {
        // Log if on angle or button
        _bpLogCurrentPoint();
        e.preventDefault();
      }
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
    (currentData && currentData.nodes) && currentData.nodes.find((n) => n.id === _bpTargetDeviceId) ||
    (currentData && currentData.nodes) && currentData.nodes.find((n) => n.id === _bpSelectedDevices[0]);
  _bpTargetDeviceId = node.id;
  const refVT = (currentData && currentData.nodes) && currentData.nodes.find((n) => n.id === _bpRefVTId);

  const expectedType = _bpDeviceExpectedType(node.type);

  // TOP CONTROLS: Device and Phase Selection
  const controls = body
    .append("div")
    .style("display", "flex")
    .style("gap", "20px")
    .style("margin-bottom", "15px")
    .style("background", "#222")
    .style("padding", "10px")
    .style("border-radius", "4px");

  const devGroup = controls.append("div").style("flex", 1);
  devGroup
    .append("label")
    .text("TARGET DEVICE")
    .style("font-size", "9px")
    .style("color", "#888")
    .style("display", "block");
  const devSel = devGroup
    .append("select")
    .style("width", "100%")
    .style("background", "#111")
    .style("color", "#eee")
    .style("border", "1px solid #444")
    .on("change", function () {
      _bpTargetDeviceId = this.value;
      _bpRenderStep5();
    });
  _bpSelectedDevices.forEach((id) => {
    devSel
      .append("option")
      .attr("value", id)
      .text(id)
      .property("selected", _bpTargetDeviceId === id);
  });

  const phaseGroup = controls.append("div").style("width", "240px");
  phaseGroup
    .append("label")
    .text("ACTIVE PHASE")
    .style("font-size", "9px")
    .style("color", "#888")
    .style("display", "block");
  const phaseRow = phaseGroup
    .append("div")
    .style("display", "flex")
    .style("gap", "5px")
    .style("margin-top", "2px");
  const showsI = _deviceShowsCurrent(node.type);
  const needsNeutral =
    showsI && (_bpSelectedMode === "m3y" || _bpSelectedMode === "m1");
  const phaseList = needsNeutral ? ["A", "B", "C", "N"] : ["A", "B", "C"];
  phaseList.forEach((p) => {
    const isNeutral = p === "N";
    phaseRow
      .append("button")
      .text(p)
      .style("flex", 1)
      .style("padding", "4px")
      .style(
        "background",
        _bpTargetPhase === p ? (isNeutral ? "#a0a000" : "#0f0") : "#333",
      )
      .style(
        "color",
        _bpTargetPhase === p ? "#000" : isNeutral ? "#aa0" : "#eee",
      )
      .style("border", isNeutral ? "1px solid #660" : "none")
      .style("border-radius", "2px")
      .on("click", () => {
        _bpTargetPhase = p;
        _bpRenderStep5();
      });
  });

  const main = body
    .append("div")
    .style("display", "grid")
    .style("grid-template-columns", "260px 1fr")
    .style("gap", "15px");

  // Left Side: Reference Monitor + Target Predicted
  const refCol = main
    .append("div")
    .style("background", "#111")
    .style("padding", "15px")
    .style("border", "1px solid #444")
    .style("border-radius", "4px");

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
    refCol
      .append("div")
      .text(refVT.id)
      .style("color", "#3af")
      .style("font-weight", "bold")
      .style("font-size", "11px");
    refCol
      .append("div")
      .text(`PHASE ${_bpTargetPhase}`)
      .style("font-size", "9px")
      .style("color", "#555");
    refCol
      .append("div")
      .style("margin-top", "8px")
      .html(
        `<div style="font-size:22px;color:#3af;">${vRef.toFixed(1)} <span style="font-size:9px;color:#555;">V</span></div>` +
          `<div style="font-size:15px;color:#3af;">∠ ${_fmtAngle(aRef)}</div>`,
      );
  } else {
    refCol
      .append("div")
      .text("NO REF VT SELECTED")
      .style("color", "#555")
      .style("font-size", "10px");
  }

  // Target device predicted values (use device-type-aware key)
  const predMagKey = _predKey(node, _bpTargetPhase, expectedType);
  const predAngKey = _predKey(
    node,
    _bpTargetPhase,
    expectedType === "current" ? "i-angle" : "v-angle",
  );
  const predMag = node.summary?.[predMagKey];
  const predAng = node.summary?.[predAngKey];
  refCol
    .append("div")
    .style("margin-top", "14px")
    .style("padding-top", "10px")
    .style("border-top", "1px solid #222");
  refCol
    .append("div")
    .text("TARGET DEVICE PREDICTED")
    .style("font-size", "9px")
    .style("color", "#888")
    .style("margin-bottom", "6px");
  refCol
    .append("div")
    .text(node.id)
    .style("color", "#fa0")
    .style("font-size", "10px")
    .style("font-weight", "bold");
  if (predMag !== undefined && predMag !== null) {
    refCol
      .append("div")
      .style("margin-top", "6px")
      .html(
        `<div style="font-size:20px;color:#fa0;">${predMag.toFixed(2)} <span style="font-size:9px;color:#555;">${expectedType === "current" ? "A" : "V"}</span></div>` +
          `<div style="font-size:14px;color:#fa0;">∠ ${_fmtAngle(predAng ?? 0)}</div>`,
      );
  } else {
    refCol
      .append("div")
      .text("No prediction available")
      .style("color", "#333")
      .style("font-size", "9px")
      .style("margin-top", "6px");
  }

  // Right Side: PMM Face
  const plugDisplay = main
    .append("div")
    .style("background", "#000")
    .style("padding", "20px")
    .style("border", "2px solid #333")
    .style("border-radius", "8px")
    .style("position", "relative");
  plugDisplay
    .append("div")
    .style("position", "absolute")
    .style("top", "5px")
    .style("right", "10px")
    .style("font-size", "9px")
    .style("color", "#050")
    .text("BRAIN POINT MODE: " + _bpSelectedMode.toUpperCase());

  {
    // Channel type indicator banner
    const isVoltage = expectedType === "voltage";
    plugDisplay
      .append("div")
      .style("margin-bottom", "14px")
      .style("padding", "5px 10px")
      .style("border-radius", "3px")
      .style("font-size", "9px")
      .style("text-align", "center")
      .style("letter-spacing", "1px")
      .style("border", `1px solid ${isVoltage ? "#226" : "#060"}`)
      .style("color", isVoltage ? "#66f" : "#0f0")
      .style("background", isVoltage ? "#000011" : "#001100")
      .text(
        `CHAN 2: ${isVoltage ? "VOLTAGE (V) INPUT" : "CURRENT (A) INPUT"}` +
          (_bpLastMeasType === null ? "  —  FIRST READING: CONNECT NOW" : ""),
      );

    const qty = expectedType === "current" ? "Current" : "Voltage";
    const unit = expectedType === "current" ? "A" : "V";
    const isNeutralPhase = _bpTargetPhase === "N";
    const storeKey = isNeutralPhase
      ? "Neutral Current"
      : `Phase ${_bpTargetPhase} ${qty}`;
    const angKey = isNeutralPhase
      ? "Neutral I-Angle"
      : `Phase ${_bpTargetPhase} ${qty === "Voltage" ? "V-Angle" : "I-Angle"}`;
    const phaseLabel = isNeutralPhase ? "NEUTRAL" : `PHASE ${_bpTargetPhase}`;

    const measBox = plugDisplay
      .append("div")
      .style("border", isNeutralPhase ? "2px solid #660" : "2px solid #1a1a1a")
      .style("padding", "20px")
      .style("background", isNeutralPhase ? "#0a0a00" : "#050505");
    measBox
      .append("div")
      .text(`MEASUREMENT: ${node.id} — ${phaseLabel}`)
      .style("font-size", "12px")
      .style("color", isNeutralPhase ? "#aa0" : "#0a0")
      .style("margin-bottom", "16px");
    if (isNeutralPhase) {
      measBox
        .append("div")
        .text("CONNECT PROBE TO NEUTRAL TERMINAL (N)")
        .style("font-size", "9px")
        .style("color", "#660")
        .style("margin-bottom", "12px")
        .style("letter-spacing", "1px");
    }

    const valRow = measBox
      .append("div")
      .style("display", "flex")
      .style("align-items", "center")
      .style("gap", "25px")
      .style("padding", "5px 0");
    valRow
      .append("span")
      .text("MAG")
      .style("font-size", "14px")
      .style("color", "#0a0")
      .style("font-weight", "bold")
      .style("width", "50px");
    valRow
      .append("input")
      .attr("type", "number")
      .attr("id", "bp-mag-in")
      .property("value", node.summary?.[`Manual ${storeKey}`] || "")
      .style("background", "#111")
      .style("border", "2px solid #040")
      .style("color", "#0f0")
      .style("font-size", "48px")
      .style("width", "250px")
      .style("padding", "10px")
      .style("text-align", "center")
      .style("font-family", "'Courier New', monospace")
      .on("focus", function () {
        d3.select(this)
          .style("border-color", "#0f0")
          .style("background", "#000");
      })
      .on("blur", function () {
        d3.select(this)
          .style("border-color", "#040")
          .style("background", "#111");
      });
    valRow
      .append("span")
      .text(unit)
      .style("color", "#0a0")
      .style("font-size", "24px");

    const angRow = measBox
      .append("div")
      .style("display", "flex")
      .style("align-items", "center")
      .style("gap", "25px")
      .style("margin-top", "20px");
    angRow
      .append("span")
      .text("ANG")
      .style("font-size", "14px")
      .style("color", "#0a0")
      .style("font-weight", "bold")
      .style("width", "50px");
    angRow
      .append("input")
      .attr("type", "number")
      .attr("id", "bp-ang-in")
      .property("value", node.summary?.[`Manual ${angKey}`] || "")
      .style("background", "#111")
      .style("border", "2px solid #040")
      .style("color", "#0f0")
      .style("font-size", "36px")
      .style("width", "200px")
      .style("padding", "10px")
      .style("text-align", "center")
      .style("font-family", "'Courier New', monospace")
      .on("focus", function () {
        d3.select(this)
          .style("border-color", "#0f0")
          .style("background", "#000");
      })
      .on("blur", function () {
        d3.select(this)
          .style("border-color", "#040")
          .style("background", "#111");
      });
    angRow
      .append("span")
      .text("°")
      .style("color", "#0a0")
      .style("font-size", "24px");

    plugDisplay
      .append("div")
      .style("margin-top", "15px")
      .style("color", "#444")
      .style("font-size", "10px")
      .style("text-align", "center")
      .html(
        "ENTER: LOG & NEXT  ·  ARROWS: NAVIGATE  ·  MAG: " +
          unit +
          "  ANG: DEG",
      );

    plugDisplay
      .append("button")
      .text("ACCEPT & LOG POINT (ENTER)")
      .style("width", "100%")
      .style("margin-top", "25px")
      .style("padding", "15px")
      .style("background", "#060")
      .style("color", "#0f0")
      .style("border", "2px solid #0a0")
      .style("cursor", "pointer")
      .style("font-weight", "bold")
      .style("font-size", "14px")
      .style("text-transform", "uppercase")
      .style("letter-spacing", "2px")
      .on("click", _bpLogCurrentPoint);

    setTimeout(() => {
      const el = document.getElementById("bp-mag-in");
      if (el) el.focus();
    }, 100);
  } // end channel measurement block

  const footer = d3.select("#brain-point-footer").html("");
  footer
    .append("button")
    .attr("class", "wiz-secondary")
    .text("BACK TO SELECTION")
    .on("click", _bpRenderStep4);
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
      _bpRenderStep5();
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
    .text("EXIT BRAIN POINT MODULE")
    .on("click", () => {
      _bpInSIMode = false;
      d3.select("#brain-point-module").style("display", "none");
      d3.select("body").on("keydown.bp", null); // Remove listener
      d3.select("#status-bar")
        .style("background", "#111")
        .style("color", "#0f0")
        .text("Navigation System Standby.");
      refreshData();
    });
}

function _bpLogCurrentPoint() {
  const node = (currentData && currentData.nodes) && currentData.nodes.find((n) => n.id === _bpTargetDeviceId);
  if (!node) return;
  const expectedType = _bpDeviceExpectedType(node.type);
  const qty = expectedType === "current" ? "Current" : "Voltage";
  const isNeutralPhase = _bpTargetPhase === "N";
  const storeKey = isNeutralPhase
    ? "Neutral Current"
    : `Phase ${_bpTargetPhase} ${qty}`;
  const angKey = isNeutralPhase
    ? "Neutral I-Angle"
    : `Phase ${_bpTargetPhase} ${qty === "Voltage" ? "V-Angle" : "I-Angle"}`;

  const mag = parseFloat(document.getElementById("bp-mag-in").value);
  const ang = parseFloat(document.getElementById("bp-ang-in").value);
  const measurements = {};
  if (!isNaN(mag)) measurements[storeKey] = mag;
  if (!isNaN(ang)) measurements[angKey] = ang;

  // Track locally for balance check
  if (!_bpSessionMeasurements[node.id])
    _bpSessionMeasurements[node.id] = {};
  Object.assign(_bpSessionMeasurements[node.id], measurements);

  reconfigureAPI(node.id, "record_measurement", { measurements }).then(() => {
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
    (_bpInstrumentType === "pmm1" || _bpInstrumentType === "sim") ? _bpRenderPMMStep5() : _bpRenderStep5();
  } else if (isMultiAnalog && _bpDeviceMeasStep === "voltage") {
    // Done with voltage pass of multi-analog — switch to current
    _bpDeviceMeasStep = "current";
    _bpTargetPhase = "A";
    _bpShowChannelConfig("current", "voltage", () => {
      (_bpInstrumentType === "pmm1" || _bpInstrumentType === "sim") ? _bpRenderPMMStep5() : _bpRenderStep5();
    });
  } else {
    // At phase C — go to N for wye current devices, otherwise next device
    const inCurrentPass = _bpDeviceMeasStep === "current" || (!isMultiAnalog && showsI);
    if (wantsNeutral && inCurrentPass) {
      _bpTargetPhase = "N";
      (_bpInstrumentType === "pmm1" || _bpInstrumentType === "sim") ? _bpRenderPMMStep5() : _bpRenderStep5();
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
    (_bpInstrumentType === "pmm1" || _bpInstrumentType === "sim") ? _bpRenderPMMStep5() : _bpRenderStep5();
  }
}

function _bpMoveToNextDevice() {
  const idx = _bpSelectedDevices.indexOf(_bpTargetDeviceId);
  _pmmLastReading = null;
  _bpDeviceMeasStep = null;

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
        (_bpInstrumentType === "pmm1" || _bpInstrumentType === "sim") ? _bpRenderPMMStep5() : _bpRenderStep5();
      });
    } else {
      _bpApplyChanConfig(nextMeasType);
      (_bpInstrumentType === "pmm1" || _bpInstrumentType === "sim") ? _bpRenderPMMStep5() : _bpRenderStep5();
    }
  } else {
    (_bpInstrumentType === "pmm1" || _bpInstrumentType === "sim") ? _bpRenderPMMStep5() : _bpRenderStep5();
  }
}

function _bpMoveToPrevDevice() {
  const idx = _bpSelectedDevices.indexOf(_bpTargetDeviceId);
  _pmmLastReading = null;
  if (idx > 0) {
    _bpTargetDeviceId = _bpSelectedDevices[idx - 1];
    _bpTargetPhase = "A";
  }
  (_bpInstrumentType === "pmm1" || _bpInstrumentType === "sim") ? _bpRenderPMMStep5() : _bpRenderStep5();
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

function showHistoryModal() {
  d3.select("#history-modal").style("display", "flex");
  _renderHistoryTab("snapshots");
}

function _fmtEpoch(epoch) {
  const d = new Date(epoch * 1000);
  return d.toLocaleString();
}

function _fmtEpochShort(epoch) {
  const d = new Date(epoch * 1000);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" })
    + " " + d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

function _dayBucket(epoch) {
  const d = new Date(epoch * 1000);
  const now = new Date();
  const diffMs = now - d;
  const diffDays = diffMs / 86400000;
  if (diffDays < 1) return "TODAY";
  if (diffDays < 2) return "YESTERDAY";
  if (diffDays < 7) return "THIS WEEK";
  return "OLDER";
}

let _historyTab = "snapshots";

function _renderHistoryTab(tab) {
  _historyTab = tab;

  // Tab bar in body header
  const body = d3.select("#history-body").html("");

  const tabBar = body.append("div")
    .style("display", "flex").style("gap", "0").style("border-bottom", "1px solid #1a1a1a")
    .style("margin-bottom", "0").style("flex-shrink", "0");

  [["snapshots", "SNAPSHOTS"], ["sessions", "SESSIONS"]].forEach(([key, label]) => {
    const active = key === tab;
    tabBar.append("button")
      .text(label)
      .style("background", active ? "#001a00" : "#050505")
      .style("border", "none").style("border-bottom", active ? "2px solid #0f0" : "2px solid transparent")
      .style("color", active ? "#0f0" : "#555")
      .style("font-family", "inherit").style("font-size", "10px")
      .style("padding", "8px 18px").style("cursor", "pointer")
      .style("letter-spacing", "1px")
      .on("click", () => _renderHistoryTab(key));
  });

  const contentArea = body.append("div").style("overflow-y", "auto").style("flex", "1");

  if (tab === "snapshots") {
    _renderSnapshotsTab(contentArea);
  } else {
    _renderSessionsTab(contentArea);
  }

  // Footer
  const footer = d3.select("#history-footer").html("");
  if (tab === "snapshots") {
    footer.append("button").attr("class", "wiz-save").text("+ TAKE SNAPSHOT")
      .on("click", () => {
        const now = new Date();
        const dateStr = now.getFullYear() + String(now.getMonth() + 1).padStart(2, "0") + String(now.getDate()).padStart(2, "0");
        const station = currentData?.site?.station || "STN";
        showInputDialog("SNAPSHOT LABEL", dateStr + "-" + station, (label) => {
          if (!label) return;
          createSnapshot(label).then(() => _renderHistoryTab("snapshots"));
        });
      });
  }
  footer.append("div").style("flex", "1");
  footer.append("button").attr("class", "wiz-secondary").text("CLOSE")
    .on("click", () => d3.select("#history-modal").style("display", "none"));
}

function _renderSnapshotsTab(container) {
  container.html('<div style="color:#555; padding:12px; font-size:10px;">Loading...</div>');
  fetchSnapshots().then((resp) => {
    container.html("");
    const snaps = (resp.snapshots || []).slice().reverse(); // newest first
    if (snaps.length === 0) {
      container.append("div").text("No snapshots yet.").style("color", "#444").style("padding", "16px").style("font-size", "10px");
      return;
    }

    // Group by day bucket
    const groups = {};
    const order = [];
    snaps.forEach(s => {
      const b = _dayBucket(s.epoch);
      if (!groups[b]) { groups[b] = []; order.push(b); }
      groups[b].push(s);
    });

    order.forEach(bucket => {
      container.append("div")
        .style("font-size", "9px").style("color", "#555").style("letter-spacing", "1px")
        .style("padding", "8px 14px 4px").style("background", "#070707")
        .style("border-bottom", "1px solid #111")
        .text(bucket);

      groups[bucket].forEach(s => {
        const row = container.append("div")
          .style("display", "flex").style("align-items", "center")
          .style("padding", "7px 14px").style("border-bottom", "1px solid #0d0d0d")
          .style("gap", "8px");

        row.append("div")
          .style("font-size", "10px").style("color", "#aaa").style("flex", "1")
          .style("min-width", "0")
          .html(`<span style="color:#eee;">${s.label || "Unnamed"}</span> <span style="color:#444; font-size:9px;">${_fmtEpochShort(s.epoch)}</span>`);

        row.append("button").attr("class", "eng-btn")
          .style("white-space", "nowrap").style("padding", "3px 10px").style("font-size", "9px")
          .text("COMPARE")
          .on("click", () => enterCompareMode(s.id, s.label));

        row.append("button").attr("class", "wiz-secondary")
          .style("white-space", "nowrap").style("padding", "3px 8px").style("font-size", "9px").style("color", "#555")
          .text("DELETE")
          .on("click", () => {
            if (!confirm(`Delete "${s.label}"?`)) return;
            deleteSnapshot(s.id).then(() => _renderHistoryTab("snapshots"));
          });
      });
    });
  });
}

function _renderSessionsTab(container) {
  container.html('<div style="color:#555; padding:12px; font-size:10px;">Loading...</div>');
  fetchSessions().then((resp) => {
    container.html("");
    const sessions = (resp.sessions || []).slice().reverse();
    if (sessions.length === 0) {
      container.append("div").text("No sessions recorded.").style("color", "#444").style("padding", "16px").style("font-size", "10px");
      return;
    }

    sessions.forEach(s => {
      const card = container.append("div")
        .style("border-bottom", "1px solid #0d0d0d");

      const header = card.append("div")
        .style("display", "flex").style("align-items", "center")
        .style("padding", "7px 14px").style("gap", "8px").style("cursor", "pointer");

      const techLabel = s.technician || "—";
      const testLabel = s.test_name || (s.test_id ? `Test #${s.test_id.slice(0, 6)}` : "No test");
      const epochLabel = s.epoch ? _fmtEpochShort(s.epoch) : "";
      const countLabel = s.reading_count != null ? `${s.reading_count} rdg` : "";

      header.append("div").style("flex", "1").style("min-width", "0")
        .html(`<span style="color:#eee; font-size:10px;">${techLabel}</span> <span style="color:#555; font-size:9px;">· ${testLabel} · ${epochLabel}</span>`)
        .append("span").style("color", "#444").style("font-size", "9px").style("margin-left", "6px").text(countLabel);

      header.append("span").style("font-size", "9px").style("color", "#333").text("▼");

      header.append("button").attr("class", "wiz-secondary")
        .style("padding", "2px 8px").style("font-size", "9px").style("color", "#555")
        .text("DELETE")
        .on("click", (e) => {
          e.stopPropagation();
          if (!confirm(`Delete this session?`)) return;
          deleteSession(s.id).then(() => _renderHistoryTab("sessions"));
        });

      // Detail panel (hidden by default)
      const detail = card.append("div").attr("class", "session-detail")
        .style("display", "none")
        .style("background", "#080808")
        .style("padding", "8px 14px 10px 24px");

      detail.append("div").style("font-size", "9px").style("color", "#555").style("margin-bottom", "6px")
        .text(`Instrument: ${s.instrument || "manual"}`);

      const measContainer = detail.append("div");
      measContainer.append("div").style("font-size", "9px").style("color", "#444").text("Loading measurements...");

      // Lazy-load measurements on first expand
      let measLoaded = false;
      header.on("click", function() {
        const det = card.select(".session-detail");
        const isVisible = det.style("display") !== "none";
        det.style("display", isVisible ? "none" : "block");
        if (!isVisible && !measLoaded) {
          measLoaded = true;
          fetchSessionMeasurements(s.id).then(resp => {
            measContainer.html("");
            const byDevice = resp.by_device || {};
            const devices = Object.keys(byDevice);
            if (devices.length === 0) {
              measContainer.append("div").style("color", "#444").style("font-size", "9px").text("No measurements.");
              return;
            }
            devices.forEach(devId => {
              measContainer.append("div")
                .style("font-size", "9px").style("color", "#888").style("margin-top", "5px")
                .text(devId);
              const entries = byDevice[devId] || [];
              entries.slice(0, 6).forEach(m => {
                measContainer.append("div")
                  .style("font-size", "9px").style("color", "#555").style("padding-left", "10px")
                  .text(`${m.key}: ${typeof m.value === "number" ? m.value.toFixed(3) : m.value}`);
              });
              if (entries.length > 6) {
                measContainer.append("div")
                  .style("font-size", "9px").style("color", "#333").style("padding-left", "10px")
                  .text(`+ ${entries.length - 6} more`);
              }
            });
          });
        }
      });
    });
  });
}

function enterCompareMode(id, label) {
  loadSnapshotData(id).then((data) => {
    compareData = { filename: label || String(id), nodes: data.nodes };
    d3.select("#history-modal").style("display", "none");
    refreshData();
  });
}

function exitCompareMode() {
  compareData = null;
  refreshData();
}

// Keep renderHistoryBody as an alias for backwards compat
function renderHistoryBody() { _renderHistoryTab(_historyTab); }

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
    .on("click", _bpRenderStep5);

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

      _bpRenderStep5();
    });
}

// ── Config modal drag support ──────────────────────────────────────────────

function _resetConfigModalPos() {
  const m = document.getElementById("config-modal");
  if (!m) return;
  m.style.transform = "translate(-50%, -50%)";
  m.style.top = "50%";
  m.style.left = "50%";
  _configModalDragged = false;
}


function _initMinimapDrag() {
  const container = document.getElementById("minimap-container");
  const header = document.getElementById("minimap-header");
  if (!container || !header || header._dragInit) return;
  header._dragInit = true;
  header.style.cursor = "move";
  let p1 = 0, p2 = 0, p3 = 0, p4 = 0;
  let dragged = false;

  header.onmousedown = (e) => {
    if (e.target.id === "minimap-toggle" || e.target.tagName === "BUTTON") return;
    e.preventDefault();
    if (!dragged) {
      const r = container.getBoundingClientRect();
      container.style.bottom = "auto";
      container.style.left = r.left + "px";
      container.style.top = r.top + "px";
      dragged = true;
    }
    p3 = e.clientX; p4 = e.clientY;
    document.onmouseup = () => { document.onmouseup = null; document.onmousemove = null; };
    document.onmousemove = (e) => {
      e.preventDefault();
      p1 = p3 - e.clientX; p2 = p4 - e.clientY;
      p3 = e.clientX; p4 = e.clientY;
      const newTop = Math.max(0, Math.min(container.offsetTop - p2, window.innerHeight - 40));
      const newLeft = Math.max(0, Math.min(container.offsetLeft - p1, window.innerWidth - 40));
      container.style.top = newTop + "px";
      container.style.left = newLeft + "px";
    };
  };
}
function _initConfigModalDrag() {
  const modal = document.getElementById("config-modal");
  const header = document.getElementById("config-modal-drag");
  if (!modal || !header || header._dragInit) return;
  header._dragInit = true;
  let p1 = 0, p2 = 0, p3 = 0, p4 = 0;
  header.onmousedown = (e) => {
    if (e.target.classList.contains("modal-close")) return;
    e.preventDefault();
    if (!_configModalDragged) {
      const r = modal.getBoundingClientRect();
      modal.style.transform = "none";
      modal.style.top = r.top + "px";
      modal.style.left = r.left + "px";
      _configModalDragged = true;
    }
    p3 = e.clientX; p4 = e.clientY;
    document.onmouseup = () => { document.onmouseup = null; document.onmousemove = null; };
    document.onmousemove = (e) => {
      e.preventDefault();
      p1 = p3 - e.clientX; p2 = p4 - e.clientY;
      p3 = e.clientX; p4 = e.clientY;
      const newTop = Math.max(0, Math.min(modal.offsetTop - p2, window.innerHeight - 50));
      const newLeft = Math.max(0, Math.min(modal.offsetLeft - p1, window.innerWidth - 80));
      modal.style.top = newTop + "px";
      modal.style.left = newLeft + "px";
    };
  };
}

// ── All Devices panel ──────────────────────────────────────────────────────

function toggleAllDevices() {
  const panel = document.getElementById("all-devices-panel");
  if (panel.classList.contains("open")) {
    panel.classList.remove("open");
  } else {
    _buildAllDevicesList();
    panel.classList.add("open");
  }
}

function _buildAllDevicesList() {
  if (!currentData || !currentData.nodes) return;
  const list = document.getElementById("all-devices-list");
  const countEl = document.getElementById("adp-count");
  list.innerHTML = "";
  countEl.textContent = " (" + currentData.nodes.length + ")";

  const groups = {};
  currentData.nodes.forEach(n => {
    if (!groups[n.type]) groups[n.type] = [];
    groups[n.type].push(n);
  });

  Object.keys(groups).sort().forEach(type => {
    const hdr = document.createElement("div");
    hdr.className = "adp-group";
    hdr.textContent = type;
    list.appendChild(hdr);

    groups[type].sort((a, b) => a.id.localeCompare(b.id)).forEach(node => {
      const item = document.createElement("div");
      item.className = "adp-item";
      item.innerHTML = '<span class="adp-item-id">' + node.id + '</span>';
      item.onclick = () => {
        panToDevice(node.id);
        openWindow(node);
      };
      list.appendChild(item);
    });
  });
}

// ── Find Device ────────────────────────────────────────────────────────────

function onFindInput(val) {
  const results = document.getElementById("find-device-results");
  if (!val || !currentData) { results.style.display = "none"; return; }
  const q = val.toLowerCase();
  const matches = currentData.nodes
    .filter(n => n.id.toLowerCase().includes(q) || n.type.toLowerCase().includes(q))
    .slice(0, 14);

  if (!matches.length) { results.style.display = "none"; return; }

  results.innerHTML = matches.map(n =>
    '<div class="find-result-item" onmousedown="panToDevice(\'' +
    n.id.replace(/'/g, "\\'") + '\')">' +
    '<span>' + n.id + '</span>' +
    '<span class="find-result-type">' + n.type + '</span></div>'
  ).join("");
  results.style.display = "block";
}

function onFindKey(e) {
  if (e.key === "Escape") {
    clearFindResults();
    e.target.value = "";
  } else if (e.key === "Enter") {
    const first = document.querySelector(".find-result-item");
    if (first) first.onmousedown();
    clearFindResults();
    e.target.blur();
  }
}

function clearFindResults() {
  const r = document.getElementById("find-device-results");
  if (r) r.style.display = "none";
}

// ── Relay input polarity toggle ────────────────────────────────────────────

function toggleInputPolarity(deviceId, inputId, currentPol) {
  const dev = (currentData && currentData.nodes) && currentData.nodes.find((n) => n.id === deviceId);
  if (!dev) return;
  const polarities = Object.assign({}, dev.params?.input_polarities || {});
  polarities[inputId] = currentPol === 1 ? -1 : 1;
  reconfigureAPI(deviceId, "update_device", { properties: { input_polarities: polarities } }).then(() => refreshData());
}

// ── Init ───────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => { _initConfigModalDrag(); _initMinimapDrag(); });


function toggleRelayTrip(id, state) {
  reconfigureAPI(id, "update_device", { properties: { dc_output_state: state } }).then(() => refreshData());
}

function toggleRelayTarget(id, state) {
  reconfigureAPI(id, "update_device", { properties: { target_dropped: state } }).then(() => refreshData());
}

function showLogicDesigner(id) {
  const node = (currentData && currentData.nodes) && currentData.nodes.find(n => n.id === id);
  if (!node) return;
  const params = node.params || {};
  const settings = params.settings || { "50P1P": 5.0, "59P1P": 120.0 };
  const logic = params.logic || { "TRIP": "50P1 OR IN101", "OUT101": "50P1" };
  
  _resetConfigModalPos();
  d3.select("#config-modal").style("display", "flex");
  d3.select("#modal-title").text("LOGIC DESIGNER [" + id + "]");
  const body = d3.select("#modal-body").html("");
  
  body.append("div").attr("class", "section-title").text("ANALOG SETTINGS");
  Object.entries(settings).forEach(([key, val]) => {
    const row = body.append("div").style("display", "flex").style("gap", "4px").style("margin-bottom", "4px");
    row.append("label").style("width", "60px").style("font-size", "10px").style("color", "#888").text(key);
    row.append("input").attr("type", "number").attr("class", "l-setting").attr("data-key", key).property("value", val).style("flex", 1);
  });
  
  body.append("div").attr("class", "section-title").text("CONTROL EQUATIONS");
  Object.entries(logic).forEach(([out, eq]) => {
    const row = body.append("div").style("display", "flex").style("flex-direction", "column").style("margin-bottom", "8px");
    row.append("label").style("font-size", "9px").style("color", "#0af").text(out + " =");
    row.append("input").attr("type", "text").attr("class", "l-logic").attr("data-out", out).property("value", eq).style("width", "100%");
  });
  
  body.append("div").attr("class", "section-title").text("I/O DEFINITION");
  const ioRow = body.append("div").style("display", "flex").style("gap", "8px");
  const inCol = ioRow.append("div").style("flex", 1);
  inCol.append("label").style("font-size", "9px").style("color", "#888").text("Digital Inputs (CSV)");
  inCol.append("textarea").attr("id", "l-inputs").style("width", "100%").text((params.digital_inputs || ["IN101", "IN102"]).join(", "));
  
  const outCol = ioRow.append("div").style("flex", 1);
  outCol.append("label").style("font-size", "9px").style("color", "#888").text("Digital Outputs (CSV)");
  outCol.append("textarea").attr("id", "l-outputs").style("width", "100%").text((params.digital_outputs || ["OUT101", "OUT102"]).join(", "));

  body.append("div").style("font-size", "8px").style("color", "#555").style("margin-top", "8px")
    .text("Elements: 50P1 (I > Pickup), 59P1 (V > Pickup). Digital: use defined labels. Operators: AND, OR, NOT.");

  d3.select("#modal-save").on("click", () => {
    const newSettings = {};
    document.querySelectorAll(".l-setting").forEach(el => newSettings[el.dataset.key] = parseFloat(el.value));
    const newLogic = {};
    document.querySelectorAll(".l-logic").forEach(el => newLogic[el.dataset.out] = el.value.trim().toUpperCase());
    const newInputs = document.getElementById("l-inputs").value.split(",").map(s => s.trim().toUpperCase()).filter(Boolean);
    const newOutputs = document.getElementById("l-outputs").value.split(",").map(s => s.trim().toUpperCase()).filter(Boolean);
    
    newOutputs.forEach(out => { if (!newLogic[out]) newLogic[out] = "0"; });
    if (!newLogic["TRIP"]) newLogic["TRIP"] = "0"; 
    
    reconfigureAPI(id, "update_device", { properties: { settings: newSettings, logic: newLogic, digital_inputs: newInputs, digital_outputs: newOutputs } }).then(() => {
      d3.select("#config-modal").style("display", "none");
      refreshData();
    });
  });
}

function showTerminalPicker(title, options, callback) {
  const overlay = document.createElement("div");
  overlay.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,0.8);z-index:20000;display:flex;align-items:center;justify-content:center;";
  const box = document.createElement("div");
  box.style.cssText = "background:#111;border:1px solid #0af;padding:20px;display:flex;flex-direction:column;gap:8px;min-width:200px;";
  box.innerHTML = '<div style="font-size:10px;color:#888;margin-bottom:8px;">' + title + '</div>';
  options.forEach(opt => {
    const btn = document.createElement("button");
    btn.className = "eng-btn";
    btn.textContent = opt;
    btn.onclick = () => { document.body.removeChild(overlay); callback(opt); };
    box.appendChild(btn);
  });
  const cancel = document.createElement("button");
  cancel.className = "eng-btn";
  cancel.style.marginTop = "8px";
  cancel.style.borderColor = "#555";
  cancel.textContent = "CANCEL";
  cancel.onclick = () => { document.body.removeChild(overlay); cancelConnectionMode(); };
  box.appendChild(cancel);
  overlay.appendChild(box);
  document.body.appendChild(overlay);
}

function toggleTerminalOverride(deviceId, terminal, state) {
  const dev = (currentData && currentData.nodes) ? (currentData && currentData.nodes) && currentData.nodes.find(n => n.id === deviceId) : null;
  if (!dev) return;
  const params = dev.params || {};
  const overrides = Object.assign({}, params.output_manual_overrides || {});
  overrides[terminal] = state;
  reconfigureAPI(deviceId, "update_device", { properties: { output_manual_overrides: overrides } }).then(() => refreshData());
}

function breakConnection(sourceId, targetId) {
  if (confirm("Break wire between " + sourceId + " and " + targetId + "?")) {
    reconfigureAPI(sourceId, "delete_connection", { target_id: targetId }).then(() => refreshData());
  }
}
