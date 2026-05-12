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
            // Hide log panel
            if (simLogOpen) toggleSimLog();
            // Trigger a refresh of the real data
            refreshData();
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
    
    if (!simPaused) {
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
        }
    }

    render3LD(simData);

    Object.keys(openWindows).forEach((id) => {
        const node = simData.nodes.find((n) => n.id === id);
        if (node) updateWindow(id, node);
    });
}

function updateSimUI() {
    let date = new Date(simTime);
    let ms = String(Math.floor(simTime % 1000)).padStart(3, '0');
    let timeStr = date.toISOString().substr(11, 8) + "." + ms;
    document.getElementById("sim-clock").innerText = timeStr;
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
            <span class="modal-close" onclick="this.closest('.config-modal').style.display='none'">[X]</span>
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
        persistence: document.getElementById("fault-persistence").value,
        duration: parseFloat(document.getElementById("fault-duration").value),
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
    SIM_START:     { color: "#ffffff", label: "SIM START" },
    FAULT:         { color: "#ff4444", label: "FAULT" },
    CLEAR_FAULT:   { color: "#44ffff", label: "CLR FAULT" },
    RELAY_PICKUP:  { color: "#ffff44", label: "PICKUP" },
    RELAY_DROPOUT: { color: "#777777", label: "DROPOUT" },
    SWITCH_OP:     null, // handled inline based on state
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
