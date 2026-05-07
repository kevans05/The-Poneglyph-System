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
  if (Math.abs(dx) >= Math.abs(dy)) {
    const midX = x1 + dx * frac + offset;
    return `M ${x1},${y1} L ${midX},${y1} L ${midX},${y2} L ${x2},${y2}`;
  } else {
    const midY = y1 + dy * frac + offset;
    return `M ${x1},${y1} L ${x1},${midY} L ${x2},${midY} L ${x2},${y2}`;
  }
}

function render3LD(data) {
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
        const host = data.nodes.find((n) => n.id === node.summary.Location);
        if (host) {
          const b = node.summary.Bushing || "X",
            p = node.summary.Position || "inner",
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

    if (edge.type === "protection") {
      let wireClass = "secondary-wire";
      if (["CurrentTransformer", "CTTB"].includes(src.type))
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
        if (src.summary.Connection.includes("Delta")) isDelta = true;
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

    // Draw symbols...
    if (d.type === "CurrentTransformer") {
      [-PHASE_GAP, 0, PHASE_GAP].forEach((off, i) => {
        const c = ["#f00", "#ff0", "#00f"][i];
        el.append("circle")
          .attr("cx", 0)
          .attr("cy", off)
          .attr("r", 8)
          .attr("fill", "none")
          .attr("stroke", c);
        el.append("path")
          .attr("d", "M-8," + off + " A8,8 0 0,1 8," + off)
          .attr("stroke", c)
          .attr("fill", "none");
        el.append("circle")
          .attr("cx", 0)
          .attr("cy", off - 10)
          .attr("r", 2)
          .attr("fill", "#ffff22")
          .attr("stroke", "#000")
          .attr("stroke-width", 0.5);
      });
    } else if (d.type === "VoltageTransformer" || d.type === "DualWindingVT") {
      [-PHASE_GAP, 0, PHASE_GAP].forEach((off, i) => {
        const c = ["#f00", "#ff0", "#00f"][i];
        el.append("circle")
          .attr("cx", 0)
          .attr("cy", off)
          .attr("r", 8)
          .attr("fill", "#000")
          .attr("stroke", c)
          .attr("stroke-width", 1.5);
        for (let j = -6; j <= 6; j += 4) {
          const l = Math.sqrt(64 - j * j);
          el.append("line")
            .attr("x1", j)
            .attr("y1", off - l)
            .attr("x2", j)
            .attr("y2", off + l)
            .attr("stroke", c)
            .attr("stroke-width", 0.5)
            .attr("opacity", 0.6);
        }
        el.append("circle")
          .attr("cx", 0)
          .attr("cy", off - 10)
          .attr("r", 2)
          .attr("fill", "#ff3333")
          .attr("stroke", "#000")
          .attr("stroke-width", 0.5);
      });
      if (d.type === "DualWindingVT")
        el.append("circle")
          .attr("cx", 0)
          .attr("cy", 0)
          .attr("r", 25)
          .attr("fill", "none")
          .attr("stroke", "#888")
          .attr("stroke-dasharray", "2,2");
    } else if (d.type === "CTTB" || d.type === "FTBlock") {
      const c = d.type === "CTTB" ? "#ffff22" : "#ff3333";
      el.append("rect")
        .attr("x", -15)
        .attr("y", -25)
        .attr("width", 30)
        .attr("height", 50)
        .attr("fill", "#111")
        .attr("stroke", c)
        .attr("stroke-width", 2);
      el.append("text")
        .attr("dy", -28)
        .attr("fill", "#fff")
        .style("font-size", "7px")
        .text(d.type === "CTTB" ? "CTTB" : "FT");
      for (let i = -18; i <= 18; i += 9) {
        el.append("circle")
          .attr("cx", -10)
          .attr("cy", i)
          .attr("r", 2)
          .attr("fill", "#333")
          .attr("stroke", c);
        el.append("circle")
          .attr("cx", 10)
          .attr("cy", i)
          .attr("r", 2)
          .attr("fill", "#333")
          .attr("stroke", c);
      }
    } else if (d.type === "Relay") {
      el.append("rect")
        .attr("x", -25)
        .attr("y", -30)
        .attr("width", 50)
        .attr("height", 60)
        .attr("fill", "#222")
        .attr("stroke", "#0f0")
        .attr("stroke-width", 2);
      el.append("text")
        .attr("dy", 4)
        .attr("fill", "#0f0")
        .style("font-size", "14px")
        .style("font-weight", "bold")
        .text((d.summary.Function || "87").substring(0, 3));
      for (let i = -18; i <= 18; i += 9)
        el.append("circle")
          .attr("cx", i)
          .attr("cy", 24)
          .attr("r", 2)
          .attr("fill", "#333")
          .attr("stroke", "#0f0");
    } else if (d.type === "PowerTransformer") {
      el.append("circle")
        .attr("cx", -20)
        .attr("cy", 0)
        .attr("r", 25)
        .attr("fill", "none")
        .attr("stroke", "#fff")
        .attr("stroke-width", 2);
      el.append("circle")
        .attr("cx", 20)
        .attr("cy", 0)
        .attr("r", 25)
        .attr("fill", "none")
        .attr("stroke", "#fff")
        .attr("stroke-width", 2);
    } else if (["CircuitBreaker", "Disconnect"].includes(d.type)) {
      el.append("rect")
        .attr("class", "breaker-frame")
        .attr("x", -30)
        .attr("y", -30)
        .attr("width", 60)
        .attr("height", 60);
      [-PHASE_GAP, 0, PHASE_GAP].forEach((off, i) =>
        el
          .append("line")
          .attr(
            "class",
            "breaker-contact " + ["phase-a", "phase-b", "phase-c"][i],
          )
          .attr("x1", -30)
          .attr("x2", 30)
          .attr("y1", off)
          .attr("y2", off)
          .attr("stroke-dasharray", d.status === "OPEN" ? "4,4" : "none"),
      );
      el.append("line")
        .attr("class", "neutral")
        .attr("x1", -30)
        .attr("x2", 30)
        .attr("y1", PHASE_GAP * 2)
        .attr("y2", PHASE_GAP * 2)
        .attr("stroke-width", 2);
    } else if (d.type === "ShuntCapacitor") {
      // Capacitor symbol (two horizontal plates with vertical leads)
      el.append("line").attr("x1", 0).attr("y1", -26).attr("x2", 0).attr("y2", -10).attr("stroke", "#4df").attr("stroke-width", 2);
      el.append("line").attr("x1", -20).attr("y1", -10).attr("x2", 20).attr("y2", -10).attr("stroke", "#4df").attr("stroke-width", 3.5);
      el.append("line").attr("x1", -20).attr("y1", 4).attr("x2", 20).attr("y2", 4).attr("stroke", "#4df").attr("stroke-width", 3.5);
      el.append("line").attr("x1", 0).attr("y1", 4).attr("x2", 0).attr("y2", 18).attr("stroke", "#4df").attr("stroke-width", 2);
      el.append("line").attr("x1", -12).attr("y1", 18).attr("x2", 12).attr("y2", 18).attr("stroke", "#666").attr("stroke-width", 2);
      el.append("line").attr("x1", -7).attr("y1", 22).attr("x2", 7).attr("y2", 22).attr("stroke", "#666").attr("stroke-width", 1.5);
      el.append("line").attr("x1", -3).attr("y1", 26).attr("x2", 3).attr("y2", 26).attr("stroke", "#666").attr("stroke-width", 1);
    } else if (d.type === "ShuntReactor") {
      // Reactor symbol (IEC rectangle = inductor)
      el.append("line").attr("x1", 0).attr("y1", -28).attr("x2", 0).attr("y2", -16).attr("stroke", "#f90").attr("stroke-width", 2);
      el.append("rect").attr("x", -14).attr("y", -16).attr("width", 28).attr("height", 32).attr("fill", "#1a0f00").attr("stroke", "#f90").attr("stroke-width", 2);
      el.append("text").attr("x", 0).attr("y", 3).attr("text-anchor", "middle").attr("dominant-baseline", "middle").attr("font-size", "9px").attr("fill", "#f90").text("L");
      el.append("line").attr("x1", 0).attr("y1", 16).attr("x2", 0).attr("y2", 28).attr("stroke", "#f90").attr("stroke-width", 2);
      el.append("line").attr("x1", -12).attr("y1", 28).attr("x2", 12).attr("y2", 28).attr("stroke", "#666").attr("stroke-width", 2);
      el.append("line").attr("x1", -7).attr("y1", 32).attr("x2", 7).attr("y2", 32).attr("stroke", "#666").attr("stroke-width", 1.5);
      el.append("line").attr("x1", -3).attr("y1", 36).attr("x2", 3).attr("y2", 36).attr("stroke", "#666").attr("stroke-width", 1);
    } else if (d.type === "SurgeArrester") {
      // Arrow pointing toward ground + ground symbol
      el.append("line").attr("x1", 0).attr("y1", -26).attr("x2", 0).attr("y2", -12).attr("stroke", "#ff6").attr("stroke-width", 2);
      el.append("polygon").attr("points", "0,14 -14,-12 14,-12").attr("fill", "#ff6").attr("fill-opacity", 0.35).attr("stroke", "#ff6").attr("stroke-width", 1.5);
      el.append("line").attr("x1", 0).attr("y1", 14).attr("x2", 0).attr("y2", 26).attr("stroke", "#ff6").attr("stroke-width", 2);
      el.append("line").attr("x1", -12).attr("y1", 26).attr("x2", 12).attr("y2", 26).attr("stroke", "#666").attr("stroke-width", 2);
      el.append("line").attr("x1", -7).attr("y1", 30).attr("x2", 7).attr("y2", 30).attr("stroke", "#666").attr("stroke-width", 1.5);
      el.append("line").attr("x1", -3).attr("y1", 34).attr("x2", 3).attr("y2", 34).attr("stroke", "#666").attr("stroke-width", 1);
    } else if (d.type === "SVC") {
      // Diamond shape (variable reactive device)
      el.append("polygon").attr("points", "0,-20 18,0 0,20 -18,0").attr("fill", "none").attr("stroke", "#0ff").attr("stroke-width", 2);
      el.append("line").attr("x1", -14).attr("y1", -8).attr("x2", 14).attr("y2", 8).attr("stroke", "#0ff").attr("stroke-width", 1.5);
      el.append("line").attr("x1", 0).attr("y1", -28).attr("x2", 0).attr("y2", -20).attr("stroke", "#0ff").attr("stroke-width", 2);
      el.append("line").attr("x1", 0).attr("y1", 20).attr("x2", 0).attr("y2", 32).attr("stroke", "#0ff").attr("stroke-width", 2);
      el.append("line").attr("x1", -12).attr("y1", 32).attr("x2", 12).attr("y2", 32).attr("stroke", "#666").attr("stroke-width", 2);
      el.append("line").attr("x1", -7).attr("y1", 36).attr("x2", 7).attr("y2", 36).attr("stroke", "#666").attr("stroke-width", 1.5);
    } else if (d.type === "NeutralGroundingResistor") {
      // Vertical zigzag (resistor symbol) + ground
      el.append("line").attr("x1", 0).attr("y1", -28).attr("x2", 0).attr("y2", -16).attr("stroke", "#aaa").attr("stroke-width", 2);
      el.append("polyline").attr("points", "0,-16 8,-12 -8,-8 8,-4 -8,0 8,4 -8,8 0,12").attr("fill", "none").attr("stroke", "#aaa").attr("stroke-width", 2).attr("stroke-linejoin", "round");
      el.append("line").attr("x1", 0).attr("y1", 12).attr("x2", 0).attr("y2", 26).attr("stroke", "#aaa").attr("stroke-width", 2);
      el.append("line").attr("x1", -12).attr("y1", 26).attr("x2", 12).attr("y2", 26).attr("stroke", "#666").attr("stroke-width", 2);
      el.append("line").attr("x1", -7).attr("y1", 30).attr("x2", 7).attr("y2", 30).attr("stroke", "#666").attr("stroke-width", 1.5);
      el.append("line").attr("x1", -3).attr("y1", 34).attr("x2", 3).attr("y2", 34).attr("stroke", "#666").attr("stroke-width", 1);
    } else if (d.type === "SeriesCapacitor") {
      // Inline series: stubs to two vertical plates
      el.append("line").attr("x1", -55).attr("y1", 0).attr("x2", -12).attr("y2", 0).attr("stroke", "#4df").attr("stroke-width", 2);
      el.append("line").attr("x1", 12).attr("y1", 0).attr("x2", 55).attr("y2", 0).attr("stroke", "#4df").attr("stroke-width", 2);
      el.append("line").attr("x1", -12).attr("y1", -18).attr("x2", -12).attr("y2", 18).attr("stroke", "#4df").attr("stroke-width", 3.5);
      el.append("line").attr("x1", 12).attr("y1", -18).attr("x2", 12).attr("y2", 18).attr("stroke", "#4df").attr("stroke-width", 3.5);
    } else if (d.type === "SeriesReactor") {
      // Inline series: stubs to a center rectangle
      el.append("line").attr("x1", -55).attr("y1", 0).attr("x2", -20).attr("y2", 0).attr("stroke", "#f90").attr("stroke-width", 2);
      el.append("line").attr("x1", 20).attr("y1", 0).attr("x2", 55).attr("y2", 0).attr("stroke", "#f90").attr("stroke-width", 2);
      el.append("rect").attr("x", -20).attr("y", -13).attr("width", 40).attr("height", 26).attr("fill", "#1a0f00").attr("stroke", "#f90").attr("stroke-width", 2);
      el.append("text").attr("x", 0).attr("y", 4).attr("text-anchor", "middle").attr("dominant-baseline", "middle").attr("font-size", "9px").attr("fill", "#f90").text("XL");
    } else if (d.type === "LineTrap") {
      // Inline series: stubs to oval LC symbol
      el.append("line").attr("x1", -55).attr("y1", 0).attr("x2", -22).attr("y2", 0).attr("stroke", "#8f8").attr("stroke-width", 2);
      el.append("line").attr("x1", 22).attr("y1", 0).attr("x2", 55).attr("y2", 0).attr("stroke", "#8f8").attr("stroke-width", 2);
      el.append("ellipse").attr("cx", 0).attr("cy", 0).attr("rx", 22).attr("ry", 15).attr("fill", "#001a00").attr("stroke", "#8f8").attr("stroke-width", 2);
      el.append("text").attr("x", 0).attr("y", 4).attr("text-anchor", "middle").attr("dominant-baseline", "middle").attr("font-size", "8px").attr("fill", "#8f8").text("WT");
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
    if (!priDiv.empty()) renderPhasorBox(priDiv, summary, "primary");
    if (!secDiv.empty()) renderPhasorBox(secDiv, summary, "secondary");
  } else if (type === "DualWindingVT") {
    const secDiv = d3.select("#phasor-sec-" + safeId),
      sec2Div = d3.select("#phasor-sec2-" + safeId);
    if (!secDiv.empty()) renderPhasorBox(secDiv, summary, "secondary");
    if (!sec2Div.empty()) renderPhasorBox(sec2Div, summary, "sec2");
  } else if (type === "VoltageTransformer") {
    const phasorDiv = d3.select("#phasor-" + safeId);
    if (!phasorDiv.empty()) renderPhasorBox(phasorDiv, summary, "secondary");
  } else if (type === "CurrentTransformer") {
    const phasorDiv = d3.select("#phasor-" + safeId);
    if (!phasorDiv.empty()) renderPhasorBox(phasorDiv, summary, "ct_secondary");
  } else {
    const phasorDiv = d3.select("#phasor-" + safeId);
    if (!phasorDiv.empty()) renderPhasorBox(phasorDiv, summary, "all");
  }
}

function renderPhasorBox(div, summary, mode) {
  div.selectAll("*").remove();
  const w = 376,
    h = 260,
    r = 90,
    center = { x: w / 2, y: h / 2 };
  const g = div
    .append("svg")
    .attr("width", w)
    .attr("height", h)
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
    summary && summary.Connection && summary.Connection.includes("Delta");

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
          c: "#f00",
        },
        {
          n: "BC",
          vm: "Sec Voltage Phase BC",
          va: "Phase BC V-Angle",
          c: "#ff0",
        },
        {
          n: "CA",
          vm: "Sec Voltage Phase CA",
          va: "Phase CA V-Angle",
          c: "#00f",
        },
      ];
    } else {
      pMap = [
        { n: "A", vm: "Sec Voltage Phase A", va: "Phase A V-Angle", c: "#f00" },
        { n: "B", vm: "Sec Voltage Phase B", va: "Phase B V-Angle", c: "#ff0" },
        { n: "C", vm: "Sec Voltage Phase C", va: "Phase C V-Angle", c: "#00f" },
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

  let maxV = 0,
    maxI = 0;
  pMap.forEach((p) => {
    if (p.vm && summary[p.vm]) maxV = Math.max(maxV, summary[p.vm]);
    if (p.im && summary[p.im]) maxI = Math.max(maxI, summary[p.im]);
  });
  if (maxV === 0) maxV = 132790;
  if (maxI === 0) maxI = 300;
  g.append("text")
    .attr("x", -w / 2 + 10)
    .attr("y", h / 2 - 25)
    .attr("fill", "#666")
    .style("font-size", "10px")
    .text("V-Scale: " + maxV.toFixed(0) + "V");
  g.append("text")
    .attr("x", -w / 2 + 10)
    .attr("y", h / 2 - 12)
    .attr("fill", "#666")
    .style("font-size", "10px")
    .text("I-Scale: " + maxI.toFixed(1) + "A");
  drawVector(g, pMap, summary, r, w, h, center, maxV, maxI);
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
      const lbx = c.anchor === "middle" ? cx - lw / 2
                : c.anchor === "start"  ? cx
                : cx - lw;
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
    const flx = best.anchor === "middle" ? fx - lw / 2
              : best.anchor === "start"  ? fx
              : fx - lw;
    placed.push({ x: flx, y: fy - lh / 2, w: lw, h: lh });
  });
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
    if (gx < minX) minX = gx;
    if (gy < minY) minY = gy;
    if (gx > maxX) maxX = gx;
    if (gy > maxY) maxY = gy;
  });

  const pad = 60;
  minimapScaleX.domain([minX - pad, maxX + pad]).range([MINIMAP_PAD, MINIMAP_W - MINIMAP_PAD]);
  minimapScaleY.domain([minY - pad, maxY + pad]).range([MINIMAP_PAD, MINIMAP_H - MINIMAP_PAD]);

  const nodeById = {};
  nodes.forEach(n => { nodeById[n.id] = n; });

  const resolveId = e => typeof e === "string" ? e : e.id;

  const edgeSel = d3.select("#minimap-edges").selectAll("line")
    .data(currentData.edges || []);
  edgeSel.enter().append("line")
    .merge(edgeSel)
    .attr("x1", d => { const n = nodeById[resolveId(d.source)]; return n ? minimapScaleX(n.gx || 0) : 0; })
    .attr("y1", d => { const n = nodeById[resolveId(d.source)]; return n ? minimapScaleY(n.gy || 0) : 0; })
    .attr("x2", d => { const n = nodeById[resolveId(d.target)]; return n ? minimapScaleX(n.gx || 0) : 0; })
    .attr("y2", d => { const n = nodeById[resolveId(d.target)]; return n ? minimapScaleY(n.gy || 0) : 0; })
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
      if (d.type === "Load") return "#ff4444";
      if (d.type === "Bus") return "#555";
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
