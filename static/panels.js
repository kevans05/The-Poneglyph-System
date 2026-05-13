// ── Config modal drag support ──────────────────────────────────────────────

function _resetConfigModalPos() {
  const m = document.getElementById("config-modal");
  if (!m) return;
  m.style.transform = "translate(-50%, -50%)";
  m.style.top = "50%";
  m.style.left = "50%";
  _configModalDragged = false;
}


function _initMinimapDrag() {
  const container = document.getElementById("minimap-container");
  const header = document.getElementById("minimap-header");
  if (!container || !header || header._dragInit) return;
  header._dragInit = true;
  header.style.cursor = "move";
  let p1 = 0, p2 = 0, p3 = 0, p4 = 0;
  let dragged = false;

  header.onmousedown = (e) => {
    if (e.target.id === "minimap-toggle" || e.target.tagName === "BUTTON") return;
    e.preventDefault();
    if (!dragged) {
      const r = container.getBoundingClientRect();
      container.style.bottom = "auto";
      container.style.left = r.left + "px";
      container.style.top = r.top + "px";
      dragged = true;
    }
    p3 = e.clientX; p4 = e.clientY;
    document.onmouseup = () => { document.onmouseup = null; document.onmousemove = null; };
    document.onmousemove = (e) => {
      e.preventDefault();
      p1 = p3 - e.clientX; p2 = p4 - e.clientY;
      p3 = e.clientX; p4 = e.clientY;
      const newTop = Math.max(0, Math.min(container.offsetTop - p2, window.innerHeight - 40));
      const newLeft = Math.max(0, Math.min(container.offsetLeft - p1, window.innerWidth - 40));
      container.style.top = newTop + "px";
      container.style.left = newLeft + "px";
    };
  };
}
function _initConfigModalDrag() {
  const modal = document.getElementById("config-modal");
  const header = document.getElementById("config-modal-drag");
  if (!modal || !header || header._dragInit) return;
  header._dragInit = true;
  let p1 = 0, p2 = 0, p3 = 0, p4 = 0;
  header.onmousedown = (e) => {
    if (e.target.classList.contains("modal-close")) return;
    e.preventDefault();
    if (!_configModalDragged) {
      const r = modal.getBoundingClientRect();
      modal.style.transform = "none";
      modal.style.top = r.top + "px";
      modal.style.left = r.left + "px";
      _configModalDragged = true;
    }
    p3 = e.clientX; p4 = e.clientY;
    document.onmouseup = () => { document.onmouseup = null; document.onmousemove = null; };
    document.onmousemove = (e) => {
      e.preventDefault();
      p1 = p3 - e.clientX; p2 = p4 - e.clientY;
      p3 = e.clientX; p4 = e.clientY;
      const newTop = Math.max(0, Math.min(modal.offsetTop - p2, window.innerHeight - 50));
      const newLeft = Math.max(0, Math.min(modal.offsetLeft - p1, window.innerWidth - 80));
      modal.style.top = newTop + "px";
      modal.style.left = newLeft + "px";
    };
  };
}

// ── All Devices panel ──────────────────────────────────────────────────────

function toggleAllDevices() {
  const panel = document.getElementById("all-devices-panel");
  if (panel.classList.contains("open")) {
    panel.classList.remove("open");
  } else {
    _buildAllDevicesList();
    panel.classList.add("open");
  }
}

function _buildAllDevicesList() {
  if (!currentData || !currentData.nodes) return;
  const list = document.getElementById("all-devices-list");
  const countEl = document.getElementById("adp-count");
  list.innerHTML = "";
  countEl.textContent = " (" + currentData.nodes.length + ")";

  const groups = {};
  currentData.nodes.forEach(n => {
    if (!groups[n.type]) groups[n.type] = [];
    groups[n.type].push(n);
  });

  Object.keys(groups).sort().forEach(type => {
    const hdr = document.createElement("div");
    hdr.className = "adp-group";
    hdr.textContent = type;
    list.appendChild(hdr);

    groups[type].sort((a, b) => a.id.localeCompare(b.id)).forEach(node => {
      const item = document.createElement("div");
      item.className = "adp-item";
      item.innerHTML = '<span class="adp-item-id">' + node.id + '</span>';
      item.onclick = () => {
        panToDevice(node.id);
        openWindow(node);
      };
      list.appendChild(item);
    });
  });
}

// ── Find Device ────────────────────────────────────────────────────────────

function onFindInput(val) {
  const results = document.getElementById("find-device-results");
  if (!val || !currentData) { results.style.display = "none"; return; }
  const q = val.toLowerCase();
  const matches = currentData.nodes
    .filter(n => n.id.toLowerCase().includes(q) || n.type.toLowerCase().includes(q))
    .slice(0, 14);

  if (!matches.length) { results.style.display = "none"; return; }

  results.innerHTML = matches.map(n =>
    '<div class="find-result-item" onmousedown="panToDevice(\'' +
    n.id.replace(/'/g, "\\'") + '\')">' +
    '<span>' + n.id + '</span>' +
    '<span class="find-result-type">' + n.type + '</span></div>'
  ).join("");
  results.style.display = "block";
}

function onFindKey(e) {
  if (e.key === "Escape") {
    clearFindResults();
    e.target.value = "";
  } else if (e.key === "Enter") {
    const first = document.querySelector(".find-result-item");
    if (first) first.onmousedown();
    clearFindResults();
    e.target.blur();
  }
}

function clearFindResults() {
  const r = document.getElementById("find-device-results");
  if (r) r.style.display = "none";
}

// ── Relay input polarity toggle ────────────────────────────────────────────

function toggleInputPolarity(deviceId, inputId, currentPol) {
  const dev = (currentData && currentData.nodes) && currentData.nodes.find((n) => n.id === deviceId);
  if (!dev) return;
  const polarities = Object.assign({}, dev.params?.input_polarities || {});
  polarities[inputId] = currentPol === 1 ? -1 : 1;
  reconfigureAPI(deviceId, "update_device", { properties: { input_polarities: polarities } }).then(() => refreshData());
}

// ── Init ───────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => { _initConfigModalDrag(); _initMinimapDrag(); });


