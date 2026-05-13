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

function _saveDeviceNotes(deviceId, safeId) {
  const ta = document.getElementById("_dnotes-" + safeId);
  if (!ta) return;
  const notes = ta.value;
  reconfigureAPI(deviceId, "update_device", { properties: { notes } }).then(() => {
    // Update in-memory node so the window shows the saved value immediately
    if (currentData && currentData.nodes) {
      const node = currentData.nodes.find(n => n.id === deviceId);
      if (node) { if (!node.params) node.params = {}; node.params.notes = notes; }
    }
    // Brief visual confirmation
    ta.style.borderColor = "#3af";
    setTimeout(() => { ta.style.borderColor = "#333"; }, 900);
  });
}
