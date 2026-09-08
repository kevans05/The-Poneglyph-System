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

function _siteEsc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, c => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
}

function _renderSiteList() {
    const body = document.getElementById("site-selector-body");
    body.innerHTML = '<div style="color:#888; padding:12px;">Loading sites...</div>';
    document.getElementById("site-bulk-sync-btn").style.display = "none";

    const hubOn = typeof PoneglyphHub !== "undefined" && PoneglyphHub.connected();
    Promise.all([
        fetchSites(),
        hubOn ? PoneglyphHub.browseSubstations().catch(() => []) : Promise.resolve(null),
    ]).then(([{ sites }, hubSubs]) => {
        sites = sites || [];
        if (sites.length === 0 && !hubSubs) {
            body.innerHTML = `
                <div style="color:#666; padding:20px; text-align:center; font-size:11px;">
                    NO SITES FOUND<br>
                    <span style="color:#444;">Create a new site to begin.</span>
                </div>`;
            return;
        }

        let html = sites.map(s => {
            const date = s.last_epoch ? new Date(s.last_epoch * 1000).toLocaleDateString() : '—';
            const station = _siteEsc(s.station);

            let syncLine;
            if (s.hub_linked) {
                const color = s.hub_ahead > 0 ? "#d8a24a" : "#3fdc8f";
                const label = s.hub_ahead > 0
                    ? `☁ ${s.hub_ahead} unpushed change${s.hub_ahead !== 1 ? 's' : ''}`
                    : "☁ synced";
                syncLine = `
                    <span style="color:${color};">${label}</span>
                    <span style="color:#333;">·</span>
                    <span style="color:#444;">${_siteEsc(s.hub_substation_id)}</span>
                    <button data-manage="${station}" class="site-sync-btn"
                        style="margin-left:8px; background:none; border:1px solid #222; color:#3af;
                               font-family:inherit; font-size:9px; padding:1px 7px; cursor:pointer;">MANAGE</button>`;
            } else if (hubOn) {
                syncLine = `
                    <span style="color:#444;">not synced to hub</span>
                    <button data-link="${station}" class="site-sync-btn"
                        style="margin-left:8px; background:none; border:1px solid #1f6b47; color:#3fdc8f;
                               font-family:inherit; font-size:9px; padding:1px 7px; cursor:pointer;">☁ LINK TO HUB</button>`;
            } else {
                syncLine = `<span style="color:#333;">not synced to hub</span>`;
            }

            return `
                <div class="site-row" onclick="_selectSite('${station}', this)">
                    <div class="site-row-name">${s.station}</div>
                    <div class="site-row-meta">
                        ${s.description ? `<span style="color:#aaa;">${_siteEsc(s.description)}</span> &nbsp;` : ''}
                        <span style="color:#555;">${s.session_count} session${s.session_count !== 1 ? 's' : ''}</span>
                        &nbsp;&bull;&nbsp;
                        <span style="color:#555;">${s.snapshot_count} snapshot${s.snapshot_count !== 1 ? 's' : ''}</span>
                        &nbsp;&bull;&nbsp;
                        <span style="color:#444;">last: ${date}</span>
                    </div>
                    <div class="site-row-meta" style="margin-top:4px;">${syncLine}</div>
                </div>`;
        }).join('');

        // Substations that exist on the hub but have no matching local site
        // (matched by station code or number_code against the substation id).
        if (hubSubs) {
            const known = new Set();
            sites.forEach(s => {
                if (s.station) known.add(s.station.toUpperCase());
                if (s.number_code) known.add(String(s.number_code).toUpperCase());
            });
            const notLocal = hubSubs.filter(sub => !known.has(String(sub.id).toUpperCase()));
            if (notLocal.length) {
                html += `
                    <div style="padding:10px 14px 4px; font-size:9px; color:#3fdc8f; letter-spacing:1px;
                                border-top:1px solid #1a1a1a; margin-top:6px;">
                        ☁ ON THE HUB — NOT ON THIS MACHINE
                    </div>`;
                html += notLocal.map(sub => `
                    <label class="site-row" style="display:flex; align-items:center; gap:10px; cursor:pointer;">
                        <input type="checkbox" class="site-pull-check" value="${_siteEsc(sub.id)}"
                            data-name="${_siteEsc(sub.name || sub.id)}" onclick="event.stopPropagation()" />
                        <div style="flex:1;">
                            <div class="site-row-name">${_siteEsc(sub.id)}
                                <span style="color:#555; font-size:10px; font-weight:normal;">${_siteEsc(sub.name || '')}</span></div>
                            <div class="site-row-meta">${_siteEsc(sub.summary || '')}
                                &nbsp;&bull;&nbsp; ${sub.version_count} version${sub.version_count !== 1 ? 's' : ''}</div>
                        </div>
                    </label>`).join('');
                html += `
                    <div style="padding:10px 14px;">
                        <button id="site-pull-selected-btn" onclick="_siteBulkPullNew()"
                            style="background:#001a0a; border:1px solid #0f6; color:#0f6; font-family:inherit;
                                   font-size:10px; padding:6px 14px; cursor:pointer; letter-spacing:1px;" disabled>
                            ⇩ PULL SELECTED (0) →
                        </button>
                    </div>`;
            }
        }

        body.innerHTML = html;

        const anyLinked = sites.some(s => s.hub_linked);
        document.getElementById("site-bulk-sync-btn").style.display = anyLinked ? "" : "none";

        body.querySelectorAll(".site-sync-btn").forEach(b => {
            b.addEventListener("click", (e) => {
                e.stopPropagation();
                _siteGoManageSync(b.dataset.manage || b.dataset.link);
            });
        });
        body.querySelectorAll(".site-pull-check").forEach(cb => {
            cb.addEventListener("change", _siteUpdatePullSelectedCount);
        });
    }).catch(() => {
        body.innerHTML = '<div style="color:#f44; padding:12px;">Failed to load sites.</div>';
    });
}

function _siteUpdatePullSelectedCount() {
    const n = document.querySelectorAll(".site-pull-check:checked").length;
    const btn = document.getElementById("site-pull-selected-btn");
    if (!btn) return;
    btn.disabled = n === 0;
    btn.textContent = `⇩ PULL SELECTED (${n}) →`;
}

/** Load a site (if needed) then hand off to the full sync panel — link,
 *  pull, push, conflict resolution all live there. */
function _siteGoManageSync(station) {
    fetch("/api/sites/load", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ station }),
    }).then(r => r.json()).then(resp => {
        if (resp.error) { alert("Error: " + resp.error); return; }
        _activeSiteInfo = resp.info;
        _updateSiteIndicator(station);
        hideSiteSelector();
        refreshData().then(() => {
            if (typeof zoomToFit === "function") zoomToFit(0);
            if (typeof showHubSyncPanel === "function") showHubSyncPanel();
        });
    }).catch(() => alert("Network error loading site."));
}

/** Create a local site for each checked hub substation and attach it. */
function _siteBulkPullNew() {
    const checks = Array.from(document.querySelectorAll(".site-pull-check:checked"));
    if (!checks.length) return;
    const btn = document.getElementById("site-pull-selected-btn");
    const creds = PoneglyphHub.creds();
    let ok = 0, fail = 0;

    const next = (i) => {
        if (i >= checks.length) {
            btn.textContent = `✓ pulled ${ok}${fail ? `, ${fail} failed` : ""}`;
            setTimeout(_renderSiteList, 900);
            return;
        }
        const cb = checks[i];
        const subId = cb.value;
        const name = cb.dataset.name || subId;
        // Station codes are constrained to [A-Z0-9_-] (same rule the "NEW
        // SITE" form applies); a hub substation id may not already fit that.
        const station = subId.toUpperCase().replace(/[^A-Z0-9_-]/g, "") || ("SUB" + i);
        btn.disabled = true;
        btn.textContent = `PULLING ${i + 1}/${checks.length}…`;

        fetch("/api/sites/create", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ station, site_name: name, number_code: subId }),
        }).then(r => r.json()).then(createResp => {
            if (createResp.error) throw new Error(createResp.error);
            return fetch("/api/sites/load", {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ station }),
            }).then(r => r.json());
        }).then(loadResp => {
            if (loadResp.error) throw new Error(loadResp.error);
            return fetch("/api/hub-sync/link", {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ ...creds, mode: "attach", substation_id: subId }),
            }).then(r => r.json());
        }).then(linkResp => {
            if (linkResp.error) throw new Error(linkResp.error);
            ok++;
        }).catch(() => { fail++; }).then(() => next(i + 1));
    };
    next(0);
}

/** Pull (and, if that's clean, push) every locally hub-linked site in turn. */
function _siteBulkSyncAll() {
    const btn = document.getElementById("site-bulk-sync-btn");
    const creds = PoneglyphHub.creds();
    fetchSites().then(({ sites }) => {
        const linked = (sites || []).filter(s => s.hub_linked);
        if (!linked.length) return;
        let results = [];

        const next = (i) => {
            if (i >= linked.length) {
                const conflicts = results.filter(r => r === "conflicts").length;
                btn.textContent = conflicts
                    ? `☁ done — ${conflicts} need review`
                    : "☁ all synced";
                setTimeout(() => { btn.textContent = "☁ SYNC ALL LINKED SITES"; _renderSiteList(); }, 1600);
                return;
            }
            const station = linked[i].station;
            btn.disabled = true;
            btn.textContent = `SYNCING ${i + 1}/${linked.length}: ${station}…`;

            fetch("/api/sites/load", {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ station }),
            }).then(() => fetch("/api/hub-sync/pull", {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify(creds),
            }).then(r => r.json())).then(pullResp => {
                if (pullResp.conflicts && pullResp.conflicts.length) {
                    results.push("conflicts");
                    return;
                }
                results.push("ok");
                return fetch("/api/hub-sync/push", {
                    method: "POST", headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(creds),
                }).then(r => r.json());
            }).catch(() => { results.push("error"); }).then(() => {
                btn.disabled = false;
                next(i + 1);
            });
        };
        next(0);
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
    btn.textContent = "LOADING SITE...";
    btn.disabled = true;

    loadSite(station).then(resp => {
        if (resp.error) {
            btn.textContent = "LOAD SITE";
            btn.disabled = false;
            btn.style.opacity = "1";
            alert("Error: " + resp.error);
            return;
        }
        _activeSiteInfo = resp.info;
        _updateSiteIndicator(station);
        hideSiteSelector();
        refreshData().then(() => {
            if (typeof zoomToFit === "function") zoomToFit(0);
        });
        if (typeof _onSiteLoaded === "function") _onSiteLoaded(station);
    }).catch(() => {
        btn.textContent = "LOAD SITE";
        btn.disabled = false;
        btn.style.opacity = "1";
        alert("Network error loading site.");
    });
}

/** Show the create-new-site form inside the modal. */
function _showCreateForm() {
    const body = document.getElementById("site-selector-body");
    body.innerHTML = `
        <div style="padding:16px; display:flex; flex-direction:column; gap:11px; overflow-y:auto; max-height:60vh;">
            <div style="font-size:10px; color:#0f0; letter-spacing:1px; border-bottom:1px solid #1a1a1a; padding-bottom:8px;">
                NEW SITE
            </div>

            <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px;">
                <div style="display:flex; flex-direction:column; gap:4px;">
                    <label style="font-size:10px; color:#888;">SITE CODE <span style="color:#f00;">*</span></label>
                    <input id="new-site-station" type="text" placeholder="e.g. TMW"
                        style="background:#111; border:1px solid #333; color:#eee; padding:6px 8px;
                               font-family:inherit; font-size:11px; letter-spacing:2px; width:100%; box-sizing:border-box;"
                        oninput="this.value = this.value.toUpperCase().replace(/[^A-Z0-9_-]/g,'')" />
                </div>
                <div style="display:flex; flex-direction:column; gap:4px;">
                    <label style="font-size:10px; color:#888;">SITE ID <span style="color:#f00;">*</span></label>
                    <input id="new-site-number" type="text" placeholder="e.g. 001"
                        style="background:#111; border:1px solid #333; color:#eee; padding:6px 8px;
                               font-family:inherit; font-size:11px; width:100%; box-sizing:border-box;" />
                </div>
            </div>

            <div style="display:flex; flex-direction:column; gap:4px;">
                <label style="font-size:10px; color:#888;">SITE NAME <span style="color:#f00;">*</span></label>
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
                    <span style="color:#444; display:block;">Copy current site topology as the initial snapshot</span>
                </label>
            </div>

            <div style="display:flex; gap:8px;">
                <button onclick="_submitCreateSite()"
                    style="flex:1; background:#001a00; border:1px solid #0f0; color:#0f0;
                           font-family:inherit; font-size:10px; padding:8px; cursor:pointer; letter-spacing:1px;">
                    CREATE SITE
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
    }).catch(() => alert("Network error creating site."));
}

function _updateSiteIndicator(station) {
    const indicator = document.getElementById("active-site-indicator");
    if (indicator) {
        indicator.textContent = station ? `SITE: ${station}` : "NO SITE";
        indicator.style.color = station ? "#0f0" : "#f00";
        indicator.style.borderColor = station ? "#0f0" : "#f00";
    }
}

