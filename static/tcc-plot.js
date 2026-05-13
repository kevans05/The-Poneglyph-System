// ── TCC Coordination Plot ─────────────────────────────────────────────────

const _TCC_COLORS = [
  "#ff4444","#44ff88","#4488ff","#ffff44",
  "#ff88ff","#44ffff","#ff8844","#cc88ff",
];

function _tccIdmtTime(curve, M, tms) {
  if (M <= 1.0) return null;
  switch (curve) {
    case "IEC_SI":  return tms * 0.14   / (Math.pow(M, 0.02) - 1);
    case "IEC_VI":  return tms * 13.5   / (M - 1);
    case "IEC_EI":  return tms * 80.0   / (Math.pow(M, 2) - 1);
    case "IEC_LTI": return tms * 120.0  / (M - 1);
    case "IEEE_MI": return tms * (0.0515 / (Math.pow(M, 0.02) - 1) + 0.114);
    case "IEEE_VI": return tms * (19.61  / (Math.pow(M, 2) - 1) + 0.491);
    case "IEEE_EI": return tms * (28.2   / (Math.pow(M, 2) - 1) + 0.1217);
    default:        return tms;
  }
}

function showTCCPlot(focusDeviceId) {
  const data = (typeof simActive !== "undefined" && simActive && typeof simData !== "undefined" && simData)
    ? simData : currentData;
  if (!data) { alert("No topology loaded."); return; }

  const curves = [];
  let colorIdx = 0;
  let xMin = Infinity, xMax = 0;

  data.nodes.forEach(node => {
    if (node.type !== "Relay") return;
    const s = node.params && node.params.settings;
    if (!s) return;
    const focused = node.id === focusDeviceId;

    Object.keys(s).forEach(key => {
      // 51-series IDMT
      let m = key.match(/^(51[A-Z]?\d+)P$/);
      if (m) {
        const elem   = m[1];
        const pickup = parseFloat(s[key]) || 0;
        if (!pickup) return;
        const tms  = parseFloat(s[elem + "TMS"] || s[elem + "TDS"] || 1.0);
        const curve = s[elem + "CURVE"] || "IEC_SI";
        curves.push({ relay: node.id, label: node.id + " " + elem, pickup, tms, curve,
                      color: _TCC_COLORS[colorIdx++ % _TCC_COLORS.length], type: "51", focused });
        xMin = Math.min(xMin, pickup);
        xMax = Math.max(xMax, pickup * 30);
        return;
      }
      // 50-series instantaneous
      m = key.match(/^(50[A-Z]?\d+)P$/);
      if (m) {
        const elem   = m[1];
        const pickup = parseFloat(s[key]) || 0;
        if (!pickup) return;
        curves.push({ relay: node.id, label: node.id + " " + elem + " INST", pickup,
                      color: _TCC_COLORS[colorIdx++ % _TCC_COLORS.length], type: "50", focused });
        xMax = Math.max(xMax, pickup * 2);
      }
    });
  });

  if (curves.length === 0) {
    alert("No overcurrent elements found in topology.");
    return;
  }

  // Snap to clean decades
  xMin = Math.max(0.1, Math.pow(10, Math.floor(Math.log10(xMin))));
  xMax = Math.pow(10, Math.ceil(Math.log10(xMax)));

  // Resolve live current marker (sim mode only)
  let liveCurrentA = null;
  if (typeof simActive !== "undefined" && simActive && simData && focusDeviceId) {
    const node = simData.nodes.find(n => n.id === focusDeviceId);
    if (node && node.current) {
      liveCurrentA = Math.max(node.current.a.mag, node.current.b.mag, node.current.c.mag);
      if (liveCurrentA < 0.01) liveCurrentA = null;
    }
  }

  // Modal
  let modal = document.getElementById("tcc-plot-modal");
  if (!modal) {
    modal = document.createElement("div");
    modal.id = "tcc-plot-modal";
    modal.className = "config-modal";
    modal.style.cssText = "width:700px; max-height:90vh;";
    document.body.appendChild(modal);
  }
  modal.style.display = "flex";
  modal.innerHTML =
    '<div class="config-modal-header">' +
      '<span>TCC COORDINATION PLOT' + (focusDeviceId ? ": " + focusDeviceId : "") + '</span>' +
      '<span class="modal-close" onclick="this.closest(\'.config-modal\').style.display=\'none\'">[X]</span>' +
    '</div>' +
    '<div class="config-modal-body" style="padding:10px; flex-direction:column; gap:8px;">' +
      '<canvas id="tcc-canvas" width="660" height="480" style="background:#0a0a0a; border:1px solid #333; display:block;"></canvas>' +
      '<div id="tcc-legend" style="display:flex; flex-wrap:wrap; gap:8px; font-size:10px; color:#aaa;"></div>' +
    '</div>' +
    '<div class="config-modal-footer">' +
      '<button onclick="showTCCPlot(\'' + focusDeviceId + '\')" style="flex:1; border-color:#555; color:#aaa;">REFRESH</button>' +
      '<button onclick="document.getElementById(\'tcc-plot-modal\').style.display=\'none\'" class="wiz-secondary">CLOSE</button>' +
    '</div>';

  requestAnimationFrame(() => _renderTCC(curves, xMin, xMax, liveCurrentA));
}

function _renderTCC(curves, xMin, xMax, liveCurrentA) {
  const canvas = document.getElementById("tcc-canvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const W = canvas.width, H = canvas.height;
  const PAD = { top: 28, right: 20, bottom: 48, left: 62 };
  const PW  = W - PAD.left - PAD.right;
  const PH  = H - PAD.top  - PAD.bottom;
  const yMin = 0.01, yMax = 100;

  const px = I  => PAD.left + (Math.log10(I) - Math.log10(xMin)) / (Math.log10(xMax) - Math.log10(xMin)) * PW;
  const py = t  => PAD.top + PH - (Math.log10(t) - Math.log10(yMin)) / (Math.log10(yMax) - Math.log10(yMin)) * PH;

  ctx.clearRect(0, 0, W, H);
  ctx.fillStyle = "#0a0a0a";
  ctx.fillRect(0, 0, W, H);

  // Grid
  for (let d = Math.floor(Math.log10(xMin)); d <= Math.ceil(Math.log10(xMax)); d++) {
    for (let n = 1; n <= 9; n++) {
      const I = Math.pow(10, d) * n;
      if (I < xMin || I > xMax) continue;
      ctx.strokeStyle = n === 1 ? "#222" : "#161616";
      ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(px(I), PAD.top); ctx.lineTo(px(I), PAD.top + PH); ctx.stroke();
    }
  }
  for (let d = Math.floor(Math.log10(yMin)); d <= Math.ceil(Math.log10(yMax)); d++) {
    for (let n = 1; n <= 9; n++) {
      const t = Math.pow(10, d) * n;
      if (t < yMin || t > yMax) continue;
      ctx.strokeStyle = n === 1 ? "#222" : "#161616";
      ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(PAD.left, py(t)); ctx.lineTo(PAD.left + PW, py(t)); ctx.stroke();
    }
  }

  // Border
  ctx.strokeStyle = "#444";
  ctx.lineWidth = 1;
  ctx.strokeRect(PAD.left, PAD.top, PW, PH);

  // X axis labels
  ctx.fillStyle = "#777";
  ctx.font = "10px monospace";
  ctx.textAlign = "center";
  for (let d = Math.floor(Math.log10(xMin)); d <= Math.ceil(Math.log10(xMax)); d++) {
    const I = Math.pow(10, d);
    if (I < xMin * 0.99 || I > xMax * 1.01) continue;
    const label = I >= 1000 ? (I / 1000) + "kA" : I + "A";
    ctx.fillText(label, px(I), PAD.top + PH + 16);
  }
  ctx.fillStyle = "#666";
  ctx.font = "11px monospace";
  ctx.fillText("Current (A, secondary)", PAD.left + PW / 2, H - 6);

  // Y axis labels
  ctx.textAlign = "right";
  ctx.font = "10px monospace";
  ctx.fillStyle = "#777";
  for (let d = Math.floor(Math.log10(yMin)); d <= Math.ceil(Math.log10(yMax)); d++) {
    const t = Math.pow(10, d);
    if (t < yMin * 0.99 || t > yMax * 1.01) continue;
    ctx.fillText(t + "s", PAD.left - 6, py(t) + 4);
  }
  ctx.save();
  ctx.translate(12, PAD.top + PH / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.textAlign = "center";
  ctx.fillStyle = "#666";
  ctx.font = "11px monospace";
  ctx.fillText("Operating Time (s)", 0, 0);
  ctx.restore();

  // Title
  ctx.fillStyle = "#999";
  ctx.font = "bold 11px monospace";
  ctx.textAlign = "center";
  ctx.fillText("TIME-CURRENT CHARACTERISTIC (TCC)", PAD.left + PW / 2, 18);

  // Clip to plot area
  ctx.save();
  ctx.beginPath();
  ctx.rect(PAD.left, PAD.top, PW, PH);
  ctx.clip();

  const STEPS = 400;
  curves.forEach(c => {
    ctx.globalAlpha  = c.focused ? 1.0 : 0.5;
    ctx.lineWidth    = c.focused ? 2.5 : 1.5;
    ctx.strokeStyle  = c.color;

    if (c.type === "51") {
      // IDMT curve
      ctx.beginPath();
      let started = false;
      for (let s = 0; s <= STEPS; s++) {
        const I = Math.pow(10, Math.log10(xMin) + s / STEPS * (Math.log10(xMax) - Math.log10(xMin)));
        if (I <= c.pickup) continue;
        const t = _tccIdmtTime(c.curve, I / c.pickup, c.tms);
        if (!t || !isFinite(t) || t <= 0) continue;
        const x = px(I);
        const y = py(Math.max(yMin, Math.min(yMax * 2, t)));
        if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y);
      }
      ctx.stroke();

      // Pickup dashed vertical
      ctx.setLineDash([4, 4]);
      ctx.lineWidth = 1;
      ctx.globalAlpha = c.focused ? 0.6 : 0.25;
      ctx.beginPath();
      ctx.moveTo(px(c.pickup), PAD.top);
      ctx.lineTo(px(c.pickup), PAD.top + PH);
      ctx.stroke();
      ctx.setLineDash([]);

    } else if (c.type === "50") {
      // Instantaneous — solid vertical line, full height
      ctx.setLineDash([6, 3]);
      ctx.beginPath();
      ctx.moveTo(px(c.pickup), PAD.top);
      ctx.lineTo(px(c.pickup), PAD.top + PH);
      ctx.stroke();
      ctx.setLineDash([]);
    }
  });

  // Live current marker (sim mode)
  if (liveCurrentA && liveCurrentA >= xMin && liveCurrentA <= xMax) {
    ctx.globalAlpha = 0.85;
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 1.5;
    ctx.setLineDash([3, 3]);
    ctx.beginPath();
    ctx.moveTo(px(liveCurrentA), PAD.top);
    ctx.lineTo(px(liveCurrentA), PAD.top + PH);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = "#ffffff";
    ctx.font = "9px monospace";
    ctx.textAlign = "left";
    ctx.globalAlpha = 0.7;
    ctx.fillText("I=" + liveCurrentA.toFixed(1) + "A", px(liveCurrentA) + 3, PAD.top + 12);
  }

  ctx.globalAlpha = 1.0;
  ctx.restore();

  // Legend
  const legend = document.getElementById("tcc-legend");
  if (legend) {
    legend.innerHTML = curves.map(c => {
      const meta = c.type === "51"
        ? ' <span style="color:#444">(' + c.curve + ', TMS=' + c.tms + ')</span>'
        : ' <span style="color:#444">(INST)</span>';
      return '<span style="display:flex; align-items:center; gap:4px;">' +
        '<span style="display:inline-block; width:18px; height:' + (c.type === "51" ? 2 : 1) + 'px; background:' + c.color + '; opacity:' + (c.focused ? 1 : 0.5) + ';"></span>' +
        '<span style="color:' + c.color + '; font-weight:' + (c.focused ? "bold" : "normal") + '">' + c.label + '</span>' +
        meta + '</span>';
    }).join("");
  }
}
