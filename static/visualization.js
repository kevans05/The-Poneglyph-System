"use strict";

/**
 * SCADA Pro Console - Visualization Engine
 * Handles D3 rendering of the single-line diagram.
 */

const svg = d3.select("#sld-svg");
const zoomGroup = d3.select("#zoom-group");

// User-overridden wire bend fractions, keyed "srcId→tgtId" → frac (0.1–0.9).
// Populated from server-stored bend_frac on load and updated on each drag.
let _wireBends = {};

function updateWireBendsFromEdges(edges) {
    if (!edges) return;
    edges.forEach(e => {
        if (e.bend_frac == null) return;
        const sid = typeof e.source === "string" ? e.source : e.source.id;
        const tid = typeof e.target === "string" ? e.target : e.target.id;
        _wireBends[sid + "→" + tid] = e.bend_frac;
    });
}

// True when the current zoom scale is at/below the single-line threshold, i.e.
// each 3-phase run should collapse to one conductor coloured by voltage class.
let _singleLineMode = false;

function _singleLineThreshold() {
  const t =
    typeof window !== "undefined" && window.PoneglyphSettings
      ? Number(window.PoneglyphSettings.get("singleLineZoom"))
      : 0.55;
  return t > 0 ? t : 0.55;
}

function isSingleLineMode() {
  return _singleLineMode;
}

const zoom = d3
  .zoom()
  .scaleExtent([0.1, 10])
  .on("zoom", (e) => {
    zoomGroup.attr("transform", e.transform);
    updateMinimapViewport();
    const nowSingle = e.transform.k <= _singleLineThreshold();
    if (nowSingle !== _singleLineMode) {
      _singleLineMode = nowSingle;
      // Only the edge/glyph representation changes — a full re-render is fine
      // here because zoom-threshold crossings are rare relative to zoom ticks.
      if (currentData) render3LD(currentData);
    }
  });

svg.call(zoom);

// Re-render when the palette / threshold settings change.
if (typeof window !== "undefined" && window.PoneglyphSettings) {
  window.PoneglyphSettings.subscribe(() => {
    _singleLineMode = _currentZoomK() <= _singleLineThreshold();
    if (currentData) render3LD(currentData);
  });
}

function _currentZoomK() {
  try {
    return d3.zoomTransform(svg.node()).k;
  } catch (e) {
    return 1;
  }
}

// ── Voltage-class helpers ────────────────────────────────────────────────────

// ── Voltage-class zones ─────────────────────────────────────────────────────
//
// A device rarely carries its own kV nameplate (a breaker or a bus doesn't),
// so we flood the network: every galvanically-connected run is one voltage
// zone, seeded from whatever DOES name a class (a source, a regulator, a
// manual `voltage_class_kv`, or a transformer terminal), and a transformer is
// the boundary between two zones — pri_kv on its H side, sec_kv on its X side.

let _zoneKv = {};                 // node id → resolved zone kV
let _xfmrTerminalKv = {};         // "<xfmrId>|<neighbourId>" → kV at that terminal
const _PRIMARY_EDGE = (e) => !e.type || e.type === "primary";
const _rid = (v) => (typeof v === "string" ? v : v && v.id);

// kV a device explicitly declares on its own (NOT pri/sec — those belong to a
// transformer terminal, handled separately).
function _explicitNodeKv(node) {
  const p = (node && node.params) || {};
  return (
    Number(p.voltage_class_kv) ||
    Number(p.nominal_voltage_kv) ||
    Number(p.nominal_kv) ||
    Number(p.kv_rating) ||
    0
  );
}

function _computeVoltageZones(data) {
  _zoneKv = {};
  _xfmrTerminalKv = {};
  const nodes = (data && data.nodes) || [];
  const edges = ((data && data.edges) || []).filter(_PRIMARY_EDGE);
  const byId = {};
  nodes.forEach((n) => (byId[n.id] = n));
  const isXfmr = (n) => !!n && n.type === "PowerTransformer";

  // Flood explicit classes across primary edges, never through a transformer.
  const flood = () => {
    let changed = true, guard = 0;
    while (changed && guard++ < 100) {
      changed = false;
      edges.forEach((e) => {
        const a = _rid(e.source), b = _rid(e.target);
        if (isXfmr(byId[a]) || isXfmr(byId[b])) return;
        const ka = _zoneKv[a] || 0, kb = _zoneKv[b] || 0;
        if (ka > 0 && !(kb > 0)) { _zoneKv[b] = ka; changed = true; }
        else if (kb > 0 && !(ka > 0)) { _zoneKv[a] = kb; changed = true; }
      });
    }
  };

  // 1. Explicit self-declared classes seed their node, then flood.
  nodes.forEach((n) => {
    if (isXfmr(n)) return;
    const kv = _explicitNodeKv(n);
    if (kv > 0) _zoneKv[n.id] = kv;
  });
  flood();

  // 2. Resolve each transformer terminal. The backend's source/target_bushing
  //    is unreliable for transformers, so decide per neighbour:
  //      • if the neighbour already has a zone kV, pick the winding (pri/sec)
  //        closest to it;
  //      • else fall back to geometry (which side of the transformer it sits on).
  nodes.filter(isXfmr).forEach((xn) => {
    const p = xn.params || {};
    const override = Number(p.voltage_class_kv) || 0;
    const pri = Number(p.pri_kv) || 0;
    const sec = Number(p.sec_kv) || 0;
    // neighbours of this transformer over primary edges
    const nbrs = [];
    edges.forEach((e) => {
      const a = _rid(e.source), b = _rid(e.target);
      if (a === xn.id && b !== xn.id) nbrs.push(b);
      else if (b === xn.id && a !== xn.id) nbrs.push(a);
    });
    [...new Set(nbrs)].forEach((nId) => {
      const nn = byId[nId];
      let kv = override;
      if (!kv) {
        const z = _zoneKv[nId] || 0;
        if (z > 0 && pri && sec) {
          kv = Math.abs(z - pri) <= Math.abs(z - sec) ? pri : sec;
        } else if (xn.gx != null && nn && nn.gx != null) {
          const b = facingBushing(xn.gx, xn.gy, xn.rotation || 0, nn.gx, nn.gy);
          kv = b === "H" ? pri || sec : sec || pri;
        } else {
          kv = pri || sec;
        }
      }
      if (kv > 0) {
        _xfmrTerminalKv[xn.id + "|" + nId] = kv;
        if (nn && !isXfmr(nn) && !(_zoneKv[nId] > 0)) _zoneKv[nId] = kv;
      }
    });
  });

  // 3. Flood again with the transformer neighbours now seeded.
  flood();

  // 4. Sensors (CT/VT) inherit from the equipment they sit on.
  nodes.forEach((n) => {
    if (_zoneKv[n.id] > 0) return;
    if (!["CurrentTransformer", "VoltageTransformer", "DualWindingVT"].includes(n.type)) return;
    const hostId = n.summary && n.summary.Location;
    if (hostId && _zoneKv[hostId] > 0) _zoneKv[n.id] = _zoneKv[hostId];
  });
}

// Resolved kV for a node: manual override → flooded zone → own nameplate.
function _nodeVoltageKv(node) {
  if (!node) return 0;
  const p = node.params || {};
  if (Number(p.voltage_class_kv) > 0) return Number(p.voltage_class_kv);
  if (_zoneKv[node.id] > 0) return _zoneKv[node.id];
  for (const c of [p.nominal_voltage_kv, p.nominal_kv, p.kv_rating, p.pri_kv, p.sec_kv]) {
    if (Number(c) > 0) return Number(c);
  }
  return 0;
}
// Shared so the settings modal can enumerate the substation's actual classes.
window.nodeVoltageKv = _nodeVoltageKv;

// kV a node presents toward a specific neighbour — transformer terminals differ
// per side; everything else is just its zone kV.
function _nodeVoltageKvToward(node, neighbourId) {
  if (node && node.type === "PowerTransformer") {
    const t = _xfmrTerminalKv[node.id + "|" + neighbourId];
    if (t > 0) return t;
    const p = node.params || {};
    return Number(p.voltage_class_kv) || Number(p.pri_kv) || Number(p.sec_kv) || 0;
  }
  return _nodeVoltageKv(node);
}

// kV for an edge = the higher class of its two endpoints, each evaluated toward
// the other end (so a transformer's two runs get their own classes).
function _edgeVoltageKv(src, tgt) {
  return Math.max(
    _nodeVoltageKvToward(src, tgt && tgt.id),
    _nodeVoltageKvToward(tgt, src && src.id),
  );
}

function _edgeSingleLineColor(src, tgt) {
  const on =
    typeof window !== "undefined" && window.PoneglyphSettings
      ? window.PoneglyphSettings.get("colorByVoltageClass")
      : true;
  if (on && typeof window.voltageClassColor === "function") {
    return window.voltageClassColor(_edgeVoltageKv(src, tgt));
  }
  return null; // use the stylesheet default
}

// Colour for a device's one-line symbol: its voltage class, or a neutral tint.
function _nodeSingleLineColor(d) {
  const on =
    typeof window !== "undefined" && window.PoneglyphSettings
      ? window.PoneglyphSettings.get("colorByVoltageClass")
      : true;
  if (on && typeof window.voltageClassColor === "function") {
    return window.voltageClassColor(_nodeVoltageKv(d));
  }
  return "#cfd8dc";
}

// Device types that get an IEEE/IEC one-line schematic symbol when zoomed out.
const _ONE_LINE_TYPES = new Set([
  "CircuitBreaker",
  "Disconnect",
  "CurrentTransformer",
  "VoltageTransformer",
  "DualWindingVT",
  "PowerTransformer",
  "AuxiliaryTransformer",
  "VoltageRegulator",
  "VoltageSource",
  "Load",
]);

// Secondary / instrument-circuit devices hidden in one-line mode (they and
// their secondary wiring only clutter the primary power path).
const _SECONDARY_TYPES = new Set([
  "CurrentTransformer",
  "VoltageTransformer",
  "DualWindingVT",
  "CTTB",
  "FTBlock",
  "IsoBlock",
  "Relay",
  "Meter",
]);

function _isClosedStatus(d) {
  return String((d.summary || {}).Status || "").toUpperCase().startsWith("CLOSED");
}

/**
 * Draw a standard one-line schematic symbol for `d` into group `el`.
 * Symbols straddle a horizontal conductor through the local origin (y = 0),
 * matching the single-line wire runs. Coloured by voltage class.
 */
// Solid state colours for switching devices (utility convention: red = closed
// / energised, green = open / safe).
const _SW_CLOSED = "#e5352b";
const _SW_OPEN = "#1fbf4d";

// Small H / X bushing labels at the top corners of a two-terminal glyph.
function _addHXLabels(el, half, opts) {
  opts = opts || { h: true, x: true };
  if (opts.h) {
    el.append("text").attr("x", -half).attr("y", -half - 3)
      .attr("text-anchor", "middle").attr("fill", "#9aa")
      .style("font-size", "7px").style("font-weight", "bold").text("H");
  }
  if (opts.x) {
    el.append("text").attr("x", half).attr("y", -half - 3)
      .attr("text-anchor", "middle").attr("fill", "#9aa")
      .style("font-size", "7px").style("font-weight", "bold").text("X");
  }
}

function _drawOneLineSymbol(el, d) {
  const c = _nodeSingleLineColor(d);
  const line = (x1, x2, col, w) =>
    el.append("line").attr("x1", x1).attr("y1", 0).attr("x2", x2).attr("y2", 0)
      .attr("stroke", col || c).attr("stroke-width", w || 2).attr("stroke-linecap", "round");

  if (d.type === "CircuitBreaker") {
    const closed = _isClosedStatus(d);
    line(-22, -8, c, 2);
    line(8, 22, c, 2);
    el.append("rect")
      .attr("x", -8).attr("y", -8).attr("width", 16).attr("height", 16)
      .attr("fill", closed ? _SW_CLOSED : _SW_OPEN)
      .attr("stroke", c).attr("stroke-width", 2);
    _addHXLabels(el, 18);
    return;
  }

  if (d.type === "Disconnect") {
    const closed = _isClosedStatus(d);
    const blade = closed ? _SW_CLOSED : _SW_OPEN;
    line(-22, -9, c, 2);
    el.append("circle").attr("cx", -9).attr("cy", 0).attr("r", 2.4).attr("fill", c);
    el.append("circle").attr("cx", 9).attr("cy", 0).attr("r", 2.4).attr("fill", c);
    if (closed) {
      el.append("line").attr("x1", -9).attr("y1", 0).attr("x2", 9).attr("y2", 0)
        .attr("stroke", blade).attr("stroke-width", 3).attr("stroke-linecap", "round");
    } else {
      el.append("line").attr("x1", -9).attr("y1", 0).attr("x2", 7).attr("y2", -16)
        .attr("stroke", blade).attr("stroke-width", 3).attr("stroke-linecap", "round");
    }
    line(9, 22, c, 2);
    _addHXLabels(el, 18);
    return;
  }

  if (d.type === "CurrentTransformer") {
    line(-22, 22, c, 2);
    el.append("circle").attr("cx", 0).attr("cy", 0).attr("r", 7)
      .attr("fill", "none").attr("stroke", c).attr("stroke-width", 1.8);
    _addHXLabels(el, 14);
    return;
  }

  if (d.type === "VoltageTransformer" || d.type === "DualWindingVT") {
    line(-22, 0, c, 2);
    el.append("circle").attr("cx", 0).attr("cy", -3).attr("r", 6)
      .attr("fill", "none").attr("stroke", c).attr("stroke-width", 1.6);
    el.append("circle").attr("cx", 0).attr("cy", 5).attr("r", 6)
      .attr("fill", "none").attr("stroke", c).attr("stroke-width", 1.6);
    if (d.type === "DualWindingVT") {
      el.append("circle").attr("cx", 0).attr("cy", 13).attr("r", 5)
        .attr("fill", "none").attr("stroke", c).attr("stroke-width", 1.3).attr("opacity", 0.85);
    }
    // ground reference
    const gy = d.type === "DualWindingVT" ? 21 : 15;
    el.append("line").attr("x1", 0).attr("y1", d.type === "DualWindingVT" ? 18 : 11).attr("x2", 0).attr("y2", gy).attr("stroke", c).attr("stroke-width", 1.4);
    el.append("line").attr("x1", -6).attr("y1", gy).attr("x2", 6).attr("y2", gy).attr("stroke", c).attr("stroke-width", 1.4);
    el.append("line").attr("x1", -3.5).attr("y1", gy + 3).attr("x2", 3.5).attr("y2", gy + 3).attr("stroke", c).attr("stroke-width", 1.2);
    _addHXLabels(el, 12, { h: true, x: false });
    return;
  }

  if (d.type === "PowerTransformer" || d.type === "AuxiliaryTransformer") {
    const r = d.type === "AuxiliaryTransformer" ? 10 : 13;
    const dx = r * 0.7;
    // Colour each lead by its own winding class (H = pri, X = sec).
    const on =
      !window.PoneglyphSettings || window.PoneglyphSettings.get("colorByVoltageClass");
    const p = d.params || {};
    const ovr = Number(p.voltage_class_kv) || 0;
    const cH = on && d.type === "PowerTransformer" && typeof window.voltageClassColor === "function"
      ? window.voltageClassColor(ovr || Number(p.pri_kv) || 0) : c;
    const cX = on && d.type === "PowerTransformer" && typeof window.voltageClassColor === "function"
      ? window.voltageClassColor(ovr || Number(p.sec_kv) || 0) : c;
    // Each winding circle takes its own side's class colour.
    const circH = d.type === "PowerTransformer" ? cH : c;
    const circX = d.type === "PowerTransformer" ? cX : c;
    line(-r - dx - 6, -dx, circH, 2);
    line(dx, r + dx + 6, circX, 2);
    el.append("circle").attr("cx", -dx).attr("cy", 0).attr("r", r)
      .attr("fill", "none").attr("stroke", circH).attr("stroke-width", 2);
    el.append("circle").attr("cx", dx).attr("cy", 0).attr("r", r)
      .attr("fill", "none").attr("stroke", circX).attr("stroke-width", 2);
    if (d.type === "PowerTransformer") {
      const wsym = (cx, w, col) => {
        const t = String(w || "").toUpperCase();
        if (t.startsWith("D")) {
          el.append("path").attr("d", `M ${cx} -5 L ${cx + 5} 4 L ${cx - 5} 4 Z`)
            .attr("fill", "none").attr("stroke", col).attr("stroke-width", 1.3);
        } else {
          el.append("path").attr("d", `M ${cx} 4 L ${cx} -4 M ${cx} 4 L ${cx + 4.5} 8 M ${cx} 4 L ${cx - 4.5} 8`)
            .attr("fill", "none").attr("stroke", col).attr("stroke-width", 1.3);
        }
      };
      wsym(-dx, d.params.h_winding || "Y", circH);
      wsym(dx, d.params.x_winding || "D", circX);
    }
    _addHXLabels(el, r + dx + 2);
    return;
  }

  if (d.type === "VoltageRegulator") {
    line(-22, -13, c, 2);
    line(13, 22, c, 2);
    el.append("circle").attr("cx", 0).attr("cy", 0).attr("r", 13)
      .attr("fill", "none").attr("stroke", c).attr("stroke-width", 2);
    el.append("line").attr("x1", -9).attr("y1", 9).attr("x2", 9).attr("y2", -9)
      .attr("stroke", c).attr("stroke-width", 1.6);
    el.append("path").attr("d", "M 5 -9 L 9 -9 L 9 -5")
      .attr("fill", "none").attr("stroke", c).attr("stroke-width", 1.6);
    _addHXLabels(el, 15);
    return;
  }

  if (d.type === "VoltageSource") {
    const col = _nodeVoltageKv(d) > 0 ? c : "#ffaa00";
    line(13, 22, col, 2);
    el.append("circle").attr("cx", 0).attr("cy", 0).attr("r", 13)
      .attr("fill", "#0d0d0d").attr("stroke", col).attr("stroke-width", 2);
    el.append("path").attr("d", "M -7 0 Q -3.5 -7 0 0 T 7 0")
      .attr("fill", "none").attr("stroke", col).attr("stroke-width", 1.8);
    return;
  }

  if (d.type === "Load") {
    line(-22, -2, c, 2);
    el.append("path").attr("d", "M -2 -7 L 12 0 L -2 7 Z")
      .attr("fill", c).attr("stroke", c).attr("stroke-width", 1);
    return;
  }
}

// Fill the empty stretch of a single-line run: a terminal stud at each device
// end, plus evenly spaced insulator/bushing marks along straight runs.
function _drawRunDecor(g, a1, a2, color) {
  const col = color || "#9aa";
  const deco = g.append("g").attr("class", "run-decor").style("pointer-events", "none");
  [a1, a2].forEach((pt) => {
    deco.append("circle")
      .attr("cx", pt.x).attr("cy", pt.y).attr("r", 3)
      .attr("fill", col).attr("stroke", "none");
  });
  g = deco;

  const dx = a2.x - a1.x, dy = a2.y - a1.y;
  const len = Math.hypot(dx, dy);
  const straight = Math.abs(dx) < 8 || Math.abs(dy) < 8;
  if (!straight || len < 130) return;

  const ux = dx / len, uy = dy / len;      // along the run
  const px = -uy, py = ux;                  // perpendicular
  const GAP = 70, INSET = 48;
  for (let s = INSET; s <= len - INSET; s += GAP) {
    const cx = a1.x + ux * s, cy = a1.y + uy * s;
    for (const o of [-2.5, 2.5]) {          // two parallel ticks = one insulator
      const bx = cx + ux * o, by = cy + uy * o;
      g.append("line")
        .attr("x1", bx + px * 4).attr("y1", by + py * 4)
        .attr("x2", bx - px * 4).attr("y2", by - py * 4)
        .attr("stroke", col).attr("stroke-width", 1.6).attr("stroke-linecap", "round");
    }
  }
}

function facingBushing(fromX, fromY, fromAngle, toX, toY) {
  const rad = -(fromAngle * Math.PI) / 180;
  const dx = toX - fromX;
  const dy = toY - fromY;
  const localX = dx * Math.cos(rad) - dy * Math.sin(rad);
  return localX >= 0 ? "X" : "H";
}

function getAnchorPoint(x, y, angle, bushing, offset, radialOffset = 55) {
  const rad = (angle * Math.PI) / 180;
  const relX = (bushing === "H" ? -1 : 1) * radialOffset;
  const relY = offset;
  const rotX = relX * Math.cos(rad) - relY * Math.sin(rad);
  const rotY = relX * Math.sin(rad) + relY * Math.cos(rad);
  return { x: x + rotX, y: y + rotY };
}

function getPathData(x1, y1, x2, y2, offset, frac = 0.5) {
  const dx = x2 - x1, dy = y2 - y1;
  
  // To keep 3-phase lines neat and parallel, we stagger the elbow midpoint
  // based on the phase offset. This prevents bunching at the vertical/horizontal
  // transitions without over-stretching or crossing lines.
  const stagger = (offset / 16) * 0.04;
  const f = Math.max(0.1, Math.min(0.9, frac + stagger));

  if (Math.abs(dx) >= Math.abs(dy)) {
    // Horizontal-ish (H-V-H path)
    const midX = x1 + dx * f;
    return `M ${x1},${y1} L ${midX},${y1} L ${midX},${y2} L ${x2},${y2}`;
  } else {
    // Vertical-ish (V-H-V path)
    const midY = y1 + dy * f;
    return `M ${x1},${y1} L ${x1},${midY} L ${x2},${midY} L ${x2},${y2}`;
  }
}

function render3LD(data) { if (!data || !data.nodes) return;
  zoomGroup.selectAll("*").remove();

  zoomGroup
    .append("rect")
    .attr("width", 20000)
    .attr("height", 20000)
    .attr("x", -10000)
    .attr("y", -10000)
    .attr("fill", "transparent")
    .style("pointer-events", "all")
    .on("contextmenu", (e) => {
      e.preventDefault();
      const [x, y] = d3.pointer(e, zoomGroup.node());
      showPlantMenu(e.pageX, e.pageY, snapToGrid(x), snapToGrid(y));
    });

  // 1. Position Nodes
  data.nodes.forEach((node, i) => {
    if (node.gx === null || node.gx === undefined) {
      if (
        ["CurrentTransformer", "VoltageTransformer", "DualWindingVT"].includes(
          node.type,
        )
      ) {
        const host = data.nodes.find((n) => n.id ===  (node.summary || {}) .Location);
        if (host) {
          const b =  (node.summary || {}) .Bushing || "X",
            p =  (node.summary || {}) .Position || "inner",
            r = { inner: 70, middle: 95, outer: 120 }[p] || 70;
          const a = getAnchorPoint(
            host.gx || 0,
            host.gy || 400,
            host.rotation || 0,
            b,
            0,
            r,
          );
          node.gx = snapToGrid(a.x);
          node.gy = snapToGrid(a.y);
        } else {
          node.gx = snapToGrid(150 + i * 100);
          node.gy = snapToGrid(100);
        }
      } else {
        node.gx = snapToGrid(150 + i * 400);
        node.gy = snapToGrid(400);
      }
    }
  });

  // Resolve voltage-class zones now that every node has a position (the
  // transformer-terminal fallback needs geometry).
  _computeVoltageZones(data);

  // In one-line mode, hide the secondary / instrument-circuit devices (CT, VT,
  // test blocks, relays, metering) and every secondary wire.
  const hiddenIds = new Set();
  if (_singleLineMode) {
    data.nodes.forEach((n) => {
      if (_SECONDARY_TYPES.has(n.type)) hiddenIds.add(n.id);
    });
  }
  const _secondaryEdge = (e) =>
    ["protection", "protection2", "dc", "trip", "close"].includes(e.type);

  // 2. Draw Edges
  const linkGroup = zoomGroup.append("g").attr("id", "links");

  // Pre-pass: stagger bend fractions for edges that share a source or target
  // so their elbows land at different points instead of all bunching at 50%.
  // User-dragged bends (_wireBends) take priority and are also synced from
  // server-stored bend_frac on each full topology load.
  const _resolveId = v => typeof v === "string" ? v : v.id;
  const _bendFrac = {};
  const _bySrc = {}, _byTgt = {};
  data.edges.forEach(edge => {
    const sid = _resolveId(edge.source), tid = _resolveId(edge.target);
    const key = sid + "→" + tid;
    // Server-stored bend_frac is the baseline; user drag overrides further.
    if (edge.bend_frac != null) _wireBends[key] = edge.bend_frac;
    _bendFrac[key] = _wireBends[key] ?? 0.5;
    (_bySrc[sid] = _bySrc[sid] || []).push(key);
    (_byTgt[tid] = _byTgt[tid] || []).push(key);
  });
  const _stagger = (keys) => {
    if (keys.length < 2) return;
    keys.forEach((k, j) => {
      // Only auto-stagger edges that have no user override
      if (_wireBends[k] == null) _bendFrac[k] = 0.3 + 0.4 * (j / (keys.length - 1));
    });
  };
  Object.values(_byTgt).forEach(_stagger);
  // Only apply source stagger if not already moved by target stagger
  Object.values(_bySrc).forEach(keys => {
    if (keys.length < 2) return;
    keys.forEach((k, j) => {
      if (_wireBends[k] == null && _bendFrac[k] === 0.5)
        _bendFrac[k] = 0.3 + 0.4 * (j / (keys.length - 1));
    });
  });

  data.edges.forEach((edge) => {
    const src = data.nodes.find(n => n.id === _resolveId(edge.source));
    const tgt = data.nodes.find(n => n.id === _resolveId(edge.target));
    if (!src || !tgt) return;

    // One-line mode: drop secondary wiring and anything touching a hidden device.
    if (_singleLineMode && (_secondaryEdge(edge) || hiddenIds.has(src.id) || hiddenIds.has(tgt.id))) {
      return;
    }

    const frac = _bendFrac[src.id + "→" + tgt.id] ?? 0.5;

    const _wireRightClick = (srcId, tgtId) => (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (confirm("Delete wire: " + srcId + " → " + tgtId + "?")) {
        breakConnection(srcId, tgtId);
      }
    };

    if (edge.type === "protection" || edge.type === "protection2" || edge.type === "dc" || edge.type === "trip" || edge.type === "close") {
      let wireClass = "secondary-wire";
      if (edge.type === "dc") wireClass = "dc-wire";
      else if (edge.type === "trip") wireClass = "trip-wire";
      else if (edge.type === "close") wireClass = "close-wire";
      else if (edge.type === "protection2") wireClass = "vt2-wire";
      else if (["CurrentTransformer", "CTTB"].includes(src.type))
        wireClass = "ct-wire";
      else if (
        ["VoltageTransformer", "DualWindingVT", "FTBlock", "IsoBlock"].includes(
          src.type,
        )
      )
        wireClass = "vt-wire";

      const pathD = getPathData(src.gx, src.gy, tgt.gx, tgt.gy, 0, frac);
      // Invisible wide hit area — right-click anywhere near the wire to delete it
      linkGroup
        .append("path")
        .attr("class", "wire-hit")
        .attr("d", pathD)
        .on("contextmenu", _wireRightClick(src.id, tgt.id));
      linkGroup
        .append("path")
        .attr("class", wireClass)
        .attr("d", pathD)
        .attr("data-src", src.id)
        .attr("data-tgt", tgt.id)
        .attr("data-x1", src.gx)
        .attr("data-y1", src.gy)
        .attr("data-x2", tgt.gx)
        .attr("data-y2", tgt.gy)
        .attr("data-offset", 0)
        .attr("data-frac", frac)
        .on("contextmenu", _wireRightClick(src.id, tgt.id));
      _addWireBendHandle(linkGroup, src.gx, src.gy, tgt.gx, tgt.gy, frac, src.id, tgt.id);
    } else {
      const srcB = edge.source_bushing ||
        facingBushing(src.gx, src.gy, src.rotation || 0, tgt.gx, tgt.gy);
      const tgtB = edge.target_bushing ||
        facingBushing(tgt.gx, tgt.gy, tgt.rotation || 0, src.gx, src.gy);

      // Determine wire count based on connection type
      let isDelta = false;
      if (src.type === "PowerTransformer") {
        const winding =
          srcB === "H" ? src.params.h_winding : src.params.x_winding;
        if (winding && winding.toUpperCase().startsWith("D")) isDelta = true;
      } else if (src.summary && src.summary.Connection) {
        if (src.summary.Connection && src.summary.Connection.includes("Delta")) isDelta = true;
      }

      // Zoomed out: collapse the whole run to one conductor at offset 0.
      const offsets = _singleLineMode
        ? [0]
        : isDelta
          ? [-PHASE_GAP, 0, PHASE_GAP]
          : [-PHASE_GAP, 0, PHASE_GAP, PHASE_GAP * 2];
      const classes = _singleLineMode
        ? ["single-line"]
        : isDelta
          ? ["phase-a", "phase-b", "phase-c"]
          : ["phase-a", "phase-b", "phase-c", "neutral"];

      const slColor = _singleLineMode ? _edgeSingleLineColor(src, tgt) : null;
      // Zoomed out: attach the run closer to each symbol to tighten the gap.
      const RO = _singleLineMode ? 40 : 55;

      // One hit area per logical connection (not per phase)
      const a1mid = getAnchorPoint(src.gx, src.gy, src.rotation || 0, srcB, 0, RO);
      const a2mid = getAnchorPoint(tgt.gx, tgt.gy, tgt.rotation || 0, tgtB, 0, RO);
      linkGroup
        .append("path")
        .attr("class", "wire-hit")
        .attr("d", getPathData(a1mid.x, a1mid.y, a2mid.x, a2mid.y, 0, frac))
        .on("contextmenu", _wireRightClick(src.id, tgt.id));

      offsets.forEach((off, i) => {
        const a1 = getAnchorPoint(src.gx, src.gy, src.rotation || 0, srcB, off, RO),
          a2 = getAnchorPoint(tgt.gx, tgt.gy, tgt.rotation || 0, tgtB, off, RO);
        const path = linkGroup
          .append("path")
          .attr("class", "link-wire " + classes[i])
          .attr("d", getPathData(a1.x, a1.y, a2.x, a2.y, off, frac))
          .attr("data-src", src.id)
          .attr("data-tgt", tgt.id)
          .attr("data-x1", a1.x)
          .attr("data-y1", a1.y)
          .attr("data-x2", a2.x)
          .attr("data-y2", a2.y)
          .attr("data-offset", off)
          .attr("data-frac", frac)
          .on("contextmenu", _wireRightClick(src.id, tgt.id));
        if (slColor) path.style("stroke", slColor);
      });
      if (_singleLineMode) {
        _drawRunDecor(linkGroup, a1mid, a2mid, slColor || "#9aa");
      }
      // Handle appended AFTER phase paths so it sits on top in Z-order
      _addWireBendHandle(linkGroup, a1mid.x, a1mid.y, a2mid.x, a2mid.y, frac, src.id, tgt.id);
    }
  });

  // 3. Draw Nodes
  const visibleNodes = hiddenIds.size
    ? data.nodes.filter((n) => !hiddenIds.has(n.id))
    : data.nodes;
  const nodeGroup = zoomGroup
    .append("g")
    .attr("id", "nodes")
    .selectAll(".node")
    .data(visibleNodes)
    .enter()
    .append("g")
    .attr(
      "transform",
      (d) =>
        "translate(" +
        d.gx +
        "," +
        d.gy +
        ") rotate(" +
        (d.rotation || 0) +
        ")",
    )
    .attr("class", (d) => "node " + d.type)
    .call(
      d3
        .drag()
        .on("start", function () {
          d3.select(this).raise();
        })
        .on("drag", function (event, d) {
          d.gx = snapToGrid(event.x);
          d.gy = snapToGrid(event.y);
          d3.select(this).attr(
            "transform",
            "translate(" +
              d.gx +
              "," +
              d.gy +
              ") rotate(" +
              (d.rotation || 0) +
              ")",
          );
          updateLinksDuringDrag(
            d.id,
            d.gx,
            d.gy,
            d.rotation || 0,
            data,
            linkGroup,
          );
        })
        .on("end", function (event, d) {
          reconfigureAPI(d.id, "update_position", { gx: d.gx, gy: d.gy });
        }),
    )
    .on("click", (e, d) => {
      if (!e.defaultPrevented) {
        if (typeof isSelecting === "function" && isSelecting()) {
          e.stopPropagation();
          toggleDeviceSelection(d.id);
        } else {
          handleNodeInteraction(e, d);
        }
      }
    })
    .on("contextmenu", (e, d) => showContextMenu(e, d));

  nodeGroup.each(function (d) {
    const el = d3.select(this);
    el.append("circle").attr("class", "node-hitbox").attr("r", 60);

    // Fault Highlight
    const hasFault = d.fault_state;
    if (hasFault) {
        el.append("circle")
            .attr("r", 50)
            .attr("fill", "rgba(255,0,0,0.1)")
            .attr("stroke", "#f00")
            .attr("stroke-width", 3)
            .attr("stroke-dasharray", "5,5");
        
        el.append("text")
            .attr("y", 60)
            .attr("text-anchor", "middle")
            .attr("fill", "#f00")
            .style("font-size", "10px")
            .style("font-weight", "bold")
            .text("!!! FAULT !!!");
    }

    // Draw symbols...
    if (_singleLineMode && _ONE_LINE_TYPES.has(d.type)) {
      // Zoomed out: standard one-line schematic symbol, coloured by voltage class.
      _drawOneLineSymbol(el, d);
    } else if (d.type === "CurrentTransformer") {
      // 3-Phase Circular CT with winding loop and polarity
      const sw = d.params.secondary_wiring || "Y";
      const phases = (sw === "A") ? [0] : (sw === "B") ? [1] : (sw === "C") ? [2] : (sw === "N") ? [3] : [0, 1, 2];
      
      phases.forEach(idx => {
        const off = (idx === 3) ? PHASE_GAP * 2 : [-PHASE_GAP, 0, PHASE_GAP][idx];
        const c = (idx === 3) ? "#666" : ["#f00", "#ff0", "#00f"][idx];
        
        // The CT Circle on the line
        el.append("circle").attr("cx", 0).attr("cy", off).attr("r", 8).attr("fill", "none").attr("stroke", c).attr("stroke-width", 1.5);
        // The winding loop (secondary)
        el.append("path").attr("d", `M -6 ${off} A 6 6 0 1 0 6 ${off}`).attr("fill", "none").attr("stroke", c).attr("stroke-width", 1.5);
        // Polarity Dot
        el.append("circle").attr("cx", -6).attr("cy", off - 6).attr("r", 2).attr("fill", "#ffff00").attr("stroke", "none");
      });
    } else if (d.type === "VoltageTransformer" || d.type === "DualWindingVT") {
      // Magnetic VT symbol (overlapping primary/secondary coils)
      [-PHASE_GAP, 0, PHASE_GAP].forEach((off, i) => {
        const c = ["#f00", "#ff0", "#00f"][i];
        // Primary coil (connected to line)
        el.append("circle").attr("cx", 0).attr("cy", off).attr("r", 8).attr("fill", "none").attr("stroke", c).attr("stroke-width", 1.5);
        // Secondary coil 1 (overlapping)
        el.append("circle").attr("cx", 0).attr("cy", off + 10).attr("r", 8).attr("fill", "none").attr("stroke", c).attr("stroke-width", 1.5);
        
        if (d.type === "DualWindingVT") {
          // Secondary coil 2 (further overlap)
          el.append("circle").attr("cx", 0).attr("cy", off + 18).attr("r", 8).attr("fill", "none").attr("stroke", c).attr("stroke-width", 1.2).attr("opacity", 0.8);
          // Polarity Dot for W2
          el.append("circle").attr("cx", -6).attr("cy", off + 12).attr("r", 1.8).attr("fill", "#f00");
        }

        // Polarity Dots for Pri and W1
        el.append("circle").attr("cx", -6).attr("cy", off - 6).attr("r", 1.8).attr("fill", "#f00");
        el.append("circle").attr("cx", -6).attr("cy", off + 4).attr("r", 1.8).attr("fill", "#f00");
      });
      if (d.type === "DualWindingVT")
        el.append("circle").attr("cx", 0).attr("cy", 0).attr("r", 35).attr("fill", "none").attr("stroke", "#555").attr("stroke-dasharray", "3,3");
    } else if (d.type === "CTTB" || d.type === "FTBlock") {
      const c = d.type === "CTTB" ? "#ffff22" : "#ff3333";
      el.append("rect").attr("x", -15).attr("y", -25).attr("width", 30).attr("height", 50).attr("fill", "#0a0a0a").attr("stroke", c).attr("stroke-width", 2);
      el.append("text").attr("y", -32).attr("text-anchor", "middle").attr("fill", c).style("font-size", "8px").style("font-weight", "bold").text(d.type);
      for (let i = -18; i <= 18; i += 9) {
        el.append("circle").attr("cx", -8).attr("cy", i).attr("r", 2.5).attr("fill", "#333").attr("stroke", c);
        el.append("line").attr("x1", -5).attr("y1", i).attr("x2", 5).attr("y2", i).attr("stroke", "#444").attr("stroke-dasharray", "2,1");
        el.append("circle").attr("cx", 8).attr("cy", i).attr("r", 2.5).attr("fill", "#333").attr("stroke", c);
      }
    } else if (d.type === "Meter") {
      // Circle with M for Meter
      el.append("circle").attr("r", 25).attr("fill", "#1a1a1a").attr("stroke", "#fff").attr("stroke-width", 2);
      el.append("text").attr("dy", 5).attr("text-anchor", "middle").attr("fill", "#fff").style("font-size", "14px").style("font-weight", "bold").text("M");
    } else if (d.type === "AuxiliaryTransformer") {
      // Small rectangle with overlap circles for AUX TX
      el.append("rect").attr("x", -20).attr("y", -15).attr("width", 40).attr("height", 30).attr("fill", "#111").attr("stroke", "#888").attr("stroke-width", 1.5);
      el.append("circle").attr("cx", -6).attr("cy", 0).attr("r", 8).attr("fill", "none").attr("stroke", "#fff").attr("stroke-width", 1.2);
      el.append("circle").attr("cx", 6).attr("cy", 0).attr("r", 8).attr("fill", "none").attr("stroke", "#fff").attr("stroke-width", 1.2);
      el.append("text").attr("y", -22).attr("text-anchor", "middle").attr("fill", "#aaa").style("font-size", "7px").text("AUX TX");
    } else if (d.type === "Relay") {
      // Blue Circle Relay Symbol with ANSI number
      el.append("circle").attr("r", 30).attr("fill", "#001a33").attr("stroke", "#0088ff").attr("stroke-width", 2.5);
      el.append("text")
        .attr("dy", 6)
        .attr("text-anchor", "middle")
        .attr("fill", "#00ccff")
        .style("font-size", "14px")
        .style("font-weight", "bold")
        .style("font-family", "Arial")
        .text( ( (d.summary || {})  || {}) .Function || "87");
    } else if (d.type === "PowerTransformer") {
      // High-Fidelity Scalloped Winding Representation
      const drawWinding = (cx, cy, color, type, isHighSide) => {
        const g = el.append("g").attr("transform", `translate(${cx}, ${cy})`);
        
        // Vertical Scalloped Coil (3 full turns)
        const coilPath = "M 0 -24 Q 15 -18 0 -12 Q 15 -6 0 0 Q 15 6 0 12 Q 15 18 0 24";
        g.append("path")
          .attr("d", coilPath)
          .attr("fill", "none")
          .attr("stroke", color)
          .attr("stroke-width", 3)
          .attr("stroke-linecap", "round");
          
        // Winding Configuration Symbol
        const symX = isHighSide ? -22 : 22;
        const symG = g.append("g").attr("transform", `translate(${symX}, 0)`);
        
        if (type === "D") {
            symG.append("path").attr("d", "M 0 -7 L 7 5 L -7 5 Z").attr("fill", "none").attr("stroke", color).attr("stroke-width", 1.5);
        } else {
            symG.append("path").attr("d", "M 0 0 L 0 -8 M 0 0 L 6 4 M 0 0 L -6 4").attr("fill", "none").attr("stroke", color).attr("stroke-width", 1.5);
            if (type === "YG" || type === "ZG") {
                const gr = symG.append("g").attr("transform", "translate(0, 8)");
                gr.append("line").attr("x1", 0).attr("y1", 0).attr("x2", 0).attr("y2", 5).attr("stroke", color);
                gr.append("line").attr("x1", -5).attr("y1", 5).attr("x2", 5).attr("y2", 5).attr("stroke", color);
                gr.append("line").attr("x1", -3).attr("y1", 7).attr("x2", 3).attr("y2", 7).attr("stroke", color);
            }
        }
      };
      
      drawWinding(-20, 0, "#fff", d.params.h_winding || "Y", true);
      drawWinding(20, 0, "#fff", d.params.x_winding || "D", false);
      
      // Bushing Labels
      el.append("text").attr("x", -40).attr("y", -32).attr("fill", "#aaa").style("font-size", "10px").style("font-weight", "bold").text("H");
      el.append("text").attr("x", 32).attr("y", -32).attr("fill", "#aaa").style("font-size", "10px").style("font-weight", "bold").text("X");
    } else if (d.type === "VoltageRegulator") {
      el.append("text").attr("x", -38).attr("y", -32).attr("fill", "#aaa").style("font-size", "9px").style("font-weight", "bold").text("H");
      el.append("text").attr("x", 32).attr("y", -32).attr("fill", "#aaa").style("font-size", "9px").style("font-weight", "bold").text("X");
      el.append("polyline").attr("points", "-14,-14 -6,14 6,-14 14,14").attr("fill", "none").attr("stroke", "#fff").attr("stroke-width", 2.5);
      // Adjustable arrow
      el.append("line").attr("x1", -20).attr("y1", 20).attr("x2", 20).attr("y2", -20).attr("stroke", "#0f0").attr("stroke-width", 2);
      el.append("path").attr("d", "M 12,-20 L 20,-20 L 20,-12").attr("fill", "none").attr("stroke", "#0f0").attr("stroke-width", 2);
    } else if (d.type === "CircuitBreaker") {
      // 3-Phase Breaker representation with physical contact lines
      const isClosed = (ph) => {
          const s = (d.summary || {}).Status || "";
          if (s.includes("1-POLE")) {
              const parts = s.split("[")[1].split("]")[0].split(" ");
              const map = {"a": 0, "b": 1, "c": 2};
              return parts[map[ph]] !== ".";
          }
          return s.startsWith("CLOSED");
      };

      // Main frame
      el.append("rect").attr("x", -25).attr("y", -30).attr("width", 50).attr("height", 60).attr("fill", "#050505").attr("stroke", "#00ff44").attr("stroke-width", 2);
      el.append("text").attr("x", -32).attr("y", -35).attr("fill", "#aaa").style("font-size", "9px").style("font-weight", "bold").text("H");
      el.append("text").attr("x", 25).attr("y", -35).attr("fill", "#aaa").style("font-size", "9px").style("font-weight", "bold").text("X");
      
      ["a", "b", "c"].forEach((ph, i) => {
          const off = [-PHASE_GAP, 0, PHASE_GAP][i];
          const closed = isClosed(ph);
          // Fixed terminals
          el.append("circle").attr("cx", -20).attr("cy", off).attr("r", 2).attr("fill", "#fff");
          el.append("circle").attr("cx", 20).attr("cy", off).attr("r", 2).attr("fill", "#fff");
          
          if (closed) {
            // Horizontal connecting bridge
            el.append("line").attr("x1", -20).attr("y1", off).attr("x2", 20).attr("y2", off).attr("stroke", "#fff").attr("stroke-width", 3);
            el.append("rect").attr("x", -12).attr("y", off-3).attr("width", 24).attr("height", 6).attr("fill", "#00ff44");
          } else {
            // Open contact (vertical or diagonal line)
            el.append("line").attr("x1", -5).attr("y1", off-8).attr("x2", 5).attr("y2", off+8).attr("stroke", "#555").attr("stroke-width", 2);
          }
      });
    } else if (d.type === "Disconnect") {
      // 3-Phase Disconnect blades
      const isClosed = (ph) => {
          const s = (d.summary || {}).Status || "";
          if (s.includes("1-POLE")) {
              const parts = s.split("[")[1].split("]")[0].split(" ");
              const map = {"a": 0, "b": 1, "c": 2};
              return parts[map[ph]] !== ".";
          }
          return s.startsWith("CLOSED");
      };

      el.append("text").attr("x", -28).attr("y", -32).attr("fill", "#aaa").style("font-size", "9px").style("font-weight", "bold").text("H");
      el.append("text").attr("x", 22).attr("y", -32).attr("fill", "#aaa").style("font-size", "9px").style("font-weight", "bold").text("X");
      ["a", "b", "c"].forEach((ph, i) => {
        const off = [-PHASE_GAP, 0, PHASE_GAP][i];
        const closed = isClosed(ph);
        el.append("circle").attr("cx", -20).attr("cy", off).attr("r", 2.5).attr("fill", "#fff");
        el.append("circle").attr("cx", 20).attr("cy", off).attr("r", 2.5).attr("fill", "#fff");
        if (!closed) {
          // Open blade (pointing up)
          el.append("line").attr("x1", -20).attr("y1", off).attr("x2", 10).attr("y2", off-20).attr("stroke", "#fff").attr("stroke-width", 3);
        } else {
          // Closed blade (flat)
          el.append("line").attr("x1", -20).attr("y1", off).attr("x2", 20).attr("y2", off).attr("stroke", "#0f0").attr("stroke-width", 3);
        }
      });
    } else if (d.type === "VoltageSource") {
      // Source with Sine Wave
      el.append("circle").attr("r", 30).attr("fill", "#1a1a1a").attr("stroke", "#ffaa00").attr("stroke-width", 2.5);
      const sinePath = d3.line().x(t => t).y(t => 10 * Math.sin(t / 5));
      const tValues = d3.range(-20, 21, 1);
      el.append("path").attr("d", sinePath(tValues)).attr("fill", "none").attr("stroke", "#ffaa00").attr("stroke-width", 2);
    } else if (d.type === "Load") {
      // Circle enclosure for Load
      el.append("circle").attr("r", 35).attr("fill", "#1a0505").attr("stroke", "#ff4444").attr("stroke-width", 2);
      // 3-Phase Resistor-style Load inside
      [-PHASE_GAP, 0, PHASE_GAP].forEach(off => {
          // Zigzag resistor symbol
          el.append("polyline").attr("points", `-18,${off} -13,${off-4} -8,${off+4} -3,${off-4} 2,${off+4} 7,${off-4} 12,${off+4} 17,${off}`).attr("fill", "none").attr("stroke", "#ff4444").attr("stroke-width", 2);
          // Connection to ground-ish point
          el.append("line").attr("x1", 17).attr("y1", off).attr("x2", 22).attr("y2", off).attr("stroke", "#ff4444");
      });
      el.append("line").attr("x1", 22).attr("y1", -PHASE_GAP).attr("x2", 22).attr("y2", PHASE_GAP).attr("stroke", "#ff4444");
    } else if (["Bus", "Line", "PowerLine", "Wire"].includes(d.type)) {
      if (_singleLineMode) {
        // Single bar, coloured by voltage class.
        const c =
          (typeof window.voltageClassColor === "function" &&
            window.PoneglyphSettings &&
            window.PoneglyphSettings.get("colorByVoltageClass"))
            ? window.voltageClassColor(_nodeVoltageKv(d))
            : "#888";
        el.append("line")
          .attr("x1", -40).attr("y1", 0)
          .attr("x2", 40).attr("y2", 0)
          .attr("stroke", c)
          .attr("stroke-width", 5)
          .attr("stroke-linecap", "round")
          .attr("opacity", 0.95);
      } else {
        // 3-Phase Bus Bars Look
        const colors = ["#f44", "#ff4", "#44f"];
        [-PHASE_GAP, 0, PHASE_GAP].forEach((off, i) => {
            el.append("line")
              .attr("x1", -40).attr("y1", off)
              .attr("x2", 40).attr("y2", off)
              .attr("stroke", colors[i])
              .attr("stroke-width", 5)
              .attr("stroke-linecap", "round")
              .attr("opacity", 0.9);
        });
        // Neutral bar (thin, dashed)
        el.append("line")
          .attr("x1", -40).attr("y1", PHASE_GAP * 2)
          .attr("x2", 40).attr("y2", PHASE_GAP * 2)
          .attr("stroke", "#666")
          .attr("stroke-width", 2)
          .attr("stroke-dasharray", "4,2");
      }
    } else if (d.type === "ShuntCapacitor") {
      const g = el.append("g").attr("transform", "translate(0, -10)");
      g.append("line").attr("x1", 0).attr("y1", -15).attr("x2", 0).attr("y2", 0).attr("stroke", "#4df").attr("stroke-width", 2);
      g.append("line").attr("x1", -18).attr("y1", 0).attr("x2", 18).attr("y2", 0).attr("stroke", "#4df").attr("stroke-width", 3);
      g.append("line").attr("x1", -18).attr("y1", 8).attr("x2", 18).attr("y2", 8).attr("stroke", "#4df").attr("stroke-width", 3);
      g.append("line").attr("x1", 0).attr("y1", 8).attr("x2", 0).attr("y2", 20).attr("stroke", "#4df").attr("stroke-width", 2);
      // Ground
      const gr = el.append("g").attr("transform", "translate(0, 10)");
      gr.append("line").attr("x1", -12).attr("y1", 12).attr("x2", 12).attr("y2", 12).attr("stroke", "#666").attr("stroke-width", 2);
      gr.append("line").attr("x1", -7).attr("y1", 16).attr("x2", 7).attr("y2", 16).attr("stroke", "#666").attr("stroke-width", 1.5);
      gr.append("line").attr("x1", -3).attr("y1", 20).attr("x2", 3).attr("y2", 20).attr("stroke", "#666").attr("stroke-width", 1);
    } else if (d.type === "ShuntReactor") {
      el.append("line").attr("x1", 0).attr("y1", -28).attr("x2", 0).attr("y2", -16).attr("stroke", "#f90").attr("stroke-width", 2);
      // Inductor curls
      el.append("path").attr("d", "M 0 -16 Q 10 -12 0 -8 Q 10 -4 0 0 Q 10 4 0 8 Q 10 12 0 16").attr("fill", "none").attr("stroke", "#f90").attr("stroke-width", 2);
      el.append("line").attr("x1", 0).attr("y1", 16).attr("x2", 0).attr("y2", 28).attr("stroke", "#f90").attr("stroke-width", 2);
      // Ground
      el.append("line").attr("x1", -12).attr("y1", 28).attr("x2", 12).attr("y2", 28).attr("stroke", "#666").attr("stroke-width", 2);
      el.append("line").attr("x1", -7).attr("y1", 32).attr("x2", 7).attr("y2", 32).attr("stroke", "#666").attr("stroke-width", 1.5);
      el.append("line").attr("x1", -3).attr("y1", 36).attr("x2", 3).attr("y2", 36).attr("stroke", "#666").attr("stroke-width", 1);
    } else if (d.type === "SurgeArrester") {
      el.append("line").attr("x1", 0).attr("y1", -26).attr("x2", 0).attr("y2", -12).attr("stroke", "#ff6").attr("stroke-width", 2);
      // Arrester gaps/element
      el.append("rect").attr("x", -10).attr("y", -12).attr("width", 20).attr("height", 24).attr("fill", "none").attr("stroke", "#ff6").attr("stroke-width", 1.5);
      el.append("line").attr("x1", -10).attr("y1", 0).attr("x2", 10).attr("y2", 0).attr("stroke", "#ff6").attr("stroke-width", 1).attr("stroke-dasharray", "2,2");
      el.append("line").attr("x1", 0).attr("y1", 12).attr("x2", 0).attr("y2", 26).attr("stroke", "#ff6").attr("stroke-width", 2);
      // Ground
      el.append("line").attr("x1", -12).attr("y1", 26).attr("x2", 12).attr("y2", 26).attr("stroke", "#666").attr("stroke-width", 2);
      el.append("line").attr("x1", -7).attr("y1", 30).attr("x2", 7).attr("y2", 30).attr("stroke", "#666").attr("stroke-width", 1.5);
      el.append("line").attr("x1", -3).attr("y1", 34).attr("x2", 3).attr("y2", 34).attr("stroke", "#666").attr("stroke-width", 1);
    } else if (d.type === "SVC") {
      el.append("polygon").attr("points", "0,-20 18,0 0,20 -18,0").attr("fill", "#055").attr("fill-opacity", 0.5).attr("stroke", "#0ff").attr("stroke-width", 2);
      el.append("line").attr("x1", -14).attr("y1", 8).attr("x2", 14).attr("y2", -8).attr("stroke", "#0ff").attr("stroke-width", 2);
      el.append("path").attr("d", "M 8,-8 L 14,-8 L 14,-2").attr("fill", "none").attr("stroke", "#0ff").attr("stroke-width", 2);
      el.append("line").attr("x1", 0).attr("y1", -28).attr("x2", 0).attr("y2", -20).attr("stroke", "#0ff").attr("stroke-width", 2);
      el.append("line").attr("x1", 0).attr("y1", 20).attr("x2", 0).attr("y2", 32).attr("stroke", "#0ff").attr("stroke-width", 2);
      // Ground
      el.append("line").attr("x1", -12).attr("y1", 32).attr("x2", 12).attr("y2", 32).attr("stroke", "#666").attr("stroke-width", 2);
      el.append("line").attr("x1", -7).attr("y1", 36).attr("x2", 7).attr("y2", 36).attr("stroke", "#666").attr("stroke-width", 1.5);
    } else if (d.type === "NeutralGroundingResistor") {
      el.append("line").attr("x1", 0).attr("y1", -28).attr("x2", 0).attr("y2", -16).attr("stroke", "#aaa").attr("stroke-width", 2);
      el.append("polyline").attr("points", "0,-16 8,-12 -8,-8 8,-4 -8,0 8,4 -8,8 0,12").attr("fill", "none").attr("stroke", "#aaa").attr("stroke-width", 2).attr("stroke-linejoin", "round");
      el.append("line").attr("x1", 0).attr("y1", 12).attr("x2", 0).attr("y2", 26).attr("stroke", "#aaa").attr("stroke-width", 2);
      // Ground
      el.append("line").attr("x1", -12).attr("y1", 26).attr("x2", 12).attr("y2", 26).attr("stroke", "#666").attr("stroke-width", 2);
      el.append("line").attr("x1", -7).attr("y1", 30).attr("x2", 7).attr("y2", 30).attr("stroke", "#666").attr("stroke-width", 1.5);
      el.append("line").attr("x1", -3).attr("y1", 34).attr("x2", 3).attr("y2", 34).attr("stroke", "#666").attr("stroke-width", 1);
    } else if (d.type === "SeriesCapacitor") {
      el.append("text").attr("x", -60).attr("y", -25).attr("fill", "#aaa").style("font-size", "9px").style("font-weight", "bold").text("H");
      el.append("text").attr("x", 52).attr("y", -25).attr("fill", "#aaa").style("font-size", "9px").style("font-weight", "bold").text("X");
      el.append("line").attr("x1", -50).attr("y1", 0).attr("x2", -8).attr("y2", 0).attr("stroke", "#4df").attr("stroke-width", 2);
      el.append("line").attr("x1", 8).attr("y1", 0).attr("x2", 50).attr("y2", 0).attr("stroke", "#4df").attr("stroke-width", 2);
      el.append("line").attr("x1", -8).attr("y1", -20).attr("x2", -8).attr("y2", 20).attr("stroke", "#4df").attr("stroke-width", 3.5);
      el.append("line").attr("x1", 8).attr("y1", -20).attr("x2", 8).attr("y2", 20).attr("stroke", "#4df").attr("stroke-width", 3.5);
    } else if (d.type === "SeriesReactor") {
      el.append("text").attr("x", -60).attr("y", -20).attr("fill", "#aaa").style("font-size", "9px").style("font-weight", "bold").text("H");
      el.append("text").attr("x", 52).attr("y", -20).attr("fill", "#aaa").style("font-size", "9px").style("font-weight", "bold").text("X");
      el.append("line").attr("x1", -50).attr("y1", 0).attr("x2", -20).attr("y2", 0).attr("stroke", "#f90").attr("stroke-width", 2);
      el.append("line").attr("x1", 20).attr("y1", 0).attr("x2", 50).attr("y2", 0).attr("stroke", "#f90").attr("stroke-width", 2);
      // Inductor coils (horizontal)
      el.append("path").attr("d", "M -20 0 Q -15 -10 -10 0 Q -5 -10 0 0 Q 5 -10 10 0 Q 15 -10 20 0").attr("fill", "none").attr("stroke", "#f90").attr("stroke-width", 2);
    } else if (d.type === "LineTrap") {
      el.append("text").attr("x", -60).attr("y", -20).attr("fill", "#aaa").style("font-size", "9px").style("font-weight", "bold").text("H");
      el.append("text").attr("x", 52).attr("y", -20).attr("fill", "#aaa").style("font-size", "9px").style("font-weight", "bold").text("X");
      el.append("line").attr("x1", -50).attr("y1", 0).attr("x2", -25).attr("y2", 0).attr("stroke", "#8f8").attr("stroke-width", 2);
      el.append("line").attr("x1", 25).attr("y1", 0).attr("x2", 50).attr("y2", 0).attr("stroke", "#8f8").attr("stroke-width", 2);
      el.append("ellipse").attr("cx", 0).attr("cy", 0).attr("rx", 25).attr("ry", 15).attr("fill", "#050").attr("fill-opacity", 0.4).attr("stroke", "#8f8").attr("stroke-width", 2);
      // Parallel LC symbol inside
      el.append("path").attr("d", "M -15 -5 L 15 -5 M -15 5 L 15 5").attr("stroke", "#8f8").attr("stroke-width", 1);
    } else {
      el.append("circle")
        .attr("r", 30)
        .attr("fill", "#1a1a1a")
        .attr("stroke", "#444");
    }

    // Sync-error warning ring (VoltageSource with conflicts)
    if (d.type === "VoltageSource" && d.sync_errors && d.sync_errors.length > 0) {
      el.append("circle")
        .attr("r", 48)
        .attr("fill", "none")
        .attr("stroke", "#f00")
        .attr("stroke-width", 2)
        .attr("stroke-dasharray", "6,3")
        .attr("opacity", 0.85);
      el.append("text")
        .attr("x", 0).attr("y", -52)
        .attr("text-anchor", "middle")
        .attr("font-size", "10px")
        .attr("fill", "#f44")
        .attr("letter-spacing", "1px")
        .text("⚠ SYNC FAULT");
    }

    const labelText = d.id;
    const labelG = el.append("g").attr("class", "node-label");
    const textEl = labelG.append("text")
      .attr("text-anchor", "middle")
      .attr("dominant-baseline", "middle")
      .attr("x", 0).attr("y", 0)
      .text(labelText);
    const bbox = textEl.node().getBBox();
    labelG.insert("rect", "text")
      .attr("x", bbox.x - 4).attr("y", bbox.y - 2)
      .attr("width", bbox.width + 8).attr("height", bbox.height + 4)
      .attr("rx", 2).attr("class", "label-bg");
  });

  positionLabels(nodeGroup, visibleNodes);
}

/**
 * Add a small draggable handle at the wire elbow so the user can pull the
 * bend point to a new fraction along the wire's dominant axis.
 */
function _addWireBendHandle(linkGroup, x1, y1, x2, y2, frac, srcId, tgtId) {
  const dx = x2 - x1, dy = y2 - y1;
  if (Math.abs(dx) < 4 && Math.abs(dy) < 4) return; // degenerate wire
  const isHoriz = Math.abs(dx) >= Math.abs(dy);
  const key = srcId + "→" + tgtId;

  // Compute initial handle position (midpoint of the bent segment)
  const hx = isHoriz ? x1 + dx * frac : (x1 + x2) / 2;
  const hy = isHoriz ? (y1 + y2) / 2  : y1 + dy * frac;

  const handle = linkGroup.append("circle")
    .attr("class", "wire-bend-handle")
    .attr("cx", hx)
    .attr("cy", hy)
    .attr("r", 7)
    .datum({ x1, y1, x2, y2, isHoriz });

  handle.call(d3.drag()
    .on("start", function(event) {
      event.sourceEvent.stopPropagation();
      d3.select(this).attr("r", 7).attr("stroke", "#fff");
    })
    .on("drag", function(event) {
      const d = d3.select(this).datum();
      const ddx = d.x2 - d.x1, ddy = d.y2 - d.y1;
      let newFrac;
      if (d.isHoriz) {
        newFrac = ddx !== 0 ? (event.x - d.x1) / ddx : 0.5;
        d3.select(this).attr("cx", event.x).attr("cy", (d.y1 + d.y2) / 2);
      } else {
        newFrac = ddy !== 0 ? (event.y - d.y1) / ddy : 0.5;
        d3.select(this).attr("cx", (d.x1 + d.x2) / 2).attr("cy", event.y);
      }
      newFrac = Math.max(0.1, Math.min(0.9, newFrac));
      _wireBends[key] = newFrac;

      // Live-update all wire paths that belong to this edge
      linkGroup.selectAll("path").filter(function() {
        return this.getAttribute("data-src") === srcId &&
               this.getAttribute("data-tgt") === tgtId;
      }).each(function() {
        const el = d3.select(this);
        const ox1 = parseFloat(el.attr("data-x1"));
        const oy1 = parseFloat(el.attr("data-y1"));
        const ox2 = parseFloat(el.attr("data-x2"));
        const oy2 = parseFloat(el.attr("data-y2"));
        const off = parseFloat(el.attr("data-offset") || 0);
        el.attr("d", getPathData(ox1, oy1, ox2, oy2, off, newFrac))
          .attr("data-frac", newFrac);
      });
    })
    .on("end", function() {
      d3.select(this).attr("r", 7).attr("stroke", "#666");
      const newFrac = _wireBends[key];
      if (newFrac != null) {
        reconfigureAPI(null, "update_wire_bend", { src: srcId, tgt: tgtId, frac: newFrac });
      }
    })
  );
}

function updateLinksDuringDrag(nodeId, newX, newY, angle, data, linkGroup) {
  linkGroup.selectAll("path").each(function () {
    const el = d3.select(this);
    const isSrc = el.attr("data-src") === nodeId,
      isTgt = el.attr("data-tgt") === nodeId;
    if (!isSrc && !isTgt) return;
    const off = parseFloat(el.attr("data-offset")) || 0;
    let x1 = parseFloat(el.attr("data-x1")),
      y1 = parseFloat(el.attr("data-y1")),
      x2 = parseFloat(el.attr("data-x2")),
      y2 = parseFloat(el.attr("data-y2"));

    if (isSrc) {
      if (el.classed("link-wire")) {
        const tgt = data.nodes.find((n) => n.id === el.attr("data-tgt"));
        const b = facingBushing(newX, newY, angle, tgt.gx, tgt.gy);
        const a = getAnchorPoint(newX, newY, angle, b, off);
        x1 = a.x;
        y1 = a.y;
      } else {
        x1 = newX;
        y1 = newY;
      }
      el.attr("data-x1", x1).attr("data-y1", y1);
    }
    if (isTgt) {
      if (el.classed("link-wire")) {
        const src = data.nodes.find((n) => n.id === el.attr("data-src"));
        const b = facingBushing(newX, newY, angle, src.gx, src.gy);
        const a = getAnchorPoint(newX, newY, angle, b, off);
        x2 = a.x;
        y2 = a.y;
      } else {
        x2 = newX;
        y2 = newY;
      }
      el.attr("data-x2", x2).attr("data-y2", y2);
    }
    const frac = parseFloat(el.attr("data-frac")) || 0.5;
    el.attr("d", getPathData(x1, y1, x2, y2, off, frac));
  });
}

/**
 * Automatically adjusts the zoom and pan to fit all devices in the view.
 */
function zoomToFit(duration = 750) {
    if (!currentData || !currentData.nodes || currentData.nodes.length === 0) return;

    const nodes = currentData.nodes;
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;

    nodes.forEach(n => {
        // Handle potential null/undefined coordinates
        const gx = n.gx || 0;
        const gy = n.gy || 0;
        minX = Math.min(minX, gx);
        minY = Math.min(minY, gy);
        maxX = Math.max(maxX, gx);
        maxY = Math.max(maxY, gy);
    });

    const padding = 100;
    const width = svg.node().clientWidth || window.innerWidth;
    const height = svg.node().clientHeight || window.innerHeight;

    const fullWidth = maxX - minX + padding * 2;
    const fullHeight = maxY - minY + padding * 2;

    // Calculate optimal scale, don't zoom in past 1.0
    const scale = Math.max(0.1, Math.min(width / fullWidth, height / fullHeight, 1.0));
    
    const midX = (minX + maxX) / 2;
    const midY = (minY + maxY) / 2;

    const transform = d3.zoomIdentity
        .translate(width / 2 - scale * midX, height / 2 - scale * midY)
        .scale(scale);

    if (duration > 0) {
        svg.transition().duration(duration).call(zoom.transform, transform);
    } else {
        svg.call(zoom.transform, transform);
    }
}

function zoomIn() {
    svg.transition().duration(220).call(zoom.scaleBy, 1.5);
}

function zoomOut() {
    svg.transition().duration(220).call(zoom.scaleBy, 0.67);
}

function panToDevice(id) {
    if (!currentData) return;
    const node = currentData.nodes.find(n => n.id === id);
    if (!node) return;
    const width = svg.node().clientWidth || window.innerWidth;
    const height = svg.node().clientHeight || window.innerHeight;
    const k = d3.zoomTransform(svg.node()).k;
    const tx = width / 2 - k * node.gx;
    const ty = height / 2 - k * node.gy;
    svg.transition().duration(380).call(
        zoom.transform,
        d3.zoomIdentity.translate(tx, ty).scale(k)
    );
    // Brief flash to highlight the device
    zoomGroup.selectAll(".node")
        .filter(d => d.id === id)
        .each(function() {
            const el = d3.select(this);
            el.style("opacity", 0.25);
            setTimeout(() => el.style("opacity", 1), 200);
            setTimeout(() => el.style("opacity", 0.25), 400);
            setTimeout(() => el.style("opacity", 1), 600);
        });
}

// ── Label Placement ───────────────────────────────────────────────────────

// Candidate world-space offsets tried in preference order.
// dx/dy are in pixels; anchor is SVG text-anchor.
const _LABEL_CANDS = [
  { dx:   0, dy:  90, anchor: "middle" },  // below (default)
  { dx:   0, dy: -90, anchor: "middle" },  // above
  { dx:  95, dy:   0, anchor: "start"  },  // right
  { dx: -95, dy:   0, anchor: "end"    },  // left
  { dx:  72, dy:  72, anchor: "start"  },  // bottom-right
  { dx: -72, dy:  72, anchor: "end"    },  // bottom-left
  { dx:  72, dy: -72, anchor: "start"  },  // top-right
  { dx: -72, dy: -72, anchor: "end"    },  // top-left
];

function positionLabels(sel, nodes) {
  const NR = 70;  // node circle exclusion radius
  const LP = 5;   // extra padding on label box when checking overlaps
  const placed = [];

  const npos = nodes.map(n => ({ x: n.gx || 0, y: n.gy || 0 }));

  sel.each(function(d) {
    const labelG = d3.select(this).select(".node-label");
    const textEl = labelG.select("text");
    const rot    = d.rotation || 0;
    const wx = d.gx || 0, wy = d.gy || 0;

    const bb = textEl.node().getBBox();
    const lw = bb.width + 8, lh = bb.height + 4;

    let best = _LABEL_CANDS[0], bestScore = Infinity;

    for (const c of _LABEL_CANDS) {
      const cx = wx + c.dx, cy = wy + c.dy;
      const lbx = _anchorX(cx, lw, c.anchor);
      const lby = cy - lh / 2;
      let score = 0;

      for (const np of npos) {
        if (np.x === wx && np.y === wy) continue;
        if (_lblHitsCircle(lbx - LP, lby - LP, lw + LP*2, lh + LP*2, np.x, np.y, NR))
          score += 2;
      }
      for (const pl of placed) {
        if (_lblHitsRect(lbx - LP, lby - LP, lw + LP*2, lh + LP*2, pl.x, pl.y, pl.w, pl.h))
          score++;
      }

      if (score < bestScore) { bestScore = score; best = c; }
      if (bestScore === 0) break;
    }

    // Convert world-space offset to local node space, cancelling the node's rotation.
    // Node transform is translate(wx,wy) rotate(rot), so local = R^-1(rot) * world_offset.
    const rad = (rot * Math.PI) / 180;
    const ldx = best.dx * Math.cos(rad) + best.dy * Math.sin(rad);
    const ldy = best.dy * Math.cos(rad) - best.dx * Math.sin(rad);

    labelG.attr("transform", `translate(${ldx.toFixed(1)},${ldy.toFixed(1)})`);
    textEl.attr("text-anchor", best.anchor);

    const nb = textEl.node().getBBox();
    labelG.select(".label-bg")
      .attr("x", nb.x - 4).attr("y", nb.y - 2)
      .attr("width", nb.width + 8).attr("height", nb.height + 4);

    const fx = wx + best.dx, fy = wy + best.dy;
    placed.push({ x: _anchorX(fx, lw, best.anchor), y: fy - lh / 2, w: lw, h: lh });
  });
}

function _anchorX(x, w, anchor) {
  return anchor === "middle" ? x - w / 2 : anchor === "start" ? x : x - w;
}

function _lblHitsCircle(rx, ry, rw, rh, cx, cy, cr) {
  const nx = Math.max(rx, Math.min(cx, rx + rw));
  const ny = Math.max(ry, Math.min(cy, ry + rh));
  return (cx - nx) * (cx - nx) + (cy - ny) * (cy - ny) < cr * cr;
}

function _lblHitsRect(ax, ay, aw, ah, bx, by, bw, bh) {
  return ax < bx + bw && ax + aw > bx && ay < by + bh && ay + ah > by;
}

// ── Minimap ────────────────────────────────────────────────────────────────

const MINIMAP_W = 200;
const MINIMAP_H = 150;
const MINIMAP_PAD = 12;

const minimapScaleX = d3.scaleLinear();
const minimapScaleY = d3.scaleLinear();
let minimapCollapsed = false;

(function initMinimap() {
  const mmSvg = d3.select("#minimap-svg");
  mmSvg.append("g").attr("id", "minimap-edges");
  mmSvg.append("g").attr("id", "minimap-nodes");
  mmSvg.append("rect")
    .attr("id", "minimap-viewport")
    .attr("fill", "rgba(255,255,0,0.06)")
    .attr("stroke", "#ffff00")
    .attr("stroke-width", 1)
    .attr("pointer-events", "none");

  mmSvg.on("click", function(event) {
    const [mx, my] = d3.pointer(event);
    const cx = minimapScaleX.invert(mx);
    const cy = minimapScaleY.invert(my);
    const svgW = svg.node().clientWidth || window.innerWidth;
    const svgH = svg.node().clientHeight || window.innerHeight;
    const k = d3.zoomTransform(svg.node()).k;
    svg.transition().duration(200).call(
      zoom.transform,
      d3.zoomIdentity.translate(svgW / 2 - k * cx, svgH / 2 - k * cy).scale(k)
    );
  });
})();

function updateMinimap() {
  if (minimapCollapsed || !currentData || !currentData.nodes || currentData.nodes.length === 0) return;

  const nodes = currentData.nodes;
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  nodes.forEach(n => {
    const gx = n.gx || 0, gy = n.gy || 0;
    minX = Math.min(minX, gx); minY = Math.min(minY, gy);
    maxX = Math.max(maxX, gx); maxY = Math.max(maxY, gy);
  });

  const pad = 60;
  minimapScaleX.domain([minX - pad, maxX + pad]).range([MINIMAP_PAD, MINIMAP_W - MINIMAP_PAD]);
  minimapScaleY.domain([minY - pad, maxY + pad]).range([MINIMAP_PAD, MINIMAP_H - MINIMAP_PAD]);

  const nodeById = {};
  nodes.forEach(n => { nodeById[n.id] = n; });

  const resolveId = e => typeof e === "string" ? e : e.id;

  const mmNodeX = (id) => { const n = nodeById[id]; return n ? minimapScaleX(n.gx || 0) : 0; };
  const mmNodeY = (id) => { const n = nodeById[id]; return n ? minimapScaleY(n.gy || 0) : 0; };

  const edgeSel = d3.select("#minimap-edges").selectAll("line")
    .data(currentData.edges || [], d => `${resolveId(d.source)}→${resolveId(d.target)}`);
  edgeSel.enter().append("line")
    .merge(edgeSel)
    .attr("x1", d => mmNodeX(resolveId(d.source)))
    .attr("y1", d => mmNodeY(resolveId(d.source)))
    .attr("x2", d => mmNodeX(resolveId(d.target)))
    .attr("y2", d => mmNodeY(resolveId(d.target)))
    .attr("stroke", d => d.type === "protection" ? "#2a2a2a" : "#2e2e2e")
    .attr("stroke-width", 0.8);
  edgeSel.exit().remove();

  const nodeSel = d3.select("#minimap-nodes").selectAll("circle")
    .data(nodes, d => d.id);
  nodeSel.enter().append("circle")
    .merge(nodeSel)
    .attr("cx", d => minimapScaleX(d.gx || 0))
    .attr("cy", d => minimapScaleY(d.gy || 0))
    .attr("r", 2.5)
    .attr("fill", d => {
      if (d.type === "VoltageSource") return "#ffaa00";
      if (d.type === "CircuitBreaker") return d.status === "OPEN" ? "#444" : "#00cc44";
      if (d.type === "Disconnect") return d.status === "OPEN" ? "#333" : "#559955";
      if (d.type === "PowerTransformer") return "#4488ff";
      if (d.type === "VoltageRegulator") return "#44ff88";
      if (d.type === "Load") return "#ff4444";
      if (["Bus", "Line", "PowerLine", "Wire"].includes(d.type)) return "#555";
      return "#505050";
    });
  nodeSel.exit().remove();

  updateMinimapViewport();
}

function updateMinimapViewport() {
  if (minimapCollapsed) return;
  const vp = d3.select("#minimap-viewport");
  if (vp.empty() || minimapScaleX.domain()[0] === minimapScaleX.domain()[1]) return;

  const t = d3.zoomTransform(svg.node());
  const svgW = svg.node().clientWidth || window.innerWidth;
  const svgH = svg.node().clientHeight || window.innerHeight;

  const left   = minimapScaleX(-t.x / t.k);
  const top    = minimapScaleY(-t.y / t.k);
  const right  = minimapScaleX((svgW - t.x) / t.k);
  const bottom = minimapScaleY((svgH - t.y) / t.k);

  vp.attr("x", left)
    .attr("y", top)
    .attr("width", Math.max(1, right - left))
    .attr("height", Math.max(1, bottom - top));
}

function toggleMinimap() {
  minimapCollapsed = !minimapCollapsed;
  const body = document.getElementById("minimap-body");
  const btn  = document.getElementById("minimap-toggle");
  if (minimapCollapsed) {
    body.style.display = "none";
    btn.innerHTML = "+";
  } else {
    body.style.display = "block";
    btn.innerHTML = "&#x2212;";
    updateMinimap();
  }
}
