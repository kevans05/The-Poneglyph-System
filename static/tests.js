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
    footer.innerHTML = `
        <button onclick="_testsRenderCreate()"
            style="background:#001a00; border:1px solid #0f0; color:#0f0;
                   font-family:inherit; font-size:10px; padding:6px 14px; cursor:pointer; letter-spacing:1px;">
            + NEW TEST
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
                    <div style="display:flex; justify-content:space-between; align-items:baseline; margin-bottom:4px;">
                        <span class="test-row-name">${_esc(t.name)}</span>
                        <span style="font-size:9px; border:1px solid ${sc}; color:${sc};
                                     padding:1px 6px; letter-spacing:1px; white-space:nowrap;">${t.status}</span>
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
                    </tr>`;
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

        // Add drawing form is rendered inline via _testsShowAddDrawing
        footer.innerHTML = `
            <button onclick="_testsRenderList()"
                style="background:#0a0a0a; border:1px solid #333; color:#666;
                       font-family:inherit; font-size:10px; padding:6px 12px; cursor:pointer;">
                ← ALL TESTS
            </button>
            <div style="flex:1;"></div>
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
                ↑ UPLOAD COMPLETED EXCEL
            </button>
            <button onclick="if(confirm('Delete this test and all its drawings?')) deleteTest('${testId}').then(() => _testsRenderList())"
                style="background:#1a0000; border:1px solid #600; color:#a00;
                       font-family:inherit; font-size:10px; padding:6px 12px; cursor:pointer;">
                DELETE TEST
            </button>`;
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
        <div style="font-size:10px; color:#0f0; letter-spacing:1px; border-bottom:1px solid #1a1a1a; padding-bottom:8px;">
            ADD DRAWING / REFERENCE
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

    const save = () => {
        const title = (document.getElementById("drw-title").value || "").trim();
        const url   = (document.getElementById("drw-url").value   || "").trim();
        const rev   = (document.getElementById("drw-rev").value   || "").trim();
        const notes = (document.getElementById("drw-notes").value || "").trim();

        let valid = true;
        [["drw-title", title], ["drw-rev", rev]].forEach(([id, val]) => {
            const el = document.getElementById(id);
            if (!val) { el.style.borderColor = "#f00"; valid = false; }
            else el.style.borderColor = "#333";
        });
        if (!valid) return;

        const btn = document.getElementById("drw-save-btn");
        btn.textContent = "SAVING..."; btn.disabled = true;

        addDrawing(testId, title, url, rev, notes).then(resp => {
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
                    alert("Import successful! Session ID: " + res.session_id);
                    _testsRenderDetail(testId);
                } else {
                    alert("Import failed: " + (res.error || "Unknown error"));
                }
            })
            .catch(err => alert("Network error: " + err));
        };
        reader.readAsDataURL(file);
    };
    input.click();
}
