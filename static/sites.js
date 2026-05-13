"use strict";

/**
 * SCADA Pro — Site Selector
 * Manages site listing, creation, and activation.
 */

let _activeSiteInfo = null;

function getActiveSiteInfo() { return _activeSiteInfo; }

let _onSiteLoaded = null;

/** Called by splash.js after init — shows the site selector overlay. */
function showSiteSelector({ onLoaded } = {}) {
    _onSiteLoaded = onLoaded || null;
    const modal = document.getElementById("site-selector-modal");
    modal.style.display = "flex";
    _renderSiteList();
}

function hideSiteSelector() {
    document.getElementById("site-selector-modal").style.display = "none";
}

function _renderSiteList() {
    const body = document.getElementById("site-selector-body");
    body.innerHTML = '<div style="color:#888; padding:12px;">Loading docks...</div>';

    fetchSites().then(({ sites }) => {
        if (!sites || sites.length === 0) {
            body.innerHTML = `
                <div style="color:#666; padding:20px; text-align:center; font-size:11px;">
                    NO DOCKS FOUND<br>
                    <span style="color:#444;">Create a new Dock to begin.</span>
                </div>`;
            return;
        }

        let html = '';
        sites.forEach(s => {
            const date = s.last_epoch
                ? new Date(s.last_epoch * 1000).toLocaleDateString()
                : '—';
            const station = s.station.replace(/'/g, "\\'");
            html += `
                <div class="site-row" onclick="_selectSite('${station}', this)">
                    <div class="site-row-name">${s.station}</div>
                    <div class="site-row-meta">
                        ${s.description ? `<span style="color:#aaa;">${s.description}</span> &nbsp;` : ''}
                        <span style="color:#555;">${s.session_count} session${s.session_count !== 1 ? 's' : ''}</span>
                        &nbsp;&bull;&nbsp;
                        <span style="color:#555;">${s.snapshot_count} snapshot${s.snapshot_count !== 1 ? 's' : ''}</span>
                        &nbsp;&bull;&nbsp;
                        <span style="color:#444;">last: ${date}</span>
                    </div>
                </div>`;
        });
        body.innerHTML = html;
    }).catch(() => {
        body.innerHTML = '<div style="color:#f44; padding:12px;">Failed to load docks.</div>';
    });
}

function _selectSite(station, el) {
    document.querySelectorAll(".site-row").forEach(r => r.classList.remove("site-row-active"));
    el.classList.add("site-row-active");

    const btn = document.getElementById("site-load-btn");
    btn.disabled = false;
    btn.style.opacity = "1";
    btn.onclick = () => _loadSite(station);
}

function _loadSite(station) {
    const btn = document.getElementById("site-load-btn");
    btn.textContent = "LOADING DOCK...";
    btn.disabled = true;

    loadSite(station).then(resp => {
        if (resp.error) {
            btn.textContent = "LOAD DOCK";
            btn.disabled = false;
            btn.style.opacity = "1";
            alert("Error: " + resp.error);
            return;
        }
        _activeSiteInfo = resp.info;
        _updateSiteIndicator(station);
        hideSiteSelector();
        refreshData();
        if (typeof _onSiteLoaded === "function") _onSiteLoaded(station);
    }).catch(() => {
        btn.textContent = "LOAD DOCK";
        btn.disabled = false;
        btn.style.opacity = "1";
        alert("Network error loading dock.");
    });
}

/** Show the create-new-site form inside the modal. */
function _showCreateForm() {
    const body = document.getElementById("site-selector-body");
    body.innerHTML = `
        <div style="padding:16px; display:flex; flex-direction:column; gap:11px; overflow-y:auto; max-height:60vh;">
            <div style="font-size:10px; color:#0f0; letter-spacing:1px; border-bottom:1px solid #1a1a1a; padding-bottom:8px;">
                NEW DOCK
            </div>

            <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px;">
                <div style="display:flex; flex-direction:column; gap:4px;">
                    <label style="font-size:10px; color:#888;">DOCK CODE <span style="color:#f00;">*</span></label>
                    <input id="new-site-station" type="text" placeholder="e.g. TMW"
                        style="background:#111; border:1px solid #333; color:#eee; padding:6px 8px;
                               font-family:inherit; font-size:11px; letter-spacing:2px; width:100%; box-sizing:border-box;"
                        oninput="this.value = this.value.toUpperCase().replace(/[^A-Z0-9_-]/g,'')" />
                </div>
                <div style="display:flex; flex-direction:column; gap:4px;">
                    <label style="font-size:10px; color:#888;">DOCK ID <span style="color:#f00;">*</span></label>
                    <input id="new-site-number" type="text" placeholder="e.g. 001"
                        style="background:#111; border:1px solid #333; color:#eee; padding:6px 8px;
                               font-family:inherit; font-size:11px; width:100%; box-sizing:border-box;" />
                </div>
            </div>

            <div style="display:flex; flex-direction:column; gap:4px;">
                <label style="font-size:10px; color:#888;">DOCK NAME <span style="color:#f00;">*</span></label>
                <input id="new-site-name" type="text" placeholder="e.g. Tom's Workers"
                    style="background:#111; border:1px solid #333; color:#eee; padding:6px 8px;
                           font-family:inherit; font-size:11px; width:100%; box-sizing:border-box;" />
            </div>

            <div style="display:flex; flex-direction:column; gap:4px;">
                <label style="font-size:10px; color:#888;">DESCRIPTION</label>
                <input id="new-site-desc" type="text" placeholder="Optional notes"
                    style="background:#111; border:1px solid #333; color:#eee; padding:6px 8px;
                           font-family:inherit; font-size:11px; width:100%; box-sizing:border-box;" />
            </div>

            <div style="display:flex; flex-direction:column; gap:6px;">
                <label style="font-size:10px; color:#888;">GPS LOCATION</label>
                <div style="display:flex; gap:8px; align-items:center;">
                    <input id="new-site-lat" type="number" step="any" placeholder="Latitude"
                        style="flex:1; background:#111; border:1px solid #333; color:#eee; padding:6px 8px;
                               font-family:inherit; font-size:11px; box-sizing:border-box;" />
                    <input id="new-site-lon" type="number" step="any" placeholder="Longitude"
                        style="flex:1; background:#111; border:1px solid #333; color:#eee; padding:6px 8px;
                               font-family:inherit; font-size:11px; box-sizing:border-box;" />
                    <button onclick="_useMyLocation()"
                        style="white-space:nowrap; background:#0a0a0a; border:1px solid #0af; color:#0af;
                               font-family:inherit; font-size:9px; padding:6px 10px; cursor:pointer; letter-spacing:1px;">
                        &#9654; USE MY LOCATION
                    </button>
                </div>
                <div id="gps-status" style="font-size:9px; color:#444; height:14px;"></div>
            </div>

            <div style="display:flex; align-items:center; gap:8px; padding:8px; background:#0a0a0a; border:1px solid #1a1a1a;">
                <input id="new-site-seed" type="checkbox" style="margin:0;" />
                <label for="new-site-seed" style="font-size:10px; color:#888; cursor:pointer;">
                    SEED WITH CURRENT TOPOLOGY
                    <span style="color:#444; display:block;">Copy current dock topology as the initial snapshot</span>
                </label>
            </div>

            <div style="display:flex; gap:8px;">
                <button onclick="_submitCreateSite()"
                    style="flex:1; background:#001a00; border:1px solid #0f0; color:#0f0;
                           font-family:inherit; font-size:10px; padding:8px; cursor:pointer; letter-spacing:1px;">
                    CREATE DOCK
                </button>
                <button onclick="_renderSiteList()"
                    style="background:#0a0a0a; border:1px solid #333; color:#888;
                           font-family:inherit; font-size:10px; padding:8px; cursor:pointer;">
                    BACK
                </button>
            </div>
        </div>`;

    document.getElementById("site-load-btn").style.display = "none";
    document.getElementById("new-site-station").focus();
}

function _useMyLocation() {
    const status = document.getElementById("gps-status");
    if (!navigator.geolocation) {
        status.textContent = "Geolocation not supported by this browser.";
        status.style.color = "#f44";
        return;
    }
    status.textContent = "Acquiring GPS fix...";
    status.style.color = "#0af";
    navigator.geolocation.getCurrentPosition(
        pos => {
            document.getElementById("new-site-lat").value = pos.coords.latitude.toFixed(6);
            document.getElementById("new-site-lon").value = pos.coords.longitude.toFixed(6);
            const acc = pos.coords.accuracy ? ` ±${Math.round(pos.coords.accuracy)}m` : "";
            status.textContent = `Location acquired${acc}`;
            status.style.color = "#0f0";
        },
        err => {
            status.textContent = "GPS error: " + err.message;
            status.style.color = "#f44";
        },
        { enableHighAccuracy: true, timeout: 10000 }
    );
}

function _submitCreateSite() {
    const station    = (document.getElementById("new-site-station").value || "").trim().toUpperCase();
    const site_name  = (document.getElementById("new-site-name").value   || "").trim();
    const number     = (document.getElementById("new-site-number").value  || "").trim();
    const desc       = (document.getElementById("new-site-desc").value    || "").trim();
    const latRaw     = document.getElementById("new-site-lat").value;
    const lonRaw     = document.getElementById("new-site-lon").value;
    const seed       = document.getElementById("new-site-seed").checked;

    // Validate required fields
    let valid = true;
    [["new-site-station", station], ["new-site-name", site_name],
     ["new-site-number", number]].forEach(([id, val]) => {
        const el = document.getElementById(id);
        if (!val) { el.style.borderColor = "#f00"; valid = false; }
        else el.style.borderColor = "#333";
    });
    if (!valid) return;

    const payload = {
        station,
        site_name,
        number_code: number,
        description: desc,
        seed_current: seed,
        gps_lat: latRaw !== "" ? parseFloat(latRaw) : null,
        gps_lon: lonRaw !== "" ? parseFloat(lonRaw) : null,
    };

    fetch("/api/sites/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
    }).then(r => r.json()).then(resp => {
        if (resp.error) { alert("Error: " + resp.error); return; }
        document.getElementById("site-load-btn").style.display = "";
        _loadSite(station);
    }).catch(() => alert("Network error creating dock."));
}

function _updateSiteIndicator(station) {
    const indicator = document.getElementById("active-site-indicator");
    if (indicator) {
        indicator.textContent = station ? `DOCK: ${station}` : "NO DOCK";
        indicator.style.color = station ? "#0f0" : "#f00";
        indicator.style.borderColor = station ? "#0f0" : "#f00";
    }
}

