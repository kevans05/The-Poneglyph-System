"use strict";

/**
 * Application settings — a small preferences store plus its editor modal.
 *
 * Values live in localStorage under "poneglyph.settings" and are exposed
 * through window.PoneglyphSettings:
 *
 *   PoneglyphSettings.get(key)        → current value (falls back to default)
 *   PoneglyphSettings.set(key, value) → persist + notify subscribers
 *   PoneglyphSettings.all()           → shallow copy of every value
 *   PoneglyphSettings.subscribe(fn)   → fn(all) on any change; returns unsub
 *   PoneglyphSettings.reset()         → back to defaults
 *
 * Other modules (visualization.js, utils.js) read these live, so a change in
 * the modal takes effect on the next render without a reload.
 */

const _SETTINGS_KEY = "poneglyph.settings";

// Palette entries are nominal voltage *classes* (not ranges). A conductor's
// colour is the entry whose `kv` is closest to its nominal voltage, within
// _VOLTAGE_MATCH_TOL relative distance; anything further falls back to
// _UNKNOWN_VOLTAGE_COLOR. Populated from the substation's actual classes via
// the "voltage classes in this substation" panel in the settings modal.
const _DEFAULT_VOLTAGE_PALETTE = [
  { kv: 500, color: "#9b30ff", label: "500 kV" }, // purple
  { kv: 360, color: "#f2f2f2", label: "360 kV" }, // white
  { kv: 287, color: "#26d3d3", label: "287 kV" }, // cyan / turquoise
  { kv: 230, color: "#e01e1e", label: "230 kV" }, // red
  { kv: 161, color: "#ff5fbf", label: "161 kV" }, // pink
  { kv: 138, color: "#2f6bff", label: "138 kV" }, // blue
  { kv: 69,  color: "#ffd400", label: "69 kV" },  // yellow
  { kv: 25,  color: "#ff8a6b", label: "25 kV" },  // light red / coral (distinct from 230)
];

const _UNKNOWN_VOLTAGE_COLOR = "#8a8a8a";
const _VOLTAGE_MATCH_TOL = 0.15; // 15% — nearest class within this wins

// Suggested colours handed out when a newly-detected class has no palette entry.
const _AUTO_VOLTAGE_COLORS = [
  "#9b30ff", "#26d3d3", "#e01e1e", "#ff5fbf", "#2f6bff",
  "#ffd400", "#ff8a6b", "#38c172", "#f2f2f2", "#ff8c00",
];

// Trim trailing zeros from a kV figure (287, 34.5, 12.47).
function _fmtKv(kv) {
  const n = Number(kv) || 0;
  return Number.isInteger(n) ? String(n) : String(Math.round(n * 100) / 100);
}

const _SETTINGS_DEFAULTS = {
  // Seconds between automatic /api/topology refreshes. 0 disables the timer.
  autoRefreshSec: 0,
  // Zoom scale (d3 transform.k) at or below which the SLD collapses each
  // 3-phase run to a single line.
  singleLineZoom: 0.55,
  // Colour single-line runs by their voltage class.
  colorByVoltageClass: true,
  voltagePalette: _DEFAULT_VOLTAGE_PALETTE,
  // Device-placement snap grid, in world units.
  gridSnap: 20,
  // Poneglyph Hub (shared test pool / substation library). Token is per-device.
  hubUrl: "",
  hubToken: "",
  hubUser: "",
  hubTokenExpires: 0,
};

const _settingsSubscribers = new Set();
let _settingsCache = null;

function _settingsLoad() {
  if (_settingsCache) return _settingsCache;
  let stored = {};
  try {
    stored = JSON.parse(localStorage.getItem(_SETTINGS_KEY) || "{}") || {};
  } catch (e) {
    stored = {};
  }
  _settingsCache = Object.assign({}, _SETTINGS_DEFAULTS, stored);
  const pal = _settingsCache.voltagePalette;
  const stale =
    !Array.isArray(pal) ||
    pal.length === 0 ||
    // Pre-"voltage class" model used {minKv} ranges — discard it wholesale.
    pal.some((e) => e && e.minKv != null && e.kv == null);
  if (stale) {
    _settingsCache.voltagePalette = JSON.parse(JSON.stringify(_DEFAULT_VOLTAGE_PALETTE));
  } else {
    _settingsCache.voltagePalette = pal
      .map((e) => ({
        kv: Number(e.kv) || 0,
        color: e.color || _UNKNOWN_VOLTAGE_COLOR,
        label: e.label || "",
      }))
      .filter((e) => e.kv > 0);
    if (_settingsCache.voltagePalette.length === 0) {
      _settingsCache.voltagePalette = JSON.parse(JSON.stringify(_DEFAULT_VOLTAGE_PALETTE));
    }
  }
  return _settingsCache;
}

function _settingsPersist() {
  try {
    localStorage.setItem(_SETTINGS_KEY, JSON.stringify(_settingsCache));
  } catch (e) {
    /* private mode / quota — settings just won't survive reload */
  }
  _settingsSubscribers.forEach((fn) => {
    try {
      fn(Object.assign({}, _settingsCache));
    } catch (e) {
      console.error("settings subscriber failed:", e);
    }
  });
}

const PoneglyphSettings = {
  get(key) {
    const s = _settingsLoad();
    return key in s ? s[key] : _SETTINGS_DEFAULTS[key];
  },
  set(key, value) {
    _settingsLoad();
    _settingsCache[key] = value;
    _settingsPersist();
  },
  setMany(patch) {
    _settingsLoad();
    Object.assign(_settingsCache, patch);
    _settingsPersist();
  },
  all() {
    return Object.assign({}, _settingsLoad());
  },
  defaults() {
    return JSON.parse(JSON.stringify(_SETTINGS_DEFAULTS));
  },
  subscribe(fn) {
    _settingsSubscribers.add(fn);
    return () => _settingsSubscribers.delete(fn);
  },
  reset() {
    _settingsCache = JSON.parse(JSON.stringify(_SETTINGS_DEFAULTS));
    _settingsPersist();
  },
};
window.PoneglyphSettings = PoneglyphSettings;

/**
 * Nearest palette entry (by relative kV distance) for a nominal voltage, or
 * null when nothing is within tolerance.
 */
function nearestVoltageClass(kv, palette) {
  const list = palette || PoneglyphSettings.get("voltagePalette") || _DEFAULT_VOLTAGE_PALETTE;
  const v = Number(kv) || 0;
  if (v <= 0) return null;
  let best = null;
  let bestRel = Infinity;
  for (const e of list) {
    const ekv = Number(e.kv) || 0;
    if (ekv <= 0) continue;
    const rel = Math.abs(v - ekv) / ekv;
    if (rel < bestRel) {
      bestRel = rel;
      best = e;
    }
  }
  return best && bestRel <= _VOLTAGE_MATCH_TOL ? best : null;
}
window.nearestVoltageClass = nearestVoltageClass;

/**
 * Resolve a kV magnitude to a colour: the nearest configured voltage class,
 * or a neutral fallback when the substation has no matching class.
 */
function voltageClassColor(kv) {
  const hit = nearestVoltageClass(kv);
  return hit ? hit.color : _UNKNOWN_VOLTAGE_COLOR;
}
window.voltageClassColor = voltageClassColor;

/**
 * Distinct nominal voltage classes actually present in the loaded topology,
 * highest first. Values within 3% of each other are treated as one class.
 */
function detectSubstationVoltageClasses() {
  const seen = [];
  if (typeof currentData === "undefined" || !currentData || !Array.isArray(currentData.nodes)) {
    return seen;
  }
  const kvOf = window.nodeVoltageKv || (() => 0);
  currentData.nodes.forEach((n) => {
    const v = Number(kvOf(n)) || 0;
    if (v <= 0) return;
    const dup = seen.some((s) => Math.abs(s - v) / Math.max(s, v) <= 0.03);
    if (!dup) seen.push(v);
  });
  return seen.sort((a, b) => b - a);
}
window.detectSubstationVoltageClasses = detectSubstationVoltageClasses;

// ── Auto-refresh timer ───────────────────────────────────────────────────────

let _autoRefreshTimer = null;
function _applyAutoRefresh() {
  const sec = Number(PoneglyphSettings.get("autoRefreshSec")) || 0;
  if (_autoRefreshTimer) {
    clearInterval(_autoRefreshTimer);
    _autoRefreshTimer = null;
  }
  if (sec > 0 && typeof refreshData === "function") {
    _autoRefreshTimer = setInterval(() => {
      // Skip while a modal drag / connection wizard is mid-flight is unnecessary;
      // refreshData is idempotent and cheap.
      refreshData();
    }, sec * 1000);
  }
}
PoneglyphSettings.subscribe(_applyAutoRefresh);
// Kick the timer once the rest of the app has loaded.
if (typeof window !== "undefined") {
  window.addEventListener("load", _applyAutoRefresh);
}

// ── Modal ────────────────────────────────────────────────────────────────────

function showSettingsModal() {
  let overlay = document.getElementById("settings-modal-overlay");
  if (overlay) overlay.remove();

  overlay = document.createElement("div");
  overlay.id = "settings-modal-overlay";
  overlay.style.cssText =
    "position:fixed;inset:0;background:rgba(0,0,0,0.82);z-index:10700;" +
    "display:flex;align-items:center;justify-content:center;font-family:'Consolas','Courier New',monospace;";

  const box = document.createElement("div");
  box.style.cssText =
    "background:#0c0c0c;border:1px solid #888;width:460px;max-height:86vh;overflow-y:auto;" +
    "display:flex;flex-direction:column;gap:14px;padding:20px;color:#ccc;";
  overlay.appendChild(box);

  const s = PoneglyphSettings.all();

  const header = document.createElement("div");
  header.style.cssText =
    "display:flex;justify-content:space-between;align-items:center;" +
    "border-bottom:1px solid #1a1a1a;padding-bottom:8px;color:#aaa;letter-spacing:2px;font-size:11px;";
  header.innerHTML = "<span>APPLICATION SETTINGS</span>";
  const closeX = document.createElement("span");
  closeX.textContent = "[X]";
  closeX.style.cssText = "cursor:pointer;color:#666;";
  closeX.onclick = () => overlay.remove();
  header.appendChild(closeX);
  box.appendChild(header);

  // -- helpers ---------------------------------------------------------------
  const fieldWrap = (labelText, hint) => {
    const w = document.createElement("div");
    w.style.cssText = "display:flex;flex-direction:column;gap:4px;";
    const l = document.createElement("div");
    l.textContent = labelText;
    l.style.cssText = "font-size:9px;color:#888;letter-spacing:1px;";
    w.appendChild(l);
    if (hint) {
      const h = document.createElement("div");
      h.textContent = hint;
      h.style.cssText = "font-size:9px;color:#555;";
      w._hint = h;
    }
    box.appendChild(w);
    return w;
  };
  const numInput = (value, min, max, step) => {
    const i = document.createElement("input");
    i.type = "number";
    i.value = value;
    if (min != null) i.min = min;
    if (max != null) i.max = max;
    if (step != null) i.step = step;
    i.style.cssText =
      "background:#111;border:1px solid #333;color:#eee;padding:6px 8px;font-family:inherit;font-size:11px;width:100%;box-sizing:border-box;";
    return i;
  };

  // -- auto refresh --------------------------------------------------------
  const arWrap = fieldWrap("AUTO-REFRESH INTERVAL (seconds — 0 = off)");
  const arInput = numInput(s.autoRefreshSec, 0, 3600, 1);
  arWrap.appendChild(arInput);
  if (arWrap._hint) arWrap.appendChild(arWrap._hint);

  // -- single-line zoom -------------------------------------------------
  const zWrap = fieldWrap(
    "SINGLE-LINE ZOOM THRESHOLD",
    "At or below this zoom scale, 3-phase runs draw as one line.",
  );
  const zInput = numInput(s.singleLineZoom, 0.1, 3, 0.05);
  zWrap.appendChild(zInput);
  if (zWrap._hint) zWrap.appendChild(zWrap._hint);

  // -- grid snap ------------------------------------------------------------
  const gWrap = fieldWrap("DEVICE GRID SNAP (world units)");
  const gInput = numInput(s.gridSnap, 1, 200, 1);
  gWrap.appendChild(gInput);

  // -- drawing search ---------------------------------------------------
  const txtInput = (ph) => {
    const i = document.createElement("input");
    i.type = "text";
    i.placeholder = ph || "";
    i.style.cssText =
      "background:#111;border:1px solid #333;color:#eee;padding:6px 8px;font-family:inherit;font-size:11px;width:100%;box-sizing:border-box;";
    return i;
  };

  box.appendChild(
    Object.assign(document.createElement("div"), {
      textContent: "▾ DRAWING SEARCH",
      style:
        "font-size:9px;color:#3af;letter-spacing:2px;margin-top:14px;border-top:1px solid #1a1a1a;padding-top:10px;",
    }),
  );

  const dsUrlWrap = fieldWrap(
    "DRAWING SEARCH URL",
    "Base URL for the corporate drawing search server.",
  );
  const dsUrl = txtInput("https://drawings.example.com");
  dsUrlWrap.appendChild(dsUrl);
  if (dsUrlWrap._hint) dsUrlWrap.appendChild(dsUrlWrap._hint);

  const dsDlWrap = fieldWrap(
    "DRAWING DOWNLOAD URL",
    "Direct-download base URL (falls back to the search URL if blank).",
  );
  const dsDl = txtInput("https://drawings.example.com");
  dsDlWrap.appendChild(dsDl);
  if (dsDlWrap._hint) dsDlWrap.appendChild(dsDlWrap._hint);

  const dsHrsWrap = fieldWrap(
    "DRAWING CACHE REFRESH (hrs)",
    "Hours before a cached drawing-search result is re-fetched (default 4).",
  );
  const dsHrs = numInput(4, 0, 168, 1);
  dsHrsWrap.appendChild(dsHrs);
  if (dsHrsWrap._hint) dsHrsWrap.appendChild(dsHrsWrap._hint);

  const dsOut = document.createElement("textarea");
  dsOut.readOnly = true;
  dsOut.rows = 4;
  dsOut.style.cssText =
    "background:#0a0a0a;border:1px solid #222;color:#8a8;padding:6px 8px;font-family:inherit;font-size:10px;width:100%;box-sizing:border-box;resize:vertical;margin-top:6px;";
  dsOut.value = "Loading drawing-search config…";
  box.appendChild(dsOut);

  const dsBtnRow = document.createElement("div");
  dsBtnRow.style.cssText = "display:flex;gap:6px;margin-top:6px;align-items:center;";
  const dsBtn = (label) => {
    const b = document.createElement("button");
    b.textContent = label;
    b.style.cssText =
      "background:#04121c;border:1px solid #3af;color:#7fd0ff;font-family:inherit;font-size:9px;letter-spacing:0.5px;padding:5px 10px;cursor:pointer;";
    return b;
  };
  const dsGrabBtn = dsBtn("🔑 GRAB VIA WINDOWS AUTH");
  const dsOptsBtn = dsBtn("🔄 FETCH DRAWING OPTIONS");
  const dsNote = document.createElement("span");
  dsNote.style.cssText = "font-size:8px;color:#556;";
  dsNote.textContent = "Windows Auth needs both URLs set.";
  dsBtnRow.appendChild(dsGrabBtn);
  dsBtnRow.appendChild(dsOptsBtn);
  dsBtnRow.appendChild(dsNote);
  box.appendChild(dsBtnRow);

  const dsSaveConfig = () =>
    fetch("/api/drawing-search/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        base_url: dsUrl.value.trim(),
        download_url: dsDl.value.trim(),
        cache_refresh_hours: Number(dsHrs.value) || 4,
      }),
    }).then((r) => r.json());

  const dsShow = (data) => {
    const lines = [];
    if (data.platform) lines.push("server: " + data.platform + "   config: " + (data.config_path || "—"));
    lines.push("configured: " + (data.configured ? "yes" : "no"));
    lines.push(
      "cookies: " + (data.cookie_names && data.cookie_names.length ? data.cookie_names.join(", ") : "none"),
    );
    if (data.error) lines.push("⚠ " + data.error);
    dsOut.value = lines.join("\n");
  };

  fetch("/api/drawing-search/config")
    .then((r) => r.json())
    .then((cfg) => {
      dsUrl.value = cfg.base_url || "";
      dsDl.value = cfg.download_url || "";
      if (cfg.cache_refresh_hours != null) dsHrs.value = cfg.cache_refresh_hours;
      dsShow(cfg);
    })
    .catch(() => (dsOut.value = "Could not load drawing-search config."));

  dsGrabBtn.onclick = () => {
    dsOut.value = "Saving config, then grabbing cookies via Windows Auth…";
    dsSaveConfig()
      .then(() =>
        fetch("/api/drawing-search/grab-cookies", { method: "POST" }).then((r) => r.json()),
      )
      .then((res) => {
        if (res.ok) {
          dsOut.value = "✓ Cookies grabbed: " + (res.cookie_names || []).join(", ");
        } else {
          dsOut.value = "✗ " + (res.error || "grab failed");
        }
      })
      .catch(() => (dsOut.value = "✗ request failed"));
  };

  dsOptsBtn.onclick = () => {
    dsOut.value = "Saving config, then fetching drawing options…";
    dsSaveConfig()
      .then(() =>
        fetch("/api/drawing-search/options/refresh", { method: "POST" }).then((r) => r.json()),
      )
      .then((opts) => {
        const n = (o) => (o ? Object.keys(o).length : 0);
        dsOut.value =
          "✓ options: " +
          n(opts.facilities) + " facilities, " +
          n(opts.drawing_types) + " types, " +
          n(opts.drawing_subjects) + " subjects";
      })
      .catch(() => (dsOut.value = "✗ fetch failed"));
  };

  // -- Poneglyph Hub ---------------------------------------------------
  box.appendChild(
    Object.assign(document.createElement("div"), {
      textContent: "▾ PONEGLYPH HUB",
      style:
        "font-size:9px;color:#3fdc8f;letter-spacing:2px;margin-top:14px;border-top:1px solid #1a1a1a;padding-top:10px;",
    }),
  );

  const hubUrlWrap = fieldWrap(
    "HUB URL",
    "Shared server for the test pool. Leave blank to work local-only.",
  );
  const hubUrlInput = txtInput("https://hub.example.internal");
  hubUrlInput.value = s.hubUrl || "";
  hubUrlWrap.appendChild(hubUrlInput);
  if (hubUrlWrap._hint) hubUrlWrap.appendChild(hubUrlWrap._hint);

  const hubBox = document.createElement("div");
  hubBox.style.cssText =
    "display:flex;flex-direction:column;gap:6px;margin-top:6px;";
  box.appendChild(hubBox);

  const hubMsg = document.createElement("div");
  hubMsg.style.cssText = "font-size:9px;color:#8a8;min-height:12px;";

  const renderHub = () => {
    hubBox.innerHTML = "";
    const st = PoneglyphHub.status();
    const line = document.createElement("div");
    line.style.cssText = "font-size:10px;color:#aaa;";
    if (st.connected) {
      const exp = st.expires
        ? new Date(st.expires * 1000).toLocaleDateString()
        : "—";
      line.textContent = "";
      line.appendChild(document.createTextNode("Signed in as "));
      const who = document.createElement("b");
      who.style.color = "#3fdc8f";
      who.textContent = st.user || "operator";
      line.appendChild(who);
      line.appendChild(document.createTextNode(" · token valid to " + exp));
      const out = document.createElement("button");
      out.textContent = "DISCONNECT";
      out.style.cssText =
        "align-self:flex-start;background:#1a0000;border:1px solid #833;color:#c66;font-family:inherit;font-size:9px;padding:5px 10px;cursor:pointer;";
      out.onclick = () => {
        hubMsg.textContent = "Signing out…";
        PoneglyphHub.logout().then(() => {
          hubMsg.textContent = "";
          renderHub();
        });
      };
      hubBox.appendChild(line);
      hubBox.appendChild(out);
    } else {
      line.textContent = st.configured
        ? "Not signed in."
        : "Set a hub URL above, then sign in.";
      const u = txtInput("username");
      const p = txtInput("password");
      p.type = "password";
      const go = document.createElement("button");
      go.textContent = "CONNECT";
      go.style.cssText =
        "align-self:flex-start;background:#04121c;border:1px solid #3fdc8f;color:#3fdc8f;font-family:inherit;font-size:9px;letter-spacing:0.5px;padding:5px 12px;cursor:pointer;";
      go.onclick = () => {
        const url = hubUrlInput.value.trim();
        if (!url) {
          hubMsg.textContent = "Enter the hub URL first.";
          return;
        }
        PoneglyphSettings.set("hubUrl", url);
        hubMsg.textContent = "Connecting…";
        PoneglyphHub.login(u.value.trim(), p.value)
          .then(() => {
            hubMsg.textContent = "✓ connected";
            renderHub();
          })
          .catch((e) => {
            hubMsg.textContent = "✗ " + (e.message || "login failed");
          });
      };
      hubBox.appendChild(line);
      hubBox.appendChild(u);
      hubBox.appendChild(p);
      hubBox.appendChild(go);
    }
    hubBox.appendChild(hubMsg);
  };
  renderHub();

  // -- colour by voltage class -------------------------------------------
  const cWrap = fieldWrap("SINGLE-LINE COLOUR");
  const cRow = document.createElement("label");
  cRow.style.cssText = "display:flex;align-items:center;gap:8px;font-size:11px;color:#ccc;cursor:pointer;";
  const cCheck = document.createElement("input");
  cCheck.type = "checkbox";
  cCheck.checked = !!s.colorByVoltageClass;
  cRow.appendChild(cCheck);
  cRow.appendChild(document.createTextNode("Colour single lines by voltage class"));
  cWrap.appendChild(cRow);

  let workingPalette = JSON.parse(JSON.stringify(s.voltagePalette)).map((e) => ({
    kv: Number(e.kv) || 0,
    color: e.color || _UNKNOWN_VOLTAGE_COLOR,
    label: e.label || "",
  }));

  let renderPalette = () => {};

  const _nextAutoColor = () => {
    const used = new Set(workingPalette.map((e) => (e.color || "").toLowerCase()));
    for (const c of _AUTO_VOLTAGE_COLORS) if (!used.has(c.toLowerCase())) return c;
    return _AUTO_VOLTAGE_COLORS[workingPalette.length % _AUTO_VOLTAGE_COLORS.length];
  };
  const _matchInWorking = (kv) => nearestVoltageClass(kv, workingPalette);

  // -- detected substation classes -------------------------------------
  const detected = detectSubstationVoltageClasses();
  const dWrap = fieldWrap(
    "VOLTAGE CLASSES IN THIS SUBSTATION",
    detected.length
      ? "Colours below apply to the classes actually present. Unmatched classes fall back to grey."
      : "Load a site to detect its voltage classes.",
  );
  const dTable = document.createElement("div");
  dTable.style.cssText = "display:flex;flex-direction:column;gap:3px;";
  dWrap.appendChild(dTable);
  if (dWrap._hint) dWrap.appendChild(dWrap._hint);

  const renderDetected = () => {
    dTable.innerHTML = "";
    if (!detected.length) {
      const none = document.createElement("div");
      none.textContent = "— none detected —";
      none.style.cssText = "font-size:10px;color:#555;padding:2px 0;";
      dTable.appendChild(none);
      return;
    }
    detected.forEach((kv) => {
      const row = document.createElement("div");
      row.style.cssText = "display:flex;gap:8px;align-items:center;font-size:10px;";
      const match = _matchInWorking(kv);

      const name = document.createElement("span");
      name.textContent = _fmtKv(kv) + " kV";
      name.style.cssText = "width:74px;color:#ddd;";

      const chip = document.createElement("span");
      chip.style.cssText =
        "width:16px;height:16px;border:1px solid #333;flex:0 0 16px;" +
        "background:" + (match ? match.color : "repeating-linear-gradient(45deg,#333,#333 3px,#111 3px,#111 6px)") + ";";

      const status = document.createElement("span");
      status.style.cssText = "flex:1;color:" + (match ? "#8a8" : "#a86") + ";";
      status.textContent = match ? "→ " + (match.label || _fmtKv(match.kv) + " kV") : "no colour assigned";

      row.appendChild(name);
      row.appendChild(chip);
      row.appendChild(status);

      if (!match) {
        const addOne = document.createElement("button");
        addOne.textContent = "+ COLOUR";
        addOne.style.cssText =
          "background:#001a00;color:#4f4;border:1px solid #4f4;cursor:pointer;font-size:9px;padding:2px 6px;";
        addOne.onclick = () => {
          workingPalette.push({ kv: kv, color: _nextAutoColor(), label: _fmtKv(kv) + " kV" });
          renderPalette();
          renderDetected();
        };
        row.appendChild(addOne);
      }
      dTable.appendChild(row);
    });
  };

  const syncBtn = document.createElement("button");
  syncBtn.textContent = "SYNC PALETTE TO SUBSTATION";
  syncBtn.style.cssText =
    "margin-top:6px;background:#00141a;color:#3cf;border:1px solid #3cf;cursor:pointer;font-size:10px;padding:5px;width:100%;";
  syncBtn.onclick = () => {
    // Add a colour for every detected class that has no match.
    detected.forEach((kv) => {
      if (!_matchInWorking(kv)) {
        workingPalette.push({ kv: kv, color: _nextAutoColor(), label: _fmtKv(kv) + " kV" });
      }
    });
    // Drop palette entries that no detected class points at.
    if (detected.length) {
      workingPalette = workingPalette.filter((e) =>
        detected.some((kv) => {
          const ekv = Number(e.kv) || 0;
          return ekv > 0 && Math.abs(kv - ekv) / ekv <= _VOLTAGE_MATCH_TOL;
        }),
      );
    }
    renderPalette();
    renderDetected();
  };
  dWrap.appendChild(syncBtn);
  renderDetected();

  // -- palette editor ----------------------------------------------------
  const pWrap = fieldWrap("VOLTAGE-CLASS PALETTE  (nominal kV → colour)");
  const pTable = document.createElement("div");
  pTable.style.cssText = "display:flex;flex-direction:column;gap:4px;";
  pWrap.appendChild(pTable);

  renderPalette = () => {
    pTable.innerHTML = "";
    workingPalette
      .slice()
      .sort((a, b) => b.kv - a.kv)
      .forEach((entry) => {
        const row = document.createElement("div");
        row.style.cssText = "display:flex;gap:6px;align-items:center;";

        const inSub =
          detected.length === 0 ||
          detected.some((kv) => {
            const ekv = Number(entry.kv) || 0;
            return ekv > 0 && Math.abs(kv - ekv) / ekv <= _VOLTAGE_MATCH_TOL;
          });

        const kv = document.createElement("input");
        kv.type = "number";
        kv.value = entry.kv;
        kv.min = 0;
        kv.step = 0.1;
        kv.title = "nominal voltage class (kV)";
        kv.style.cssText =
          "width:70px;background:#111;border:1px solid #333;color:#eee;padding:4px 6px;font-family:inherit;font-size:10px;";
        kv.oninput = () => {
          entry.kv = parseFloat(kv.value) || 0;
        };

        const sw = document.createElement("input");
        sw.type = "color";
        sw.value = entry.color;
        sw.style.cssText = "width:38px;height:26px;background:#111;border:1px solid #333;padding:0;cursor:pointer;";
        sw.oninput = () => {
          entry.color = sw.value;
        };

        const lbl = document.createElement("input");
        lbl.type = "text";
        lbl.value = entry.label || "";
        lbl.placeholder = "label";
        lbl.style.cssText =
          "flex:1;background:#111;border:1px solid #333;color:" +
          (inSub ? "#aaa" : "#555") +
          ";padding:4px 6px;font-family:inherit;font-size:10px;";
        lbl.oninput = () => {
          entry.label = lbl.value;
        };

        const tag = document.createElement("span");
        tag.textContent = inSub ? "" : "· not in substation";
        tag.style.cssText = "font-size:8px;color:#654;white-space:nowrap;";

        const del = document.createElement("button");
        del.textContent = "✕";
        del.title = "remove class";
        del.style.cssText =
          "flex:0 0 24px;background:#200;color:#f55;border:1px solid #f55;cursor:pointer;font-size:10px;padding:2px 0;";
        del.onclick = () => {
          workingPalette = workingPalette.filter((e) => e !== entry);
          renderPalette();
          renderDetected();
        };

        row.appendChild(kv);
        row.appendChild(sw);
        row.appendChild(lbl);
        if (!inSub) row.appendChild(tag);
        row.appendChild(del);
        pTable.appendChild(row);
      });

    const add = document.createElement("button");
    add.textContent = "+ ADD CLASS";
    add.style.cssText =
      "margin-top:4px;background:#001a00;color:#4f4;border:1px solid #4f4;cursor:pointer;font-size:10px;padding:4px;width:100%;";
    add.onclick = () => {
      workingPalette.push({ kv: 0, color: _nextAutoColor(), label: "" });
      renderPalette();
    };
    pTable.appendChild(add);
  };
  renderPalette();

  // -- footer -----------------------------------------------------------
  const footer = document.createElement("div");
  footer.style.cssText = "display:flex;gap:8px;justify-content:flex-end;border-top:1px solid #1a1a1a;padding-top:12px;";

  const resetBtn = document.createElement("button");
  resetBtn.textContent = "RESET DEFAULTS";
  resetBtn.style.cssText =
    "background:#0a0a0a;border:1px solid #333;color:#777;font-family:inherit;font-size:10px;padding:6px 12px;cursor:pointer;margin-right:auto;";
  resetBtn.onclick = () => {
    PoneglyphSettings.reset();
    overlay.remove();
    if (typeof currentData !== "undefined" && currentData && typeof render3LD === "function") {
      render3LD(currentData);
    }
  };

  const cancelBtn = document.createElement("button");
  cancelBtn.textContent = "CANCEL";
  cancelBtn.style.cssText =
    "background:#0a0a0a;border:1px solid #333;color:#555;font-family:inherit;font-size:10px;padding:6px 14px;cursor:pointer;";
  cancelBtn.onclick = () => overlay.remove();

  const saveBtn = document.createElement("button");
  saveBtn.textContent = "APPLY";
  saveBtn.style.cssText =
    "background:#001a00;border:1px solid #0f0;color:#0f0;font-family:inherit;font-size:10px;padding:6px 18px;cursor:pointer;";
  saveBtn.onclick = () => {
    const clean = workingPalette
      .map((e) => ({ kv: Number(e.kv) || 0, color: e.color || _UNKNOWN_VOLTAGE_COLOR, label: e.label || "" }))
      .filter((e) => e.kv > 0)
      .sort((a, b) => b.kv - a.kv);
    PoneglyphSettings.setMany({
      autoRefreshSec: Math.max(0, Number(arInput.value) || 0),
      singleLineZoom: Math.min(3, Math.max(0.1, Number(zInput.value) || 0.55)),
      gridSnap: Math.min(200, Math.max(1, Number(gInput.value) || 20)),
      colorByVoltageClass: cCheck.checked,
      voltagePalette: clean.length ? clean : _DEFAULT_VOLTAGE_PALETTE,
      hubUrl: hubUrlInput.value.trim(),
    });
    dsSaveConfig().catch(() => {}); // persist drawing-search URLs / refresh (server-side)
    overlay.remove();
    if (typeof currentData !== "undefined" && currentData && typeof render3LD === "function") {
      render3LD(currentData);
    }
  };

  footer.appendChild(resetBtn);
  footer.appendChild(cancelBtn);
  footer.appendChild(saveBtn);
  box.appendChild(footer);

  overlay.addEventListener("mousedown", (e) => {
    if (e.target === overlay) overlay.remove();
  });
  document.body.appendChild(overlay);
}
window.showSettingsModal = showSettingsModal;
