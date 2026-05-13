"use strict";

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

function startSecondary2ConnectionMode(sourceId) {
  connectionSource = { id: sourceId, isSecondary2: true };
  d3.select("#status-bar")
    .style("display", "block")
    .style("background", "#ff9933")
    .style("color", "#000")
    .html(
      "DVT W2 CONNECTION MODE: Select target Relay/Meter to receive WINDING 2 voltage from " +
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
  const { id, bushing, isSecondary, isSecondary2, isDC, isTrip, isClose, from } = connectionSource;

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
  const action = isTrip ? "add_trip_connection" : isClose ? "add_close_connection" : isDC ? "add_dc_connection" : isSecondary2 ? "add_secondary2_connection" : isSecondary ? "add_secondary_connection" : "add_connection";
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
  VoltageRegulator:    { nominal_kv: 13.8, tap_pos: 0, step_percent: 0.625, max_steps: 16, avr_enabled: false, avr_deadband_pct: 2.5, avr_delay_ms: 30000 },
  Load:                { load_mva: 50, pf: 0.85, is_balanced: true },
  VoltageTransformer:  { ratio: "2000:1", bushing: "X", polarity_normal: true, primary_winding: "Y", secondary_wiring: "Y" },
  DualWindingVT:       { ratio: "2000:1", sec2_ratio: "2000:1", bushing: "X", polarity_normal: true, primary_winding: "Y", secondary_wiring: "Y", secondary2_wiring: "Y" },
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

// Device type → short abbreviation for the badge
const _DEV_TYPE_SHORT = {
  Bus: "BUS", VoltageSource: "SRC", Load: "LOAD",
  CircuitBreaker: "CB", ThreePoleDisconnect: "DS", SinglePoleDisconnect: "DS",
  PowerTransformer: "XFR", VoltageTransformer: "VT", CurrentTransformer: "CT",
  DualWindingVT: "DVT", Relay: "RLY", CTTB: "CTTB", FTBlock: "FTB",
  IsoBlock: "ISO", Meter: "MTR", Indicator: "IND", AuxiliaryTransformer: "AXT",
  PowerLine: "LINE", VoltageRegulator: "REG", ShuntCapacitor: "CAP",
  ShuntReactor: "RCT", SVC: "SVC", LineTrap: "TRAP",
  NeutralGroundingResistor: "NGR", SeriesCapacitor: "SC",
};
// Device type → header accent colour
const _DEV_TYPE_COLOR = {
  Bus: "#0af", VoltageSource: "#0f0", Load: "#f80",
  CircuitBreaker: "#ff0", ThreePoleDisconnect: "#ff0", SinglePoleDisconnect: "#ff0",
  PowerTransformer: "#a0f", VoltageTransformer: "#4af", CurrentTransformer: "#4af",
  DualWindingVT: "#4af", Relay: "#f44", CTTB: "#f44", FTBlock: "#f84",
  IsoBlock: "#f84", Meter: "#0f8", Indicator: "#0f8", AuxiliaryTransformer: "#a0f",
  PowerLine: "#888", VoltageRegulator: "#0af",
};


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

