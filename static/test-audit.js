"use strict";

/**
 * test-audit.js — the AUDIT view for a test: reviewing recorded results,
 * validating neutral/residual balance, checking primary→secondary chains,
 * and comparing any two measurement sets against each other.
 *
 * All the phasor math (parsing keys, vector sums, chain expectations) runs
 * server-side in test_audit.py via GET /api/tests/<id>/audit — this file is
 * purely presentation + a shared SVG phasor-diagram renderer.
 */

let _auditData = null;   // last-loaded /api/tests/<id>/audit response
let _auditTestId = null;
let _auditTab = "results";

const _AUDIT_PASS = 5;   // % — under this is a clean pass
const _AUDIT_WARN = 10;  // % — under this is a caution; at/above is a fail

function _auditGrade(pct) {
  if (pct == null || Number.isNaN(pct)) return { label: "—", color: "#444" };
  if (pct < _AUDIT_PASS) return { label: pct.toFixed(1) + "%", color: "#0f0" };
  if (pct < _AUDIT_WARN) return { label: pct.toFixed(1) + "%", color: "#d8a24a" };
  return { label: pct.toFixed(1) + "%", color: "#c66" };
}

function _auEsc(s) {
  return String(s == null ? "" : s).replace(/[&<>"]/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;",
  }[c]));
}
function _auFmtEpoch(e) { return e ? new Date(e * 1000).toLocaleString() : "—"; }
function _auAng(a) { return a == null ? "—" : a.toFixed(1) + "°"; }
function _auMag(m) { return m == null ? "—" : (Math.round(m * 1000) / 1000).toString(); }

// ── Entry point ────────────────────────────────────────────────────────────────

function showTestAudit(testId) {
  const existing = document.getElementById("audit-overlay");
  if (existing) existing.remove();

  const overlay = document.createElement("div");
  overlay.id = "audit-overlay";
  overlay.style.cssText =
    "position:fixed; inset:0; background:rgba(0,0,0,0.85); z-index:11400; " +
    "display:flex; align-items:center; justify-content:center; font-family:'Consolas','Courier New',monospace;";
  overlay.addEventListener("mousedown", e => { if (e.target === overlay) overlay.remove(); });

  const panel = document.createElement("div");
  panel.style.cssText =
    "background:#0c0c0c; border:1px solid #0f0; width:94vw; max-width:1180px; height:88vh; " +
    "display:flex; flex-direction:column; color:#ccc;";
  overlay.appendChild(panel);
  document.body.appendChild(overlay);

  panel.innerHTML = `
    <div style="display:flex; justify-content:space-between; align-items:center;
                border-bottom:1px solid #1a1a1a; padding:10px 16px; flex-shrink:0;">
      <span style="color:#0f0; letter-spacing:2px; font-size:11px;" id="audit-title">🔍 AUDIT</span>
      <span id="audit-close" style="cursor:pointer; color:#666; font-size:14px;">[X]</span>
    </div>
    <div id="audit-summary" style="flex-shrink:0;"></div>
    <div id="audit-tabbar" style="display:flex; border-bottom:1px solid #1a1a1a; flex-shrink:0;"></div>
    <div id="audit-body" style="flex:1; overflow-y:auto; padding:14px 16px;">
      <div style="color:#555; padding:20px; text-align:center;">Loading…</div>
    </div>`;
  document.getElementById("audit-close").onclick = () => overlay.remove();

  _auditTestId = testId;
  _auditTab = "results";
  fetch("/api/tests/" + encodeURIComponent(testId) + "/audit")
    .then(r => r.json())
    .then(data => {
      if (data.error) {
        document.getElementById("audit-body").innerHTML =
          '<div style="color:#c66; padding:20px;">' + _auEsc(data.error) + "</div>";
        return;
      }
      _auditData = data;
      document.getElementById("audit-title").textContent =
        "🔍 AUDIT — " + (data.test && data.test.name ? data.test.name : testId);
      _auditRenderSummary();
      _auditRenderTabs();
      _auditRenderTab();
    })
    .catch(() => {
      document.getElementById("audit-body").innerHTML =
        '<div style="color:#c66; padding:20px;">Failed to load audit data.</div>';
    });
}
window.showTestAudit = showTestAudit;

// ── Summary strip + tabs ────────────────────────────────────────────────────────

function _auditAllResiduals() {
  const out = [];
  Object.entries(_auditData.devices).forEach(([deviceId, dev]) => {
    Object.entries(dev.sessions).forEach(([sid, sess]) => {
      ["current", "voltage"].forEach(fam => {
        const r = sess.residual[fam];
        if (r) out.push({ deviceId, sessionId: sid, family: fam, ...r, sessMeta: sess });
      });
    });
  });
  return out;
}

function _auditRenderSummary() {
  const residuals = _auditAllResiduals();
  const chain = _auditData.chain_checks || [];
  const nSessions = _auditData.sessions.length;
  const nDevices = Object.keys(_auditData.devices).length;

  const gradeCount = (items, pctFn) => {
    let pass = 0, warn = 0, fail = 0;
    items.forEach(it => {
      const p = pctFn(it);
      if (p == null) return;
      if (p < _AUDIT_PASS) pass++; else if (p < _AUDIT_WARN) warn++; else fail++;
    });
    return { pass, warn, fail };
  };
  const rg = gradeCount(residuals.filter(r => r.diff_pct != null || r.computed_pct != null),
    r => (r.diff_pct != null ? r.diff_pct : r.computed_pct));
  const cg = gradeCount(chain, c => c.mag_diff_pct);

  const chip = (n, color, label) =>
    `<span style="color:${color};">${n}</span> <span style="color:#555;">${label}</span>`;

  document.getElementById("audit-summary").innerHTML = `
    <div style="display:flex; gap:22px; flex-wrap:wrap; padding:10px 16px;
                background:#080808; border-bottom:1px solid #1a1a1a; font-size:10px;">
      <span>${nSessions} session${nSessions !== 1 ? "s" : ""}</span>
      <span>${nDevices} device${nDevices !== 1 ? "s" : ""} measured</span>
      <span>neutral checks: ${chip(rg.pass, "#0f0", "ok")} · ${chip(rg.warn, "#d8a24a", "caution")} · ${chip(rg.fail, "#c66", "review")}</span>
      <span>chain checks: ${chip(cg.pass, "#0f0", "ok")} · ${chip(cg.warn, "#d8a24a", "caution")} · ${chip(cg.fail, "#c66", "review")}</span>
    </div>`;
}

function _auditRenderTabs() {
  const tabs = [
    ["results", "RESULTS"],
    ["neutrals", "NEUTRALS"],
    ["chain", "CHAIN"],
    ["compare", "COMPARE"],
  ];
  const bar = document.getElementById("audit-tabbar");
  bar.innerHTML = "";
  tabs.forEach(([key, label]) => {
    const active = key === _auditTab;
    const b = document.createElement("button");
    b.textContent = label;
    b.style.cssText =
      "background:" + (active ? "#001a00" : "#050505") + ";border:none;" +
      "border-bottom:2px solid " + (active ? "#0f0" : "transparent") + ";" +
      "color:" + (active ? "#0f0" : "#555") + ";font-family:inherit;font-size:10px;" +
      "padding:8px 18px;cursor:pointer;letter-spacing:1px;";
    b.onclick = () => { _auditTab = key; _auditRenderTabs(); _auditRenderTab(); };
    bar.appendChild(b);
  });
}

function _auditRenderTab() {
  const body = document.getElementById("audit-body");
  body.innerHTML = "";
  if (_auditTab === "results") return _auditRenderResults(body);
  if (_auditTab === "neutrals") return _auditRenderNeutrals(body);
  if (_auditTab === "chain") return _auditRenderChain(body);
  if (_auditTab === "compare") return _auditRenderCompare(body);
}

// ── RESULTS tab ──────────────────────────────────────────────────────────────

function _auditRenderResults(body) {
  const rows = [];
  Object.entries(_auditData.devices).forEach(([deviceId, dev]) => {
    Object.entries(dev.sessions).forEach(([sid, sess]) => {
      rows.push({ deviceId, type: dev.type, sid, sess });
    });
  });
  rows.sort((a, b) => (b.sess.epoch || 0) - (a.sess.epoch || 0));

  if (!rows.length) {
    body.innerHTML = '<div class="empty" style="color:#444; padding:20px;">No recorded measurements yet.</div>';
    return;
  }

  body.innerHTML = rows.map(({ deviceId, type, sid, sess }) => {
    const keys = Object.keys(sess.raw).sort();
    const cells = keys.map(k =>
      `<span style="display:inline-block; margin:2px 10px 2px 0; font-size:10px;">
         <span style="color:#555;">${_auEsc(k)}</span>
         <span style="color:#0f0; font-weight:bold;">${_auMag(sess.raw[k])}</span>
       </span>`).join("");
    return `
      <div style="border:1px solid #1a1a1a; border-radius:3px; margin-bottom:10px; padding:10px 12px;">
        <div style="display:flex; justify-content:space-between; align-items:baseline; margin-bottom:6px;">
          <span style="color:#eee; font-size:11px;">${_auEsc(deviceId)}
            <span style="color:#555; font-size:9px;">${_auEsc(type)}</span></span>
          <span style="color:#444; font-size:9px;">${_auEsc(sess.technician || "—")} · ${_auFmtEpoch(sess.epoch)}</span>
        </div>
        <div>${cells}</div>
        <button data-dev="${_auEsc(deviceId)}" data-sid="${_auEsc(sid)}" class="au-diagram-btn"
          style="margin-top:8px; background:none; border:1px solid #222; color:#3af;
                 font-family:inherit; font-size:9px; padding:3px 8px; cursor:pointer; letter-spacing:1px;">
          ◈ PHASOR DIAGRAM
        </button>
      </div>`;
  }).join("");

  body.querySelectorAll(".au-diagram-btn").forEach(b => {
    b.onclick = () => _auditShowDiagramModal([
      { label: b.dataset.dev, deviceId: b.dataset.dev, sessionId: b.dataset.sid, color: "#0f0" },
    ]);
  });
}

// ── NEUTRALS tab ─────────────────────────────────────────────────────────────

function _auditRenderNeutrals(body) {
  const residuals = _auditAllResiduals();
  if (!residuals.length) {
    body.innerHTML = '<div style="color:#444; padding:20px;">No device has all three phases (mag + angle) recorded in one session yet — neutral/residual checks need A, B and C.</div>';
    return;
  }
  residuals.sort((a, b) => (b.sessMeta.epoch || 0) - (a.sessMeta.epoch || 0));

  body.innerHTML = `
    <div style="font-size:9px; color:#555; margin-bottom:10px; line-height:1.6;">
      Residual = the phasor (vector) sum of the three measured phases — what a healthy,
      balanced circuit's neutral current should be near zero. A high percentage of the
      average phase magnitude means either real imbalance or a measurement / wiring error.
      Where a Neutral value was also directly measured, it's compared against the computed one.
    </div>
    <table style="width:100%; border-collapse:collapse; font-size:10px;">
      <thead><tr style="color:#555; font-size:9px; letter-spacing:1px;">
        <th style="text-align:left; padding:5px 8px; border-bottom:1px solid #1a1a1a;">DEVICE</th>
        <th style="text-align:left; padding:5px 8px; border-bottom:1px solid #1a1a1a;">QTY</th>
        <th style="text-align:left; padding:5px 8px; border-bottom:1px solid #1a1a1a;">AVG PHASE</th>
        <th style="text-align:left; padding:5px 8px; border-bottom:1px solid #1a1a1a;">COMPUTED (A+B+C)</th>
        <th style="text-align:left; padding:5px 8px; border-bottom:1px solid #1a1a1a;">MEASURED N</th>
        <th style="text-align:left; padding:5px 8px; border-bottom:1px solid #1a1a1a;">RESULT</th>
        <th style="border-bottom:1px solid #1a1a1a;"></th>
      </tr></thead>
      <tbody>
        ${residuals.map(r => {
          const pct = r.diff_pct != null ? r.diff_pct : r.computed_pct;
          const g = _auditGrade(pct);
          const label = r.diff_pct != null ? "vs. measured" : "phasor sum";
          return `<tr style="border-bottom:1px solid #111;">
            <td style="padding:6px 8px; color:#ccc;">${_auEsc(r.deviceId)}</td>
            <td style="padding:6px 8px; color:#555;">${r.family}</td>
            <td style="padding:6px 8px;">${_auMag(r.avg_phase_mag)}</td>
            <td style="padding:6px 8px;">${_auMag(r.computed_mag)} ∠${_auAng(r.computed_ang)}</td>
            <td style="padding:6px 8px;">${r.measured_mag != null ? _auMag(r.measured_mag) + " ∠" + _auAng(r.measured_ang) : "—"}</td>
            <td style="padding:6px 8px; color:${g.color}; font-weight:bold;">${g.label} <span style="color:#444; font-weight:normal;">${label}</span></td>
            <td style="padding:6px 8px;">
              <button data-dev="${_auEsc(r.deviceId)}" data-sid="${_auEsc(r.sessionId)}" class="au-diagram-btn"
                style="background:none; border:1px solid #222; color:#3af; font-family:inherit;
                       font-size:9px; padding:3px 8px; cursor:pointer;">◈</button>
            </td>
          </tr>`;
        }).join("")}
      </tbody>
    </table>`;

  body.querySelectorAll(".au-diagram-btn").forEach(b => {
    b.onclick = () => _auditShowDiagramModal([
      { label: b.dataset.dev, deviceId: b.dataset.dev, sessionId: b.dataset.sid, color: "#0f0" },
    ]);
  });
}

// ── CHAIN tab ────────────────────────────────────────────────────────────────

function _auditRenderChain(body) {
  const checks = (_auditData.chain_checks || []).slice()
    .sort((a, b) => (a.mag_diff_pct == null) - (b.mag_diff_pct == null) || (b.mag_diff_pct || 0) - (a.mag_diff_pct || 0));

  if (!checks.length) {
    body.innerHTML = '<div style="color:#444; padding:20px;">No secondary chain (CT/VT → CTTB/Relay/Meter) has recordings on both ends yet.</div>';
    return;
  }

  body.innerHTML = `
    <div style="font-size:9px; color:#555; margin-bottom:10px; line-height:1.6;">
      For each device fed by others through the secondary wiring, the expected value is the
      polarity-weighted vector sum of what its inputs recorded in the same session — exactly
      the summation / differential math the relay itself performs. A mismatch usually means a
      CT ratio, polarity, or connection issue somewhere in the chain.
    </div>
    <table style="width:100%; border-collapse:collapse; font-size:10px;">
      <thead><tr style="color:#555; font-size:9px; letter-spacing:1px;">
        <th style="text-align:left; padding:5px 8px; border-bottom:1px solid #1a1a1a;">DEVICE</th>
        <th style="text-align:left; padding:5px 8px; border-bottom:1px solid #1a1a1a;">FED BY</th>
        <th style="text-align:left; padding:5px 8px; border-bottom:1px solid #1a1a1a;">PHASE</th>
        <th style="text-align:left; padding:5px 8px; border-bottom:1px solid #1a1a1a;">EXPECTED</th>
        <th style="text-align:left; padding:5px 8px; border-bottom:1px solid #1a1a1a;">ACTUAL</th>
        <th style="text-align:left; padding:5px 8px; border-bottom:1px solid #1a1a1a;">Δ MAG</th>
        <th style="text-align:left; padding:5px 8px; border-bottom:1px solid #1a1a1a;">Δ ANG</th>
        <th style="border-bottom:1px solid #1a1a1a;"></th>
      </tr></thead>
      <tbody>
        ${checks.map((c, i) => {
          const g = _auditGrade(c.mag_diff_pct);
          const fed = c.upstream_ids.join(" + ") + (c.missing_upstream.length
            ? ` <span style="color:#644;">(missing ${c.missing_upstream.join(", ")})</span>` : "");
          return `<tr style="border-bottom:1px solid #111;">
            <td style="padding:6px 8px; color:#ccc;">${_auEsc(c.downstream_id)}
              <span style="color:#555; font-size:9px;">${_auEsc(c.downstream_type)}</span></td>
            <td style="padding:6px 8px; color:#888;">${fed}</td>
            <td style="padding:6px 8px;">${c.phase} <span style="color:#555;">${c.family}</span></td>
            <td style="padding:6px 8px;">${_auMag(c.expected_mag)} ∠${_auAng(c.expected_ang)}</td>
            <td style="padding:6px 8px;">${_auMag(c.actual_mag)} ∠${_auAng(c.actual_ang)}</td>
            <td style="padding:6px 8px; color:${g.color}; font-weight:bold;">${g.label}</td>
            <td style="padding:6px 8px; color:#888;">${c.ang_diff_deg != null ? c.ang_diff_deg.toFixed(1) + "°" : "—"}</td>
            <td style="padding:6px 8px;">
              <button data-i="${i}" class="au-chain-diagram-btn"
                style="background:none; border:1px solid #222; color:#3af; font-family:inherit;
                       font-size:9px; padding:3px 8px; cursor:pointer;">◈</button>
            </td>
          </tr>`;
        }).join("")}
      </tbody>
    </table>`;

  body.querySelectorAll(".au-chain-diagram-btn").forEach(b => {
    b.onclick = () => {
      const c = checks[Number(b.dataset.i)];
      const sets = [
        { label: c.upstream_ids.join("+") + " (expected)", phasorsOverride: { [c.phase]: { mag: c.expected_mag, ang: c.expected_ang } }, color: "#3af" },
        { label: c.downstream_id + " (actual)", deviceId: c.downstream_id, sessionId: c.session_id, family: c.family, color: "#0f0" },
      ];
      _auditShowDiagramModal(sets);
    };
  });
}

// ── COMPARE tab ──────────────────────────────────────────────────────────────

function _auditFlatRows() {
  const rows = [];
  Object.entries(_auditData.devices).forEach(([deviceId, dev]) => {
    Object.entries(dev.sessions).forEach(([sid, sess]) => {
      rows.push({
        key: deviceId + "|" + sid,
        deviceId, sid, sess,
        display: deviceId + " — " + (sess.technician || "?") + " — " + _auFmtEpoch(sess.epoch),
      });
    });
  });
  rows.sort((a, b) => (b.sess.epoch || 0) - (a.sess.epoch || 0));
  return rows;
}

function _auditRenderCompare(body) {
  const rows = _auditFlatRows();
  if (rows.length < 1) {
    body.innerHTML = '<div style="color:#444; padding:20px;">No recorded measurements to compare yet.</div>';
    return;
  }
  const opts = rows.map(r => `<option value="${_auEsc(r.key)}">${_auEsc(r.display)}</option>`).join("");

  body.innerHTML = `
    <div style="font-size:9px; color:#555; margin-bottom:12px; line-height:1.6;">
      Compare any two recorded sets — the same device across two sessions (drift over time),
      or two different devices that should agree (e.g. a CT and the relay it feeds).
    </div>
    <div style="display:flex; gap:14px; align-items:flex-end; margin-bottom:14px; flex-wrap:wrap;">
      <div><label style="font-size:9px; color:#888; display:block; margin-bottom:3px;">SET A</label>
        <select id="au-cmp-a" style="background:#111; border:1px solid #333; color:#0f0; font-family:inherit; font-size:10px; padding:5px; min-width:260px;">${opts}</select></div>
      <div><label style="font-size:9px; color:#888; display:block; margin-bottom:3px;">SET B</label>
        <select id="au-cmp-b" style="background:#111; border:1px solid #333; color:#3af; font-family:inherit; font-size:10px; padding:5px; min-width:260px;">${opts}</select></div>
      <button id="au-cmp-go" style="background:#001a00; border:1px solid #0f0; color:#0f0; font-family:inherit;
              font-size:10px; padding:6px 16px; cursor:pointer; letter-spacing:1px;">COMPARE</button>
    </div>
    <div id="au-cmp-result"></div>`;

  const selB = body.querySelector("#au-cmp-b");
  if (rows.length > 1) selB.selectedIndex = 1;

  document.getElementById("au-cmp-go").onclick = () => {
    const a = rows.find(r => r.key === body.querySelector("#au-cmp-a").value);
    const b = rows.find(r => r.key === body.querySelector("#au-cmp-b").value);
    _auditRenderCompareResult(body.querySelector("#au-cmp-result"), a, b);
  };
  // auto-run once so the tool isn't an empty shell on first open
  document.getElementById("au-cmp-go").click();
}

function _auditRenderCompareResult(el, a, b) {
  if (!a || !b) { el.innerHTML = ""; return; }
  const keys = Array.from(new Set([...Object.keys(a.sess.raw), ...Object.keys(b.sess.raw)])).sort();
  const rows = keys.map(k => {
    const va = a.sess.raw[k], vb = b.sess.raw[k];
    let delta = "—", pct = null;
    if (va != null && vb != null) {
      delta = (vb - va).toFixed(3);
      const base = Math.max(Math.abs(va), 1e-9);
      pct = Math.abs(vb - va) / base * 100;
    }
    const g = pct != null ? _auditGrade(pct) : { label: "—", color: "#444" };
    return `<tr style="border-bottom:1px solid #111;">
      <td style="padding:5px 8px; color:#888;">${_auEsc(k)}</td>
      <td style="padding:5px 8px; color:#0f0;">${_auMag(va)}</td>
      <td style="padding:5px 8px; color:#3af;">${_auMag(vb)}</td>
      <td style="padding:5px 8px; color:#aaa;">${delta}</td>
      <td style="padding:5px 8px; color:${g.color}; font-weight:bold;">${g.label}</td>
    </tr>`;
  }).join("");

  el.innerHTML = `
    <table style="width:100%; border-collapse:collapse; font-size:10px; margin-bottom:14px;">
      <thead><tr style="color:#555; font-size:9px; letter-spacing:1px;">
        <th style="text-align:left; padding:5px 8px; border-bottom:1px solid #1a1a1a;">KEY</th>
        <th style="text-align:left; padding:5px 8px; border-bottom:1px solid #1a1a1a; color:#0f0;">A: ${_auEsc(a.deviceId)}</th>
        <th style="text-align:left; padding:5px 8px; border-bottom:1px solid #1a1a1a; color:#3af;">B: ${_auEsc(b.deviceId)}</th>
        <th style="text-align:left; padding:5px 8px; border-bottom:1px solid #1a1a1a;">Δ</th>
        <th style="text-align:left; padding:5px 8px; border-bottom:1px solid #1a1a1a;">% OF A</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <div id="au-cmp-diagram"></div>`;

  _auditRenderDiagram(document.getElementById("au-cmp-diagram"), [
    { label: "A: " + a.deviceId, deviceId: a.deviceId, sessionId: a.sid, color: "#0f0" },
    { label: "B: " + b.deviceId, deviceId: b.deviceId, sessionId: b.sid, color: "#3af" },
  ]);
}

// ── Shared phasor diagram ────────────────────────────────────────────────────

function _auditResolveSet(set) {
  // A set either names a device+session to pull phasors from, carries an
  // explicit single-phase override (for a chain check's "expected" side), or
  // is already a raw {A:{mag,ang},...} map.
  if (set.phasorsOverride) return set.phasorsOverride;
  if (set.phasors) return set.phasors;
  const dev = _auditData.devices[set.deviceId];
  const sess = dev && dev.sessions[set.sessionId];
  if (!sess) return {};
  const family = set.family || (Object.keys(sess.phasors.current).length ? "current" : "voltage");
  return sess.phasors[family] || {};
}

function _auditShowDiagramModal(sets) {
  const existing = document.getElementById("audit-diagram-overlay");
  if (existing) existing.remove();
  const overlay = document.createElement("div");
  overlay.id = "audit-diagram-overlay";
  overlay.style.cssText =
    "position:fixed; inset:0; background:rgba(0,0,0,0.85); z-index:11500; " +
    "display:flex; align-items:center; justify-content:center;";
  overlay.addEventListener("mousedown", e => { if (e.target === overlay) overlay.remove(); });
  const box = document.createElement("div");
  box.style.cssText = "background:#0c0c0c; border:1px solid #3af; padding:16px;";
  overlay.appendChild(box);
  document.body.appendChild(overlay);
  _auditRenderDiagram(box, sets);
}

/** Draw one or more phasor sets ({A,B,C,N} -> {mag,ang}) overlaid on one polar chart. */
function _auditRenderDiagram(container, sets) {
  const resolved = sets.map(s => ({ label: s.label, color: s.color || "#0f0", phasors: _auditResolveSet(s) }));
  let maxMag = 0;
  resolved.forEach(s => Object.values(s.phasors).forEach(p => { if (p && p.mag > maxMag) maxMag = p.mag; }));
  if (maxMag <= 0) maxMag = 1;

  const size = 300, cx = size / 2, cy = size / 2, R = size / 2 - 30;
  const toXY = (mag, ang) => {
    const rad = (ang * Math.PI) / 180;
    const r = (mag / maxMag) * R;
    return [cx + r * Math.cos(rad), cy - r * Math.sin(rad)];
  };

  let svg = `<svg width="${size}" height="${size}" style="background:#050505;">`;
  // rings
  [0.25, 0.5, 0.75, 1].forEach(f => {
    svg += `<circle cx="${cx}" cy="${cy}" r="${R * f}" fill="none" stroke="#1a1a1a" stroke-width="1"/>`;
  });
  // axes
  svg += `<line x1="${cx - R}" y1="${cy}" x2="${cx + R}" y2="${cy}" stroke="#222"/>`;
  svg += `<line x1="${cx}" y1="${cy - R}" x2="${cx}" y2="${cy + R}" stroke="#222"/>`;

  const phaseColor = { A: "#f55", B: "#5f5", C: "#59f", N: "#fa0" };
  resolved.forEach(set => {
    Object.entries(set.phasors).forEach(([phase, p]) => {
      if (!p || p.mag == null || p.ang == null) return;
      const [x, y] = toXY(p.mag, p.ang);
      svg += `<line x1="${cx}" y1="${cy}" x2="${x.toFixed(1)}" y2="${y.toFixed(1)}"
                stroke="${set.color}" stroke-width="2" marker-end="url(#au-arrow)"/>`;
      svg += `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="3" fill="${phaseColor[phase] || set.color}"/>`;
      svg += `<text x="${x.toFixed(1)}" y="${(y - 6).toFixed(1)}" fill="${phaseColor[phase] || set.color}"
                font-size="9" font-family="Consolas,monospace" text-anchor="middle">${phase}</text>`;
    });
  });

  svg += `<defs><marker id="au-arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
            <path d="M0,0 L0,6 L7,3 z" fill="#888"/></marker></defs>`;
  svg += "</svg>";

  const legend = resolved.map(s =>
    `<div style="display:flex; align-items:center; gap:6px; font-size:9px; color:#aaa; margin-bottom:3px;">
       <span style="width:10px; height:2px; background:${s.color}; display:inline-block;"></span>
       ${_auEsc(s.label)}
     </div>`).join("");

  container.innerHTML = `
    <div style="display:flex; gap:14px; align-items:flex-start;">
      <div>${svg}</div>
      <div style="min-width:140px;">
        <div style="font-size:9px; color:#555; letter-spacing:1px; margin-bottom:6px;">PHASOR DIAGRAM</div>
        ${legend}
        <div style="font-size:8px; color:#444; margin-top:8px;">rings: 25/50/75/100% of ${_auMag(maxMag)}</div>
      </div>
    </div>`;
}
