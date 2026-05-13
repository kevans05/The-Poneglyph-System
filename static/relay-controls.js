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

