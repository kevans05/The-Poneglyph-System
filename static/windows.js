"use strict";

/**
 * SCADA Pro Console - UI & Window Management
 * Handles draggable windows, context menus, and modals.
 */

let zIndexCounter = 5000;
let connectionSource = null;
let _winCascade = 0;
let _configModalDragged = false;

// Belt-and-braces filter: the backend already strips computed power-flow
// telemetry from /api/topology, but snapshot payloads or a stale server could
// still carry per-phase voltages/currents/angles/power. Keep the device window
// showing structural state only.
const _TELEMETRY_KEY_RE =
  /(voltage|current|v-angle|i-angle|\bangle\b|power|watt|\bvars?\b|frequency|\bfreq\b|\bpf\b|power factor|kva|mva|phasor|magnitude)/i;

// Energization state is a steady-state-solve artifact (no simulation now), so
// drop it — but keep a real switch status ("CLOSED" / "OPEN [...]").
const _DEAD_STATUS_RE = /de-?energi[sz]ed|dead|open circuit|no load/i;

function _structuralEntries(summary) {
  return Object.entries(summary || {}).filter(
    ([k, v]) =>
      v !== "HEADER" &&
      !(k.startsWith("---") && k.trimEnd().endsWith("---")) &&
      !_TELEMETRY_KEY_RE.test(k) &&
      !(k === "Status" && typeof v === "string" && _DEAD_STATUS_RE.test(v)),
  );
}

// Secondary device types (instrument / protection / metering).
const _SECONDARY_DEV = new Set([
  "CurrentTransformer", "VoltageTransformer", "DualWindingVT", "CTTB",
  "FTBlock", "IsoBlock", "Relay", "Meter", "AuxiliaryTransformer",
]);

// Walk a secondary device's analog inputs back to the primary equipment it
// ultimately watches. Returns one entry per branch: { trail:[ids], primId }.
function _tracePrimaryPaths(node) {
  const byId = (i) => ((currentData && currentData.nodes) || []).find((n) => n.id === i);
  const out = [];
  const walk = (n, trail, guard) => {
    if (!n || guard > 15 || trail.includes(n.id)) return;
    const t = trail.concat(n.id);
    const ins = (n.inputs || []).map(byId).filter(Boolean);
    if (ins.length === 0) {
      const host = (n.summary && n.summary.Location) || null;
      out.push({ trail: t, primId: host, leaf: n.id });
    } else {
      ins.forEach((i) => walk(i, t, guard + 1));
    }
  };
  walk(node, [], 0);
  return out;
}

// Interactive connection editor: primary wiring, secondary/protection feeds,
// and — for a CTTB or Relay — the input summation as signed I(x) terms you can
// flip, remove, or add to. Lives here, not in the parameters form.
function _connectionsBlock(node) {
  const rid = (v) => (typeof v === "string" ? v : v && v.id);
  const nid = node.id;
  const q = (s) => String(s).replace(/'/g, "\\'");
  const edges = (currentData && currentData.edges) || [];

  const primary = [], sec = [], sec2 = [];
  edges.forEach((e) => {
    const s = rid(e.source), t = rid(e.target);
    if (s !== nid && t !== nid) return;
    const rec = { other: s === nid ? t : s, mine: s === nid };
    if (!e.type || e.type === "primary") {
      rec.b = rec.mine ? e.source_bushing : e.target_bushing;
      primary.push(rec);
    } else if (e.type === "protection") sec.push(rec);
    else if (e.type === "protection2") sec2.push(rec);
  });

  const host = node.summary && node.summary.Location;
  const isSummation = ["CTTB", "Relay"].includes(node.type);
  const isSensor = ["CurrentTransformer", "VoltageTransformer", "DualWindingVT", "AuxiliaryTransformer"].includes(node.type);
  const isShunt = ["VoltageSource", "Load", "ShuntCapacitor", "ShuntReactor", "SurgeArrester", "SVC", "NeutralGroundingResistor", "Bus", "Line", "PowerLine", "Wire"].includes(node.type);

  // remove-wire button for a classified entry (call delete on the source side)
  const rmx = (rec) => {
    const src = rec.mine ? nid : rec.other;
    const tgt = rec.mine ? rec.other : nid;
    return `<button class="conn-x" title="remove wire" onclick="breakConnection('${q(src)}','${q(tgt)}')">✕</button>`;
  };
  const devRow = (inner) => `<div class="conn-row">${inner}</div>`;
  const addBtn = (label, call) => `<button class="conn-add" onclick="${call}">${label}</button>`;

  let h = '<div class="section-title">CONNECTIONS</div><div class="conn-block">';

  if (host && host !== nid) {
    h += devRow(`<span class="conn-tag">MOUNT</span><span class="conn-dev">${host}</span>`);
  }

  // ── Trace back to the primary equipment this secondary device watches ────
  if (_SECONDARY_DEV.has(node.type)) {
    const paths = _tracePrimaryPaths(node);
    if (paths.length) {
      h += '<div class="conn-sub">TRACE TO PRIMARY</div>';
      const kvOf =
        typeof window !== "undefined" && typeof window.nodeVoltageKv === "function"
          ? (id) => window.nodeVoltageKv(((currentData && currentData.nodes) || []).find((n) => n.id === id))
          : () => 0;
      paths.forEach((p) => {
        const hops = p.trail
          .map((idp, i) => (i ? '<span class="trace-arrow">←</span>' : "") + `<span class="trace-hop">${idp}</span>`)
          .join("");
        const kv = p.primId ? kvOf(p.primId) : 0;
        const prim = p.primId
          ? `<span class="trace-prim">⇒ ${p.primId}</span>` + (kv > 0 ? `<span class="trace-kv">${kv} kV</span>` : "")
          : `<span class="trace-prim conn-none">⇒ not traced to primary</span>`;
        h += `<div class="conn-trace">${hops} ${prim}</div>`;
      });
    }
  }

  // ── Summation math (CTTB / Relay) ────────────────────────────────────────
  if (isSummation) {
    const pol = (node.params && node.params.input_polarities) || {};
    const inputs = node.inputs || [];
    let head = '<div class="conn-sub">Σ INPUTS';
    if (node.type === "CTTB") {
      const diff = (node.params && node.params.mode) === "DIFFERENTIAL";
      head += `<span class="conn-modes">` +
        `<button class="conn-mode${!diff ? " on" : ""}" onclick="setSummationMode('${q(nid)}','SUM')">Σ SUM</button>` +
        `<button class="conn-mode${diff ? " on" : ""}" onclick="setSummationMode('${q(nid)}','DIFFERENTIAL')">± DIFF</button>` +
        `</span>`;
    }
    h += head + "</div>";

    if (inputs.length === 0) {
      h += devRow(`<span class="conn-dev conn-none">no inputs wired</span>`);
    } else {
      inputs.forEach((inId) => {
        const p = pol[inId] === -1 ? -1 : 1;
        const col = p === 1 ? "#3fdc8f" : "#f66";
        h += devRow(
          `<button class="conn-sign" style="color:${col};border-color:${col};" title="flip polarity" ` +
          `onclick="toggleInputPolarity('${q(nid)}','${q(inId)}',${p})">${p === 1 ? "+" : "−"}</button>` +
          `<span class="conn-term">I(<b>${inId}</b>)</span>` +
          `<button class="conn-x" title="remove input" onclick="breakConnection('${q(inId)}','${q(nid)}')">✕</button>`,
        );
      });
    }
    h += addBtn("＋ ADD INPUT", `addSummationInput('${q(nid)}')`);

    const outs = sec.filter((x) => x.mine);
    h += '<div class="conn-sub">OUTPUT →</div>';
    if (outs.length === 0) {
      h += devRow(`<span class="conn-dev conn-none">not wired onward</span>`);
    } else {
      outs.forEach((o) => (h += devRow(`<span class="conn-dev">→ ${o.other}</span>${rmx(o)}`)));
    }
    h += addBtn("＋ WIRE OUTPUT →", `startSecondaryConnectionMode('${q(nid)}')`);
    return h + "</div>";
  }

  // ── Primary wiring ───────────────────────────────────────────────────────
  h += '<div class="conn-sub">PRIMARY</div>';
  if (primary.length === 0) {
    h += devRow(`<span class="conn-dev conn-none">— not wired —</span>`);
  } else {
    primary.forEach((p) =>
      (h += devRow(
        `<span class="conn-tag">${p.b || "•"}</span><span class="conn-dev">↔ ${p.other}</span>${rmx(p)}`,
      )),
    );
  }
  if (isShunt) {
    h += addBtn("＋ ADD CONNECTION →", `startConnectionMode('${q(nid)}','X')`);
  } else {
    h += '<div class="conn-addrow">' +
      `<button class="conn-add" onclick="startConnectionMode('${q(nid)}','H')">＋ ON&nbsp;H</button>` +
      `<button class="conn-add" onclick="startConnectionMode('${q(nid)}','X')">＋ ON&nbsp;X</button>` +
      "</div>";
  }

  // ── Secondary / protection feeds ─────────────────────────────────────────
  const showSec =
    sec.length || sec2.length || isSensor ||
    ["FTBlock", "IsoBlock", "Meter"].includes(node.type);
  if (showSec) {
    h += '<div class="conn-sub">SECONDARY</div>';
    if (sec.length === 0 && sec2.length === 0) {
      h += devRow(`<span class="conn-dev conn-none">— none —</span>`);
    } else {
      sec.forEach((s) =>
        (h += devRow(`<span class="conn-dev">${s.mine ? "→" : "←"} ${s.other}</span>${rmx(s)}`)),
      );
      sec2.forEach((s) =>
        (h += devRow(
          `<span class="conn-tag">W2</span><span class="conn-dev">${s.mine ? "→" : "←"} ${s.other}</span>${rmx(s)}`,
        )),
      );
    }
    if (isSensor) {
      h += addBtn("＋ WIRE OUTPUT →", `startSecondaryConnectionMode('${q(nid)}')`);
      if (node.type === "DualWindingVT") {
        h += addBtn("＋ WIRE W2 OUTPUT →", `startSecondary2ConnectionMode('${q(nid)}')`);
      }
    }
  }

  return h + "</div>";
}

// Detached popup windows: deviceId → popup window reference
let _popupWindows = {};

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

function updateStatusBar(syncErrors) {
  const bar = d3.select("#status-bar");
  let html = "";

  if (syncErrors && syncErrors.length > 0) {
    syncErrors.forEach(err => {
      const issues = err.issues.join(" · ");
      html += "<span style=\"background:#1a0000; color:#f44; padding:2px 10px; margin-right:8px; border:1px solid #f44; font-size:10px; letter-spacing:1px;\">";
      html += `⚠ SYNC FAULT: ${err.sources.join(" ↔ ")} — ${issues}</span>`;
    });
    bar.style("background", "#0d0000").style("color", "#f44");
  } else {
    html += "Load-Test Console — ready.";
    bar.style("background", "#111").style("color", "#0f0");
  }

  bar.html(html).style("display", "block");
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
  const typeShort = _DEV_TYPE_SHORT[node.type] || node.type;
  const typeColor = _DEV_TYPE_COLOR[node.type] || "#888";
  const escapedId = node.id.replace(/\\/g, "\\\\").replace(/'/g, "\\'");

  win.innerHTML =
    '<div class="window-header" style="border-left:3px solid ' + typeColor + ';">' +
    '<span style="display:flex;align-items:center;gap:7px;min-width:0;">' +
    '<span class="dev-type-badge" style="background:' + typeColor + '22;color:' + typeColor + ';border-color:' + typeColor + '44;">' + typeShort + '</span>' +
    '<span class="window-title" title="' + node.id + '">' + node.id + '</span>' +
    '</span>' +
    '<span style="display:flex;gap:6px;align-items:center;flex-shrink:0;">' +
    '<button class="ang-conv-btn" onclick="_toggleAngleConv()" title="Toggle angle convention">' +
    (_use360Lag ? "360°" : "±180°") +
    '</button>' +
    '<button class="ang-conv-btn" onclick="detachWindow(\'' + escapedId + '\')" title="Open in new window" style="font-size:12px;">⤢</button>' +
    '<span style="cursor:pointer;color:#888;padding:2px 4px;" onclick="closeWindow(\'' + escapedId + '\')" title="Close">✕</span>' +
    '</span></div>' +
    '<div class="window-content" id="win-' + safeId + '"></div>';

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
  // Also close any detached popup for this window
  if (_popupWindows[id] && !_popupWindows[id].closed) {
    _popupWindows[id].close();
  }
  delete _popupWindows[id];
}

/**
 * Open a device window in a separate browser popup.
 * The popup loads detached.html, which proxies all interactions back here.
 */
function detachWindow(id) {
  // If popup already open, just focus it
  if (_popupWindows[id] && !_popupWindows[id].closed) {
    _popupWindows[id].focus();
    return;
  }
  const w = 480, h = 700;
  const left = Math.round(window.screenX + window.outerWidth / 2 - w / 2);
  const top  = Math.round(window.screenY + 60);
  const popup = window.open(
    "/static/detached.html?id=" + encodeURIComponent(id),
    "device_" + id.replace(/\s+/g, "_"),
    "width=" + w + ",height=" + h + ",resizable=yes,scrollbars=yes,left=" + left + ",top=" + top
  );
  if (!popup) { alert("Popup blocked — please allow popups for this site."); return; }
  _popupWindows[id] = popup;
}

// Called by detached.html once its DOM is ready
function _detachedWindowReady(id, popup) {
  _popupWindows[id] = popup;
  const node = _resolveNode(id);
  if (!node) return;
  const typeShort = _DEV_TYPE_SHORT[node.type] || node.type;
  const typeColor = _DEV_TYPE_COLOR[node.type] || "#888";
  // Set title / badge in popup
  try { popup._showDevice(id, typeShort, typeColor); } catch(e) {}
  // Sync angle convention flag
  try { popup._use360Lag = _use360Lag; } catch(e) {}
  // Push current content
  _syncWindowToPopup(id, node);
}

// Called by detached.html's beforeunload
function _detachedWindowClosed(id) {
  delete _popupWindows[id];
}

// Sync the local device-window content to its popup (if open)
function _syncWindowToPopup(id, node) {
  const popup = _popupWindows[id];
  if (!popup || popup.closed) { delete _popupWindows[id]; return; }
  const safeId = id.replace(/\s+/g, "-");
  const src = document.getElementById("win-" + safeId);
  if (!src) return;
  try {
    const target = popup.document.getElementById("win-" + safeId);
    if (!target) return;
    target.innerHTML = src.innerHTML;
    // The inline config form uses live JS handlers that don't survive an
    // innerHTML copy — in the popup, offer the modal editor instead.
    const pcfg = popup.document.getElementById("cfg-body-" + safeId);
    if (pcfg) {
      pcfg.innerHTML =
        '<button class="eng-btn" style="width:100%" onclick="showConfigModal(\'' +
        id.replace(/'/g, "\\'") +
        '\')">EDIT PARAMETERS…</button>';
    }
    // Sync angle button label
    const angBtn = popup.document.getElementById("detached-ang-btn");
    if (angBtn) {
      angBtn.innerText      = _use360Lag ? "360°" : "±180°";
      angBtn.style.color    = _use360Lag ? "#3af" : "#888";
      angBtn.style.borderColor = _use360Lag ? "#3af" : "#555";
    }
  } catch(e) {
    // Popup closed or cross-origin
    delete _popupWindows[id];
  }
}

// Resolve the current node data from the live topology.
function _resolveNode(id) {
  const data = currentData;
  return data && data.nodes && data.nodes.find(n => n.id === id);
}

// Called from detached.html proxy for _saveDeviceNotes (reads popup textarea value)
function _saveDeviceNotesFromPopup(deviceId, notes) {
  reconfigureAPI(deviceId, "update_device", { properties: { notes } }).then(() => {
    if (currentData && currentData.nodes) {
      const node = currentData.nodes.find(n => n.id === deviceId);
      if (node) { if (!node.params) node.params = {}; node.params.notes = notes; }
    }
  });
}

// ── Summary row rendering helpers ─────────────────────────────────────────────

function _renderSummaryRows(entries) {
  let html = "";
  entries.forEach(function(entry) { var key = entry[0], value = entry[1];
    if (value === "HEADER") {
      html += `<div style="background:#1a1a1a; padding:2px 8px; font-size:10px; color:#aaa; margin-top:8px; text-align:center; border:1px solid #333; text-transform:uppercase;">${key.replace(/-/g, "").trim()}</div>`;
    } else {
      let valDisplay;
      if (typeof value === "number") {
        valDisplay = unitsMap[key] === "deg" ? _fmtAngle(value) : formatSI(value, unitsMap[key] || "");
      } else {
        valDisplay = value;
      }
      html += `<div class="stat-row" style="flex-direction:column; align-items:stretch; border-bottom:1px solid #222; padding:4px 0;"><div style="display:flex; justify-content:space-between;"><span class="stat-label">${key}:</span><span class="stat-value">${valDisplay}</span></div></div>`;
    }
  });
  return html;
}

// ── updateWindow ───────────────────────────────────────────────────────────────

function updateWindow(id, node) {
  if (!node) return;
  const safeId = id.replace(/\s+/g, "-");
  const content = document.getElementById("win-" + safeId);
  if (!content) return;

  let html = "";

  // Secondary devices: headline action — spin up a load test for the scheme.
  if (_SECONDARY_DEV.has(node.type)) {
    html +=
      '<button class="cmd-btn" style="width:100%;background:#0d160d;color:#3fdc8f;border-color:#1f6b47;margin-bottom:8px;font-weight:bold;" ' +
      "onclick=\"_generateLoadTest('" + node.id.replace(/'/g, "\\'") + "')\">⚡ GENERATE LOAD TEST</button>";
  }

  html += '<div class="section-title">DEVICE STATE</div>';
  html += _renderSummaryRows(_structuralEntries(node.summary));

  html += _connectionsBlock(node);

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
        '<button class="eng-btn" style="flex:1" onclick="showPlantMenu(event.pageX, event.pageY, snapToGrid(' +
        gx +
        "+60), snapToGrid(" +
        gy +
        "), '" +
        node.id +
        "', '" +
        b +
        "')\">PLANT <span>+</span></button>" +
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

  // Add a downstream protection stage from a sensor / summation device.
  if (
    ["CurrentTransformer", "CTTB", "VoltageTransformer", "DualWindingVT", "FTBlock"].includes(node.type)
  ) {
    const isCurrent = ["CurrentTransformer", "CTTB"].includes(node.type);
    html +=
      '<div style="display:flex; gap:4px; margin-top:8px;">' +
      '<button class="eng-btn" style="flex:1" onclick="' + (isCurrent ? "addCTTB" : "addFTBlock") + "('" + node.id + "')\">+ " + (isCurrent ? "CTTB" : "FT") + " STAGE</button>" +
      '<button class="eng-btn" style="flex:1" onclick="addRelay(\'' + node.id + "')\">+ RELAY</button>" +
      "</div>";
  }

  // 5. DEVICE MANAGEMENT
  html += '<div class="section-title">DEVICE CONFIGURATION</div>';
  html +=
    '<div style="display:flex; gap:4px;">' +
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

  // Device parameters — rendered inline below (no popup).
  html += '<div class="section-title" style="margin-top:10px;">PARAMETERS</div>';
  if (node.type === "Load") {
    html += `<button class="eng-btn" style="width:100%;" onclick="showLoadConfigModal('${node.id}')">EDIT LOAD P / Q…</button>`;
  } else {
    html += `<div id="cfg-body-${safeId}" class="win-params"></div>`;
  }

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
  html += `<button class="eng-btn" style="width:100%; margin-top:2px;" onclick="showAnalogHistoryModal('${node.id}')">VIEW RECORDED MEASUREMENTS</button>`;

  // Drawings — attached drawing references for this device
  html += '<div class="section-title" style="margin-top:12px;">DRAWINGS</div>';
  html += `<div id="dstrip-${safeId}" class="device-drawing-strip"><span style="color:#2a2a2a;font-size:9px;">Loading…</span></div>`;
  html += `<button class="eng-btn" style="width:100%;margin-top:3px;color:#aaf;border-color:#2a2a4a;" onclick="_openDrawingsManager('${node.id.replace(/'/g, "\\'")}')">📎 ATTACH / MANAGE DRAWINGS</button>`;

  // Device notes — free-form editable field stored on the device params
  const curNotes = (node.params && node.params.notes) || "";
  html += '<div style="font-size:9px; color:#666; margin-top:8px; border-bottom:1px solid #222;">DEVICE NOTES</div>';
  html += `<textarea id="_dnotes-${safeId}" style="width:100%;box-sizing:border-box;margin-top:3px;background:#0d0d0d;border:1px solid #333;color:#bbb;font-family:inherit;font-size:10px;padding:5px 7px;resize:vertical;min-height:46px;outline:none;" placeholder="Add notes about this device…">${curNotes}</textarea>`;
  html += `<button class="eng-btn" style="width:100%;margin-top:2px;color:#3af;border-color:#1a3a5a;" onclick="_saveDeviceNotes('${node.id}','${safeId}')">SAVE NOTES</button>`;

  // Preserve an in-progress parameter edit across a background refresh: if the
  // user is typing in this window's inline config, keep the existing form.
  const prevCfg = document.getElementById("cfg-body-" + safeId);
  const keepCfg =
    prevCfg && prevCfg.contains(document.activeElement) ? prevCfg : null;

  content.innerHTML = html;

  const cfgBody = document.getElementById("cfg-body-" + safeId);
  if (cfgBody && keepCfg) {
    cfgBody.replaceWith(keepCfg); // restore the form the user was editing
  } else if (cfgBody && typeof renderInlineConfig === "function") {
    renderInlineConfig(d3.select(cfgBody), node, () => refreshData());
  }
  _renderWindowDrawingStrip(safeId, node.id);
  _syncWindowToPopup(id, node);
}

function _renderWindowDrawingStrip(safeId, deviceId) {
  fetchDeviceDrawings(deviceId).then(resp => {
    const el = document.getElementById("dstrip-" + safeId);
    if (!el) return;
    const drawings = resp.drawings || [];
    if (drawings.length === 0) {
      el.innerHTML = '<span style="color:#2a2a2a;font-size:9px;">No drawings attached.</span>';
      return;
    }
    el.innerHTML = "";
    drawings.forEach(d => {
      const chip = document.createElement("div");
      chip.className = "drawing-chip";
      const hasUrl = !!d.url;
      chip.innerHTML =
        `<span class="drawing-chip-icon">${hasUrl ? "📄" : "📋"}</span>` +
        `<span class="drawing-chip-title">${d.title}</span>` +
        (d.revision ? `<span class="drawing-chip-rev">${d.revision}</span>` : "");
      if (hasUrl) {
        chip.title = "Open drawing";
        chip.style.cursor = "pointer";
        chip.addEventListener("click", () => window.open(d.url, "_blank"));
      } else {
        chip.title = d.notes || d.title;
      }
      el.appendChild(chip);
    });
  }).catch(() => {
    const el = document.getElementById("dstrip-" + safeId);
    if (el) el.innerHTML = '<span style="color:#333;font-size:9px;">—</span>';
  });
}

