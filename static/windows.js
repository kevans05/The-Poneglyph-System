"use strict";

/**
 * SCADA Pro Console - UI & Window Management
 * Handles draggable windows, context menus, and modals.
 */

let zIndexCounter = 5000;
let connectionSource = null;
let _winCascade = 0;
let _configModalDragged = false;

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
    '<button class="ang-conv-btn ref-pick-btn" onclick="_showRefPicker(\'' + escapedId + '\')" title="Set device as 0° phase reference">⊙ REF</button>' +
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
    if (typeof popup.drawPhasors === "function") {
      popup.drawPhasors(id, node.summary, node.type);
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

// Resolve the current node data from either live data or simulation data
function _resolveNode(id) {
  const data = (typeof simData !== "undefined" && simData) ? simData : currentData;
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

/**
 * Show a small dropdown beneath the REF button letting the user pick which
 * phase (A / B / C) of this device becomes the global 0° reference, or clear
 * the active reference entirely.
 */
function _showRefPicker(nodeId) {
  // Remove any existing picker
  const existing = document.getElementById("_ref-picker-popup");
  if (existing) { existing.remove(); return; }

  const win = openWindows[nodeId];
  if (!win) return;
  const btn = win.querySelector(".ref-pick-btn");
  if (!btn) return;

  const popup = document.createElement("div");
  popup.id = "_ref-picker-popup";
  popup.style.cssText =
    "position:absolute;background:#111;border:1px solid #3af;z-index:99999;" +
    "font-family:'Consolas','Courier New',monospace;font-size:10px;min-width:160px;" +
    "box-shadow:0 4px 16px rgba(0,0,0,0.8);";

  const rect = btn.getBoundingClientRect();
  popup.style.left = rect.left + "px";
  popup.style.top = (rect.bottom + 4) + "px";

  const currentRef = currentData && currentData.reference;
  const isActive = currentRef && currentRef.device_id === nodeId;

  const phases = ["A", "B", "C"];
  let html = '<div style="padding:6px 10px;color:#3af;letter-spacing:1px;border-bottom:1px solid #222;font-size:9px;">SET 0° REFERENCE — ' + nodeId + '</div>';
  phases.forEach(ph => {
    const isSelected = isActive && currentRef.phase === ph;
    html += `<div class="ref-pick-item${isSelected ? " ref-pick-selected" : ""}" onclick="_applyRef('${nodeId.replace(/'/g,"\\'")}','${ph}')">`;
    html += `<span style="color:#3af;width:18px;display:inline-block;">${isSelected ? "●" : "○"}</span>`;
    html += `Phase ${ph} → 0°</div>`;
  });
  html += '<div class="ref-pick-item ref-pick-clear" onclick="_applyRef(null,null)">✕ &nbsp;Clear reference</div>';
  popup.innerHTML = html;
  document.body.appendChild(popup);

  // Close on outside click
  setTimeout(() => {
    document.addEventListener("click", function _closeRefPicker(e) {
      if (!popup.contains(e.target)) {
        popup.remove();
        document.removeEventListener("click", _closeRefPicker);
      }
    });
  }, 0);
}

function _applyRef(deviceId, phase) {
  const popup = document.getElementById("_ref-picker-popup");
  if (popup) popup.remove();
  setAsReference(deviceId, phase);
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
    html += "<button class=\"cmd-btn\" style=\"background:#001a1a; color:#4ff; border-color:#4ff; margin-top:4px;\" " +
            "onclick=\"showTCCPlot(\'" + node.id + "\')\">TCC COORDINATION PLOT</button>";

    if (typeof simActive !== "undefined" && simActive) {
      html += "<button class=\"cmd-btn\" style=\"background:#001a00; color:#4f4; border-color:#4f4; margin-top:4px;\" " +
              "onclick=\"showRelaySettingsEditor(\'" + node.id + "\')\">RELAY SETTINGS <span>SIM</span></button>";
      html += "<button class=\"cmd-btn\" style=\"background:#0a0018; color:#c8a0ff; border-color:#c8a0ff; margin-top:4px;\" " +
              "onclick=\"showOscillography(\'" + node.id + "\')\">OSCILLOGRAPHY <span>SIM</span></button>";
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
      "')\">W1 CONN <span>&rarr;</span></button>" +
      (node.type === 'DualWindingVT' ? '<button class="eng-btn" style="flex:1; background:#321; color:#ff9933;" onclick="startSecondary2ConnectionMode(\'' + node.id + '\')">W2 CONN <span>&rarr;</span></button>' : '') +
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

  // Drawings — attached drawing references for this device
  html += '<div class="section-title" style="margin-top:12px;">DRAWINGS</div>';
  html += `<div id="dstrip-${safeId}" class="device-drawing-strip"><span style="color:#2a2a2a;font-size:9px;">Loading…</span></div>`;
  html += `<button class="eng-btn" style="width:100%;margin-top:3px;color:#aaf;border-color:#2a2a4a;" onclick="_openDrawingsManager('${node.id.replace(/'/g, "\\'")}')">📎 ATTACH / MANAGE DRAWINGS</button>`;

  // Device notes — free-form editable field stored on the device params
  const curNotes = (node.params && node.params.notes) || "";
  html += '<div style="font-size:9px; color:#666; margin-top:8px; border-bottom:1px solid #222;">DEVICE NOTES</div>';
  html += `<textarea id="_dnotes-${safeId}" style="width:100%;box-sizing:border-box;margin-top:3px;background:#0d0d0d;border:1px solid #333;color:#bbb;font-family:inherit;font-size:10px;padding:5px 7px;resize:vertical;min-height:46px;outline:none;" placeholder="Add notes about this device…">${curNotes}</textarea>`;
  html += `<button class="eng-btn" style="width:100%;margin-top:2px;color:#3af;border-color:#1a3a5a;" onclick="_saveDeviceNotes('${node.id}','${safeId}')">SAVE NOTES</button>`;

  content.innerHTML = html;
  drawPhasors(id, node.summary, node.type);
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

