"use strict";

/**
 * SCADA Pro — Test Manager
 * Handles the TESTS modal: listing, creating, viewing detail, and managing drawings.
 */

const TEST_STATUSES = ["IN PROGRESS", "COMPLETE", "ARCHIVED"];

const STATUS_COLOR = {
    "IN PROGRESS": "#fa0",
    "COMPLETE":    "#0f0",
    "ARCHIVED":    "#555",
};

// ── Generate a load test from the secondary devices ──────────────────────────
// Opened from the "⚡ GENERATE LOAD TEST" button on any secondary device window.
// Every secondary device is listed; the ones with a real test point (test
// blocks, relays, meters) are ticked by default — raw CT/VT windings are not,
// since you don't land test leads on them. The list stays fully editable.
const _TEST_POINT_TYPES = new Set(["CTTB", "FTBlock", "IsoBlock", "Relay", "Meter"]);

function _generateLoadTest(seedDeviceId) {
    const nodes = (currentData && currentData.nodes) || [];
    const secTypes = (typeof _SECONDARY_DEV !== "undefined")
        ? _SECONDARY_DEV
        : new Set(["CurrentTransformer", "VoltageTransformer", "DualWindingVT", "CTTB",
                   "FTBlock", "IsoBlock", "Relay", "Meter"]);
    const secDevices = nodes.filter(n => secTypes.has(n.type));
    if (secDevices.length === 0) { alert("No secondary devices in this topology."); return; }

    const site = (currentData && currentData.site) || {};
    const station = site.station || site.site_name || "";
    const today = new Date().toISOString().slice(0, 10);
    const defaultName = "Load Test" + (station ? " — " + station : "") + " — " + today;
    const tech = (typeof _technicianName !== "undefined" && _technicianName) || window._technicianName || "";

    const primHint = (n) => {
        try {
            if (typeof _tracePrimaryPaths === "function") {
                const prims = [...new Set(_tracePrimaryPaths(n).map(x => x.primId).filter(Boolean))];
                return prims.length ? "  → " + prims.join(", ") : "";
            }
        } catch (e) { /* ignore */ }
        return "";
    };

    const existing = document.getElementById("_glt-overlay");
    if (existing) existing.remove();
    const overlay = document.createElement("div");
    overlay.id = "_glt-overlay";
    overlay.style.cssText =
        "position:fixed;inset:0;background:rgba(0,0,0,0.85);z-index:12500;" +
        "display:flex;align-items:center;justify-content:center;font-family:'Consolas','Courier New',monospace;";
    overlay.addEventListener("click", e => { if (e.target === overlay) overlay.remove(); });
    document.body.appendChild(overlay);

    const box = document.createElement("div");
    box.style.cssText =
        "background:#0b0b10;border:1px solid #1f6b47;width:min(92vw,560px);max-height:88vh;display:flex;flex-direction:column;";
    overlay.appendChild(box);

    const rows = secDevices.map(n => {
        const isTP = _TEST_POINT_TYPES.has(n.type);
        return `<label style="display:flex;align-items:center;gap:8px;padding:3px 0;font-size:10px;color:${isTP ? "#cdd" : "#788"};cursor:pointer;">` +
            `<input type="checkbox" class="_glt-dev" value="${_esc(n.id)}"${isTP ? " checked" : ""}>` +
            `<span style="flex:1;min-width:0;">${_esc(n.id)} <span style="color:#556;">[${_esc(n.type)}]</span>` +
            `<span style="color:#7a8;">${_esc(primHint(n))}</span>` +
            (isTP ? "" : ' <span style="color:#655;">· no test point</span>') + `</span></label>`;
    }).join("");
    const nTP = secDevices.filter(n => _TEST_POINT_TYPES.has(n.type)).length;

    box.innerHTML =
        `<div style="padding:12px 16px;background:#0d160d;border-bottom:1px solid #0a2a0a;color:#3fdc8f;font-size:11px;letter-spacing:1px;display:flex;justify-content:space-between;">` +
        `<span>⚡ GENERATE LOAD TEST</span><span id="_glt-close" style="cursor:pointer;color:#556;">✕</span></div>` +
        `<div style="padding:12px 16px;display:flex;flex-direction:column;gap:6px;overflow-y:auto;">` +
        `<label style="font-size:8px;color:#778;letter-spacing:1px;">TEST NAME</label>` +
        `<input id="_glt-name" type="text" value="${_esc(defaultName)}" ` +
        `style="background:#111;border:1px solid #333;color:#eee;padding:6px 8px;font-family:inherit;font-size:11px;">` +
        `<div style="display:flex;justify-content:space-between;align-items:center;margin-top:6px;">` +
        `<span style="font-size:8px;color:#778;letter-spacing:1px;">CAPTURE POINTS — ${nTP} test point(s) of ${secDevices.length} secondary</span>` +
        `<span><button id="_glt-tp" style="background:none;border:1px solid #333;color:#889;font-size:8px;padding:2px 6px;cursor:pointer;">TEST PTS</button> ` +
        `<button id="_glt-all" style="background:none;border:1px solid #333;color:#889;font-size:8px;padding:2px 6px;cursor:pointer;">ALL</button> ` +
        `<button id="_glt-none" style="background:none;border:1px solid #333;color:#889;font-size:8px;padding:2px 6px;cursor:pointer;">NONE</button></span></div>` +
        `<div style="border:1px solid #1a1a1a;padding:6px 10px;max-height:40vh;overflow-y:auto;">${rows}</div></div>` +
        `<div style="padding:12px 16px;border-top:1px solid #1a1a1a;display:flex;gap:8px;">` +
        `<button id="_glt-create" style="flex:1;background:#001a00;border:1px solid #0f0;color:#0f0;font-family:inherit;font-size:10px;padding:8px;cursor:pointer;letter-spacing:1px;">CREATE LOAD TEST</button>` +
        `<button id="_glt-cancel" style="background:#0a0a0a;border:1px solid #333;color:#666;font-family:inherit;font-size:10px;padding:8px 16px;cursor:pointer;">CANCEL</button></div>`;

    const close = () => overlay.remove();
    box.querySelector("#_glt-close").onclick = close;
    box.querySelector("#_glt-cancel").onclick = close;
    const setAll = v => box.querySelectorAll("._glt-dev").forEach(c => (c.checked = v));
    box.querySelector("#_glt-all").onclick = () => setAll(true);
    box.querySelector("#_glt-none").onclick = () => setAll(false);
    box.querySelector("#_glt-tp").onclick = () => box.querySelectorAll("._glt-dev").forEach((c, i) => {
        c.checked = _TEST_POINT_TYPES.has(secDevices[i].type);
    });

    box.querySelector("#_glt-create").onclick = () => {
        const name = (box.querySelector("#_glt-name").value || "").trim();
        if (!name) { box.querySelector("#_glt-name").style.borderColor = "#f00"; return; }
        const picked = [...box.querySelectorAll("._glt-dev:checked")].map(c => c.value);
        if (picked.length === 0) { alert("Pick at least one capture point."); return; }
        const btn = box.querySelector("#_glt-create");
        btn.textContent = "CREATING…"; btn.disabled = true;
        createTest(name, "Auto-generated load test — secondary devices", tech).then(resp => {
            if (resp.error) { alert("Error: " + resp.error); btn.disabled = false; btn.textContent = "CREATE LOAD TEST"; return; }
            updateTestCapturePoints(resp.test_id, picked)
                .then(() => { close(); showTestsModal(); _testsRenderDetail(resp.test_id); })
                .catch(() => { close(); showTestsModal(); _testsRenderDetail(resp.test_id); });
        }).catch(() => { alert("Network error creating test."); btn.disabled = false; btn.textContent = "CREATE LOAD TEST"; });
    };
}

function showTestsModal() {
    if (!getActiveSiteInfo()) {
        alert("No site loaded. Load a site first.");
        return;
    }
    document.getElementById("tests-modal").style.display = "flex";
    _testsRenderList();
}

function hideTestsModal() {
    document.getElementById("tests-modal").style.display = "none";
}

// ── List view ─────────────────────────────────────────────────────────────────

function _testsRenderList() {
    const header = document.getElementById("tests-modal-header");
    const body   = document.getElementById("tests-modal-body");
    const footer = document.getElementById("tests-modal-footer");

    header.textContent = "TESTS";
    footer.style.flexDirection = "row";
    footer.innerHTML = `
        <button onclick="_testsRenderCreate()"
            style="background:#001a00; border:1px solid #0f0; color:#0f0;
                   font-family:inherit; font-size:10px; padding:6px 14px; cursor:pointer; letter-spacing:1px;">
            + NEW TEST
        </button>
        <div style="flex:1;"></div>
        <button onclick="_testsShowShared()"
            style="background:#04121c; border:1px solid #3fdc8f; color:#3fdc8f;
                   font-family:inherit; font-size:10px; padding:6px 14px; cursor:pointer; letter-spacing:1px;">
            ☁ SHARED TESTS
        </button>`;

    body.innerHTML = '<div style="color:#555; padding:14px; font-size:10px;">Loading...</div>';

    fetchTests().then(({ tests }) => {
        if (!tests || tests.length === 0) {
            body.innerHTML = `
                <div style="color:#444; padding:24px; text-align:center; font-size:11px;">
                    NO TESTS FOUND<br>
                    <span style="color:#333; font-size:10px;">Create a test to begin logging measurements.</span>
                </div>`;
            return;
        }

        let html = '';
        tests.forEach(t => {
            const date = new Date(t.epoch * 1000).toLocaleDateString();
            const sc   = STATUS_COLOR[t.status] || "#888";
            html += `
                <div class="test-row" onclick="_testsRenderDetail('${t.id}')">
                    <div style="display:flex; justify-content:space-between; align-items:baseline; margin-bottom:4px; gap:6px;">
                        <span class="test-row-name">${_esc(t.name)}</span>
                        <span style="display:flex; gap:6px; white-space:nowrap;">
                        ${t.origin && t.origin.indexOf("hub:") === 0
                            ? `<span style="font-size:9px; border:1px solid #3fdc8f; color:#3fdc8f;
                                     padding:1px 6px; letter-spacing:1px;">☁ SHARED</span>` : ""}
                        <span style="font-size:9px; border:1px solid ${sc}; color:${sc};
                                     padding:1px 6px; letter-spacing:1px;">${t.status}</span>
                        </span>
                    </div>
                    <div class="test-row-meta">
                        ${t.description ? `<span style="color:#777;">${_esc(t.description)}</span> &nbsp;&bull;&nbsp; ` : ''}
                        <span>${t.drawing_count} drawing${t.drawing_count !== 1 ? 's' : ''}</span>
                        &nbsp;&bull;&nbsp;
                        <span>${t.session_count} session${t.session_count !== 1 ? 's' : ''}</span>
                        &nbsp;&bull;&nbsp;
                        <span>${t.created_by ? 'by ' + _esc(t.created_by) + ' &nbsp;&bull;&nbsp; ' : ''}${date}</span>
                    </div>
                </div>`;
        });
        body.innerHTML = html;
    }).catch(() => {
        body.innerHTML = '<div style="color:#f44; padding:14px;">Failed to load tests.</div>';
    });
}

// ── Create view ───────────────────────────────────────────────────────────────

function _testsRenderCreate() {
    const header = document.getElementById("tests-modal-header");
    const body   = document.getElementById("tests-modal-body");
    const footer = document.getElementById("tests-modal-footer");

    header.textContent = "NEW TEST";
    body.innerHTML = `
        <div style="padding:16px; display:flex; flex-direction:column; gap:12px;">
            <div style="display:flex; flex-direction:column; gap:4px;">
                <label style="font-size:10px; color:#888;">TEST NAME <span style="color:#f00;">*</span></label>
                <input id="new-test-name" type="text"
                    placeholder="e.g. 500kV Line Protection Analog Proof — ALZ to XYZ"
                    style="background:#111; border:1px solid #333; color:#eee; padding:8px 10px;
                           font-family:inherit; font-size:12px; width:100%; box-sizing:border-box;"
                    onkeydown="if(event.key==='Enter') _testsSubmitCreate()" />
            </div>
            <div style="display:flex; flex-direction:column; gap:4px;">
                <label style="font-size:10px; color:#888;">DESCRIPTION</label>
                <textarea id="new-test-desc" rows="3"
                    placeholder="Objective, scope, or notes..."
                    style="background:#111; border:1px solid #333; color:#eee; padding:8px 10px;
                           font-family:inherit; font-size:11px; width:100%; box-sizing:border-box;
                           resize:vertical;"></textarea>
            </div>
            <div style="display:flex; flex-direction:column; gap:4px;">
                <label style="font-size:10px; color:#888;">CREATED BY</label>
                <input id="new-test-by" type="text"
                    placeholder="Technician name"
                    value="${_esc(window._technicianName || '')}"
                    style="background:#111; border:1px solid #333; color:#eee; padding:8px 10px;
                           font-family:inherit; font-size:11px; width:100%; box-sizing:border-box;" />
            </div>
        </div>`;

    footer.style.flexDirection = "row";
    footer.innerHTML = `
        <button onclick="_testsRenderList()"
            style="background:#0a0a0a; border:1px solid #333; color:#666;
                   font-family:inherit; font-size:10px; padding:6px 12px; cursor:pointer;">
            ← BACK
        </button>
        <div style="flex:1;"></div>
        <button onclick="_testsSubmitCreate()"
            style="background:#001a00; border:1px solid #0f0; color:#0f0;
                   font-family:inherit; font-size:10px; padding:6px 16px; cursor:pointer; letter-spacing:1px;">
            CREATE TEST
        </button>`;

    document.getElementById("new-test-name").focus();
}

function _testsSubmitCreate() {
    const name = (document.getElementById("new-test-name").value || "").trim();
    const desc = (document.getElementById("new-test-desc").value || "").trim();
    const by   = (document.getElementById("new-test-by").value   || "").trim();

    if (!name) {
        document.getElementById("new-test-name").style.borderColor = "#f00";
        return;
    }

    createTest(name, desc, by).then(resp => {
        if (resp.error) { alert("Error: " + resp.error); return; }
        _testsRenderDetail(resp.test_id);
    }).catch(() => alert("Network error creating test."));
}

// ── Detail view ───────────────────────────────────────────────────────────────

function _testsRenderDetail(testId) {
    const header = document.getElementById("tests-modal-header");
    const body   = document.getElementById("tests-modal-body");
    const footer = document.getElementById("tests-modal-footer");

    body.innerHTML = '<div style="color:#555; padding:14px; font-size:10px;">Loading...</div>';
    header.textContent = "TEST DETAIL";
    footer.innerHTML = '';

    fetchTestDetail(testId).then(({ test, drawings, sessions }) => {
        if (!test) { body.innerHTML = '<div style="color:#f44; padding:14px;">Test not found.</div>'; return; }

        header.textContent = _esc(test.name);
        const sc = STATUS_COLOR[test.status] || "#888";
        const date = new Date(test.epoch * 1000).toLocaleDateString();

        // ── Meta strip ─────────────────────────────────────────────────────
        let html = `
            <div style="padding:12px 16px; background:#080808; border-bottom:1px solid #1a1a1a;
                        display:flex; gap:16px; flex-wrap:wrap; align-items:center;">
                <span style="font-size:9px; border:1px solid ${sc}; color:${sc}; padding:2px 8px; letter-spacing:1px;">${test.status}</span>
                ${test.created_by ? `<span style="font-size:10px; color:#666;">by ${_esc(test.created_by)}</span>` : ''}
                <span style="font-size:10px; color:#444;">${date}</span>
                <div style="flex:1;"></div>
                <select onchange="setTestStatus('${testId}', this.value).then(() => _testsRenderDetail('${testId}'))"
                    style="background:#111; border:1px solid #333; color:#aaa; font-family:inherit;
                           font-size:10px; padding:3px 6px; cursor:pointer;">
                    ${TEST_STATUSES.map(s => `<option value="${s}" ${s === test.status ? 'selected' : ''}>${s}</option>`).join('')}
                </select>
            </div>`;

        if (test.description) {
            html += `<div style="padding:10px 16px; font-size:11px; color:#777; border-bottom:1px solid #111;">
                ${_esc(test.description)}</div>`;
        }

        // ── Drawings section ────────────────────────────────────────────────
        html += `
            <div style="padding:10px 16px 6px; font-size:9px; color:#555; letter-spacing:1px;
                        border-bottom:1px solid #111; display:flex; justify-content:space-between; align-items:center;">
                <span>DRAWINGS &amp; REFERENCES</span>
                <button onclick="_testsShowAddDrawing('${testId}')"
                    style="background:none; border:1px solid #333; color:#666; font-family:inherit;
                           font-size:9px; padding:2px 8px; cursor:pointer; letter-spacing:1px;">
                    + ADD
                </button>
            </div>`;

        if (drawings.length === 0) {
            html += `<div style="padding:10px 16px; font-size:10px; color:#333;">No drawings logged yet.</div>`;
        } else {
            html += `<table style="width:100%; border-collapse:collapse; font-size:10px;">
                <thead>
                    <tr style="background:#0c0c0c; color:#444; font-size:9px; letter-spacing:1px;">
                        <th style="padding:5px 16px; text-align:left; border-bottom:1px solid #1a1a1a;">DRAWING / TITLE</th>
                        <th style="padding:5px 8px; text-align:left; border-bottom:1px solid #1a1a1a; width:70px;">REV</th>
                        <th style="padding:5px 8px; text-align:left; border-bottom:1px solid #1a1a1a;">URL / REFERENCE</th>
                        <th style="padding:5px 8px; border-bottom:1px solid #1a1a1a; width:30px;"></th>
                    </tr>
                </thead><tbody>`;
            drawings.forEach(d => {
                const urlCell = d.url
                    ? `<a href="${_esc(d.url)}" target="_blank" style="color:#3af; text-decoration:none;"
                          title="${_esc(d.url)}">${_truncate(d.url, 40)}</a>`
                    : `<span style="color:#333;">—</span>`;
                html += `
                    <tr style="border-bottom:1px solid #0d0d0d;">
                        <td style="padding:6px 16px; color:#ccc;">
                            ${_esc(d.title)}
                            ${d.notes ? `<div style="font-size:9px; color:#555; margin-top:2px;">${_esc(d.notes)}</div>` : ''}
                        </td>
                        <td style="padding:6px 8px; color:#fa0; font-family:monospace;">${_esc(d.revision) || '—'}</td>
                        <td style="padding:6px 8px;">${urlCell}</td>
                        <td style="padding:6px 8px; text-align:center;">
                            <button onclick="deleteDrawing('${d.id}').then(() => _testsRenderDetail('${testId}'))"
                                style="background:none; border:none; color:#333; cursor:pointer; font-size:12px;"
                                title="Remove drawing">&times;</button>
                        </td>
                    </tr>
                    ${d.drawing_number ? `<tr><td colspan="4" style="padding:0 16px 8px;">
                        <div id="tdr-${_esc(d.id)}"></div></td></tr>` : ''}`;
            });
            html += '</tbody></table>';
        }

        // ── Sessions section ────────────────────────────────────────────────
        html += `
            <div style="padding:10px 16px 6px; font-size:9px; color:#555; letter-spacing:1px;
                        border-top:1px solid #111; margin-top:4px;">
                MEASUREMENT SESSIONS
            </div>`;

        if (sessions.length === 0) {
            html += `<div style="padding:8px 16px; font-size:10px; color:#333;">No sessions recorded yet.</div>`;
        } else {
            sessions.forEach(s => {
                const sDate = new Date(s.epoch * 1000).toLocaleString();
                html += `
                    <div style="padding:6px 16px; border-bottom:1px solid #0d0d0d; display:flex;
                                gap:12px; align-items:baseline; font-size:10px;">
                        <span style="color:#aaa;">${sDate}</span>
                        <span style="color:#666;">${_esc(s.technician) || 'unknown'}</span>
                        <span style="color:#444; font-size:9px;">${_esc(s.instrument)}</span>
                        <span style="color:#333; font-size:9px;">${s.reading_count} readings</span>
                    </div>`;
            });
        }

        body.innerHTML = html;

        // Sibling revisions for each drawing that carries a drawing number
        // (read-only here — a test pins the revision that was referenced).
        if (typeof renderDrawingRevisions === "function") {
            (drawings || []).forEach(d => {
                if (!d.drawing_number) return;
                const el = document.getElementById("tdr-" + d.id);
                if (el) renderDrawingRevisions(el, {
                    drawingNumber: d.drawing_number,
                    currentRevision: d.revision,
                });
            });
        }

        // Add drawing form is rendered inline via _testsShowAddDrawing.
        // Two grouped rows — workflow actions, then export / share / admin —
        // so the footer wraps cleanly instead of squeezing button text.
        footer.style.flexDirection = "column";
        footer.innerHTML = `
            <div style="display:flex; gap:8px; flex-wrap:wrap;">
                <button onclick="_testsRenderList()"
                    style="background:#0a0a0a; border:1px solid #333; color:#666;
                           font-family:inherit; font-size:10px; padding:6px 12px; cursor:pointer;">
                    ← ALL TESTS
                </button>
                <div style="flex:1;"></div>
                <button onclick="hideTestsModal(); startTestMeasurement('${testId}', '${_esc(String(test.name || '').replace(/\\/g, '\\\\').replace(/'/g, "\\'"))}')"
                    style="background:#001a0a; border:1px solid #0f6; color:#0f6;
                           font-family:inherit; font-size:10px; padding:6px 14px; cursor:pointer; letter-spacing:1px; font-weight:bold;">
                    ▶ START MEASUREMENTS
                </button>
                <button onclick="showTestAudit('${testId}')"
                    style="background:#000d1a; border:1px solid #0f0; color:#0f0;
                           font-family:inherit; font-size:10px; padding:6px 14px; cursor:pointer; letter-spacing:1px;">
                    🔍 AUDIT
                </button>
            </div>
            <div style="display:flex; gap:8px; flex-wrap:wrap;">
                <button onclick="window.open('/static/print-report.html?test_id=${testId}', '_blank')"
                    style="background:#000d1a; border:1px solid #3af; color:#3af;
                           font-family:inherit; font-size:10px; padding:6px 14px; cursor:pointer; letter-spacing:1px;">
                    ⎙ PRINT REPORT
                </button>
                <button onclick="window.location='/api/tests/${testId}/report.xlsx?use360=' + (window._use360Lag !== undefined ? window._use360Lag : true)"
                    style="background:#001a0d; border:1px solid #3a7; color:#3a7;
                           font-family:inherit; font-size:10px; padding:6px 14px; cursor:pointer; letter-spacing:1px;">
                    ↓ DOWNLOAD EXCEL
                </button>
                <button onclick="_testsIngestExcel('${testId}')"
                    style="background:#1a1a00; border:1px solid #aa0; color:#aa0;
                           font-family:inherit; font-size:10px; padding:6px 14px; cursor:pointer; letter-spacing:1px;">
                    ↑ UPLOAD EXCEL
                </button>
                <button id="tests-publish-hub-btn" onclick="_testsPublishToHub('${testId}', this)"
                    style="background:#04121c; border:1px solid #3fdc8f; color:#3fdc8f;
                           font-family:inherit; font-size:10px; padding:6px 14px; cursor:pointer; letter-spacing:1px;">
                    ⇪ PUBLISH TO HUB
                </button>
                <div style="flex:1;"></div>
                <button onclick="if(confirm('Delete this test and all its drawings?')) deleteTest('${testId}').then(() => _testsRenderList())"
                    style="background:#1a0000; border:1px solid #600; color:#a00;
                           font-family:inherit; font-size:10px; padding:6px 12px; cursor:pointer;">
                    DELETE TEST
                </button>
            </div>`;
    }).catch(() => {
        body.innerHTML = '<div style="color:#f44; padding:14px;">Failed to load test detail.</div>';
    });
}

// ── Add drawing overlay ───────────────────────────────────────────────────────

function _testsShowAddDrawing(testId) {
    // Remove any existing overlay
    const existing = document.getElementById("add-drawing-overlay");
    if (existing) existing.remove();

    const overlay = document.createElement("div");
    overlay.id = "add-drawing-overlay";
    overlay.style.cssText = `position:absolute; inset:0; background:rgba(0,0,0,0.9);
        display:flex; flex-direction:column; gap:10px; padding:20px; z-index:10;
        font-family:'Consolas','Courier New',monospace;`;

    overlay.innerHTML = `
        <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid #1a1a1a; padding-bottom:8px;">
            <span style="font-size:10px; color:#0f0; letter-spacing:1px;">ADD DRAWING / REFERENCE</span>
            <button id="drw-search-btn" style="background:#04121c; border:1px solid #3af; color:#7fd0ff;
                    font-family:inherit; font-size:9px; letter-spacing:1px; padding:4px 10px; cursor:pointer;">
                🔍 SEARCH CORPORATE DRAWINGS
            </button>
        </div>

        <div style="display:flex; flex-direction:column; gap:4px;">
            <label style="font-size:10px; color:#888;">DRAWING TITLE / NUMBER <span style="color:#f00;">*</span></label>
            <input id="drw-title" type="text" placeholder="e.g. 25B1 Protection Schematic"
                style="background:#111; border:1px solid #333; color:#eee; padding:7px 10px;
                       font-family:inherit; font-size:11px; width:100%; box-sizing:border-box;" />
        </div>

        <div style="display:grid; grid-template-columns:1fr 120px; gap:10px;">
            <div style="display:flex; flex-direction:column; gap:4px;">
                <label style="font-size:10px; color:#888;">URL / FILE REFERENCE</label>
                <input id="drw-url" type="text" placeholder="https://... or \\\\server\\share\\drawing.pdf"
                    style="background:#111; border:1px solid #333; color:#eee; padding:7px 10px;
                           font-family:inherit; font-size:11px; width:100%; box-sizing:border-box;" />
            </div>
            <div style="display:flex; flex-direction:column; gap:4px;">
                <label style="font-size:10px; color:#888;">REVISION <span style="color:#f00;">*</span></label>
                <input id="drw-rev" type="text" placeholder="Rev C"
                    style="background:#111; border:1px solid #333; color:#eee; padding:7px 10px;
                           font-family:inherit; font-size:11px; width:100%; box-sizing:border-box;" />
            </div>
        </div>

        <div style="display:flex; flex-direction:column; gap:4px;">
            <label style="font-size:10px; color:#888;">NOTES</label>
            <input id="drw-notes" type="text" placeholder="Optional — e.g. Protection relay wiring detail"
                style="background:#111; border:1px solid #333; color:#eee; padding:7px 10px;
                       font-family:inherit; font-size:11px; width:100%; box-sizing:border-box;" />
        </div>
        <input id="drw-dwgnum" type="hidden" />

        <div style="display:flex; gap:8px; margin-top:4px;">
            <button id="drw-save-btn"
                style="flex:1; background:#001a00; border:1px solid #0f0; color:#0f0;
                       font-family:inherit; font-size:10px; padding:8px; cursor:pointer; letter-spacing:1px;">
                SAVE DRAWING
            </button>
            <button onclick="document.getElementById('add-drawing-overlay').remove()"
                style="background:#0a0a0a; border:1px solid #333; color:#666;
                       font-family:inherit; font-size:10px; padding:8px; cursor:pointer;">
                CANCEL
            </button>
        </div>`;

    document.getElementById("tests-modal-body").style.position = "relative";
    document.getElementById("tests-modal-body").appendChild(overlay);
    document.getElementById("drw-title").focus();

    const dsb = document.getElementById("drw-search-btn");
    if (dsb && typeof _openDrawingSearch === "function") {
        dsb.onclick = () => _openDrawingSearch({}, (d) => {
            const set = (id, v) => { const el = document.getElementById(id); if (el) el.value = v || ""; };
            set("drw-title", d.title || d.drawing_number);
            set("drw-rev", d.revision);
            set("drw-url", d.document_url);
            set("drw-dwgnum", d.drawing_number);
            set("drw-notes", "DWG " + d.drawing_number + (d.drawing_subject ? " · subj " + d.drawing_subject : ""));
        });
    } else if (dsb) {
        dsb.style.display = "none";
    }

    const save = () => {
        const title = (document.getElementById("drw-title").value || "").trim();
        const url   = (document.getElementById("drw-url").value   || "").trim();
        const rev   = (document.getElementById("drw-rev").value   || "").trim();
        const notes = (document.getElementById("drw-notes").value || "").trim();
        const dwgnum = (document.getElementById("drw-dwgnum").value || "").trim();

        let valid = true;
        [["drw-title", title], ["drw-rev", rev]].forEach(([id, val]) => {
            const el = document.getElementById(id);
            if (!val) { el.style.borderColor = "#f00"; valid = false; }
            else el.style.borderColor = "#333";
        });
        if (!valid) return;

        const btn = document.getElementById("drw-save-btn");
        btn.textContent = "SAVING..."; btn.disabled = true;

        addDrawing(testId, title, url, rev, notes, dwgnum).then(resp => {
            if (resp.error) { alert("Error: " + resp.error); btn.textContent = "SAVE DRAWING"; btn.disabled = false; return; }
            overlay.remove();
            _testsRenderDetail(testId);
        }).catch(() => { alert("Network error."); btn.textContent = "SAVE DRAWING"; btn.disabled = false; });
    };

    document.getElementById("drw-save-btn").onclick = save;
    overlay.querySelectorAll("input").forEach(inp => {
        inp.addEventListener("keydown", e => { if (e.key === "Enter") save(); });
    });
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function _esc(s) {
    return String(s || "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}

function _truncate(s, n) {
    return s.length > n ? s.slice(0, n) + "…" : s;
}

/**
 * Lightweight test picker used by the measurement wizard and PLUG sequence.
 * Returns a Promise that resolves to { test_id, test_name } or null (skipped).
 */
function pickTest(technicianName) {
    return new Promise(resolve => {
        const modal  = document.getElementById("test-picker-modal");
        const body   = document.getElementById("test-picker-body");
        const footer = document.getElementById("test-picker-footer");

        modal.style.display = "flex";
        body.innerHTML = '<div style="color:#555; padding:14px; font-size:10px;">Loading tests...</div>';

        let selectedTestId   = null;
        let selectedTestName = null;

        const close = (result) => {
            modal.style.display = "none";
            resolve(result);
        };

        // Footer buttons — wired with addEventListener, not onclick strings
        footer.innerHTML = `
            <button id="picker-skip-btn"
                style="background:#0a0a0a; border:1px solid #333; color:#555;
                       font-family:inherit; font-size:10px; padding:6px 12px; cursor:pointer;">
                SKIP
            </button>
            <div style="flex:1;"></div>
            <button id="test-picker-confirm" disabled
                style="background:#001a00; border:1px solid #0f0; color:#0f0; opacity:0.4;
                       font-family:inherit; font-size:10px; padding:6px 16px; cursor:pointer; letter-spacing:1px;">
                ATTACH TO TEST →
            </button>`;

        document.getElementById("picker-skip-btn").addEventListener("click", () => close(null));

        fetchTests().then(({ tests }) => {
            let html = `
                <div style="padding:8px 14px 4px; font-size:9px; color:#555; letter-spacing:1px;">
                    SELECT TEST FOR THIS SESSION
                </div>
                <div id="picker-create-row" style="padding:10px 14px; border-bottom:1px solid #111; cursor:pointer;">
                    <div style="font-size:11px; color:#0f0;">+ CREATE NEW TEST</div>
                    <div style="font-size:9px; color:#444; margin-top:2px;">Define a new named test for this measurement run</div>
                </div>`;

            if (tests && tests.length > 0) {
                tests.filter(t => t.status !== "ARCHIVED").forEach(t => {
                    const sc = STATUS_COLOR[t.status] || "#888";
                    html += `
                        <div class="test-row" data-test-id="${t.id}" data-test-name="${_esc(t.name)}">
                            <div style="display:flex; justify-content:space-between; align-items:baseline;">
                                <span class="test-row-name">${_esc(t.name)}</span>
                                <span style="font-size:9px; border:1px solid ${sc}; color:${sc}; padding:1px 5px;">${t.status}</span>
                            </div>
                            <div class="test-row-meta">
                                ${t.session_count} session${t.session_count !== 1 ? 's' : ''}
                                &nbsp;&bull;&nbsp;${t.drawing_count} drawing${t.drawing_count !== 1 ? 's' : ''}
                            </div>
                        </div>`;
                });
            } else {
                html += `<div style="padding:10px 14px; font-size:10px; color:#333;">No active tests — create one above.</div>`;
            }

            body.innerHTML = html;

            document.getElementById("picker-create-row").addEventListener("click", () => {
                _pickerShowCreate(technicianName, close);
            });

            body.querySelectorAll(".test-row").forEach(row => {
                row.addEventListener("click", () => {
                    selectedTestId   = row.dataset.testId;
                    selectedTestName = row.dataset.testName;
                    body.querySelectorAll(".test-row").forEach(r => r.classList.remove("test-row-active"));
                    row.classList.add("test-row-active");
                    const btn = document.getElementById("test-picker-confirm");
                    btn.disabled = false;
                    btn.style.opacity = "1";
                    btn.onclick = () => close({ test_id: selectedTestId, test_name: selectedTestName });
                });
            });

        }).catch(() => {
            body.innerHTML = '<div style="color:#f44; padding:14px;">Failed to load tests.</div>';
        });
    });
}

function _pickerShowCreate(technicianName, close) {
    const body = document.getElementById("test-picker-body");
    body.innerHTML = `
        <div style="padding:16px; display:flex; flex-direction:column; gap:10px;">
            <div style="font-size:10px; color:#0f0; letter-spacing:1px; border-bottom:1px solid #1a1a1a; padding-bottom:8px;">
                NEW TEST
            </div>
            <div style="display:flex; flex-direction:column; gap:4px;">
                <label style="font-size:10px; color:#888;">TEST NAME <span style="color:#f00;">*</span></label>
                <input id="picker-new-name" type="text"
                    placeholder="e.g. 500kV Protection Analog Proof — ALZ to XYZ"
                    style="background:#111; border:1px solid #333; color:#eee; padding:8px 10px;
                           font-family:inherit; font-size:12px; width:100%; box-sizing:border-box;" />
            </div>
            <div style="display:flex; flex-direction:column; gap:4px;">
                <label style="font-size:10px; color:#888;">DESCRIPTION</label>
                <textarea id="picker-new-desc" rows="2"
                    placeholder="Objective, scope, or notes..."
                    style="background:#111; border:1px solid #333; color:#eee; padding:8px 10px;
                           font-family:inherit; font-size:11px; width:100%; box-sizing:border-box; resize:none;"></textarea>
            </div>
            <div style="display:flex; gap:8px; margin-top:4px;">
                <button id="picker-create-confirm"
                    style="flex:1; background:#001a00; border:1px solid #0f0; color:#0f0;
                           font-family:inherit; font-size:10px; padding:8px; cursor:pointer; letter-spacing:1px;">
                    CREATE &amp; ATTACH
                </button>
            </div>
        </div>`;

    const nameInput = document.getElementById("picker-new-name");
    nameInput.focus();

    const submit = () => {
        const name = (nameInput.value || "").trim();
        const desc = (document.getElementById("picker-new-desc").value || "").trim();
        if (!name) { nameInput.style.borderColor = "#f00"; return; }
        nameInput.style.borderColor = "#333";
        createTest(name, desc, technicianName || "").then(resp => {
            if (resp.error) { alert("Error: " + resp.error); return; }
            _pickerShowDrawings(resp.test_id, name, close);
        }).catch(() => alert("Network error creating test."));
    };

    nameInput.addEventListener("keydown", e => { if (e.key === "Enter") submit(); });
    document.getElementById("picker-create-confirm").addEventListener("click", submit);
}

function _pickerShowDrawings(testId, testName, close) {
    let drawingCount = 0;

    const render = () => {
        const body = document.getElementById("test-picker-body");
        body.innerHTML = `
            <div style="padding:16px; display:flex; flex-direction:column; gap:10px;">
                <div style="font-size:10px; color:#0f0; letter-spacing:1px; border-bottom:1px solid #1a1a1a; padding-bottom:8px;">
                    ADD DRAWINGS${drawingCount > 0 ? ` (${drawingCount} added)` : ''}
                </div>
                <div style="font-size:9px; color:#444; margin-bottom:2px;">${testName}</div>
                <div style="display:flex; flex-direction:column; gap:4px;">
                    <label style="font-size:10px; color:#888;">DRAWING TITLE <span style="color:#f00;">*</span></label>
                    <input id="drawing-title" type="text"
                        placeholder="e.g. 500kV Line Protection SLD"
                        style="background:#111; border:1px solid #333; color:#eee; padding:8px 10px;
                               font-family:inherit; font-size:12px; width:100%; box-sizing:border-box;" />
                </div>
                <div style="display:flex; gap:8px;">
                    <div style="flex:1; display:flex; flex-direction:column; gap:4px;">
                        <label style="font-size:10px; color:#888;">REVISION</label>
                        <input id="drawing-rev" type="text" placeholder="e.g. R3"
                            style="background:#111; border:1px solid #333; color:#eee; padding:6px 8px;
                                   font-family:inherit; font-size:11px; width:100%; box-sizing:border-box;" />
                    </div>
                </div>
                <div style="display:flex; flex-direction:column; gap:4px;">
                    <label style="font-size:10px; color:#888;">URL / REFERENCE</label>
                    <input id="drawing-url" type="text" placeholder="https://... or document reference"
                        style="background:#111; border:1px solid #333; color:#eee; padding:6px 8px;
                               font-family:inherit; font-size:11px; width:100%; box-sizing:border-box;" />
                </div>
                <div style="display:flex; flex-direction:column; gap:4px;">
                    <label style="font-size:10px; color:#888;">NOTES</label>
                    <textarea id="drawing-notes" rows="2" placeholder="Sheet numbers, relevant sections..."
                        style="background:#111; border:1px solid #333; color:#eee; padding:6px 8px;
                               font-family:inherit; font-size:11px; width:100%; box-sizing:border-box; resize:none;"></textarea>
                </div>
                <div style="display:flex; gap:8px; margin-top:4px;">
                    <button id="drawing-skip-btn"
                        style="background:#0a0a0a; border:1px solid #333; color:#555;
                               font-family:inherit; font-size:10px; padding:8px 14px; cursor:pointer;">
                        ${drawingCount > 0 ? 'DONE' : 'SKIP'}
                    </button>
                    <button id="drawing-add-btn"
                        style="flex:1; background:#001a00; border:1px solid #0f0; color:#0f0;
                               font-family:inherit; font-size:10px; padding:8px; cursor:pointer; letter-spacing:1px;">
                        ${drawingCount > 0 ? '+ ADD ANOTHER DRAWING' : 'ADD DRAWING'}
                    </button>
                </div>
            </div>`;

        document.getElementById("drawing-skip-btn").addEventListener("click", () => {
            close({ test_id: testId, test_name: testName });
        });

        const addBtn = document.getElementById("drawing-add-btn");
        addBtn.addEventListener("click", () => {
            const title = (document.getElementById("drawing-title").value || "").trim();
            const rev   = (document.getElementById("drawing-rev").value || "").trim();
            const url   = (document.getElementById("drawing-url").value || "").trim();
            const notes = (document.getElementById("drawing-notes").value || "").trim();
            if (!title) { document.getElementById("drawing-title").style.borderColor = "#f00"; return; }
            addBtn.textContent = "SAVING...";
            addBtn.disabled = true;
            addDrawing(testId, title, url, rev, notes).then(() => {
                drawingCount++;
                render();
            }).catch(() => {
                addBtn.textContent = drawingCount > 0 ? "+ ADD ANOTHER DRAWING" : "ADD DRAWING";
                addBtn.disabled = false;
                alert("Network error adding drawing.");
            });
        });

        document.getElementById("drawing-title").focus();
    };

    // Clear the picker footer — navigation is inline
    document.getElementById("test-picker-footer").innerHTML = "";
    render();
}

function _testsIngestExcel(testId) {
    let input = document.getElementById("excel-ingest-input");
    if (!input) {
        input = document.createElement("input");
        input.id = "excel-ingest-input";
        input.type = "file";
        input.accept = ".xlsx";
        input.style.display = "none";
        document.body.appendChild(input);
    }
    input.onchange = e => {
        const file = e.target.files[0];
        if (!file) return;
        input.value = ""; // allow re-selecting the same file after a failed attempt
        _testsShowIngestResult(testId, null, "loading");
        const reader = new FileReader();
        reader.onload = () => {
            const b64 = reader.result.split(",")[1];
            fetch("/api/tests/ingest-report", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ test_id: testId, data: b64 })
            })
            .then(r => r.json())
            .then(res => {
                if (res.ok) {
                    _testsShowIngestResult(testId, res, "ok");
                    _testsRenderDetail(testId);
                } else {
                    _testsShowIngestResult(testId, res, "error");
                }
            })
            .catch(err => _testsShowIngestResult(testId, { error: String(err) }, "error"));
        };
        reader.readAsDataURL(file);
    };
    input.click();
}

// Replaces the old blocking alert()s with an actual summary — which devices
// were imported (and how many phases), which blocks were skipped and why,
// and any device name that doesn't match the current substation model.
function _testsShowIngestResult(testId, result, state) {
    const existing = document.getElementById("ingest-result-overlay");
    if (existing) existing.remove();

    const overlay = document.createElement("div");
    overlay.id = "ingest-result-overlay";
    overlay.style.cssText =
        "position:fixed; inset:0; background:rgba(0,0,0,0.85); z-index:11600; " +
        "display:flex; align-items:center; justify-content:center; font-family:'Consolas','Courier New',monospace;";
    if (state !== "loading") {
        overlay.addEventListener("mousedown", e => { if (e.target === overlay) overlay.remove(); });
    }

    const panel = document.createElement("div");
    panel.style.cssText =
        "background:#0c0c0c; border:1px solid " + (state === "error" ? "#a00" : "#0f0") +
        "; width:560px; max-height:80vh; display:flex; flex-direction:column; color:#ccc;";
    overlay.appendChild(panel);
    document.body.appendChild(overlay);

    if (state === "loading") {
        panel.innerHTML =
            '<div style="padding:24px; text-align:center; color:#888; font-size:11px;">Reading workbook…</div>';
        return;
    }

    if (state === "error") {
        panel.innerHTML = `
            <div style="display:flex; justify-content:space-between; align-items:center;
                        border-bottom:1px solid #1a1a1a; padding:10px 16px; color:#c66; letter-spacing:2px; font-size:11px;">
                <span>✗ IMPORT FAILED</span>
                <span id="ingest-close" style="cursor:pointer; color:#666;">[X]</span>
            </div>
            <div style="padding:16px; font-size:11px; line-height:1.6; color:#e88;">
                ${_esc((result && result.error) || "Unknown error.")}
            </div>
            <div style="padding:0 16px 16px; font-size:10px; color:#666;">
                Nothing was recorded — the file is unchanged, so you can fix it and try UPLOAD EXCEL again.
            </div>
            <div style="padding:12px 16px; border-top:1px solid #1a1a1a; display:flex; justify-content:flex-end;">
                <button onclick="document.getElementById('ingest-result-overlay').remove()"
                    style="background:#0a0a0a; border:1px solid #333; color:#888; font-family:inherit;
                           font-size:10px; padding:6px 14px; cursor:pointer;">CLOSE</button>
            </div>`;
        document.getElementById("ingest-close").onclick = () => overlay.remove();
        return;
    }

    // state === "ok"
    const imported = result.imported || [];
    const skipped = result.skipped || [];
    const unknown = new Set(result.unknown_devices || []);

    const importedRows = imported.map(d => `
        <div style="padding:6px 0; border-bottom:1px solid #111; font-size:10px; display:flex; justify-content:space-between;">
            <span style="color:#0f0;">${_esc(d.device_id)}</span>
            <span style="color:#555;">${_esc(d.type)} · phases ${d.phases.join(", ") || "—"} · ${d.count} value${d.count !== 1 ? "s" : ""}</span>
        </div>`).join("") || '<div style="color:#333; font-size:10px; padding:6px 0;">none</div>';

    const skippedRows = skipped.map(s => `
        <div style="padding:6px 0; border-bottom:1px solid #111; font-size:10px;">
            <span style="color:${unknown.has(s.device_id) ? '#fa0' : '#888'};">row ${s.row}${s.device_id ? " — " + _esc(s.device_id) : ""}</span>
            <span style="color:#555;"> — ${_esc(s.reason)}</span>
        </div>`).join("");

    panel.innerHTML = `
        <div style="display:flex; justify-content:space-between; align-items:center;
                    border-bottom:1px solid #1a1a1a; padding:10px 16px; color:#0f0; letter-spacing:2px; font-size:11px;">
            <span>✓ IMPORT COMPLETE</span>
            <span id="ingest-close" style="cursor:pointer; color:#666;">[X]</span>
        </div>
        <div style="padding:10px 16px; font-size:10px; color:#888; border-bottom:1px solid #111;">
            ${result.measurement_count} value${result.measurement_count !== 1 ? "s" : ""} recorded across
            ${imported.length} device${imported.length !== 1 ? "s" : ""} &nbsp;·&nbsp;
            technician: ${_esc(result.technician)} &nbsp;·&nbsp; session ${_esc((result.session_id || "").slice(0, 8))}
        </div>
        <div style="overflow-y:auto; flex:1; padding:12px 16px;">
            <div style="font-size:9px; color:#555; letter-spacing:1px; margin-bottom:4px;">IMPORTED</div>
            ${importedRows}
            ${skipped.length ? `
                <div style="font-size:9px; color:#a80; letter-spacing:1px; margin:14px 0 4px;">SKIPPED (${skipped.length})</div>
                ${skippedRows}
            ` : ""}
            ${unknown.size ? `
                <div style="margin-top:14px; padding:10px; background:#1a1500; border:1px solid #663; font-size:10px; color:#fa0;">
                    ${unknown.size} device name${unknown.size !== 1 ? "s" : ""} didn't match anything in the current
                    substation model: ${_esc(Array.from(unknown).join(", "))}. Check for a typo or a renamed device,
                    then re-upload — everything else above was still recorded.
                </div>
            ` : ""}
        </div>
        <div style="padding:12px 16px; border-top:1px solid #1a1a1a; display:flex; justify-content:flex-end;">
            <button onclick="document.getElementById('ingest-result-overlay').remove()"
                style="background:#001a00; border:1px solid #0f0; color:#0f0; font-family:inherit;
                       font-size:10px; padding:6px 14px; cursor:pointer;">CLOSE</button>
        </div>`;
    document.getElementById("ingest-close").onclick = () => overlay.remove();
}

// ── Poneglyph Hub — publish / browse the shared test pool ─────────────────────

function _testsPublishToHub(testId, btn) {
    if (!window.PoneglyphHub || !PoneglyphHub.connected()) {
        alert("Connect to the hub first: ⚙ SETTINGS → PONEGLYPH HUB.");
        return;
    }
    const restore = btn ? btn.textContent : "";
    if (btn) { btn.disabled = true; btn.textContent = "PUBLISHING…"; }
    PoneglyphHub.publishTest(testId)
        .then(res => {
            if (btn) btn.textContent = res.dedup ? "✓ ALREADY ON HUB" : "✓ PUBLISHED";
        })
        .catch(err => {
            alert("Publish failed: " + (err.message || err));
            if (btn) { btn.disabled = false; btn.textContent = restore; }
        });
}

function _testsShowShared() {
    const existing = document.getElementById("shared-tests-overlay");
    if (existing) existing.remove();

    const overlay = document.createElement("div");
    overlay.id = "shared-tests-overlay";
    overlay.style.cssText =
        "position:fixed; inset:0; background:rgba(0,0,0,0.8); z-index:11200; " +
        "display:flex; align-items:center; justify-content:center; font-family:'Consolas','Courier New',monospace;";
    overlay.addEventListener("mousedown", e => { if (e.target === overlay) overlay.remove(); });

    const panel = document.createElement("div");
    panel.style.cssText =
        "background:#0c0c0c; border:1px solid #3fdc8f; width:640px; max-height:82vh; " +
        "display:flex; flex-direction:column; color:#ccc;";
    overlay.appendChild(panel);

    panel.innerHTML = `
        <div style="display:flex; justify-content:space-between; align-items:center;
                    border-bottom:1px solid #1a1a1a; padding:10px 14px; color:#3fdc8f;
                    letter-spacing:2px; font-size:11px;">
            <span>☁ SHARED TESTS</span>
            <span id="shared-tests-close" style="cursor:pointer; color:#666;">[X]</span>
        </div>
        <div id="shared-tests-body" style="overflow-y:auto; flex:1; padding:4px 0; font-size:10px;">
            <div style="color:#555; padding:16px;">Loading…</div>
        </div>`;
    document.body.appendChild(overlay);
    document.getElementById("shared-tests-close").onclick = () => overlay.remove();

    const bodyEl = document.getElementById("shared-tests-body");

    if (!window.PoneglyphHub || !PoneglyphHub.connected()) {
        bodyEl.innerHTML =
            '<div style="color:#888; padding:20px; text-align:center;">' +
            "Not connected to a hub.<br><span style=\"color:#555;\">" +
            "Open ⚙ SETTINGS → PONEGLYPH HUB to sign in.</span></div>";
        return;
    }

    PoneglyphHub.browseTests("")
        .then(tests => {
            if (!tests.length) {
                bodyEl.innerHTML =
                    '<div style="color:#555; padding:20px; text-align:center;">No published tests yet.</div>';
                return;
            }
            let localIds = new Set();
            fetchTests().then(({ tests: mine }) => {
                (mine || []).forEach(t => localIds.add(t.id));
                render();
            }).catch(render);

            function render() {
                bodyEl.innerHTML = tests.map(t => {
                    const date = t.published_epoch
                        ? new Date(t.published_epoch * 1000).toLocaleDateString() : "—";
                    const have = localIds.has(t.test_id);
                    return `
                    <div style="display:flex; align-items:center; gap:10px; padding:8px 14px;
                                border-bottom:1px solid #111;">
                        <div style="flex:1; min-width:0;">
                            <div style="color:#eee;">${_esc(t.name || "(untitled)")}</div>
                            <div style="color:#666; font-size:9px; margin-top:2px;">
                                ${_esc(t.substation_id || "?")} &nbsp;&bull;&nbsp;
                                ${t.session_count} sess / ${t.reading_count} rdg &nbsp;&bull;&nbsp;
                                ${_esc(t.published_by || "?")} &nbsp;&bull;&nbsp; ${date}
                            </div>
                        </div>
                        <button data-pull="${_esc(t.test_id)}" ${have ? "disabled" : ""}
                            style="white-space:nowrap; background:${have ? "#111" : "#001a0a"};
                                   border:1px solid ${have ? "#333" : "#0f6"};
                                   color:${have ? "#555" : "#0f6"};
                                   font-family:inherit; font-size:9px; letter-spacing:1px;
                                   padding:4px 10px; cursor:${have ? "default" : "pointer"};">
                            ${have ? "IN THIS SITE" : "PULL →"}
                        </button>
                    </div>`;
                }).join("");

                bodyEl.querySelectorAll("button[data-pull]").forEach(b => {
                    if (b.disabled) return;
                    b.onclick = () => {
                        b.disabled = true;
                        b.textContent = "PULLING…";
                        PoneglyphHub.pullTest(b.getAttribute("data-pull"))
                            .then(() => {
                                b.textContent = "IN THIS SITE";
                                b.style.color = "#555";
                                b.style.borderColor = "#333";
                                if (typeof _testsRenderList === "function") _testsRenderList();
                            })
                            .catch(err => {
                                alert("Pull failed: " + (err.message || err));
                                b.disabled = false;
                                b.textContent = "PULL →";
                            });
                    };
                });
            }
        })
        .catch(err => {
            bodyEl.innerHTML =
                '<div style="color:#c66; padding:20px; text-align:center;">' +
                _esc(err.message || "Could not reach the hub.") + "</div>";
        });
}
