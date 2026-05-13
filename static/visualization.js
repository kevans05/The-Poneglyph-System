/**
 * SCADA Pro Console - Visualization Engine
 * Handles D3 rendering and Phasor diagrams.
 */

const svg = d3.select("#sld-svg");
const zoomGroup = d3.select("#zoom-group");

const zoom = d3
  .zoom()
  .scaleExtent([0.1, 10])
  .on("zoom", (e) => {
    zoomGroup.attr("transform", e.transform);
    updateMinimapViewport();
  });

svg.call(zoom);

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

  // 2. Draw Edges
  const linkGroup = zoomGroup.append("g").attr("id", "links");

  // Pre-pass: stagger bend fractions for edges that share a source or target
  // so their elbows land at different points instead of all bunching at 50%.
  const _resolveId = v => typeof v === "string" ? v : v.id;
  const _bendFrac = {};
  const _bySrc = {}, _byTgt = {};
  data.edges.forEach(edge => {
    const sid = _resolveId(edge.source), tid = _resolveId(edge.target);
    const key = sid + "→" + tid;
    _bendFrac[key] = 0.5;
    (_bySrc[sid] = _bySrc[sid] || []).push(key);
    (_byTgt[tid] = _byTgt[tid] || []).push(key);
  });
  const _stagger = (keys) => {
    if (keys.length < 2) return;
    keys.forEach((k, j) => {
      _bendFrac[k] = 0.3 + 0.4 * (j / (keys.length - 1));
    });
  };
  Object.values(_byTgt).forEach(_stagger);
  // Only apply source stagger if not already moved by target stagger
  Object.values(_bySrc).forEach(keys => {
    if (keys.length < 2) return;
    keys.forEach((k, j) => {
      if (_bendFrac[k] === 0.5) _bendFrac[k] = 0.3 + 0.4 * (j / (keys.length - 1));
    });
  });

  data.edges.forEach((edge) => {
    const src = data.nodes.find(n => n.id === _resolveId(edge.source));
    const tgt = data.nodes.find(n => n.id === _resolveId(edge.target));
    if (!src || !tgt) return;

    const frac = _bendFrac[src.id + "→" + tgt.id] ?? 0.5;

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

      linkGroup
        .append("path")
        .attr("class", wireClass)
        .attr("d", getPathData(src.gx, src.gy, tgt.gx, tgt.gy, 0, frac))
        .attr("data-src", src.id)
        .attr("data-tgt", tgt.id)
        .attr("data-x1", src.gx)
        .attr("data-y1", src.gy)
        .attr("data-x2", tgt.gx)
        .attr("data-y2", tgt.gy)
        .attr("data-offset", 0)
        .attr("data-frac", frac);
    } else {
      const srcB = facingBushing(
        src.gx,
        src.gy,
        src.rotation || 0,
        tgt.gx,
        tgt.gy,
      );
      const tgtB = facingBushing(
        tgt.gx,
        tgt.gy,
        tgt.rotation || 0,
        src.gx,
        src.gy,
      );

      // Determine wire count based on connection type
      let isDelta = false;
      if (src.type === "PowerTransformer") {
        const winding =
          srcB === "H" ? src.params.h_winding : src.params.x_winding;
        if (winding && winding.toUpperCase().startsWith("D")) isDelta = true;
      } else if (src.summary && src.summary.Connection) {
        if (src.summary.Connection && src.summary.Connection.includes("Delta")) isDelta = true;
      }

      const offsets = isDelta
          ? [-PHASE_GAP, 0, PHASE_GAP]
          : [-PHASE_GAP, 0, PHASE_GAP, PHASE_GAP * 2],
        classes = isDelta
          ? ["phase-a", "phase-b", "phase-c"]
          : ["phase-a", "phase-b", "phase-c", "neutral"];

      offsets.forEach((off, i) => {
        const a1 = getAnchorPoint(src.gx, src.gy, src.rotation || 0, srcB, off),
          a2 = getAnchorPoint(tgt.gx, tgt.gy, tgt.rotation || 0, tgtB, off);
        linkGroup
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
          .attr("data-frac", frac);
      });
    }
  });

  // 3. Draw Nodes
  const nodeGroup = zoomGroup
    .append("g")
    .attr("id", "nodes")
    .selectAll(".node")
    .data(data.nodes)
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
    if (d.type === "CurrentTransformer") {
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
    } else if (d.type === "Indicator") {
      // Indicator Light Symbol
      const isOn = ( ( (d.summary || {})  || {})  &&  ( (d.summary || {})  || {}) ["Status"]) &&  ( (d.summary || {})  || {}) ["Status"].includes("ON");
      el.append("circle").attr("r", 20).attr("fill", isOn ? "#f44" : "#300").attr("stroke", "#fff").attr("stroke-width", 2);
      if (isOn) {
        el.append("circle").attr("r", 25).attr("fill", "none").attr("stroke", "#f44").attr("stroke-width", 3).attr("opacity", 0.5);
      }
      el.append("line").attr("x1", -12).attr("y1", -12).attr("x2", 12).attr("y2", 12).attr("stroke", "#fff").attr("stroke-width", 1.5);
      el.append("line").attr("x1", 12).attr("y1", -12).attr("x2", -12).attr("y2", 12).attr("stroke", "#fff").attr("stroke-width", 1.5);
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

  positionLabels(nodeGroup, data.nodes);
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

// ── Phasor Scale Controls ─────────────────────────────────────────────────────
// Per-phasor scale overrides so users can manually zoom in/out the V and I axes.
// Keys are "<deviceId>_<mode>".  null value means "use auto".
var _phasorScaleOverrides = {};
var _phasorAutoScales = {};
var _phasorRenderCtx = {};  // stores args for re-rendering after scale change

function _phasorScaleStep(scaleKey, axis, dir) {
  const auto = _phasorAutoScales[scaleKey] || { maxV: 132790, maxI: 300 };
  const ov = _phasorScaleOverrides[scaleKey] || {};
  const field = axis === "V" ? "maxV" : "maxI";
  const cur = ov[field] != null ? ov[field] : auto[field];
  if (!_phasorScaleOverrides[scaleKey]) _phasorScaleOverrides[scaleKey] = {};
  // Step up: ×2, Step down: ÷2, but clamp to a sensible minimum
  const next = dir > 0 ? cur * 2 : cur / 2;
  const min = axis === "V" ? 10 : 0.1;
  _phasorScaleOverrides[scaleKey][field] = Math.max(min, next);
  _phasorRerender(scaleKey);
}

function _phasorScaleReset(scaleKey, axis) {
  if (_phasorScaleOverrides[scaleKey]) {
    const field = axis === "V" ? "maxV" : "maxI";
    _phasorScaleOverrides[scaleKey][field] = null;
  }
  _phasorRerender(scaleKey);
}

function _phasorRerender(scaleKey) {
  const ctx = _phasorRenderCtx[scaleKey];
  if (!ctx) return;
  renderPhasorBox(ctx.div, ctx.summary, ctx.mode, ctx.deviceId);
}

function drawVector(g, pMap, summary, r, w, h, center, maxV, maxI) {
  pMap.forEach((p) => {
    if (p.vm && summary[p.vm]) {
      const a = ((summary[p.va] || 0) * Math.PI) / 180,
        m = (summary[p.vm] / maxV) * r;
      g.append("line")
        .attr("x2", m * Math.cos(a))
        .attr("y2", -m * Math.sin(a))
        .attr("stroke", p.c)
        .attr("stroke-width", p.isPri ? 3 : 2);
      g.append("text")
        .attr("x", (m + 10) * Math.cos(a))
        .attr("y", -(m + 10) * Math.sin(a))
        .attr("text-anchor", "middle")
        .attr("dominant-baseline", "middle")
        .attr("fill", p.c)
        .style("font-size", "10px")
        .style("font-weight", "bold")
        .text("V" + p.n);
    }
    if (p.im && summary[p.im]) {
      const a = ((summary[p.ia] || 0) * Math.PI) / 180,
        m = (summary[p.im] / maxI) * r;
      g.append("line")
        .attr("x2", m * Math.cos(a))
        .attr("y2", -m * Math.sin(a))
        .attr("stroke", p.c)
        .attr("stroke-width", p.isSec ? 1.5 : 2)
        .attr("stroke-dasharray", p.isSec ? "4,2" : "3,2");
      g.append("text")
        .attr("x", (m + 22) * Math.cos(a))
        .attr("y", -(m + 22) * Math.sin(a))
        .attr("text-anchor", "middle")
        .attr("dominant-baseline", "middle")
        .attr("fill", p.c)
        .style("font-size", "10px")
        .text("I" + p.n);
    }
  });
}

function drawPhasors(id, summary, type) {
  const safeId = id.replace(/\s+/g, "-");
  if (type === "PowerTransformer") {
    const priDiv = d3.select("#phasor-pri-" + safeId),
      secDiv = d3.select("#phasor-sec-" + safeId);
    if (!priDiv.empty()) renderPhasorBox(priDiv, summary, "primary", id);
    if (!secDiv.empty()) renderPhasorBox(secDiv, summary, "secondary", id);
  } else if (type === "DualWindingVT") {
    const secDiv = d3.select("#phasor-sec-" + safeId),
      sec2Div = d3.select("#phasor-sec2-" + safeId);
    if (!secDiv.empty()) renderPhasorBox(secDiv, summary, "secondary", id);
    if (!sec2Div.empty()) renderPhasorBox(sec2Div, summary, "sec2", id);
  } else if (type === "VoltageTransformer") {
    const phasorDiv = d3.select("#phasor-" + safeId);
    if (!phasorDiv.empty()) renderPhasorBox(phasorDiv, summary, "secondary", id);
  } else if (type === "CurrentTransformer") {
    const phasorDiv = d3.select("#phasor-" + safeId);
    if (!phasorDiv.empty()) renderPhasorBox(phasorDiv, summary, "ct_secondary", id);
  } else {
    const phasorDiv = d3.select("#phasor-" + safeId);
    if (!phasorDiv.empty()) renderPhasorBox(phasorDiv, summary, "all", id);
  }
}

function renderPhasorBox(div, summary, mode, deviceId) {
  div.selectAll("*").remove();
  const scaleKey = (deviceId || "?") + "_" + mode;
  _phasorRenderCtx[scaleKey] = { div, summary, mode, deviceId };

  const w = 376,
    h = 210,
    r = 92,
    center = { x: w / 2, y: h / 2 };
  const g = div
    .append("svg")
    .attr("viewBox", `0 0 ${w} ${h}`)
    .attr("width", "100%")
    .attr("height", h)
    .style("display", "block")
    .append("g")
    .attr("transform", "translate(" + center.x + "," + center.y + ")");
  g.append("circle").attr("r", r).attr("fill", "none").attr("stroke", "#222");
  [0, 30, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330].forEach((d) =>
    g
      .append("line")
      .attr("x2", r * Math.cos((d * Math.PI) / 180))
      .attr("y2", -r * Math.sin((d * Math.PI) / 180))
      .attr("stroke", "#111")
      .attr("stroke-dasharray", d % 90 === 0 ? "none" : "2,2"),
  );

  const isDelta =
    summary && summary.Connection && summary.Connection && summary.Connection.includes("Delta");

  let pMap = [];
  if (mode === "primary") {
    if (isDelta) {
      pMap = [
        {
          n: "ABp",
          vm: "Pri Phase A Voltage (LL)",
          va: "Pri Phase A V-Angle",
          im: "Pri Phase A Current",
          ia: "Pri Phase A I-Angle",
          c: "#f00",
          isPri: true,
        },
        {
          n: "BCp",
          vm: "Pri Phase B Voltage (LL)",
          va: "Pri Phase B V-Angle",
          im: "Pri Phase B Current",
          ia: "Pri Phase B I-Angle",
          c: "#ff0",
          isPri: true,
        },
        {
          n: "CAp",
          vm: "Pri Phase C Voltage (LL)",
          va: "Pri Phase C V-Angle",
          im: "Pri Phase C Current",
          ia: "Pri Phase C I-Angle",
          c: "#00f",
          isPri: true,
        },
      ];
    } else {
      pMap = [
        {
          n: "Ap",
          vm: "Pri Phase A Voltage (LN)",
          va: "Pri Phase A V-Angle",
          im: "Pri Phase A Current",
          ia: "Pri Phase A I-Angle",
          c: "#f00",
          isPri: true,
        },
        {
          n: "Bp",
          vm: "Pri Phase B Voltage (LN)",
          va: "Pri Phase B V-Angle",
          im: "Pri Phase B Current",
          ia: "Pri Phase B I-Angle",
          c: "#ff0",
          isPri: true,
        },
        {
          n: "Cp",
          vm: "Pri Phase C Voltage (LN)",
          va: "Pri Phase C V-Angle",
          im: "Pri Phase C Current",
          ia: "Pri Phase C I-Angle",
          c: "#00f",
          isPri: true,
        },
      ];
    }
  } else if (mode === "secondary") {
    if (isDelta) {
      pMap = [
        {
          n: "AB",
          vm: "Sec Voltage Phase AB",
          va: "Phase AB V-Angle",
          im: "Sec Current Phase A",
          ia: "Phase A I-Angle",
          c: "#f00",
        },
        {
          n: "BC",
          vm: "Sec Voltage Phase BC",
          va: "Phase BC V-Angle",
          im: "Sec Current Phase B",
          ia: "Phase B I-Angle",
          c: "#ff0",
        },
        {
          n: "CA",
          vm: "Sec Voltage Phase CA",
          va: "Phase CA V-Angle",
          im: "Sec Current Phase C",
          ia: "Phase C I-Angle",
          c: "#00f",
        },
      ];
    } else {
      pMap = [
        { n: "A", vm: "Sec Voltage Phase A", va: "Phase A V-Angle", im: "Sec Current Phase A", ia: "Phase A I-Angle", c: "#f00" },
        { n: "B", vm: "Sec Voltage Phase B", va: "Phase B V-Angle", im: "Sec Current Phase B", ia: "Phase B I-Angle", c: "#ff0" },
        { n: "C", vm: "Sec Voltage Phase C", va: "Phase C V-Angle", im: "Sec Current Phase C", ia: "Phase C I-Angle", c: "#00f" },
      ];
    }
  } else if (mode === "sec2") {
    if (isDelta) {
      pMap = [
        {
          n: "AB2",
          vm: "Sec2 Voltage Phase AB",
          va: "Phase AB W2 V-Angle",
          c: "#f88",
        },
        {
          n: "BC2",
          vm: "Sec2 Voltage Phase BC",
          va: "Phase BC W2 V-Angle",
          c: "#ff8",
        },
        {
          n: "CA2",
          vm: "Sec2 Voltage Phase CA",
          va: "Phase CA W2 V-Angle",
          c: "#88f",
        },
      ];
    } else {
      pMap = [
        {
          n: "A2",
          vm: "Sec2 Voltage Phase A",
          va: "Phase A W2 V-Angle",
          c: "#f88",
        },
        {
          n: "B2",
          vm: "Sec2 Voltage Phase B",
          va: "Phase B W2 V-Angle",
          c: "#ff8",
        },
        {
          n: "C2",
          vm: "Sec2 Voltage Phase C",
          va: "Phase C W2 V-Angle",
          c: "#88f",
        },
      ];
    }
  } else if (mode === "ct_secondary")
    pMap = [
      {
        n: "A",
        im: "Sec Current Phase A",
        ia: "Phase A I-Angle",
        c: "#f00",
        isSec: true,
      },
      {
        n: "B",
        im: "Sec Current Phase B",
        ia: "Phase B I-Angle",
        c: "#ff0",
        isSec: true,
      },
      {
        n: "C",
        im: "Sec Current Phase C",
        ia: "Phase C I-Angle",
        c: "#00f",
        isSec: true,
      },
    ];
  else {
    if (isDelta) {
      pMap = [
        {
          n: "AB",
          vm: "Phase A-B Voltage",
          va: "Phase A-B V-Angle",
          im: "Phase A Current",
          ia: "Phase A I-Angle",
          c: "#f00",
        },
        {
          n: "BC",
          vm: "Phase B-C Voltage",
          va: "Phase B-C V-Angle",
          im: "Phase B Current",
          ia: "Phase B I-Angle",
          c: "#ff0",
        },
        {
          n: "CA",
          vm: "Phase C-A Voltage",
          va: "Phase C-A V-Angle",
          im: "Phase C Current",
          ia: "Phase C I-Angle",
          c: "#00f",
        },
      ];
    } else {
      pMap = [
        {
          n: "A",
          vm: "Phase A Voltage (LN)",
          va: "Phase A V-Angle",
          im: "Phase A Current",
          ia: "Phase A I-Angle",
          c: "#f00",
        },
        {
          n: "B",
          vm: "Phase B Voltage (LN)",
          va: "Phase B V-Angle",
          im: "Phase B Current",
          ia: "Phase B I-Angle",
          c: "#ff0",
        },
        {
          n: "C",
          vm: "Phase C Voltage (LN)",
          va: "Phase C V-Angle",
          im: "Phase C Current",
          ia: "Phase C I-Angle",
          c: "#00f",
        },
      ];
    }
    // Always add secondary currents if present
    pMap.push(
      {
        n: "As",
        im: "Sec Current Phase A",
        ia: "Phase A I-Angle",
        c: "#ff8888",
        isSec: true,
      },
      {
        n: "Bs",
        im: "Sec Current Phase B",
        ia: "Phase B I-Angle",
        c: "#ffff88",
        isSec: true,
      },
      {
        n: "Cs",
        im: "Sec Current Phase C",
        ia: "Phase C I-Angle",
        c: "#8888ff",
        isSec: true,
      },
    );
  }

  let autoMaxV = 0, autoMaxI = 0;
  pMap.forEach((p) => {
    if (p.vm && summary[p.vm]) autoMaxV = Math.max(autoMaxV, summary[p.vm]);
    if (p.im && summary[p.im]) autoMaxI = Math.max(autoMaxI, summary[p.im]);
  });
  if (autoMaxV === 0) autoMaxV = 132790;
  if (autoMaxI === 0) autoMaxI = 300;
  _phasorAutoScales[scaleKey] = { maxV: autoMaxV, maxI: autoMaxI };

  const ov = _phasorScaleOverrides[scaleKey] || {};
  const maxV = ov.maxV != null ? ov.maxV : autoMaxV;
  const maxI = ov.maxI != null ? ov.maxI : autoMaxI;

  const isVAuto = ov.maxV == null;
  const isIAuto = ov.maxI == null;

  drawVector(g, pMap, summary, r, w, h, center, maxV, maxI);

  // Scale control bar rendered as HTML below the SVG
  const sk = JSON.stringify(scaleKey);
  div.append("div")
    .attr("class", "phasor-scale-ctrl")
    .html(
      `<span class="psc-label">V</span>` +
      `<button class="psc-btn" onclick="_phasorScaleStep(${sk},'V',-1)" title="Halve V scale">−</button>` +
      `<span class="psc-val${isVAuto ? " psc-auto-active" : ""}">${_fmtPhasorScale(maxV, "V")}</span>` +
      `<button class="psc-btn" onclick="_phasorScaleStep(${sk},'V',1)" title="Double V scale">+</button>` +
      `<button class="psc-btn psc-auto${isVAuto ? " psc-auto-active" : ""}" onclick="_phasorScaleReset(${sk},'V')" title="Reset to auto">AUTO</button>` +
      `<span class="psc-sep"></span>` +
      `<span class="psc-label">I</span>` +
      `<button class="psc-btn" onclick="_phasorScaleStep(${sk},'I',-1)" title="Halve I scale">−</button>` +
      `<span class="psc-val${isIAuto ? " psc-auto-active" : ""}">${_fmtPhasorScale(maxI, "I")}</span>` +
      `<button class="psc-btn" onclick="_phasorScaleStep(${sk},'I',1)" title="Double I scale">+</button>` +
      `<button class="psc-btn psc-auto${isIAuto ? " psc-auto-active" : ""}" onclick="_phasorScaleReset(${sk},'I')" title="Reset to auto">AUTO</button>`
    );
}

function _fmtPhasorScale(val, axis) {
  if (axis === "V") {
    if (val >= 1e6) return (val / 1e6).toPrecision(3) + "MV";
    if (val >= 1e3) return (val / 1e3).toPrecision(3) + "kV";
    return val.toPrecision(3) + "V";
  }
  if (val >= 1e3) return (val / 1e3).toPrecision(3) + "kA";
  return val.toPrecision(3) + "A";
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
