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

