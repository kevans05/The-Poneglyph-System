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

function startSim() {
    if (simActive) return;
    
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
            simPaused = true;
            lastFrameId = -1;
            frameQueue = [];
            document.getElementById("sim-bar").style.display = "flex";
            document.body.classList.add("sim-mode-active");
            
            // Start polling and playback loops
            simPoll();
            requestAnimationFrame(simPlaybackLoop);
        });
}

function stopSim() {
    fetch("/api/sim/stop", { method: "POST" })
        .then(() => {
            simActive = false;
            document.getElementById("sim-bar").style.display = "none";
            document.body.classList.remove("sim-mode-active");
            simData = null;
            // No, refreshData is disabled if simActive is true. 
            // So now that it's false, we can refresh.
            // But we need to call it manually.
            location.reload(); // Simplest way to exit sim mode cleanly
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
