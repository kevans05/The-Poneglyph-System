"use strict";

/**
 * Simulation Mode Controller
 */

let simActive = false;
let simPaused = true;
let lastFrameId = -1;
let simTime = 0;
let simSpeed = 1.0;
let simData = null; // Local copy of topology for simulation
let frameQueue = [];
let simInterval = null;
let simLogOpen = false;

// Oscillography buffer — rolling 60-second window of per-device current samples
let _oscBuffer = [];  // [{sim_time_ms, data: {device_id: {ia,ib,ic}}}]
let _oscEvents = [];  // [{sim_time, type, device_id, ...}] for markers
const OSC_WINDOW_MS = 60000;

// Rewind history — periodic snapshots of sim state for scrubbing backwards
let _rewindHistory = [];      // [{simTime, state: JSON string of simData}]
let _lastRewindSnapshotTime = -Infinity;
let _rewindMode = false;
let _rewindIdx = -1;
const REWIND_SNAPSHOT_INTERVAL_MS = 500;  // one snapshot per 500ms sim-time
const REWIND_MAX_SNAPSHOTS = 240;         // ~2 minutes of history

function startSim() {
    if (simActive) return;
    if (!confirm("Enter Simulation Mode? This will snapshot the current topology and start the virtual clock.")) return;

    // Snapshot current topology
    if (!currentData) {
        alert("Load a site first!");
        return;
    }
    simData = JSON.parse(JSON.stringify(currentData));

    fetch("/api/sim/start", { method: "POST" })
        .then(r => r.json())
        .then(res => {
            simActive = true;
            const toggleBtn = document.getElementById("sim-toggle-btn");
            if (toggleBtn) toggleBtn.innerText = "EXIT SIM";
            simPaused = true;
            lastFrameId = -1;
            frameQueue = [];
            document.getElementById("sim-bar").style.display = "flex";
            document.body.classList.add("sim-mode-active");

            clearSimLog();
            addSimLogEntry(0, "SIM_START", {});

            // Start polling and playback loops
            simPoll();
            requestAnimationFrame(simPlaybackLoop);
        });
}

function stopSim() {
    if (_rewindMode) exitRewindMode();
    fetch("/api/sim/stop", { method: "POST" })
        .then(() => {
            simActive = false;
            simPaused = true;
            document.getElementById("sim-bar").style.display = "none";
            document.body.classList.remove("sim-mode-active");
            const toggleBtn = document.getElementById("sim-toggle-btn");
            if (toggleBtn) toggleBtn.innerText = "SIMULATION";
            simData = null;
            frameQueue = [];
            _oscBuffer = [];
            _oscEvents = [];
            _rewindHistory = [];
            _lastRewindSnapshotTime = -Infinity;
            // Hide log panel
            if (simLogOpen) toggleSimLog();
            // Trigger a refresh of the real data
            refreshData();
        });
}

function resetSim() {
    if (!simActive) return;
    if (_rewindMode) exitRewindMode();
    fetch("/api/sim/reset", { method: "POST" })
        .then(r => r.json())
        .then(() => {
            simPaused = true;
            lastFrameId = -1;
            frameQueue = [];
            _oscBuffer = [];
            _oscEvents = [];
            _rewindHistory = [];
            _lastRewindSnapshotTime = -Infinity;
            document.getElementById("sim-pause-btn").innerText = "RESUME";
            clearSimLog();
            addSimLogEntry(0, "SIM_START", {});
        });
}

function toggleSimPause() {
    simPaused = !simPaused;
    fetch("/api/sim/pause", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ paused: simPaused })
    }).then(() => {
        document.getElementById("sim-pause-btn").innerText = simPaused ? "RESUME" : "PAUSE";
    });
}

function updateSimSpeed(val) {
    // val is log-scale slider
    simSpeed = Math.pow(10, val);
    document.getElementById("sim-speed-label").innerText = simSpeed.toFixed(1) + "x";
    fetch("/api/sim/speed", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ multiplier: simSpeed })
    });
}

function simPoll() {
    if (!simActive) return;
    
    fetch("/api/sim/frames?since=" + lastFrameId)
        .then(r => r.json())
        .then(res => {
            if (res.frames && res.frames.length > 0) {
                for (let f of res.frames) {
                    if (f.full_sld) {
                        simData = JSON.parse(JSON.stringify(f.full_sld));
                    }
                }
                frameQueue.push(...res.frames);
                lastFrameId = res.frames[res.frames.length - 1].id;
            }
            document.getElementById("sim-status").innerText = simPaused ? "PAUSED" : (frameQueue.length > 100 ? "BUFFERING..." : "LIVE");
            document.getElementById("sim-pause-btn").innerText = "RESUME";
            setTimeout(simPoll, 200);
        })
        .catch(err => {
            console.error("Sim poll error:", err);
            if (simActive) setTimeout(simPoll, 1000);
        });
}

let lastRealTime = 0;
function simPlaybackLoop(now) {
    if (!simActive) return;
    
    if (!lastRealTime) lastRealTime = now;
    let dt = now - lastRealTime;
    lastRealTime = now;
    
    if (!simPaused && !_rewindMode) {
        if (frameQueue.length > 0) {
            let catchup = 1.0;
            if (frameQueue.length > 50) catchup = 1.5;
            if (frameQueue.length > 200) catchup = 5.0;

            simTime += dt * simSpeed * catchup;

            while (frameQueue.length > 0 && frameQueue[0].sim_time <= simTime) {
                applyFrame(frameQueue.shift());
            }

            if (frameQueue.length > 500) {
                let latest = frameQueue.pop();
                frameQueue = [];
                simTime = latest.sim_time;
                applyFrame(latest);
            }
        }
    }
    
    updateSimUI();
    requestAnimationFrame(simPlaybackLoop);
}

function applyFrame(frame) {
    if (!simData) return;

    if (frame.full_sld) {
        simData = JSON.parse(JSON.stringify(frame.full_sld));
    }

    for (let did in frame.changes) {
        let change = frame.changes[did];
        let node = simData.nodes.find(n => n.id === did);
        if (node) {
            Object.assign(node, change);
            if (change.fault_state === null) delete node.fault_state;
        }
    }

    if (frame.events && frame.events.length > 0) {
        for (let e of frame.events) {
            addSimLogEntry(e.sim_time, e.type, e);
            // Keep events for oscillography markers
            if (['FAULT','RELAY_PICKUP','SWITCH_OP','AR_RECLOSE','AR_LOCKOUT','BF_TRIP'].includes(e.type)) {
                _oscEvents.push(e);
                if (_oscEvents.length > 300) _oscEvents.shift();
            }
        }
    }

    // Populate oscillography buffer
    const snap = { sim_time_ms: frame.sim_time, data: {} };
    for (const did in frame.changes) {
        const cur = frame.changes[did].current;
        if (cur) snap.data[did] = { ia: cur.a.mag, ib: cur.b.mag, ic: cur.c.mag };
    }
    if (Object.keys(snap.data).length > 0) {
        _oscBuffer.push(snap);
        while (_oscBuffer.length > 0 && _oscBuffer[0].sim_time_ms < frame.sim_time - OSC_WINDOW_MS) {
            _oscBuffer.shift();
        }
    }

    render3LD(simData);

    Object.keys(openWindows).forEach((id) => {
        const node = simData.nodes.find((n) => n.id === id);
        if (node) updateWindow(id, node);
    });

    // Take a rewind snapshot if enough sim-time has elapsed
    if (!_rewindMode && frame.sim_time - _lastRewindSnapshotTime >= REWIND_SNAPSHOT_INTERVAL_MS) {
        _rewindHistory.push({ simTime: frame.sim_time, state: JSON.stringify(simData) });
        if (_rewindHistory.length > REWIND_MAX_SNAPSHOTS) _rewindHistory.shift();
        _lastRewindSnapshotTime = frame.sim_time;
        _updateRewindScrubber();
    }
}

function updateSimUI() {
    let date = new Date(simTime);
    let ms = String(Math.floor(simTime % 1000)).padStart(3, '0');
    let timeStr = date.toISOString().substr(11, 8) + "." + ms;
    const clock = document.getElementById("sim-clock");
    if (clock) {
        clock.innerText = (_rewindMode ? "⏪ " : "") + timeStr;
        clock.style.color = _rewindMode ? "#ffff00" : "#fff";
    }
}

function injectFault(deviceId, type) {
    console.log("Injecting", type, "fault on", deviceId);
    fetch("/api/sim/fault", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ device_id: deviceId, fault_type: type, impedance: 0.01 })
    });
}

function clearFault(deviceId) {
    console.log("Clearing fault on", deviceId);
    fetch("/api/sim/clear_fault", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ device_id: deviceId })
    });
}

/**
 * Fault Configuration UI
 */

function showFaultConfig(deviceId) {
    // Create modal if it doesn't exist
    let modal = document.getElementById("fault-config-modal");
    if (!modal) {
        modal = document.createElement("div");
        modal.id = "fault-config-modal";
        modal.className = "config-modal";
        modal.style.width = "380px";
        document.body.appendChild(modal);
    }
    
    modal.style.display = "flex";
    modal.innerHTML = `
        <div class="config-modal-header">
            <span>INJECT FAULT: ${deviceId}</span>
            <span style="display:flex;gap:8px;align-items:center;">
                <span class="modal-close" onclick="detachFaultConfig('${deviceId}')" title="Open in new window" style="cursor:pointer;color:#888;font-size:13px;">⤢</span>
                <span class="modal-close" onclick="this.closest('.config-modal').style.display='none'">[X]</span>
            </span>
        </div>
        <div class="config-modal-body" style="padding: 15px; gap: 10px;">
            <div style="display:flex; flex-direction:column; gap:4px;">
                <label style="font-size:10px; color:#888;">FAULT TYPE</label>
                <select id="fault-type" style="width:100%;">
                    <option value="3PH">Symmetric (3-Phase)</option>
                    <option value="SLG-A">Asymmetric (SLG-A)</option>
                    <option value="SLG-B">Asymmetric (SLG-B)</option>
                    <option value="SLG-C">Asymmetric (SLG-C)</option>
                    <option value="LL-AB">Line-to-Line (AB)</option>
                    <option value="LL-BC">Line-to-Line (BC)</option>
                    <option value="LL-CA">Line-to-Line (CA)</option>
                    <option value="LLG-AB">Line-to-Line-Ground (ABG)</option>
                    <option value="LLG-BC">Line-to-Line-Ground (BCG)</option>
                    <option value="LLG-CA">Line-to-Line-Ground (CAG)</option>
                </select>
            </div>
            
            <div style="display:flex; flex-direction:column; gap:4px;">
                <label style="font-size:10px; color:#888;">IMPEDANCE (Bolted = 0.001)</label>
                <input type="number" id="fault-impedance" value="0.01" step="0.001" style="width:100%;">
            </div>
            
            <div style="display:flex; flex-direction:column; gap:4px;">
                <label style="font-size:10px; color:#888;">PERSISTENCE</label>
                <select id="fault-persistence" onchange="document.getElementById('fault-dur-row').style.display = (this.value === 'transient' ? 'flex' : 'none')" style="width:100%;">
                    <option value="persistent">Persistent</option>
                    <option value="transient">Transient</option>
                </select>
            </div>
            
            <div id="fault-dur-row" style="display:none; flex-direction:column; gap:4px;">
                <label style="font-size:10px; color:#888;">DURATION (ms)</label>
                <input type="number" id="fault-duration" value="100" step="1" style="width:100%;">
            </div>

            <div style="display:flex; flex-direction:column; gap:4px;">
                <label style="font-size:10px; color:#888;">ACTIVATION DELAY (s) — fault triggers after this delay</label>
                <input type="number" id="fault-delay" value="0" step="0.1" min="0" style="width:100%;">
            </div>

            <div style="display:flex; flex-direction:column; gap:4px;">
                <label style="font-size:10px; color:#888;">SYSTEM X/R RATIO (typ: 10–40 transmission, 5–15 distribution)</label>
                <input type="number" id="fault-xr" value="15" step="1" min="1" max="100" style="width:100%;">
            </div>

            <div style="display:flex; align-items:center; gap:10px; margin-top:5px;">
                <input type="checkbox" id="fault-arcing">
                <label for="fault-arcing" style="font-size:11px; color:#ccc; cursor:pointer;">Arcing Fault (Variable Z)</label>
            </div>

            <div style="display:flex; align-items:center; gap:10px;">
                <input type="checkbox" id="fault-internal">
                <label for="fault-internal" style="font-size:11px; color:#ccc; cursor:pointer;">Internal Fault</label>
            </div>
        </div>
        <div class="config-modal-footer">
            <button onclick="commitFault('${deviceId}')" style="flex:1; border-color:#f55; color:#f55;">INJECT</button>
            <button onclick="this.closest('.config-modal').style.display='none'" class="wiz-secondary">CANCEL</button>
        </div>
    `;
}

function commitFault(deviceId) {
    const data = {
        device_id: deviceId,
        fault_type: document.getElementById("fault-type").value,
        impedance: parseFloat(document.getElementById("fault-impedance").value),
        x_r_ratio: parseFloat(document.getElementById("fault-xr").value) || 15,
        persistence: document.getElementById("fault-persistence").value,
        duration: parseFloat(document.getElementById("fault-duration").value),
        delay_ms: (parseFloat(document.getElementById("fault-delay").value) || 0) * 1000,
        arcing: document.getElementById("fault-arcing").checked,
        internal: document.getElementById("fault-internal").checked
    };

    fetch("/api/sim/fault", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data)
    }).then(() => {
        document.getElementById("fault-config-modal").style.display = "none";
    });
}

function detachFaultConfig(deviceId) {
    const modal = document.getElementById("fault-config-modal");
    const w = 420, h = 560;
    const left = Math.round(window.screenX + window.outerWidth / 2 - w / 2);
    const top  = Math.round(window.screenY + 80);
    const popup = window.open("", "fault_" + deviceId,
        "width=" + w + ",height=" + h + ",resizable=yes,left=" + left + ",top=" + top);
    if (!popup) { alert("Popup blocked — please allow popups for this site."); return; }

    // Gather styles
    const styleLinks = Array.from(document.querySelectorAll("link[rel=stylesheet]"))
        .map(l => '<link rel="stylesheet" href="' + l.href + '">')
        .join("\n");

    // Snapshot current form values
    const faultType   = document.getElementById("fault-type")?.value || "3PH";
    const impedance   = document.getElementById("fault-impedance")?.value || "0.01";
    const persistence = document.getElementById("fault-persistence")?.value || "persistent";
    const duration    = document.getElementById("fault-duration")?.value || "100";
    const delay       = document.getElementById("fault-delay")?.value || "0";
    const xr          = document.getElementById("fault-xr")?.value || "15";
    const arcing      = document.getElementById("fault-arcing")?.checked || false;
    const internal    = document.getElementById("fault-internal")?.checked || false;

    popup.document.write(`<!doctype html><html><head>
        <meta charset="UTF-8">
        <title>INJECT FAULT: ${deviceId}</title>
        ${styleLinks}
        <style>body{overflow:auto;height:auto;background:#0e0e0e;}</style>
    </head><body>
        <div class="config-modal" style="position:relative;top:0;left:0;transform:none;display:flex;width:100%;box-sizing:border-box;">
            <div class="config-modal-header">
                <span>INJECT FAULT: ${deviceId}</span>
                <span class="modal-close" onclick="window.close()">[X]</span>
            </div>
            <div class="config-modal-body" style="padding:15px;gap:10px;">
                <div style="display:flex;flex-direction:column;gap:4px;">
                    <label style="font-size:10px;color:#888;">FAULT TYPE</label>
                    <select id="fault-type" style="width:100%;">
                        <option value="3PH"   ${faultType==="3PH"?"selected":""}>Symmetric (3-Phase)</option>
                        <option value="SLG-A" ${faultType==="SLG-A"?"selected":""}>Asymmetric (SLG-A)</option>
                        <option value="SLG-B" ${faultType==="SLG-B"?"selected":""}>Asymmetric (SLG-B)</option>
                        <option value="SLG-C" ${faultType==="SLG-C"?"selected":""}>Asymmetric (SLG-C)</option>
                        <option value="LL-AB" ${faultType==="LL-AB"?"selected":""}>Line-to-Line (AB)</option>
                        <option value="LL-BC" ${faultType==="LL-BC"?"selected":""}>Line-to-Line (BC)</option>
                        <option value="LL-CA" ${faultType==="LL-CA"?"selected":""}>Line-to-Line (CA)</option>
                        <option value="LLG-AB" ${faultType==="LLG-AB"?"selected":""}>Line-to-Line-Ground (ABG)</option>
                        <option value="LLG-BC" ${faultType==="LLG-BC"?"selected":""}>Line-to-Line-Ground (BCG)</option>
                        <option value="LLG-CA" ${faultType==="LLG-CA"?"selected":""}>Line-to-Line-Ground (CAG)</option>
                    </select>
                </div>
                <div style="display:flex;flex-direction:column;gap:4px;">
                    <label style="font-size:10px;color:#888;">IMPEDANCE (Bolted = 0.001)</label>
                    <input type="number" id="fault-impedance" value="${impedance}" step="0.001" style="width:100%;">
                </div>
                <div style="display:flex;flex-direction:column;gap:4px;">
                    <label style="font-size:10px;color:#888;">PERSISTENCE</label>
                    <select id="fault-persistence" onchange="document.getElementById('fault-dur-row').style.display=(this.value==='transient'?'flex':'none')" style="width:100%;">
                        <option value="persistent" ${persistence==="persistent"?"selected":""}>Persistent</option>
                        <option value="transient"  ${persistence==="transient"?"selected":""}>Transient</option>
                    </select>
                </div>
                <div id="fault-dur-row" style="display:${persistence==="transient"?"flex":"none"};flex-direction:column;gap:4px;">
                    <label style="font-size:10px;color:#888;">DURATION (ms)</label>
                    <input type="number" id="fault-duration" value="${duration}" step="1" style="width:100%;">
                </div>
                <div style="display:flex;flex-direction:column;gap:4px;">
                    <label style="font-size:10px;color:#888;">ACTIVATION DELAY (s)</label>
                    <input type="number" id="fault-delay" value="${delay}" step="0.1" min="0" style="width:100%;">
                </div>
                <div style="display:flex;flex-direction:column;gap:4px;">
                    <label style="font-size:10px;color:#888;">SYSTEM X/R RATIO</label>
                    <input type="number" id="fault-xr" value="${xr}" step="1" min="1" max="100" style="width:100%;">
                </div>
                <div style="display:flex;align-items:center;gap:10px;margin-top:5px;">
                    <input type="checkbox" id="fault-arcing" ${arcing?"checked":""}>
                    <label for="fault-arcing" style="font-size:11px;color:#ccc;cursor:pointer;">Arcing Fault (Variable Z)</label>
                </div>
                <div style="display:flex;align-items:center;gap:10px;">
                    <input type="checkbox" id="fault-internal" ${internal?"checked":""}>
                    <label for="fault-internal" style="font-size:11px;color:#ccc;cursor:pointer;">Internal Fault</label>
                </div>
            </div>
            <div class="config-modal-footer">
                <button onclick="doInject()" style="flex:1;border-color:#f55;color:#f55;">INJECT</button>
                <button onclick="window.close()" class="wiz-secondary">CANCEL</button>
            </div>
        </div>
        <script>
        function doInject() {
            const data = {
                device_id: "${deviceId}",
                fault_type:  document.getElementById("fault-type").value,
                impedance:   parseFloat(document.getElementById("fault-impedance").value),
                x_r_ratio:   parseFloat(document.getElementById("fault-xr").value) || 15,
                persistence: document.getElementById("fault-persistence").value,
                duration:    parseFloat(document.getElementById("fault-duration").value),
                delay_ms:    (parseFloat(document.getElementById("fault-delay").value) || 0) * 1000,
                arcing:      document.getElementById("fault-arcing").checked,
                internal:    document.getElementById("fault-internal").checked
            };
            fetch("/api/sim/fault", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(data)})
                .then(() => window.close());
        }
        <\/script>
    </body></html>`);
    popup.document.close();
    // Hide the modal in the main window
    if (modal) modal.style.display = "none";
}

/**
 * Rewind / History Scrubber
 */

function enterRewindMode() {
    if (_rewindHistory.length === 0) {
        alert("No history recorded yet — let the simulation run for a moment first.");
        return;
    }
    _rewindMode = true;
    _rewindIdx = _rewindHistory.length - 1;
    if (!simPaused) toggleSimPause();

    const controls = document.getElementById("sim-rewind-controls");
    if (controls) {
        controls.style.display = "flex";
        const scrubber = document.getElementById("rewind-scrubber");
        if (scrubber) {
            scrubber.max = _rewindHistory.length - 1;
            scrubber.value = _rewindIdx;
        }
        document.getElementById("rewind-count").innerText =
            (_rewindIdx + 1) + "/" + _rewindHistory.length;
    }
    const btn = document.getElementById("sim-rewind-btn");
    if (btn) { btn.style.color = "#ffff00"; btn.style.borderColor = "#ffff00"; }

    _applyRewindSnapshot(_rewindIdx);
}

function exitRewindMode() {
    _rewindMode = false;
    const controls = document.getElementById("sim-rewind-controls");
    if (controls) controls.style.display = "none";
    const btn = document.getElementById("sim-rewind-btn");
    if (btn) { btn.style.color = ""; btn.style.borderColor = ""; }

    // Restore the most-recent snapshot so the display is consistent
    if (_rewindHistory.length > 0) {
        const latest = _rewindHistory[_rewindHistory.length - 1];
        simData = JSON.parse(latest.state);
        render3LD(simData);
        Object.keys(openWindows).forEach(id => {
            const node = simData.nodes.find(n => n.id === id);
            if (node) updateWindow(id, node);
        });
    }
}

function rewindStep(delta) {
    if (!_rewindMode) return;
    _rewindIdx = Math.max(0, Math.min(_rewindHistory.length - 1, _rewindIdx + delta));
    const scrubber = document.getElementById("rewind-scrubber");
    if (scrubber) scrubber.value = _rewindIdx;
    document.getElementById("rewind-count").innerText =
        (_rewindIdx + 1) + "/" + _rewindHistory.length;
    _applyRewindSnapshot(_rewindIdx);
}

function rewindScrub(val) {
    if (!_rewindMode) return;
    _rewindIdx = parseInt(val);
    document.getElementById("rewind-count").innerText =
        (_rewindIdx + 1) + "/" + _rewindHistory.length;
    _applyRewindSnapshot(_rewindIdx);
}

function _applyRewindSnapshot(idx) {
    const snap = _rewindHistory[idx];
    if (!snap) return;
    simData = JSON.parse(snap.state);
    simTime = snap.simTime;
    updateSimUI();
    render3LD(simData);
    Object.keys(openWindows).forEach(id => {
        const node = simData.nodes.find(n => n.id === id);
        if (node) updateWindow(id, node);
    });
}

function _updateRewindScrubber() {
    if (!_rewindMode) return;
    const scrubber = document.getElementById("rewind-scrubber");
    if (scrubber) {
        scrubber.max = _rewindHistory.length - 1;
        // Don't move thumb while user is manually scrubbing
    }
}

/**
 * Relay Settings Editor (live, during simulation)
 */

function showRelaySettingsEditor(deviceId) {
    // Resolve current settings from simData
    const node = simData && simData.nodes.find(n => n.id === deviceId);
    const settings = (node && node.params && node.params.settings) ? node.params.settings : {};

    let modal = document.getElementById("relay-settings-modal");
    if (!modal) {
        modal = document.createElement("div");
        modal.id = "relay-settings-modal";
        modal.className = "config-modal";
        modal.style.width = "420px";
        modal.style.maxHeight = "80vh";
        modal.style.flexDirection = "column";
        document.body.appendChild(modal);
    }

    // Build rows for existing settings + one blank "add" row
    let rowsHtml = Object.entries(settings).map(([k, v]) =>
        `<div class="rs-row" style="display:flex; gap:4px; align-items:center;">
            <input class="rs-key"   value="${_escAttr(String(k))}" style="flex:2; font-family:monospace;" placeholder="KEY">
            <input class="rs-value" value="${_escAttr(String(v))}" style="flex:2;" placeholder="VALUE">
            <button onclick="this.closest('.rs-row').remove()" style="flex:0 0 22px; background:#200; color:#f55; border:1px solid #f55; cursor:pointer; font-size:11px; padding:0;">✕</button>
         </div>`
    ).join("");

    modal.style.display = "flex";
    modal.innerHTML = `
        <div class="config-modal-header">
            <span>RELAY SETTINGS: ${deviceId}</span>
            <span class="modal-close" onclick="this.closest('.config-modal').style.display='none'">[X]</span>
        </div>
        <div class="config-modal-body" style="padding:10px; gap:6px; overflow-y:auto; flex:1;">
            <div style="font-size:9px; color:#666; margin-bottom:4px;">Changes apply immediately to the running simulation. Accumulator state is preserved for unchanged elements.</div>
            <div id="rs-rows" style="display:flex; flex-direction:column; gap:4px;">
                ${rowsHtml}
            </div>
            <button onclick="_rsAddRow()" style="margin-top:6px; width:100%; background:#001a00; color:#4f4; border:1px solid #4f4; padding:4px; cursor:pointer; font-size:11px;">+ ADD SETTING</button>
        </div>
        <div class="config-modal-footer">
            <button onclick="commitRelaySettings('${deviceId}')" style="flex:1; border-color:#3af; color:#3af;">APPLY</button>
            <button onclick="this.closest('.config-modal').style.display='none'" class="wiz-secondary">CANCEL</button>
        </div>`;
}

function _escAttr(s) {
    return s.replace(/&/g,"&amp;").replace(/"/g,"&quot;").replace(/</g,"&lt;");
}

function _rsAddRow() {
    const container = document.getElementById("rs-rows");
    const div = document.createElement("div");
    div.className = "rs-row";
    div.style.cssText = "display:flex; gap:4px; align-items:center;";
    div.innerHTML = `<input class="rs-key"   style="flex:2; font-family:monospace;" placeholder="KEY (e.g. 51N1P)">
                     <input class="rs-value" style="flex:2;" placeholder="VALUE">
                     <button onclick="this.closest('.rs-row').remove()" style="flex:0 0 22px; background:#200; color:#f55; border:1px solid #f55; cursor:pointer; font-size:11px; padding:0;">✕</button>`;
    container.appendChild(div);
    div.querySelector(".rs-key").focus();
}

function commitRelaySettings(deviceId) {
    const rows = document.querySelectorAll("#rs-rows .rs-row");
    const settings = {};
    rows.forEach(row => {
        const k = row.querySelector(".rs-key").value.trim();
        const v = row.querySelector(".rs-value").value.trim();
        if (!k) return;
        // Coerce to number where possible
        settings[k] = isNaN(v) || v === "" ? v : parseFloat(v);
    });

    fetch("/api/sim/relay_settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ device_id: deviceId, settings })
    }).then(r => r.json()).then(res => {
        if (res.ok) {
            document.getElementById("relay-settings-modal").style.display = "none";
            addSimLogEntry(simTime, "SETTINGS_CHANGE", { device_id: deviceId });
        }
    });
}

/**
 * Toggle simulation mode on/off
 */
function toggleSimMode() {
    if (simActive) {
        stopSim();
    } else {
        startSim();
    }
}

/**
 * Simulation Event Log
 */

const SIM_LOG_EVENT_STYLES = {
    SIM_START:       { color: "#ffffff", label: "SIM START" },
    FAULT:           { color: "#ff4444", label: "FAULT" },
    CLEAR_FAULT:     { color: "#44ffff", label: "CLR FAULT" },
    RELAY_PICKUP:    { color: "#ffff44", label: "PICKUP" },
    RELAY_DROPOUT:   { color: "#777777", label: "DROPOUT" },
    SETTINGS_CHANGE: { color: "#88aaff", label: "SETTINGS" },
    AR_RECLOSE:      { color: "#44ff88", label: "RECLOSE" },
    AR_LOCKOUT:      { color: "#ff6600", label: "AR LOCKOUT" },
    BF_TRIP:         { color: "#ff2200", label: "BF TRIP" },
    SWITCH_OP:       null, // handled inline based on state
};

function addSimLogEntry(sim_time_ms, type, data) {
    const entries = document.getElementById("sim-log-entries");
    if (!entries) return;

    const t = (sim_time_ms / 1000).toFixed(3);
    let style = SIM_LOG_EVENT_STYLES[type];
    let color, label, detail;

    if (type === "SWITCH_OP") {
        color = data.state ? "#44ff88" : "#ff8833";
        label = data.state ? "CB CLOSE" : "CB OPEN";
        detail = `${data.device_id} ph-${(data.phase || "").toUpperCase()}`;
    } else if (type === "RELAY_PICKUP") {
        color = style.color;
        label = style.label;
        detail = `${data.device_id}: ${data.label}`;
        if (data.multiple != null) {
            const tStr = data.t_op_s != null ? `, ${data.t_op_s}s` : '';
            detail += ` (${data.multiple}× ${data.curve || 'IDMT'}${tStr})`;
        }
    } else if (type === "RELAY_DROPOUT") {
        color = style.color;
        label = style.label;
        detail = `${data.device_id}: ${data.label}`;
    } else if (type === "FAULT") {
        color = style.color;
        label = style.label;
        detail = `${data.device_id}: ${data.fault_type || "?"}, Z=${data.impedance != null ? data.impedance : "?"}Ω`;
    } else if (type === "CLEAR_FAULT") {
        color = style.color;
        label = style.label;
        detail = data.device_id || "";
    } else if (type === "SIM_START") {
        color = style.color;
        label = style.label;
        detail = "topology snapshot";
    } else if (type === "SETTINGS_CHANGE") {
        color = style.color;
        label = style.label;
        detail = data.device_id || "";
    } else if (type === "AR_RECLOSE") {
        color = style.color;
        label = style.label;
        detail = `${data.device_id} shot ${data.shot}/${data.of}`;
    } else if (type === "AR_LOCKOUT") {
        color = style.color;
        label = style.label;
        detail = data.device_id || "";
    } else if (type === "BF_TRIP") {
        color = style.color;
        label = style.label;
        detail = `${data.device_id} — backup trip initiated`;
    } else {
        color = "#aaaaaa";
        label = type;
        detail = data.device_id || "";
    }

    const row = document.createElement("div");
    row.className = "sim-log-entry";
    row.innerHTML =
        `<span class="sim-log-time">T=${t}s</span>` +
        `<span class="sim-log-type" style="color:${color}">[${label}]</span>` +
        `<span class="sim-log-detail">${detail}</span>`;
    entries.appendChild(row);

    // Auto-scroll if already near bottom
    const threshold = 40;
    const nearBottom = entries.scrollHeight - entries.scrollTop - entries.clientHeight < threshold;
    if (nearBottom) entries.scrollTop = entries.scrollHeight;

    // Cap at 500 entries to avoid DOM bloat
    while (entries.children.length > 500) {
        entries.removeChild(entries.firstChild);
    }
}

function toggleSimLog() {
    simLogOpen = !simLogOpen;
    const panel = document.getElementById("sim-log-panel");
    const btn = document.getElementById("sim-log-btn");
    panel.style.display = simLogOpen ? "flex" : "none";
    if (btn) btn.innerText = simLogOpen ? "LOG ▼" : "LOG";
}

function clearSimLog() {
    const entries = document.getElementById("sim-log-entries");
    if (entries) entries.innerHTML = "";
}

/**
 * Oscillography — rolling waveform record of phase current magnitudes
 */

const OSC_EVENT_COLORS = {
    FAULT:        "#ff4444",
    RELAY_PICKUP: "#ffff44",
    SWITCH_OP:    "#ff8833",
    AR_RECLOSE:   "#44ff88",
    AR_LOCKOUT:   "#ff6600",
    BF_TRIP:      "#ff2200",
};

function showOscillography(deviceId, windowMs) {
    if (!simActive || _oscBuffer.length === 0) {
        alert("Oscillography is only available during an active simulation.");
        return;
    }
    windowMs = windowMs || 30000;

    let modal = document.getElementById("osc-modal");
    if (!modal) {
        modal = document.createElement("div");
        modal.id = "osc-modal";
        modal.className = "config-modal";
        modal.style.cssText = "width:720px; max-height:90vh;";
        document.body.appendChild(modal);
    }
    modal.style.display = "flex";
    modal.innerHTML =
        '<div class="config-modal-header">' +
            '<span>OSCILLOGRAPHY: ' + deviceId + '</span>' +
            '<span style="display:flex;gap:8px;align-items:center;">' +
                '<span onclick="detachOscillography(\'' + deviceId + '\',' + windowMs + ')" title="Open in new window" style="cursor:pointer;color:#888;font-size:13px;">⤢</span>' +
                '<span class="modal-close" onclick="this.closest(\'.config-modal\').style.display=\'none\'">[X]</span>' +
            '</span>' +
        '</div>' +
        '<div class="config-modal-body" style="padding:10px; flex-direction:column; gap:8px;">' +
            '<div style="display:flex; gap:8px; align-items:center; font-size:10px; color:#888;">' +
                '<span>WINDOW:</span>' +
                [5000,10000,30000,60000].map(w =>
                    '<button onclick="showOscillography(\'' + deviceId + '\',' + w + ')" ' +
                    'style="padding:2px 8px; background:' + (w===windowMs?'#333':'#111') + '; ' +
                    'color:' + (w===windowMs?'#fff':'#555') + '; border:1px solid #333; cursor:pointer; font-size:10px;">' +
                    (w/1000) + 's</button>'
                ).join('') +
            '</div>' +
            '<canvas id="osc-canvas" width="680" height="320" style="background:#0a0a0a; border:1px solid #333; display:block;"></canvas>' +
            '<div id="osc-legend" style="display:flex; gap:12px; font-size:10px; flex-wrap:wrap;"></div>' +
        '</div>' +
        '<div class="config-modal-footer">' +
            '<button onclick="showOscillography(\'' + deviceId + '\',' + windowMs + ')" style="flex:1; border-color:#555; color:#aaa;">REFRESH</button>' +
            '<button onclick="document.getElementById(\'osc-modal\').style.display=\'none\'" class="wiz-secondary">CLOSE</button>' +
        '</div>';

    requestAnimationFrame(() => _renderOsc(deviceId, windowMs));
}

function _renderOsc(deviceId, windowMs) {
    const canvas = document.getElementById("osc-canvas");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const W = canvas.width, H = canvas.height;
    const PAD = { top: 28, right: 20, bottom: 44, left: 62 };
    const PW = W - PAD.left - PAD.right;
    const PH = H - PAD.top  - PAD.bottom;

    // Filter buffer to window
    const tEnd   = _oscBuffer.length > 0 ? _oscBuffer[_oscBuffer.length - 1].sim_time_ms : 0;
    const tStart = tEnd - windowMs;
    const samples = _oscBuffer.filter(s => s.sim_time_ms >= tStart && s.data[deviceId]);

    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = "#0a0a0a";
    ctx.fillRect(0, 0, W, H);

    if (samples.length === 0) {
        ctx.fillStyle = "#555";
        ctx.font = "12px monospace";
        ctx.textAlign = "center";
        ctx.fillText("No current data for " + deviceId + " in this window.", W / 2, H / 2);
        return;
    }

    // Y range: 0 to max across all phases, with 10% headroom
    let yMax = 0;
    samples.forEach(s => {
        const d = s.data[deviceId];
        yMax = Math.max(yMax, d.ia, d.ib, d.ic);
    });
    yMax = yMax > 0 ? yMax * 1.12 : 10;

    const px = t  => PAD.left + (t - tStart) / windowMs * PW;
    const py = v  => PAD.top  + PH * (1 - v / yMax);

    // Grid — time
    const timeStepMs = _niceStep(windowMs / 6);
    const tGridStart = Math.ceil(tStart / timeStepMs) * timeStepMs;
    for (let t = tGridStart; t <= tEnd + 1; t += timeStepMs) {
        const x = px(t);
        ctx.strokeStyle = "#1e1e1e";
        ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(x, PAD.top); ctx.lineTo(x, PAD.top + PH); ctx.stroke();
    }
    // Grid — current
    const currStep = _niceStep(yMax / 4);
    for (let v = 0; v <= yMax + currStep; v += currStep) {
        const y = py(v);
        if (y < PAD.top || y > PAD.top + PH + 1) continue;
        ctx.strokeStyle = "#1e1e1e";
        ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(PAD.left, y); ctx.lineTo(PAD.left + PW, y); ctx.stroke();
    }

    // Border
    ctx.strokeStyle = "#444";
    ctx.lineWidth = 1;
    ctx.strokeRect(PAD.left, PAD.top, PW, PH);

    // Clip
    ctx.save();
    ctx.beginPath();
    ctx.rect(PAD.left, PAD.top, PW, PH);
    ctx.clip();

    // Event markers
    const relevantEvents = _oscEvents.filter(e => e.sim_time >= tStart && e.sim_time <= tEnd);
    relevantEvents.forEach(e => {
        const x = px(e.sim_time);
        const col = OSC_EVENT_COLORS[e.type] || "#888";
        ctx.strokeStyle = col;
        ctx.globalAlpha = 0.6;
        ctx.lineWidth = 1;
        ctx.setLineDash([4, 3]);
        ctx.beginPath(); ctx.moveTo(x, PAD.top); ctx.lineTo(x, PAD.top + PH); ctx.stroke();
        ctx.setLineDash([]);

        // Label at top
        ctx.fillStyle = col;
        ctx.font = "8px monospace";
        ctx.textAlign = "left";
        ctx.globalAlpha = 0.9;
        const shortType = { FAULT:"FLT", RELAY_PICKUP:"PKP", SWITCH_OP:"CB", AR_RECLOSE:"RCL", AR_LOCKOUT:"LKT" }[e.type] || e.type;
        ctx.fillText(shortType, x + 2, PAD.top + 10);
    });
    ctx.globalAlpha = 1;

    // Phase current traces
    const PHASE_COLORS = { ia: "#ff5555", ib: "#55ff88", ic: "#5599ff" };
    ["ia", "ib", "ic"].forEach(ph => {
        ctx.strokeStyle = PHASE_COLORS[ph];
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        let started = false;
        samples.forEach(s => {
            const x = px(s.sim_time_ms);
            const y = py(s.data[deviceId][ph]);
            if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y);
        });
        ctx.stroke();
    });

    ctx.restore();

    // X axis labels (time relative to window end)
    ctx.fillStyle = "#777";
    ctx.font = "10px monospace";
    ctx.textAlign = "center";
    for (let t = tGridStart; t <= tEnd + 1; t += timeStepMs) {
        const x = px(t);
        const relS = ((t - tEnd) / 1000).toFixed(1);
        ctx.fillText(relS + "s", x, PAD.top + PH + 16);
    }
    ctx.fillStyle = "#666";
    ctx.font = "11px monospace";
    ctx.fillText("Time (s, relative to now)", PAD.left + PW / 2, H - 6);

    // Y axis labels
    ctx.textAlign = "right";
    ctx.font = "10px monospace";
    ctx.fillStyle = "#777";
    for (let v = 0; v <= yMax + currStep * 0.5; v += currStep) {
        const y = py(v);
        if (y < PAD.top - 2 || y > PAD.top + PH + 2) continue;
        ctx.fillText(v.toFixed(v < 10 ? 1 : 0) + "A", PAD.left - 6, y + 4);
    }
    ctx.save();
    ctx.translate(13, PAD.top + PH / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.textAlign = "center";
    ctx.fillStyle = "#666";
    ctx.font = "11px monospace";
    ctx.fillText("Current RMS (A)", 0, 0);
    ctx.restore();

    // Title
    ctx.fillStyle = "#999";
    ctx.font = "bold 11px monospace";
    ctx.textAlign = "center";
    ctx.fillText("OSCILLOGRAPHY — " + deviceId, PAD.left + PW / 2, 18);

    // Legend
    const legend = document.getElementById("osc-legend");
    if (legend) {
        const phaseLabels = [
            ['#ff5555', 'Phase A (Ia)'],
            ['#55ff88', 'Phase B (Ib)'],
            ['#5599ff', 'Phase C (Ic)'],
        ];
        legend.innerHTML =
            phaseLabels.map(([c, l]) =>
                '<span style="display:flex;align-items:center;gap:4px;">' +
                '<span style="display:inline-block;width:16px;height:2px;background:' + c + ';"></span>' +
                '<span style="color:' + c + '">' + l + '</span></span>'
            ).join('') +
            '<span style="color:#444; margin-left:8px;">|</span>' +
            Object.entries(OSC_EVENT_COLORS).map(([type, c]) =>
                '<span style="display:flex;align-items:center;gap:3px;">' +
                '<span style="color:' + c + '">▎</span>' +
                '<span style="color:' + c + '">' + type.replace('_',' ') + '</span></span>'
            ).join('');
    }
}

/**
 * Render oscillography into a detached popup window's canvas.
 * Called by the popup on a 1-second timer.
 */
function _renderOscToPopup(popup, deviceId, windowMs) {
    if (!simActive || _oscBuffer.length === 0) return;
    try {
        const canvas = popup.document.getElementById("osc-canvas");
        const legend = popup.document.getElementById("osc-legend");
        if (!canvas) return;
        // Temporarily swap the DOM element references so _renderOsc uses popup's canvas
        const origGetEl = document.getElementById.bind(document);
        const _saved = { canvas: document.getElementById("osc-canvas"), legend: document.getElementById("osc-legend") };
        // Override just for this call
        const realCanvas = document.getElementById("osc-canvas");
        const realLegend = document.getElementById("osc-legend");
        // Resize canvas to popup dimensions
        canvas.width  = popup.innerWidth;
        canvas.height = popup.innerHeight
            - (popup.document.getElementById("osc-toolbar")?.offsetHeight || 42) - 26;
        // Render directly to popup's canvas using parent's buffer
        _renderOscOnCanvas(canvas, legend, deviceId, windowMs);
    } catch(e) { /* popup may have closed */ }
}

/**
 * Core oscillography renderer — accepts explicit canvas/legend elements.
 * Mirrors _renderOsc but takes element refs instead of reading from document.
 */
function _renderOscOnCanvas(canvas, legendEl, deviceId, windowMs) {
    const ctx = canvas.getContext("2d");
    const W = canvas.width, H = canvas.height;
    const PAD = { top: 28, right: 20, bottom: 44, left: 62 };
    const PW = W - PAD.left - PAD.right;
    const PH = H - PAD.top  - PAD.bottom;

    const tEnd   = _oscBuffer.length > 0 ? _oscBuffer[_oscBuffer.length - 1].sim_time_ms : 0;
    const tStart = tEnd - windowMs;
    const samples = _oscBuffer.filter(s => s.sim_time_ms >= tStart && s.data[deviceId]);

    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = "#0a0a0a";
    ctx.fillRect(0, 0, W, H);

    if (samples.length === 0) {
        ctx.fillStyle = "#555";
        ctx.font = "12px monospace";
        ctx.textAlign = "center";
        ctx.fillText("No current data for " + deviceId + " in this window.", W / 2, H / 2);
        return;
    }

    let yMax = 0;
    samples.forEach(s => { const d = s.data[deviceId]; yMax = Math.max(yMax, d.ia, d.ib, d.ic); });
    yMax = yMax > 0 ? yMax * 1.12 : 10;

    const px = t => PAD.left + (t - tStart) / windowMs * PW;
    const py = v => PAD.top  + PH * (1 - v / yMax);

    const timeStepMs = _niceStep(windowMs / 6);
    const tGridStart = Math.ceil(tStart / timeStepMs) * timeStepMs;
    for (let t = tGridStart; t <= tEnd + 1; t += timeStepMs) {
        const x = px(t);
        ctx.strokeStyle = "#1e1e1e"; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(x, PAD.top); ctx.lineTo(x, PAD.top + PH); ctx.stroke();
    }
    const currStep = _niceStep(yMax / 4);
    for (let v = 0; v <= yMax + currStep; v += currStep) {
        const y = py(v);
        if (y < PAD.top || y > PAD.top + PH + 1) continue;
        ctx.strokeStyle = "#1e1e1e"; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(PAD.left, y); ctx.lineTo(PAD.left + PW, y); ctx.stroke();
    }
    ctx.strokeStyle = "#444"; ctx.lineWidth = 1;
    ctx.strokeRect(PAD.left, PAD.top, PW, PH);

    ctx.save();
    ctx.beginPath(); ctx.rect(PAD.left, PAD.top, PW, PH); ctx.clip();

    const relevantEvents = _oscEvents.filter(e => e.sim_time >= tStart && e.sim_time <= tEnd);
    relevantEvents.forEach(e => {
        const x = px(e.sim_time);
        const col = OSC_EVENT_COLORS[e.type] || "#888";
        ctx.strokeStyle = col; ctx.globalAlpha = 0.6; ctx.lineWidth = 1;
        ctx.setLineDash([4, 3]);
        ctx.beginPath(); ctx.moveTo(x, PAD.top); ctx.lineTo(x, PAD.top + PH); ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = col; ctx.font = "8px monospace"; ctx.textAlign = "left"; ctx.globalAlpha = 0.9;
        const shortType = { FAULT:"FLT", RELAY_PICKUP:"PKP", SWITCH_OP:"CB", AR_RECLOSE:"RCL", AR_LOCKOUT:"LKT" }[e.type] || e.type;
        ctx.fillText(shortType, x + 2, PAD.top + 10);
    });
    ctx.globalAlpha = 1;

    const PHASE_COLORS = { ia: "#ff5555", ib: "#55ff88", ic: "#5599ff" };
    ["ia", "ib", "ic"].forEach(ph => {
        ctx.strokeStyle = PHASE_COLORS[ph]; ctx.lineWidth = 1.5;
        ctx.beginPath(); let started = false;
        samples.forEach(s => {
            const x = px(s.sim_time_ms), y = py(s.data[deviceId][ph]);
            if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y);
        });
        ctx.stroke();
    });
    ctx.restore();

    ctx.fillStyle = "#777"; ctx.font = "10px monospace"; ctx.textAlign = "center";
    for (let t = tGridStart; t <= tEnd + 1; t += timeStepMs) {
        const x = px(t), relS = ((t - tEnd) / 1000).toFixed(1);
        ctx.fillText(relS + "s", x, PAD.top + PH + 16);
    }
    ctx.fillStyle = "#666"; ctx.font = "11px monospace";
    ctx.fillText("Time (s, relative to now)", PAD.left + PW / 2, H - 6);

    ctx.textAlign = "right"; ctx.font = "10px monospace"; ctx.fillStyle = "#777";
    for (let v = 0; v <= yMax + currStep * 0.5; v += currStep) {
        const y = py(v);
        if (y < PAD.top - 2 || y > PAD.top + PH + 2) continue;
        ctx.fillText(v.toFixed(v < 10 ? 1 : 0) + "A", PAD.left - 6, y + 4);
    }
    ctx.save(); ctx.translate(13, PAD.top + PH / 2); ctx.rotate(-Math.PI / 2);
    ctx.textAlign = "center"; ctx.fillStyle = "#666"; ctx.font = "11px monospace";
    ctx.fillText("Current RMS (A)", 0, 0); ctx.restore();

    ctx.fillStyle = "#999"; ctx.font = "bold 11px monospace"; ctx.textAlign = "center";
    ctx.fillText("OSCILLOGRAPHY — " + deviceId, PAD.left + PW / 2, 18);

    if (legendEl) {
        legendEl.innerHTML =
            [["#ff5555","Phase A (Ia)"],["#55ff88","Phase B (Ib)"],["#5599ff","Phase C (Ic)"]].map(
                ([c,l]) => '<span style="display:flex;align-items:center;gap:4px;">' +
                    '<span style="display:inline-block;width:16px;height:2px;background:'+c+';"></span>' +
                    '<span style="color:'+c+'">'+l+'</span></span>'
            ).join("") +
            '<span style="color:#444;margin-left:8px;">|</span>' +
            Object.entries(OSC_EVENT_COLORS).map(([type,c]) =>
                '<span style="display:flex;align-items:center;gap:3px;">' +
                '<span style="color:'+c+'">▎</span>' +
                '<span style="color:'+c+'">'+type.replace("_"," ")+'</span></span>'
            ).join("");
    }
}

function _niceStep(raw) {
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const norm = raw / mag;
    let nice;
    if (norm < 1.5)      nice = 1;
    else if (norm < 3.5) nice = 2;
    else if (norm < 7.5) nice = 5;
    else                 nice = 10;
    return nice * mag;
}

/**
 * Open the oscillography chart in a standalone popup window.
 * The popup holds its own canvas and auto-refreshes from the parent's buffer.
 */
function detachOscillography(deviceId, windowMs) {
    const key = "_oscPopup_" + deviceId;
    if (window[key] && !window[key].closed) { window[key].focus(); return; }

    const w = 760, h = 520;
    const left = Math.round(window.screenX + window.outerWidth / 2 - w / 2);
    const popup = window.open("", "osc_" + deviceId,
        "width=" + w + ",height=" + h + ",resizable=yes,scrollbars=no,left=" + left + ",top=80");
    if (!popup) { alert("Popup blocked — please allow popups for this site."); return; }
    window[key] = popup;

    const styleLinks = Array.from(document.querySelectorAll("link[rel=stylesheet]"))
        .map(l => '<link rel="stylesheet" href="' + l.href + '">').join("\n");

    popup.document.write(`<!doctype html><html><head>
        <meta charset="UTF-8">
        <title>OSCILLOGRAPHY: ${deviceId}</title>
        ${styleLinks}
        <style>body{overflow:hidden;background:#060606;margin:0;font-family:monospace;}
        #osc-toolbar{background:#111;border-bottom:1px solid #2a2a2a;padding:5px 10px;display:flex;gap:8px;align-items:center;font-size:10px;color:#888;}
        </style>
    </head><body>
        <div id="osc-toolbar">
            <span style="color:#aaa;letter-spacing:1px;">OSCILLOGRAPHY — ${deviceId}</span>
            <span style="margin-left:6px;">WINDOW:</span>
            ${[5000,10000,30000,60000].map(w =>
                '<button onclick="setWindow('+w+')" id="wbtn'+w+'" style="padding:2px 8px;background:'+(w===windowMs?'#333':'#111')+';color:'+(w===windowMs?'#fff':'#555')+';border:1px solid #333;cursor:pointer;font-size:10px;">'+(w/1000)+'s</button>'
            ).join("")}
            <button onclick="doRefresh()" style="margin-left:8px;padding:2px 8px;background:#111;color:#3af;border:1px solid #3af;cursor:pointer;font-size:10px;">REFRESH</button>
            <label style="margin-left:8px;display:flex;align-items:center;gap:4px;">
                <input type="checkbox" id="auto-refresh" checked>AUTO
            </label>
        </div>
        <canvas id="osc-canvas" style="display:block;"></canvas>
        <div id="osc-legend" style="padding:4px 10px;display:flex;gap:12px;font-size:10px;flex-wrap:wrap;min-height:22px;background:#060606;"></div>
        <script>
        let _windowMs = ${windowMs};
        function setWindow(w) {
            _windowMs = w;
            [5000,10000,30000,60000].forEach(v => {
                const b = document.getElementById("wbtn"+v);
                if (b) { b.style.background = v===w?"#333":"#111"; b.style.color = v===w?"#fff":"#555"; }
            });
            doRefresh();
        }
        function doRefresh() {
            if (window.opener && !window.opener.closed) {
                window.opener._renderOscToPopup(window, "${deviceId}", _windowMs);
            }
        }
        function resizeCanvas() {
            const cv = document.getElementById("osc-canvas");
            cv.width  = window.innerWidth;
            cv.height = window.innerHeight - document.getElementById("osc-toolbar").offsetHeight - 26;
        }
        window.addEventListener("resize", () => { resizeCanvas(); doRefresh(); });
        resizeCanvas();
        doRefresh();
        setInterval(() => {
            if (document.getElementById("auto-refresh")?.checked) doRefresh();
        }, 1000);
        <\/script>
    </body></html>`);
    popup.document.close();
    // Hide main modal
    const modal = document.getElementById("osc-modal");
    if (modal) modal.style.display = "none";
}
