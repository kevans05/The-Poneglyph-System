// ── Selection Tool ───────────────────────────────────────────────────────────

const selectedIds = new Set();
let _selPanelOpen = false;

const SENSOR_TYPES = new Set(["CurrentTransformer", "VoltageTransformer", "DualWindingVT"]);

function isSelecting() { return _selPanelOpen; }

function toggleSelectionPanel() {
  _selPanelOpen = !_selPanelOpen;
  const panel = document.getElementById("selection-panel");
  const btn   = document.getElementById("sel-mode-btn");
  if (_selPanelOpen) {
    panel.classList.add("open");
    btn && btn.classList.add("active");
    _loadTestsForPicker();
    _renderPickList();
  } else {
    panel.classList.remove("open");
    btn && btn.classList.remove("active");
    clearSelection();
  }
}

async function _loadTestsForPicker() {
  const sel = document.getElementById("sel-test-picker");
  sel.innerHTML = '<option value="">— pick a test —</option>';
  try {
    const data = await fetchTests();
    (data.tests || []).forEach(t => {
      const opt = document.createElement("option");
      opt.value = t.id;
      opt.textContent = t.name + (t.session_count ? ` (${t.session_count})` : "");
      sel.appendChild(opt);
    });
  } catch (e) {}
}

// ── Pick List ─────────────────────────────────────────────────────────────────

const TYPE_LABELS = {
  VoltageSource: "SOURCE",
  CircuitBreaker: "BREAKER",
  Disconnect: "DISCONNECT",
  PowerTransformer: "TRANSFORMER",
  CurrentTransformer: "CT",
  VoltageTransformer: "VT",
  DualWindingVT: "VT (DUAL)",
  Bus: "BUS",
  PowerLine: "LINE",
  Load: "LOAD",
  Relay: "RELAY",
  CTTB: "CTTB",
  FTBlock: "FT BLOCK",
  IsoBlock: "ISO BLOCK",
};

function _renderPickList() {
  const list = document.getElementById("sel-pick-list");
  if (!list) return;
  list.innerHTML = "";
  if (!currentData || !currentData.nodes || currentData.nodes.length === 0) {
    list.innerHTML = '<div class="sel-list-empty">No devices loaded</div>';
    return;
  }

  // Group by type preserving typical electrical order
  const typeOrder = [
    "VoltageSource", "PowerTransformer", "CircuitBreaker", "Disconnect",
    "Bus", "PowerLine", "Load",
    "CurrentTransformer", "VoltageTransformer", "DualWindingVT",
    "Relay", "CTTB", "FTBlock", "IsoBlock",
  ];
  const groups = {};
  currentData.nodes.forEach(n => {
    (groups[n.type] = groups[n.type] || []).push(n);
  });

  const orderedTypes = [
    ...typeOrder.filter(t => groups[t]),
    ...Object.keys(groups).filter(t => !typeOrder.includes(t)).sort(),
  ];

  orderedTypes.forEach(type => {
    const header = document.createElement("div");
    header.className = "sel-list-group";
    header.textContent = TYPE_LABELS[type] || type.toUpperCase();
    list.appendChild(header);

    groups[type].forEach(node => {
      const item = document.createElement("div");
      item.className = "sel-list-item" + (selectedIds.has(node.id) ? " sel-item-on" : "");
      item.dataset.id = node.id;

      const check = document.createElement("span");
      check.className = "sel-list-check";
      check.textContent = selectedIds.has(node.id) ? "■" : "□";

      const label = document.createElement("span");
      label.className = "sel-list-id";
      label.textContent = node.id;

      item.appendChild(check);
      item.appendChild(label);
      item.onclick = () => toggleDeviceSelection(node.id);
      list.appendChild(item);
    });
  });
}

function _syncPickList() {
  const list = document.getElementById("sel-pick-list");
  if (!list) return;
  list.querySelectorAll(".sel-list-item").forEach(item => {
    const on = selectedIds.has(item.dataset.id);
    item.classList.toggle("sel-item-on", on);
    item.querySelector(".sel-list-check").textContent = on ? "■" : "□";
  });
}

// ── Selection Actions ─────────────────────────────────────────────────────────

function selectAll() {
  if (!currentData || !currentData.nodes) return;
  currentData.nodes.forEach(n => selectedIds.add(n.id));
  _updateSelection();
}

async function applyTestSelection() {
  const testId = document.getElementById("sel-test-picker").value;
  if (!testId) return;
  try {
    const res = await fetch(`/api/tests/${testId}/devices`);
    const data = await res.json();
    (data.device_ids || []).forEach(id => selectedIds.add(id));
    _updateSelection();
  } catch (e) {
    console.error("Failed to fetch test devices:", e);
  }
}

function clearSelection() {
  selectedIds.clear();
  _updateSelection();
}

function toggleDeviceSelection(id) {
  if (selectedIds.has(id)) selectedIds.delete(id);
  else selectedIds.add(id);
  _updateSelection();
}

function _updateSelection() {
  const total = currentData ? currentData.nodes.length : 0;
  document.getElementById("sel-count-badge").textContent =
    selectedIds.size ? ` — ${selectedIds.size}/${total}` : "";
  _syncPickList();
  applySelectionHighlight();
}

function applySelectionHighlight() {
  const anySelected = selectedIds.size > 0;
  d3.select("#zoom-group").selectAll(".node")
    .classed("node-selected", d => selectedIds.has(d.id))
    .classed("node-dimmed",   d => anySelected && !selectedIds.has(d.id));
}

// Called from api-client.js after every refresh
function onTopologyRefreshed() {
  if (_selPanelOpen) _renderPickList();
  applySelectionHighlight();
}

// ── Auto-Layout ──────────────────────────────────────────────────────────────

function autoLayoutSelected() {
  if (!currentData || selectedIds.size < 2) return;

  const allSelected = currentData.nodes.filter(n => selectedIds.has(n.id));
  const sensors  = allSelected.filter(n =>  SENSOR_TYPES.has(n.type));
  const primaries = allSelected.filter(n => !SENSOR_TYPES.has(n.type));

  if (primaries.length === 0) return;

  const nodeById = {};
  currentData.nodes.forEach(n => { nodeById[n.id] = n; });

  const resolveId = v => typeof v === "string" ? v : v.id;
  const selSet = new Set(allSelected.map(n => n.id));

  // Build directed adjacency for primaries only
  const adj = {};
  const inDeg = {};
  primaries.forEach(n => { adj[n.id] = []; inDeg[n.id] = 0; });

  (currentData.edges || []).forEach(e => {
    const s = resolveId(e.source);
    const t = resolveId(e.target);
    const sOk = selSet.has(s) && !SENSOR_TYPES.has(nodeById[s]?.type);
    const tOk = selSet.has(t) && !SENSOR_TYPES.has(nodeById[t]?.type);
    if (sOk && tOk && s !== t) {
      adj[s].push(t);
      inDeg[t] = (inDeg[t] || 0) + 1;
    }
  });

  // BFS topological depth for primaries
  const depth = {};
  const queue = primaries.filter(n => !inDeg[n.id]).map(n => n.id);
  queue.forEach(id => { depth[id] = 0; });
  const seen = new Set(queue);

  let head = 0;
  while (head < queue.length) {
    const cur = queue[head++];
    (adj[cur] || []).forEach(next => {
      const nd = (depth[cur] || 0) + 1;
      if (depth[next] === undefined || depth[next] < nd) depth[next] = nd;
      if (!seen.has(next)) { seen.add(next); queue.push(next); }
    });
  }
  primaries.forEach(n => { if (depth[n.id] === undefined) depth[n.id] = 0; });

  // Group primaries into columns by depth
  const cols = {};
  primaries.forEach(n => {
    const d = depth[n.id];
    (cols[d] = cols[d] || []).push(n.id);
  });

  // Centroid of primaries (preserve general location)
  let cx = 0, cy = 0;
  primaries.forEach(n => { cx += (n.gx || 0); cy += (n.gy || 0); });
  cx /= primaries.length;
  cy /= primaries.length;

  const COL_GAP = 350;
  const ROW_GAP = 270;
  const depths = Object.keys(cols).map(Number).sort((a, b) => a - b);
  const totalW = (depths.length - 1) * COL_GAP;

  const newPos = {};
  depths.forEach((d, di) => {
    const ids = cols[d];
    const totalH = (ids.length - 1) * ROW_GAP;
    ids.forEach((id, ri) => {
      newPos[id] = {
        gx: Math.round(cx - totalW / 2 + di * COL_GAP),
        gy: Math.round(cy - totalH / 2 + ri * ROW_GAP),
      };
    });
  });

  // Place sensors on their host bushing using the host's NEW position
  sensors.forEach(sensor => {
    const s = sensor.summary || {};
    const hostId = s.Location;
    if (!hostId) return;
    const host = nodeById[hostId];
    if (!host) return;

    const hostPos = newPos[hostId] || { gx: host.gx || 0, gy: host.gy || 0 };
    const b = s.Bushing || "X";
    const p = s.Position || "inner";
    const r = { inner: 70, middle: 95, outer: 120 }[p] || 70;

    const a = getAnchorPoint(hostPos.gx, hostPos.gy, host.rotation || 0, b, 0, r);
    newPos[sensor.id] = {
      gx: Math.round(snapToGrid(a.x)),
      gy: Math.round(snapToGrid(a.y)),
    };
  });

  Promise.all(
    Object.entries(newPos).map(([id, pos]) =>
      reconfigureAPI(id, "update_position", { gx: pos.gx, gy: pos.gy })
    )
  ).then(() => refreshData());
}
