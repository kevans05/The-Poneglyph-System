"use strict";

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

      (d.type === 'Relay' ? '<div class="menu-item" style="color:#4ff;" onclick="showTCCPlot(\'' + d.id + '\')">VIEW TCC COORDINATION PLOT</div>' : '') +
      (d.type === 'DualWindingVT' ? '<div class="menu-item" style="color:#ff9933;" onclick="d3.select(\'#context-menu\').style(\'display\',\'none\'); startSecondary2ConnectionMode(\'' + d.id + '\')">CONNECT WINDING 2 OUTPUT...</div>' : '') +
      (typeof simActive !== 'undefined' && simActive ?
        '<div style="padding:4px 10px; font-size:9px; color:#555; background:#0a0a0a; border-top:1px solid #222;">SIMULATION</div>' +
        '<div class="menu-item" style="color:#f55;" onclick="showFaultConfig(\'' + d.id + '\')">CONFIGURE & INJECT FAULT...</div>' +
        '<div class="menu-item" style="color:#0f0;" onclick="clearFault(\'' + d.id + '\')">CLEAR FAULT</div>' +
        (d.type === 'Relay' ? '<div class="menu-item" style="color:#4af;" onclick="showRelaySettingsEditor(\'' + d.id + '\')">EDIT RELAY SETTINGS...</div>' : '') +
        '<div class="menu-item" style="color:#c8a0ff;" onclick="showOscillography(\'' + d.id + '\')">VIEW OSCILLOGRAPHY...</div>'
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
      (['Bus', 'Wire', 'PowerLine', 'Line'].includes(d.type) ?
        '<div style="padding:4px 10px; font-size:9px; color:#555; background:#0a0a0a; border-top:1px solid #222;">TOPOLOGY</div>' +
        '<div class="menu-item" style="color:#7df;" onclick="d3.select(\'#context-menu\').style(\'display\',\'none\'); showRingConnectionDialog(\'' + d.id + '\')">ADD RING CONNECTION...</div>'
      : '') +
      '<div class="menu-item" onclick="showRenameDialog(\'' +
      d.id +
      "')\">RENAME DEVICE</div>" +
      "<div class=\"menu-item\" onclick=\"d3.select('#context-menu').style('display','none')\">CLOSE MENU</div>",
  );
  d3.select("body").on("click.menu", () =>
    d3.select("#context-menu").style("display", "none"),
  );
}

function showRingConnectionDialog(sourceId) {
  // Collect buses/wires that are not already directly connected to sourceId
  const directNeighbors = new Set();
  currentData.edges.forEach(e => {
    const sid = (typeof e.source === "string") ? e.source : e.source.id;
    const tid = (typeof e.target === "string") ? e.target : e.target.id;
    if (sid === sourceId) directNeighbors.add(tid);
    if (tid === sourceId) directNeighbors.add(sid);
  });

  const candidates = currentData.nodes
    .filter(n => n.id !== sourceId && !directNeighbors.has(n.id) &&
                 ['Bus', 'Wire', 'PowerLine', 'Line'].includes(n.type))
    .map(n => n.id);

  if (candidates.length === 0) {
    alert('No available buses to connect to (all reachable buses are already connected).');
    return;
  }

  const modal = document.createElement('div');
  modal.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.7);z-index:9999;display:flex;align-items:center;justify-content:center;';
  modal.innerHTML = `
    <div style="background:#1a1a1a;border:1px solid #444;border-radius:6px;padding:24px;min-width:320px;color:#eee;font-family:monospace;">
      <div style="font-size:13px;font-weight:bold;margin-bottom:16px;color:#7df;">ADD RING CONNECTION</div>
      <div style="font-size:11px;color:#aaa;margin-bottom:8px;">Connect <b style="color:#fff;">${sourceId}</b> to:</div>
      <select id="ring-target-select" style="width:100%;background:#111;color:#eee;border:1px solid #555;padding:6px;font-family:monospace;font-size:12px;margin-bottom:16px;">
        ${candidates.map(id => `<option value="${id}">${id}</option>`).join('')}
      </select>
      <div style="display:flex;gap:8px;justify-content:flex-end;">
        <button onclick="this.closest('div[style*=fixed]').remove()" style="background:#333;color:#aaa;border:1px solid #555;padding:6px 14px;cursor:pointer;font-family:monospace;">CANCEL</button>
        <button id="ring-connect-btn" style="background:#1a3a5a;color:#7df;border:1px solid #7df;padding:6px 14px;cursor:pointer;font-family:monospace;">CONNECT</button>
      </div>
    </div>`;
  document.body.appendChild(modal);

  modal.querySelector('#ring-connect-btn').onclick = () => {
    const targetId = modal.querySelector('#ring-target-select').value;
    modal.remove();
    reconfigureAPI(sourceId, "add_connection", { to: targetId });
  };
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

