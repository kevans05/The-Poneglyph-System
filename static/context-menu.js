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

